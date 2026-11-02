import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Item } from '../types'
import { outlineOf } from './outline'

const PANE = 'file-outline'
const MAX_BYTES = 1024 * 1024
const file = atom({ plugin: 'file-outline', key: 'file' } as const, null as string | null)
const items = atom({ plugin: 'file-outline', key: 'items' } as const, [] as Item[])

const MARK: Record<string, string> = { h: '#', class: '◆', fn: 'ƒ', section: '§', key: '·' }

/** Reads `path` and shows its outline; a file with none leaves the pane as it was, unless asked for it. */
async function show ($: EngineInterface, path: string, isCommand = false) {
  const stat = await $.fs.stat(path).catch(() => null)
  if (!stat || stat.kind !== 'file' || stat.size > MAX_BYTES) return false
  const text = await $.fs.read(path).catch(() => undefined)
  if (typeof text !== 'string' || text.includes('\0')) return false
  const found = outlineOf(path, text)
  if (found.length === 0 && !isCommand) return false
  await update($, file, () => path)
  await update($, items, () => found)
  void $.ui.open({ id: PANE, title: 'Outline' })
  return true
}

export const register: Register = on => {
  // The pane follows the files the agent reads, edits or writes.
  on('tool.call', { tool: ['Read', 'Edit', 'Write'] }, async ($, e, next) => {
    const ran = await next(e)
    const path = (e as { file_path?: string }).file_path
    if (typeof path === 'string') await show($, path).catch(() => undefined)
    return ran
  })

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'outline', description: 'Show the outline of a file: /outline <path>' })
    return next(e)
  })

  on('command.run', { name: 'outline' }, async ($, e) => {
    const arg = String(e.args ?? '').trim()
    const path = arg.startsWith('/') ? arg : `${await $.session.cwd()}/${arg}`
    if (!arg) return { text: 'Usage: /outline <path>' }
    return { text: (await show($, path, true)) ? `Outline of ${path}` : `No outline for ${path}` }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const [path, list] = await Promise.all([read($, file), read($, items)])
    if (path === null) return <Text dimColor>Waiting for a file.</Text>
    const room = Math.max(1, (e.viewport?.rows ?? 24) - 8)
    const width = String(list.at(-1)?.line ?? 0).length
    return (
      <Box flexDirection="column">
        <Text bold color="cyan" wrap="truncate-middle">{path}</Text>
        <Text dimColor>{list.length} entries</Text>
        {list.length === 0 && <Text dimColor>Nothing to list in this file.</Text>}
        {list.slice(0, room).map(item => (
          <Text key={item.line} wrap="truncate-end">
            <Text dimColor>{String(item.line).padStart(width)} </Text>
            {'  '.repeat(item.depth)}
            <Text color="yellow">{MARK[item.kind] ?? '·'} </Text>
            {item.title}
          </Text>
        ))}
        {list.length > room && <Text dimColor>… {list.length - room} more</Text>}
      </Box>
    )
  })
}
