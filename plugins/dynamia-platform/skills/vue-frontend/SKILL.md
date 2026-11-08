---
name: vue-frontend
description: Frontend work against a Dynamia Platform backend with the @dynamia-tools npm packages - sdk (DynamiaClient), ui-core, vue (DynamiaVue plugin, DynamiaViewer, composables), microfrontend-bridge and the extension SDKs (dashboard, reports, saas, files, http-functions). Use when a package.json depends on @dynamia-tools/*, when building Vue/TypeScript screens for a Dynamia API, or when choosing how to combine Vue with ZK.
---

# dynamia-platform:vue-frontend

Applies when `dp-detect` reports `Vue`, `TS SDK` or `microfrontend`. The backend contract (entities, `CrudPage`, descriptors) is in `dynamia-platform:backend`: the frontend renders what the server declares. Check the exact versions in `package.json` (or the workspace catalog) and read the package README for the version in use (`dynamia-platform:docs`).

## Packages
| Package | Use |
|---|---|
| `@dynamia-tools/sdk` | `DynamiaClient`: REST client, metadata, navigation, CRUD, actions |
| `@dynamia-tools/ui-core` | Framework-agnostic views, viewers, renderers, resolvers, converters, validators |
| `@dynamia-tools/vue` | Vue 3 plugin, components and composables (peer deps: `vue >= 3.4`, `ui-core`, `sdk`) |
| `@dynamia-tools/microfrontend-bridge` | Typed helpers for bundles embedded in ZK with `<microfrontend>` |
| `dashboard-sdk/-vue`, `reports-sdk/-vue`, `saas-sdk`, `files-sdk`, `http-functions-sdk` | Clients (and Vue components) for the matching backend extensions |
| `@dynamia-tools/cli` | Scaffolding, see `dynamia-platform:cli` |

React is a scaffold option in the CLI, but the component library is Vue; for React use `sdk` and `ui-core`.

## SDK
```ts
import { DynamiaClient } from '@dynamia-tools/sdk';
const client = new DynamiaClient({ baseUrl: '/api', token });          // Bearer token (recommended for SPAs)
// or { baseUrl, username, password }  server-to-server (Basic)
// or { baseUrl, withCredentials: true } session cookie after POST /login
const app = await client.metadata.getApp();
const books = await client.crud('books').findAll();                    // paged: books.content, books.totalPages
```
The SDK has no `login()` helper: log in with `fetch` against the form login, then build the client with a token or cookies. Other APIs: `client.metadata`, navigation, CRUD navigation, CRUD service, actions.

## Vue
```ts
import { createApp } from 'vue';
import { DynamiaVue } from '@dynamia-tools/vue';
createApp(App).use(DynamiaVue).mount('#app');   // registers renderers and global components
```
Global components: `DynamiaViewer`, `DynamiaForm`, `DynamiaTable`, `DynamiaCrud`, `DynamiaField`, `DynamiaActions`, `DynamiaNavMenu`, `DynamiaNavBreadcrumb`, `DynamiaCrudPage`, `DynamiaZkEmbed`.
```vue
<DynamiaViewer view-type="crud" bean-class="Book" />
```
Composables: `useViewer`, `useView`, `useForm`, `useTable`, `useCrud`, `useEntityPicker`, `useCrudPage`, `useNavigation`.

**Metadata-driven shell**: `useNavigation(client, { autoSelectFirst: true })` gives `nodes`, `currentPage`, `navigateTo`; render `<DynamiaNavMenu>`, `<DynamiaNavBreadcrumb>` and `<DynamiaCrudPage :node :client>` for nodes of type `CrudPage`. A screen added on the server with `CrudPage` + descriptors appears with no new Vue code; write Vue only for what the descriptors cannot express (custom view types via `ViewRendererRegistry`, custom field components).

## Choosing how to combine Vue and ZK
| Situation | Use |
|---|---|
| New screen in a Vue app talking to the REST API | Vue + `sdk` (+ `DynamiaCrudPage` when it is a CRUD) |
| A Vue widget inside an existing ZK page | Build a bundle with `microfrontend-bridge`, mount it with `<microfrontend>` (`dynamia-platform:zk-ui`) |
| An existing ZK view inside a Vue app | `<DynamiaZkEmbed src="..."/>`, same origin only (`docs/frontend/INLINE_ZK_EMBED.md`) |

If the project already has a convention for this, follow it; if it is unclear which side a new screen belongs to, ask.

## More
Action flows (`runActionFlow`, steps, headless actions, the handlers for preview, clipboard, `openPage`, `refresh`, `pickEntity`), list queries with `client.crud(path).find(QuerySpec)`, toolbar controls, field components (`FieldComponentRegistry`), table cells, dates and the theme package: `references/action-flows-and-fields.md`. Read it when a button must run a server action with questions, when a field needs a custom component, or when a date shows the wrong day.

## Rules
- Keep API access in one place (a client instance or composable), not scattered `fetch` calls.
- Never put tokens in source or `localStorage` without the project's decision on it; use what the app already does.
- Do not copy server rules (validation, permissions) into the frontend as the only check.
- `catalog:` or `workspace:*` versions mean a pnpm workspace; do not replace them with ranges.
- Before claiming a screen works, build/type-check (`pnpm build`, `vue-tsc`) and open it, or say it was not run.

Provenance: summarized from the package READMEs of `dynamiatools/framework` (Apache-2.0). See `NOTICE`.
