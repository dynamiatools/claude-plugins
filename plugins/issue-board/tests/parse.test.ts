import { test, expect } from 'claude-code/testing'

import { ago, issueRefs, repoOf } from '../hooks/parse'

test('gh issue commands mark an issue as work, close marks it done', () => {
  expect(issueRefs('gh issue view 12 --json title')).toEqual([{ n: 12, kind: 'work' }])
  expect(issueRefs('gh issue comment #7 -b hi')).toEqual([{ n: 7, kind: 'work' }])
  expect(issueRefs('gh issue view https://github.com/o/r/issues/9')).toEqual([{ n: 9, kind: 'work' }])
  expect(issueRefs('gh issue close 12')).toEqual([{ n: 12, kind: 'done' }])
})

test('a new branch named after an issue is work and remembers the branch', () => {
  expect(issueRefs('git switch -c fix/123-login-bug')).toEqual([{ n: 123, kind: 'work', branch: 'fix/123-login-bug' }])
  expect(issueRefs('git checkout -b issue-45')).toEqual([{ n: 45, kind: 'work', branch: 'issue-45' }])
  expect(issueRefs('git switch -c feat/dynamia-promote')).toEqual([])
  expect(issueRefs('git switch -c release-2026')).toEqual([])
})

test('a pr that closes an issue moves it to pr, and the strongest state wins', () => {
  expect(issueRefs('gh pr create --title x --body "Closes #5 and fixes #6"')).toEqual([
    { n: 5, kind: 'pr' },
    { n: 6, kind: 'pr' },
  ])
  expect(issueRefs('gh issue view 5 && gh issue close 5')).toEqual([{ n: 5, kind: 'done' }])
})

test('commit messages count only on git commit; plain commands are ignored', () => {
  expect(issueRefs('git commit -m "Fix login (#31)"')).toEqual([{ n: 31, kind: 'work' }])
  expect(issueRefs('echo "see #31"')).toEqual([])
  expect(issueRefs('ls -la')).toEqual([])
})

test('repoOf reads ssh and https remotes', () => {
  expect(repoOf('git@github.com:dynamiatools/claude-plugins.git\n')).toBe('dynamiatools/claude-plugins')
  expect(repoOf('https://github.com/dynamiatools/claude-plugins')).toBe('dynamiatools/claude-plugins')
  expect(repoOf('https://gitlab.com/a/b.git')).toBeUndefined()
})

test('ago is short', () => {
  expect(ago(20_000)).toBe('now')
  expect(ago(5 * 60_000)).toBe('5m')
  expect(ago(3 * 3_600_000)).toBe('3h')
  expect(ago(2 * 86_400_000)).toBe('2d')
})
