// Governed operations use the same authenticated backend as the workspace.
import './intelligence-capabilities.mjs';
// Agent text is rendered as text, never interpreted as markup or authority.
const $=id=>document.getElementById(id);
const element=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let session=null,active=new URL(location.href).searchParams.get('view')==='operations',epoch=0,pending=null,current=null;
let fabricCatalog=[],fabricRequest=null,fabricSequence=0,fabricRun=null,fabricRunSequence=0;
let fabricAudioUrl=null,fabricAudioTimer=null,fabricMediaSequence=0,fabricImageSequence=0;
const kinds=['agents','fabrics','capabilities','dependencies','policies','models','health_snapshots','execution_records','evidence','knowledge_claims','knowledge_contributions','knowledge_relationships','knowledge_challenges','puzzles','puzzle_requirements','gaps','remediation_plans','remediation_executions','remediation_verifications','lessons_learned'];
function status(message,error=false){$('operations-state').textContent=message;$('operations-state').dataset.state=error?'error':'ready';}
function clear(){epoch++;pending?.abort();pending=null;current=null;clearFabricConsole();for(const id of ['operations-metrics','operations-records','operations-detail'])$(id)?.replaceChildren();}
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
 addMetric(root,'Baseline provider fabrics',`${m.fabrics?.integrated??0} / ${m.fabrics?.discovered??0}`,'Seven existing provider integrations; the full capability catalog is shown below.');
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
 void loadFabrics();
 try{const value=await api('status',undefined,controller.signal);if(generation!==epoch||!active)return;current=value;drawMetrics(value);drawRecords(value.gaps?.items||[]);status(`Observed ${value.observed_at||value.metrics?.observed_at}. Claims, execution observations and verified facts remain distinct.`);}
 catch(error){if(generation===epoch)status(controller.signal.aborted?'The registry timed out. Refresh to retry.':error.message,true);}
 finally{clearTimeout(timeout);if(pending===controller)pending=null;}
}
async function mutate(path,body){
 if(!session||!navigator.onLine||current?.stale===true)return;const generation=epoch;const buttons=$('operations-view').querySelectorAll('button');buttons.forEach(b=>b.disabled=true);status('Submitting an authorized, bounded operation…');
 try{const value=await api(path,body,AbortSignal.timeout(35000));if(generation!==epoch)return;await load();if(value.record)chooseRecord(value.record);status(value.job_id?`Investigation queued as ${value.job_id}. Its eventual result must still be checked.`:'Operation recorded. Refresh or inspect the record for its actual state and evidence.');}
 catch(error){if(generation===epoch)status(error.message,true);}
 finally{buttons.forEach(b=>b.disabled=false);fabricControls();}
}
const fabricId=/^f(?:0[1-9]|[12][0-9]|3[0-6])$/;
const executionId=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function fabricStatus(message,error=false){const node=$('fabric-state');if(node){node.textContent=message;node.dataset.state=error?'error':'ready';}}
function selectedFabric(){return fabricCatalog.find(item=>item.id===$('fabric-select')?.value);}
function fabricOperations(item){return Array.isArray(item?.runtime_contract?.operations)?item.runtime_contract.operations.filter(op=>typeof op?.operation==='string'&&/^[A-Za-z0-9_.:-]{1,100}$/.test(op.operation)):[];}
function selectedOperation(){return fabricOperations(selectedFabric()).find(op=>op.operation===$('fabric-operation')?.value);}
function fabricImageOperation(){const item=selectedFabric(),operation=selectedOperation();return Boolean((item?.id==='f17'&&operation?.operation==='image.inspect'||item?.id==='f32'&&operation?.operation==='image.measure')&&operation.input_schema?.properties?.image_base64?.type==='string');}
function clearFabricImage(){fabricImageSequence++;if($('fabric-image-file'))$('fabric-image-file').value='';if($('fabric-image-state'))$('fabric-image-state').textContent='Select a PNG up to 512 KB. Its original bytes populate the declared image input; select Run to execute.';}
function fabricControls(){
 const connected=Boolean(active&&session?.role==='OWNER'&&navigator.onLine);
 if($('fabric-inputs'))$('fabric-inputs').disabled=!connected||!fabricCatalog.length||Boolean(fabricRun);
 if($('fabric-run'))$('fabric-run').disabled=!connected||!selectedOperation()||Boolean(fabricRun)||['DISABLED','UNAVAILABLE'].includes(selectedFabric()?.state);
 if($('fabric-read'))$('fabric-read').disabled=!connected||Boolean(fabricRun)||!executionId.test($('fabric-execution-id')?.value.trim().toLowerCase()||'');
 if($('fabric-refresh'))$('fabric-refresh').disabled=!connected||Boolean(fabricRequest);
}
function clearFabricResult(){
 fabricMediaSequence++;const root=$('fabric-result');root?.querySelector('audio')?.pause();clearTimeout(fabricAudioTimer);fabricAudioTimer=null;
 if(fabricAudioUrl){URL.revokeObjectURL(fabricAudioUrl);fabricAudioUrl=null;}
 root?.replaceChildren();
}
function clearFabricConsole(){
 fabricSequence++;fabricRunSequence++;fabricRequest?.abort();fabricRun?.abort();fabricRequest=null;fabricRun=null;fabricCatalog=[];
 clearFabricResult();clearFabricImage();if($('fabric-image-upload'))$('fabric-image-upload').hidden=true;for(const id of ['fabric-select','fabric-operation','fabric-contract'])$(id)?.replaceChildren();
 for(const id of ['fabric-input-schema','fabric-output-schema','fabric-summary'])if($(id))$(id).textContent='';
 if($('fabric-parameters'))$('fabric-parameters').value='{}';
 if($('fabric-execution-id'))$('fabric-execution-id').value='';
 if($('fabric-run'))$('fabric-run').textContent='Run selected operation';
 fabricStatus('Restore the bound owner connection to read fabric contracts.');fabricControls();
}
function drawFabricContract(){
 const item=selectedFabric(),operation=selectedOperation(),root=$('fabric-contract');if(!root)return;root.replaceChildren();
 if($('fabric-image-upload'))$('fabric-image-upload').hidden=!fabricImageOperation();
 if(!item){root.append(element('p','No fabric contracts are available. Refresh the catalog to retry.'));$('fabric-input-schema').textContent='No executable input schema.';$('fabric-output-schema').textContent='No executable output schema.';fabricControls();return;}
 const verification=item.verification||{},expires=Date.parse(verification.expires_at||'');
 const expired=Number.isFinite(expires)&&expires<=Date.now();
 root.append(element('h3',`${item.id.toUpperCase()} · ${item.name}`),element('p',item.purpose||'Purpose not reported.'));
 root.append(element('p',`Lifecycle: ${item.state||'UNVERIFIED'} · Contract ${item.runtime_contract?.version||item.version||'unavailable'}`,'fabric-lifecycle'));
 if(verification.scope)root.append(element('p','Verification scope: '+verification.scope));
 else root.append(element('p','Verification: '+(verification.reason||verification.status||'No current functional evidence reported.')));
 if(verification.observed_at)root.append(element('p','Evidence observed: '+verification.observed_at));
 if(verification.expires_at)root.append(element('p',`Evidence expires: ${verification.expires_at}${expired?' — expired; refresh before relying on this state.':''}`,expired?'fabric-warning':undefined));
 if(operation)root.append(element('p','Selected operation scope: '+(operation.scope||'Not reported.')));
 else root.append(element('p','No executable operation is exposed for this fabric. Its lifecycle entry remains visible.','fabric-warning'));
 const limits=item.runtime_contract?.limitations;
 if(Array.isArray(limits)&&limits.length){const list=element('ul');for(const limit of limits.slice(0,12))list.append(element('li',String(limit)));root.append(list);}
 $('fabric-input-schema').textContent=operation?JSON.stringify(operation.input_schema||{},null,2):'No executable input schema.';
 $('fabric-output-schema').textContent=operation?JSON.stringify(operation.output_schema||{},null,2):'No executable output schema.';
 fabricControls();
}
function chooseFabric({preserve=false}={}){
 const options=$('fabric-operation'),previous=options.value;options.replaceChildren();
 for(const operation of fabricOperations(selectedFabric())){const node=element('option',operation.operation);node.value=operation.operation;options.append(node);}
 if(preserve&&fabricOperations(selectedFabric()).some(op=>op.operation===previous))options.value=previous;
 if(!preserve){$('fabric-parameters').value='{}';clearFabricResult();clearFabricImage();$('fabric-execution-id').value='';$('fabric-run').textContent='Run selected operation';}
 drawFabricContract();
}
async function loadFabrics(){
 if(!$('fabric-select'))return;
 if(!active||session?.role!=='OWNER'||!navigator.onLine){clearFabricConsole();fabricStatus(navigator.onLine?'Restore the bound owner connection to read fabric contracts.':'Offline. Private fabric inputs and receipts were cleared. Reconnect to refresh.');return;}
 fabricRequest?.abort();const controller=new AbortController();fabricRequest=controller;const sequence=++fabricSequence,generation=epoch;
 fabricStatus('Loading current fabric contracts and verification evidence…');fabricControls();const timeout=setTimeout(()=>controller.abort(),15000);
 try{
  const value=await api('fabrics/registry',undefined,controller.signal);
  if(generation!==epoch||sequence!==fabricSequence||!active)return;
  if(!Array.isArray(value?.fabrics)||value.fabrics.length>36||value.fabrics.some(item=>!fabricId.test(item?.id))||new Set(value.fabrics.map(item=>item.id)).size!==value.fabrics.length)throw new Error('The service returned an unsupported fabric catalog.');
  const previous=$('fabric-select').value;fabricCatalog=value.fabrics;const select=$('fabric-select');select.replaceChildren();
  for(const item of fabricCatalog){const node=element('option',`${item.id.toUpperCase()} · ${item.name} · ${item.state}`);node.value=item.id;select.append(node);}
  if(fabricCatalog.some(item=>item.id===previous))select.value=previous;
  const exposed=fabricCatalog.filter(item=>fabricOperations(item).length).length,verified=fabricCatalog.filter(item=>item.state==='VERIFIED').length;
  $('fabric-summary').textContent=`${fabricCatalog.length} defined · ${exposed} with executable operations · ${verified} reported VERIFIED within their listed scopes. Registry observed: ${value.verification_context?.observed_at||'not reported'}.`;
  chooseFabric({preserve:Boolean(previous&&select.value===previous)});
  fabricStatus(fabricCatalog.length?'Catalog loaded. Select a fabric and review its operation scope and input schema.':'The registry returned no fabric contracts. Refresh to retry.');
 }catch(error){if(generation===epoch&&sequence===fabricSequence&&active)fabricStatus(controller.signal.aborted?'The fabric catalog timed out. Refresh to retry.':error.message,true);}
 finally{clearTimeout(timeout);if(fabricRequest===controller)fabricRequest=null;fabricControls();}
}
function fabricParameters(){
 const text=$('fabric-parameters').value;
 if(new TextEncoder().encode(text).length>800000)throw new Error('JSON input exceeds the 800 KB request limit.');
 let value;try{value=JSON.parse(text);}catch{throw new Error('Enter valid JSON input. The input must be one object.');}
 if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('The JSON input must be one object.');
 const inspect=(item,depth=0)=>{if(depth>20)throw new Error('JSON nesting exceeds the supported limit.');if(typeof item==='number'&&!Number.isFinite(item))throw new Error('JSON numbers must be finite.');if(item&&typeof item==='object')for(const child of Object.values(item))inspect(child,depth+1);};inspect(value);
 return value;
}
async function readFabricImage(){
 if(!fabricImageOperation()||!active||session?.role!=='OWNER'||!navigator.onLine||fabricRun)return;
 const input=$('fabric-image-file'),file=input.files?.[0],state=$('fabric-image-state');if(!file)return;
 if(input.files.length!==1||file.size<8||file.size>524288||!['','image/png'].includes(file.type)){input.value='';state.textContent='Select one PNG up to 512 KB. The existing JSON input was not changed.';return;}
 let parameters;try{parameters=fabricParameters();}catch(error){input.value='';state.textContent=error.message;return;}
 const generation=epoch,sequence=++fabricImageSequence,id=selectedFabric().id,operation=selectedOperation().operation,original=$('fabric-parameters').value;
 state.textContent='Reading the selected PNG bytes…';
 try{
  const bytes=new Uint8Array(await file.arrayBuffer());if(bytes.length!==file.size||![137,80,78,71,13,10,26,10].every((value,index)=>bytes[index]===value))throw new Error('Invalid PNG signature.');
  let binary='';for(let index=0;index<bytes.length;index+=32768)binary+=String.fromCharCode(...bytes.subarray(index,index+32768));
  const encoded=btoa(binary),limit=selectedOperation()?.input_schema?.properties?.image_base64?.maxLength;if(Number.isInteger(limit)&&encoded.length>limit)throw new Error('PNG exceeds the declared field limit.');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('');
  if(generation!==epoch||sequence!==fabricImageSequence||!active||!navigator.onLine||selectedFabric()?.id!==id||selectedOperation()?.operation!==operation)return;
  if($('fabric-parameters').value!==original){state.textContent='The JSON input changed while reading. Select the PNG again to keep your edits.';return;}
  $('fabric-parameters').value=JSON.stringify({...parameters,image_base64:encoded},null,2);state.textContent=`Loaded ${file.name} · ${bytes.length} original bytes · SHA-256 ${hash}. Select Run to execute.`;
 }catch{if(generation===epoch&&sequence===fabricImageSequence){input.value='';state.textContent='PNG input was not loaded. Use a readable PNG up to 512 KB within the declared field limit. The existing JSON input was not changed.';}}
}
function decodeFabricWav(result){
 const encoded=result.audio_base64,maximum=1048576;
 if(result.mime_type!=='audio/wav'||typeof encoded!=='string'||encoded.length>4*Math.ceil(maximum/3)||!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded))throw new Error('Unsupported audio payload.');
 let binary;try{binary=atob(encoded);}catch{throw new Error('Invalid audio encoding.');}
 if(binary.length<44||binary.length>maximum||btoa(binary)!==encoded)throw new Error('Audio exceeds its supported format or size.');
 const bytes=Uint8Array.from(binary,value=>value.charCodeAt(0)),view=new DataView(bytes.buffer);
 if(view.getUint32(0)!==0x52494646||view.getUint32(8)!==0x57415645||view.getUint32(4,true)!==bytes.length-8)throw new Error('Invalid WAV container.');
 let offset=12,format=null,dataBytes=null,chunks=0;
 while(offset<bytes.length){
  if(++chunks>64||offset+8>bytes.length)throw new Error('Invalid WAV chunks.');
  const kind=view.getUint32(offset),size=view.getUint32(offset+4,true),start=offset+8,end=start+size,next=end+(size%2);
  if(end>bytes.length||next>bytes.length)throw new Error('Truncated WAV chunk.');
  if(kind===0x666d7420){
   if(format||size!==16||view.getUint16(start,true)!==1)throw new Error('Only PCM WAV is supported.');
   const channels=view.getUint16(start+2,true),rate=view.getUint32(start+4,true),byteRate=view.getUint32(start+8,true),alignment=view.getUint16(start+12,true),bits=view.getUint16(start+14,true);
   if(![1,2].includes(channels)||rate<8000||rate>48000||bits!==16||alignment!==channels*2||byteRate!==rate*alignment)throw new Error('Unsupported PCM audio.');
   format={channels,rate,alignment};
  }else if(kind===0x64617461){
   if(!format||dataBytes!==null||!size||size%format.alignment)throw new Error('Invalid PCM frames.');dataBytes=size;
  }else throw new Error('Unsupported WAV chunk.');
  offset=next;
 }
 if(!format||dataBytes===null||offset!==bytes.length||dataBytes/(format.rate*format.alignment)>60||!/^[a-f0-9]{64}$/.test(result.audio_sha256||''))throw new Error('A bounded WAV with its recorded hash is required.');
 return {bytes,channels:format.channels,rate:format.rate,frames:dataBytes/format.alignment,seconds:dataBytes/(format.rate*format.alignment)};
}
async function addFabricAudio(result,decoded,id,generation,sequence){
 const root=$('fabric-result');
 try{
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',decoded.bytes)),value=>value.toString(16).padStart(2,'0')).join('');
  if(generation!==epoch||sequence!==fabricMediaSequence)return;
  if(hash!==result.audio_sha256)throw new Error('Audio hash mismatch.');
  const url=URL.createObjectURL(new Blob([decoded.bytes],{type:'audio/wav'}));fabricAudioUrl=url;
  const media=element('section',undefined,'fabric-audio'),label=element('h4','Speech audio'),audio=element('audio'),download=element('a','Download WAV audio'),play=element('button','Play speech'),state=element('p','Playback starts only when you choose Play.');
  audio.controls=true;audio.autoplay=false;audio.preload='metadata';audio.src=url;audio.setAttribute('aria-label','Generated speech audio');
  play.type='button';state.setAttribute('role','status');
  const current=()=>generation===epoch&&sequence===fabricMediaSequence;
  const unavailable=()=>{if(current())state.textContent='This browser could not play the WAV. Download it to use your device\'s audio player.';};
  audio.addEventListener('error',unavailable);audio.addEventListener('playing',()=>{if(current())state.textContent='The audio player is playing.';});audio.addEventListener('ended',()=>{if(current())state.textContent='Playback finished.';});
  play.addEventListener('click',()=>{if(!current())return;clearTimeout(fabricAudioTimer);state.textContent='Starting audio playback…';const timer=setTimeout(()=>{if(current()&&audio.readyState===0){audio.pause();unavailable();}},6000);fabricAudioTimer=timer;void audio.play().catch(unavailable).finally(()=>{clearTimeout(timer);if(fabricAudioTimer===timer)fabricAudioTimer=null;});});
  download.href=url;download.download='orqevia-speech-'+id+'.wav';download.type='audio/wav';
  media.append(label,element('p',`${decoded.frames} PCM frames · ${decoded.channels} channel(s) · ${decoded.rate} Hz · ${decoded.seconds.toFixed(2)} seconds. Choose Play to listen.`),audio,play,download,state);root.append(media);
 }catch{if(generation===epoch&&sequence===fabricMediaSequence)root.append(element('p','Audio preview unavailable: its format, size or recorded hash could not be validated. The original execution receipt remains available.','fabric-warning'));}
}
function drawFabricExecution(value,id,expected=null){
 if(value?.execution_id!==id||typeof value.status!=='string'||(expected&&(value.fabric_id!==expected.fabric||value.operation!==expected.operation)))throw new Error('The service returned a different execution receipt. Recover the requested execution by its identifier.');
 clearFabricResult();const root=$('fabric-result');root.append(element('h3','Recorded execution'),element('p',`Status: ${value.status}`,'fabric-lifecycle'));
 const facts=element('dl',undefined,'fabric-receipt');
 for(const [label,content] of [['Execution ID',value.execution_id],['Fabric / operation',`${value.fabric_id} / ${value.operation}`],['Contract version',value.version],['Runtime source',value.runtime_revision],['Input SHA-256',value.input_sha256],['Result SHA-256',value.result_sha256],['Elapsed milliseconds',value.duration_ms],['Started',value.started_at],['Error code',value.error_code]]){
  facts.append(element('dt',label),element('dd',content===undefined||content===null?'Not recorded':String(content)));
 }
 root.append(facts);
 if(value.result!==undefined&&value.result!==null){
  let decoded=null;const hasAudio=Object.prototype.hasOwnProperty.call(value.result,'audio_base64');
  if(hasAudio){try{decoded=decodeFabricWav(value.result);}catch{root.append(element('p','Audio preview unavailable: the receipt does not contain a supported bounded PCM WAV.','fabric-warning'));}}
  const preview=JSON.stringify(value.result,(key,content)=>key==='audio_base64'?(decoded?`[${decoded.bytes.length} WAV bytes; use the audio controls or download]`:'[audio payload omitted]'):content,2);
  root.append(element('pre',preview,'fabric-output'));
  if(decoded)void addFabricAudio(value.result,decoded,id,epoch,fabricMediaSequence);
 }
 $('fabric-execution-id').value=id;
 return value.status;
}
async function runFabric(){
 if(fabricRun||session?.role!=='OWNER'||!active||!navigator.onLine)return;
 const item=selectedFabric(),operation=selectedOperation();if(!item||!operation||['DISABLED','UNAVAILABLE'].includes(item.state)){fabricControls();return;}
 let parameters;try{parameters=fabricParameters();}catch(error){fabricStatus(error.message,true);return;}
 const id=crypto.randomUUID(),generation=epoch,sequence=++fabricRunSequence,controller=new AbortController();fabricRun=controller;
 clearFabricResult();$('fabric-execution-id').value=id;fabricStatus(`Running ${item.id.toUpperCase()} / ${operation.operation}. Execution ${id}.`);fabricControls();
 const timeout=setTimeout(()=>controller.abort(),45000);let received=false;
 try{
  const value=await api(`fabrics/${item.id}/execute`,{operation:operation.operation,parameters,execution_id:id},controller.signal);
  if(generation!==epoch||sequence!==fabricRunSequence||!active)return;
  drawFabricExecution(value,id,{fabric:item.id,operation:operation.operation});received=true;
  const receipt=await api('fabrics/executions/'+id,undefined,controller.signal);
  if(generation!==epoch||sequence!==fabricRunSequence||!active)return;
  const state=drawFabricExecution(receipt,id,{fabric:item.id,operation:operation.operation});
  fabricStatus(`Execution ${state}. Its persisted receipt was read back. Fabric verification remains limited to the catalog's recorded evidence.`,state==='FAILED');
 }catch(error){if(generation===epoch&&sequence===fabricRunSequence&&active)fabricStatus(received?'An execution response was received, but receipt readback is unavailable. Use Read execution to recover its recorded state.':`The request did not return a confirmed outcome. Use Read execution for ${id} before repeating it. ${controller.signal.aborted?'The request timed out.':error.message}`,true);}
 finally{clearTimeout(timeout);if(fabricRun===controller){fabricRun=null;$('fabric-run').textContent='Run new execution';}fabricControls();}
}
async function readFabricExecution(){
 if(fabricRun||session?.role!=='OWNER'||!active||!navigator.onLine)return;
 const id=$('fabric-execution-id').value.trim().toLowerCase();if(!executionId.test(id)){fabricStatus('Enter a valid execution UUID to read its scoped receipt.',true);return;}
 const controller=new AbortController(),generation=epoch,sequence=++fabricRunSequence;fabricRun=controller;fabricStatus('Reading the persisted execution receipt…');fabricControls();const timeout=setTimeout(()=>controller.abort(),15000);
 try{const value=await api('fabrics/executions/'+id,undefined,controller.signal);if(generation!==epoch||sequence!==fabricRunSequence||!active)return;const state=drawFabricExecution(value,id);fabricStatus(`Recorded execution ${state}. Reading a receipt does not repeat the operation.`,state==='FAILED');}
 catch(error){if(generation===epoch&&sequence===fabricRunSequence&&active)fabricStatus(controller.signal.aborted?'Receipt readback timed out. Read execution again to retry safely.':error.message,true);}
 finally{clearTimeout(timeout);if(fabricRun===controller)fabricRun=null;fabricControls();}
}
$('fabric-refresh')?.addEventListener('click',()=>void loadFabrics());
$('fabric-select')?.addEventListener('change',()=>chooseFabric());
$('fabric-operation')?.addEventListener('change',()=>{$('fabric-parameters').value='{}';clearFabricResult();clearFabricImage();$('fabric-execution-id').value='';drawFabricContract();});
$('fabric-image-file')?.addEventListener('change',()=>void readFabricImage());
$('fabric-form')?.addEventListener('submit',event=>{event.preventDefault();void runFabric();});
$('fabric-read')?.addEventListener('click',()=>void readFabricExecution());
$('fabric-execution-id')?.addEventListener('input',fabricControls);
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
