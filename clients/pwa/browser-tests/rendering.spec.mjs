// Source fixtures under the closed production CSP; never live owner data.
import {expect,test} from '@playwright/test';
import {mockSession,waitForSession,expectNoHorizontalOverflow} from './fixtures.mjs';

const CLOSED_CSP="default-src 'self'; connect-src 'self'; worker-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";
async function closedPage(page,view='home'){
 await mockSession(page);
 await page.addInitScript(()=>{globalThis.__policyFailures=[];document.addEventListener('securitypolicyviolation',event=>globalThis.__policyFailures.push(event.effectiveDirective));});
 await page.route(/\/pwa\/\?view=/,async route=>{const response=await route.fetch();await route.fulfill({response,headers:{...response.headers(),'content-security-policy':CLOSED_CSP}});});
 await page.goto('/pwa/?view='+view);await waitForSession(page);
}

test('all original map icons load from same-origin SVG files under the closed policy',async({page})=>{
 await closedPage(page);
 const measured=await page.evaluate(async()=>{
  const manifest=await(await fetch('/pwa/vendor/MAPLIBRE-ASSET-PROVENANCE.json')).json();
  const link=document.createElement('link');link.rel='stylesheet';link.href='/pwa/vendor/maplibre-gl.css';document.head.append(link);await new Promise((resolve,reject)=>{link.onload=resolve;link.onerror=reject;});
  const host=document.createElement('section');host.className='maplibregl-map';document.body.append(host);
  const controls=document.createElement('div');controls.className='maplibregl-ctrl';host.append(controls);
  for(const name of ['zoom-in','zoom-out','compass']){const button=document.createElement('button');button.className='maplibregl-ctrl-'+name;const span=document.createElement('span');span.className='maplibregl-ctrl-icon';button.append(span);controls.append(button);}
  const attribution=document.createElement('div');attribution.className='maplibregl-ctrl-attrib maplibregl-compact';host.append(attribution);const toggle=document.createElement('button');toggle.className='maplibregl-ctrl-attrib-button';attribution.append(toggle);
  const images=await Promise.all(manifest.icons.map(icon=>new Promise((resolve,reject)=>{const image=new Image();image.alt='Bundled map icon';image.onload=()=>resolve({same_origin:new URL(image.src).origin===location.origin,width:image.naturalWidth,height:image.naturalHeight});image.onerror=reject;image.src=icon.path;host.append(image);})));
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const backgrounds=[...controls.querySelectorAll('.maplibregl-ctrl-icon'),toggle].map(node=>getComputedStyle(node).backgroundImage);
  return {images,backgrounds,violations:globalThis.__policyFailures};
 });
 expect(measured.images).toHaveLength(31);expect(measured.images.every(image=>image.same_origin&&image.width>0&&image.height>0)).toBe(true);
 expect(measured.backgrounds.every(image=>image==='none'||image.includes('/pwa/vendor/maplibre-icons/'))).toBe(true);
 expect(measured.violations).toEqual([]);
});

test('native desktop map uses its existing same-origin worker without policy errors',async({page,browserName})=>{
 await closedPage(page);await page.setViewportSize({width:1440,height:1100});
 await page.route('**/api/orqevia/intelligence/geo/features?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({type:'FeatureCollection',features:[]})}));
 const workers=[];page.on('worker',worker=>workers.push(new URL(worker.url()).pathname));
 const rendered=await page.evaluate(async()=>{
  const host=document.createElement('section');document.getElementById('dashboard').append(host);
  const {mountCommandMap}=await import('/pwa/command-map.mjs');
  const result=await mountCommandMap(host,{records:[]});
  return {loaded:Boolean(result.map),policy_failures:globalThis.__policyFailures};
 });
 expect(rendered.policy_failures).toEqual([]);
 if(browserName==='chromium')expect(rendered.loaded).toBe(true);
 test.info().annotations.push({type:'map_runtime',description:rendered.loaded?'Native map initialized':'WebGL unavailable; native readable fallback observed'});
 if(rendered.loaded){expect(workers).toContain('/pwa/vendor/maplibre-gl-worker.mjs');await expect(page.locator('.maplibregl-ctrl-zoom-in')).toBeVisible();}
 else await expect(page.getByText('Interactive map unavailable:',{exact:false})).toBeVisible();
});

test('full consequential-action hashes and metadata wrap at 320 and 390 pixels',async({page})=>{
 const hash='abcdef0123456789'.repeat(4),reference='fixture-reference-'+hash;
 await page.route('**/interface/v1/osip/approvals',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({protocol:'orqevia.osip.v1',approvals:[{action_type:'external.write',status:'APPROVED',correlation_id:reference,idempotency_key:reference,envelope_sha256:hash,review:{status:'APPROVED',fixture:true},reviewable:false}]})}));
 await closedPage(page,'settings');const record=page.locator('.oq-approval');await expect(record).toContainText(hash);await expect(record).toContainText(reference);
 for(const width of [320,390]){
  await page.setViewportSize({width,height:844});await expectNoHorizontalOverflow(page);
  const fields=await record.locator('small').evaluateAll((nodes,values)=>nodes.map(node=>{const rect=node.getBoundingClientRect();return {text:node.textContent,complete_hash:node.textContent.includes(values.hash),right:rect.right,wrap:getComputedStyle(node).overflowWrap};}),{hash});
  expect(fields.every(field=>field.right<=width+1&&field.wrap==='anywhere')).toBe(true);expect(fields.some(field=>field.complete_hash)).toBe(true);
  await expect(record.locator('pre')).toContainText('"fixture": true');await expect(record).toContainText(reference);
 }
 expect(await page.evaluate(()=>globalThis.__policyFailures)).toEqual([]);
});
