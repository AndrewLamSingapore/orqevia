export const PROTOCOL = 'orqevia.interface.v1';
export const terminal = state => ['COMPLETED','FAILED','CANCELLED','COMPLETED_WITH_FAILURES'].includes(state);
export const safeID = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value) && !['.','..'].includes(value);
export class ClientError extends Error { constructor(code, status = 0) { super(code); this.code = code; this.status = status; } }
export function errorMessage(error) {
  if (error?.status === 401 || error?.status === 403) return 'Your session has expired or access was denied. Connect again to continue.';
  if (error?.status === 409) return 'The previous request needs reconciliation. Keep its retry key and avoid sending a new copy.';
  if (error?.status === 404) return 'This task or file is not available to your session.';
  if (error?.status === 422 || error?.code === 'input') return 'Check the objective or file. Upload up to four text files, with combined content below 80,000 characters.';
  if (error?.status === 429) return 'ORQEVIA is busy. Wait a moment, then try again.';
  if (error?.code === 'integrity') return 'File verification failed. No download was released. Try retrieving it again.';
  if (error?.code === 'pending') return 'An earlier objective may already be running. Retry its original text and attachments to recover it.';
  if (error?.code === 'protocol') return 'This endpoint did not return the expected ORQEVIA response. Check your connection.';
  if (error?.code === 'storage') return 'This browser could not save retry protection. Enable site storage before sending an objective.';
  if (error?.name === 'AbortError') return 'Request paused. Reconnect to recover the task; its retry identity is preserved.';
  if (error?.code === 'timeout' || error instanceof TypeError) return 'Connection interrupted. Retry the same objective or refresh your task when online.';
  return 'ORQEVIA could not complete this request. Try again when the connection is available.';
}
export function sessionActive(session, nowSeconds = Date.now() / 1000) {
  return Boolean(session?.authenticated && session.protocol === PROTOCOL && Number.isFinite(session.expiresAt) && session.expiresAt > nowSeconds && Number.isFinite(session.verifiedAt) && nowSeconds-session.verifiedAt <= 90);
}
export async function sha256(bytes) { return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2,'0')).join(''); }
export function nextSubmission(prior, digest, key) {
  if (prior?.digest === digest) return prior;
  if (prior && !prior.taskId) throw new ClientError('pending');
  return {digest, key, taskId:null};
}
export function acknowledge(prior, key, taskId) {
  if (!prior || prior.key !== key || !safeID(taskId)) throw new ClientError('protocol');
  if (prior.action?.kind === 'continue' && prior.action.targetTaskId !== taskId) throw new ClientError('protocol');
  return {...prior, taskId};
}
export function continuationAction(task) {
  const id=taskID(task);
  if(!terminal(task.state)||!Number.isSafeInteger(task.revision)||task.revision<0)throw new ClientError('input');
  return {kind:'continue',targetTaskId:id,expectedRevision:task.revision};
}
export function submissionPayload(objective,uploads=[],action={kind:'new'}) {
  if(typeof objective!=='string'||!objective.trim()||objective.length>20000)throw new ClientError('input');
  if(action.kind==='continue'){
    if(!safeID(action.targetTaskId)||!Number.isSafeInteger(action.expectedRevision)||action.expectedRevision<0||uploads.length)throw new ClientError('input');
    return {mode:'continue',taskId:action.targetTaskId,expected_revision:action.expectedRevision,objective:objective.trim(),context:''};
  }
  return {objective:objective.trim(),uploads};
}
export function taskID(task) { const id = task.taskId ?? task.task_id ?? task.id; if (!safeID(id)) throw new ClientError('protocol'); return id; }
export function taskRevision(task) { const revision=task.revision??0;if(!Number.isSafeInteger(revision)||revision<0)throw new ClientError('protocol');return revision; }
export function authoritativeMetadataText(task) {
  const value=task.executionMetadata??task.execution_metadata;if(!value)return '';
  if(value.authoritative!==true||value.task_id!==taskID(task)||value.revision!==taskRevision(task))throw new ClientError('protocol');
  const shown=item=>item===null||item===undefined||item===''?'UNKNOWN':String(item);
  const contradictions=Array.isArray(task.result?.contradictions)?task.result.contradictions.length:0;
  return `ORQEVIA SYSTEM RECORD\nTask UUID: ${shown(value.task_id)}\nState: ${shown(value.state)}\nCreated: ${shown(value.created_at)}\nStarted: ${shown(value.started_at)}\nCompleted: ${shown(value.completed_at)}\nRuntime: ${shown(value.runtime?.host_id)} · ${shown(value.runtime?.source_revision)}\n${contradictions?`Warning: ${contradictions} model metadata claim(s) conflict with or are unsupported by the system record.\n`:''}\nThe response below is model-generated content. Any UUID, timestamp, digest, runtime identity, or authority claim inside it is not system metadata.`;
}
export function currentSteps(task) { const revision=taskRevision(task);return (task.steps||[]).filter(step=>(step.revision??0)===revision).slice(0,21); }
export function resultText(task) {
  const textOf = value => typeof value === 'string' ? value : value && [value.text,value.summary,value.message].find(x => typeof x === 'string');
  const direct = textOf(task.result);
  if (direct) return direct.slice(0,40000);
  return currentSteps(task).map(step => {
    const text = textOf(step.job?.result);
    return text || '';
  }).filter(Boolean).join('\n\n').slice(0,40000);
}
// Read-aloud and visible result text both exclude internal agent identities.
export function spokenText(task) {
  if (!task) return '';
  const textOf = value => typeof value === 'string' ? value : value && [value.text,value.summary,value.message].find(x => typeof x === 'string');
  const direct = textOf(task.result);
  if (direct) return direct.slice(0,40000);
  return currentSteps(task).map(step => textOf(step.job?.result) || '').filter(Boolean).join('\n\n').slice(0,40000);
}
export function resultPresentation(task,previous=null) {
  const current=resultText(task),revision=taskRevision(task),id=taskID(task);
  const showPrevious=!current&&!terminal(task.state)&&previous?.taskId===id&&previous.revision<revision&&Boolean(previous.text);
  return {current,previous:showPrevious?{text:previous.text,label:`Previous result · revision ${previous.revision}`} : null};
}
export function artifactLabel(item) {
  const revision=Number.isSafeInteger(item.revision)?` · revision ${item.revision}`:'';
  return `${item.isLatestResult?'Latest result': 'Saved file'}${revision} · ${String(item.type||'result').toUpperCase()}`;
}
export function parseSSE(text) {
  const normalized = text.replace(/\r\n/g,'\n');
  if (normalized && !normalized.endsWith('\n\n')) throw new ClientError('protocol');
  return normalized.split('\n\n').filter(Boolean).flatMap(frame => {
    const lines = frame.split('\n'), id = lines.find(l => l.startsWith('id:'))?.slice(3).trim();
    const body = lines.filter(l => l.startsWith('data:')).map(l => l.slice(5).replace(/^ /,'')).join('\n');
    if (!body) return [];
    if (!/^[a-f0-9]{64}$/i.test(id || '')) throw new ClientError('protocol');
    let task; try { task = JSON.parse(body); } catch { throw new ClientError('protocol'); }
    taskID(task); return [{id,task}];
  });
}
export function retryable(error) { return error instanceof TypeError || error?.code === 'timeout'; }
export async function boundedRetry(operation, {safe = true, sleep = ms => new Promise(r => setTimeout(r,ms)), signal} = {}) {
  for (let attempt = 0; attempt < 3; attempt++) {
    if (signal?.aborted) throw new DOMException('Paused','AbortError');
    try { return await operation(); } catch (error) { if (!safe || attempt === 2 || !retryable(error) || signal?.aborted) throw error; await sleep(500 * (2 ** attempt)); }
  }
}
export class InterfaceAPI {
  constructor(fetcher = globalThis.fetch.bind(globalThis)) { this.fetcher = fetcher; }
  async request(path, {method='GET', body, headers={}, signal, timeout=30000, mode='json', retry=false} = {}) {
    if (!(path.startsWith('/pwa/api/') || path.startsWith('/interface/v1/')) || path.includes('..')) throw new ClientError('input');
    return boundedRetry(async () => {
      const controller = new AbortController(); let timedOut = false;
      const abort = () => controller.abort(); signal?.addEventListener('abort',abort,{once:true});
      const timer = setTimeout(() => { timedOut = true; controller.abort(); },timeout);
      try {
        if (signal?.aborted) throw new DOMException('Paused','AbortError');
        const response = await this.fetcher(path,{method,body,headers:{'X-ORQEVIA-PWA':'1',...headers},credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
        if (path.startsWith('/interface/') && response.headers.get('X-ORQEVIA-Protocol') !== PROTOCOL) throw new ClientError('protocol');
        if (!response.ok) throw new ClientError('http',response.status);
        const expected = mode === 'sse' ? 'text/event-stream' : mode === 'bytes' ? 'application/octet-stream' : 'application/json';
        if (response.headers.get('content-type')?.split(';')[0].trim() !== expected) throw new ClientError('protocol');
        const limit = mode === 'bytes' ? 16*1024*1024 : 2*1024*1024;
        if (Number(response.headers.get('content-length')) > limit) throw new ClientError('input');
        const reader = response.body?.getReader(); if (!reader) throw new ClientError('protocol');
        const chunks = []; let size = 0;
        try { while (true) { const {done,value} = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw new ClientError('input'); } chunks.push(value); } } finally { reader.releaseLock(); }
        const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.length; }
        if (mode === 'bytes') return {bytes,headers:response.headers};
        let text; try { text = new TextDecoder('utf-8',{fatal:true}).decode(bytes); } catch { throw new ClientError('protocol'); }
        if (mode === 'sse') return parseSSE(text);
        try { return JSON.parse(text); } catch { throw new ClientError('protocol'); }
      } catch (error) { if (timedOut) throw new ClientError('timeout'); throw error; }
      finally { clearTimeout(timer); signal?.removeEventListener('abort',abort); }
    },{safe:retry,signal});
  }
  session() { return this.request('/pwa/api/session'); }
  enroll(code) { return this.request('/pwa/api/enroll',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({code})}); }
  logout() { return this.request('/pwa/api/logout',{method:'POST'}); }
  ownerAuthorityCheck() { return this.request('/pwa/api/owner-authority-check',{method:'POST'}); }
  submit(objective,key,uploads,signal) { return this.request('/interface/v1/objectives',{method:'POST',headers:{'content-type':'application/json','idempotency-key':key},body:JSON.stringify({objective,uploaded_artifact_ids:uploads}),retry:true,signal}); }
  continueTask(action,objective,key,signal) {
    const payload=submissionPayload(objective,[],action);
    if(payload.mode!=='continue'||!safeID(key)||key.length>100)throw new ClientError('input');
    return this.request(`/interface/v1/tasks/${encodeURIComponent(payload.taskId)}/continue`,{method:'POST',headers:{'content-type':'application/json','idempotency-key':key},body:JSON.stringify({objective:payload.objective,context:payload.context,expected_revision:payload.expected_revision,idempotency_key:key}),retry:true,signal}).then(task=>{if(taskID(task)!==payload.taskId||!Number.isSafeInteger(task.revision)||task.revision<=payload.expected_revision)throw new ClientError('protocol');return task;});
  }
  status(id,signal) { if (!safeID(id)) throw new ClientError('input'); return this.request(`/interface/v1/tasks/${encodeURIComponent(id)}`,{retry:true,signal}).then(task => { if(taskID(task)!==id) throw new ClientError('protocol'); return task; }); }
  events(id,cursor,signal) { if (!safeID(id)) throw new ClientError('input'); return this.request(`/interface/v1/tasks/${encodeURIComponent(id)}/events`,{mode:'sse',headers:cursor?{'Last-Event-ID':cursor}:{},signal}).then(events => { if(events.some(e=>taskID(e.task)!==id)) throw new ClientError('protocol');return events; }); }
  cancel(id) { if (!safeID(id)) throw new ClientError('input'); return this.request(`/interface/v1/tasks/${encodeURIComponent(id)}/cancel`,{method:'POST'}); }
  async artifacts(id,signal) { if (!safeID(id)) throw new ClientError('input'); let offset=0; const all=[]; while(true) { const page=await this.request(`/interface/v1/tasks/${encodeURIComponent(id)}/artifacts?offset=${offset}&limit=100`,{retry:true,signal}); if(!Array.isArray(page.artifacts)||page.artifacts.length>100) throw new ClientError('protocol'); all.push(...page.artifacts.map(item=>{const latest=(item.artifactId??item.artifact_id)===page.latest_result_artifact_id;return{...item,isLatestResult:latest,...(latest?{revision:page.revision??0}:{})};})); if(page.next_offset==null)return all.sort((a,b)=>Number(b.isLatestResult)-Number(a.isLatestResult)); if(!Number.isInteger(page.next_offset)||page.next_offset<=offset||page.next_offset>100000)throw new ClientError('protocol');offset=page.next_offset; } }
  async artifact(item,signal) { const id=item.artifactId??item.artifact_id; if(!safeID(id)||!/^[0-9a-f]{64}$/i.test(item.sha256))throw new ClientError('input'); const value=await this.request(`/interface/v1/artifacts/${encodeURIComponent(id)}`,{mode:'bytes',retry:true,signal}); const hash=await sha256(value.bytes); if(hash!==item.sha256.toLowerCase()||hash!==value.headers.get('X-Artifact-SHA256')?.toLowerCase()||value.bytes.length!==item.bytes)throw new ClientError('integrity');return {...value,hash,id}; }
  async upload(file) { if(file.size>1024*1024||! /\.(txt|md|json)$/i.test(file.name))throw new ClientError('input'); const bytes=await file.arrayBuffer(); const result=await this.request('/pwa/api/uploads',{method:'POST',headers:{'content-type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:bytes}); if(result.sha256?.toLowerCase()!==await sha256(bytes)||result.bytes!==file.size)throw new ClientError('integrity');return result; }
}
