export type DevVar = { scope: string; name: string; value: string; secret: boolean }
export type Draft = { name: string; value: string; repo: string }
export type Note = { type: string; batch: string; title: string; name: string }
export type ThanosTask = { mark: string; size: string; text: string; active: boolean }
export type ThanosView = {
  mission: {
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
  tasks: ThanosTask[]
  decisions: string[]
  failed: string[]
  blockers: string[]
  usage: number | null
  procs: { name: string; pid: number; alive: boolean; cmd: string }[]
  last_block: { c: string; why: string; t: number } | null
}
export type NoteDraft = { type: string; text: string }

declare module 'claude-code' {
  interface PluginState {
    dynamia: {
      vars: DevVar[]
      repos: string[]
      draft: Draft
      message: string
      logLines: string[]
      noteRows: Note[]
      noteDraft: NoteDraft
      panelNote: string
      thanos: ThanosView | null
    }
  }
}
