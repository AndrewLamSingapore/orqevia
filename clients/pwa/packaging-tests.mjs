// The complete shell and its real module imports must exist in every image recipe.
import assert from 'node:assert/strict';
import {readFileSync,statSync} from 'node:fs';
import {resolve,posix} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const root=resolve(process.env.ORQEVIA_PACKAGING_SOURCE||fileURLToPath(new URL('../..',import.meta.url)));
const publicRoot=resolve(root,'clients/pwa');
const assetPath=name=>name.startsWith('design/')?resolve(root,'clients/shared',name.slice(7)):resolve(publicRoot,name);
const read=path=>readFileSync(assetPath(path),'utf8');
const shell=JSON.parse(read('sw.js').match(/const SHELL=(\[[^;]+\]);/)[1].replaceAll("'",'"'));
const required=new Set(['sw.js','projects.html','reset.html',...shell.map(path=>path==='/pwa/'?'index.html':path.slice('/pwa/'.length))]);
const pending=[...required];
while(pending.length){
  const name=pending.pop();assert.ok(!name.startsWith('../')&&!name.startsWith('/'));
  assert.ok(statSync(assetPath(name)).isFile(),`Required asset is missing: ${name}`);
  if(!/\.(?:m?js|html)$/.test(name))continue;
  const content=read(name),references=name.endsWith('.html')?
    [...content.matchAll(/<(?:script|link)\b[^>]*(?:src|href)=["']([^"']+)["']/g)].map(match=>match[1]):
    [...content.matchAll(/(?:from\s*|import\s*)['"](\.[^'"]+)['"]/g)].map(match=>match[1]);
  for(const reference of references){
    if(/^(?:https?:|data:|#)/.test(reference))continue;
    const clean=reference.split(/[?#]/)[0];
    const target=clean.startsWith('/pwa/')?clean.slice(5):clean.startsWith('/design/')?clean.slice(1):posix.normalize(posix.join(posix.dirname(name),clean));
    if(!required.has(target)){required.add(target);pending.push(target);}
  }
}

for(const recipe of ['Dockerfile','deploy/Dockerfile.https-runtime'])test(`${recipe} packages the complete shell and transitive modules`,()=>{
  const copied=[];
  for(const line of readFileSync(resolve(root,recipe),'utf8').split(/\r?\n/)){
    const words=line.trim().split(/\s+/);if(words.shift()!=='COPY')continue;
    const destination=words.pop();if(!/(?:pwa_static|shared_static)/.test(destination||''))continue;
    for(const source of words){
      if(!source.startsWith('clients/pwa/')&&!source.startsWith('clients/shared'))continue;
      const relative=source.startsWith('clients/pwa/')?source.slice('clients/pwa/'.length):'design'+source.slice('clients/shared'.length);
      copied.push({relative,directory:statSync(resolve(root,source)).isDirectory()});
    }
  }
  for(const name of required)assert.ok(copied.some(item=>item.relative===name||(item.directory&&name.startsWith(item.relative+'/'))),`${recipe} omits required public asset ${name}`);
});
