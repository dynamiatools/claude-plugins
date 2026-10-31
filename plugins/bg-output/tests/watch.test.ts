import { test, expect } from 'claude-code/testing'

import { isDetached, isWatched, logFileOf } from '../hooks/watch'

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

test('finds the log of a nohup command', () => {
  expect(isDetached('nohup java -jar app.jar > app.log 2>&1 &')).toBe(true)
  expect(isDetached('echo nohup')).toBe(false)
  expect(logFileOf('nohup java -jar app.jar > app.log 2>&1 &', '/p')).toBe('/p/app.log')
  expect(logFileOf('nohup ./run.sh >> /tmp/run.log 2>&1 &', '/p')).toBe('/tmp/run.log')
  expect(logFileOf('cd app && nohup mvn spring-boot:run &> out.log &', '/p')).toBe('/p/app/out.log')
})

test('uses nohup.out when nothing is redirected, and ignores /dev/null', () => {
  expect(logFileOf('nohup node server.js &', '/p')).toBe('/p/nohup.out')
  expect(logFileOf('nohup node server.js > /dev/null 2>&1 &', '/p')).toBe('/p/nohup.out')
  expect(logFileOf('node server.js > a.log', '/p')).toBeNull()
})
