// Native Academy evidence, using the current same-origin Owner session.
const panel=document.getElementById('coaching-view');
if(panel){
  const box=document.createElement('section');box.className='dashboard-card';box.id='academy-program';
  const title=document.createElement('h2');title.textContent='Probability learning';
  const state=document.createElement('p');state.id='academy-state';state.setAttribute('role','status');state.textContent='Open Coaching to load the curriculum.';
  const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Refresh learning';
  const select=document.createElement('select');select.setAttribute('aria-label','Agent learning record');
  const retained=document.createElement('p');retained.id='academy-retention';
  const lessons=document.createElement('div');lessons.id='academy-lessons';
  box.append(title,state,refresh,select,retained,lessons);panel.append(box);
  let epoch=0,active=null,authenticated=false;
  async function read(path,signal){const response=await fetch('/pwa/api/academy/'+path,{credentials:'same-origin',cache:'no-store',signal});if(!response.ok)throw new Error('Unavailable');return response.json();}
  async function loadMethods(){
    if(!select.value||!authenticated)return;
    const current=epoch,agent=select.value;
    retained.textContent='Loading retained methods…';
    try{const record=await read('agents/'+encodeURIComponent(agent));if(current!==epoch||agent!==select.value)return;
      retained.textContent=record.retained_methods.length?`${record.retained_methods.length} methods retained after an independent unseen assessment. Source ${record.retained_methods[0].source_revision.slice(0,7)}. Educational evidence grants no execution authority.`:'No independently passed, retained probability methods recorded for this agent yet.';
    }catch{if(current===epoch)retained.textContent=navigator.onLine?'Learning record unavailable. Refresh to retry.':'Offline. Reconnect and refresh.';}
  }
  async function load(){
    if(!authenticated||active)return;
    const controller=new AbortController(),current=epoch;active=controller;
    state.textContent='Loading native curriculum…';
    try{const value=await read('probability',controller.signal);if(current!==epoch||!authenticated)return;
      lessons.replaceChildren();for(const item of value.lessons){const detail=document.createElement('details'),summary=document.createElement('summary'),method=document.createElement('p');summary.textContent=item.title;method.textContent=item.method;detail.append(summary,method);lessons.append(detail);}
      const previous=select.value;select.replaceChildren();for(const agent of value.agents){const option=document.createElement('option');option.value=agent;option.textContent=agent.toUpperCase();select.append(option);}if(value.agents.includes(previous))select.value=previous;
      state.textContent=`${value.lessons.length} topics · ${value.agents.length} agent learning paths · practice and unseen assessment recorded separately. ${value.version}.`;
      await loadMethods();
    }catch{if(current===epoch&&!controller.signal.aborted)state.textContent=navigator.onLine?'Curriculum unavailable. Refresh to retry.':'Offline. Reconnect and refresh.';}
    finally{if(active===controller)active=null;}
  }
  refresh.addEventListener('click',()=>void load());select.addEventListener('change',()=>void loadMethods());
  window.addEventListener('orqevia-view',event=>{if(event.detail?.name==='coaching')void load();});
  window.addEventListener('orqevia-session',event=>{epoch++;active?.abort();active=null;authenticated=Boolean(event.detail?.clientId);lessons.replaceChildren();select.replaceChildren();retained.textContent='';state.textContent=authenticated?'Open Coaching to load the curriculum.':'Restore your trusted connection.';if(authenticated&&!panel.classList.contains('hidden'))void load();});
  window.addEventListener('offline',()=>{epoch++;active?.abort();active=null;state.textContent='Offline. Reconnect and refresh.';});
  window.addEventListener('online',()=>{if(!panel.classList.contains('hidden'))void load();});
}
