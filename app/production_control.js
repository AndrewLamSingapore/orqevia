'use strict';
const el=id=>document.getElementById(id);
el('exposure-refresh').onclick=async()=>{
  el('exposure-results').textContent='Reading…';
  try {
    const response=await fetch('/control/api/exposure-intelligence');
    if(!response.ok) throw new Error('Unavailable');
    el('exposure-results').textContent=JSON.stringify(await response.json(),null,2);
  } catch {el('exposure-results').textContent='Exposure evidence unavailable.';}
};
async function call(path, body) {
  el('message').textContent='Working…';
  try {
    const response=await fetch('/control/api/'+path, body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const value=await response.json();
    el('result').textContent=JSON.stringify(value,null,2);
    el('message').textContent=response.ok?'Complete.':'Request failed ('+response.status+').';
    if(response.ok) {
      if(value.id || value.job?.id || value.task_id) el('work-id').value=value.id || value.job?.id || value.task_id;
      if(value.artifact_id || value.artifact?.artifact_id) el('artifact-id').value=value.artifact_id || value.artifact.artifact_id;
    }
  } catch(error) {el('message').textContent='Request could not be completed.';}
}
el('submit').addEventListener('submit',event=>{
  event.preventDefault();
  const mode=el('mode').value;
  const body={objective:el('objective').value,context:el('context').value,capability:el('capability').value};
  if(mode==='dispatch' && body.capability==='auto') body.capability='responsibility.a02';
  if(el('operation').value) body.deterministic_operation=el('operation').value;
  call(mode,body);
});
const work=()=>encodeURIComponent(el('work-id').value.trim());
el('task').onclick=()=>call('objectives/'+work());
el('job').onclick=()=>call('jobs/'+work());
el('jobs').onclick=()=>call('jobs');
el('artifact').onclick=()=>call('artifacts/from-task/'+work(),{});
el('download').onclick=()=>{if(el('artifact-id').value.trim()) window.location.href='/control/api/artifacts/'+encodeURIComponent(el('artifact-id').value.trim());};
async function lens(method) {
  const task=work();
  if(!task) {el('proof').textContent='Enter an objective ID.';return;}
  el('proof').textContent='Checking…';
  try {
    const path=method==='happened' ? 'objectives/' : 'evidence/from-objective/';
    const response=await fetch('/control/api/'+path+task,
      method==='record' ? {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'} : {});
    const value=await response.json();
    if(!response.ok) {
      el('proof').textContent=response.status===404 && method==='prove'
        ? 'No proof record yet. Record proof explicitly after the objective finishes.'
        : response.status===404 ? 'Objective not found.'
        : 'Evidence request failed ('+response.status+').';
      return;
    }
    if(method==='happened') {
      const meta=value.execution_metadata || {};
      const result=value.result || {};
      el('proof').textContent=[
        'Objective: '+(value.id || 'UNKNOWN'),
        'Execution: '+(value.state || 'UNKNOWN'),
        'Result type: '+(result.type || 'UNKNOWN'),
        'Claim verification: '+(result.verification_status || 'UNKNOWN'),
        'Agent IDs: '+(meta.agent_execution || []).map(item=>item.selected_agent_id || 'UNKNOWN').join(', '),
        'Source revision: '+(meta.runtime?.source_revision || 'UNKNOWN'),
        'Completed: '+(meta.completed_at || 'UNKNOWN'),
        'Result: '+(result.text || 'No result text recorded')
      ].join('\n');
    } else {
      const observed=value.observed || {};
      const proof=value.proof || {};
      el('proof').textContent=[
        'Record: '+(value.record_id || 'UNKNOWN'),
        'Execution: '+(value.result_state || 'UNKNOWN'),
        'Ledger integrity: '+(value.integrity || 'UNKNOWN'),
        'Currentness: '+(value.currentness || 'UNKNOWN'),
        'Currentness basis: '+(proof.currentness_basis || 'UNKNOWN'),
        'Time freshness: '+(proof.time_freshness || 'UNKNOWN'),
        'Independent verification: '+(value.verification || 'UNKNOWN'),
        'Claim verification at capture: '+(observed.claim_verification || 'UNKNOWN'),
        'Evidence producer: '+(proof.producer || 'UNKNOWN'),
        'Captured: '+(proof.captured_at || 'UNKNOWN'),
        'Completed: '+(proof.completed_at || 'UNKNOWN'),
        'Result SHA-256: '+(observed.result_digest?.value || 'UNKNOWN'),
        'Metadata SHA-256: '+(observed.metadata_digest?.value || 'UNKNOWN'),
        'Reported source revision: '+(observed.runtime?.source_revision || 'UNKNOWN'),
        'Reported runtime image: '+(observed.runtime?.image_digest || 'UNKNOWN'),
        'Not proven: '+(proof.unproven || []).join(', '),
        'Ledger head: '+(value.ledger_head || 'UNKNOWN')
      ].join('\n');
    }
  } catch {el('proof').textContent='Evidence request could not be completed.';}
}
el('what-happened').onclick=()=>lens('happened');
el('record-proof').onclick=()=>lens('record');
el('prove-it').onclick=()=>lens('prove');
let pairingTimer;
el('pair-phone').onclick=async()=>{
  clearTimeout(pairingTimer);
  el('pair-code').textContent='Preparing…';
  try {
    const response=await fetch('/control/api/pwa-pairing',{method:'POST',headers:{'X-Jarvis-PWA':'1','Content-Type':'application/json'},body:JSON.stringify({role:el('pair-role').value})});
    if(!response.ok) throw new Error('Unavailable');
    const value=await response.json();
    el('pair-code').textContent=value.role+' · '+value.code;
    pairingTimer=setTimeout(()=>{el('pair-code').textContent='Pairing code expired.';},Math.max(0,value.expiresAt*1000-Date.now()));
  } catch {el('pair-code').textContent='Pairing unavailable. Try again from the ABEX local control page.';}
};
