import { atom, read, update } from 'claude-code'
import type { EngineInterface, On, Timer } from 'claude-code'

import type { ThanosView } from './thanos-view'
import { bar, bullet, clip, counts, glyph, killArgv, panelArgv, parsePanel, splitTask, statusLine, wrap } from './thanos-view'

const PANE = 'dynamia-thanos'
const EVERY_MS = 3000

// null: no mission to show.
const view = atom({ plugin: 'dynamia', key: 'thanos' } as const, null as ThanosView | null)

let ticker: Timer | null = null
let last = ''

// Asks the tool for the mission of this session and redraws only when something changed.
async function refresh($: EngineInterface) {
  const out = await $.process.run(panelArgv($.plugin.root, await $.session.id()))
  const text = out.exitCode === 0 ? out.stdout.trim() : ''
  if (text === last) return
  last = text
  await update($, view, () => parsePanel(text))
}

// Polls while the pane is open and stops by itself once it is closed.
function startTicker($: EngineInterface) {
  if (ticker) return
  ticker = $.clock.every(EVERY_MS, async () => {
    if (!(await $.ui.panes()).some(p => p.id === PANE)) {
      ticker?.cancel()
      ticker = null

      return
    }
    await refresh($)
  })
}

// The ui.press hook lives in register.tsx (one per event); it calls this for the panel's buttons.
export async function thanosPress($: EngineInterface, element: string) {
  if (!element.startsWith('thanos-kill:')) return
  await $.process.run(killArgv($.plugin.root, element.slice('thanos-kill:'.length), await $.session.id()))
  await refresh($)
}

async function openPanel($: EngineInterface, focus: boolean) {
  await refresh($)
  await $.ui.open(focus ? { id: PANE, title: 'THANOS', focus: true } : { id: PANE, title: 'THANOS' })
  startTicker($)
}

// Called from the single session.start hook in register.tsx (the engine refuses a second one).
export async function registerThanosCommands($: EngineInterface) {
  await $.command.register({ name: 'dynamia-thanos-panel', description: 'Side panel with the tasks of the THANOS mission (THANOS.md)' })
}

export function registerThanos(on: On) {
  on('command.run', { command: 'dynamia-thanos-panel' }, async $ => {
    await openPanel($, true)

    return { text: 'THANOS panel opened.' }
  })

  // `thanos start|resume` opens the panel on its own; any other thanos command refreshes it.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    const m = /\bms-workspace\s+thanos\s+(\w+)/.exec(e.command ?? '')
    if (!m || 'deny' in ran) return ran
    if (m[1] === 'start' || m[1] === 'resume') await openPanel($, false)
    else await refresh($)

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const v = await read($, view)
    const width = Math.max(20, (e.props?.bodyColumns ?? 40) - 2)
    if (!v) {
      return (
        <Box flexDirection="column">
          <Text bold>THANOS</Text>
          <Text dimColor>No mission in this session. It opens by itself on `ms-workspace thanos start`.</Text>
        </Box>
      )
    }
    const c = counts(v.tasks)
    const room = Math.max(4, (e.viewport?.rows ?? 24) - 12)
    // Keep the running task and the open ones in view; finished ones scroll away first.
    const firstOpen = Math.max(0, v.tasks.findIndex(t => t.mark === ' '))
    const from = Math.min(Math.max(0, firstOpen - 2), Math.max(0, v.tasks.length - room))
    // Long task text wraps onto the next lines, so the window is counted in lines, not tasks.
    const rows = v.tasks.map(t => {
      const { name, what } = splitTask(t.text)
      const head = `${glyph(t)} ${t.size !== '' ? `[${t.size}] ` : ''}`
      const lines = wrap(`${head}${name}`, width).map((l, i) => (i === 0 ? l : `  ${l}`))
      const extra = t.active && what !== '' ? wrap(what, width - 2).map(l => `  ${l}`) : []

      return { t, lines, extra }
    })
    const shown: typeof rows = []
    for (let used = 0, i = from; i < rows.length; i++) {
      const n = rows[i].lines.length + rows[i].extra.length
      if (shown.length > 0 && used + n > room) break
      shown.push(rows[i])
      used += n
    }
    const tone = v.mission.status === 'working' ? 'magenta' : v.mission.status === 'done' ? 'green' : 'yellow'

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text bold color={tone}>
            {`THANOS · ${v.mission.batch}`}
          </Text>
          <Text dimColor>{clip(statusLine(v.mission), width)}</Text>
          <Text dimColor>{wrap(v.mission.goal, width).join('\n')}</Text>
          {v.usage !== null && (
            <Text color={v.usage >= 90 ? 'red' : v.usage >= 70 ? 'yellow' : undefined} dimColor={v.usage < 70}>
              {`plan usage ${Math.round(v.usage)}%${v.mission.until_usage ? ` (stops at ${v.mission.until_usage}%)` : ''}`}
            </Text>
          )}
        </Box>
        <Box flexDirection="column">
          <Text>
            {`${bar(c.done, c.total, Math.min(24, width - 12))} ${c.done}/${c.total}`}
          </Text>
          <Text dimColor>
            {`${c.open} open · ${c.parked} parked`}
          </Text>
        </Box>
        <Box flexDirection="column">
          {v.tasks.length === 0 && <Text dimColor>No tasks yet in THANOS.md.</Text>}
          {from > 0 && <Text dimColor>… {from} earlier</Text>}
          {shown.map(({ t, lines, extra }, i) => (
            <Box key={`${from + i}`} flexDirection="column">
              {lines.map((l, j) => (
                <Text key={String(j)} color={t.mark === '!' ? 'red' : t.active ? 'magenta' : undefined} dimColor={t.mark === 'x'} bold={t.active}>
                  {l}
                </Text>
              ))}
              {extra.map((l, j) => (
                <Text key={`x${j}`} dimColor>
                  {l}
                </Text>
              ))}
            </Box>
          ))}
          {from + shown.length < v.tasks.length && <Text dimColor>… {v.tasks.length - from - shown.length} more</Text>}
        </Box>
        {v.procs.length > 0 && (
          <Box flexDirection="column">
            <Text bold>{`Processes (${v.procs.length})`}</Text>
            {v.procs.map(p => (
              <Box key={p.name} flexDirection="row" gap={1}>
                <Button key={`thanos-kill:${p.name}`} label="■" onPress={() => {}} />
                <Text dimColor={!p.alive}>{clip(`${p.name} ${p.alive ? 'running' : 'exited'} · ${p.cmd}`, width - 6)}</Text>
              </Box>
            ))}
          </Box>
        )}
        {v.last_block && (
          <Box flexDirection="column">
            <Text bold color="red">
              Last blocked
            </Text>
            <Text dimColor>{wrap(v.last_block.c, width).join('\n')}</Text>
            <Text dimColor>{wrap(v.last_block.why, width).join('\n')}</Text>
          </Box>
        )}
        {v.blockers.length > 0 && (
          <Box flexDirection="column">
            <Text bold color="red">
              {`Blockers (${v.blockers.length})`}
            </Text>
            {v.blockers.slice(-3).map((b, i) => (
              <Text key={String(i)} dimColor>
                {bullet(b, width)}
              </Text>
            ))}
          </Box>
        )}
        {v.decisions.length > 0 && (
          <Box flexDirection="column">
            <Text bold>{`Decisions (${v.decisions.length})`}</Text>
            {v.decisions.slice(-2).map((d, i) => (
              <Text key={String(i)} dimColor>
                {bullet(d, width)}
              </Text>
            ))}
          </Box>
        )}
        {v.failed.length > 0 && <Text dimColor>{v.failed.length} failed attempt(s) in THANOS.md</Text>}
      </Box>
    )
  })
}
