// The complete shell and its real module imports must exist in every image recipe.
import assert from 'node:assert/strict';
import {readFileSync,statSync} from 'node:fs';
import {resolve,posix} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import vm from 'node:vm';
import {hash,materializeImages,UPSTREAM_CSS_SHA256,MAPLIBRE_VERSION} from './build-map-assets.mjs';

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

const provenance=JSON.parse(read('vendor/MAPLIBRE-ASSET-PROVENANCE.json'));
const original=readFileSync(resolve(root,provenance.upstream.source_copy));
const materialized=materializeImages(original.toString('utf8'));

test('reviewed upstream map CSS and exact decoded SVG bytes reproduce every generated icon',()=>{
  assert.equal(hash(original),UPSTREAM_CSS_SHA256);assert.equal(provenance.upstream.version,MAPLIBRE_VERSION);
  assert.equal(materialized.occurrences,39);assert.equal(materialized.icons.length,32);
  assert.equal(provenance.image_occurrences,39);assert.equal(provenance.icons.length,32);
  assert.equal(read('vendor/maplibre-gl.css'),materialized.css);
  assert.equal(hash(materialized.css),provenance.generated_css_sha256);
  assert.doesNotMatch(materialized.css,/data:image\//i);
  for(const icon of materialized.icons){
    const actual=readFileSync(assetPath(icon.path.slice(5))),record=provenance.icons.find(item=>item.sha256===icon.sha256);
    assert.deepEqual(actual,icon.bytes);assert.equal(hash(actual),icon.sha256);assert.equal(record.bytes,actual.length);
    assert.equal(record.occurrences,icon.occurrences);assert.deepEqual(record.source_data_url_sha256,[...icon.source_data_url_sha256].sort());
    assert.ok(materialized.css.includes(`url("${icon.path}")`));
  }
});

test('map image conversion deduplicates decoded bytes and rejects unreviewed active formats',()=>{
  const svg='<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1"/></svg>';
  const url='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
  const first=materializeImages(`a{background:url("${url}")}b{background:url('${url}')}`);
  assert.equal(first.icons.length,1);assert.equal(first.occurrences,2);assert.deepEqual(first.icons[0].bytes,Buffer.from(svg));
  assert.equal(materializeImages(`a{background:url("${url}")}b{background:url('${url}')}`).css,first.css);
  assert.throws(()=>materializeImages('a{background:url("data:image/png;base64,AA==")}'),/Unreviewed map image encoding/);
  assert.throws(()=>materializeImages('a{background:url("data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg><script/></svg>')+'")}'),/Unreviewed active map SVG/);
});

test('upstream map modules and BSD notice retain their recorded byte integrity',()=>{
  assert.equal(provenance.upstream.license,'BSD-3-Clause');
  assert.equal(hash(readFileSync(assetPath('vendor/MAPLIBRE-LICENSE.txt'))),provenance.upstream.license_sha256);
  assert.match(read('vendor/MAPLIBRE-LICENSE.txt'),/Copyright \(c\) 2023, MapLibre contributors/);
  for(const [name,expected] of Object.entries(provenance.upstream.unchanged_modules)){
    const actual=readFileSync(assetPath('vendor/'+name));assert.equal(actual.length,expected.bytes);assert.equal(hash(actual),expected.sha256);
  }
});

test('every materialized map icon and its notices belong to the literal offline shell',()=>{
  const paths=provenance.icons.map(icon=>icon.path);
  assert.deepEqual(shell.filter(path=>path.startsWith('/pwa/vendor/maplibre-icons/')).sort(),paths.sort());
  assert.ok(shell.includes('/pwa/vendor/MAPLIBRE-ASSET-PROVENANCE.json'));assert.ok(shell.includes('/pwa/vendor/MAPLIBRE-LICENSE.txt'));
  assert.equal(new Set(shell).size,shell.length);
});

test('actual worker retrieves each complete map icon from only its current offline generation',async()=>{
  const listeners=new Map(),installed=[];let activeCache;
  const self={location:{origin:'https://offline.invalid'},addEventListener(name,handler){listeners.set(name,handler);},skipWaiting(){},clients:{claim(){}}};
  const caches={async open(name){activeCache=name;return {async addAll(values){installed.push(...values);},async match(path){assert.ok(installed.includes(path));return new Response(readFileSync(assetPath(path.slice(5))));}};}};
  vm.runInNewContext(read('sw.js'),{self,caches,URL,Response,fetch:async()=>{throw new Error('offline fixture');}});
  let install;listeners.get('install')({waitUntil(promise){install=promise;}});await install;
  for(const icon of provenance.icons){let response;listeners.get('fetch')({request:{method:'GET',url:self.location.origin+icon.path},respondWith(promise){response=promise;}});assert.equal(hash(Buffer.from(await(await response).arrayBuffer())),icon.sha256);}
  assert.equal(activeCache,read('sw.js').match(/const CACHE='([^']+)'/)[1]);
});
