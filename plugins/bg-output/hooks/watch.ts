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
