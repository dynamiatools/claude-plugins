/** A picture decoded to 8-bit RGBA, row-major from the top-left pixel. */
export type Pixels = { width: number; height: number; data: Uint8Array }

const UPPER_HALF = 0x2580 // ▀
const SPACE = 0x20
const DEFAULT_COLOR = 0x01000000

/** Reads an uncompressed 24- or 32-bit BMP, the kind ImageMagick (`BMP3:`) and `sips` write. */
export function parseBmp (bytes: Uint8Array): Pixels {
  if (bytes.length < 54 || bytes[0] !== 0x42 || bytes[1] !== 0x4d) throw new Error('not a BMP file')
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const offset = view.getUint32(10, true)
  const width = view.getInt32(18, true)
  const signedHeight = view.getInt32(22, true)
  const bits = view.getUint16(28, true)
  const compression = view.getUint32(30, true)
  const height = Math.abs(signedHeight)

  if (width <= 0 || height === 0) throw new Error('an empty BMP')
  if (bits !== 24 && bits !== 32) throw new Error(`a ${bits}-bit BMP`)
  if (compression !== 0) throw new Error('a compressed BMP')
  const stride = Math.ceil((width * bits) / 32) * 4
  if (offset + stride * height > bytes.length) throw new Error('a truncated BMP')

  const step = bits / 8
  const data = new Uint8Array(width * height * 4)
  for (let y = 0; y < height; y++) {
    const start = offset + (signedHeight < 0 ? y : height - 1 - y) * stride
    for (let x = 0; x < width; x++) {
      const at = start + x * step
      const out = (y * width + x) * 4
      data[out] = bytes[at + 2]!
      data[out + 1] = bytes[at + 1]!
      data[out + 2] = bytes[at]!
      // shortcut: the alpha byte of a 32-bit BMP is unreliable (writers leave zeros), so the picture is opaque; revisit if transparent PNGs matter.
      data[out + 3] = 255
    }
  }
  return { width, height, data }
}

/**
 * The largest box of cells within the bounds that keeps the picture's shape. A cell is about
 * twice as tall as it is wide, and holds two rows of pixels.
 */
export function fit (width: number, height: number, maxColumns: number, maxRows: number) {
  const columnsCap = Math.max(1, Math.min(maxColumns, width))
  let columns = columnsCap
  let rows = Math.max(1, Math.round((columns * height) / width / 2))
  if (rows > maxRows) {
    rows = Math.max(1, maxRows)
    columns = Math.max(1, Math.min(columnsCap, Math.round((rows * 2 * width) / height)))
  }
  return { columns, rows }
}

// Light adds up in linear terms, not in the gamma-encoded bytes: averaging the bytes darkens a
// light line on a dark ground until it is gone.
const LINEAR = Float64Array.from({ length: 256 }, (_, i) => {
  const value = i / 255
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
})
const encode = (linear: number) => {
  const value = Math.min(1, Math.max(0, linear))
  return Math.round(255 * (value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055))
}

/** The average color of the pixels under the box `[x0, x1) × [y0, y1)`, in linear light, as 0x00RRGGBB. */
function average ({ width, data }: Pixels, x0: number, x1: number, y0: number, y1: number) {
  let r = 0
  let g = 0
  let b = 0
  let count = 0
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const at = (y * width + x) * 4
      r += LINEAR[data[at]!]!
      g += LINEAR[data[at + 1]!]!
      b += LINEAR[data[at + 2]!]!
      count++
    }
  }
  return count === 0 ? DEFAULT_COLOR : (encode(r / count) << 16) | (encode(g / count) << 8) | encode(b / count)
}

/**
 * The picture as a `Raster`'s cells: `columns × rows` upper half blocks, the foreground the color
 * of the cell's top half and the background that of its bottom half.
 * shortcut: half blocks only; midudev's image-preview picks the best of 20 block shapes per cell for sharper text, revisit if screenshots look too coarse.
 */
export function toCells (pixels: Pixels, columns: number, rows: number): string {
  const { width, height } = pixels
  const words = new Uint32Array(columns * rows * 3)
  const down = rows * 2
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const x0 = Math.floor((column * width) / columns)
      const x1 = Math.max(x0 + 1, Math.floor(((column + 1) * width) / columns))
      const top0 = Math.floor((row * 2 * height) / down)
      const top1 = Math.max(top0 + 1, Math.floor(((row * 2 + 1) * height) / down))
      const bottom0 = top1
      const bottom1 = Math.max(bottom0 + 1, Math.floor(((row * 2 + 2) * height) / down))
      const at = (row * columns + column) * 3
      words[at] = height === 0 ? SPACE : UPPER_HALF
      words[at + 1] = average(pixels, x0, x1, top0, Math.min(top1, height))
      words[at + 2] = average(pixels, x0, x1, Math.min(bottom0, height - 1), Math.min(bottom1, height))
    }
  }
  return new Uint8Array(words.buffer).toBase64()
}
