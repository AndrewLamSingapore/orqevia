// Governed operations use the same authenticated backend as the workspace.
// Agent text is rendered as text, never interpreted as markup or authority.
const $=id=>document.getElementById(id);
const element=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let session=null,active=new URL(location.href).searchParams.get('view')==='operations',epoch=0,pending=null,current=null;
const kinds=['agents','fabrics','capabilities','dependencies','policies','models','health_snapshots','execution_records','evidence','knowledge_claims','knowledge_contributions','knowledge_relationships','knowledge_challenges','puzzles','puzzle_requirements','gaps','remediation_plans','remediation_executions','remediation_verifications','lessons_learned'];
function status(message,error=false){$('operations-state').textContent=message;$('operations-state').dataset.state=error?'error':'ready';}
function clear(){epoch++;pending?.abort();pending=null;current=null;for(const id of ['operations-metrics','operations-records','operations-detail'])$(id)?.replaceChildren();}
async function api(path,body,signal){
 const response=await fetch('/interface/v1/collective/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal,
  headers:{'Content-Type':'application/json','X-ORQEVIA-PWA':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 const messages={401:'Your session expired. Restore your connection.',403:'This operation requires the bound owner or a trusted independent verifier.',404:'The requested record is unavailable in this account.',409:'The record changed or its prerequisites are not satisfied. Refresh before retrying.',422:'The request does not satisfy the evidence or workflow requirements.',429:'The bounded request budget is reached. Wait before trying again.',503:'The registry is unavailable. Existing task execution keeps its own controls.'};
 if(!response.ok)throw new Error(messages[response.status]||`The service could not complete this request (${response.status}).`);
 const value=await response.json();if(value?.protocol!=='orqevia.collective.v1')throw new Error('Unsupported operations-board contract.');return value.data;
}
function addMetric(parent,label,value,note){const n=element('div',undefined,'oq-module operations-metric');n.append(element('strong',String(value??'UNAVAILABLE')),element('span',label));if(note)n.append(element('small',note));parent.append(n);}
function drawMetrics(value){
 const m=value.metrics||{},root=$('operations-metrics');root.replaceChildren();
 addMetric(root,'Registered agents',`${m.agents?.registered??0} / ${m.agents?.expected??21}`,'Registration and qualification are separate.');
 addMetric(root,'Verified contribution paths',`${m.agents?.verified_contributing_agents??0} / 21`,'Bound to actual completed queue executions.');
 addMetric(root,'Questioning paths tested',`${m.agents?.questioning_tested_agents??0} / 21`);
 addMetric(root,'Gap participation tested',`${m.agents?.gap_workflow_tested_agents??0} / 21`);
 addMetric(root,'Fabrics integrated',`${m.fabrics?.integrated??0} / ${m.fabrics?.discovered??0}`,'Health and inference qualification remain distinct.');
 addMetric(root,'Verified facts',m.knowledge?.verified_facts??0);
 addMetric(root,'Active / completed puzzles',`${m.puzzles?.active??0} / ${m.puzzles?.completed??0}`);
 addMetric(root,'Open / resolved challenges',`${m.challenges?.open??0} / ${m.challenges?.resolved??0}`);
 addMetric(root,'Open / verified closed gaps',`${m.gaps?.open??0} / ${m.gaps?.verified_closed??0}`);
 addMetric(root,'Awaiting approval',m.gaps?.awaiting_approval??0);
 addMetric(root,'Unresolved contradictions',m.knowledge?.unresolved_contradictions??0);
 addMetric(root,'Registry integrity',m.registry_health||'UNAVAILABLE',m.resources?.sqlite_bytes!==undefined?`${(m.resources.sqlite_bytes/1048576).toFixed(2)} MB SQLite · ${m.resources.query_elapsed_ms} ms observation`:undefined);
 $('operations-freshness').textContent=`Observed ${value.observed_at||m.observed_at||'time unavailable'}. Mandatory AWS dependency: ${m.resources?.mandatory_aws_cost_usd===0?'US$0':'unavailable'}. Latest knowledge update: ${m.knowledge?.newest_updated_at||'no claims recorded'}.`;
}
function title(record){return record.data?.title||record.data?.name||record.data?.canonical_id||record.data?.question||record.id;}
function summary(record){return record.data?.statement||record.data?.description||record.data?.objective||record.data?.reason||record.data?.purpose||'';}
function chooseRecord(record){
 const root=$('operations-detail');root.replaceChildren();root.append(element('h2',title(record)),element('p',`${record.kind} · ${record.state} · version ${record.version}`));
 const detail=element('pre',JSON.stringify(record,null,2));root.append(detail);
 if(record.kind==='agents'){
  const button=element('button','Ask this agent to investigate its registry record');button.type='button';button.addEventListener('click',()=>mutate('investigations',{agent_id:record.data.canonical_id,target_id:record.id,idempotency_key:'ops-question:'+crypto.randomUUID()}));root.append(button);
 }
 if(record.kind==='gaps'&&record.state==='PLANNED'){
  const button=element('button','Run prepared notebook-index repair');button.type='button';button.addEventListener('click',()=>mutate('repairs/notebook-index',{gap_id:record.id,expected_version:record.version}));root.append(button,element('p','The service checks the fixed adapter, scope and authorization before execution. Closure requires separate outcome, regression and security observations.'));
 }
 const question=element('button','Question this record');question.type='button';question.addEventListener('click',()=>{$('operations-challenge-target').value=record.id;$('operations-challenge-question').focus();$('operations-challenge-form').scrollIntoView({block:'center'});});root.append(question);
 root.scrollIntoView({block:'nearest'});
}
function drawRecords(records){
 const root=$('operations-records');root.replaceChildren();if(!records.length){root.append(element('p','No matching records were returned.'));return;}
 for(const record of records){const row=element('article',undefined,'operations-record'),button=element('button',title(record));button.type='button';button.addEventListener('click',()=>chooseRecord(record));row.append(button,element('small',`${record.kind} · ${record.state} · ${record.updated_at||record.created_at}`));const text=summary(record);if(text)row.append(element('p',text.slice(0,360)));row.append(element('small',record.id));root.append(row);}
}
async function lookup(){
 if(!session||!navigator.onLine)return;const generation=epoch;
 const params=new URLSearchParams({kind:$('operations-kind').value,limit:'50'});const id=$('operations-lookup-id').value.trim();if(id)params.set('id',id);
 try{status('Reading scoped registry records…');const value=await api('lookup?'+params,undefined,AbortSignal.timeout(12000));if(generation!==epoch||!active)return;drawRecords(value.items||[value]);status(`Loaded ${value.total??1} matching records. Lookup grants no execution permission.`);}
 catch(error){if(generation===epoch)status(error.message,true);}
}
async function load(){
 if(!active)return;pending?.abort();const controller=new AbortController();pending=controller;const generation=epoch;
 if(!session||session.role!=='OWNER'){clear();status('Restore the bound owner connection to view the Operations Board.');return;}
 if(!navigator.onLine){clear();status('Offline. Private records were cleared. Reconnect to load current evidence.');return;}
 status('Loading the governed Operations Board…');const timeout=setTimeout(()=>controller.abort(),20000);
 try{const value=await api('status',undefined,controller.signal);if(generation!==epoch||!active)return;current=value;drawMetrics(value);drawRecords(value.gaps?.items||[]);status(`Observed ${value.observed_at||value.metrics?.observed_at}. Claims, execution observations and verified facts remain distinct.`);}
 catch(error){if(generation===epoch)status(controller.signal.aborted?'The registry timed out. Refresh to retry.':error.message,true);}
 finally{clearTimeout(timeout);if(pending===controller)pending=null;}
}
async function mutate(path,body){
 if(!session||!navigator.onLine||current?.stale===true)return;const generation=epoch;const buttons=$('operations-view').querySelectorAll('button');buttons.forEach(b=>b.disabled=true);status('Submitting an authorized, bounded operation…');
 try{const value=await api(path,body,AbortSignal.timeout(35000));if(generation!==epoch)return;await load();if(value.record)chooseRecord(value.record);status(value.job_id?`Investigation queued as ${value.job_id}. Its eventual result must still be checked.`:'Operation recorded. Refresh or inspect the record for its actual state and evidence.');}
 catch(error){if(generation===epoch)status(error.message,true);}
 finally{buttons.forEach(b=>b.disabled=false);}
}
const evidence=value=>value.split(/[\s,]+/).filter(Boolean);
const command=(operation,payload)=>mutate('commands',{api_version:'1.0',operation,payload,idempotency_key:'operations:'+crypto.randomUUID()});
$('operations-refresh')?.addEventListener('click',()=>void load());
$('operations-reconcile')?.addEventListener('click',()=>void mutate('reconcile',{}));
$('operations-lookup-form')?.addEventListener('submit',event=>{event.preventDefault();void lookup();});
$('operations-observation-form')?.addEventListener('submit',event=>{event.preventDefault();void command('evidence.record',{kind:'OBSERVATION',environment:'OWNER_OBSERVATION',source:$('operations-source').value.trim(),content:{observation:$('operations-observation').value.trim()}});});
$('operations-claim-form')?.addEventListener('submit',event=>{event.preventDefault();void command('claim.contribute',{title:$('operations-claim-title').value.trim(),statement:$('operations-claim-statement').value.trim(),classification:'HYPOTHESIS',evidence_ids:evidence($('operations-claim-evidence').value)});});
$('operations-challenge-form')?.addEventListener('submit',event=>{event.preventDefault();void command('challenge.open',{target_id:$('operations-challenge-target').value.trim(),question:$('operations-challenge-question').value.trim(),reason:$('operations-challenge-reason').value.trim(),severity:'MEDIUM',reviewer_agent_id:'a26',evidence_ids:evidence($('operations-challenge-evidence').value),actionable:$('operations-challenge-actionable').checked});});
$('operations-puzzle-form')?.addEventListener('submit',event=>{event.preventDefault();const lines=$('operations-puzzle-pieces').value.split('\n').map(x=>x.trim()).filter(Boolean);void command('puzzle.create',{title:$('operations-puzzle-title').value.trim(),objective:$('operations-puzzle-objective').value.trim(),requirements:lines.map((description,index)=>({key:'piece-'+(index+1),description,evidence_criteria:'Source-attributed contribution and independent validation of the exact assembled records.'})),assigned_agent_ids:evidence($('operations-puzzle-agents').value),completion_condition:$('operations-puzzle-condition').value.trim(),evidence_ids:evidence($('operations-puzzle-evidence').value)});});
for(const kind of kinds){const option=element('option',kind.replaceAll('_',' '));option.value=kind;$('operations-kind')?.append(option);}
if($('operations-kind'))$('operations-kind').value='gaps';
function show(name){active=name==='operations';$('operations-view')?.classList.toggle('hidden',!active);if(active)void load();else pending?.abort();}
window.addEventListener('orqevia-view',event=>show(event.detail.name));
window.addEventListener('orqevia-session',event=>{const next=event.detail;if(next?.clientId!==session?.clientId||next?.role!==session?.role||next?.generation!==session?.generation){clear();$('operations-view')?.querySelectorAll('form').forEach(form=>form.reset());}session=next;if(active)void load();});
window.addEventListener('offline',()=>{clear();if(active)status('Offline. Private records were cleared. Reconnect to refresh.');});
window.addEventListener('online',()=>{if(active)void load();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)pending?.abort();else if(active)void load();});
setInterval(()=>{if(active&&!document.hidden)void load();},60000);
show(active?'operations':'home');window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
