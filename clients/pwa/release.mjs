const RELEASE='orqevia-shell-v43';

// Shell coherence is separate from API health, authorization and data freshness.
// No session, enrollment, TaskStore reference or plaintext draft is cleared here.
if((location.protocol==='https:'||['localhost','127.0.0.1'].includes(location.hostname))&&'serviceWorker'in navigator){
  let registration=null,updating=null,pendingRelease=null,reloading=false;
  const attempted=new Set(),edits=new Map();
  const version=/^orqevia-shell-v\d+$/;
  const snapshot=node=>node.type==='file'?Array.from(node.files||[],file=>`${file.name}:${file.size}:${file.lastModified}`).join('|'):
    ['checkbox','radio'].includes(node.type)?String(node.checked):String(node.value??'');
  const input=node=>node&&['INPUT','TEXTAREA','SELECT'].includes(node.tagName)&&!['button','submit','hidden'].includes(node.type);
  const remember=event=>{if(input(event.target)&&!edits.has(event.target))edits.set(event.target,snapshot(event.target));};
  document.addEventListener('focusin',remember,true);
  document.addEventListener('beforeinput',remember,true);
  const changed=event=>{
    if(input(event.target)&&!edits.has(event.target)){
      const node=event.target;
      edits.set(node,['checkbox','radio'].includes(node.type)?String(node.defaultChecked):String(node.defaultValue??''));
    }
  };
  document.addEventListener('input',changed,true);
  document.addEventListener('change',changed,true);

  function announce(state,workerRelease=null,reason=null){
    const detail={state,pageRelease:RELEASE,workerRelease,online:navigator.onLine!==false,updateAvailable:!!workerRelease&&workerRelease!==RELEASE,reason};
    globalThis.__ORQEVIA_SHELL_STATE__=detail;
    document.documentElement.dataset.orqeviaShellRelease=RELEASE;
    document.documentElement.dataset.orqeviaShellState=state;
    if(workerRelease)document.documentElement.dataset.orqeviaWorkerRelease=workerRelease;
    window.dispatchEvent(new CustomEvent('orqevia-shell-state',{detail}));
  }

  function dirty(){
    for(const [node,original] of edits){
      if(!node.isConnected){edits.delete(node);continue;}
      if(['INPUT','TEXTAREA'].includes(node.tagName)&&!['file','checkbox','radio'].includes(node.type)&&!String(node.value??'').trim())continue;
      if(snapshot(node)!==original)return true;
    }
    return !!document.querySelector('[aria-busy="true"],[data-orqevia-update-busy="true"]');
  }

  function notice(reason){
    let panel=document.getElementById('shell-update-notice');
    if(!panel){
      panel=document.createElement('aside');panel.id='shell-update-notice';panel.className='notice';panel.setAttribute('role','status');
      const text=document.createElement('p');text.id='shell-update-text';
      const button=document.createElement('button');button.type='button';button.textContent='Reload when ready';
      button.addEventListener('click',()=>void reloadPending(true));panel.append(text,button);document.body.append(panel);
    }
    document.getElementById('shell-update-text').textContent=reason==='offline'?'A workspace update is ready. Reconnect before reloading.':
      reason==='save_failed'?'The update is ready, but current work could not be saved. Keep this workspace open and retry.':
      'A workspace update is ready. Finish your current input or active work before reloading.';
  }

  async function reloadPending(manual=false){
    const target=pendingRelease;
    if(!target||reloading)return;
    if(document.hidden||navigator.onLine===false||dirty()){
      announce(navigator.onLine===false?'offline':'update-ready',target,'work_open');notice(navigator.onLine===false?'offline':'work_open');return;
    }
    const waits=[];
    // The application can defer active work or wait for its existing TaskStore
    // transaction. Plaintext inputs are never persisted by this module.
    const event=new CustomEvent('orqevia-before-shell-update',{cancelable:true,detail:{fromRelease:RELEASE,toRelease:target,waitUntil(promise){waits.push(Promise.resolve(promise));}}});
    if(!window.dispatchEvent(event)){announce('update-ready',target,'work_open');notice('work_open');return;}
    reloading=true;
    try{
      await Promise.all(waits);
      if(document.hidden||dirty()||navigator.onLine===false){reloading=false;announce('update-ready',target,'work_open');notice('work_open');return;}
      if(globalThis.__ORQEVIA_TEST_SUPPRESS_CONTROLLER_RELOAD__===true){reloading=false;announce('update-ready',target,'test_reload_suppressed');return;}
      const key=`${target}:controller-reload`;
      let stored=false;try{stored=!!sessionStorage.getItem(key);}catch{/* Storage can be unavailable. */}
      if(!manual&&(stored||attempted.has(target))){reloading=false;announce('update-ready',target,'reload_already_attempted');notice('work_open');return;}
      attempted.add(target);try{sessionStorage.setItem(key,'1');}catch{/* Never clear other storage. */}
      announce('reloading',target);location.reload();
    }catch{reloading=false;announce('update-ready',target,'save_failed');notice('save_failed');}
  }

  function workerRelease(worker){
    if(!worker)return Promise.resolve(null);
    return new Promise(resolve=>{
      const channel=new MessageChannel();
      const finish=value=>{clearTimeout(timer);channel.port1.close();resolve(value);};
      const timer=setTimeout(()=>finish(null),1500);
      channel.port1.onmessage=event=>finish(event.data?.type==='ORQEVIA_SHELL_RELEASE'&&version.test(event.data.release)?event.data.release:null);
      channel.port1.start?.();
      try{worker.postMessage({type:'ORQEVIA_SHELL_RELEASE'},[channel.port2]);}catch{finish(null);}
    });
  }

  async function coherence(){
    const worker=navigator.serviceWorker.controller;
    const current=await workerRelease(worker);
    if(worker!==navigator.serviceWorker.controller)return;
    if(!current){announce(navigator.onLine===false?'offline':'unknown',null,'worker_release_unavailable');return;}
    if(current===RELEASE){pendingRelease=null;announce(navigator.onLine===false?'offline':'current',current);document.getElementById('shell-update-notice')?.remove();return;}
    pendingRelease=current;announce('update-ready',current);await reloadPending();
  }

  async function check(){
    if(updating)return updating;
    updating=(async()=>{
      let failed=false;
      if(navigator.onLine!==false){try{await registration?.update();}catch{failed=true;}}
      await coherence();
      if(failed&&!reloading)announce('unknown',globalThis.__ORQEVIA_SHELL_STATE__?.workerRelease||null,'update_check_unavailable');
    })().finally(()=>{updating=null;});
    return updating;
  }

  navigator.serviceWorker.addEventListener('controllerchange',()=>void coherence());
  navigator.serviceWorker.addEventListener('message',event=>{
    if(event.source===navigator.serviceWorker.controller&&event.data?.type==='ORQEVIA_SHELL_OFFLINE')announce('offline',event.data.release,'cached_shell');
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void check();});
  window.addEventListener('pageshow',event=>{if(event.persisted)void check();});
  window.addEventListener('online',()=>void check());
  window.addEventListener('offline',()=>announce('offline',globalThis.__ORQEVIA_SHELL_STATE__?.workerRelease||null));
  window.addEventListener('orqevia-shell-update-safe',()=>{if(pendingRelease)void reloadPending();});
  announce(navigator.onLine===false?'offline':'checking');
  navigator.serviceWorker.register('/pwa/sw.js',{scope:'/pwa/',updateViaCache:'none'})
    .then(value=>{registration=value;return check();}).catch(()=>announce(navigator.onLine===false?'offline':'unknown',null,'worker_registration_unavailable'));
}
