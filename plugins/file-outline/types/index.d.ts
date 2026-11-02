/** One entry of an outline: its line, its depth (0 is the top), its kind and its title. */
export type Item = { line: number; depth: number; kind: string; title: string }

declare module 'claude-code' {
  interface PluginState {
    'file-outline': {
      /** The file the pane shows, and its outline. */
      file: string | null
      items: Item[]
    }
  }
}
