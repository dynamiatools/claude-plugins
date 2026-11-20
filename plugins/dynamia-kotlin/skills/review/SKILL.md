---
name: review
description: Reviews Kotlin code for null-safety, idiom, immutability, Java interop, coroutine leaks, error handling, serialization and persistence problems, and reports findings with file and line. Use when asked to review a Kotlin change, class or module, before a commit or pull request, or to audit Kotlin code for bugs and risks. Triggers on "revisa este código Kotlin", "review my Kotlin".
argument-hint: "[path or diff]"
---

# dynamia-kotlin:review

Review the change the user names; read the surrounding code and callers first. Report only what you can point to. This complements the general `code-review` skill.

## What to check (priority order)
1. **Correctness**: `==` vs `===`, mutable default arguments shared between calls, `copy()` of data classes carrying secrets or ids, ranges and off-by-one (`until` vs `..`), integer overflow on `Int` money or sizes, `BigDecimal` equality (`compareTo`), time zones, `when` with `else` hiding a new case.
2. **Null-safety**: `!!`, unchecked platform types from Java, `lateinit` on domain state, `as` casts instead of `as?`, nullable ids treated as present, `Optional` leaking from Java APIs.
3. **Errors**: `runCatching`/`catch (Exception)` swallowing failures (and `CancellationException`), exceptions for control flow, `Result` ignored, `error(...)` messages without context, secrets inside exception messages.
4. **Coroutines** (`dynamia-kotlin:coroutines`): `GlobalScope`, `runBlocking` in server paths, blocking calls on `Default`, missing timeouts, orphan `launch`, shared mutable state without `Mutex`, `Flow` collected without an owner.
5. **Immutability and design**: `var` and mutable collections in public APIs, `data class` used for JPA entities, god `object`s with state, long extension-function chains that hide behavior, DSLs without need, files mixing unrelated things.
6. **Interop and frameworks**: classes that must be open (Spring, JPA) without the compiler plugins, missing `@Jvm*` for Java callers, `@Throws` missing, jackson/serialization of nullable and default properties, `@Serializable` polymorphism without a sealed hierarchy, value classes with frameworks.
7. **Persistence** (Exposed): transactions around remote calls, unbounded queries, N+1 in loops, `SchemaUtils` in production code, schema changes without a migration, money as `Double` (`dynamia-kotlin:ktor-exposed`).
8. **Security**: injection (SQL/JPQL string templates), secrets in logs/`toString` of data classes, missing authorization on routes, unsafe deserialization, weak randomness (`Random` vs `SecureRandom`), timing-unsafe secret comparison.
9. **Performance**: sequences vs lists misuse, boxing in hot paths, repeated regex compilation, work inside loops, loading everything in memory.
10. **Tests**: new behavior without a test, assertions on mocks only, real clocks/randomness, suspend code tested with `Thread.sleep`.

## Report
Group by severity: **Bug / security**, **Risk**, **Improvement**. One line each: `file:line`, the problem, the fix. Then "Not verified" (what needs running, profiling or a real database). If asked, apply fixes in small steps with tests. No praise filler; if nothing is wrong, say so.

End with one line: what was reviewed, what was not run.
