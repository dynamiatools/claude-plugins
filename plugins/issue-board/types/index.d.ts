export type Kind = 'work' | 'pr' | 'done'
export type Issue = { n: number; kind: Kind; title: string; branch: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'issue-board': { issues: Shaped<Issue[]> }
  }
}
