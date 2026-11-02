import assert from 'node:assert/strict'
import { readdir, readFile, stat } from 'node:fs/promises'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = join(root, '.vitepress/dist')
const base = process.env.DOCS_BASE || '/umeko-desktop/'
const failures = []

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const children = await Promise.all(entries.map(async entry => {
    if (['node_modules', '.vitepress', 'public', 'scripts'].includes(entry.name)) return []
    const path = join(dir, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  }))
  return children.flat()
}

const sources = (await walk(root)).filter(path => path.endsWith('.md') && relative(root, path) !== 'README.md')
const zh = sources.filter(path => !relative(root, path).startsWith('en/')).map(path => relative(root, path)).sort()
const en = sources.filter(path => relative(root, path).startsWith('en/')).map(path => relative(join(root, 'en'), path)).sort()
assert.deepEqual(zh, en, 'Chinese and English must have matching page paths')
assert.ok(zh.length >= 10, 'The guide must contain substantive content in both languages')

const captures = []
for (const language of ['zh', 'en']) {
  const metadata = JSON.parse(await readFile(join(root, `public/images/capture-${language}.json`), 'utf8'))
  assert.equal(metadata.language, language)
  assert.equal(metadata.theme, 'docs-white', 'Documentation screenshots use the pure-white app theme')
  assert.match(metadata.sourceCommit, /^[a-f0-9]{40}$/)
  const names = []
  for (const entry of metadata.captures) {
    assert.ok(entry.file.endsWith(`-${language}.png`))
    const bytes = await readFile(join(root, 'public/images', entry.file))
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256, `Screenshot provenance mismatch: ${entry.file}`)
    names.push(entry.file.replace(`-${language}.png`, ''))
  }
  captures.push(names.sort())
}
assert.deepEqual(captures[0], captures[1], 'Every captured scene needs separate Chinese and English UI')
for (const path of sources) {
  const otherLanguage = relative(root, path).startsWith('en/') ? 'zh' : 'en'
  assert.ok(!(await readFile(path, 'utf8')).includes(`-${otherLanguage}.png`), `Wrong screenshot language: ${path}`)
}

const cache = new Map()
async function html(path) {
  if (!cache.has(path)) cache.set(path, await readFile(path, 'utf8'))
  return cache.get(path)
}
function decode(value) {
  return value.replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"')
}

for (const page of zh) {
  const output = page.replace(/\.md$/, '.html')
  const headings = document => [...document.matchAll(/<h[1-6] id="([^"]+)"/g)].map(match => match[1])
  assert.deepEqual(
    headings(await html(join(dist, output))),
    headings(await html(join(dist, 'en', output))),
    `Translated headings must share stable anchors for language switching: ${page}`
  )
}

let links = 0
for (const source of sources) {
  const page = relative(root, source).replace(/\.md$/, '.html')
  const output = join(dist, page)
  const document = await html(output)
  const lang = page.startsWith('en/') ? 'en' : 'zh-Hans'
  assert.ok(document.includes(`lang="${lang}"`), `Wrong document language: ${page}`)
  for (const [tag] of document.matchAll(/<(?:a|link|script|img)\b[^>]*>/gi)) {
    for (const [, , raw] of tag.matchAll(/\b(href|src)="([^"]*)"/gi)) {
      const value = decode(raw)
      if (!value || /^(?:https?:|mailto:|tel:|data:|javascript:|\/\/)/i.test(value)) continue
      const url = new URL(value, `https://docs.invalid${base}${page}`)
      if (!url.pathname.startsWith(base)) {
        failures.push(`${page}: URL escapes deployment base: ${value}`)
        continue
      }
      let localPath = decodeURIComponent(url.pathname.slice(base.length))
      if (localPath.endsWith('/') || !localPath) localPath += 'index.html'
      const target = resolve(dist, localPath)
      if (!target.startsWith(`${dist}/`)) {
        failures.push(`${page}: URL escapes build directory: ${value}`)
        continue
      }
      links++
      try {
        assert.ok((await stat(target)).isFile())
        if (url.hash && target.endsWith('.html')) {
          const id = decodeURIComponent(url.hash.slice(1))
          if (!(await html(target)).includes(`id="${id}"`)) failures.push(`${page}: missing anchor: ${value}`)
        }
      } catch {
        failures.push(`${page}: missing local target: ${value}`)
      }
    }
  }
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exitCode = 1
} else {
  console.log(`Docs verified: ${sources.length} pages, ${zh.length} translation pairs, ${links} local links/assets/anchors.`)
}
