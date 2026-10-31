// shortcut: edit this list to change the default whitelist; move it to userConfig if it needs a menu.
export const WATCHED = new Set([
  'mvn', 'mvnw', 'gradle', 'gradlew', 'java', 'node', 'npm', 'npx', 'pnpm', 'yarn', 'bun', 'deno',
  'docker', 'cargo', 'go', 'python', 'python3', 'pytest', 'make', 'tsc', 'vite', 'webpack',
])

// True when any word of the command, minus its directory, is a watched program.
export const isWatched = (command: string): boolean =>
  command
    .split(/[\s;&|()]+/)
    .some(word => WATCHED.has(word.replace(/^.*\//, '')))

// True when the command detaches itself from the shell (`nohup`), so Claude Code makes no
// background task for it and the pane has to follow its log file instead.
export const isDetached = (command: string): boolean => /(^|[\s;&|(])nohup\s/.test(command)

const REDIRECT = /(?:^|[\s;&|)])(?:1?>>?|&>>?)\s*(?!&)([^\s&|;<>()]+)/g

/**
 * The file a detached command writes to: its last `>`, `>>` or `&>` target (not /dev/null),
 * else the `nohup.out` that nohup creates. A relative path is taken from `cwd`, or from the
 * folder of a `cd dir &&` before it. Null when the command is not detached.
 */
export const logFileOf = (command: string, cwd: string): string | null => {
  if (!isDetached(command)) return null
  const targets = [...command.matchAll(REDIRECT)].map(match => match[1]!.replace(/^["']|["']$/g, '')).filter(path => path !== '/dev/null')
  const file = targets.at(-1) ?? 'nohup.out'
  if (file.startsWith('/')) return file
  const dir = /(?:^|[;&|]\s*)cd\s+("[^"]+"|'[^']+'|[^\s;&|]+)\s*(?:&&|;)/.exec(command)?.[1]?.replace(/^["']|["']$/g, '')
  const base = dir ? (dir.startsWith('/') ? dir : `${cwd}/${dir}`) : cwd
  return `${base.replace(/\/+$/, '')}/${file.replace(/^\.\//, '')}`
}
