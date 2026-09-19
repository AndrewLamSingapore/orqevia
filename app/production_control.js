'use strict';
const el=id=>document.getElementById(id);
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
