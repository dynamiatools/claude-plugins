---
name: backend
description: Dynamia Platform backend patterns for any project using tools.dynamia.* - entities extending BaseEntity, CrudService and QueryParameters, ModuleProvider and CrudPage navigation, actions, validators, CrudServiceListener, ViewCustomizer and the YAML view descriptors (form, table, tree, json, crud, entityfilters). Use when writing or reviewing Java/Kotlin/Groovy code or META-INF/descriptors in a Dynamia project.
---

# dynamia-platform:backend

Dynamia APIs are not deducible from general Spring knowledge. Before writing:
1. Run `${CLAUDE_PLUGIN_ROOT}/bin/dp-detect --facts` for the version, and read how the module you touch already does it. **Follow the module's conventions over this page.**
2. Verify signatures in the project's own sources or the docs (`dynamia-platform:docs`), not from memory. Versions are CalVer (`YY.MM.N`); APIs here were checked against 26.11.
3. Reference app: `examples/demo-zk-books` in `dynamiatools/framework`.

## Stereotypes
`tools.dynamia.integration.sterotypes.*` (sic) are aliases of Spring's that mark intent:

| Annotation | Use |
|---|---|
| `@Provider` | `ModuleProvider` and `Validator<T>` (the convention for validators too), other providers |
| `@Listener` | `CrudServiceListener` / `CrudServiceListenerAdapter` |
| `@Service`, `@Repository`, `@Controller`, `@Component` | Spring's, or Dynamia's aliases; **follow what the module uses** |

Do not migrate existing annotations as a side effect of another change.

## Entities
```java
@Entity
@Table(name = "books")
@OrderBy("title")
public class Book extends BaseEntity {
    @NotNull private String title;
    @ManyToOne private Category category;
    @OneToMany(mappedBy = "book", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<BookReview> reviews = new ArrayList<>();
    @Override public String toString() { return title; }   // shown in pickers and references
}
```
- `BaseEntity` gives `id` and audit fields. Multi-tenant apps extend a SaaS base class instead (`BaseEntitySaaS` / `SimpleEntitySaaS`, `saas` extension): use whatever the project's other entities extend.
- Always override `toString()`.
- Domain logic (`isActive()`, `calcTotal()`) belongs in the entity; logic needing injected services does not.
- Attachments: `EntityFile` (extension `entity-files`) via `@OneToOne`.
- Dates in `BaseEntity` are `java.time`; filter with `LocalDate`/`LocalDateTime`, never `java.util.Date`.
- Lazy collections: with open-in-view off (`dynamia.app.open-persistence-in-view=false`), an entity returned by `find`, `load`, `reload` or `findSingle` is detached. Declare what travels with it using `@InitializeOnLoad` (class, field or getter) or ask at the call site: `crudService.load(Type.class, id, "detalles")`. Only the outermost call loads. Do not touch `.size()` to force a load. Details: `references/loading-collections.md`.

## Persistence: `CrudService`
Inject it (constructor) or, where injection does not reach, `DomainUtils.lookupCrudService()`. Never use `EntityManager` or loose JPQL in services.
```java
crudService.find(Book.class, id);
crudService.find(Book.class, QueryParameters.with("category", category).orderBy("title", true));
crudService.count(Book.class, QueryParameters.with("stockStatus", StockStatus.IN_STOCK));
```
Existing: `save/create/update/delete/find/findAll/count`, `findByExample`, `executeQuery(QueryBuilder, params)`, `executeProjection` (count/sum/max/avg), `batchUpdate`, `updateField`, `increaseCounter`, `saveWithinTransaction`/`executeWithinTransaction`, `reload`. Filters: `QueryParameters` + `QueryConditions` (`eq`, `between`...). Do not reinvent them. A `String` value in `QueryParameters` is a `LIKE` by default: use `QueryConditions.eq` for exact matches. Full guide, OR groups and custom conditions: `references/crud-service.md`.

## Navigation: `ModuleProvider`
Naming, ids, merging and ordering rules: `references/module-conventions.md`.
```java
@Provider
public class LibraryModuleProvider implements ModuleProvider {
    @Override public Module getModule() {
        Module m = new Module("library", "Library").icon("book");
        m.addPageGroup(new PageGroup("catalog", "Catalog")
            .addPage(new CrudPage("books", "Books", Book.class))
            .addPage(new CrudPage("categories", "Categories", Category.class).icon("tree")));
        return m;
    }
}
```
`CrudPage(id, name, Entity.class)` generates list + form + delete; a fourth argument names an alternate `CrudService`. Other pages: `new Page(id, name, "classpath:/pages/x.zul")`, `ExternalPage`, `ActionPage`. Fluent: `.icon() .description() .featured() .position()`.

## Actions
```java
@InstallAction
public class ReprocessAction extends AbstractCrudAction {
    public ReprocessAction() { setName("Reprocess"); setApplicableClass(Invoice.class); setImage("refresh"); }
    @Override public void actionPerformed(CrudActionEvent evt) {
        Invoice invoice = (Invoice) evt.getData();
        evt.getController().doQuery();          // refresh the list
    }
}
```
`@InstallAction` self-registers. To make an action work for REST clients too, mark it `HeadlessCapable`, talk to the user only through the UI ports (`UIMessages`, `UIFiles`, `UIClipboard`, `UINavigation`, `UIChoices`, `UIProgress`, `UIViews`, never `Messagebox`/`Filedownload`/`Executions`) and follow `references/headless-actions.md`. A toolbar widget that filters the list (date range, combo, search box) is a `FilterAction` with a `Control`, not a ZK renderer: `references/portable-controls.md`. `setApplicableClass` limits it to an entity; `setGroup(ActionGroup.get("CRUD"))` puts it with the standard toolbar; override `isEnabled(Object)` / `isVisible()` for rules; inside use the inherited `crudService()`. Long work: `ProgressMonitor` + `SchedulerUtil`, not the UI thread. Name `VerbNounAction`.

## Validators and listeners
`Validator<T>.validate(T)` is `void` and fails by **throwing** `ValidationError`; it runs on `CrudService.create/update/save`. Register with `@Provider`. Never validate in `@PrePersist`.
```java
@Provider
public class ContactValidator implements Validator<Contact> {
    @Override public void validate(Contact c) throws ValidationError {
        if (c.getEmail() == null) throw new ValidationError("Email is required", null, "email", Contact.class);
    }
}
```
`throw new ValidationError("message")` is also the way to abort any operation with a user message.
Derived values and effects that must always apply go in a listener, not the service:
```java
@Listener
public class InvoiceListener extends CrudServiceListenerAdapter<Invoice> {
    @Override public void beforeCreate(Invoice i) { i.calcTotal(); }
    @Override public void beforeUpdate(Invoice i) { i.calcTotal(); }
}
```

## View descriptors: `META-INF/descriptors/{Entity}{Form|Table|Tree|Json|Crud|Filters}.yml`
`beanClass` is the fully qualified name. Prefer `autofields: false` and list fields; `true` exposes every field, including internal ones.
```yaml
# BookForm.yml
view: form
beanClass: mybookstore.domain.Book
autofields: false
customizer: mybookstore.customizers.BookFormViewCustomizer   # optional
fields:
  title:
    params: { span: 2 }
  category:                          # @ManyToOne -> combo
  publishDate:
    component: dateselector
  price:
    params: { format: $###,###, constraint: "min 0" }
  reviews:
    component: crudview              # embedded sub-CRUD (@OneToMany)
    params: { inplace: true, height: 400px }
groups:
  details: { label: Book Details, fields: [ price, reviews ] }
layout: { columns: 4 }
```
```yaml
# BookTable.yml
view: table
beanClass: mybookstore.domain.Book
autofields: false
fields:
  title:
  price:
    params: { converter: converters.Currency, header: { align: right }, footer: { function: sum } }
  stockStatus:
    component: enumlabel
params: { orderBy: title }
```
- `crud`: `view: crud`, `beanClass`, optionally `controller: <CrudController class>` and `params`.
- `entityfilters`: filter panel with the same `fields` syntax. `tree`: hierarchies. `json`: API/autocomplete projection (`parent.id` dot paths, `params.conditions`).
- Converters: `converters.Date`, `converters.LocalDateTime`, `converters.Currency`.
- `ViewCustomizer<FormView<T>>` is referenced by class name from `customizer:`; it needs no annotation. Use it only for reactive logic YAML cannot express (`view.getFieldComponent("x").hide()`, `view.addEventListener(FormView.ON_VALUE_CHANGED, ...)`).
- Every key and how descriptors are found and merged: `references/view-descriptors.md`.
- Full schema and field components: the framework's `docs/frontend/FIELD_COMPONENTS.md` and `docs/backend/`.

## New CRUD entity: checklist
1. Entity extends the project's base class, `toString()`, correct JPA annotations.
2. `Validator<T>` only for rules beyond bean validation. Listener only for effects that must always apply.
3. `CrudPage` in the module's `ModuleProvider`.
4. `{Entity}Form.yml` and `{Entity}Table.yml` (or `{Entity}Crud.yml` if autofields is enough).
5. Actions only for non-CRUD operations; `ViewCustomizer` only for what YAML cannot do.
6. Run the app's tests and open the page; a CRUD that compiles can still fail on a bad descriptor.

## References (read the one you need)
| Topic | File |
|---|---|
| Actions that run in ZK and for REST clients (headless, replay, flow steps, the UI ports table, `EntityLookup`) | `references/headless-actions.md` |
| Toolbar filter controls (`Control`, `FilterAction`), `POST /find` with `QuerySpec`, `QuerySpecFilter` | `references/portable-controls.md` |
| `CrudService` methods, `QueryParameters`, the String-is-LIKE default, `QueryConditions`, writing new conditions | `references/crud-service.md` |
| `EntityHandler` and the `DomainUtils` helpers | `references/entity-handler-domain-utils.md` |
| All `dynamia.*` configuration properties and defaults | `references/configuration-properties.md` |
| YAML view descriptors: every view and field key, `extends`, components | `references/view-descriptors.md` |
| Tests: JPA with H2, `ActionTester`, port contracts, arch rules | `references/testing.md` |
| Security extension: filter chains, JWT, sessions, `CurrentUser`, login hooks | `references/security-sessions.md` |
| `Containers`, `ObjectsContext`, `ContextCapturer`, messaging, search, `ProgressMonitor`, reactive | `references/integration.md` |
| Collections and detached entities, `@InitializeOnLoad`, `LoadPlan`, OSIV off | `references/loading-collections.md` |
| `BeanMap`, `BeanMapEntityMapper`, automatic DTOs | `references/bean-map-dto.md` |
| `QueryBuilder`, `QueryConditions` | `references/query-builder.md` |
| `ModuleProvider` naming and rules | `references/module-conventions.md` |
| Utility classes, `SchedulerUtil` (background work, cron) | `references/utilities.md` |
| Navigation scope (`ScopedValue`), app metadata, `/api` vs `/apps/api` | `references/navigation-metadata.md` |
| SaaS multi-tenancy: `@TenantId`, `AccountTenants`, `AccountServiceAPI`, root tenant | `references/saas-tenancy.md` |
| Dates: legacy `Date` to `java.time` | skill `dynamia-platform:dates` |
| Extensions: entity-files, reports, http-functions, finances | skill `dynamia-platform:extensions` |

## Anti-patterns
Anemic entities; services injected into entities; `EntityManager`/loose JPQL in services; field injection (`@Autowired` on a field; use the constructor); swallowing exceptions (`catch (Exception e) { e.printStackTrace(); }`); validating in `@PrePersist`; `autofields: true` in production descriptors without review.

Provenance: adapted from the framework's own `dynamia-tools` skill (Apache-2.0) and field-tested conventions from a large Dynamia ERP. See `NOTICE`.
