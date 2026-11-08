# Testing Dynamia code

Read from framework 26.10: `platform/testing` (`ui-testing`, `ui-contract`, `arch-rules`), the `domain-jpa` and `zk` tests, `JpaTestConfig`. The suite moved from JUnit 4 to **JUnit 5**. Artifacts are `tools.dynamia:tools.dynamia.ui.testing`, `tools.dynamia.ui.contract` and `tools.dynamia.arch-rules` (use `<scope>test</scope>`).

## What to test and with what
| Target | Tool |
|---|---|
| Entity, `CrudService`, queries, loading, mappers, tenant filters | JUnit 5 + `SpringExtension` + an H2 `JpaTestConfig` (below) |
| An action (logic and as a remote client) | `ActionTester` from `ui-testing` |
| A custom UI port adapter | `PortContract` suite from `ui-contract` |
| Architecture rules (ZK only in the corner, every action declared and remote-usable) | `arch-rules` |
| Pure helpers (`DateTimeUtils`, `Money`, calculators) | plain JUnit, no Spring |
| Screens | the app's e2e tool (Playwright etc.), not this framework's modules |

## JPA tests with H2
The framework's own pattern (`JpaTestConfig`): a small Spring configuration, no Spring Boot.
```java
@Configuration @EnableTransactionManagement
public class JpaTestConfig {
    @Bean DataSource dataSource() { /* H2: jdbc:h2:mem:testdb;MODE=MySQL;DB_CLOSE_DELAY=-1 */ }
    @Bean EntityManagerFactory entityManagerFactory() { /* packagesToScan = your entity package, generateDdl=true, H2Dialect */ }
    @Bean PlatformTransactionManager transactionManager() { return new JpaTransactionManager(entityManagerFactory()); }
    @Bean CrudService crudService() { return new JpaCrudService(null); }
    @Bean EntityUtilsProvider entityUtilsProvider() { return new JpaEntityUtilsProvider(); }
    @Bean ObjectContainer objectContainer() { /* a container so Containers.get() works */ }
}

@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = JpaTestConfig.class)
class OrderQueriesTest {
    @Autowired CrudService crudService;
    @Test void findsByCode() { ... }
}
```
- **Run without a test-managed transaction** (do not put `@Transactional` on the test) when you want to prove the OSIV-off behavior: the persistence context closes when the call returns, exactly like a view rendered without Open Persistence In View. `EntityMapperTest` and `LazyLoadNoTransConfigTest` do this. A `@Transactional` test hides `LazyInitializationException`.
- Test both modes for anything that touches lazy data: with and without a transaction (`loading-collections.md`).
- H2 with `MODE=MySQL` is close, not identical: test native SQL and database functions on the real database (Testcontainers).
- Tenants: bind explicitly (`AccountTenants.with(id, ...)`), assert that another tenant sees nothing, and add a case with no tenant bound (the answer must be empty, not a failure; `saas-tenancy.md`).
- Dates: fixed `LocalDate`/`Clock` values, never `now()` in assertions (`dynamia-platform:dates`).

## ActionTester: actions without ZK, browser or server
```java
ActionResult r = ActionTester.of(new DeleteAction())
        .crud(Sale.class, crudService)        // headless CRUD over a real or mock service
        .on(sale)                              // the data the action receives
        .user(u -> u.confirm(true))            // the scripted user
        .runEverywhere();

assertThat(r.types()).containsExactly(CONFIRM, NOTIFY);
```
- `run()`: direct execution as in ZK (callbacks run immediately): the logic of the action.
- `runRemote()`: through the real `ReplayExecutor`, one pass per answer, signed tokens: proves it works for a remote client.
- `runEverywhere()`: both, **failing if they differ**. An action declared `HEADLESS` must pass this (`headless-actions.md`).
- Setup: `crud(Class, crudService)` or `crud(TestCrud)`, `on(data)`, `param(name, value)`, `bean(obj)` (make a bean available to the action), `lenient()` (do not fail on unanswered questions), `user(script)`.
- The script (`UIScript`): `confirm(boolean)`, `input(value)`, `fillForm(map)`, `submitForm(editor)`, `choose(labels...)`, `chooseAt(positions...)`, `upload(files...)`, `cancel()`, `whenQuestion(predicate)` to answer a specific question (`UIScript.containing("text")`).
- The result (`ActionResult`): `types()` (the interaction/step types in order), `interactions()`, `notifications()`, `downloads()`, `redirectUrl()`, `steps()` (`ActionFlowStep`s of the remote run), `maxTokenLength()`, `exception()`/`failed()`, `crud()`, `remote()`.
- Write one test per action path: confirmed, cancelled, validation error, no permission. Assert on `types()` and on the data in the (mock) service.

## Port contracts
`ui-contract` has a suite per UI port (messages, choices incl. `pickEntity`, files incl. `preview`, clipboard, views, navigation incl. `openPage`/`refresh`, progress). To add a UI adapter (a new front end), subclass the contract of the port and implement `driver()`. The framework's own adapters run the same suites (`TestPlatform*PortContractTest`, `Replay*PortContractTest`), so behavior stays identical across ZK, tests and the REST replay.

## Architecture rules
`arch-rules` reads sources and `pom.xml` files (no build needed) as JUnit tests: R1 ZK only in the corner paths, R2 inventory of front-end-bound actions, R3 no published action bound to the front end, R4 every `@InstallAction` declares a runtime, R5 no `ZK` in neutral identifiers, R6 parity (every standard action usable by a remote client). A **baseline** lists today's violations and only shrinks: a new violation fails, and so does a fixed one still listed. Update with `-Dui.baseline.update=true`, review the diff, commit. To adopt in your repo: add the test dependency, create an `ArchRulesConfig` (`forZk(baselineDir, cornerPaths)` or the full constructor), and extend each rule class returning it.

## Rules
- Test behavior and contracts, not the framework: do not retest `CrudService.save`.
- One concern per test, named for the behavior (`rejectsAccountOfAnotherTenant`).
- No sleeping or real clocks; fixed data, in-memory stores (`InMemoryTransferStore` in `ActionTester`).
- A bug fix starts with a failing test that reproduces it.
- Say in the report which tests ran and which were not run (for example native SQL on the real database).
