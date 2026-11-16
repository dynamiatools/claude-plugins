import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'dynamia',
  component: 'Pane',
  requestId: 'dynamia-thanos',
  props: { title: 'THANOS', isFocused: false, bodyColumns: 40, placement: 'dock', scroll: { offset: 0, bodyRows: 24 }, view: {} },
} as const

const mission = { batch: 'b1', branch: 'feat/b1', goal: 'ship the thing', status: 'working', steps: 2, max_steps: 30, until_usage: 0, opus_used: 1, max_opus: 3, blockers: 1 }
const stored = {
  mission,
  tasks: [
    { mark: 'x', size: 'S', text: 'db: schema', active: false },
    { mark: ' ', size: 'M', text: 'api: endpoints', active: true },
    { mark: '!', size: 'S', text: 'mail: smtp', active: false },
  ],
  decisions: ['use sqlite'],
  failed: [],
  blockers: ['ssh was refused'],
  usage: 72,
  procs: [{ name: 'web', pid: 11, alive: true, cmd: 'pnpm dev' }],
  last_block: { c: 'git push origin next', why: 'not its own branch', t: 1 },
}

test('the pane lists the tasks of the mission on every surface', async ($, on) => {
  on('state.get', () => ({ value: { value: stored, version: 1 } }))

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /THANOS · b1/ }))?.text).toContain('b1')
    expect((await ui.find({ type: 'Text', text: /api/ }))?.text).toContain('▶')
    expect((await ui.find({ type: 'Text', text: /mail/ }))?.text).toContain('✗')
    expect((await ui.find({ type: 'Text', text: /ssh was refused/ }))?.text).toBe('ssh was refused')
    expect((await ui.find({ type: 'Text', text: /plan usage 72%/ }))?.text).toContain('72')
    expect((await ui.find({ type: 'Text', text: /web running/ }))?.text).toContain('pnpm dev')
    expect((await ui.find({ type: 'Text', text: /git push origin next/ }))?.text).toContain('next')
    await ui.unmount()
  }
})

test('with no mission the pane says how to start one', async ($, on) => {
  on('state.get', () => ({ value: { value: null, version: 1 } }))

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /No mission/ }))?.text).toContain('thanos start')
  await ui.unmount()
})
