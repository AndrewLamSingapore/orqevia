import {InterfaceAPI, safeID} from './core.mjs';

export function telemetryFreshness(value, now=Date.now()) {
  if(value?.schema_version!=='orqevia.telemetry.v1'||!Array.isArray(value.metrics)||!Array.isArray(value.agents)||value.agents.length!==21||new Set(value.agents.map(a=>a.agent_id)).size!==21) return 'UNKNOWN';
  const timestamp=Date.parse(value.observed_at), ttl=value.freshness_seconds;
  if(!Number.isFinite(timestamp)||!Number.isFinite(ttl)||ttl<=0||ttl>60||timestamp>now+5000) return 'UNKNOWN';
  return now-timestamp>ttl*1000?'STALE':'OBSERVED';
}

if(typeof document!=='undefined') {
  const api=new InterfaceAPI(), $=id=>document.getElementById(id);
  let latest=null, pending=null, epoch=0, events=new Map();
  const text=(id,value)=>{if($(id))$(id).textContent=value;};
  function view(name){
    $('dashboard').classList.toggle('hidden',name!=='home');
    $('task-workspace').classList.toggle('hidden',!['objective','evidence','data & tools'].includes(name));
    $('capability-view').classList.toggle('hidden',['home','objective'].includes(name));
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
  function unavailable(state){$('agent-provenance-list').replaceChildren();text('telemetry-state',state);text('mobile-system-state',state==='UNAUTHORIZED'?'Not connected':state);text('registered-count','—');text('active-count','—');text('mobile-ready','— / 21');text('telemetry-source','No current authenticated measurement');}
  function render(){
    const state=telemetryFreshness(latest);
    if(state!=='OBSERVED'){unavailable(state);return;}
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
    if(document.hidden||!navigator.onLine||pending)return;
    const controller=new AbortController(), requestEpoch=epoch;pending=controller;
    try{const value=await api.request('/interface/v1/telemetry',{signal:controller.signal,timeout:10000});if(requestEpoch!==epoch)return;latest=value;render();}
    catch(error){if(requestEpoch!==epoch)return;latest=null;unavailable([401,403].includes(error.status)?'UNAUTHORIZED':!navigator.onLine?'OFFLINE':'UNAVAILABLE');}
    finally{if(pending===controller)pending=null;}
  }
  window.addEventListener('orqevia-task',event=>{
    const task=event.detail;if(!safeID(task?.id))return;
    const rows=$('dashboard-task-rows');rows.replaceChildren();const row=document.createElement('tr');
    for(const value of [task.agents.join(', ')||'UNKNOWN',task.id,task.state,'UNKNOWN',task.updated||'UNKNOWN']){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}rows.append(row);
    const key=`${task.id}:${task.revision}:${task.state}`;if(events.has(key))return;
    events.set(key,task);if(events.size>50)events.delete(events.keys().next().value);
    const activity=$('dashboard-activity-rows');activity.replaceChildren();
    for(const record of [...events.values()].reverse().slice(0,8)){const entry=document.createElement('div');entry.className='agent-record';entry.textContent=`${record.id} · ${record.state} · ${record.updated||'source timestamp UNKNOWN'}`;activity.append(entry);}
    text('activity-state','OWNED TASK OBSERVATIONS');
  });
  window.addEventListener('orqevia-session',event=>{epoch++;pending?.abort();pending=null;events.clear();latest=null;unavailable('UNAUTHORIZED');text('dashboard-activity-rows','No owned task event stream selected.');text('activity-state','UNAVAILABLE');const rows=$('dashboard-task-rows');rows.replaceChildren();const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=5;cell.textContent='Open an owned task to inspect its genuine execution record.';row.append(cell);rows.append(row);if(event.detail)void poll();});
  function suspend(){epoch++;pending?.abort();pending=null;latest=null;unavailable('OFFLINE');}
  window.addEventListener('offline',suspend);window.addEventListener('online',()=>void poll());
  document.addEventListener('visibilitychange',()=>{if(document.hidden){epoch++;pending?.abort();pending=null;}else void poll();});
  const clock=()=>text('dashboard-clock',new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'medium'}).format(new Date()));
  clock();setInterval(clock,1000);setInterval(()=>void poll(),30000);setInterval(()=>{if(latest)render();},5000);void poll();
}
