---
name: jvm
description: Writes and fixes JVM tests - JUnit Jupiter 6, AssertJ, Mockito 5, Spring Boot 4 slices and MockMvc, Testcontainers, Awaitility, Surefire and Failsafe or Gradle setup, Kotlin tests. Use whenever the user asks to write, run or fix Java or Kotlin tests, even a single small one, or to test Spring, JPA or REST code, because it holds the conventions to follow. Triggers on "escribe tests para este servicio", "write unit tests", "agrega un test".
argument-hint: "[class or test]"
---

# dynamia-test:jvm

Versions here were read on 2026-10-23: JUnit **6.x** (Platform, Jupiter and Vintage share one version; Java 17 and Kotlin 2.1 minimum), Mockito 5.24.0, JaCoCo 0.8.14 (Java 25) or 0.8.15 (Java 26), Spring Boot 4.0/4.1 BOMs manage JUnit Jupiter 6.0.3. Always follow the versions the project's build file pins.

## Stack
| Need | Use |
|---|---|
| Test framework | JUnit Jupiter: `@Test`, `@Nested`, `@ParameterizedTest` (`@CsvSource`, `@MethodSource`, `@EnumSource`), `@TempDir`, `@Tag`, lifecycle `@BeforeEach`/`@AfterEach` |
| Assertions | AssertJ (`assertThat(x).isEqualTo(..)`, `assertThatThrownBy`), or JUnit `assertAll`/`assertThrows`; `kotlin-test` in Kotlin |
| Mocks | Mockito (`@ExtendWith(MockitoExtension.class)`, strict stubs) or MockK/SpringMockK in Kotlin; follow the project, do not mix without agreement |
| Async | Awaitility (`await().atMost(..).untilAsserted(..)`), never `sleep` |
| HTTP stubs | an in-process fake or WireMock for third-party APIs; `MockMvc`/`RestTestClient` for your own endpoints |
| Real services | **Testcontainers** for databases, brokers, object stores |
| Time | inject `java.time.Clock` (`Clock.fixed`), pass `ZoneId` explicitly |

## JUnit 6 notes (from the official release notes)
- Removed: `junit-platform-runner` and `junit-platform-jfr`; deprecated: `org.junit.jupiter.migrationsupport` (JUnit 4 rules), `JRE.OTHER`, old `ForkJoinPool` constructors. Vintage (JUnit 4 engine) still runs old tests but warns; `junit.vintage.discovery.issue.reporting.enabled=false` silences it.
- `@Nested` classes run in a **deterministic order** and inherit `@TestMethodOrder`: do not rely on a previous order.
- `@CsvSource`/`@CsvFileSource` use FastCSV (check quoting edge cases). Nullability annotations are JSpecify.
- New: Kotlin `suspend` test methods; `--fail-fast` in the console launcher; a worker-pool executor for parallel execution (`junit.jupiter.execution.parallel.config.executor-service`); built-in `@DefaultLocale`, `@DefaultTimeZone` and a configurable `@TempDir` cleanup.
- Upgrading from 5: Java 17+; replace removed artifacts; run the suite; fix order assumptions in `@Nested`.

## Spring Boot 4 tests
- Prefer plain unit tests; then slices: `@WebMvcTest` (controllers), `@DataJpaTest` (repositories), `@JsonTest`; a full `@SpringBootTest` only for wiring and a few flows.
- Boot 4 changes: `@MockitoBean`/`@MockitoSpyBean` replace `@MockBean`/`@SpyBean`; add `@AutoConfigureMockMvc` explicitly; `RestTestClient` (`@AutoConfigureRestTestClient`) is new; `TestRestTemplate` needs `@AutoConfigureTestRestTemplate` and `spring-boot-resttestclient`; each technology has a `spring-boot-starter-<tech>-test` starter (for example security tests need `spring-boot-starter-security-test`).
- Test the web layer for: status codes, validation errors (ProblemDetail), serialization, security (unauthenticated, wrong role, wrong tenant), pagination.
- Keep the context cache hot: avoid `@MockitoBean` and `@DirtiesContext` sprawl that creates a new context per class.

## Persistence tests
- Use the same database engine as production (Testcontainers) for SQL, constraints, locking, JSON/array types and migrations (Flyway/Liquibase applied to a clean database **and** to the previous release's schema).
- Testcontainers 2.x: the `testcontainers-` prefix was added to module artifact ids (for example `testcontainers-postgresql`), container classes live in `org.testcontainers.<module>` packages, and JUnit 4 rule support was dropped (use the Jupiter `@Testcontainers`/`@Container` extension, artifact `testcontainers-junit-jupiter`). This comes from project migration reports and the library's 2.0 notes: confirm coordinates on Maven Central before editing a build. One container per class or suite (static container), not per test.
- Test the transaction boundary: run without a test-managed transaction when you need to prove lazy-loading or commit behavior (`@Transactional` on a test hides `LazyInitializationException`; `dynamia-java:hibernate`).
- Assert the SQL you care about (statement counts for N+1) with a statement counter or logs.

## Build wiring
- **Maven**: Surefire runs unit tests (`*Test`, `*Tests`, `Test*`); Failsafe runs integration tests (`*IT`, `IT*`) in `verify`; run one: `mvn -Dtest=Class#method test`, `mvn -Dit.test=Class verify`; `-pl module -am` for a module and its dependencies; `-Dsurefire.failIfNoSpecifiedTests=false` when filtering across modules.
- **Gradle**: `useJUnitPlatform()`; separate source set or suite for integration tests; `./gradlew test --tests 'pkg.Class.method'`; `-i` for output; `--rerun` to ignore up-to-date.
- Mockito 5 uses the inline mock maker by default; on newer JDKs it can warn about dynamically loaded agents: configure Mockito as a `-javaagent` in the test JVM arguments when the warning appears (see the Mockito docs for the exact setup; not verified here).
- Parallel execution only for tests that are isolated; enable it explicitly and measure.

## Kotlin tests
`kotlin-test-junit5` (JUnit 6 compatible, check the artifact), `runTest` for coroutines (`dynamia-kotlin:coroutines`), backtick names, MockK or Mockito per project.

## Checklist before saying "tests pass"
Run the exact module command, read the summary (tests run, failures, skipped), check that new tests were actually discovered (naming/tags), and report skipped or tagged tests that did not run.

End with one line: command run and result, what was not run (integration, other modules).
