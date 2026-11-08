# Action flows, field components and theme

Checked against framework 26.11: `@dynamia-tools/ui-core` (`runActionFlow`, `FieldComponentRegistry`, `registerClientAction`), `@dynamia-tools/sdk` (generated `ui-contract`), `docs/frontend/FIELD_COMPONENTS.md`, `docs/design/HEADLESS_ACTIONS.md`.

## Running a server action (headless or flow)
Entity actions are published in the entity metadata with a runtime: `HEADLESS`, `FLOW`, `REMOTE`, `FRONTEND` or `UNDECLARED` (`ACTION_RUNTIMES`). `HEADLESS` and `FLOW` actions answer with **steps**; the client loop shows each one and resumes with the answer. Do not write the loop yourself: use `runActionFlow` from `@dynamia-tools/ui-core`.
```ts
import { runActionFlow } from '@dynamia-tools/ui-core';
const response = await runActionFlow(client, actionMetadata, request, {
  confirm: ({ message, title }) => ui.confirm(message, title),          // CONFIRM step -> boolean
  showToast: ({ message, variant }) => ui.toast(message, variant),       // NOTIFY / DONE messages
  prompt: ({ message }) => ui.prompt(message),                           // INPUT step -> string | null
  showForm: (req) => ui.openForm(req),                                   // DIALOG / VIEW step -> values | null
});
```
- Step types by port: messages `CONFIRM`, `INPUT`, `NOTIFY`; choices `CHOICE`; files `UPLOAD`; progress `PROGRESS`; views `DIALOG`, `VIEW`; navigation `REDIRECT`; the final one is `DONE`. A step carries `flowId`, `type`, `title`, `message`, `data`, `fieldErrors`, `hints` and a signed, expiring `resumeToken`.
- Final effects arrive in `params` of the last response and `runActionFlow` hands them to optional handlers: `previewFile` (`params.downloads[].disposition: 'inline'`, only `isInlineAllowed` types, default opens a tab and saves when the popup is blocked), `saveFile` (other downloads), `showClipboardFallback(text)` (`params.clipboard`; the runner writes `navigator.clipboard` first), `openPage(path, params)` (`params.page`; `isPagePath` rejects URLs, `..` and leading `/`; ignored without the handler) and `refresh()` (`params.refresh`). Question handlers: `choose` (CHOICE, returns keys), `pickEntity({title, search})` (CHOICE with a `lookup`, returns the chosen key; required for such steps; `search` wraps `client.lookups.search(name, query, limit)`), `pickFiles` (UPLOAD, defaults to the browser picker; content goes to `/apps/api/transfers`, never inside the flow), `showProgress(status)` (PROGRESS, `progressIntervalMs` default 500).
- Each resume sends the user's answer with the step's `flowId` and `resumeToken`; the server re-runs the action with the answers so far (replay, `dynamia-platform:backend` `references/headless-actions.md`). The client holds nothing but the token.
- A plain `RemoteAction` with no `flow` in its response resolves on the first call.
- `REDIRECT` and `CALL` steps are **experimental**.
- Pure UI actions are `FRONTEND`: register your own in TypeScript with `registerClientAction`; there is no server runtime named `CLIENT` anymore.
- Dispatch rules for CRUD pages live in `crudActionDispatch.ts` / `useCrudPage`; prefer `DynamiaCrudPage` and let it run the flow.

## List queries and toolbar controls
`client.crud(path).find(spec)` calls `POST /api/{path}/find` with a `QuerySpec` (`filters: {field, op, value}[]`, `search`, `sort`, `page`, `size`; ops `eq like between gte lte in isNull`) and returns the same list result as `findAll`. An invalid field or value is a 422 `DynamiaApiError` naming it. The per-field query parameters of `GET /api/{path}` no longer exist: use `find`.
Actions published with a `control` (renderer key `control`, runtime `FRONTEND`) are toolbar widgets: kinds `DATE`, `DATE_RANGE`, `DATETIME_RANGE`, `TEXT`, `CHOICE` with `field`, `label`, `options`, `allLabel` and a symbolic `preset` (`TODAY`, `THIS_MONTH`, `LAST_MONTH`, resolve it in the user's time zone). `@dynamia-tools/vue` draws them (`VueControlActionRenderer`) and calls `TableView.setQueryFilter(field, filter)`; do not execute those actions on the server. Server side: `dynamia-platform:backend` `references/portable-controls.md`.

## Field components
`FieldResolver` picks the component for a descriptor field: the descriptor's `component:` or `params.component`; a collection of entities (`entityrefmultipicker` with `params.entityAlias`, else `label`); a single entity (`entityrefpicker` with `entityAlias`, else read-only `entityreflabel`); else by field class (text, integer, decimal, checkbox, date, enum combobox; unknown is `textbox`).
`Field.vue` then resolves the identifier in this order: 1) `FieldComponentRegistry` (case-insensitive, can override built-ins), 2) the components of `@dynamia-tools/vue`, 3) the component of the field's type (so an unknown `component: fancything` on a boolean is still a checkbox).
Register your own once, before mounting:
```ts
import { FieldComponentRegistry } from '@dynamia-tools/ui-core';
FieldComponentRegistry.register('rating', StarRating, ['stars']);   // name, component, aliases
```
A component receives `field`, `modelValue`, `readOnly`, `params` and emits `update:modelValue`.
```yaml
rating:
  component: rating
  params: { max: 5, scale: 10 }
```
- Many-to-many fields are sent as `[{id, name}]`; the server replaces the collection with the entities of those ids (shared by REST `PUT` and `save`). Other collections (owned children, element collections) are untouched when patching.
- Editing loads the whole entity: list rows carry only the table columns, so `startEdit` shows the row and replaces it with `GET /api/{path}/{id}` when it arrives (wired in `useCrudPage`).
- Table cells render read-only through `Field.vue` for booleans and for display components (`label`, `link`, `rating`, `badge`, `status`, `coollabel`, `enumlabel`, `entityreflabel` or one a theme registered); input-only names stay plain text. A column may declare `params.bindings` for a virtual field and honors `params.converter`.
- Dates: a date-only value (`yyyy-MM-dd`) is read as a calendar day, not as UTC midnight (fixed in 26.10). Send ISO strings; see `dynamia-platform:dates`.
- Pickers for entities and collections, enums with options and components in table cells exist in `@dynamia-tools/vue`; `DynamiaViewer` resolves any descriptor, takes a client and also renders plain descriptor objects.

## Theme package
`@dynamia-tools/theme-dynamical-vue` publishes the Vue frontend (TailAdmin based) as an npm package and registers its field components (`rating`/`stars`, `badge`, `status`, `colorpicker`, `moneyinput`, `quantityinput`; each reads its `params:`). Its Vite preset proxies `/apps` to the backend; auth behavior is configurable; with Tailwind, make sure the package's sources are in the Tailwind content paths when it is installed from npm. Check the package README for the current options.

## Metadata endpoints the client uses
Under `/apps/api/metadata` (session or Bearer; writes are same-origin): navigation, entities, views, actions. Details and the cache option in `dynamia-platform:backend` `references/navigation-metadata.md`.
