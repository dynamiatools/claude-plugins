# Portable toolbar controls and the standard list query

Checked against `dynamiatools/framework` 26.11 (`docs/design/UI_INPUTS.md`, `Control`, `FilterAction`, `QuerySpec`). Implemented for the list of a CRUD page; ZK and Vue verified against `demo-zk-books`.

## Problem it solves
A toolbar widget (date range, search box, state combo) that filters the list is not a button: it changes the query state of the list, and a headless controller has none. Before, ZK built it with an `ActionRenderer<Component>` and metadata published a class name a remote client could not use. Now the widget is **data** and the value travels with the list request.

## `Control` (in `tools.dynamia.actions`)
A record: `Control(kind, field, label, options, allLabel, preset)`. No component, callback or class name.

| Factory | Kind |
|---|---|
| `Control.date(field)` | `DATE` |
| `Control.dateRange(field)` | `DATE_RANGE` |
| `Control.dateTimeRange(field)` | `DATETIME_RANGE` |
| `Control.text(field)` | `TEXT` (search box) |
| `Control.choice(field, EnumClass.class)` or `choice(field, List<Option>)` | `CHOICE` |

Fluent: `.label(..)`, `.allLabel("All")` (the "all" item becomes a missing filter), `.preset("TODAY" | "THIS_MONTH" | "LAST_MONTH")`. A preset is symbolic: each front end resolves it in the user's time zone (the server's in ZK).

## `FilterAction`
```java
@InstallAction
@RunsOn(ActionRuntime.FRONTEND)
public class FilterBookByStockAction extends FilterAction {
    public FilterBookByStockAction() {
        super(Book.class, Control.choice("stockStatus", StockStatus.class).allLabel("All"));
        setName("Stock");
    }
}
```
- `FilterAction` sets `HeadlessActionRenderer.of(control)`, `setApplicableClass(entity)` and the `CRUD` group. Do **not** write `actionPerformed` or `getRenderer`.
- Declare `@RunsOn(ActionRuntime.FRONTEND)` on the concrete class: the client draws the control and never executes the action (the annotation is not inherited).
- `ActionMetadata` publishes `control` and sets `renderer` to the stable key `control`, not a class name.
- **ZK**: `ControlRenderers.adapt` maps the control to the renderer ZK already had; on a change `FilterAction.actionPerformed` builds a condition (`FilterValues` then `FilterConditions`), sets it on the controller and runs the query.
- **Vue**: the `control` renderer draws the widget and the list loader calls `POST /find` when the table has field filters.

Rules: a control filters the list, it does not run the action remotely. An action that must *do* something with the value (reads a ViewModel from the event) is not a control and stays a custom `FRONTEND` action. Read context from the event, never from the page at construction time. Migrating an old action: pure filters (`setParemeter` + `doQuery` behind a date, range, combo or text renderer) become `extends FilterAction` and lose their `actionPerformed`; filters with extra logic stay `FRONTEND`.

## `QuerySpec`: `POST /api/{path}/find`
```json
{ "version": 1,
  "filters": [ {"field": "stockStatus", "op": "in", "value": ["OUT_STOCK"]},
               {"field": "publishDate", "op": "between", "value": ["2026-01-01", null]} ],
  "search": "dune", "sort": [{"field": "title", "dir": "desc"}], "page": 1, "size": 20 }
```
- Operators: `eq`, `like`, `between` (a `null` side is open), `gte`, `lte`, `in`, `isNull`. One filter per field, combined with AND.
- Values are coerced by the field's type (text, numbers, boolean, enum, `LocalDate`, `LocalDateTime`); a date without time covers the whole day. Anything invalid is a **422 naming the field**, never ignored.
- **The table view descriptor is the whitelist**: every field of `filters` and `sort` must be in it.
- Limits (`QuerySpecLimits`): 20 filters, 100 values of an `in`, 5 sort keys, 200 characters of search, page size 500.
- `GET /api/{path}` now reads only `page`, `size`, `_q`, `_sort`, `_order`. The per-field query parameters were removed (they could filter on any property, hidden ones included): move such callers to `POST /find`.

## Server policy: `QuerySpecFilter`
Every spec goes through `QuerySpecProcessor`: limits, then `QuerySpecFilter` beans by `order()`, then the whitelist and the conditions.
```java
@Component
class NoAccountFilter implements QuerySpecFilter {
    public QuerySpec filter(QueryContext context, QuerySpec spec) {
        return spec.without("accountId");                          // drop what the client may not choose
        // return spec.with(new Filter("accountId", "eq", mine));  // impose a condition
        // throw new ValidationError("...");                       // refuse (422); NavigationNotAllowedException is a 403
    }
}
```
The context carries path, entity class, descriptor and operation; the account comes from `AccountTenants`. Dropping a field is not a defence for something like `accountId`: **impose** the current account after the client's filters.

## Known limits
- `QuerySpecFilter` protects the REST list only; ZK builds filters from controller parameters.
- Only the list uses a `QuerySpec` (count, export, bulk and lookup do not yet). No OR groups, no filters across relations.
- `POST /apps/api/crud-service/{className}/find` binds `QueryParameters` whose keys reach the query text unchecked: do not expose it to untrusted clients; use `POST /api/{path}/find`.
- The action `endpoint` in metadata says `/actions/{id}` but the controller maps `/action/{id}` (the SDK uses the latter).
