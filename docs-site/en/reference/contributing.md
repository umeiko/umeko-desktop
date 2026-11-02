# Contribute to the docs {#contribute-to-the-docs}

Use **Improve this page on GitHub** at the bottom of a page to edit its Markdown. You can also [report an issue](https://github.com/umeiko/umeko-desktop/issues/new) with the page, app version and correct behavior.

## Writing conventions {#writing-conventions}

- Docs follow main. Identify unreleased capabilities and differences between editions.
- Match current UI labels. Verify workflows before documenting them; do not describe planned features as available.
- Use isolated demo data for screenshots, without real accounts, Keys, private paths or conversations.
- Explain user goals and steps first; link exact interfaces to SDK specifications in source.
- Update matching root and `en/` pages together. New languages need the same page set and navigation so language switches do not lead to missing pages.
- Keep matching `{#anchor}` IDs on translated headings so language switching preserves the section. Do not change these IDs just to reword a heading.

## Build locally {#build-locally}

```bash
cd docs-site
npm ci
npm run dev
```

Run `npm run build` for a production build and checks for translation parity, internal targets, anchors and local assets. Use `npm run preview` and open its printed local address to inspect the result.

The site uses local full-text search, without an external search service, remote fonts or analytics. Its dependencies are separate from desktop runtimes. See the [site README](https://github.com/umeiko/umeko-desktop/blob/main/docs-site/README.md) for deployment and maintenance.
