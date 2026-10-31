# hover-preview

Hover to peek, click to open. A mod for Claude Code's fullscreen terminal: it adds no skills or agents.

- **Pasted images.** Paste an image and a row above the prompt lists its `[Image #N]`. Put the pointer on one and the picture opens above the row, drawn in colored terminal cells (any true-color terminal). Click it and the image opens in the system viewer (`xdg-open`, `open` on macOS).
- **Paths in replies.** Under a reply block that names files or folders that exist (`src/app.ts:42`, `~/notes.md`, `./run.sh`), a row of links appears. Hover one and a card above the prompt shows its size and age, and the lines of a text file (around the named line, lit) or the first entries of a folder. Click it to open its folder (Finder with the file selected on macOS); Alt-click opens the file itself.

Hovering needs the mouse, so it needs the fullscreen interface (`"tui": "fullscreen"` in your settings, or `/config`).

## Install
```
/plugin install hover-preview@dynamia-tools
```

## Limits
- Images need ImageMagick (`magick` or `convert`) or `sips` to shrink them. Cells are coarse: a screenshot of text shows its layout, not text you can read.
- Only images pasted in the box while you write; once sent, the prompt shows no preview.
- Paths: a row of links under each reply block, not links inside the text. Paths with spaces are not found. Text is shown plain, with no syntax colors. A file over 1 MB or with a NUL byte shows only its size.
- On Linux the click opens the file's folder; there is no portable "select this file".
- A terminal multiplexer between Claude Code and the terminal must pass the mouse motion on.

## Credits
Inspired by [image-preview](https://github.com/midudev/better-claude/tree/master/plugins/image-preview) and [quick-peek](https://github.com/midudev/better-claude/tree/master/plugins/quick-peek) from midudev's [better-claude](https://github.com/midudev/better-claude) (MIT). This is a smaller rewrite, terminal-only; see `NOTICE`.

## Tests
```
claude plugin test plugins/hover-preview
```
