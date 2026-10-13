import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=name=>readFileSync(new URL(name,import.meta.url),'utf8');
test('brand migration keeps installed app identity and private storage compatibility',()=>{
  const manifest=JSON.parse(read('./manifest.webmanifest'));
  assert.equal(manifest.name,'ORQEVIA');assert.equal(manifest.short_name,'ORQEVIA');
  assert.deepEqual([manifest.id,manifest.start_url,manifest.scope],['/pwa/','/pwa/','/pwa/']);
  const html=read('./index.html');assert.match(html,/<title>ORQEVIA<\/title>/);assert.match(html,/apple-mobile-web-app-title" content="ORQEVIA"/);assert.match(html,/奥启维亚/);assert.doesNotMatch(html,/JARVIS|\bPRIME\b/);
  assert.match(read('./storage.mjs'),/indexedDB.open\('jarvis-client-reference',1\)/);
  assert.match(read('./core.mjs'),/X-Jarvis-PWA/);
});
test('versioned brand assets exist and every current icon is in the offline shell',()=>{
  const sw=read('./sw.js'),release=read('./release.mjs');
  assert.match(sw,/const CACHE='orqevia-shell-v20'/);assert.match(release,/const RELEASE='orqevia-shell-v20'/);
  for(const [name,size]of[['orqevia-official-v1-192.png',192],['orqevia-official-v1-512.png',512],['orqevia-official-v1-apple-touch.png',180]]){
    assert.ok(sw.includes(`/pwa/icons/${name}`));const bytes=readFileSync(new URL(`./icons/${name}`,import.meta.url));
    assert.equal(bytes.subarray(1,4).toString(),'PNG');assert.equal(bytes.readUInt32BE(16),size);assert.equal(bytes.readUInt32BE(20),size);
  }
  assert.ok(sw.includes("key.startsWith('jarvis-shell-')"));assert.ok(sw.includes("key.startsWith('orqevia-shell-')"));
});
