// Authorized projections only. No credentials, prompts or result bodies are cached.
const $=id=>document.getElementById(id);
const make=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
let session=null,epoch=0,pending=null,active=new URL(location.href).searchParams.get('view')||'home';
const ownViews=new Set(['plane','approvals']);
function invalidate(){epoch++;pending?.abort();pending=null;for(const id of ['osip-content','approval-content'])$(id)?.replaceChildren();}
function state(id,text,error=false){const node=$(id);if(node){node.textContent=text;node.dataset.state=error?'error':'ready';}}
async function api(path,{body,signal}={}){
  const response=await fetch('/interface/v1/osip/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal,
    headers:{'Content-Type':'application/json','X-ORQEVIA-PWA':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){const error=new Error(response.status===401?'Your session has expired. Restore your connection.':response.status===403?'This view requires the bound owner account.':response.status===429?'Request limit reached. Wait a moment before retrying.':`Service unavailable (${response.status}). Retry when the service is ready.`);error.status=response.status;throw error;}
  const value=await response.json();if(value?.protocol!=='orqevia.osip.v1')throw new Error('The service returned an unsupported contract.');return value;
}
function module(title){const node=make('section',undefined,'oq-module');node.append(make('h2',title));return node;}
function detail(parent,title,value,description){const row=make('div',undefined,'oq-detail'),name=make('strong',title);if(description)name.append(make('small',description));row.append(name,make('span',value,'oq-tag'));parent.append(row);}
function drawPlane(value){
  const root=$('osip-content');root.replaceChildren();const grid=make('div',undefined,'oq-grid');
  const models=module('Model intelligence');models.append(make('p','Configuration and model availability are observations. They do not establish inference quality or certification.'));
  for(const entry of value.models?.entries||[])detail(models,entry.model||entry.id,entry.enabled?'CONFIGURED':'DISABLED',`${entry.location||'unknown locality'} · ${entry.tier||'unclassified tier'} · ${entry.qualification_status||'qualification not supplied'}`);
  if(!value.models?.entries?.length)models.append(make('p','The configured provider catalog is unavailable.'));
  const runtime=value.models?.runtime;detail(models,'Local runtime',runtime?.status||'UNAVAILABLE',runtime?.ready?'Required configured models are present.':'One or more required model roles are unavailable.');
  const memory=module('Memory & continuity');for(const [key,record] of Object.entries(value.memory||{}))detail(memory,key.replaceAll('_',' '),record.status||'UNAVAILABLE',record.disclosure||'Read-only observation of the existing server store.');
  const memoryLink=make('button','Open governed knowledge');memoryLink.type='button';memoryLink.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('orqevia-open-view',{detail:{name:'intelligence'}})));memory.append(memoryLink);
  const agents=module('Canonical agent directory');agents.append(make('p','Registration is distinct from activity. Queue observations show recorded execution state and its timestamp, rather than an invented heartbeat.'));
  for(const agent of value.agents||[])detail(agents,`${agent.agent_id} · ${agent.name}`,agent.last_observed_state||'NOT OBSERVED',agent.observed_at?`Recorded ${agent.observed_at}`:'No recorded queue activity.');
  const governance=module('Authority & verification');detail(governance,'Approval store',value.governance?.approval_store?.status||'UNAVAILABLE');detail(governance,'Execution path','EXISTING OWNED OBJECTIVES');detail(governance,"GOD’S EYE",'READ ONLY');governance.append(make('p','A model selection, plan or approval record grants no new execution authority. Results retain the existing task and evidence controls.'));
  grid.append(models,memory,agents,governance);root.append(grid);state('osip-state',`Observed ${value.observed_at}. Correlation ${value.correlation_id}. Certification remains scoped to separate acceptance evidence.`);
}
async function load(){
  if(!ownViews.has(active))return;const panel=active==='plane'?'osip':'approval';
  pending?.abort();const controller=new AbortController();pending=controller;const generation=epoch,view=active;
  $(panel+'-content').replaceChildren();
  if(!session){state(panel+'-state','Restore your trusted connection to load this private view.');return;}
  if(session.role!=='OWNER'){state(panel+'-state','The bound owner account is required for this view.',true);return;}
  if(!navigator.onLine){state(panel+'-state','Offline. Reconnect and refresh to obtain a current observation.');return;}
  state(panel+'-state','Loading an authorized service observation…');
  const timeout=setTimeout(()=>controller.abort(),12000);
  try{const value=await api(view==='plane'?'status':'approvals',{signal:controller.signal});if(generation!==epoch||view!==active||controller.signal.aborted)return;if(view==='plane')drawPlane(value);else drawApprovals(value,generation);}
  catch(error){if(generation===epoch&&view===active)state(panel+'-state',controller.signal.aborted?'The service timed out. Refresh to retry.':error.message,true);}
  finally{clearTimeout(timeout);if(pending===controller)pending=null;}
}
function drawApprovals(value,generation){
  const root=$('approval-content');root.replaceChildren();const section=module('Existing Stable Spine decisions');
  section.append(make('p','Review a pending action and record a decision. The originating executor must re-evaluate its original action; recording a decision does not execute it.'));
  if(!value.approvals?.length)section.append(make('p','The approval service returned no records.'));
  for(const record of value.approvals||[]){
    const row=make('article',undefined,'oq-approval');row.append(make('h3',record.action_type),make('small',`Status: ${record.status}`),make('small',`Correlation: ${record.correlation_id}`),make('small',`Reference: ${record.idempotency_key}`));
    if(record.review){const details=make('pre',JSON.stringify(record.review,null,2));row.append(details,make('small',`Original action SHA-256: ${record.envelope_sha256}`));}
    if(record.status==='PENDING'&&record.reviewable){
      const note=make('textarea');note.maxLength=1000;note.placeholder='Record the reason for your decision';note.setAttribute('aria-label',`Decision note for ${record.idempotency_key}`);row.append(note);const actions=make('div',undefined,'oq-approval-actions');
      for(const [decision,label] of [['approve','Approve action'],['reject','Reject action']]){const button=make('button',label);button.type='button';button.addEventListener('click',async()=>{
        if(!note.value.trim()){note.focus();state('approval-state','A decision note is required.',true);return;}
        actions.querySelectorAll('button').forEach(b=>b.disabled=true);
        try{const result=await api('approvals/'+encodeURIComponent(record.idempotency_key),{body:{decision,note:note.value.trim(),envelope_sha256:record.envelope_sha256},signal:AbortSignal.timeout(12000)});if(generation!==epoch||active!=='approvals')return;await load();state('approval-state',`${result.status}. ${result.disclosure}`);}
        catch(error){if(generation===epoch)state('approval-state',error.message,true);}
        finally{actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
      });actions.append(button);}row.append(actions);
    }section.append(row);
  }root.append(section);state('approval-state','Loaded from the existing approval service. No action was executed.');
}
function showView(name){active=name;pending?.abort();$('osip-view')?.classList.toggle('hidden',name!=='plane');$('approval-view')?.classList.toggle('hidden',name!=='approvals');if(ownViews.has(name))void load();}
for(const id of ['osip-refresh','approval-refresh'])$(id)?.addEventListener('click',()=>void load());
$('osip-plan-form')?.addEventListener('submit',async event=>{
  event.preventDefault();const objective=$('osip-objective').value.trim();if(!objective||!session)return;const generation=epoch,button=$('osip-plan-submit');button.disabled=true;$('osip-plan-result').replaceChildren();state('osip-plan-state','Preparing a bounded plan through the existing capability registry…');
  try{const value=await api('plans',{body:{objective},signal:AbortSignal.timeout(12000)});if(generation!==epoch)return;const result=$('osip-plan-result'),list=make('ol');for(const step of value.steps||[])list.append(make('li',step.purpose+(step.capabilities?.length?' Capabilities: '+step.capabilities.join(', '):'')));result.append(list,make('p',value.disclosure));const use=make('button','Use as objective','oq-primary');use.type='button';use.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('orqevia-objective-draft',{detail:{text:objective}})));result.append(use);state('osip-plan-state',`Plan prepared. No model invocation or execution was performed. Correlation ${value.correlation_id}.`);}
  catch(error){if(generation===epoch)state('osip-plan-state',error.message,true);}
  finally{button.disabled=false;}
});
const more=$('mobile-more-dialog');$('mobile-more-open')?.addEventListener('click',()=>more.showModal());$('mobile-more-close')?.addEventListener('click',()=>more.close());more?.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>more.close()));
window.addEventListener('orqevia-view',event=>showView(event.detail.name));
window.addEventListener('orqevia-session',event=>{
  const next=event.detail;if(next?.clientId!==session?.clientId||next?.role!==session?.role||next?.generation!==session?.generation){invalidate();$('osip-plan-result')?.replaceChildren();if($('osip-objective'))$('osip-objective').value='';}
  session=next;void load();
});
window.addEventListener('offline',()=>{invalidate();if(ownViews.has(active))state(active==='plane'?'osip-state':'approval-state','Offline. Private observations were cleared. Reconnect to refresh.');});
window.addEventListener('online',()=>void load());
document.addEventListener('visibilitychange',()=>{if(document.hidden)pending?.abort();else void load();});
setInterval(()=>{if(!document.hidden&&ownViews.has(active))void load();},60000);
showView(active);window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
