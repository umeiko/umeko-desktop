# Umeko documentation site

A shared Chinese / English user guide for the Python and C++ editions, built with VitePress ([#31](https://github.com/umeiko/umeko-desktop/issues/31)). The site has its own dependencies, separate from the desktop app.

## Local development

Use Node.js 22.19+ and npm:

```bash
cd docs-site
npm ci
npm run dev
```

Build and check the actual static output:

```bash
npm run build
npm run preview
```

Open the Local URL printed by VitePress (including `/umeko-desktop/`). Preview binds to `127.0.0.1`. `npm run build` checks language parity and every generated internal target, asset and anchor, and VitePress reports dead Markdown links. To test root-path hosting, run `DOCS_BASE=/ npm run build`.

The lockfile pins the dependency tree. The site uses VitePress 1.6.4 with Vite overridden to 6.4.5, which the bundled Vue plugin supports; this avoids advisories in VitePress's original Vite 5 dependency. After changing this override, check build, preview and search. All dependencies are build-time only and live outside `runtime/package.json`.

## Structure and translation

- Root: Simplified Chinese; `en/`: matching English pages. Language switching keeps the current page.
- `.vitepress/config.mts`: shared navigation, localized labels, local search and base path.
- `.vitepress/theme/`: a small theme extension with local assets only.
- `public/`: local branding, separately captured Chinese/English application screenshots, capture manifests and an importable pure-white theme. Branding provenance lives in `app/icons`.
- `scripts/check-site.mjs`: checks the production output locally.

Change matching language pages together. Headings use explicit shared `{#anchor}` IDs so language switching and search links land on the same section; keep these IDs when rewording headings. To add a language, provide matching routes and localized navigation, then extend the parity checker to cover it. Write task-oriented user instructions and link exact SDK interfaces to their source documentation.

Content follows `main`. Mark edition differences and features that are not in a stable Release yet. Source links point to each repository's `main`; the build checks internal links only.

Local search uses `Intl.Segmenter` for Chinese and mixed-language text, which current browsers support. The site runs as static files with local search, fonts and assets.

## Update screenshots

Use the current source checkout with its prepared Pi runtime and project PySide6 environment:

```bash
.venv/bin/python scripts/capture-documentation.py --language zh
.venv/bin/python scripts/capture-documentation.py --language en
```

Run from the repository root. The capture script creates disposable profiles with synthetic data and captures the real current QML/Widget interfaces without model calls. It applies `public/examples/pure-white.umeko-theme.json` in both languages. Each manifest records the source commit, app version, language, theme and image hashes; the site build verifies them and keeps each language on its own images. Regenerate both sets when the UI changes. Keep personal profiles and credentials out of captures. Markdown images load lazily with reserved dimensions and link to full-size originals.

## GitHub Pages

The `Documentation` workflow builds and validates on relevant PRs, main pushes and manual runs. PR runs use read-only permissions and only build. Main pushes deploy after the documentation build passes, independently of desktop packaging and Releases. A manual run can build only or deploy main.

To publish the site, a maintainer can:

1. Enable **Settings → Pages → Source: GitHub Actions** in `umeiko/umeko-desktop`.
2. Merge validated documentation into `main` to deploy it, or run **Actions → Documentation → Run workflow** on `main` with **Deploy the validated documentation to GitHub Pages** enabled.
3. Check that both build and deployment succeed. The project site is `https://umeiko.github.io/umeko-desktop/`.

The default base is `/umeko-desktop/`. Use `DOCS_BASE=/` for a root-domain deployment and rebuild for each destination. The static output in `.vitepress/dist` works on any static host. The Pages deployment uses the `github-pages` environment and publishes only the site; tags, app versions and desktop Releases stay as they are.
