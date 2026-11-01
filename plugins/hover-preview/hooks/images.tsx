import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import { fit, parseBmp, toCells } from './pixels'
import type { Pixels } from './pixels'
import type { Picture } from '../types'

type Engine = EngineInterface

const draft = atom({ plugin: 'hover-preview', key: 'draft' } as const, [] as number[])
const pictures = atom({ plugin: 'hover-preview', key: 'pictures' } as const, {} as Record<string, Picture>)
const shown = atom({ plugin: 'hover-preview', key: 'shown' } as const, null as number | null)

const TOKEN = /\[Image #(\d+)\]/g
const NOT_STORED = 'not stored in this session'
// The longest side a picture is shrunk to before it is sampled into cells.
const SOURCE_PIXELS = 800
const MAX_COLUMNS = 120
const MAX_ROWS = 30
// Pasting an image puts its placeholder in the box with no edit event: the box is looked at this often.
const POLL_MS = 500
const WAIT_MS = 200
const WAIT_TRIES = 15

/** The ids of the `[Image #N]` placeholders in a text, each once, in order. */
export const idsIn = (text: string) => [...new Set([...text.matchAll(TOKEN)].map(match => Number(match[1])))]

const sameIds = (a: readonly number[], b: readonly number[]) => a.length === b.length && a.every((id, i) => id === b[i])

const sizeOf = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

let sessionId: string | undefined
let folder: string | undefined
let draftIds: number[] = []
let poll: { cancel: () => void } | undefined
// The pictures read, shrunk, by id; the cells drawn of them, by id and size.
const thumbs = new Map<number, Pixels>()
const loading = new Set<number>()
const cells = new Map<string, string>()

/** Forgets what was read in another session: after /clear the ids start again from 1. */
async function follow ($: Engine) {
  const id = await $.session.id()
  if (id === sessionId) return
  sessionId = id
  folder = undefined
  thumbs.clear()
  loading.clear()
  cells.clear()
  await update($, pictures, () => ({}))
  await update($, shown, () => null)
}

/**
 * Claude Code's temp folder for this session, where a pasted image is stored as
 * `images/<N>.<ext>`: `<CLAUDE_CODE_TMPDIR or /tmp>/claude-<uid>/<project path, dashed>/<session id>`.
 */
async function sessionFolder ($: Engine) {
  if (folder) return folder
  const id = await $.session.id()
  const base = ((await $.env.get('CLAUDE_CODE_TMPDIR')) || '/tmp').replace(/\/+$/, '')
  const root = `${base}/claude-${(await $.process.run(['id', '-u'])).stdout.trim()}`
  const names = new Set([await $.session.root(), await $.session.cwd()].map(path => path.replace(/[^a-zA-Z0-9]/g, '-')))
  for (const name of names) {
    if (await $.fs.exists(`${root}/${name}/${id}/images`)) return (folder = `${root}/${name}/${id}`)
  }
  // A project path too long for a folder name gets a hash after it: look for the session instead.
  for (const entry of await $.fs.list(root).catch(() => [])) {
    if (entry.kind === 'dir' && (await $.fs.exists(`${root}/${entry.name}/${id}/images`))) {
      return (folder = `${root}/${entry.name}/${id}`)
    }
  }
  return undefined
}

async function fileOf ($: Engine, id: number) {
  const found = await sessionFolder($)
  if (!found) return undefined
  const name = (await $.fs.list(`${found}/images`).catch(() => [])).find(entry => entry.name.startsWith(`${id}.`))?.name
  return name && /^\d+\.[a-z]+$/.test(name) ? `${found}/images/${name}` : undefined
}

// The converters tried in order, the first that works kept: ImageMagick 7 and 6, `sips` on macOS.
const TOOLS = ['magick', 'convert', 'sips'] as const
let tool: (typeof TOOLS)[number] | undefined

/** The picture shrunk to a 24-bit BMP at `out`, the longest side `SOURCE_PIXELS`. */
async function shrink ($: Engine, file: string, out: string) {
  for (const name of tool ? [tool] : TOOLS) {
    const argv = name === 'sips'
      ? ['sips', '-s', 'format', 'bmp', '-Z', String(SOURCE_PIXELS), file, '--out', out]
      : [name, file, '-resize', `${SOURCE_PIXELS}x${SOURCE_PIXELS}>`, `BMP3:${out}`]
    const result = await $.process.run(argv).catch(() => undefined)
    if (result?.exitCode === 0) {
      tool = name
      return
    }
  }
  throw new Error('needs ImageMagick (or sips on macOS) to read it')
}

/** Reads image `id` once: its file, then its pixels, shrunk; the drawings that wait on it redraw. */
async function load ($: Engine, id: number) {
  const all = await read($, pictures)
  if (all[id] || thumbs.has(id) || loading.has(id)) return
  const loadingIn = sessionId
  loading.add(id)
  let picture: Picture
  try {
    // The engine writes the file just after the paste puts the placeholder in the box.
    let file = await fileOf($, id)
    for (let tries = 0; !file && tries < WAIT_TRIES; tries++) {
      await $.clock.sleep(WAIT_MS)
      file = await fileOf($, id)
    }
    if (!file) throw new Error(NOT_STORED)
    const cache = `${await sessionFolder($)}/hover-preview`
    await $.process.run(['mkdir', '-p', cache])
    const out = `${cache}/${id}.bmp`
    await shrink($, file, out)
    const pixels = parseBmp(Uint8Array.fromBase64((await $.fs.read(out, { as: 'bytes' })).base64))
    if (sessionId === loadingIn) thumbs.set(id, pixels)
    picture = { file, format: file.slice(file.lastIndexOf('.') + 1), bytes: (await $.fs.stat(file)).size, width: pixels.width, height: pixels.height }
  } catch (error) {
    picture = { error: error instanceof Error ? error.message : String(error) }
  } finally {
    loading.delete(id)
  }
  if (sessionId !== loadingIn) return
  // Read in the background: a module unloaded meanwhile has no state to write to.
  await update($, pictures, now => ({ ...now, [id]: picture })).catch(() => undefined)
}

/** Opens image `id` in the system's viewer: `open` on macOS, `xdg-open` elsewhere. */
async function openImage ($: Engine, id: number) {
  const picture = (await read($, pictures))[id]
  const file = picture && !('error' in picture) ? picture.file : await fileOf($, id)
  if (!file) return
  const opener = (await $.process.run(['uname', '-s']).catch(() => undefined))?.stdout.trim() === 'Darwin' ? 'open' : 'xdg-open'
  await $.process.run([opener, file]).catch(() => undefined)
}

/** Keeps the band's list of the draft's images in step with the prompt box. */
async function track ($: Engine, text: string) {
  await follow($)
  const ids = idsIn(text)
  if (!sameIds(ids, draftIds)) {
    draftIds = ids
    await update($, draft, () => ids)
    // The box changed under the pointer: a card for an image no longer in it closes.
    await update($, shown, now => (now !== null && ids.includes(now) ? now : null))
  }
  for (const id of ids) void load($, id)
}

export const registerImages: Register = (on) => {
  on('session.start', async ($, e, next) => {
    poll?.cancel()
    poll = undefined
    const result = await next(e)
    await follow($)
    draftIds = await read($, draft)
    await track($, (await $.prompt.read()).text)
    if (e.isInteractive) {
      // A look that fails (the module unloading under it) waits for the next.
      poll = $.clock.every(POLL_MS, () => {
        void $.prompt.read().then(box => track($, box.text)).catch(() => undefined)
      })
    }
    return result
  })

  on('session.end', ($, e, next) => {
    poll?.cancel()
    poll = undefined
    return next(e)
  })

  on('prompt.edit', async ($, e, next) => {
    const box = await next(e)
    await track($, box.text)
    return box
  })

  on('prompt.submit', async ($, e, next) => {
    const result = await next(e)
    draftIds = []
    await update($, draft, () => [])
    await update($, shown, () => null)
    return result
  }).catch(($, e, next) => next(e))

  // A chip says when the pointer is on it and when it leaves: its card opens and closes. Clicked,
  // it opens the image in the system's viewer.
  on('ui.message', { element: /^chip:\d+$/ }, async ($, e, next) => {
    const result = await next(e)
    const chip = /^chip:(\d+)$/.exec(e.element)
    if (!chip) return result
    const id = Number(chip[1])
    const data = e.data as { isOver?: unknown; isClicked?: unknown } | null
    if (data?.isClicked === true) {
      void openImage($, id)
      await update($, shown, () => null)
    } else if (data?.isOver === true) await update($, shown, () => id)
    else await update($, shown, now => (now === id ? null : now))
    return result
  })

  // Above the prompt: the draft's images, each a chip that opens its card while the pointer is on
  // it. The card is drawn in the band, under the chips, so it moves nothing in the transcript.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // Off fullscreen the terminal reports no pointer: nothing could be hovered.
    if (e.surface !== 'terminal' || e.props.hasSurvey || e.viewport?.isFullscreen === false) return next(e)
    const [ids, open, all] = await Promise.all([read($, draft), read($, shown), read($, pictures)])
    if (ids.length === 0) return next(e)

    const { Box, Client, Raster, Text } = $.ui.resolve(e)
    const below = await next(e)
    let card = null
    if (open !== null) {
      const picture = all[open]
      const label = `[Image #${open}]`
      if (!picture || (!('error' in picture) && !thumbs.has(open))) card = <Text dimColor>{label} loading…</Text>
      else if ('error' in picture) card = <Text dimColor wrap="truncate-end">{label} no preview: {picture.error}</Text>
      else {
        const bounds = { columns: Math.max(8, Math.min(MAX_COLUMNS, e.props.bodyColumns) - 2), rows: Math.max(2, Math.min(MAX_ROWS, e.props.maxRows - 4)) }
        const { columns, rows } = fit(picture.width, picture.height, bounds.columns, bounds.rows)
        const key = `${open}:${columns}x${rows}`
        let painted = cells.get(key)
        if (painted === undefined) cells.set(key, (painted = toCells(thumbs.get(open)!, columns, rows)))
        card = (
          <Box key={`card-${open}`} flexDirection="column" borderStyle="round" borderDimColor flexShrink={0} alignSelf="flex-start">
            <Raster key={`image-${open}`} columns={columns} rows={rows} cells={painted} />
            <Text dimColor wrap="truncate-end">{label} {picture.format.toUpperCase()} · {sizeOf(picture.bytes)} · {picture.width}×{picture.height}</Text>
          </Box>
        )
      }
    }
    return (
      <Box flexDirection="column">
        {below}
        <Box flexDirection="row" columnGap={1} position="relative">
          {card && <Box position="absolute" bottom={1} left={0}>{card}</Box>}
          {ids.map(id => <Client key={`chip:${id}`} module="./chip.tsx" props={{ label: `[Image #${id}]` }} />)}
          <Text dimColor>hover to preview · click to open</Text>
        </Box>
      </Box>
    )
  })
}
