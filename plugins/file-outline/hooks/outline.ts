import type { Item } from '../types'

// One rule per kind of line worth listing. The depth comes from the indentation, so a method sits
// under its class. shortcut: line patterns, not a parser; a line a pattern misses is not listed.
// Revisit with tree-sitter only if the misses annoy.
const DEFS: { kind: string; re: RegExp }[] = [
  { kind: 'class', re: /^\s*(?:export\s+|public\s+|private\s+|protected\s+|abstract\s+|final\s+|open\s+|data\s+|sealed\s+|static\s+)*(?:class|interface|enum|object|trait|record|struct|impl|type)\s+([A-Za-z_][\w<>,.]*)/ },
  { kind: 'fn', re: /^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|final\s+|override\s+|suspend\s+)*(?:function\s*\*?|def|fun|fn|func)\s+([A-Za-z_][\w.]*)/ },
  { kind: 'fn', re: /^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*(?::[^=]+)?=>/ },
  { kind: 'fn', re: /^([A-Za-z_][\w-]*)\s*\(\)\s*\{/ },
  { kind: 'fn', re: /^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>[\],.? ]+\s+([A-Za-z_]\w*)\s*\(/ }
]

const INDENT = 2

/** The indentation of a line, in levels of two columns (a tab is a level). */
const levelOf = (line: string) => {
  const lead = /^[ \t]*/.exec(line)![0]
  return Math.floor((lead.replaceAll('\t', '  ').length) / INDENT)
}

/** The outline of a Markdown file: its ATX headings, outside fenced code. */
function markdown (lines: string[]): Item[] {
  const items: Item[] = []
  let fence: string | undefined
  lines.forEach((text, i) => {
    const mark = /^\s*(```|~~~)/.exec(text)?.[1]
    if (mark) fence = fence === undefined ? mark : fence === mark ? undefined : fence
    if (fence !== undefined || mark) return
    const heading = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(text)
    if (heading) items.push({ line: i + 1, depth: heading[1]!.length - 1, kind: 'h', title: heading[2]! })
  })
  return items
}

/** The outline of a YAML or TOML file: its sections and top-level keys. */
function config (lines: string[], toml: boolean): Item[] {
  const items: Item[] = []
  lines.forEach((text, i) => {
    const table = toml ? /^\s*\[{1,2}([^\]]+)\]{1,2}\s*$/.exec(text) : undefined
    if (table) items.push({ line: i + 1, depth: table[1]!.split('.').length - 1, kind: 'section', title: table[1]! })
    else if (!toml) {
      const key = /^(\s{0,2})([A-Za-z_][\w.-]*):(?:\s|$)/.exec(text)
      if (key) items.push({ line: i + 1, depth: key[1]!.length / INDENT, kind: 'key', title: key[2]! })
    }
  })
  return items
}

/** The outline of a source file: its classes and functions, deeper where indented. */
function code (lines: string[]): Item[] {
  const items: Item[] = []
  let inBlock = false
  lines.forEach((text, i) => {
    if (inBlock) {
      if (text.includes('*/')) inBlock = false
      return
    }
    if (/^\s*\/\*/.test(text) && !text.includes('*/')) {
      inBlock = true
      return
    }
    if (/^\s*(\/\/|#|\*)/.test(text) && !/^#!/.test(text)) return
    for (const { kind, re } of DEFS) {
      const match = re.exec(text)
      if (match) {
        items.push({ line: i + 1, depth: Math.min(levelOf(text), 4), kind, title: match[1]! })
        return
      }
    }
  })
  return items
}

/** The outline of `text`, by the extension of `path`; empty for a kind of file with no outline. */
export function outlineOf (path: string, text: string): Item[] {
  const name = path.slice(path.lastIndexOf('/') + 1).toLowerCase()
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1) : ''
  const lines = text.split('\n')
  if (ext === 'md' || ext === 'markdown' || ext === 'mdx') return markdown(lines)
  if (ext === 'yml' || ext === 'yaml') return config(lines, false)
  if (ext === 'toml') return config(lines, true)
  if (['ts', 'tsx', 'js', 'jsx', 'mjs', 'py', 'java', 'kt', 'kts', 'groovy', 'go', 'rs', 'sh', 'bash', 'php', 'rb', 'swift', 'cs', 'scala'].includes(ext)) return code(lines)
  return []
}
