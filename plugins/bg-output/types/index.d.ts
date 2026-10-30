export type Job = { id: string; command: string; file: string; tail: string; changedAt: number; startedAt: number }

declare module 'claude-code' {
  interface PluginState {
    'bg-output': { jobs: Shaped<Job[]> }
  }
}
