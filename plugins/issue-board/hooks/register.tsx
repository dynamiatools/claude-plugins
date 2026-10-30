import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Issue } from '../types'
import { ago, issueRefs, repoOf } from './parse'

const PANE = 'issue-board'
const KEEP = 20
const BADGE = { work: ['WORK', 'yellow'], pr: ['PR', 'cyan'], done: ['DONE', 'green'] } as const

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
    const room = Math.max(1, (e.viewport?.rows ?? 12) - 3)
    const shown = [...list].sort((a, b) => b.at - a.at).slice(0, room)

    return (
      <Box flexDirection="column">
        <Text bold color="black" backgroundColor="magenta">
          {` ISSUES ${repo} `}
        </Text>
        {shown.length === 0 && <Text dimColor>No issues yet.</Text>}
        {shown.map(i => (
          <Box>
            <Text bold color="black" backgroundColor={BADGE[i.kind][1]}>
              {` ${BADGE[i.kind][0]} `}
            </Text>
            <Text bold>{` #${i.n} `}</Text>
            <Text dimColor={i.kind === 'done'}>{(i.title || '').slice(0, 60)}</Text>
            <Text dimColor>{` ${ago(now - i.at)}`}</Text>
          </Box>
        ))}
      </Box>
    )
  })
}
