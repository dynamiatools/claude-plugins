import { test, expect } from 'claude-code/testing'

import { isWatched } from '../hooks/watch'

test('watches build and runtime commands, also behind cd and paths', () => {
  expect(isWatched('mvn -q test')).toBe(true)
  expect(isWatched('cd app && ./gradlew build')).toBe(true)
  expect(isWatched('/usr/bin/node server.js')).toBe(true)
})

test('ignores short everyday commands', () => {
  expect(isWatched('ls -la')).toBe(false)
  expect(isWatched('git status')).toBe(false)
  expect(isWatched('echo nodejs')).toBe(false)
})
