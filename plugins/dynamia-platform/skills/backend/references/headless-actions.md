# Headless (stateless) actions

One action class, many front ends. Checked against `dynamiatools/framework` 26.11 (`docs/design/HEADLESS_ACTIONS.md`, `UI_PORTS_WAVE2.md`, `docs/backend/DEVELOPMENT_PATTERNS.md`, and the facades in `ui-shared`).

## What it is
A `LocalAction` that talks to the user only through UI-neutral ports and is marked `HeadlessCapable`. ZK runs it as always. A REST client (Vue, React, mobile) runs the same class through `POST /apps/api/metadata/entities/{id}/action/{action}`. The server keeps **no state between requests**: it uses *replay*.

## How replay works
1. The action runs from the start. Each question (`UIMessages.showQuestion`, `showInput`...) is answered, in order, with the answers the client already gave.
2. The first question without an answer stops the pass and goes to the client as an `ActionFlowStep` (status `PENDING`).
3. The original request and the answers travel in a **signed, expiring `resumeToken`**. The client calls again with the token and the new answer; the action runs again from the start, until it finishes (`SUCCESS`, step `DONE`).
4. Every pass runs in a transaction (`ReplayTransactions`); **only the pass that runs to the end commits**. A pass stopped at a question is rolled back.

## Writing one
```java
@InstallAction
public class ArchiveAction extends AbstractCrudAction implements HeadlessCapable {
    public ArchiveAction() {
        setName("Archive");
        setApplicableStates(CrudState.get(CrudState.READ));
    }
    @Override
    public void actionPerformed(CrudActionEvent evt) {
        Invoice invoice = (Invoice) evt.getData();
        UIMessages.showQuestion("Archive invoice " + invoice.getNumber() + "?", () -> {
            invoice.setArchived(true);
            evt.getController().getCrudService().save(invoice);
            UIMessages.showMessage("Archived");
        });
    }
}
```
A headless run executes the action once per question, plus one.

## Rules (break one and replay breaks)
- **Deterministic**: same request and answers give the same questions in the same order. No randomness, no `now()`-dependent branching before a question.
- **Side effects that are not database writes** (mail, files, calls to other systems) go inside the **last callback**, never before a question; a stopped pass is only rolled back for the database.
- **Ports only**: `UIMessages`, `CrudControllerAPI`, `CrudViewComponent` and the facades in the table below. No ZK classes (`Messagebox`, `Filedownload`, `Executions`...). An action that imports ZK stays ZK-only (fine for pure-UI actions). ZK may be used only in the modules the framework's `ZkCornerRuleTest` lists.
- Where each port ends up for a remote client: see the table below. Metadata publishes each action with a runtime: `HEADLESS`, `FLOW`, `REMOTE`, `FRONTEND` or `UNDECLARED`. Declare it on the concrete class with `@RunsOn(ActionRuntime.HEADLESS)` (or `FRONTEND`); it is **not inherited**, so a subclass is `UNDECLARED` until it declares its own.
- The id REST clients see is the class name without `Action`, lower case (`archive`). Override `headlessId()` to change it, `headlessSupported()` to leave a subclass out.
- The entity class comes from the URL (`EntityMetadata.getClassName()`), never from the client. `ActionRestrictions`, state checks and `ActionFilter`s apply as for any remote action.

## The ports
Facades in `tools.dynamia.ui` (`ui-shared`). Each picks its implementation from the environment: ZK registers its own, a headless run binds a replay one for the execution (`UIFacades`). Use them instead of ZK classes:

| Instead of | Use | Headless result |
|---|---|---|
| `Messagebox`, `ZKUtil.showMessage` | `UIMessages.showMessage/showQuestion/showInput` | steps `CONFIRM`, `INPUT`; messages in the response |
| `Filedownload`, `Fileupload` | `UIFiles.download(...)`, `UIFiles.upload(...)`, `uploadOne(accept, cb)` | step `UPLOAD`; downloads in `params.downloads` (1 MB up, 10 MB down by default) |
| Show a PDF, image or text instead of saving | `UIFiles.preview(...)` | `params.downloads[].disposition = "inline"`; only `InlinePolicy` types (pdf, png, jpeg, gif, webp, text/plain), others are downloaded |
| Copy a text or URL | `UIClipboard.copy(text)` | `params.clipboard`; the client shows the text if the browser refuses |
| `NavigationManager.navigateTo`, reload the view | `UINavigation.openPage(path[, params])`, `UINavigation.refresh()` | `params.page = {path, params}`, `params.refresh`. `openPage` takes a page path (`ventas/ventas`), never a URL; params must be plain values |
| `Executions.sendRedirect` | `UINavigation.open(url)`, `openInNewWindow(url)` | final `REDIRECT` (experimental) |
| `ZKUtil.showListboxSelector` | `UIChoices.chooseOne/chooseMany` | `CHOICE` |
| Pick a record of a big catalog | `UIChoices.pickEntity(lookupName, title, cb)` over an `EntityLookup` bean | `CHOICE` with `data.lookup`; the client searches `GET /apps/api/lookups/{name}` |
| Selected rows of the list | `CrudControllerAPI.getSelection()` | `ids` of the request (at most `HeadlessCrudRemoteAction.MAX_BULK_IDS`) |
| `LongOperation` + monitor window | `UIProgress.run(title, task, onFinish)` | runs inside the request and must be the last interaction; with a background job the client follows a `PROGRESS` step |
| `Window` + `Viewer` with a form | `UIViews.showForm(FormOptions, cb)` (entity classes only), `showView` | `DIALOG` / `VIEW` |

Use `UIPlatform.supports(ChoicesProvider.class)` (or the port's SPI) when an action must degrade where a port is missing.

**Question or final effect.** A *question* (`showQuestion`, `showInput`, `chooseOne`, `upload`, `pickEntity`) waits for an answer and is an `ActionFlowStep`. A *final effect* (`download`, `preview`, `copy`, `openPage`, `refresh`, notifications) is received once the action ended: only the pass that ran to the end publishes it, in `params.*` of the final response, so it needs no step type. Never model something that only informs as a step.

**Ask for a reason.** There is no port: `UIMessages.<String>showInput(title, String.class, cb)` returns the text and a cancelled answer is `null`. To make it required in a headless run throw `ReplayRetry` on a blank answer (the same question is asked again). `ReplayRetry` exists only in the replay runtime: in ZK and in the direct mode of the test platform it is an unhandled exception, so an action that must behave the same everywhere asks again itself instead.
```java
UIMessages.<String>showInput("Why do you void this sale?", String.class, reason -> {
    if (reason == null || reason.isBlank()) throw new ReplayRetry("A reason is required");
    sale.voidSale(reason);
});
```

**`EntityLookup<T>`** (`name()`, `search(text, limit)`, `find(key)`, `key(v)`, `label(v)`, `isSearchable()`) backs `pickEntity`. Register it as a bean (an `EntityLookup` is a bean, not a stored file lookup). `search` and `find` must apply the same filters and the tenant (use the tenant-aware `CrudService`): each pass calls `find` again with the key the client sent, and a key outside the set is refused. Remote search is **opt-in**: `/apps/api/lookups/{name}` answers only when `isSearchable()` returns `true`, because that endpoint is not tied to an action; expose only lookups every user of the account may see. entity-files ships `EntityFileLookup` for picking a stored file of the current account.

**Adding a port** (rare, framework work): an SPI interface annotated `@UIPort`, a static facade resolving it with `UIFacades.port`, a ZK implementation in `ZKUIEnvironment`, a replay one in `ReplayUIEnvironment` (or a `ReplayPortContributor` bean when it needs a module such as `crud`), a contract case, a protocol fixture, and the TS handler in `ui-core`. Every port must behave in ZK as the old direct call did.

## What the framework already has
- `SaveAction` and `DeleteAction` are headless. `SaveAndEditAction` and `SaveAndNewAction` opt out (they leave the form on a record, which is the client's job). Reports, entity-files and saas actions were declared headless too. An arch rule (R6) fails when a standard action is neither headless nor declared `FRONTEND`.
- The hand-written `SaveRemoteAction`, `SaveFlowRemoteAction`, `DeleteRemoteAction`, `DeleteFlowRemoteAction` and `DeleteSupport` were removed: do not recreate them, make the local action headless.
- `UIMessages.withDisplayer(...)` binds a displayer per execution with a `ScopedValue`.
- Files: `UIFiles` over the `FileTransfer` SPI; uploads and downloads stream through a `TransferStore` (`/apps/api/transfers`). Transfers are limited by `dynamia.ui.files.max-file-size` (default 100 MB), `max-files` and `quota`; see `configuration-properties.md`.

## Config
`dynamia.actions.flow.secret` signs the token (set it in production), `dynamia.actions.flow.token-ttl` is its lifetime. The token is bound to the action id, so a client cannot change what it confirmed.

## When not to use replay
- The action must be written for REST clients only, needs a step replay does not produce, or is not deterministic: write a `FlowRemoteAction` (explicit `start` / `resume` state machine). `DIALOG`, `REDIRECT`, `CALL` and `CUSTOM` steps still come from `FlowRemoteAction`; REDIRECT/CALL flow steps are marked experimental.
- Pure UI actions are `FRONTEND`: the front end writes its own client action in TypeScript (`registerClientAction`). A toolbar widget that only filters the list is a portable control, not a custom renderer: see `portable-controls.md`.
- Remote actions no longer have a `CLIENT` runtime (`ActionRuntime.CLIENT` was removed).

## Testing
Use the `runEverywhere` style tests (the same assertions in ZK and headless mode) as the converted actions in `entity-files` do.
