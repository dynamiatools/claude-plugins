import { test, expect } from 'claude-code/testing'

import { fit, parseBmp, toCells } from '../hooks/pixels'

/** A 24-bit bottom-up BMP of `rows` (each a list of [r, g, b]). */
function bmp (rows: number[][][]): Uint8Array {
  const height = rows.length
  const width = rows[0]!.length
  const stride = Math.ceil((width * 24) / 32) * 4
  const bytes = new Uint8Array(54 + stride * height)
  const view = new DataView(bytes.buffer)
  bytes[0] = 0x42
  bytes[1] = 0x4d
  view.setUint32(10, 54, true)
  view.setUint32(14, 40, true)
  view.setInt32(18, width, true)
  view.setInt32(22, height, true)
  view.setUint16(28, 24, true)
  rows.forEach((row, y) => row.forEach(([r, g, b], x) => {
    const at = 54 + (height - 1 - y) * stride + x * 3
    bytes[at] = b!
    bytes[at + 1] = g!
    bytes[at + 2] = r!
  }))
  return bytes
}

test('parseBmp reads a 24-bit BMP top-down into RGBA', () => {
  const pixels = parseBmp(bmp([[[255, 0, 0]], [[0, 0, 255]]]))
  expect([pixels.width, pixels.height]).toEqual([1, 2])
  expect([...pixels.data]).toEqual([255, 0, 0, 255, 0, 0, 255, 255])
})

test('parseBmp refuses what is not an uncompressed BMP', () => {
  expect(() => parseBmp(new Uint8Array(100))).toThrow('not a BMP')
  expect(() => parseBmp(new Uint8Array([0x42, 0x4d]))).toThrow('not a BMP')
})

test('fit keeps the picture shape within the bounds', () => {
  expect(fit(800, 400, 100, 50)).toEqual({ columns: 100, rows: 25 })
  expect(fit(400, 800, 100, 10)).toEqual({ columns: 10, rows: 10 })
  expect(fit(10, 10, 100, 50)).toEqual({ columns: 10, rows: 5 })
})

test('toCells draws top half as foreground and bottom half as background', () => {
  const cells = toCells(parseBmp(bmp([[[255, 0, 0]], [[0, 0, 255]]])), 1, 1)
  const words = new Uint32Array(Uint8Array.fromBase64(cells).buffer)
  expect([...words]).toEqual([0x2580, 0xff0000, 0x0000ff])
})
