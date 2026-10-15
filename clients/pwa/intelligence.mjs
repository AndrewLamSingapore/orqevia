// Existing authenticated services, rendered inside the primary trusted PWA.
// No credentials or provider tokens are stored in JavaScript or browser storage.
export function safeSource(value){try{const u=new URL(value);return u.protocol==='https:'?u.href:null;}catch{return null;}}
export function freshness(value,now=Date.now()){const at=Date.parse(value);return Number.isFinite(at)&&at<=now+5000?(now-at<=900000?'FRESH':'STALE'):'UNKNOWN';}
export function mapPoint(location,width=960,height=480){const {lat,lon}=location||{};return Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180?[(lon+180)/360*width,(90-lat)/180*height]:null;}

if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id), root=$('intelligence-content');
 let session=null, generation=0, pending=null, active=new URL(location.href).searchParams.get('view')||'home';
 let restoring=null;
 const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 const status=(state,text)=>{const n=$('intelligence-state');n.dataset.state=state;n.textContent=text;};
 function panel(title){const p=node('section');p.className='intel-panel';p.append(node('h3',title));root.append(p);return p;}
 function record(p,label,value){const d=node('details');d.append(node('summary',label),node('pre',JSON.stringify(value,null,2)));p.append(d);return d;}
 function source(p,label,url){const href=safeSource(url);if(!href)return;const a=node('a',label);a.href=href;a.target='_blank';a.rel='noopener noreferrer';p.append(a);}
 async function request(path,{body,signal,recovered=false}={}){
  const r=await fetch(path,{method:body?'POST':'GET',body:body?JSON.stringify(body):undefined,credentials:'same-origin',cache:'no-store',redirect:'error',signal:signal||AbortSignal.timeout(12000),headers:{'Accept':'application/json','X-Jarvis-PWA':'1',...(body?{'Content-Type':'application/json'}:{})}});
  if(r.status===401&&!recovered&&path!=='/pwa/api/session'){
   restoring??=request('/pwa/api/session',{signal:AbortSignal.timeout(12000)}).finally(()=>{restoring=null;});
   const restored=await restoring;if(restored.authenticated)return request(path,{body,signal,recovered:true});
  }
  if(!r.ok){const e=new Error(r.status===401?'Device trust is unavailable. Use the recovery form below.':`Service returned ${r.status}`);e.status=r.status;throw e;}return r.json();
 }
 function drawMap(p,records){
  const c=node('canvas');c.width=960;c.height=480;c.setAttribute('aria-label','World grid with attributed earthquake observations; equivalent records below');p.append(c);
  const ctx=c.getContext('2d');if(!ctx){p.append(node('p','Canvas unavailable. All observations remain listed below.'));return;}
  ctx.strokeStyle='#456064';for(let x=0;x<=960;x+=80){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,480);ctx.stroke();}for(let y=0;y<=480;y+=80){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(960,y);ctx.stroke();}
  ctx.fillStyle='#83d6c1';for(const r of records){const xy=mapPoint(r.location);if(xy){ctx.beginPath();ctx.arc(...xy,4,0,2*Math.PI);ctx.fill();}}
 }
 function renderObservations(result){
  const p=panel("God's Eye · Geospatial observations"), rows=Array.isArray(result.records)?result.records:[];
  p.append(node('p',`${rows.length} stored observations · ${new Date().toLocaleString()} · public USGS data; not global live coverage.`));drawMap(p,rows);
  if(!rows.length)p.append(node('p','No observations stored. Refresh after an authorized ingestion run.'));
  for(const r of rows){const d=record(p,`${r.place||r.event_id} · M${r.magnitude} · ${freshness(r.ingested_at)}`,r);source(d,'Original provider evidence',r.source_url);}
 }
 function retrieval(){
  const p=panel('Knowledge retrieval · cited public observations'), form=node('form'), label=node('label','Search stored knowledge'), input=node('input'), button=node('button','Retrieve'), out=node('div');input.required=true;input.maxLength=4096;input.id='intelligence-query';label.htmlFor=input.id;button.type='submit';form.append(label,input,button);p.append(form,out);
  form.addEventListener('submit',async e=>{e.preventDefault();const epoch=generation;button.disabled=true;out.textContent='Retrieving cited evidence…';try{const result=await request('/api/orqevia/intelligence/rag/retrieve',{body:{query:input.value},signal:AbortSignal.timeout(30000)});if(epoch!==generation)return;out.replaceChildren(node('p',`Retrieval: ${result.status||'UNKNOWN'}`),node('pre',JSON.stringify(result,null,2)));for(const citation of result.results||[])source(out,'Open cited source',citation.source);}catch(err){if(epoch===generation)out.textContent=`Retrieval unavailable: ${err.message}. Retry when the service is available.`;}finally{button.disabled=false;}});
 }
 async function refresh(){
  if(!['intelligence','gods-eye'].includes(active)||pending)return;
  $('intelligence-title').textContent=active==='gods-eye'?"God's Eye":'Intelligence';
  if(!navigator.onLine){root.replaceChildren();status('offline','Offline. Reconnect and press Refresh. No cached private data is shown.');return;}
  if(!session){root.replaceChildren();const access=document.documentElement?.dataset.accessState;status(access==='untrusted'?'error':'loading',access==='untrusted'?'This device is not currently trusted. Restore access once using the recovery form below.':'Restoring trusted access. If the connection is unavailable, retry below.');return;}
  const epoch=generation, controller=new AbortController();pending=controller;const timer=setTimeout(()=>controller.abort(),30000);root.replaceChildren();status('loading','Loading authorized observations…');
  const specs=[['health','/api/orqevia/intelligence/health'],['events','/api/orqevia/intelligence/geo/events?limit=200'],['alerts','/api/orqevia/intelligence/detection/alerts'],['sources','/api/orqevia/intelligence/sources'],['history','/api/orqevia/intelligence/history/timeline'],['telemetry','/interface/v1/telemetry']];
  try{
   const results=await Promise.allSettled(specs.map(([,path])=>request(path,{signal:controller.signal})));if(epoch!==generation)return;if(controller.signal.aborted)throw new Error('Service deadline exceeded');
   const values=new Map(specs.map(([key],i)=>[key,results[i]]));let failures=0;
   const health=values.get('health');const hp=panel('Service health');if(health.status==='fulfilled'){record(hp,'Intelligence companion observation',health.value);}else{hp.append(node('p',`Unavailable: ${health.reason.message}`));failures++;}
   const events=values.get('events');if(events.status==='fulfilled')renderObservations(events.value);else{panel('Geospatial observations').append(node('p',`Unavailable: ${events.reason.message}`));failures++;}
   retrieval();
   const telemetry=values.get('telemetry'), op=panel('Operational visibility · agents and tasks');
   if(telemetry.status==='fulfilled'){
    const t=telemetry.value,at=Date.parse(t.observed_at), ttl=t.freshness_seconds*1000, fresh=Number.isFinite(at)&&at<=Date.now()+5000&&ttl>0&&ttl<=60000&&Date.now()-at<=ttl;
    op.append(node('p',`Telemetry: ${fresh?'OBSERVED':'STALE / UNKNOWN'} · ${t.observed_at||'unknown time'}. Registration is separate from agent availability.`));
    for(const m of t.metrics||[])record(op,m.metric_id,m);
    for(const a of t.agents||[])record(op,`${a.agent_id} · ${a.availability||'UNKNOWN'}`,a);
   }else{op.append(node('p',`Operational telemetry unavailable: ${telemetry.reason.message}. Intelligence remains independently usable.`));failures++;}
   const tasks=node('a','Open your owned tasks and original artifacts');tasks.href='/pwa/?view=evidence';op.append(tasks);
   for(const [key,title] of [['alerts','Alerts, exceptions and anomalies'],['history','Historical event feed'],['sources','Providers and provenance']]){const p=panel(title),r=values.get(key);if(r.status==='fulfilled'){if(key==='alerts'&&!r.value.alerts?.length)p.append(node('p','No alerts have fired. This does not assert that no hazards exist.'));record(p,'Inspect underlying records',r.value);}else{p.append(node('p',`Unavailable: ${r.reason.message}`));failures++;}}
   panel('Integration availability').append(node('p','Aviation, maritime and geopolitical providers are not connected. Formal semantic inference is unavailable. Existing geospatial, retrieval, history and operational observations do not depend on those integrations. Activity updates every 30 seconds while this page is visible.'));
   status(failures?'error':'ready',failures?`Loaded with ${failures} unavailable service(s). See each panel; Refresh retries recovery.`:'Authorized observations loaded. Open any record to inspect evidence and provenance.');
  }catch(e){if(epoch===generation)status('error',`Unable to load: ${e.message}. Press Refresh to recover.`);}
  finally{clearTimeout(timer);if(pending===controller)pending=null;}
 }
 window.addEventListener('orqevia-session',e=>{generation++;pending?.abort();pending=null;session=e.detail;sync.hidden=session?.role!=='OWNER';root.replaceChildren();void refresh();});
 window.addEventListener('orqevia-view',e=>{active=e.detail.name;generation++;pending?.abort();pending=null;void refresh();});
 window.addEventListener('offline',()=>{generation++;pending?.abort();pending=null;root.replaceChildren();status('offline','Offline. Reconnect to recover authorized observations.');});
 window.addEventListener('online',()=>void refresh());$('intelligence-refresh').addEventListener('click',()=>void refresh());
 const sync=$('intelligence-ingest');
 sync.addEventListener('click',async()=>{
  if(session?.role!=='OWNER'||sync.disabled)return;
  sync.disabled=true;const epoch=generation;status('loading','Synchronizing public USGS observations…');
  try{const result=await request('/api/orqevia/intelligence/ingest/run',{body:{},signal:AbortSignal.timeout(30000)});if(epoch!==generation)return;if(!result.ok)throw new Error('Provider ingestion failed; previous observations preserved');await refresh();}
  catch(e){if(epoch===generation)status('error',`Source synchronization unavailable: ${e.message}. Previous observations are preserved; retry when available.`);}
  finally{sync.disabled=false;}
 });
 setInterval(()=>{if(!document.hidden&&document.activeElement?.tagName!=='INPUT')void refresh();},30000);
 // Reuse the shell's existing handshake; do not race a second session refresh.
 window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
 void refresh();
}
