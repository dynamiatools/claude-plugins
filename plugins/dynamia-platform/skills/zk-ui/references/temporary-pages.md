# Temporary pages and page parameters

A **temporary page** is a `Page` that is not in the navigation tree: "view this book", "edit this order", "manage this loan". It is created in code (usually from an action), opened on demand, and carries the data it needs as **page attributes**.

## Create and open one (ZK, from an action)
```java
@InstallAction
public class EditBookAction extends EditAction {
    public EditBookAction() { setName("Edit Book"); setApplicableClass(Book.class); }

    @Override
    public void actionPerformed(CrudActionEvent evt) {
        if (evt.getData() instanceof Book book) {
            var page = new Page("editBook" + book.getId(), "Edit " + book.getTitle(), "classpath:/zk/books/edit.zul");
            page.setAlwaysAllowed(true);               // not in the menu: skip menu permission check
            page.setTemporal(true);                    // keep it out of the navigation tree
            page.addAttribute("bookId", book.getId()); // parameter: a simple value
            ZKNavigationManager.getInstance().setCurrentPage(page);
        } else {
            UIMessages.showMessage("Select a book", MessageType.WARNING);
        }
    }
}
```
- **Page id**: build it from the data it shows (`editBook<id>`, `viewOrder<id>`). Asking for the same id again reuses the same tab instead of duplicating it; a different id opens another page.
- `setTemporal(true)` + `setAlwaysAllowed(true)` are the usual pair. Set `setShowAsPopup(true)` only for a modal window.
- `setCurrentPage(page, Map<String, Serializable> params)` also exists to pass an extra parameter map with the page.

## What to put in attributes
**Prefer simple values: ids, numbers, strings, booleans, enum names.** Do not put a whole entity (or a collection) in an attribute unless you must.

Why: page attributes are serialized to JSON when the page reaches a Vue shell (for example in the navigation tree endpoint and when the page is parked for a new tab). A large entity makes that payload big, can expose internal fields, and breaks when it has lazy collections that are not loaded.

Pattern: store the id, load the entity where you use it. A small helper keeps it in one place:
```java
public final class BookPage {
    public static final String ATTRIBUTE = "bookId";
    public static void set(Page page, Book book) { page.addAttribute(ATTRIBUTE, book.getId()); }
    public static Long id(Page page) {
        return page != null && page.getAttribute(ATTRIBUTE) instanceof Long id ? id : null;
    }
    public static Book of(Page page) {
        Long id = id(page);
        return id != null ? DomainUtils.lookupCrudService().find(Book.class, id) : null;
    }
    public static Book current() { return of(Page.getCurrent()); }
}
```
Loading by id also gives you a fresh entity, so use `crudService.reload(...)` / `@InitializeOnLoad` for collections the screen walks (see `dynamia-platform:backend`, `references/loading-collections.md`).

## Read the parameters in ZK
```java
public class BookEditViewModel {
    private Book book;

    @Init
    public void init() {
        Page page = Page.getCurrent();                         // or ZKNavigationManager.getInstance().getCurrentPage()
        Long id = page != null && page.getAttribute("bookId") instanceof Long v ? v : null;
        book = id != null ? DomainUtils.lookupCrudService().find(Book.class, id) : new Book();
    }
}
```
- `Page.getCurrent()` / `ZKNavigationManager.getInstance().getCurrentPage()` return the page being shown; read with `getAttribute(name)` and check the type with `instanceof` (an attribute may be missing, e.g. page opened by a stale link).
- If the ZUL is also opened as a window with execution args, read them with `ZKUtil.getExecutionArg("name")`. Check both sources when one view model serves both ways.
- In ZUL you can bind to what the view model loaded (`@load(vm.book.title)`); do not read page attributes from expressions in several places.
- When the page is reused, verify it is still the same record (`id.equals(page.getAttribute("bookId"))`) before trusting cached state.

## Temporary pages inside a Vue shell
When the ZK UI runs inside a Vue shell (iframe per tab), a temporary page asked for from a screen that is already visible does not replace that screen:
1. The server **parks** the page and its parameters in the HTTP session and gives the shell a path like `temporal/<token>`.
2. The shell opens a new tab for that path; its iframe loads the page by that same path.
3. The ZK side reads the attributes as above: Vue only opens the tab, it does not receive the parameters as props.

Consequences to design for:
- The token only works in the session that created it, and the session keeps a limited number of parked pages (oldest dropped first): a reload works, a link shared with someone else does not.
- Parameters are reachable on the ZK side only. If a Vue screen needs the same data, give it the **id** (route, query or props) and let it call the REST API; do not rely on serialized entities from the page.
- Keep attributes small and JSON-safe, for the reasons above.

For a Vue screen that must be opened with parameters, see `dynamia-platform:vue-frontend` ("Opening a screen with parameters").

## Checklist
- [ ] `setTemporal(true)` (and `setAlwaysAllowed(true)` if not in the menu)
- [ ] Page id includes the record id
- [ ] Attributes are ids/strings/numbers, not entities or collections
- [ ] The view model reads with a type check and reloads the entity by id
- [ ] If a Vue shell is used, nothing depends on non-serializable attributes
