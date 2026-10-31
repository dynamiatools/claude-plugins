/** A pasted image as the mod read it: its file, format, size and pixel shape, or why it has no preview. */
export type Picture = { file: string; format: string; bytes: number; width: number; height: number } | { error: string }

/** The card of a path under a reply: what it is, and its lines or entries. */
export type Peek = {
  path: string
  kind: 'file' | 'dir'
  size: number
  mtimeMs: number
  /** The line the reply named, lit in the card. */
  line?: number
  /** The file's line count and the lines the card shows. */
  total?: number
  lines?: { n: number; text: string }[]
  /** The first entries of a folder. */
  entries?: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'hover-preview': {
      /** The `[Image #N]` ids in the prompt box, in the order typed. */
      draft: number[]
      /** Each image read so far, by id. */
      pictures: Record<string, Picture>
      /** The id whose card is open; null while none is. */
      shown: number | null
      /** The card of the path the pointer is on; null while none is. */
      peek: Peek | null
    }
  }
}
