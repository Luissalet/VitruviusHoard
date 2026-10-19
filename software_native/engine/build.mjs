import {readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {build} from 'esbuild';

const root = dirname(fileURLToPath(import.meta.url));
const sources = (await readdir(join(root, 'src'), {recursive:true})).filter(path => path.endsWith('.ts'));
const own=(await readdir(root)).filter(path=>path.endsWith('.ts')).map(path=>join(root,path));
await build({entryPoints:[...own, ...sources.map(path => join(root,'src',path))],
  outbase:root, outdir:join(root,'dist'), platform:'node', format:'esm', target:'node22'});
