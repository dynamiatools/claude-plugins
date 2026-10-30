export type Kind = 'work' | 'pr' | 'done'
export type Ref = { n: number; kind: Kind; branch?: string }

const RANK: Record<Kind, number> = { work: 0, pr: 1, done: 2 }

const GH_ISSUE = /\bgh\s+issue\s+(view|comment|edit|develop|close|reopen)\s+(?:\S*\/issues\/|#)?(\d{1,6})\b/g
const CLOSING = /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d{1,6})\b/gi
const NEW_BRANCH = /\bgit\s+(?:switch\s+-c|checkout\s+-b|branch)\s+(?:-\S+\s+)*(\S+)/
const BRANCH_ISSUE = /^(?:[a-z]+\/)?(?:issue-?)?(\d{1,6})(?:[-_]|$)/i
const COMMIT_REF = /#(\d{1,6})\b/g

// The issues a shell command points at, the strongest state per issue.
export const issueRefs = (command: string): Ref[] => {
  const found = new Map<number, Ref>()
  const add = (ref: Ref) => {
    const old = found.get(ref.n)
    if (old === undefined || RANK[ref.kind] > RANK[old.kind]) found.set(ref.n, { ...old, ...ref })
  }

  for (const m of command.matchAll(GH_ISSUE)) {
    add({ n: Number(m[2]), kind: m[1] === 'close' ? 'done' : 'work' })
  }
  if (/\bgh\s+pr\s+create\b/.test(command)) {
    for (const m of command.matchAll(CLOSING)) add({ n: Number(m[1]), kind: 'pr' })
  }
  const branch = command.match(NEW_BRANCH)?.[1]
  const fromBranch = branch === undefined ? undefined : branch.match(BRANCH_ISSUE)?.[1]
  if (branch !== undefined && fromBranch !== undefined) add({ n: Number(fromBranch), kind: 'work', branch })
  if (/\bgit\s+commit\b/.test(command)) {
    for (const m of command.matchAll(COMMIT_REF)) add({ n: Number(m[1]), kind: 'work' })
  }

  return [...found.values()]
}

// "git@github.com:o/r.git" or "https://github.com/o/r" -> "o/r"
export const repoOf = (remote: string): string | undefined =>
  remote.trim().match(/github\.com[:/]([^/\s]+\/[^/\s]+?)(?:\.git)?\/?$/)?.[1]

export const ago = (ms: number): string => {
  const min = Math.floor(ms / 60_000)
  if (min < 1) return 'now'
  if (min < 60) return `${min}m`
  return min < 1440 ? `${Math.floor(min / 60)}h` : `${Math.floor(min / 1440)}d`
}

// Cuts text to `max` cells, ending in an ellipsis.
export const clip = (text: string, max: number): string =>
  max <= 1 ? '' : text.length <= max ? text : `${text.slice(0, max - 1)}…`

export const bar = (done: number, total: number, width: number): string => {
  const filled = total === 0 ? 0 : Math.round((done / total) * width)
  return '▰'.repeat(filled) + '▱'.repeat(width - filled)
}
