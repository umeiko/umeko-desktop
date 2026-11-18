import { readFile } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { build, transform } from 'esbuild';

const release = resolve(process.argv[2]);
const sdk = './node_modules/@earendil-works/pi-coding-agent/dist/';

await build({
  absWorkingDir: release,
  entryPoints: ['bridge.mjs'],
  outfile: 'bridge.bundle.mjs',
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node22.19',
  banner: { js: 'import { createRequire as createBundleRequire } from "node:module"; const require = createBundleRequire(import.meta.url);' },
  external: [
    '@silvia-odwyer/photon-node', 'jiti', 'bufferutil', 'utf-8-validate', 'kerberos', 'supports-color',
    'quickjs-wasi', '@modelcontextprotocol/sdk',
  ],
  legalComments: 'eof',
  minifyWhitespace: true,
  plugins: [{
    name: 'preserve-pi-runtime-paths',
    setup(builder) {
      builder.onLoad({ filter: /\.[cm]?js$/ }, async ({ path }) => {
        let source = await readFile(path, 'utf-8');
        const file = relative(release, path).replaceAll('\\', '/');
        if (file === 'bridge.mjs' || file === 'system-prompt.mjs') {
          // esbuild cannot follow import(new URL()). Convert only Pi's fixed internal imports.
          const imports = /import\(new URL\(["']\.\/(core\/[^"']+|extensions\/mcp\/config\.js)["'],\s*(?:entry|import\.meta\.resolve\(["']@earendil-works\/pi-coding-agent["']\))\)\)/g;
          source = source.replace(imports, (_, name) => `import(${JSON.stringify(sdk + name)})`);
        }
        if (file === 'bridge.mjs' || !source.includes('import.meta.url')) {
          return { contents: source, resolveDir: dirname(path) };
        }
        // Keep the original URLs for assets, worker scripts and CLI guards.
        const { code } = await transform(source, {
          sourcefile: path,
          define: { 'import.meta.url': '__umekoModuleUrl' },
          banner: `const __umekoModuleUrl = new URL(${JSON.stringify('./' + file)}, import.meta.url).href;`,
        });
        return { contents: code, resolveDir: dirname(path) };
      });
    },
  }],
});
