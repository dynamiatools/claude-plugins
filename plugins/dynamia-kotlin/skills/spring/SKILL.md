---
name: spring
description: Kotlin with Spring Boot 4 - kotlin-spring and kotlin-jpa plugins, runApplication, constructor-bound properties as data classes, JPA entities, Jackson Kotlin module, JSpecify null-safety, JUnit with Mockito or MockK. Use when adding Kotlin to a Spring Boot or Dynamia application, writing Spring code in Kotlin, or fixing proxy, JPA or JSON problems in Kotlin.
argument-hint: "[file or topic]"
---

# dynamia-kotlin:spring

Spring Boot 4 requires **Kotlin 2.2 or later** and manages the Kotlin version (Maven: property `kotlin.version`; Gradle: the Spring Boot plugin aligns it). It needs `kotlin-stdlib` and `kotlin-reflect`. Read the Spring Boot reference "Kotlin support" for the current text.

## Setup that avoids the usual failures
- **`kotlin-spring` (all-open)** opens classes annotated with Spring stereotypes so proxies work (Kotlin classes are final). Without it: "class is final" errors, `@Transactional` and `@Configuration` not applied.
- **`kotlin-jpa` (no-arg)** gives `@Entity`, `@Embeddable`, `@MappedSuperclass` a synthetic no-arg constructor; add **all-open for JPA** (`allOpen { annotation("jakarta.persistence.Entity") ... }`) when you need lazy proxies.
- Compiler flag `-Xannotation-default-target=param-property` (recommended by Spring Boot) to avoid warnings from Kotlin 2.2 annotation defaulting. Spring projects declare nullability with JSpecify annotations, which Kotlin enforces strictly since 2.1.
- Jackson's Kotlin module is required for JSON and is auto-registered when present. Boot 4 uses Jackson 3 (`tools.jackson`): use the Jackson 3 Kotlin module artifact and check its coordinates in the Boot BOM.
- Maven layout: `<sourceDirectory>src/main/kotlin</sourceDirectory>`, `<testSourceDirectory>src/test/kotlin</testSourceDirectory>`, `kotlin-maven-plugin` with the `spring`/`jpa` compiler plugins; for mixed Java/Kotlin modules compile Kotlin first (default) so Java can see Kotlin classes. With Kotlin 2.4 the Maven plugin can derive `jvmTarget` from `maven.compiler.release` when `<extensions>true</extensions>`.

## Code
```kotlin
@SpringBootApplication
class App
fun main(args: Array<String>) { runApplication<App>(*args) }

@ConfigurationProperties("payments")
data class PaymentsProperties(val baseUrl: URI, val apiToken: String, val timeout: Duration = Duration.ofSeconds(10))
```
- Constructor binding with immutable `data class` for properties; value classes have **limited** binding support (defaults do not bind): use plain types. Configuration metadata via kapt + `spring-boot-configuration-processor` (defaults and deprecation detection do not work with kapt).
- Constructor injection with `val` parameters; one constructor; no `@Autowired` field injection or `lateinit` for dependencies.
- Controllers and services: expressions, `when`, extension functions for mapping entities to response data classes; return DTOs, never entities.
- **JPA entities in Kotlin**: plain `class` (not `data class`), `var` properties with sensible defaults or nullable ids (`var id: Long? = null`), open for proxying, `equals`/`hashCode` on the id or business key as for Java (`dynamia-java:hibernate`), no `toString` that touches lazy collections. Avoid non-null fields initialized to fake values just to satisfy the compiler.
- `Optional` from Java repositories: use Kotlin nullability (`findByXxx(): T?` in Spring Data).
- Coroutines in Spring MVC or WebFlux: `suspend` controller functions are supported; see `dynamia-kotlin:coroutines`.

## Testing
- JUnit: Boot 4 provides **JUnit Jupiter 6** by default (6.0.3 in the 4.0.5 and 4.1.1 BOMs; the Spring Boot Kotlin reference notes the per-class lifecycle that lets `@BeforeAll` be non-static); a project may pin 5.x on purpose: follow its build file.
- Mocking: **MockK** is Spring's recommendation for Kotlin classes, with **SpringMockK** (`@MockkBean`, `@SpykBean`); **Mockito** works too (`@MockitoBean`, `mockito-kotlin`). Consistency wins: a Dynamia ERP Kotlin module chose JUnit + Mockito to match the rest of its repo. Don't introduce a second mocking library without the team agreeing.
- `kotlin-test-junit5` for assertions; `@AutoConfigureMockMvc` is explicit in Boot 4; slices and `RestTestClient` as in `dynamia-java:spring-boot`.
- Test names in backticks are fine (`fun \`rejects expired token\`()`), keep them short.

## Dynamia Platform
Kotlin modules inside Dynamia applications follow the application's conventions (packages, `@Provider`, `CrudService`). Entities that extend `BaseEntity` need the open/no-arg plugins and Java-style classes. Details: if `dynamia-platform` is installed (skills listed as `/dynamia-platform:*`) use `/dynamia-platform:backend`; otherwise suggest `/plugin install dynamia-platform@dynamia-tools` for Dynamia projects. Not verified: that every Dynamia annotation processing step works with Kotlin classes; test one entity end to end.

End with one line: Boot and Kotlin versions assumed, what built and ran, what was not tested.
