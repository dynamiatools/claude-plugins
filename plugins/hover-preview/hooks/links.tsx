import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import { excerptOf, pathsIn, resolve } from './paths'
import type { Peek } from '../types'

type Engine = EngineInterface

const peek = atom({ plugin: 'hover-preview', key: 'peek' } as const, null as Peek | null)

// The most paths one reply block gets as links, the lines a card shows, the largest file read for
// them, and how long an answer about a path is kept.
const MAX_LINKS = 6
const CARD_LINES = 12
const CODE_BYTES = 1024 * 1024
const ENTRIES = 10
const STAT_MS = 5_000

const stats = new Map<string, { at: number; path: string | null }>()
// The path the pointer is on: a preview that finishes after the pointer left is not shown.
let hovered: string | undefined

/** The place `target` leads to as a file or folder, trying the shell's folder and then the project's; null where nowhere. */
async function locate ($: Engine, target: string) {
  const cwd = await $.session.cwd()
  const root = await $.session.root().catch(() => cwd)
  const key = `${cwd}\n${root}\n${target}`
  const known = stats.get(key)
  if (known && Date.now() - known.at < STAT_MS) return known.path
  const home = await $.env.get('HOME')
  let found: string | null = null
  for (const base of new Set([cwd, root])) {
    const path = resolve(target, base, home)
    const stat = path && (await $.fs.stat(path).catch(() => null))
    if (path && stat && stat.kind !== 'other') {
      found = path
      break
    }
  }
  stats.set(key, { at: Date.now(), path: found })
  return found
}

/** What the card shows of `path`: its kind, size and age, and its lines or entries. */
async function peekAt ($: Engine, path: string, line: number | undefined): Promise<Peek | null> {
  const stat = await $.fs.stat(path).catch(() => null)
  if (!stat || stat.kind === 'other') return null
  const base = { path, kind: stat.kind, size: stat.size, mtimeMs: stat.mtimeMs, ...(line !== undefined && { line }) }
  if (stat.kind === 'dir') {
    const entries = (await $.fs.list(path).catch(() => [])).slice(0, ENTRIES).map(entry => (entry.kind === 'dir' ? `${entry.name}/` : entry.name))
    return { ...base, entries }
  }
  if (stat.size > CODE_BYTES) return base
  const text = await $.fs.read(path).catch(() => undefined)
  // A NUL is what text never holds: the file is not text.
  if (typeof text !== 'string' || text.includes('\0')) return base
  const { total, lines } = excerptOf(text, line, CARD_LINES)
  return { ...base, total, lines }
}

/** Shows `path` in the file manager (opens it, with `isAlt`): Finder on macOS, the folder in `xdg-open` elsewhere. */
async function show ($: Engine, path: string, kind: 'file' | 'dir', isAlt: boolean) {
  const isMac = (await $.process.run(['uname', '-s']).catch(() => undefined))?.stdout.trim() === 'Darwin'
  // shortcut: Linux has no portable "select this file"; open its folder. Revisit with org.freedesktop.FileManager1 ShowItems if wanted.
  const folder = kind === 'dir' ? path : path.slice(0, path.lastIndexOf('/')) || '/'
  const argv = isMac ? (isAlt || kind === 'dir' ? ['open', path] : ['open', '-R', path]) : ['xdg-open', isAlt ? path : folder]
  await $.process.run(argv).catch(() => undefined)
}

const ago = (ms: number) => {
  const minutes = Math.max(0, Math.round((Date.now() - ms) / 60_000))
  return minutes < 60 ? `${minutes} min ago` : minutes < 2880 ? `${Math.round(minutes / 60)} h ago` : `${Math.round(minutes / 1440)} d ago`
}

const sizeOf = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

export const registerLinks: Register = (on) => {
  // Under a reply block that names paths leading somewhere: one link each. The reply itself is
  // drawn by the engine as it was.
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.viewport?.isFullscreen === false) return next(e)
    const drawn = await next(e)
    const links: { label: string; path: string; line?: number }[] = []
    for (const { target, line } of pathsIn(e.props.text)) {
      const path = await locate($, target)
      if (path) links.push({ label: line === undefined ? target : `${target}:${line}`, path, ...(line !== undefined && { line }) })
      if (links.length === MAX_LINKS) break
    }
    if (links.length === 0) return drawn
    const { Box, Client, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {drawn}
        <Box flexDirection="row" columnGap={1} flexWrap="wrap" paddingLeft={2}>
          <Text dimColor>↳</Text>
          {links.map((link, i) => <Client key={`peek:${i}`} module="./link.tsx" props={link} />)}
        </Box>
      </Box>
    )
  })

  on('ui.message', { element: /^peek:\d+$/ }, async ($, e, next) => {
    const result = await next(e)
    if (!/^peek:\d+$/.test(e.element)) return result
    const data = e.data as { path?: unknown; line?: unknown; isOver?: unknown; isClicked?: unknown; isAlt?: unknown } | null
    if (typeof data?.path !== 'string') return result
    const line = typeof data.line === 'number' ? data.line : undefined
    if (data.isClicked === true) {
      const stat = await $.fs.stat(data.path).catch(() => null)
      if (stat && stat.kind !== 'other') await show($, data.path, stat.kind, data.isAlt === true)
      hovered = undefined
      await update($, peek, () => null)
    } else if (data.isOver === true) {
      if (hovered === data.path) return result
      hovered = data.path
      const card = await peekAt($, data.path, line)
      if (hovered === data.path) await update($, peek, () => card)
    } else if (hovered === data.path) {
      hovered = undefined
      await update($, peek, () => null)
    }
    return result
  })

  // Above the prompt: the card of the path the pointer is on.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.hasSurvey || e.viewport?.isFullscreen === false) return next(e)
    const card = await read($, peek)
    if (card === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const below = await next(e)
    const width = String(card.lines?.at(-1)?.n ?? 0).length
    return (
      <Box flexDirection="column">
        {below}
        <Box flexDirection="column" borderStyle="round" borderDimColor flexShrink={0}>
          <Text bold wrap="truncate-middle">{card.path}</Text>
          <Text dimColor>
            {card.kind === 'dir' ? 'folder' : `file · ${sizeOf(card.size)}`} · {ago(card.mtimeMs)}
            {card.total !== undefined ? ` · ${card.total} lines` : ''}
          </Text>
          {card.lines?.map(({ n, text }) => (
            <Text key={n} wrap="truncate-end" inverse={n === card.line}>{String(n).padStart(width)} {text}</Text>
          ))}
          {card.entries?.map(name => <Text key={name} wrap="truncate-end">{name}</Text>)}
        </Box>
      </Box>
    )
  })
}
