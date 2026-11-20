---
name: triage
description: Diagnoses failing, flaky or slow tests in Java, Kotlin and JavaScript - reads the report, classifies the cause (code bug, test bug, flaky, environment, configuration, build), reproduces it and proposes the smallest fix. Use whenever a test fails, is intermittent, passes locally but fails in CI, or the suite got slower, even when the cause looks obvious. Triggers on "este test falla a veces", "flaky test", "falla solo en CI".
argument-hint: "[failing test or log]"
---

# dynamia-test:triage

Do not guess from the red line. Read the evidence, classify, reproduce, then fix the **cause**. Never "fix" by deleting the assertion, adding a sleep, raising a timeout, or disabling the test without saying so.

## 1. Read the evidence
- **Maven**: console summary plus `target/surefire-reports/*.txt` (unit) and `target/failsafe-reports` (integration); use `-DtrimStackTrace=false` to see the full trace. **Gradle**: `build/reports/tests/test/index.html` and `build/test-results/`. **Vitest/Playwright**: the CLI output; Playwright's HTML report and trace (`--trace on`).
- Find the **first** failure (later ones are often consequences). Note: test name, exception type, message, the line in the test and the line in production code, environment (JDK, OS, CI vs local), and whether it is new (what changed: `git log`, `git diff` since the last green run).

## 2. Classify
| Class | Signs | Next step |
|---|---|---|
| **Code bug** | deterministic, assertion shows wrong value, fails after a specific change | fix production code; keep the test |
| **Test bug** | wrong expectation, depends on order/time/data, mocks diverge from reality | fix the test; explain what it assumed |
| **Flaky** | passes and fails with no change; timing, ordering, shared state, randomness, ports, async | reproduce with repetition; find the race or the shared resource |
| **Environment** | passes locally, fails in CI/other machine: time zone, locale, file paths, case-sensitive FS, memory, missing Docker, network, CPU count | compare environments; make the test independent of it |
| **Configuration** | wrong profile/properties, missing bean, context fails to start, wrong test scope | read the first `Caused by`; check config and test resources |
| **Build/dependency** | `NoSuchMethodError`, `ClassNotFoundException`, version conflicts, stale artifacts, annotation processing not run | `dependency:tree`, clean build, check BOM/versions |
| **Infrastructure** | container did not start, port in use, DB not ready, out of disk | check logs of the service, waits, resource limits |

## 3. Reproduce and isolate
- Run the single test: Maven `mvn -Dtest=Class#method test` (or `-Dit.test=` for Failsafe), Gradle `--tests`, Vitest `-t`, Playwright by file/title.
- Repeat to expose flakes: a loop of 20 to 50 runs, JUnit `@RepeatedTest`, Playwright `--repeat-each=20`, parallel on/off (`--workers=1` / single fork), different order (randomize or reverse).
- Bisect: `git bisect run <test command>` for a regression; delete half the setup to find the interacting test.
- Run in the same conditions as CI (same JDK, time zone `TZ`, locale, `--no-daemon`, container) when it only fails there.

## 4. Typical causes worth checking first
Time and time zones (`LocalDate.now()`, daylight saving, midnight crossing), locale-dependent formatting, unordered collections (`HashMap`/`Set` iteration, unsorted SQL), shared static state or singletons, database rows left by other tests, auto-increment ids assumed, port or temp-file collisions, async work not awaited, test order, floating-point equality, lazy-loading outside a transaction, mock stubbing mismatches, a fixture reused after mutation, dependence on the network or the real clock, slow machines with tight timeouts.

## 5. Fix and prove
1. Smallest change at the cause. 2. A test that fails without the fix (if the bug was in production code). 3. Re-run: the single test, its class, the module, then the CI command. 4. For flakes, run the repetition loop again and report the count (for example 50/50 green). 5. If you must quarantine a flaky test, tag it, link a ticket and a deadline: never leave a silent `@Disabled`.

## Slow suites
Measure first (Surefire/Gradle test timings, Vitest `--reporter=verbose`, Playwright report); look for container startup per class, full Spring contexts, sleeps, repeated expensive fixtures, serial e2e; fix by sharing containers/contexts, moving checks down a level, and parallelizing isolated tests.

## Optional pointers
In a Dynamia multi-repo workspace the `dynamia` plugin has a cheap `test-triage` agent and `/dynamia:test`; if installed (listed among skills/agents) it can do the first pass, otherwise suggest `/plugin install dynamia@dynamia-tools` once. Tenant and OSIV pitfalls: `/dynamia-platform:backend` `references/testing.md` if installed.

## Report
Cause class, evidence (`file:line`, log line), the fix or next step, the commands run with results, and what remains unverified.
