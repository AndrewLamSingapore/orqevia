// Private document intelligence shares the primary workspace and trusted session.
if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id),panel=$('private-knowledge');
 let session=null,epoch=0,busy=false,lastAnswer=null;
 const make=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 function state(text,error=false){$('knowledge-state').textContent=text;$('knowledge-state').classList.toggle('error',error);}
 async function api(path,{body,raw,filename,timeout=30000}={}){
  const headers={'Accept':'application/json','X-ORQEVIA-PWA':'1'};
  if(filename)headers['X-Document-Name']=encodeURIComponent(filename);
  headers['Content-Type']=raw?'application/octet-stream':'application/json';
  const r=await fetch('/api/orqevia/knowledge/'+path,{method:body!==undefined||raw?'POST':'GET',body:raw|| (body!==undefined?JSON.stringify(body):undefined),headers,credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(timeout)});
  if(!r.ok){const e=new Error(r.status===403?'Private documents require the bound owner account.':r.status===429?'Another local AI request is running. Retry shortly.':`Knowledge service returned ${r.status}. Retry when available.`);e.status=r.status;throw e;}return r.json();
 }
 function controls(){for(const id of ['knowledge-upload','knowledge-ask','knowledge-retrieve','knowledge-reindex'])$(id).disabled=busy||session?.role!=='OWNER';}
 async function action(operation){if(busy)return;busy=true;controls();const current=epoch;try{await operation(current);}catch(e){if(current===epoch)state(e.name==='TimeoutError'?'The local AI request reached its deadline. Existing data is preserved.':e.message,true);}finally{busy=false;controls();if(current!==epoch&&session?.role==='OWNER')void action(load);}}
 async function load(current=epoch){
  if(session?.role!=='OWNER')return;
  const results=await Promise.allSettled([api('health'),api('documents')]);if(current!==epoch)return;
  const health=results[0],docs=results[1];
  $('knowledge-health').textContent=health.status==='fulfilled'?JSON.stringify(health.value,null,2):'Local knowledge health unavailable. Public observation panels remain independently available.';
  if(docs.status==='fulfilled'){
   const list=$('knowledge-documents');list.replaceChildren();
   for(const d of docs.value.documents||[]){const row=make('label'),input=make('input');input.type='checkbox';input.value=d.document_id;input.name='knowledge-document';row.append(input,make('span',`${d.source} · version ${d.version} · ${d.bytes} bytes · SHA-256 ${d.sha256}`));list.append(row);}
   if(!list.children.length)list.append(make('p','No documents indexed. Upload a supported document.'));
  }else $('knowledge-documents').textContent='Document catalogue unavailable; press Refresh knowledge to recover.';
  state(health.status==='fulfilled'&&docs.status==='fulfilled'?'Private knowledge connected. Select source documents to narrow retrieval; no selection searches your current document versions.':'Some local knowledge functions are unavailable. Retry refresh.',health.status==='rejected'||docs.status==='rejected');
 }
 function render(result){
  lastAnswer=result;const output=$('knowledge-answer');output.replaceChildren();
  output.append(make('p',`Result: ${result.status} · ${result.model||result.embedding_model||'local retrieval'}`));
  if(result.answer)output.append(make('p',result.answer));
  if(result.disclosure)output.append(make('p',result.disclosure));
  if(result.diagnostics)output.append(make('pre',JSON.stringify(result.diagnostics,null,2)));
  for(const r of result.results||[]){const d=make('details');d.append(make('summary',`${r.citation} ${r.source} · page ${r.page??'not applicable'} · similarity ${Number.isFinite(r.similarity)?r.similarity.toFixed(3):'observation'}`),make('pre',r.passage),make('small',`Passage SHA-256: ${r.sha256} · document version ${r.document_version??'observation'} · untrusted reference data`));output.append(d);}
  if(!result.results?.length)output.append(make('p','No relevant source evidence was retrieved. No unsupported answer is claimed.'));
 }
 $('knowledge-refresh').addEventListener('click',()=>action(load));
 $('knowledge-upload').addEventListener('click',()=>action(async current=>{
  const file=$('knowledge-file').files?.[0];if(!file||! /\.(pdf|docx|txt|md)$/i.test(file.name)||file.size>8*1024*1024)throw new Error('Choose a PDF, DOCX, TXT or Markdown file up to 8 MiB.');
  state('Extracting, embedding and indexing your document…');const result=await api('ingest',{raw:await file.arrayBuffer(),filename:file.name,timeout:110000});if(current!==epoch)return;
  await load(current);state(`${result.status}: ${result.duplicate_prevented?'The identical document was already indexed; no duplicate was added.':`${result.added_chunks} new chunks indexed.`}`);
 }));
 $('knowledge-reindex').addEventListener('click',()=>action(async current=>{state('Reindexing preserved documents with the existing cached embedding model…');const result=await api('reindex',{body:{},timeout:110000});if(current!==epoch)return;await load(current);state(`${result.status}: ${result.chunks} chunks. Previous index generations remain recoverable.`);}));
 function question(){const value=$('knowledge-question').value.trim();if(!value||value.length>4096)throw new Error('Enter a question of up to 4096 characters.');const selected=[...document.querySelectorAll('input[name="knowledge-document"]:checked')].map(x=>x.value);return {question:value,top_k:3,...(selected.length?{document_ids:selected}:{})};}
 $('knowledge-retrieve').addEventListener('click',()=>action(async current=>{state('Retrieving document evidence…');const result=await api('retrieve',{body:question(),timeout:110000});if(current===epoch){render(result);state('Retrieval complete. Inspect source passages and scores below.');}}));
 $('knowledge-ask').addEventListener('click',()=>action(async current=>{state('Retrieving evidence and generating an answer with local Qwen2.5:7b…');const result=await api('answer',{body:{...question(),include_observations:$('knowledge-observations').checked},timeout:180000});if(current===epoch){render(result);state(result.citations_valid?'Local answer returned with valid retrieved-source citation identifiers. Inspect its supporting passages.':'Generation completed without validated citations or sufficient evidence; see the explicit result status.',!result.citations_valid);}}));
 window.addEventListener('orqevia-session',e=>{const changed=session?.clientId!==e.detail?.clientId||session?.role!==e.detail?.role;session=e.detail;panel.hidden=session?.role!=='OWNER';if(changed){epoch++;lastAnswer=null;$('knowledge-answer').replaceChildren();$('knowledge-documents').replaceChildren();$('knowledge-question').value='';}controls();if(session?.role==='OWNER'&&changed)void action(load);});
 window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
}
