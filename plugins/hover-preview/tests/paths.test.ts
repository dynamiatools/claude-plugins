import { test, expect } from 'claude-code/testing'

import { excerptOf, pathsIn, resolve } from '../hooks/paths'

test('finds absolute, home and relative paths with a line', () => {
  const found = pathsIn('See `src/app.ts:42`, ~/notes/todo.md and /etc/hosts. Also ./run.sh!')
  expect(found).toEqual([
    { target: 'src/app.ts', line: 42 },
    { target: '~/notes/todo.md' },
    { target: '/etc/hosts' },
    { target: './run.sh' }
  ])
})

test('ignores addresses and repeats', () => {
  expect(pathsIn('open https://example.com/a/b.html and a.txt then a.txt')).toEqual([{ target: 'a.txt' }])
})

test('resolve folds dots and handles home', () => {
  expect(resolve('../x/./y.ts', '/p/q', '/h')).toBe('/p/x/y.ts')
  expect(resolve('~/a', '/p', '/h')).toBe('/h/a')
  expect(resolve('~/a', '/p', undefined)).toBeUndefined()
})

test('excerptOf centers the named line and numbers from 1', () => {
  const text = Array.from({ length: 50 }, (_, i) => `l${i + 1}`).join('\n')
  const { total, lines } = excerptOf(text, 30, 12)
  expect(total).toBe(50)
  expect(lines.some(l => l.n === 30)).toBe(true)
  expect(lines).toHaveLength(12)
  expect(excerptOf(text, undefined, 5).lines[0]).toEqual({ n: 1, text: 'l1' })
})
