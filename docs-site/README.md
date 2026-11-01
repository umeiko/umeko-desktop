# Umeko documentation site

Issue [#31](https://github.com/umeiko/umeko-desktop/issues/31): a shared Chinese / English user guide for the Python and C++ editions, built with VitePress. No desktop dependency or install-size change.

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

Open the Local URL printed by VitePress (including `/umeko-desktop/`). Preview binds only to `127.0.0.1`. `npm run build` checks language parity and every generated internal target, asset and anchor. VitePress also rejects dead Markdown links. Test root-path hosting with `DOCS_BASE=/ npm run build` if changing hosting.

The lockfile pins the dependency tree. VitePress 1.6.4 is the stable release; Vite is overridden to 6.4.5 to avoid advisories in VitePress's old Vite 5 dependency. The bundled Vue plugin supports Vite 6. Validate build, preview and search when changing this override. Dependencies are build-time only and are not added to `runtime/package.json`.

## Structure and translation

- Root: Simplified Chinese; `en/`: matching English pages. Language switching retains the current page.
- `.vitepress/config.mts`: shared navigation, localized labels, local search and base path.
- `.vitepress/theme/`: a small theme extension, with no external fonts or scripts.
- `public/`: local branding, separately captured Chinese/English application screenshots, capture manifests and an importable pure-white theme. Branding provenance remains in `app/icons`.
- `scripts/check-site.mjs`: production-output checks, without a browser or external service.

Change matching language pages together. Headings use explicit shared `{#anchor}` IDs so language switching preserves the section, including links from search. Keep these IDs stable when rewording headings. To add another language, provide matching routes and localized navigation, then extend the parity checker to cover it. Do not leave translation links pointing to missing pages. Prefer task-oriented user instructions and link exact SDK interfaces to their existing source documentation, avoiding duplicate interface definitions.

Content follows `main`, rather than claiming every feature is in the latest stable Release. When edition behavior differs or functionality has not shipped, say so. Source links use each repository's `main`; no automatic external URL checker makes network availability a build requirement.

Local search uses `Intl.Segmenter` for Chinese and mixed-language text. This requires a current browser with `Intl.Segmenter` support. No analytics, CDN fonts, remote search account or runtime server is required.

## Update screenshots

Use the current source checkout with its prepared Pi runtime and project PySide6 environment:

```bash
.venv/bin/python scripts/capture-documentation.py --language zh
.venv/bin/python scripts/capture-documentation.py --language en
```

Run from the repository root. The capture script creates disposable profiles and synthetic data, uses the real current QML/Widget interfaces, and never makes model calls. It applies `public/examples/pure-white.umeko-theme.json` in both languages. Each manifest records the source commit, app version, language, theme and image hashes; the site build verifies them and rejects cross-language image references. Regenerate both sets when UI changes. Do not use a personal profile or capture credentials. Markdown images load lazily with reserved dimensions and link to full-size originals.

## GitHub Pages

The `Documentation` workflow builds and validates on relevant PRs, main pushes and manual runs. PRs have read-only repository permissions and never deploy. Main pushes deploy only after the documentation build passes, independently of desktop packaging or Releases. A manual run can build only or explicitly deploy main.

After acceptance, a maintainer can:

1. Enable **Settings → Pages → Source: GitHub Actions** in `umeiko/umeko-desktop`.
2. Merge validated documentation into `main` to deploy it, or run **Actions → Documentation → Run workflow** on `main` with **Deploy the validated documentation to GitHub Pages** enabled.
3. Check that both build and deployment succeed. The expected project-site URL is `https://umeiko.github.io/umeko-desktop/`; it is not live merely because these source files exist.

The default base is `/umeko-desktop/`. `DOCS_BASE=/` can be used for a root-domain deployment; rebuild for the destination. The static output is `.vitepress/dist`, suitable for other static hosting without changing content. The Pages deployment uses the `github-pages` environment and does not create a tag, change application versions or publish a desktop Release.
