import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Issue } from '../types'
import { ago, bar, clip, issueRefs, repoOf } from './parse'

const PANE = 'issue-board'
const KEEP = 20
const LOOK = {
  work: { icon: '●', label: 'IN PROGRESS', color: 'yellow' },
  pr: { icon: '◐', label: 'PULL REQUEST', color: 'cyan' },
  done: { icon: '✓', label: 'DONE', color: 'green' },
} as const
const FRESH_MS = 30_000

const issues = atom({ plugin: 'issue-board', key: 'issues' } as const, [], { shape: 'issues-1' })

const line = (i: Issue) => `#${i.n} ${i.title || '(no title)'}${i.branch ? ` [${i.branch}]` : ''}`

// A top-level function: the validator follows $ only into functions declared here.
async function save($: EngineInterface, repo: string, list: Issue[]) {
  if (repo !== '') await $.store.set(`issues:${repo}`, list)
}

export const register: Register = on => {
  let repo = ''
  let resume = ''

  on('session.start', async ($, e, next) => {
    const remote = await $.process.run(['git', 'remote', 'get-url', 'origin']).catch(() => undefined)
    repo = remote?.exitCode === 0 ? (repoOf(remote.stdout) ?? '') : ''
    const stored = repo === '' ? [] : (((await $.store.get(`issues:${repo}`)) as Issue[] | undefined) ?? [])
    const open = stored.filter(i => i.kind !== 'done')
    resume = open.length === 0 ? '' : `Issues in progress in ${repo} when the last session ended:\n${open.map(line).join('\n')}`
    await update($, issues, () => stored)
    await $.command.register({ name: 'issues', description: 'Show the issues in progress; "/issues clear" empties the list' })
    if (open.length > 0) void $.ui.open({ id: PANE, title: 'Issues' })

    return next(e)
  })

  on('prompt.compose', async ($, e, next) => {
    const out = await next(e)
    if (resume === '') return out

    return {
      sections: [
        ...out.sections,
        {
          id: 'issue-board:resume',
          scope: 'session',
          text: `${resume}\nOffer to continue them; check each one's state on GitHub first. If /dynamia:memory is available, a handoff note can keep the plan.`,
        },
      ],
    }
  })

  on('command.run', { command: 'issues' }, async ($, e) => {
    if (e.args.trim() === 'clear') {
      await update($, issues, () => [])
      await save($, repo, [])
      return { text: 'Issue list cleared.' }
    }
    const list = await read($, issues)
    void $.ui.open({ id: PANE, title: 'Issues' })

    return { text: list.length === 0 ? 'No issues tracked yet.' : list.map(line).join('\n') }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    const refs = issueRefs(e.command)
    if (refs.length === 0) return ran

    const now = await $.clock.now()
    const known = await read($, issues)
    for (const ref of refs) {
      const title =
        known.find(i => i.n === ref.n)?.title ||
        (await $.process
          .run(['gh', 'issue', 'view', String(ref.n), '--json', 'title', '-q', '.title'], { timeoutMs: 10_000 })
          .then(r => (r.exitCode === 0 ? r.stdout.trim() : ''))
          .catch(() => ''))
      await update($, issues, list => {
        const old = list.find(i => i.n === ref.n)
        const one: Issue = { n: ref.n, kind: ref.kind, title, branch: ref.branch ?? old?.branch ?? '', at: now }

        return [...list.filter(i => i.n !== ref.n), one].slice(-KEEP)
      })
    }
    await save($, repo, await read($, issues))
    void $.ui.open({ id: PANE, title: 'Issues' })

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const list = await read($, issues)
    const now = await $.clock.now()
    const rows = Math.max(6, e.viewport?.rows ?? 12)
    const count = { work: 0, pr: 0, done: 0 }
    for (const i of list) count[i.kind] += 1
    const head = ` ◆ ISSUES · ${repo || 'no repo'} `

    // Rows left for issues: the header, the bar, one gap and the footer are fixed.
    let room = rows - 5
    const groups = (['work', 'pr', 'done'] as const).map(kind => ({
      kind,
      items: list.filter(i => i.kind === kind).sort((a, b) => b.at - a.at),
    }))

    return (
      <Box flexDirection="column">
        <Box backgroundColor="magenta">
          <Text bold color="black" wrap="truncate-end">
            {head}
          </Text>
        </Box>
        <Box>
          <Text color="green">{bar(count.done, list.length, 12)}</Text>
          <Text dimColor>{` ${count.done}/${list.length} done  `}</Text>
          <Text color="yellow">{`● ${count.work} `}</Text>
          <Text color="cyan">{`◐ ${count.pr}`}</Text>
        </Box>
        {list.length === 0 && <Text dimColor>{'\n  Waiting for the agent to touch an issue…'}</Text>}
        {groups.map(({ kind, items }) => {
          if (items.length === 0 || room < 2) return null
          const look = LOOK[kind]
          const shown = items.slice(0, Math.max(1, room - 1))
          room -= shown.length + 1

          return (
            <Box flexDirection="column" marginTop={1}>
              <Text bold color={look.color}>{`${look.label} · ${items.length}`}</Text>
              {shown.map(i => {
                const when = ago(now - i.at)
                const isFresh = now - i.at < FRESH_MS
                const title = clip(i.title || '(no title)', 120)

                return (
                  <Box justifyContent="space-between">
                    <Box flexShrink={1}>
                      <Text color={look.color} bold={isFresh}>{` ${look.icon} `}</Text>
                      <Text bold color="magenta">{`#${i.n} `}</Text>
                      <Text bold={isFresh} dimColor={kind === 'done'} wrap="truncate-end">
                        {title}
                      </Text>
                    </Box>
                    <Box flexShrink={0}>
                      <Text dimColor>{isFresh ? ' ✦ now' : ` ${when}`}</Text>
                    </Box>
                  </Box>
                )
              })}
              {items.length > shown.length && <Text dimColor>{`   +${items.length - shown.length} more`}</Text>}
            </Box>
          )
        })}
        <Box marginTop={1}>
          <Text dimColor>{' /issues clear · updates live'}</Text>
        </Box>
      </Box>
    )
  })
}
