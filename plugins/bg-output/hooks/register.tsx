import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Job } from '../types'
import { isDetached, isWatched, logFileOf } from './watch'

const PANE = 'bg-output'
const KEEP = 8
const TAIL_CHARS = 6000
const IDLE_MS = 10_000
const jobs = atom({ plugin: 'bg-output', key: 'jobs' } as const, [], { shape: 'jobs-1' })

export const register: Register = (on, options) => {
  const isAutoOpen = options?.autoOpen === true

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'bg-output', description: 'Open the background output pane' })
    $.clock.every(1000, async () => {
      const list = await read($, jobs)
      const now = await $.clock.now()
      const fresh: Job[] = []
      let isChanged = false
      for (const job of list) {
        const text = await $.fs.read(job.file).catch(() => undefined)
        const tail = text === undefined ? job.tail : text.slice(-TAIL_CHARS)
        if (tail !== job.tail) {
          isChanged = true
          fresh.push({ ...job, tail, changedAt: now })
        } else fresh.push(job)
      }
      if (isChanged) await update($, jobs, () => fresh)
    })

    return next(e)
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    // The shell's folder before the command runs: a relative log path is taken from it.
    const cwd = await $.session.cwd()
    const ran = await next(e)
    if (!('result' in ran) || ran.result === undefined) return ran
    const result = ran.result as { backgroundTaskId?: string; backgroundOutputPath?: string }

    // A command with nohup is no background task of Claude Code: follow the log it writes.
    let id = result.backgroundTaskId
    let file = result.backgroundOutputPath ?? ran.text?.match(/(\/\S+\.output)/)?.[1]
    if (id === undefined && isDetached(e.command)) {
      file = logFileOf(e.command, cwd) ?? undefined
      id = file && `nohup:${file}`
    } else if (!isWatched(e.command)) return ran
    if (id === undefined || file === undefined) return ran

    const now = await $.clock.now()
    const job: Job = { id, command: e.command, file, tail: '', changedAt: now, startedAt: now }
    await update($, jobs, list => [...list.filter(one => one.id !== id), job].slice(-KEEP))
    if (isAutoOpen) void $.ui.open({ id: PANE, title: 'Background output' })

    return ran
  })

  on('command.run', { command: 'bg-output' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Background output' })

    return { text: 'Background output pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const list = await read($, jobs)
    const now = await $.clock.now()
    const room = Math.max(1, (e.viewport?.rows ?? 24) - 7 - Math.max(0, list.length - 1))
    const last = list[list.length - 1]
    if (last === undefined) return <Text dimColor>No background commands yet.</Text>

    const lines = last.tail.split('\n').slice(-room)

    const isLive = now - last.changedAt < IDLE_MS

    return (
      <Box flexDirection="column">
        <Box>
          <Text bold color="black" backgroundColor={isLive ? 'green' : 'yellow'}>
            {isLive ? ' LIVE ' : ' IDLE '}
          </Text>
          <Text bold color="cyan">
            {' '}
            {last.command.slice(0, 160)}
          </Text>
        </Box>
        {list.slice(0, -1).map(job => (
          <Text dimColor>
            {now - job.changedAt < IDLE_MS ? 'live' : 'idle'} {job.command.slice(0, 80)}
          </Text>
        ))}
        <Text dimColor>{'─'.repeat(40)}</Text>
        {lines.map(line => (
          <Text>{line}</Text>
        ))}
      </Box>
    )
  })
}
