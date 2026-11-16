import { describe, expect, test } from 'claude-code/testing'

import { bar, bullet, clip, counts, glyph, killArgv, panelArgv, parsePanel, splitTask, statusLine, wrap } from './thanos-view'

const mission = { batch: 'b1', branch: 'feat/b1', goal: 'g', status: 'working', steps: 3, max_steps: 30, until_usage: 0, opus_used: 1, max_opus: 3, blockers: 0 }

describe('thanos panel helpers', () => {
  test('parsePanel accepts the tool JSON and nothing else', async () => {
    const ok = parsePanel(JSON.stringify({ mission, tasks: [{ mark: 'x', size: 'S', text: 'a: b', active: false }], decisions: ['d'], failed: [], blockers: 3 }))
    expect(ok?.tasks.length).toBe(1)
    expect(ok?.decisions).toEqual(['d'])
    expect(ok?.blockers).toEqual([])
    expect(ok?.usage).toBeNull()
    expect(ok?.procs).toEqual([])
    const full = parsePanel(JSON.stringify({ mission, tasks: [], usage: 42.5, procs: [{ name: 'web', pid: 1, alive: true, cmd: 'x' }, 7], last_block: { c: 'ssh', why: 'no', t: 1 } }))
    expect(full?.usage).toBe(42.5)
    expect(full?.procs.length).toBe(1)
    expect(full?.last_block?.c).toBe('ssh')
    expect(parsePanel('{"mission":null}')).toBeNull()
    expect(parsePanel('not json')).toBeNull()
    expect(parsePanel('')).toBeNull()
  })

  test('tasks are counted, drawn and split', async () => {
    const t = (mark: string, active = false) => ({ mark, size: 'S', text: 'x', active })
    expect(counts([t('x'), t(' '), t(' ', true), t('!')])).toEqual({ done: 1, open: 2, parked: 1, total: 4 })
    expect([glyph(t('x')), glyph(t('!')), glyph(t(' ', true)), glyph(t(' '))]).toEqual(['✓', '✗', '▶', '○'])
    expect(splitTask('api: the endpoints: all')).toEqual({ name: 'api', what: 'the endpoints: all' })
    expect(splitTask('api')).toEqual({ name: 'api', what: '' })
  })

  test('text and bar fit their width', async () => {
    expect(clip('abcdef', 4)).toBe('abc…')
    expect(clip('abc', 4)).toBe('abc')
  })

  test('wrap breaks long text onto more lines', async () => {
    expect(wrap('one two three four', 9)).toEqual(['one two', 'three', 'four'])
    expect(wrap('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij'])
    expect(wrap('', 5)).toEqual([''])
    expect(bullet('uno dos tres', 8)).toBe('• uno\n  dos\n  tres')
    expect(bar(1, 4, 8)).toBe('██░░░░░░')
    expect(bar(0, 0, 4)).toBe('░░░░')
    expect(statusLine(mission)).toBe('working · step 3 of 30 · Opus 1/3')
    expect(statusLine({ ...mission, generation: 2 })).toBe('working · step 3 of 30 · Opus 1/3 · gen 2')
    expect(statusLine({ ...mission, until_usage: 80 })).toBe('working · step 3 until 80% usage · Opus 1/3')
  })

  test('the argv never goes through a shell', async () => {
    expect(killArgv('/p', 'web', 's-1')).toEqual(['/p/bin/ms-workspace', 'thanos', 'kill', 'web', '--session', 's-1'])
    expect(panelArgv('/p', 's-1')).toEqual(['/p/bin/ms-workspace', 'thanos', 'panel', '--session', 's-1'])
  })
})
