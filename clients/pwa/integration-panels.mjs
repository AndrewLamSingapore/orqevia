// Observation snapshots are read-only here. Collection and NLI belong to Intelligence.
export function mountIntegrationPanels(section,{request,owner,readOnly,node,record,source,isCurrent}){
 const controller=new AbortController();let failed=true,running=false,stopped=false,timer,semanticTouched=false;
 const stop=()=>{if(stopped)return;stopped=true;controller.abort();clearInterval(timer);for(const event of ['orqevia-session','orqevia-view','offline'])window.removeEventListener?.(event,stop);};
 for(const event of ['orqevia-session','orqevia-view','offline'])window.addEventListener(event,stop);
 const current=()=>!stopped&&isCurrent()&&section.isConnected!==false;
 function render(value){
  semanticTouched=false;
  section.replaceChildren(node('h3','Integration availability'));
  for(const provider of value.providers||[]){
   const detail=record(section,`${provider.provider} · ${provider.status} · ${provider.records?.length||0} records`,provider);
   detail.prepend?.(node('p',provider.coverage));
   source(detail,'Provider source',provider.source_url);
   section.append(node('p',`${provider.provider}: ${provider.status}. Collected ${provider.collected_at||'not yet observed'}${provider.error?' · '+provider.error:''}. ${provider.coverage}`));
  }
  const semantic=value.semantic_entailment||{status:'UNAVAILABLE'};
  section.append(node('p',`Semantic entailment: ${semantic.status}. Classifies a claim relative to its premise. Formal proof and premise authenticity are not established.`));
  if(semantic.qualification?.status==='BOUNDED_SYNTHETIC_PASS')section.append(node('p',`Bounded qualification: ${semantic.qualification.top_label_matches}/${semantic.qualification.cases} synthetic label matches, ${semantic.qualification.confident_false_entailments} confident false entailments. ${semantic.qualification.known_failures}.`));
  record(section,'Semantic model provenance',semantic);
  section.append(node('p','Public source snapshots retain their collection time, provider timestamp and SHA-256 evidence. Collection uses a 15-minute minimum interval. Vessel AIS requires a configured provider.'));
  if(readOnly)section.append(node('p','GOD’S EYE reads these observations. Collection and analysis controls are in Intelligence.'));
  if(!readOnly){
   const refresh=node('button','Refresh external observations');refresh.type='button';refresh.id='external-observations-refresh';
   refresh.addEventListener('click',async()=>{refresh.disabled=true;try{const result=await request('/interface/v1/osip/observations/refresh',{body:{},timeout:20000,signal:controller.signal});if(!current())return;render(result);section.append(node('p',`Collection: ${result.collection_status}. Provider statuses above show the actual outcome; minimum polling windows remain enforced.`));}catch(e){if(current())section.append(node('p',`Collection unavailable: ${e.message}. Previous observations remain preserved.`));}finally{refresh.disabled=false;}});section.append(refresh);
   if(semantic.status==='LOADED'&&semantic.qualification?.status==='BOUNDED_SYNTHETIC_PASS'){
    const form=node('form'),premise=node('textarea'),claim=node('textarea'),submit=node('button','Check semantic entailment'),out=node('div');
    premise.required=true;premise.maxLength=5000;premise.id='semantic-premise';claim.required=true;claim.maxLength=2000;claim.id='semantic-claim';submit.type='submit';
    for(const input of [premise,claim])input.addEventListener('input',()=>{semanticTouched=true;});
    for(const [title,input] of [['Evidence premise',premise],['Claim to assess',claim]]){const label=node('label',title);label.htmlFor=input.id;form.append(label,input);}
    form.append(submit);section.append(form,out);
    form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;out.replaceChildren(node('p','Assessing the premise and claim locally…'));try{const result=await request('/api/orqevia/knowledge/semantic/assess',{body:{premise:premise.value,claim:claim.value},timeout:20000,signal:controller.signal});if(!current())return;out.replaceChildren(node('p',`Semantic assessment: ${result.assessment}. ${result.disclosure}`));record(out,'Inspect actual model result and provenance',result);}catch(e){if(current())out.replaceChildren(node('p',`Semantic assessment unavailable: ${e.message}.`));}finally{submit.disabled=false;}});
   }
  }
  // Retained, timestamped records (including STALE snapshots) stay stable until
  // explicit Refresh. Only unavailable empty panels need automatic recovery.
  failed=(value.providers||[]).some(p=>p.status==='UNAVAILABLE'&&!p.records?.length)||semantic.status!=='LOADED';
 }
 async function load(){
  if(!current()||running)return;if(!owner){section.replaceChildren(node('h3','Integration availability'),node('p','The bound owner account is required for the optional provider and semantic projections.'));failed=false;return;}
  running=true;
  try{const value=await request('/interface/v1/osip/observations',{timeout:5000,signal:controller.signal});if(current())render(value);}
  catch(e){if(current())section.replaceChildren(node('h3','Integration availability'),node('p',`Optional provider projection unavailable: ${e.message}. Existing geospatial and operational observations remain available.`));}
  finally{running=false;}
 }
 timer=setInterval(()=>{if(!current()){stop();return;}if(failed&&!semanticTouched&&!document.hidden&&!section.contains?.(document.activeElement))void load();},30000);
 section.append(node('p','Loading observed integration availability…'));void load();return stop;
}
