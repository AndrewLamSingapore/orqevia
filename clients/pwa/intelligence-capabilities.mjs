// Optional services share the trusted HTTPS connection; no action authority.
const create=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
const anchor=document.getElementById('fabric-console');
if(anchor){
 const panel=create('section');panel.className='oq-module';panel.id='intelligence-capabilities';
 const state=create('p','Check availability to read the independent services.');state.setAttribute('role','status');state.setAttribute('aria-live','polite');
 const controls=create('div');controls.className='oq-approval-actions';
 const label=create('label','Starting state '),start=create('select');start.id='prediction-start';
 for(const name of ['queued','held','running','completed','failed','cancelled']){const option=create('option',name);option.value=name;start.append(option);}label.append(start);
 const horizonLabel=create('label','State transitions '),horizon=create('input');horizon.type='number';horizon.min='0';horizon.step='1';horizon.value='2';horizon.id='prediction-horizon';horizonLabel.append(horizon);
 const output=create('div');output.id='intelligence-capability-result';output.style.overflowWrap='anywhere';
 const details=create('details'),summary=create('summary','Evidence and diagnostics'),evidence=create('pre');details.append(summary,evidence);
 panel.append(create('h2','Forecasting and model efficiency'),create('p','Forecasts are advisory. Scenario outcomes are simulations. Optimization evidence does not replace the current model.'),state,label,horizonLabel,controls,output,details);anchor.after(panel);
 let pending=null,session=null;
 async function api(path,body,signal){
  const response=await fetch('/interface/v1/collective/intelligence/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-ORQEVIA-PWA':'1'},body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',redirect:'error',cache:'no-store',signal});
  if(!response.ok)throw new Error(`The service could not complete this request (${response.status}).`);
  const value=await response.json();if(value.protocol!=='orqevia.collective.v1')throw new Error('Unexpected service response.');return value.data;
 }
 function draw(value){
  output.replaceChildren();evidence.textContent=JSON.stringify(value,null,2);
  if(value.pif&&value.mel){output.append(create('p',`Forecasting: ${value.pif.status}. Model efficiency: ${value.mel.status}.`));return;}
  output.append(create('p',`Status: ${value.status||'UNAVAILABLE'}.`));
  if(value.status==='SHADOW')output.append(create('p','Shadow forecast: operational predictive accuracy has not been validated.'));
  if(value.status==='INSUFFICIENT_DATA')output.append(create('p','There is insufficient validated evidence for this forecast.'));
  if(value.status==='DISABLED'||value.status==='disabled')output.append(create('p','This optional capability is disabled. Core tasks remain available.'));
  if(value.status==='retain_baseline')output.append(create('p','Retain the current model. No qualified replacement is available.'));
  const probabilities=value.data?.probabilities;
  if(probabilities){const table=create('table'),head=create('tr');head.append(create('th','State'),create('th','Probability'));table.append(head);for(const [name,probability] of Object.entries(probabilities)){const row=create('tr');row.append(create('td',name),create('td',`${(probability*100).toFixed(2)}%`));table.append(row);}output.append(table);}
  if(value.model_version)output.append(create('p',`Model version: ${value.model_version}. Horizon: ${value.forecast_horizon??'fit'} state transitions.`));
  if(value.ingestion)output.append(create('p','Observed queue history was checked for incomplete or inconsistent events. See diagnostics for excluded histories.'));
 }
 const buttons=[];
 async function run(action){
  if(pending)return;const controller=new AbortController();pending=controller;buttons.forEach(control=>control.disabled=true);state.textContent='Reading service evidence…';
  try{const value=await action(controller.signal);if(!controller.signal.aborted){draw(value);state.textContent='Service evidence received.';}}
  catch(error){if(!controller.signal.aborted){state.textContent=error.message;output.replaceChildren();evidence.textContent='';}}
  finally{if(pending===controller)pending=null;buttons.forEach(control=>control.disabled=false);}
 }
 function button(text,action){const control=create('button',text);control.type='button';control.className='secondary';control.addEventListener('click',()=>void run(action));buttons.push(control);controls.append(control);}
 const forecast=()=>{const steps=Number(horizon.value);if(!Number.isSafeInteger(steps)||steps<0)throw new Error('Enter a nonnegative whole number of state transitions.');return {start:start.value,steps};};
 // Sequential explicit actions avoid another background poller.
 button('Check availability',async signal=>({pif:await api('pif/status',undefined,signal),mel:await api('mel/status',undefined,signal)}));
 button('Fit observed queue history',signal=>api('pif/fit',{},signal));
 button('Forecast states',signal=>api('pif/forecast',forecast(),signal));
 button('Simulate scenario',signal=>api('pif/scenario',{...forecast(),samples:100,seed:0},signal));
 button('View efficiency evidence',signal=>api('mel/recommendation?model_id=all-MiniLM-L6-v2',undefined,signal));
 function clear(){pending?.abort();pending=null;output.replaceChildren();evidence.textContent='';state.textContent=navigator.onLine?'Check availability to read the independent services.':'Offline. Reconnect to read service evidence.';buttons.forEach(control=>control.disabled=false);}
 window.addEventListener('offline',clear);window.addEventListener('orqevia-session',event=>{const next=event.detail;if(next?.clientId!==session?.clientId||next?.role!==session?.role||next?.generation!==session?.generation)clear();session=next;});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)pending?.abort();});
}
