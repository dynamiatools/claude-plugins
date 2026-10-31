import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Issue } from '../types'
import { ago, bar, clip, issueRefs, repoOf, rowsOf } from './parse'

const PANE = 'issue-board'
const KEEP = 20
const LOOK = {
  work: { icon: '●', label: 'IN PROGRESS', color: 'yellow' },
  pr: { icon: '◐', label: 'PULL REQUEST', color: 'cyan' },
  done: { icon: '✓', label: 'DONE', color: 'green' },
} as const
const FRESH_MS = 30_000
const MAX_TITLE_ROWS = 3

const issues = atom({ plugin: 'issue-board', key: 'issues' } as const, [], { shape: 'issues-1' })

const line = (i: Issue) => `#${i.n} ${i.title || '(no title)'}${i.branch ? ` [${i.branch}]` : ''}`

// A top-level function: the validator follows $ only into functions declared here.
async function save($: EngineInterface, repo: string, list: Issue[]) {
  if (repo !== '') await $.store.set(`issues:${repo}`, list)
}

const TOOL = 'mcp__issue-board__issue'
const STATES = ['work', 'pr', 'done', 'drop'] as const
type Change = { n: number; state: (typeof STATES)[number]; title?: string }

const ghTitle = ($: EngineInterface, n: number) =>
  $.process
    .run(['gh', 'issue', 'view', String(n), '--json', 'title', '-q', '.title'], { timeoutMs: 10_000 })
    .then(r => (r.exitCode === 0 ? r.stdout.trim() : ''))
    .catch(() => '')

// Applies what the agent says: a state per issue, `drop` removes it. Returns one line per change.
async function apply($: EngineInterface, changes: Change[]) {
  const now = await $.clock.now()
  const out: string[] = []
  for (const c of changes) {
    const known = (await read($, issues)).find(i => i.n === c.n)
    if (c.state === 'drop') {
      await update($, issues, list => list.filter(i => i.n !== c.n))
      out.push(`#${c.n} removed`)
      continue
    }
    const title = c.title || known?.title || (await ghTitle($, c.n))
    await update($, issues, list => {
      const one: Issue = { n: c.n, kind: c.state, title, branch: known?.branch ?? '', at: now }

      return [...list.filter(i => i.n !== c.n), one].slice(-KEEP)
    })
    out.push(`#${c.n} ${c.state}`)
  }

  return out
}

// Asks GitHub about every issue not done and marks the closed ones done: a merged PR closes its issue
// without any command the board could see.
async function sync($: EngineInterface) {
  const closed: Change[] = []
  for (const i of (await read($, issues)).filter(i => i.kind !== 'done')) {
    const state = await $.process
      .run(['gh', 'issue', 'view', String(i.n), '--json', 'state', '-q', '.state'], { timeoutMs: 10_000 })
      .then(r => (r.exitCode === 0 ? r.stdout.trim() : ''))
      .catch(() => '')
    if (state === 'CLOSED') closed.push({ n: i.n, state: 'done' })
  }

  return apply($, closed)
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
    await $.command.register({ name: 'issues', description: 'Show the issues in progress; "/issues sync" checks them on GitHub, "/issues clear" empties the list' })
    await $.tool.register({
      name: 'issue',
      isDeferred: false,
      description:
        'Updates the issue board shown to the user. Call it whenever an issue changes state and the board may not have noticed: ' +
        'a PR merged or closed it, you started one, or one is no longer relevant. ' +
        'Pass `updates` with a state per issue (work, pr, done, or drop to remove it), and/or `sync: true` to check every open issue on GitHub and mark the closed ones done.',
      inputSchema: {
        type: 'object',
        properties: {
          updates: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                n: { type: 'number', description: 'Issue number' },
                state: { type: 'string', enum: [...STATES] },
                title: { type: 'string', description: 'Optional; read from GitHub when left out' },
              },
              required: ['n', 'state'],
            },
          },
          sync: { type: 'boolean', description: 'Check open issues on GitHub and mark the closed ones done' },
        },
      },
    })
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
    if (e.args.trim() === 'sync') {
      const done = await sync($)
      await save($, repo, await read($, issues))

      return { text: done.length === 0 ? 'Nothing closed on GitHub.' : `Marked done: ${done.join(', ')}` }
    }
    const list = await read($, issues)
    void $.ui.open({ id: PANE, title: 'Issues' })

    return { text: list.length === 0 ? 'No issues tracked yet.' : list.map(line).join('\n') }
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    const input = e as unknown as { updates?: Change[]; sync?: boolean }
    const changes = (input.updates ?? []).filter(c => Number.isInteger(c.n) && STATES.includes(c.state))
    const done = [...(await apply($, changes)), ...(input.sync ? await sync($) : [])]
    await save($, repo, await read($, issues))
    void $.ui.open({ id: PANE, title: 'Issues' })

    return { result: done.length === 0 ? 'Board unchanged.' : `Board updated: ${done.join(', ')}` }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    // A merged PR closes its issues with no command the board can read: ask GitHub.
    if (/\bgh\s+pr\s+merge\b/.test(e.command)) {
      await sync($)
      await save($, repo, await read($, issues))
    }
    const refs = issueRefs(e.command)
    if (refs.length === 0) return ran

    const now = await $.clock.now()
    const known = await read($, issues)
    for (const ref of refs) {
      const title =
        known.find(i => i.n === ref.n)?.title ||
        (await ghTitle($, ref.n))
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
    const cols = e.viewport?.columns ?? 100
    // A title wraps under itself, in the width left after the icon, "#N" and the time column.
    const titleOf = (i: Issue) => {
      const width = cols - String(i.n).length - 13

      return { text: clip(i.title || '(no title)', width * MAX_TITLE_ROWS - 3), width }
    }
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
          const shown: Issue[] = []
          let used = 1
          for (const i of items) {
            const { text, width } = titleOf(i)
            const need = rowsOf(text, width)
            if (shown.length > 0 && used + need > room) break
            shown.push(i)
            used += need
          }
          room -= used

          return (
            <Box flexDirection="column" marginTop={1}>
              <Text bold color={look.color}>{`${look.label} · ${items.length}`}</Text>
              {shown.map(i => {
                const when = ago(now - i.at)
                const isFresh = now - i.at < FRESH_MS
                const { text } = titleOf(i)

                return (
                  <Box>
                    <Box flexShrink={0}>
                      <Text color={look.color} bold={isFresh}>{` ${look.icon} `}</Text>
                      <Text bold color="magenta">{`#${i.n}`}</Text>
                    </Box>
                    <Box flexGrow={1} flexShrink={1} marginLeft={1}>
                      <Text bold={isFresh} dimColor={kind === 'done'} wrap="wrap">
                        {text}
                      </Text>
                    </Box>
                    <Box flexShrink={0} marginLeft={1}>
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
