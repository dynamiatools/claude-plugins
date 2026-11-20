---
name: ux-review
description: Reviews a UI for usability and accessibility, on desktop web and on mobile, then fixes it with approval. For web apps used on a phone it checks the conventions of current mobile apps. Use when the user asks to review, audit or improve the UX, accessibility, responsive behavior or mobile experience of a screen, component or diff. Triggers on "revisa esta pantalla", "no es accesible", "se ve mal en el celular".
argument-hint: "[path or screen] [review|fix]"
---

# dynamia-ui:ux-review

Two steps. **Review** is read-only. **Fix** changes code only after the user approves the list.

## Review
1. **Scope**: the files, screen or diff named; otherwise ask which one. Read the code, and the project's `design-system/MASTER.md` if it exists (compare against it).
2. **Context**: read `references/web.md` always. Also read `references/mobile.md` when any of these holds: viewport meta or responsive CSS, PWA manifest or Capacitor, mobile framework, or the user said phone, tablet or app. A web app used on a phone is judged by mobile app conventions at small widths, not by desktop ones.
3. **Check** what the code shows. Do not claim what needs a running app (real contrast of images, screen reader output, device behavior); list those under "not verified". If the app can be run and a browser tool is available, use it at 375, 768, 1024 and 1440 px.
4. **Report**, most severe first. One line each: `file:line`, what is wrong, the fix. Group by Critical (blocks use or fails accessibility), High, Medium. Add "Not verified". No praise filler, no list of passes.

## Fix
After the report, offer the fixes. On approval apply them in small steps, highest severity first, run the project's tests or build, and re-check the touched items. Do not restyle beyond the finding. If the project has a design system, use its tokens instead of new values.

End with one line: what was reviewed, what was not verified, and any risk left.
