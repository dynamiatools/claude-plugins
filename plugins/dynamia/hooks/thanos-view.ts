export type ThanosTask = { mark: string; size: string; text: string; active: boolean }
export type ThanosMission = {
  batch: string
  branch: string
  goal: string
  status: string
  steps: number
  max_steps: number
  until_usage: number
  opus_used: number
  max_opus: number
  blockers: number
  generation?: number
}
export type ThanosProc = { name: string; pid: number; alive: boolean; cmd: string }
export type ThanosView = {
  mission: ThanosMission
  tasks: ThanosTask[]
  decisions: string[]
  failed: string[]
  blockers: string[]
  usage: number | null
  procs: ThanosProc[]
  last_block: { c: string; why: string; t: number } | null
}

export function panelArgv(root: string, sessionId: string): string[] {
  return [`${root}/bin/ms-workspace`, 'thanos', 'panel', '--session', sessionId]
}

// The JSON of `ms-workspace thanos panel`; null when there is no mission or the text is not that JSON.
export function parsePanel(stdout: string): ThanosView | null {
  let raw: unknown
  try {
    raw = JSON.parse(stdout)
  } catch {
    return null
  }
  const o = raw as Partial<ThanosView> | null
  if (!o || typeof o !== 'object' || !o.mission || !Array.isArray(o.tasks)) return null
  const lines = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

  const procs = Array.isArray(o.procs) ? o.procs.filter(p => p && typeof p.name === 'string') : []
  const lb = o.last_block && typeof o.last_block.c === 'string' ? o.last_block : null

  return {
    mission: o.mission,
    tasks: o.tasks,
    decisions: lines(o.decisions),
    failed: lines(o.failed),
    blockers: lines(o.blockers),
    usage: typeof o.usage === 'number' ? o.usage : null,
    procs,
    last_block: lb,
  }
}

export function killArgv(root: string, name: string, sessionId: string): string[] {
  return [`${root}/bin/ms-workspace`, 'thanos', 'kill', name, '--session', sessionId]
}

export function clip(text: string, width: number): string {
  return text.length <= width ? text : `${text.slice(0, Math.max(1, width - 1))}…`
}

// Word-wraps text into lines of at most `width` chars; a word longer than a line is split.
export function wrap(text: string, width: number): string[] {
  const w = Math.max(1, width)
  const lines: string[] = []
  let line = ''
  for (const word of text.split(/\s+/).filter(Boolean)) {
    let rest = word
    while (rest.length > w) {
      if (line !== '') {
        lines.push(line)
        line = ''
      }
      lines.push(rest.slice(0, w))
      rest = rest.slice(w)
    }
    if (line === '') line = rest
    else if (line.length + 1 + rest.length <= w) line += ` ${rest}`
    else {
      lines.push(line)
      line = rest
    }
  }
  if (line !== '' || lines.length === 0) lines.push(line)

  return lines
}

export function bar(done: number, total: number, width: number): string {
  const cells = Math.max(1, width)
  const filled = total <= 0 ? 0 : Math.round((done / total) * cells)

  return '█'.repeat(filled) + '░'.repeat(cells - filled)
}

// "[x] name: what" lines become the name and what the task does.
export function splitTask(text: string): { name: string; what: string } {
  const i = text.indexOf(':')
  return i < 0 ? { name: text.trim(), what: '' } : { name: text.slice(0, i).trim(), what: text.slice(i + 1).trim() }
}

export function glyph(task: ThanosTask): string {
  if (task.mark === 'x') return '✓'
  if (task.mark === '!') return '✗'

  return task.active ? '▶' : '○'
}

export function counts(tasks: ThanosTask[]) {
  const n = (mark: string) => tasks.filter(t => t.mark === mark).length

  return { done: n('x'), open: n(' '), parked: n('!'), total: tasks.length }
}

export function statusLine(m: ThanosMission): string {
  const cap = m.until_usage ? `until ${m.until_usage}% usage` : `of ${m.max_steps}`

  const gen = (m.generation ?? 1) > 1 ? ` · gen ${m.generation}` : ''

  return `${m.status} · step ${m.steps} ${cap} · Opus ${m.opus_used}/${m.max_opus}${gen}`
}
