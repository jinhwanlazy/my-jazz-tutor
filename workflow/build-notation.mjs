// Rebuild pinned third-party assets; no package installation at runtime.
import {build} from 'esbuild';
import {copyFile} from 'node:fs/promises';
await build({entryPoints: ['abc-parser-entry.cjs'], outfile: 'abc-parser.cjs',
  bundle: true, platform: 'node', format: 'cjs', minify: true, legalComments: 'eof'});
await copyFile('node_modules/abcjs/dist/abcjs-basic-min.js', 'abcjs.min.js');
await copyFile('node_modules/abcjs/LICENSE.md', 'abcjs-LICENSE.md');
await copyFile('node_modules/abcjs/dist/abcjs-basic-min.js.LICENSE', 'abcjs.min.js.LICENSE');
