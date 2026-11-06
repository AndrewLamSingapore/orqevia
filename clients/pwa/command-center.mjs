// Native Command Center. Metadata comes from the authenticated service; no
// credentials, wallet authority or container-control channel exists here.
import {canonicalView} from './core.mjs';
export {canonicalView, VIEWS} from './core.mjs';
export function safeCapability(value) {
  return value && typeof value.id === 'string' && typeof value.name === 'string' && typeof value.status === 'string';
}

if (typeof document !== 'undefined' && document.getElementById('depot-view')) {
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => {const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(cls)node.className=cls;return node;};
  let session=null, epoch=0, pending=null, experimentPending=null, historyPending=null, lensPending=null, active=canonicalView(new URL(location.href).searchParams.get('view'));
  const relevant = () => ['assets','wallets'].includes(active);
  function controls() {const owner=session?.role==='OWNER';if($('evolution-run'))$('evolution-run').disabled=!owner||Boolean(experimentPending);for(const id of ['lens-read','lens-record','lens-inspect'])if($(id))$(id).disabled=!owner||Boolean(lensPending);}
  function clear() { epoch++;pending?.abort();pending=null;experimentPending?.abort();experimentPending=null;lensPending?.abort();lensPending=null;$('depot-capabilities').replaceChildren();$('wallets-content').replaceChildren();$('evolution-result')?.replaceChildren();historyPending?.abort();historyPending=null;$('evolution-history')?.replaceChildren();$('lens-result')?.replaceChildren();if($('lens-task'))$('lens-task').value='';if($('evolution-state'))$('evolution-state').textContent='No experiment result is loaded for this connection.';if($('lens-state'))$('lens-state').textContent='Open an owned task to inspect or record its evidence.'; }
  function fields(parent, entries) {
    const dl=make('dl');
    for(const [label,value] of entries) { dl.append(make('dt',label),make('dd',value??'Not reported')); }
    parent.append(dl);
  }
  function render(value) {
    if(value?.schema!=='orqevia.capability-depot.v1')throw new Error('The catalog returned an unsupported response.');
    const root=$('depot-capabilities');root.replaceChildren();
    for(const item of (Array.isArray(value.capabilities)?value.capabilities:[]).filter(safeCapability)) {
      const card=make('section',undefined,'oq-module'), meta=make('div',undefined,'depot-meta');
      meta.append(make('span',item.status,'oq-tag'),make('span',item.offline===true?'Local / offline-capable':item.offline===false?'Connectivity required':'Locality not reported','oq-tag'));
      card.append(meta,make('h3',item.name));
      if(item.description)card.append(make('p',item.description));
      const deps=Array.isArray(item.dependencies)?item.dependencies.map(x=>typeof x==='string'?x:x?.name||x?.id||'Unspecified').join(', '):'Not reported';
      fields(card,[['Kind',item.kind],['Version',item.version],['Availability',item.available===true?'Available':item.available===false?'Unavailable':'Not reported'],['Dependencies',deps||'None declared']]);
      if(item.resources && typeof item.resources==='object') {
        const details=make('details');details.append(make('summary','Resource requirements'),make('pre',JSON.stringify(item.resources,null,2)));card.append(details);
      }
      if(Array.isArray(item.operations)&&item.operations.length)card.append(make('p','Supported operations: '+item.operations.map(x=>typeof x==='string'?x:x?.name||x?.id||'Unspecified').join(', ')));
      const destinations={'activity-pockets':'workspace','local-inference':'missions','local-knowledge':'knowledge','agent-capabilities':'agents','predictive-intelligence':'console','model-efficiency':'console','durable-memory':'workspace','offline-continuity':'live-systems',knowledge:'knowledge', memory:'workspace', agents:'agents', inference:'intelligence', models:'intelligence', fabric:'console', academy:'evolution', resource_guardian:'live-systems'};
      const destination=destinations[item.id];
      if(destination){const button=make('button','Open capability');button.type='button';button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('orqevia-open-view',{detail:{name:destination}})));card.append(button);}
      root.append(card);
    }
    if(!root.children.length)root.append(make('p','The service returned no installed capability records.'));
    $('depot-state').textContent=`${root.children.length} catalog entries observed. Installations, updates and removal use the existing scoped host release process; unavailable operations are not simulated.`;
    const wallet=value.wallet||{},walletRoot=$('wallets-content');walletRoot.replaceChildren();
    const card=make('section',undefined,'oq-module');card.append(make('span',wallet.status||'UNKNOWN','oq-tag'),make('h3','Financial capability'));
    fields(card,[['Transaction signing',wallet.signing_available===true?'Available':wallet.signing_available===false?'Not available':'Unknown'],['Autonomous spending',wallet.spend_enabled===true?'Enabled within existing permissions':wallet.spend_enabled===false?'Disabled':'Unknown']]);
    card.append(make('p',wallet.scope||'No runtime financial evidence was supplied. Compute accounting is not proof of funds.'));walletRoot.append(card);
    if(Array.isArray(wallet.wallets))for(const item of wallet.wallets){const entry=make('section',undefined,'oq-module');entry.append(make('h3',item.name||item.id||'Wallet'),make('span',item.status||'UNKNOWN','oq-tag'));fields(entry,[['Type',item.type],['Owner',item.owner],['Network',item.network],['Currency',item.currency]]);walletRoot.append(entry);}
    $('wallets-state').textContent='Read-only inventory. No transaction, signature, funding or account-connection action has been performed.';
  }
  async function load() {
    if(!relevant())return;
    const state=active==='assets'?$('depot-state'):$('wallets-state');
    if(!session){state.textContent='Restore your connection to inspect private capability metadata.';return;}
    if(session.role!=='OWNER'){state.textContent='This private inventory requires the bound owner account.';return;}
    if(!navigator.onLine){state.textContent='Offline. Private inventory was cleared. Local model and task services have separate availability.';return;}
    pending?.abort();const controller=new AbortController(),generation=epoch,view=active;pending=controller;
    const timer=setTimeout(()=>controller.abort(),15000);state.textContent='Reading the installed capability inventory…';
    try {
      const response=await fetch('/api/orqevia/depot',{credentials:'same-origin',cache:'no-store',redirect:'error',headers:{Accept:'application/json','X-ORQEVIA-PWA':'1'},signal:controller.signal});
      if(!response.ok)throw new Error(response.status===401?'Restore your connection.':response.status===403?'Owner access is required.':`Catalog unavailable (${response.status}).`);
      const value=await response.json();if(generation===epoch&&active===view)render(value);
    } catch(error) {if(generation===epoch&&active===view)state.textContent=controller.signal.aborted?'The catalog request timed out. Refresh to retry.':error.message;}
    finally {clearTimeout(timer);if(pending===controller)pending=null;}
  }
  async function loadHistory() {
    if(active!=='evolution'||session?.role!=='OWNER'||!navigator.onLine)return;
    historyPending?.abort();const controller=new AbortController(),generation=epoch;historyPending=controller;
    const timer=setTimeout(()=>controller.abort(),15000);$('evolution-history-state').textContent='Reading saved experiment evidence?';
    try {
      const response=await fetch('/api/orqevia/evolution/experiments',{credentials:'same-origin',cache:'no-store',redirect:'error',headers:{Accept:'application/json','X-ORQEVIA-PWA':'1'},signal:controller.signal});
      if(!response.ok)throw new Error(`Saved runs unavailable (${response.status}).`);
      const value=await response.json();if(generation!==epoch||controller.signal.aborted)return;
      $('evolution-history').replaceChildren();for(const record of Array.isArray(value.experiments)?value.experiments:[]){const details=make('details');details.append(make('summary',`${record.run_id||record.experiment_id||'Saved experiment'} ? ${record.observed_at_utc||'time not reported'}`),make('pre',JSON.stringify(record,null,2)));$('evolution-history').append(details);}
      $('evolution-history-state').textContent=$('evolution-history').children.length?'Saved evidence loaded. Expand a run to inspect its recorded scope.':'No saved experiment records were returned.';
    } catch(error) {if(generation===epoch)$('evolution-history-state').textContent=controller.signal.aborted?'Saved-run request timed out. Refresh to retry.':error.message;}
    finally {clearTimeout(timer);if(historyPending===controller)historyPending=null;}
  }
  $('evolution-refresh')?.addEventListener('click',()=>void loadHistory());
  window.addEventListener('orqevia-before-shell-update',event=>{if(experimentPending||lensPending)event.preventDefault();});
  $('depot-refresh').addEventListener('click',()=>void load());
  $('settings-connection').addEventListener('click',()=>$('account-button').click());
  $('evolution-run')?.addEventListener('click',async()=>{
    if(session?.role!=='OWNER'||experimentPending||!navigator.onLine)return;
    const generation=epoch,controller=new AbortController();experimentPending=controller;controls();$('evolution-result').replaceChildren();$('evolution-state').textContent='Running the fixed baseline and held-out comparison…';
    const timer=setTimeout(()=>controller.abort(),30000);
    try {
      const response=await fetch('/api/orqevia/evolution/experiment',{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'Content-Type':'application/json','X-ORQEVIA-PWA':'1'},body:'{}',signal:controller.signal});
      if(!response.ok)throw new Error(`Experiment unavailable (${response.status}).`);
      const value=await response.json();if(generation!==epoch)return;
      $('evolution-result').append(make('pre',JSON.stringify(value,null,2)));
      $('evolution-state').textContent='Comparison returned. Inspect held-out outcomes and resource metrics below; this fixed experiment does not change production routing or permissions.';void loadHistory();
    } catch(error) {if(generation===epoch)$('evolution-state').textContent=controller.signal.aborted?'The experiment request timed out. No result is claimed.':error.message;}
    finally {clearTimeout(timer);if(experimentPending===controller)experimentPending=null;controls();}
  });
  async function lens(action) {
    if(session?.role!=='OWNER'||lensPending||!navigator.onLine)return;
    const id=$('lens-task').value.trim();if(!/^[a-zA-Z0-9_.:-]{1,128}$/.test(id)){$('lens-state').textContent='Enter the existing task identifier.';return;}
    const generation=epoch,controller=new AbortController();lensPending=controller;controls();$('lens-result').replaceChildren();$('lens-state').textContent=action==='record'?'Recording evidence from the existing owned task…':'Reading the owned task evidence…';
    const timer=setTimeout(()=>controller.abort(),15000);
    try {
      const path=action==='read'?'objectives/':'evidence/from-objective/';
      const response=await fetch('/interface/v1/lens/'+path+encodeURIComponent(id),{method:action==='record'?'POST':'GET',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'Content-Type':'application/json','X-ORQEVIA-PWA':'1'},...(action==='record'?{body:'{}'}:{}),signal:controller.signal});
      if(!response.ok)throw new Error(response.status===404?'No owned task or recorded evidence was found.':`Evidence service unavailable (${response.status}).`);
      const value=await response.json();if(generation!==epoch)return;
      $('lens-result').append(make('pre',JSON.stringify(value,null,2)));
      $('lens-state').textContent=action==='record'?'Evidence recording returned. Inspect integrity and source status below.':'The stored source record is shown below. Verification status is supplied by the service.';
    } catch(error) {if(generation===epoch)$('lens-state').textContent=controller.signal.aborted?'The evidence request timed out. Retry to inspect the persisted state.':error.message;}
    finally {clearTimeout(timer);if(lensPending===controller)lensPending=null;controls();}
  }
  for(const [id,action] of [['lens-read','read'],['lens-record','record'],['lens-inspect','inspect']])$(id)?.addEventListener('click',()=>void lens(action));
  $('command-objective-form').addEventListener('submit',event=>{
    event.preventDefault();const input=$('command-objective'),text=input.value.trim();if(!text)return;
    window.dispatchEvent(new CustomEvent('orqevia-objective-draft',{detail:{text}}));
    window.dispatchEvent(new CustomEvent('orqevia-open-view',{detail:{name:'missions'}}));
    input.value='';$('objective')?.focus();
  });
  window.addEventListener('orqevia-view',event=>{active=canonicalView(event.detail?.name);pending?.abort();pending=null;if(relevant())void load();if(active==='evolution')void loadHistory();});
  window.addEventListener('orqevia-session',event=>{const next=event.detail;if(next?.clientId!==session?.clientId||next?.role!==session?.role||next?.generation!==session?.generation)clear();session=next;controls();void load();void loadHistory();});
  window.addEventListener('offline',()=>{clear();if(relevant())void load();if(active==='evolution')void loadHistory();});
  window.addEventListener('online',()=>void load());
  controls();
  window.dispatchEvent(new CustomEvent('orqevia-dashboard-ready'));
}
