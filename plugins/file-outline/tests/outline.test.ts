import { test, expect } from 'claude-code/testing'

import { outlineOf } from '../hooks/outline'

test('markdown headings, outside fenced code', () => {
  const text = '# One\n\n```\n# not a heading\n```\n\n## Two ##\n'
  expect(outlineOf('a.md', text)).toEqual([
    { line: 1, depth: 0, kind: 'h', title: 'One' },
    { line: 7, depth: 1, kind: 'h', title: 'Two' }
  ])
})

test('a method sits one level under its class (a bare JS method is not listed)', () => {
  const text = 'export class Repo {\n  async save(x) {}\n  public void load() {}\n}\nfunction helper() {}\n'
  const found = outlineOf('a.ts', text)
  expect(found.map(i => [i.title, i.depth, i.kind])).toEqual([['Repo', 0, 'class'], ['load', 1, 'fn'], ['helper', 0, 'fn']])
})

test('python defs and comments', () => {
  const text = '# def fake():\nclass A:\n    def run(self):\n        pass\n'
  expect(outlineOf('a.py', text).map(i => [i.title, i.depth])).toEqual([['A', 0], ['run', 2]])
})

test('toml sections and yaml top-level keys', () => {
  expect(outlineOf('a.toml', '[a]\nx=1\n[a.b]\n').map(i => [i.title, i.depth])).toEqual([['a', 0], ['a.b', 1]])
  expect(outlineOf('a.yml', 'name: x\nitems:\n  - a\n  sub: 1\n').map(i => i.title)).toEqual(['name', 'items', 'sub'])
})

test('a kind of file with no outline is empty', () => {
  expect(outlineOf('a.txt', '# hi')).toEqual([])
  expect(outlineOf('a.png', 'x')).toEqual([])
})
