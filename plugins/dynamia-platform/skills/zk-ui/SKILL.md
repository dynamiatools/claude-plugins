---
name: zk-ui
description: ZK 10 UI work in a Dynamia Platform project - ZUL pages with MVVM view models, CrudController, ViewCustomizer, the Containers service locator, UIMessages, testing view models, and embedding Vue bundles with the microfrontend tag. Use when editing .zul files or view model classes, or when a Dynamia project mixes ZK and Vue.
---

# dynamia-platform:zk-ui

Applies when `dp-detect` reports `ZK`. For entities, services and descriptors use `dynamia-platform:backend`; for the Vue side use `dynamia-platform:vue-frontend`. Verify against the project's ZK version, and look at the nearest existing `.zul` first.

## Where UI comes from
Most screens need no ZUL: `CrudPage` + YAML descriptors render list, form and actions (`dynamia-platform:backend`). Write ZUL or a view model for what descriptors cannot express. Customize generated views with `ViewCustomizer`; hook CRUD behavior with a controller.

## MVVM page
```xml
<zk>
  <borderlayout vflex="1" viewModel="@id('vm') @init('mybookstore.viewmodel.StandardViewModel')">
    <center>
      <listbox vflex="1" model="@load(vm.books)" selectedItem="@bind(vm.selected)">
        <listhead><listheader label="Title"/><listheader label="Actions" width="100px"/></listhead>
        <template name="model" var="b">
          <listitem>
            <listcell label="@load(b.title)"/>
            <listcell><button iconSclass="z-icon-eye" onClick="@command('view',book=b)"/></listcell>
          </listitem>
        </template>
      </listbox>
    </center>
  </borderlayout>
</zk>
```
```java
public class StandardViewModel {
    private final CrudService crudService = DomainUtils.lookupCrudService();
    private List<Book> books;
    private Book selected;

    @Init public void init() { books = crudService.findAll(Book.class); }

    @Command public void view(@BindingParam Book book) {
        Containers.get().findObject(ViewDataAction.class).view(crudService.reload(book));
    }
    // getters/setters for books and selected
}
```
- Standard ZK binding: `@Init`, `@AfterCompose`, `@Command`, `@NotifyChange`, `@BindingParam`. Dynamia adds `tools.dynamia.zk.AbstractViewModel<T>` and `FormCrudViewModel<T>` as optional bases, and utilities `ZKUtil`, `ZKBindingUtil`, `CrudView`, `FormView`, `CrudState`.
- **Actions use UI ports, not ZK classes.** In an action, prefer `UIMessages`, `UIFiles` (download, upload, preview), `UIClipboard.copy`, `UINavigation` (`openPage`, `refresh`), `UIChoices` (`chooseOne`, `pickEntity`), `UIProgress.run` and `UIViews.showForm` over `Messagebox`, `Filedownload`, `Executions`, `Window`: ZK has an adapter for each and behavior is the same, and the action can then be `HeadlessCapable` for Vue/REST clients (`dynamia-platform:backend`, `references/headless-actions.md`). ZK classes stay fine in ZUL view models and pure-UI actions. A toolbar filter widget is a `FilterAction` with a `Control` (ZK maps it with `ControlRenderers.adapt`), not a hand-built `ActionRenderer<Component>`.
- User messages: `UIMessages.showMessage("text", MessageType.WARNING)`, `showQuestion(text, onYes)`, `showMessageDialog`. Throw `ValidationError` for rule violations.
- Pages are registered in a `ModuleProvider` with `new Page(id, name, "classpath:/pages/x.zul")`.

## CrudController
Extend `CrudController<T>` for hooks `beforeCreate`, `afterCreate`, `beforeEdit`, `beforeDelete`, `beforeQuery`; `getEntity()` returns the current entity. Link it from the descriptor: `view: crud`, `beanClass: ...`, `controller: com.acme.BookCrudController`. Throw `ValidationError` to stop an operation.

## Containers (service locator)
`Containers.get().findObject(Type.class)` / `findObjects(Type.class)` resolve beans where injection does not reach (entities, utilities, view models). In normal beans use constructor injection.

## Testing a view model
No Spring needed: register stubs and reset between tests.
```java
private final Containers containers = Containers.get();
@BeforeEach void setUp()    { containers.removeAllContainers(); }
@AfterEach  void tearDown() { containers.removeAllContainers(); }
// then: containers.installObjectContainer(new SingleObjectContainer(...)) with the stubs the view model looks up
```

## Vue inside ZK: `<microfrontend>`
Mount a bundle (Vue, React, Svelte, plain JS) in a ZUL page without an iframe:
```xml
<microfrontend src="/bundles/my-widget.js" tag="my-widget" userId="${user.id}"
               onMicrofrontendEvent="@command('handleWidgetEvent', data=event.data)"/>
<microfrontend src="/bundles/my-app.js" mode="mount-fn" mountFn="mountMyApp" unmountFn="unmountMyApp" updateFn="updateMyApp"/>
```
- Modes: custom element (`tag=`), `mount-fn` (single-spa style), and auto-discovery of a Vite-style `dist/`.
- The bundle side uses `@dynamia-tools/microfrontend-bridge` (`emitToHost`, `getHostContext`, `isDynamiaHost`).
- Provide tenant/locale/API context from Java with a bean implementing `MicroFrontendHostContextProvider` (`getHostContext()` returns a map such as `tenantId`, `locale`, `apiBaseUrl`).
- Server commands called from a script-based Vue page: annotate the view model with `@ToServerCommand({"hello", "showBook"})`. See `examples/demo-zk-books/.../pages/vue-integration.zul`.

## The other direction: ZK inside Vue
`<DynamiaZkEmbed src="/page-embed/library/books"/>` (package `@dynamia-tools/vue`) mounts a ZK page inline in a Vue host. Same origin only, depends on private ZK client API; read `docs/frontend/INLINE_ZK_EMBED.md` through `dynamia-platform:docs` before using it.

## Do not
Block the UI thread with long work; keep state in static fields; migrate working ZUL to another style as a side effect of a different task.
