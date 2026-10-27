import {InterfaceAPI, safeID, terminal} from './core.mjs';

export function telemetryFreshness(value, now=Date.now()) {
  if(value?.schema_version!=='orqevia.telemetry.v1'||typeof value.source?.instance!=='string'||typeof value.source?.revision!=='string'||!Array.isArray(value.metrics)||!Array.isArray(value.agents)||value.agents.length>1000||new Set(value.agents.map(a=>a?.agent_id)).size!==value.agents.length||value.agents.some(a=>!safeID(a?.agent_id))) return 'UNKNOWN';
  const timestamp=Date.parse(value.observed_at), ttl=value.freshness_seconds;
  if(!Number.isFinite(timestamp)||!Number.isFinite(ttl)||ttl<=0||ttl>60||timestamp>now+5000) return 'UNKNOWN';
  return now-timestamp>ttl*1000?'STALE':'OBSERVED';
}

export function agentReadinessSummary(value) {
  const observed=value?.observed_agent_count,fresh=value?.fresh_agent_count,ready=value?.ready_agent_count;
  if(![observed,fresh,ready].every(Number.isSafeInteger)||[observed,fresh,ready].some(n=>n<0||n>21)) return null;
  if(fresh>observed||ready>fresh) return null;
  const models=value?.model_runtime;
  if(!models||typeof models!=='object'||typeof models.ready!=='boolean'||!Array.isArray(models.required_models)||!Array.isArray(models.missing_models)) return null;
  return `Observed history ${observed} / 21 · recent activity ${fresh} / 21 · confirmed execution ${ready} / 21`;
}

const healthStates=new Set(['HEALTHY','DEGRADED','CRITICAL','UNKNOWN','NOT_CONFIGURED']);
const healthText=(value,fallback='UNAVAILABLE')=>typeof value==='string'?value.slice(0,512):fallback;
export function sampleFreshness(value,ttl,now=Date.now()) {
  const at=typeof value==='number'?value*1000:typeof value==='string'&&/(Z|[+-]\d\d:\d\d)$/.test(value)?Date.parse(value):NaN;
  if(!Number.isFinite(at)||!Number.isFinite(ttl)||ttl<=0||ttl>1200||at>now+5000)return 'UNKNOWN';
  return now-at>ttl*1000?'STALE':'OBSERVED';
}

// Child observations retain their own clocks; an API poll cannot renew them.
export function healthFacts(value,now=Date.now()) {
  const parent=telemetryFreshness(value,now), host=value?.host;
  const fields={cpu:'cpu_percent',memory:'memory_percent',disk:'disk_percent',network_latency:'network_latency_ms'};
  const metrics=Object.fromEntries(Object.entries(fields).map(([name,field])=>{
    const row=value?.metrics?.find(m=>m?.metric_id===name), meta=host?.field_status?.[field];
    const captured=meta?.captured_at??row?.event_timestamp;
    const freshness=sampleFreshness(captured,host?.max_age_seconds??150,now);
    const valid=parent==='OBSERVED'&&row?.collection_status==='OBSERVED'&&(!meta||meta.collection_status==='OBSERVED')&&freshness==='OBSERVED'&&Number.isFinite(row.value)&&row.value>=0&&(name==='network_latency'||row.value<=100);
    return [name,{value:valid?row.value:null,status:valid?'OBSERVED':parent!=='OBSERVED'?parent:freshness==='STALE'?'STALE':'UNAVAILABLE',
      reason:valid?null:parent!=='OBSERVED'?'APPLICATION_'+parent:freshness==='STALE'?'HOST_SAMPLE_STALE':healthText(meta?.reason??row?.reason??host?.reason,'METRIC_NOT_COLLECTED'),
      capturedAt:captured,source:healthText(meta?.source??row?.source,'SOURCE_UNAVAILABLE'),hostId:healthText(host?.source?.host_id,'HOST_UNAVAILABLE')}];
  }));
  const raw=value?.service_health, ttl=raw?.freshness_seconds;
  const serviceFresh=parent==='OBSERVED'&&raw?.schema_version==='orqevia.service-health.v1'&&sampleFreshness(raw.observed_at,ttl,now)==='OBSERVED';
  const services=serviceFresh&&Array.isArray(raw.services)&&raw.services.length<=32?raw.services.filter(r=>safeID(r?.service_id)).map(row=>{
    const checks=Array.isArray(row.checks)?row.checks.slice(0,16):[];
    const fresh=checks.length>0&&checks.every(c=>['PASS','FAIL'].includes(c?.status)&&c.fresh===true&&sampleFreshness(c.observed_at,ttl,now)==='OBSERVED');
    return {...row,status:fresh&&healthStates.has(row.status)?row.status:['NOT_CONFIGURED','UNKNOWN'].includes(row.status)?row.status:'UNKNOWN',
      reason:fresh?healthText(row.reason,'DECLARED_CHECKS_ONLY'):healthText(row.reason,'SERVICE_CHECK_UNAVAILABLE'),checks};
  }):[];
  const ids=new Set(services.map(row=>row.service_id));
  const expected=['backend','interface','ollama','intelligence','coaching','otel-collector','integration-gateway','cloudflared','cloudflared-dual'];
  const checksFresh=(checks,age)=>Array.isArray(checks)&&checks.length>0&&checks.every(c=>['PASS','FAIL'].includes(c?.status)&&c.fresh===true&&sampleFreshness(c.observed_at,age,now)==='OBSERVED');
  const coverageFresh=serviceFresh&&services.length===9&&ids.size===9&&expected.every(id=>ids.has(id))&&services.every(r=>checksFresh(r.checks,ttl))&&
    raw.collector_checks?.length===3&&checksFresh(raw.collector_checks,ttl)&&raw.canary_checks?.length===16&&checksFresh(raw.canary_checks,raw.coverage?.canary_freshness_seconds);
  let coreStatus=serviceFresh&&healthStates.has(raw.status)?raw.status:parent==='OBSERVED'&&raw?.status==='NOT_CONFIGURED'?'NOT_CONFIGURED':'UNKNOWN';
  if(coreStatus==='HEALTHY'&&!coverageFresh)coreStatus='UNKNOWN';
  const critical=value?.critical_issues;
  const count=Number.isSafeInteger(critical?.critical_count)&&critical.critical_count>=0?critical.critical_count:null;
  const authoritative=coverageFresh&&raw.coverage?.complete===true&&critical?.schema_version==='orqevia.operational-incidents.v1'&&critical.coverage_complete===true&&critical.store_status==='OBSERVED'&&sampleFreshness(critical.observed_at,ttl,now)==='OBSERVED'&&count!==null;
  if(coreStatus==='HEALTHY'&&!authoritative)coreStatus='UNKNOWN';
  const hostFresh=parent==='OBSERVED'&&sampleFreshness(host?.captured_at,host?.max_age_seconds,now)==='OBSERVED';
  const network=hostFresh&&sampleFreshness(host?.network?.captured_at,host?.max_age_seconds,now)==='OBSERVED'?host.network:null;
  return {metrics,host:hostFresh?host:null,network,services,core:{status:coreStatus,observedAt:raw?.observed_at,lastSuccessAt:raw?.last_success_at,
    reason:serviceFresh?healthText(raw.reason):parent!=='OBSERVED'?'APPLICATION_'+parent:healthText(raw?.reason,'SERVICE_MONITORING_NOT_CONFIGURED')},
    critical:{count:authoritative?count:null,knownCount:parent==='OBSERVED'&&Number.isSafeInteger(critical?.known_critical_count)?critical.known_critical_count:null,
      observedAt:critical?.observed_at,lastSuccessAt:critical?.last_success_at,reason:authoritative?'MONITORING_COMPLETE':parent!=='OBSERVED'?'APPLICATION_'+parent:healthText(critical?.reason,'CRITICAL_MONITORING_NOT_CONFIGURED'),
      incidents:parent==='OBSERVED'&&Array.isArray(critical?.incidents)?critical.incidents.slice(0,100):[]}};
}

// One device-independent interpretation of the authenticated telemetry record.
// This does not consult local task history, screen size or model-generated text.
export function operationalFacts(value, now=Date.now()) {
  const status=telemetryFreshness(value,now);
  const unavailable={status,snapshotId:'UNKNOWN',observedAt:null,sourceRevision:'UNKNOWN',registered:null,ready:null,activeJobs:null,
    host:{cpu:null,memory:null,disk:null,network_latency:null},work:{status:'UNAVAILABLE',tasks:[],activity:[]}};
  if(status!=='OBSERVED')return unavailable;
  const metric=name=>value.metrics.find(row=>row?.metric_id===name);
  const health=healthFacts(value,now);
  const measured=(name,integer=false)=>{const row=metric(name);if(['cpu','memory','disk','network_latency'].includes(name)&&(value.host||row?.producer==='host-collector'))return health.metrics[name].value;return row?.collection_status==='OBSERVED'&&Number.isFinite(row.value)&&row.value>=0&&(!integer||Number.isSafeInteger(row.value))?row.value:null;};
  const host=Object.fromEntries(['cpu','memory','disk','network_latency'].map(name=>[name,measured(name)]));
  for(const name of ['cpu','memory','disk'])if(host[name]>100)host[name]=null;
  const raw=value.work_observation, stamp=Date.parse(raw?.observed_at||'');
  let work=unavailable.work;
  if(raw?.schema_version==='orqevia.owned-work.v1'&&raw.status==='UNAUTHORIZED')work={status:'UNAUTHORIZED',tasks:[],activity:[]};
  if(raw?.schema_version==='orqevia.owned-work.v1'&&raw.status==='OBSERVED'&&['OWNER_ACCOUNT','CLIENT'].includes(raw.scope)&&
     Number.isFinite(stamp)&&stamp<=now+5000&&now-stamp<=value.freshness_seconds*1000&&Array.isArray(raw.tasks)&&raw.tasks.length<=50&&Array.isArray(raw.activity)&&raw.activity.length<=50){
    const states=new Set(['RUNNING','WAITING FOR RESOURCE','COMPLETED','COMPLETED_WITH_FAILURES','reconciliation_required']);
    const taskValid=row=>safeID(row?.id)&&states.has(row.state)&&((Number.isSafeInteger(row.revision)&&row.revision>=0)||(row.state==='reconciliation_required'&&row.revision===null))&&Array.isArray(row.agents)&&row.agents.length<=21&&row.agents.every(safeID);
    const activityValid=row=>row?.event==='TASK_STATE_OBSERVATION'&&safeID(row.task_id)&&states.has(row.state)&&Number.isFinite(Date.parse(row.timestamp))&&Date.parse(row.timestamp)<=now+5000;
    if(raw.tasks.every(taskValid)&&new Set(raw.tasks.map(row=>row.id)).size===raw.tasks.length&&raw.activity.every(activityValid))work=raw;
  }
  return {status,snapshotId:typeof value.snapshot_id==='string'?value.snapshot_id:'UNKNOWN',observedAt:value.observed_at,
    sourceRevision:value.source.revision,registered:measured('registered_agents',true),ready:agentReadinessSummary(value)?value.ready_agent_count:null,
    activeJobs:measured('active_job_records',true),host,work};
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

export function normalLatestLines(value, now=Date.now()) {
  if(value?.status!=='OBSERVED'||value.normal_denominator!==21||value.reassessed_count!==21||!Array.isArray(value.agents)||value.agents.length!==21) return null;
  if(new Set(value.agents.map(a=>a?.agent_id)).size!==21||value.agents.some(a=>!safeID(a?.agent_id)||a.execution_bound!==true||typeof a.latest_pass!=='boolean'))return null;
  const passed=value.agents.filter(a=>a.latest_pass).length;
  if(value.normal_pass_count!==passed||value.normal_fail_count!==21-passed||value.full_role_accepted_count!==0||value.certification_awarded!==false)return null;
  const observed=Date.parse(value.reconciled_at),completed=Date.parse(value.last_execution_at);
  if(!Number.isFinite(observed)||!Number.isFinite(completed)||observed>now+5000||completed>now+5000||now-observed>60000)return null;
  if(!/^[a-f0-9]{40}$/.test(value.assessment_runtime_revision)||!/^[a-f0-9]{40}$/.test(value.observer_runtime_revision))return null;
  return [`Latest pinned normal cases: ${passed} / 21 pass`,
    `${21-passed} fail; unchanged oracle replay ${new Date(observed).toLocaleString()}. Last execution ${new Date(completed).toLocaleString()}. Full end-to-end acceptance: 0 / 21 established. Azure L7: not established.`,
    `Assessment runtime ${value.assessment_runtime_revision.slice(0,7)}; observer ${value.observer_runtime_revision.slice(0,7)}. Historical waves and failures remain retained.`];
}

if(typeof document!=='undefined') {
  const api=new InterfaceAPI(), $=id=>document.getElementById(id);
  let latest=null, pending=null, events=new Map(), sessionEpoch=0, authenticated=false, clientId=null, interfaceClientId=null, generation=null;
  const panelIds=new Set(['system-overview','live-system-health','active-tasks','live-activity']);
  function invalidatePending(){sessionEpoch++;pending?.abort();pending=null;}
  const text=(id,value)=>{if($(id))$(id).textContent=value;};
  function view(name,updateRoute=true,panel=null){
    const known=new Set([...document.querySelectorAll('[data-view]')].map(x=>x.dataset.view));known.add('objective');if(!known.has(name))name='home';
    panel=name==='home'&&panelIds.has(panel)?panel:null;
    if(updateRoute){const url=new URL(location.href);url.searchParams.set('view',name);if(panel)url.searchParams.set('panel',panel);else url.searchParams.delete('panel');history.pushState({},'',url);}
    const intelligence=['intelligence','gods-eye'].includes(name);
    $('intelligence-workspace')?.classList.toggle('hidden',!intelligence);
    window.dispatchEvent(new CustomEvent('orqevia-view',{detail:{name}}));
    $('dashboard').classList.toggle('hidden',name!=='home');
    $('task-workspace').classList.toggle('hidden',!['objective','evidence','data & tools'].includes(name));
    $('capability-view').classList.toggle('hidden',['home','objective','intelligence','gods-eye','coaching','plane','approvals','operations'].includes(name));
    $('coaching-view').classList.toggle('hidden',name!=='coaching');
    text('capability-title',name==='objective'?'New objective':name[0].toUpperCase()+name.slice(1));
    const descriptions={agents:'Registry membership, readiness and recorded execution evidence are reported separately from current authenticated observations.',evidence:'Open your owned task to retrieve its original result and integrity-checked artifacts. Other accounts’ tasks are not exposed.','data & tools':'Upload TXT, Markdown or JSON through the existing authenticated objective interface. Live System Health reports each host metric with its current observation status.',settings:'Manage the existing server session and permissions through Your connection.',intelligence:'Use the existing objective interface for bounded analysis. Every returned result retains its own execution record.',ideas:'Submit an objective through the existing orchestrator. Results and evidence remain attached to the original task.',architecture:'Request architectural analysis through the existing authorized objective interface.',build:'Inspect the available build operations and their source-bound execution evidence. A generated response alone is not proof that code was built.',test:'Inspect available checks and their recorded outcomes. Source tests and live execution receipts retain their own evidence scope.',deploy:'Production deployment remains an owner-authorized operation; this interface has no deployment adapter.',present:'A presentation execution adapter is unavailable. Existing objectives can request a draft; no completed deck is invented.'};
    text('capability-description',descriptions[name]||'Use the existing owned objective and task interfaces.');
    $('agent-provenance-list').classList.toggle('hidden',name!=='agents');
    for(const item of document.querySelectorAll('[data-view]'))item.setAttribute('aria-current',String(item.dataset.view===name));
    if(name==='settings')$('account-button').click();
    if(name==='objective')$('objective').focus();
    if(panel)$(panel)?.scrollIntoView?.({block:'start',behavior:'smooth'});else window.scrollTo({top:0,behavior:'smooth'});
  }
  for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>view(button.dataset.view,true,button.dataset.panel));
  for(const button of document.querySelectorAll('[data-new-objective]'))button.addEventListener('click',()=>view('objective'));
  for(const button of document.querySelectorAll('[data-open-task]'))button.addEventListener('click',()=>{view('evidence');$('resume-button').click();});
  window.addEventListener('orqevia-open-view',e=>view(e.detail.name,true,e.detail.panel));
  const route=()=>{const params=new URL(location.href).searchParams;view(params.get('view')||'home',false,params.get('panel'));};
  window.addEventListener('popstate',route);
  route();
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
    const scope=coaching.program_id==='probability-foundations'?'educational probability assessment':'synthetic role assessment';
    text('coaching-source',`cohort ${coaching.cohort_id||'UNKNOWN'} - ${src} - last event ${event} - controller ${controllerAvailability} / ${controller} - last tick ${Number.isFinite(tick)?new Date(tick).toLocaleString():'UNKNOWN'} - ${scope} only; full role acceptance is separate`);
    const counts=coachingPhaseCounts(coaching.agents);
    if(summary&&counts){for(const item of counts){const c=document.createElement('div');c.className='coaching-stat';const s=document.createElement('strong');s.textContent=`${item.assessed} / 21 assessed`;const l=document.createElement('small');l.textContent=`${item.phase}: ${item.passed} pass, ${item.failed} fail, ${item.unassessed} unassessed`;c.append(s,l);summary.append(c);}}
    const normal=coaching.normal_followup;
    if(summary&&normal?.status==='OBSERVED'&&normal.normal_denominator===21&&normal.agents?.length===21){const c=document.createElement('div');c.className='coaching-stat';const s=document.createElement('strong');s.textContent=`Normal-role reassessment: ${normal.normal_pass_count} / 21 pass`;const l=document.createElement('small');l.textContent=`${normal.reassessed_count} / 21 assessed; ${normal.normal_fail_count} fail. Full end-to-end acceptance: 0 / 21 established. Azure L7: not established.`;c.append(s,l);summary.append(c);}
    if(!counts){text('coaching-state','UNKNOWN');empty('Complete per-role observation unavailable; partial or malformed registry.');return;}
    if(!Array.isArray(coaching.agents)||coaching.agents.length===0){empty('No per-role observation (cohort unavailable or partial registry).');return;}
    if(list){list.replaceChildren();for(const agent of coaching.agents){if(!safeID(agent?.agent_id))continue;const row=document.createElement('div');row.className='coaching-role';const head=document.createElement('div');head.className='coaching-role-head';const name=document.createElement('strong');name.textContent=`${agent.agent_id.toUpperCase()} - ${typeof agent.role==='string'?agent.role.slice(0,128):'Role UNKNOWN'} - ${agent.phase||'UNKNOWN'} - ${agent.state||'UNKNOWN'}`;const marks=document.createElement('span');marks.className='coaching-marks';const m=(k)=>agent[k]===true?'P':agent[k]===false?'F':'-';marks.textContent=`Baseline ${m('baseline_pass')} / Practice ${m('practice_pass')} / Synthetic acceptance ${m('acceptance_pass')}`;head.append(name,marks);const t=document.createElement('small');const transition=Date.parse(agent.last_transition_at||'');t.textContent=Number.isFinite(transition)&&transition<=Date.now()+5000?`Last transition ${new Date(transition).toLocaleString()}`:'Last transition UNKNOWN';row.append(head,t);for(const line of coachingDetailLines(agent)){const detail=document.createElement('small');detail.textContent=line;row.append(detail);}list.append(row);}}
    if(list&&normal?.status==='OBSERVED'&&normal.agents?.length===21){for(const agent of normal.agents){if(!safeID(agent?.agent_id))continue;const row=document.createElement('div');row.className='coaching-role';const name=document.createElement('strong');name.textContent=`${agent.agent_id.toUpperCase()} - ${agent.role||'Role UNKNOWN'} - Normal-role follow-up`;row.append(name);for(const line of normalFollowupLines(agent)){const detail=document.createElement('small');detail.textContent=line;row.append(detail);}list.append(row);}}
  }
  function bindSnapshot(facts){
    const root=$('dashboard');
    for(const [key,value] of [['snapshot-id',facts.snapshotId],['observed-at',facts.observedAt||'UNKNOWN'],['source-revision',facts.sourceRevision],['telemetry-state',facts.status],['work-state',facts.work.status]])root?.setAttribute('data-'+key,value);
  }
  function renderWork(facts){
    const work=facts.work,rows=$('dashboard-task-rows'),activity=$('dashboard-activity-rows');rows.replaceChildren();activity.replaceChildren();
    const emptyRow=message=>{const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=5;cell.textContent=message;row.append(cell);rows.append(row);};
    if(work.status!=='OBSERVED'){
      emptyRow('Active task observations '+work.status+'.');text('activity-state',work.status);activity.textContent='Live activity observations '+work.status+'.';return;
    }
    const active=work.tasks.filter(task=>!terminal(task.state));
    if(!active.length)emptyRow(work.has_more?'No active tasks in this page of authorized records. Older records may exist.':'No active tasks in the authorized observation.');
    for(const task of active){
      const row=document.createElement('tr');row.setAttribute('data-task-id',task.id);row.setAttribute('data-task-state',task.state);
      const progress=Number.isFinite(task.progress)&&task.progress>=0&&task.progress<=100?task.progress+'%':'UNKNOWN';
      for(const [label,value] of [['Agent',task.agents.join(', ')||'UNKNOWN'],['Task',task.id],['Status',task.state],['Progress',progress],['Updated',task.updated_at||'UNKNOWN']]){
        const cell=document.createElement('td');cell.setAttribute('data-label',label);
        if(label==='Task'){const button=document.createElement('button');button.type='button';button.textContent=value;button.disabled=task.revision===null;button.setAttribute('aria-label',button.disabled?'Task '+task.id+' requires reconciliation; canonical revision unavailable':'Open task '+task.id);button.addEventListener?.('click',()=>window.dispatchEvent(new CustomEvent('orqevia-open-owned-task',{detail:{id:task.id}})));cell.append(button);}
        else cell.textContent=value;row.append(cell);
      }rows.append(row);
    }
    if(active.length&&work.has_more)emptyRow('Showing recent authorized task records. Older records may exist.');
    text('activity-state',work.activity.length?'OBSERVED TASK STATES':'NO TIMESTAMPED ACTIVITY');
    if(!work.activity.length)activity.textContent='No timestamped task state observation is available.';
    for(const record of work.activity){const entry=document.createElement('div');entry.className='agent-record';entry.setAttribute('data-task-id',record.task_id);entry.setAttribute('data-task-state',record.state);entry.textContent=`${record.task_id} · ${record.state} · ${record.timestamp}`;activity.append(entry);}
  }
  function unavailable(state){
    latest=null;$('coaching-roles').replaceChildren();$('coaching-summary').replaceChildren();text('coaching-state',state);text('coaching-source','No current authenticated coaching observation');$('agent-provenance-list').replaceChildren();text('telemetry-state',state);
    for(const id of ['registered-count','ready-agent-count','active-count','critical-count','core-services-count','metric-cpu','metric-memory','metric-disk','metric-network_latency']){text(id,'UNKNOWN');$(id)?.setAttribute('data-collection-status','UNAVAILABLE');}
    renderHealth(null);
    text('telemetry-source','No current authenticated measurement');
    const facts=operationalFacts(null);facts.status=state;bindSnapshot(facts);renderWork(facts);
  }
  const sampleLabel=value=>{const time=typeof value==='number'?value*1000:Date.parse(value);return Number.isFinite(time)?new Date(time).toISOString():'unavailable';};
  const bytes=value=>Number.isSafeInteger(value)&&value>=0?`${(value/1073741824).toFixed(2)} GiB`:'unavailable';
  function renderHealth(value){
    const health=healthFacts(value);
    const details=$('health-observations');details?.replaceChildren();
    const line=(target,message)=>{if(target){const row=document.createElement('small');row.textContent=message;target.append(row);}};
    for(const name of ['cpu','memory','disk','network_latency']){
      const fact=health.metrics[name], label=$('metric-'+name+'-detail');
      text('metric-'+name+'-detail',`${fact.status}${fact.reason?' · '+fact.reason:''} · sample ${sampleLabel(fact.capturedAt)} · ${fact.hostId} · ${fact.source}`);
      label?.setAttribute('data-freshness',fact.status);
    }
    for(const name of ['memory','disk']){const group=health.host?.[name];line(details,`${name==='disk'?'Disk '+healthText(group?.device,'system drive'):'Memory'}: total ${bytes(group?.total_bytes)} · used ${bytes(group?.used_bytes)} · available ${bytes(group?.available_bytes)}${group?.reason?' · '+group.reason:''}`);}
    const network=health.network;
    if(network&&Array.isArray(network.interfaces))for(const nic of network.interfaces.slice(0,32)){
      const fresh=sampleFreshness(nic.captured_at,health.host.max_age_seconds)==='OBSERVED';
      const count=(key)=>fresh&&nic.field_status?.[key]?.collection_status==='OBSERVED'&&Number.isSafeInteger(nic[key])?String(nic[key]):'unavailable';
      const rate=key=>fresh&&nic.field_status?.[key]?.collection_status==='OBSERVED'&&Number.isFinite(nic[key])?nic[key].toFixed(1)+' B/s':'unavailable';
      line(details,`${healthText(nic.name)} · ${healthText(nic.status)} · RX ${count('received_bytes')} bytes / ${rate('received_bytes_per_second')} · TX ${count('sent_bytes')} bytes / ${rate('sent_bytes_per_second')} · errors RX ${count('received_packet_errors')} / TX ${count('outbound_packet_errors')} · sample ${sampleLabel(nic.captured_at)}`);
    }
    else line(details,`Network interfaces: ${value?.host?.network?.reason||'METRIC_NOT_COLLECTED'}`);
    line(details,'Network gauge measures the default-gateway round trip; it does not establish Internet or service readiness.');
    text('core-services-count',health.core.status);$('core-services-count')?.setAttribute('data-collection-status',health.core.status==='UNKNOWN'?'UNAVAILABLE':'OBSERVED');
    text('core-services-detail',`${health.core.reason} · sample ${sampleLabel(health.core.observedAt)} · last complete success ${sampleLabel(health.core.lastSuccessAt)}`);
    text('critical-count',health.critical.count===null?'UNKNOWN':String(health.critical.count));$('critical-count')?.setAttribute('data-collection-status',health.critical.count===null?'UNAVAILABLE':'OBSERVED');
    text('critical-detail',`${health.critical.reason}${health.critical.knownCount===null?'':' · known critical records '+health.critical.knownCount+' (coverage may be incomplete)'} · sample ${sampleLabel(health.critical.observedAt)} · last complete success ${sampleLabel(health.critical.lastSuccessAt)}`);
    const services=$('service-health-list');services?.replaceChildren();
    for(const service of health.services){line(services,`${service.service_id} · ${service.status} · ${service.reason} · process ${healthText(service.process_state)} · last success ${sampleLabel(service.last_success_at)}`);for(const check of service.checks)line(services,`${check.check_id}: ${check.state||check.status} · ${healthText(check.reason)} · ${healthText(check.scope)} · sample ${sampleLabel(check.observed_at)} · last success ${sampleLabel(check.last_success_at)} · ${healthText(check.source)}`);}
    if(!health.services.length)line(services,health.core.reason);
    const incidents=$('critical-incident-list');incidents?.replaceChildren();
    for(const incident of health.critical.incidents)line(incidents,`${healthText(incident.service_id)} / ${healthText(incident.check_id)} · ${healthText(incident.severity)} · ${healthText(incident.state)} · ${healthText(incident.reason)}`);
  }
  function render(){
    const state=telemetryFreshness(latest);
    if(state!=='OBSERVED'){unavailable(state);return;}
    renderCoaching(latest?.coaching??null);
    const normalLines=normalLatestLines(latest?.normal_latest);
    if(normalLines){const box=document.createElement('div');box.className='coaching-stat';const title=document.createElement('strong');title.textContent=normalLines[0];box.append(title);for(const line of normalLines.slice(1)){const detail=document.createElement('small');detail.textContent=line;box.append(detail);}$('coaching-summary').append(box);}
    const facts=operationalFacts(latest);bindSnapshot(facts);renderWork(facts);
    text('telemetry-state',state);text('ready-agent-count',facts.ready===null?'UNKNOWN':String(facts.ready));$('ready-agent-count')?.setAttribute('data-collection-status',facts.ready===null?'UNAVAILABLE':'OBSERVED');renderHealth(latest);
    const readiness=agentReadinessSummary(latest);
    for(const [id,value] of [['registered-count',facts.registered],['active-count',facts.activeJobs]]){
      text(id,value===null?'UNKNOWN':String(value));
      $(id)?.setAttribute('data-collection-status',value===null?'UNAVAILABLE':'OBSERVED');
    }
    let hostObserved=0;
    for(const [id,name] of [['metric-cpu','cpu'],['metric-memory','memory'],['metric-disk','disk'],['metric-network_latency','network_latency']]){
      const metric=latest.metrics.find(m=>m.metric_id===name);
      const ok=facts.host[name]!==null;
      if(ok)hostObserved++;
      $(id)?.setAttribute('data-collection-status',ok?'OBSERVED':'UNAVAILABLE');
      text(id,ok?(Number.isInteger(metric.value)?String(metric.value):metric.value.toFixed(1))+(name==='network_latency'?' ms':'%'):'UNKNOWN');
    }
    text('telemetry-source',`${latest.source.instance} · ${readiness||'agent readiness UNKNOWN'} · observed ${new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'short'}).format(new Date(latest.observed_at))} · ${hostObserved===4?'host metrics OBSERVED':'host gauges unavailable'}`);
    const list=$('agent-provenance-list');list.replaceChildren();
    for(const agent of latest.agents){const row=document.createElement('div');row.className='agent-record';const title=document.createElement('strong'),status=document.createElement('span');title.textContent=`${agent.agent_id.toUpperCase()} · ${agent.name}`;status.textContent=`${agent.registration} · ${agent.readiness_status||'UNCONFIRMED'} · ${agent.reason_code||'READINESS_NOT_MEASURED'} · last success ${sampleLabel(agent.last_success?.completed_at)} · last failure ${sampleLabel(agent.last_failure?.completed_at)} · heartbeat ${agent.heartbeat_status||'NOT_COLLECTED'} · on-demand execution, role competence not established`;row.append(title,status);list.append(row);}
  }
  let diagnosticFailures=0,nextDiagnosticAttempt=0;
  async function poll(){
    if(!authenticated||document.hidden||!navigator.onLine||pending||Date.now()<nextDiagnosticAttempt)return;
    const controller=new AbortController(), epoch=sessionEpoch;pending=controller;
    try{const value=await api.request('/interface/v1/telemetry',{signal:controller.signal,timeout:20000});if(epoch!==sessionEpoch||controller.signal.aborted||!authenticated)return;if(value?.audience?.client_id!==interfaceClientId){unavailable('UNKNOWN');return;}diagnosticFailures=0;nextDiagnosticAttempt=0;latest=value;render();}
    catch(error){if(epoch!==sessionEpoch||controller.signal.aborted||!authenticated)return;diagnosticFailures=Math.min(3,diagnosticFailures+1);nextDiagnosticAttempt=Date.now()+Math.min(120000,15000*2**diagnosticFailures);unavailable([401,403].includes(error.status)?'UNAUTHORIZED':!navigator.onLine?'OFFLINE':'UNAVAILABLE');}
    finally{if(pending===controller)pending=null;}
  }
  window.addEventListener('orqevia-task',event=>{
    const task=event.detail;if(!authenticated||task?.clientId!==clientId||task?.generation!==generation||!safeID(task?.id))return;
    const key=`${task.id}:${task.revision}:${task.state}`;if(events.has(key))return;
    events.set(key,task);if(events.size>50)events.delete(events.keys().next().value);
    // Local browser notifications never become shared live execution evidence.
    // Read the existing authenticated source again for the canonical state.
    void poll();
  });
  window.addEventListener('orqevia-session',event=>{invalidatePending();diagnosticFailures=0;nextDiagnosticAttempt=0;const next=event.detail;const nextInterfaceClientId=next?.interfaceClientId||next?.clientId||null;if(authenticated&&next?.clientId===clientId&&nextInterfaceClientId===interfaceClientId&&next?.generation===generation){void poll();return;}authenticated=Boolean(next?.clientId);clientId=next?.clientId||null;interfaceClientId=nextInterfaceClientId;generation=next?.generation??null;events.clear();if(next){latest=null;void poll();}else{latest=null;unavailable('UNAUTHORIZED');}});
  function suspend(){invalidatePending();unavailable('OFFLINE');}
  window.addEventListener('offline',suspend);window.addEventListener('online',()=>{nextDiagnosticAttempt=0;void poll();});
  window.addEventListener('orqevia-shell-state',event=>{if(event.detail?.state==='offline')suspend();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){invalidatePending();}else void poll();});
  const clock=()=>text('dashboard-clock',new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'medium'}).format(new Date()));
  clock();setInterval(clock,1000);setInterval(()=>void poll(),30000);setInterval(()=>{if(latest)render();},5000);void poll();
  window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
}

if (typeof document !== 'undefined' && typeof document.querySelector === 'function' && typeof document.createElement === 'function') {
  const navigation=document.querySelector('.desktop-navigation');
  if(navigation&&!navigation.querySelector('.nav-project-link')){
    const link=document.createElement('a');
    link.className='nav-project-link';
    link.href='/pwa/projects.html';
    link.textContent='Projects & Notebooks';
    navigation.append(link);
  }
  const grid=document.querySelector('.function-grid');
  if(grid&&!grid.querySelector('.project-workspace-link')){
    const link=document.createElement('a');
    link.className='project-workspace-link';
    link.href='/pwa/projects.html';
    link.textContent='Projects & Notebooks';
    grid.append(link);
  }
}
