import {mkdir,copyFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname,join} from 'node:path';
const require=createRequire(import.meta.url),root=dirname(require.resolve('maplibre-gl/package.json')),out=new URL('./vendor/',import.meta.url);
await mkdir(out,{recursive:true});
for(const name of ['maplibre-gl.mjs','maplibre-gl-shared.mjs','maplibre-gl-worker.mjs','maplibre-gl.css'])await copyFile(join(root,'dist',name),new URL(name,out));
await copyFile(join(root,'LICENSE.txt'),new URL('MAPLIBRE-LICENSE.txt',out));
