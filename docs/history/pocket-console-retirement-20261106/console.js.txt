'use strict';
const $=id=>document.getElementById(id);
let runtime=null;
async function api(path,body,headers={}){
 const response=await fetch(path,{credentials:'same-origin',cache:'no-store',headers:{...(body?{'Content-Type':'application/json'}:{}),...headers},...(body?{method:'POST',body:JSON.stringify(body)}:{})});
 if(!response.ok)throw new Error(`Service returned ${response.status}. ${response.status===401?'Open ORQEVIA with your trusted session.':response.status===503?'Factory configuration or storage is unavailable.':'Review ownership, source permission and execution state.'}`);
 return response.json();
}
function text(tag,value){const node=document.createElement(tag);node.textContent=value;return node;}
async function command(id,action,body={}){try{await api(`/api/activity-pockets/${encodeURIComponent(id)}/${action}`,body);await load();}catch(error){$('message').textContent=error.message;}}
function button(label,callback){const node=text('button',label);node.type='button';node.addEventListener('click',callback);return node;}
function render(pockets){
 const root=$('pockets');root.replaceChildren();
 if(!pockets.length){root.append(text('p','No pockets have been created for this owner.'));return;}
 for(const pocket of pockets){
  const node=document.createElement('article');node.append(text('h3',pocket.manifest.objective),text('p',`${pocket.state} · ${pocket.reason||'No blocking finding'} · extraction version ${pocket.version}`));
  const actions=document.createElement('div');actions.className='actions';
  for(const action of (pocket.state==='READY'||pocket.state==='RUNNING'?['pause','cancel']:pocket.state==='PAUSED'?['resume','cancel']:pocket.state!=='RETIRED'?['retire']:[]))actions.append(button(action,()=>command(pocket.id,action)));
  for(const proposal of pocket.coaching_proposals||[]){const evaluation=(pocket.evaluations||[]).find(e=>e.proposal_id===proposal.id&&e.passed);if(evaluation&&pocket.reason==='QUALITY_FAILURE')actions.append(button('Approve evaluated extraction change',()=>command(pocket.id,'promote',{proposal_id:proposal.id,evaluation_id:evaluation.id,reason:'Owner reviewed the displayed execution and held-out evaluation evidence.'})));}
  node.append(actions);
  const details=document.createElement('details');details.append(text('summary','Show full owned state and evidence'),text('pre',JSON.stringify(pocket,null,2)));node.append(details);
  node.append(button('Show event chain',async()=>{try{const events=await api(`/api/activity-pockets/${encodeURIComponent(pocket.id)}/events`);details.open=true;details.append(text('pre',JSON.stringify(events,null,2)));}catch(error){$('message').textContent=error.message;}}));root.append(node);
 }
}
async function load(){
 $('message').textContent='Refreshing service evidence…';
 try{
  const [status,pockets,coverage]=await Promise.all([api('/api/activity-pockets/status'),api('/api/activity-pockets'),api('/api/activity-pockets/coverage')]);
  runtime=status;$('runtime').textContent=JSON.stringify(status,null,2);$('coverage').textContent=JSON.stringify(coverage,null,2);render(pockets);
  const selected=$('source').value;$('source').replaceChildren();for(const source of status.sources){const option=text('option',source.id);option.value=source.id;$('source').append(option);}if(selected)$('source').value=selected;
  $('message').textContent=status.configuration==='NO_AUTHORIZED_SOURCES'?'Factory is available. No permitted sources are configured.':`Evidence refreshed. Worker: ${status.worker.state}. Production readiness: ${status.production_ready?'verified':'not established'}.`;
 }catch(error){$('message').textContent=error.message;}
}
$('refresh').addEventListener('click',load);
$('create').addEventListener('submit',async event=>{event.preventDefault();if(!runtime)return;try{
 const manifest={owner:runtime.owner_scope,objective:$('objective').value,source_ids:[$('source').value],permissions:['provided_context.read'],success_criteria:$('criteria').value,provenance:{component:'orqevia',source_revision:runtime.source_revision,reference:'ORQEVIA Activity Pocket console'}};
 await api('/api/agents/objectives/activity-pocket',manifest,{'idempotency-key':crypto.randomUUID()});await load();
}catch(error){$('message').textContent=error.message;}});
load();
