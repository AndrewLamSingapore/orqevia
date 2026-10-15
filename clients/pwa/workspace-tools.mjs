// Recovered capabilities use the same authenticated application service.
if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id),root=$('workflow-module');
 const pages=new Set(['ideas','architecture','build','test','deploy','present']);
 let active=new URL(location.href).searchParams.get('view')||'home',session=null,generation=0;
 const make=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 async function api(path,body){const r=await fetch('/api/orqevia/knowledge/'+path,{method:body===undefined?'GET':'POST',body:body===undefined?undefined:JSON.stringify(body),headers:{'Content-Type':'application/json','X-JARVIS-PWA':'1'},credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(path==='validate'?110000:20000)});if(!r.ok)throw new Error(`Workspace service returned ${r.status}. Retry when available.`);return r.json();}
 function output(parent,title,value){const d=make('details');d.append(make('summary',title),make('pre',JSON.stringify(value,null,2)));parent.append(d);return d;}
 function button(parent,title,operation){const b=make('button',title);b.type='button';b.addEventListener('click',async()=>{if(b.disabled)return;b.disabled=true;const epoch=generation;try{await operation(epoch);}catch(e){if(epoch===generation)$('workflow-state').textContent=e.message;}finally{b.disabled=false;}});parent.append(b);return b;}
 async function render(){
  const epoch=++generation;root.replaceChildren();if(!pages.has(active))return;
  $('capability-description').textContent={ideas:'Persisted owner drafts; use a draft in the existing owned objective workflow.',architecture:'Observed shared services and explicit authority boundaries.',build:'Recovered construction engine: generate reviewable candidate files without executing or deploying them.',test:'Run the fixed isolated document/index regression suite. Fixture checks are separate from real-model and corpus acceptance.',deploy:'Measured release and rollback metadata. Deployment changes remain in the established ABEX release workflow.',present:'Inspect and export an operational report from the actual shared services.'}[active];
  const status=make('p','Loading workspace capability…');status.id='workflow-state';root.append(status);
  if(session?.role!=='OWNER'){status.textContent='This capability requires the bound owner account. Your existing member functionality is unchanged.';return;}
  try{
   if(active==='ideas'){
    const list=make('div'),form=make('form'),title=make('input'),body=make('textarea');title.required=true;title.maxLength=200;title.placeholder='Idea title';title.setAttribute('aria-label','Idea title');body.maxLength=8000;body.placeholder='Describe the idea';body.setAttribute('aria-label','Idea description');const submit=make('button','Save idea');submit.type='submit';form.append(title,body,submit);root.append(form,list);
    function draw(value){list.replaceChildren();for(const idea of value.ideas||[]){const d=output(list,`${idea.title} · ${idea.created_at}`,idea);button(d,'Use as objective',async()=>window.dispatchEvent(new CustomEvent('orqevia-objective-draft',{detail:{text:idea.title+'\n\n'+idea.body}})));}if(!list.children.length)list.append(make('p','No saved ideas yet.'));}
    const initial=await api('ideas');if(epoch!==generation)return;draw(initial);status.textContent='Ideas loaded from persistent owner storage.';
    form.addEventListener('submit',async e=>{e.preventDefault();submit.disabled=true;try{const value=await api('ideas',{title:title.value,body:body.value});if(epoch!==generation)return;draw(value);title.value='';body.value='';status.textContent='Idea saved.';}catch(err){if(epoch===generation)status.textContent=err.message;}finally{submit.disabled=false;}});
   }else if(active==='build'){
    const name=make('input'),description=make('textarea'),result=make('div');name.placeholder='Project name';name.setAttribute('aria-label','Project name');name.maxLength=100;description.placeholder='Project description';description.setAttribute('aria-label','Project description');description.maxLength=2000;root.append(name,description);
    button(root,'Generate project candidate',async current=>{status.textContent='Generating candidate files…';const value=await api('scaffold',{kind:'project',name:name.value,description:description.value});if(current!==generation)return;result.replaceChildren();output(result,'Candidate provenance',Object.fromEntries(Object.entries(value).filter(([key])=>key!=='files')));for(const [path,text] of Object.entries(value.files||{})){const d=make('details');d.append(make('summary',path),make('pre',text));result.append(d);}status.textContent='Candidate generated. Files were not executed or deployed.';});root.append(result);status.textContent='Construction engine available. Enter a project specification.';
   }else{
    const state=await api('workspace');if(epoch!==generation)return;output(root,'Observed workspace capabilities',state);status.textContent='Measured capability metadata loaded; unavailable measurements remain explicit.';
    if(active==='architecture'||active==='present'){const health=await api('health');if(epoch!==generation)return;output(root,'Document retrieval and local model service',health);}
    if(active==='test')button(root,'Run local pipeline regression checks',async current=>{status.textContent='Running fixed tests in a new isolated fixture directory…';const result=await api('validate',{});if(current!==generation)return;output(root,'Actual test execution receipt',result);status.textContent=`Regression execution: ${result.status}. These checks do not establish production corpus correctness.`;});
    if(active==='present')button(root,'Export operational report',async()=>{const report=await api('workspace');const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const link=make('a');link.href=url;link.download='orqevia-operational-report.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);});
   }
  }catch(e){if(epoch===generation)status.textContent=e.message;}
 }
 window.addEventListener('orqevia-view',e=>{active=e.detail.name;queueMicrotask(()=>void render());});
 window.addEventListener('orqevia-session',e=>{const changed=session?.clientId!==e.detail?.clientId||session?.role!==e.detail?.role;session=e.detail;if(changed)void render();});
 window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));void render();
}
