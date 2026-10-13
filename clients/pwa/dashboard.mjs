import {InterfaceAPI, safeID} from './core.mjs';

export function telemetryFreshness(value, now=Date.now()) {
  if(value?.schema_version!=='orqevia.telemetry.v1'||typeof value.source?.instance!=='string'||typeof value.source?.revision!=='string'||!Array.isArray(value.metrics)||!Array.isArray(value.agents)||value.agents.length!==21||new Set(value.agents.map(a=>a?.agent_id)).size!==21||value.agents.some(a=>!safeID(a?.agent_id))) return 'UNKNOWN';
  const timestamp=Date.parse(value.observed_at), ttl=value.freshness_seconds;
  if(!Number.isFinite(timestamp)||!Number.isFinite(ttl)||ttl<=0||ttl>60||timestamp>now+5000) return 'UNKNOWN';
  return now-timestamp>ttl*1000?'STALE':'OBSERVED';
}

export function coachingStatus(value, now=Date.now()) {
  if(value===null||typeof value!=='object'||!Array.isArray(value.agents)) return 'UNKNOWN';
  if(value.status==='UNAVAILABLE') return 'UNAVAILABLE';
  if(!['OBSERVED','STALE'].includes(value.status)) return 'UNKNOWN';
  const timestamp=Date.parse(value.last_event_at||'');
  if(!Number.isFinite(timestamp)) return 'UNKNOWN';
  if(timestamp>now+5000) return 'UNKNOWN';
  return value.status==='STALE'||now-timestamp>60000?'STALE':'OBSERVED';
}

export function coachingPhaseCounts(agents) {
  if(!Array.isArray(agents)||agents.length!==21||new Set(agents.map(a=>a?.agent_id)).size!==21||agents.some(a=>!safeID(a?.agent_id))) return null;
  return ['baseline','practice','acceptance'].map(phase=>{
    const grades=agents.map(a=>a[phase+'_pass']);
    const passed=grades.filter(g=>g===true).length,failed=grades.filter(g=>g===false).length;
    return {phase,assessed:passed+failed,passed,failed,unassessed:21-passed-failed};
  });
}

export function coachingDetailLines(agent) {
  const score=value=>value===0||value===100?String(value):'UNKNOWN';
  const date=value=>typeof value==='string'&&Number.isFinite(Date.parse(value))?value:'UNKNOWN';
  const lines=[`Synthetic case score: baseline ${score(agent?.baseline_score)} / latest ${score(agent?.latest_score)} (0 or 100; not role competence)`,
    'Full role acceptance: NOT ESTABLISHED',`Last activity: ${date(agent?.last_activity_at)}`];
  if(typeof agent?.blocker==='string') lines.push(`Blocker: ${agent.blocker.slice(0,96)}`);
  if(Array.isArray(agent?.failures)) for(const failure of agent.failures.slice(0,6)) {
    const errors=Array.isArray(failure?.errors)?failure.errors.filter(x=>typeof x==='string'&&/^[a-zA-Z0-9_.:-]{1,96}$/.test(x)).slice(0,12):[];
    lines.push(`Retained failure: ${failure?.phase||'UNKNOWN'} / ${date(failure?.assessed_at)} / ${errors.join(', ')||'assessment failed'}`);
  }
  if(Array.isArray(agent?.coaching_actions)) lines.push(`Recorded coaching actions: ${agent.coaching_actions.length}`);
  if(typeof agent?.coaching_method==='string') lines.push(`Method: ${agent.coaching_method.slice(0,1000)}`);
  if(Array.isArray(agent?.reassessment_results)) for(const result of agent.reassessment_results.slice(0,2))
    lines.push(`Synthetic reassessment: ${result?.outcome==='PASS'?'PASS':result?.outcome==='FAIL'?'FAIL':'UNKNOWN'} / ${date(result?.assessed_at)}`);
  return lines;
}

export function normalFollowupLines(agent) {
  const mark=value=>value===true?'PASS':value===false?'FAIL':'PENDING';
  const lines=[`Normal-role baseline: ${mark(agent?.baseline_pass)}; reassessment: ${mark(agent?.latest_pass)}. Full role acceptance: NOT ESTABLISHED; independent Azure L7: NOT ESTABLISHED.`];
  if(Array.isArray(agent?.baseline_errors)&&agent.baseline_errors.length)lines.push(`Original normal-role failures: ${agent.baseline_errors.slice(0,32).join(', ').slice(0,1500)}`);
  if(Array.isArray(agent?.reassessment_results)){const latest=agent.reassessment_results.at(-1);if(latest)lines.push(`Latest reassessment: ${latest.outcome}; failures: ${(latest.errors||[]).slice(0,32).join(', ')||'none'}; execution: ${(latest.execution_error||[]).join(', ')||'completed'}`);}
  if(Array.isArray(agent?.coaching_actions))lines.push(`Coaching actions: ${agent.coaching_actions.slice(0,8).join(', ').slice(0,1500)}`);
  if(Array.isArray(agent?.blocker)&&agent.blocker.length)lines.push(`Blocker: ${agent.blocker.join(', ').slice(0,1500)}`);
  if(agent?.last_activity_at)lines.push(`Normal-role last activity: ${String(agent.last_activity_at).slice(0,64)}`);
  return lines;
}

if(typeof document!=='undefined') {
  const api=new InterfaceAPI(), $=id=>document.getElementById(id);
  let latest=null, pending=null, events=new Map(), sessionEpoch=0, authenticated=false, clientId=null, generation=null;
  function invalidatePending(){sessionEpoch++;pending?.abort();pending=null;}
  const text=(id,value)=>{if($(id))$(id).textContent=value;};
  function view(name){
    $('dashboard').classList.toggle('hidden',name!=='home');
    $('task-workspace').classList.toggle('hidden',!['objective','evidence','data & tools'].includes(name));
    $('capability-view').classList.toggle('hidden',['home','objective'].includes(name));
    $('coaching-view').classList.toggle('hidden',name!=='coaching');
    text('capability-title',name==='objective'?'New objective':name[0].toUpperCase()+name.slice(1));
    const descriptions={agents:'Registry membership is verified separately from readiness. Individual live execution and heartbeat evidence is unavailable.',evidence:'Open your owned task to retrieve its original result and integrity-checked artifacts. Other accounts’ tasks are not exposed.','data & tools':'Upload TXT, Markdown or JSON through the existing authenticated objective interface. Host CPU, memory, disk and network collectors are not configured.',settings:'Manage the existing server session and permissions through Your connection.',intelligence:'Use the existing objective interface for bounded analysis. Every returned result retains its own execution record.',ideas:'Submit an objective through the existing orchestrator. Results and evidence remain attached to the original task.',architecture:'Request architectural analysis through the existing authorized objective interface.',build:'A dedicated build runner is unavailable. Advisory objectives are available; a response is not proof that code was built.',test:'A dedicated test runner is unavailable. Source tests and genuine execution receipts are classified separately.',deploy:'Production deployment remains an owner-authorized operation; this interface has no deployment adapter.',present:'A presentation execution adapter is unavailable. Existing objectives can request a draft; no completed deck is invented.'};
    text('capability-description',descriptions[name]||'Use the existing owned objective and task interfaces.');
    $('agent-provenance-list').classList.toggle('hidden',name!=='agents');
    for(const item of document.querySelectorAll('[data-view]'))item.setAttribute('aria-current',String(item.dataset.view===name));
    if(name==='settings')$('account-button').click();
    if(name==='objective')$('objective').focus();
    window.scrollTo({top:0,behavior:'smooth'});
  }
  for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>view(button.dataset.view));
  for(const button of document.querySelectorAll('[data-new-objective]'))button.addEventListener('click',()=>view('objective'));
  for(const button of document.querySelectorAll('[data-open-task]'))button.addEventListener('click',()=>{view('evidence');$('resume-button').click();});
  for(const button of document.querySelectorAll('[data-profile]'))button.addEventListener('click',()=>$('account-button').click());
  function renderCoaching(coaching){
    const list=$('coaching-roles'), summary=$('coaching-summary');
    const empty=(msg)=>{if(list){list.replaceChildren();const d=document.createElement('div');d.className='empty-record';d.textContent=msg;list.append(d);}};
    if(summary)summary.replaceChildren();
    if(coaching===null||typeof coaching!=='object'){text('coaching-state','UNAVAILABLE');text('coaching-source','Older Interface endpoint: no coaching observation field.');empty('Coaching telemetry is unavailable in this Interface version.');return;}
    const state=coachingStatus(coaching);text('coaching-state',state);
    if(!['OBSERVED','STALE'].includes(state)){text('coaching-source','No validated coaching observation.');empty('Coaching observation unavailable or malformed.');return;}
    const src=typeof coaching.cohort_source_revision==='string'?('source '+coaching.cohort_source_revision.slice(0,7)):'source UNKNOWN';
    const event=coaching.last_event_at?new Date(coaching.last_event_at).toLocaleString():'UNKNOWN';
    const tick=Date.parse(coaching.controller?.last_tick_at||'');
    const controllerAvailability=Number.isFinite(tick)&&tick<=Date.now()+5000?(['OBSERVED','STALE','UNKNOWN'].includes(coaching.controller?.availability)?coaching.controller.availability:'UNKNOWN'):'UNKNOWN';
    const controller=coaching.controller?.last_state||'UNKNOWN';
    text('coaching-source',`cohort ${coaching.cohort_id||'UNKNOWN'} - ${src} - last event ${event} - controller ${controllerAvailability} / ${controller} - last tick ${Number.isFinite(tick)?new Date(tick).toLocaleString():'UNKNOWN'} - synthetic role assessment only; full role acceptance is separate`);
    const counts=coachingPhaseCounts(coaching.agents);
    if(summary&&counts){for(const item of counts){const c=document.createElement('div');c.className='coaching-stat';const s=document.createElement('strong');s.textContent=`${item.assessed} / 21 assessed`;const l=document.createElement('small');l.textContent=`${item.phase}: ${item.passed} pass, ${item.failed} fail, ${item.unassessed} unassessed`;c.append(s,l);summary.append(c);}}
    const normal=coaching.normal_followup;
    if(summary&&normal?.status==='OBSERVED'&&normal.normal_denominator===21&&normal.agents?.length===21){const c=document.createElement('div');c.className='coaching-stat';const s=document.createElement('strong');s.textContent=`Normal-role reassessment: ${normal.normal_pass_count} / 21 pass`;const l=document.createElement('small');l.textContent=`${normal.reassessed_count} / 21 assessed; ${normal.normal_fail_count} fail. Full end-to-end acceptance: 0 / 21 established. Azure L7: not established.`;c.append(s,l);summary.append(c);}
    if(!counts){text('coaching-state','UNKNOWN');empty('Complete per-role observation unavailable; partial or malformed registry.');return;}
    if(!Array.isArray(coaching.agents)||coaching.agents.length===0){empty('No per-role observation (cohort unavailable or partial registry).');return;}
    if(list){list.replaceChildren();for(const agent of coaching.agents){if(!safeID(agent?.agent_id))continue;const row=document.createElement('div');row.className='coaching-role';const head=document.createElement('div');head.className='coaching-role-head';const name=document.createElement('strong');name.textContent=`${agent.agent_id.toUpperCase()} - ${typeof agent.role==='string'?agent.role.slice(0,128):'Role UNKNOWN'} - ${agent.phase||'UNKNOWN'} - ${agent.state||'UNKNOWN'}`;const marks=document.createElement('span');marks.className='coaching-marks';const m=(k)=>agent[k]===true?'P':agent[k]===false?'F':'-';marks.textContent=`Baseline ${m('baseline_pass')} / Practice ${m('practice_pass')} / Synthetic acceptance ${m('acceptance_pass')}`;head.append(name,marks);const t=document.createElement('small');const transition=Date.parse(agent.last_transition_at||'');t.textContent=Number.isFinite(transition)&&transition<=Date.now()+5000?`Last transition ${new Date(transition).toLocaleString()}`:'Last transition UNKNOWN';row.append(head,t);for(const line of coachingDetailLines(agent)){const detail=document.createElement('small');detail.textContent=line;row.append(detail);}list.append(row);}}
    if(list&&normal?.status==='OBSERVED'&&normal.agents?.length===21){for(const agent of normal.agents){if(!safeID(agent?.agent_id))continue;const row=document.createElement('div');row.className='coaching-role';const name=document.createElement('strong');name.textContent=`${agent.agent_id.toUpperCase()} - ${agent.role||'Role UNKNOWN'} - Normal-role follow-up`;row.append(name);for(const line of normalFollowupLines(agent)){const detail=document.createElement('small');detail.textContent=line;row.append(detail);}list.append(row);}}
  }
  function unavailable(state){latest=null;$('coaching-roles').replaceChildren();$('coaching-summary').replaceChildren();text('coaching-state',state);text('coaching-source','No current authenticated coaching observation');$('agent-provenance-list').replaceChildren();text('telemetry-state',state);text('mobile-system-state',state==='UNAUTHORIZED'?'Not connected':state);text('registered-count','—');text('active-count','—');text('mobile-ready','— / 21');text('telemetry-source','No current authenticated measurement');}
  function render(){
    const state=telemetryFreshness(latest);
    if(state!=='OBSERVED'){unavailable(state);return;}
    renderCoaching(latest?.coaching??null);
    text('telemetry-state',state);text('mobile-system-state','Observations received');
    for(const [id,name] of [['registered-count','registered_agents'],['active-count','active_job_records']]){
      const metric=latest.metrics.find(m=>m.metric_id===name);
      text(id,metric?.collection_status==='OBSERVED'&&Number.isSafeInteger(metric.value)&&metric.value>=0?String(metric.value):'—');
    }
    text('telemetry-source',`${latest.source.instance} · observed ${new Date(latest.observed_at).toLocaleTimeString()} · host gauges unavailable`);
    const list=$('agent-provenance-list');list.replaceChildren();
    for(const agent of latest.agents){const row=document.createElement('div');row.className='agent-record';const title=document.createElement('strong'),status=document.createElement('span');title.textContent=`${agent.agent_id.toUpperCase()} · ${agent.name}`;status.textContent=`${agent.registration} · availability ${agent.availability}`;row.append(title,status);list.append(row);}
  }
  async function poll(){
    if(!authenticated||document.hidden||!navigator.onLine||pending)return;
    const controller=new AbortController(), epoch=sessionEpoch;pending=controller;
    try{const value=await api.request('/interface/v1/telemetry',{signal:controller.signal,timeout:10000});if(epoch!==sessionEpoch||controller.signal.aborted||!authenticated)return;if(value?.audience?.client_id!==clientId){unavailable('UNKNOWN');return;}latest=value;render();}
    catch(error){if(epoch!==sessionEpoch||controller.signal.aborted||!authenticated)return;unavailable([401,403].includes(error.status)?'UNAUTHORIZED':!navigator.onLine?'OFFLINE':'UNAVAILABLE');}
    finally{if(pending===controller)pending=null;}
  }
  window.addEventListener('orqevia-task',event=>{
    const task=event.detail;if(!authenticated||task?.clientId!==clientId||task?.generation!==generation||!safeID(task?.id))return;
    const rows=$('dashboard-task-rows');rows.replaceChildren();const row=document.createElement('tr');
    for(const value of [task.agents.join(', ')||'UNKNOWN',task.id,task.state,'UNKNOWN',task.updated||'UNKNOWN']){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}rows.append(row);
    const key=`${task.id}:${task.revision}:${task.state}`;if(events.has(key))return;
    events.set(key,task);if(events.size>50)events.delete(events.keys().next().value);
    const activity=$('dashboard-activity-rows');activity.replaceChildren();
    for(const record of [...events.values()].reverse().slice(0,8)){const entry=document.createElement('div');entry.className='agent-record';entry.textContent=`${record.id} · ${record.state} · ${record.updated||'source timestamp UNKNOWN'}`;activity.append(entry);}
    text('activity-state','OWNED TASK OBSERVATIONS');
  });
  window.addEventListener('orqevia-session',event=>{invalidatePending();const next=event.detail;if(authenticated&&next?.clientId===clientId&&next?.generation===generation){void poll();return;}authenticated=Boolean(next?.clientId);clientId=next?.clientId||null;generation=next?.generation??null;events.clear();latest=null;unavailable('UNAUTHORIZED');text('dashboard-activity-rows','No owned task event stream selected.');text('activity-state','UNAVAILABLE');const rows=$('dashboard-task-rows');rows.replaceChildren();const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=5;cell.textContent='Open an owned task to inspect its genuine execution record.';row.append(cell);rows.append(row);if(next)void poll();});
  function suspend(){invalidatePending();unavailable('OFFLINE');}
  window.addEventListener('offline',suspend);window.addEventListener('online',()=>void poll());
  document.addEventListener('visibilitychange',()=>{if(document.hidden){invalidatePending();}else void poll();});
  const clock=()=>text('dashboard-clock',new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'medium'}).format(new Date()));
  clock();setInterval(clock,1000);setInterval(()=>void poll(),30000);setInterval(()=>{if(latest)render();},5000);void poll();
  window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
}
