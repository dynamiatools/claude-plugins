---
name: coroutines
description: Guides Kotlin coroutines on the JVM - structured concurrency, dispatchers, cancellation and timeouts, Flow, channels, shared state, runTest - and coroutines versus Java virtual threads. Use whenever Kotlin code has suspend, launch, async, GlobalScope, Flow or a coroutine scope, including a quick review or fix. Triggers on "revisa esta corrutina", "leaks a coroutine scope", "el Flow no cancela".
argument-hint: "[file or problem]"
---

# dynamia-kotlin:coroutines

Based on the official coroutines guide (structured concurrency, dispatchers, cancellation, exceptions, flows, channels, shared state). Check the `kotlinx-coroutines` version in the project (Dynamia's own Kotlin services use 1.10.x) before using a newer API.

## Coroutines or virtual threads?
| Situation | Prefer |
|---|---|
| Ktor server, Flow pipelines, cancellation trees, existing coroutine code | **coroutines** |
| Spring MVC / JDBC code in Java or Kotlin that mostly blocks | plain blocking code on **virtual threads** (`spring.threads.virtual.enabled=true`, `dynamia-java:concurrency`) |
| Mixed | keep the boundary explicit: blocking calls inside `withContext(Dispatchers.IO) { ... }`; never block a `Default` thread |
Don't wrap blocking code in `async` "to make it concurrent": measure first.

## Rules
1. **Structured concurrency**: every coroutine lives in a scope with an owner; launch from `coroutineScope { }`, a request scope or an application scope you cancel on shutdown. **No `GlobalScope`**, no fire-and-forget without a supervisor and logging.
2. **Dispatchers**: `Default` for CPU work, `IO` for blocking I/O (JDBC, files), `Main` only on UI platforms. Inject dispatchers (constructor parameter) so tests can replace them. Bound parallelism with `limitedParallelism(n)` or a `Semaphore`.
3. **Cancellation is cooperative**: long loops call `ensureActive()`/`yield()`; suspend calls are cancellation points. **Never swallow `CancellationException`**: `catch (e: Exception)` and `runCatching` catch it; rethrow it or catch narrower types.
4. **Timeouts**: `withTimeout` / `withTimeoutOrNull` around remote calls; clean up in `finally` (use `withContext(NonCancellable)` for cleanup that must suspend).
5. **Exceptions**: in `coroutineScope` a failing child cancels the siblings and the exception propagates to the caller; use `supervisorScope` when children are independent. `async` defers its exception until `await`. `CoroutineExceptionHandler` is for top-level `launch` only.
6. **Shared mutable state**: confine to one coroutine/thread, use `Mutex` (suspending, not `synchronized` around a suspend call), atomics, or immutable snapshots; `StateFlow` for observable state.
7. **Flow**: cold streams; operators are lazy; collect in a scope; `flowOn` changes the upstream dispatcher; buffer or conflate slow consumers; use `SharedFlow`/`StateFlow` for hot streams; don't `collect` inside `launch` without owning the job.
8. **Channels**: for producer/consumer handoff with backpressure; close them; prefer Flow for plain streams.
9. **Bridging**: `suspendCancellableCoroutine` for callbacks, `await()` for `CompletableFuture`, `runBlocking` only in `main` or at the edge of non-suspend code (never inside a server request path).
10. **Context**: coroutine context elements (`CoroutineName`, tenant, trace id) travel with the coroutine; `ThreadLocal` values do not follow it (use `ThreadContextElement` / `asContextElement()`).

## Testing
`kotlinx-coroutines-test`: `runTest { }` runs with virtual time (`advanceTimeBy`, `advanceUntilIdle`); inject a `StandardTestDispatcher`/`UnconfinedTestDispatcher`; test cancellation and timeouts explicitly; assert on `Flow` with `toList()` or `first()`; Ktor handlers via `testApplication` (`dynamia-kotlin:ktor-exposed`).

## Review checklist
- [ ] Every launched coroutine has an owner scope; none in `GlobalScope`.
- [ ] No blocking call on `Default`/`Main`; blocking JDBC/IO wrapped in `Dispatchers.IO`.
- [ ] `CancellationException` rethrown; no blanket `catch (Exception)` around suspend code.
- [ ] Timeouts on remote calls; resources closed in `finally`.
- [ ] No `runBlocking` in request handlers; no `synchronized` around suspend calls.
- [ ] Shared state guarded; `Flow` collection owned and cancelled.
- [ ] Tests use `runTest` with injected dispatchers.

End with one line: dispatchers and scopes involved, what was not tested under load.
