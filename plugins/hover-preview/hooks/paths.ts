// Finding the paths a text names: absolute (`/home/x`), from home (`~/x`), relative (`./x`,
// `src/x.ts`, `README.md`), each with an optional `:line` or `:line:column`. A path found here is
// only a candidate: the hooks module keeps the ones that lead to a file or folder.

/** A path a text names, `:line` cut, and the line it names. */
export type Found = { target: string; line?: number }

// What a sentence puts after a path, and a line (and column) after a file.
const TRAILING = /[.,;:!?)\]}>'"]+$/
const LINE = /:(\d+)(?::\d+)?$/
// An address: never a path, nor the paths inside it.
const URL = /\b[a-z][a-z0-9+.-]*:\/\/[^\s<>()]+/gi
// Absolute, from home or explicitly relative; a relative path with a folder in it; a file name
// with an extension. None starts inside a word, an address or another path.
const CANDIDATE = new RegExp(
  [
    String.raw`(?:~|\.{1,2})?\/[^\s\`'"<>()[\]{}|*]+`,
    String.raw`[\w@+-][\w@.+-]*(?:\/[\w@.+-]+)+\/?`,
    String.raw`[\w@+-][\w@.+-]*\.[A-Za-z][A-Za-z0-9]{0,9}`
  ].map(source => `(?<![\\w/.~:@-])(?:${source})(?::\\d+(?::\\d+)?)?`).join('|'),
  'g'
)

/** The paths named in a text, each once, in order. Spaces end a path: there are no paths with spaces. */
export function pathsIn (text: string): Found[] {
  const masked = text.replace(URL, match => ' '.repeat(match.length))
  const seen = new Map<string, Found>()
  for (const match of masked.matchAll(CANDIDATE)) {
    let target = match[0].replace(TRAILING, '')
    const line = LINE.exec(target)
    if (line) target = target.slice(0, line.index)
    target = target.replace(TRAILING, '')
    if (!/[\w~]/.test(target) || target === '~') continue
    if (!seen.has(target)) seen.set(target, line ? { target, line: Number(line[1]) } : { target })
  }
  return [...seen.values()]
}

/** Where `target` lands: home for `~`, `cwd` for a relative path; `.` and `..` folded, no trailing `/`. */
export function resolve (target: string, cwd: string, home: string | undefined) {
  let path = target
  if (path === '~' || path.startsWith('~/')) {
    if (!home) return undefined
    path = home + path.slice(1)
  } else if (!path.startsWith('/')) {
    path = `${cwd}/${path}`
  }
  const parts: string[] = []
  for (const part of path.split('/')) {
    if (part === '' || part === '.') continue
    if (part === '..') parts.pop()
    else parts.push(part)
  }
  return `/${parts.join('/')}`
}

/** The lines of `text` around `line` (the top when none), at most `rows`, numbered from 1. */
export function excerptOf (text: string, line: number | undefined, rows: number) {
  const all = text.split('\n')
  if (all.at(-1) === '') all.pop()
  const start = Math.max(0, Math.min(all.length - rows, (line ?? 1) - 1 - Math.floor(rows / 3)))
  return { total: all.length, lines: all.slice(start, start + rows).map((text, i) => ({ n: start + i + 1, text: text.replaceAll('\t', '  ').slice(0, 200) })) }
}
