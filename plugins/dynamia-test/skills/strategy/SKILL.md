---
name: strategy
description: Decides what to test and at which level, designs and reviews tests - behavior over implementation, determinism, fixtures and builders, naming, test smells - and sets a test plan for a change. Use when planning tests for a feature or bug fix, reviewing a test suite or a test file, deciding between unit, integration, contract and end-to-end tests, or when tests are slow, brittle or meaningless. Triggers on "qué debería testear", "los tests son lentos o frágiles".
argument-hint: "[change or test file]"
---

# dynamia-test:strategy

## Pick the level
| What you are proving | Level | Typical tool |
|---|---|---|
| A rule, calculation or parser with no I/O | **Unit**: fast, no framework | JUnit + AssertJ / `kotlin-test`, Vitest |
| A component with its real neighbours (database, HTTP layer, serialization, transactions, tenants) | **Integration**: one real dependency each, real database engine | Spring slices, Testcontainers, `testApplication` |
| An agreement between two systems or modules (API shape, events) | **Contract** | schema/OpenAPI checks, consumer-driven contracts, golden files |
| A user journey across the whole system | **End-to-end**: few, on the critical paths | Playwright |
| A UI component in isolation | **Component** | Vitest browser mode / Testing Library |
Put most tests where they are cheap and still catch the bug: many unit, a solid middle of integration, a handful of end-to-end. If a bug escaped, add the test at the **lowest level that reproduces it**.

## Write a test plan for a change (before code)
1. List the behaviors (inputs → observable result), including boundaries, errors, permissions and tenants/accounts.
2. For each, choose the level and the data (smallest realistic fixture).
3. Name what is deliberately **not** tested and why.
4. Decide how time, randomness, files, network and the database are controlled.
5. Write the failing test first when fixing a bug (`dynamia-craft:tdd` if that plugin is installed, otherwise: write it, watch it fail for the right reason, then fix).

## Principles
- **Test behavior, not implementation**: assert on outputs, state and visible effects; not on private methods, call order or exact log text. A refactor that keeps behavior must not break tests.
- **One reason to fail**; **arrange / act / assert** visible; the test reads as a specification (`rejectsOrderWithoutItems`, not `test1`).
- **Deterministic**: inject a `Clock`, seeded random, fixed time zone (`America/Bogota` for Colombian rules), temp dirs, no `sleep` (wait for a condition with a timeout), no dependence on test order or on data left by other tests.
- **Isolated**: each test creates what it needs and cleans up; parallel-safe (no shared mutable statics, unique ports/schemas/ids).
- **Fixtures**: test data builders / factory functions with sensible defaults and explicit overrides for what matters in the test; avoid giant shared fixtures and magic ids.
- **Mocks sparingly**: mock the boundaries you do not own (HTTP to a third party, clock, email); use real objects for your own code; prefer fakes (in-memory implementations) over deep mock chains; never mock the thing under test or value objects.
- **Real databases for persistence behavior** (constraints, locking, SQL dialects, migrations): an in-memory substitute proves less (`dynamia-test:jvm`).
- **Assertions say what is wrong**: assert on the specific value, not just "not null"; one logical assertion per test.
- **Fast feedback**: unit suite in seconds; slow tests tagged and run in their own stage.

## Smells to flag in a review
Tests that assert nothing or only that no exception was thrown; assertions on mocks only; copy-pasted tests with one changed value (use parameterized tests); `Thread.sleep`; tests that need the previous test; real network or real clock; commented-out or `@Disabled` tests without a ticket; coverage chased with getter tests; shared mutable fixtures; over-specified mocks (`verifyNoMoreInteractions` everywhere); catching `Exception` to make a test pass; test code more complex than production code.

## Reviewing a test file
Read the production code it covers first. Report: missing behaviors and boundaries, fragile coupling to implementation, nondeterminism, wrong level, unclear names, slow setup. One line each: `file:line`, the problem, the fix. End with "Not verified" (tests not run, flaky behavior not reproduced).

## Optional pointers
For Dynamia Platform projects (actions without ZK, H2 JPA config, port contracts, arch rules, tenants), see `/dynamia-platform:backend` `references/testing.md` if `dynamia-platform` is installed; otherwise suggest `/plugin install dynamia-platform@dynamia-tools` once. For Java and Kotlin specifics `/dynamia-java:spring-boot` and `/dynamia-kotlin:spring` if installed.

End with one line: the plan or findings, which tests ran, which were not run.
