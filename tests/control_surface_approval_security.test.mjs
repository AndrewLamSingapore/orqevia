import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../docs/history/frontend-retirement-20261105/control_surface.html', import.meta.url), 'utf8');
const line = prefix => source.split(/\r?\n/).find(value => value.startsWith(prefix));
const approvalCard = new Function(`${line('const $=')} ${line('function approvalCard(x)')}; return approvalCard;`)();

test('approval keys with quotes and markup remain inert data and reach the delegated handler intact', () => {
  const key = `case'\");globalThis.injected=true;//<svg onload=alert(1)>&quot;`;
  const markup = approvalCard({
    status: 'PENDING', idempotency_key: key, title: 'Review', risk: 'low',
    source: 'test', reversibility: 'yes', evidence: [], expected_effect: {},
  });
  assert.equal((markup.match(/data-approval-key=/g) || []).length, 3);
  assert.doesNotMatch(markup, /\sonclick=/);
  assert.match(markup, /&#39;/);
  assert.match(markup, /&quot;/);
  assert.match(markup, /&lt;svg/);
  assert.match(markup, /&amp;quot;/);

  let clickHandler;
  const button = {dataset: {approvalKey: key, decision: 'approve'}};
  const approvalList = {
    addEventListener: (name, handler) => { assert.equal(name, 'click'); clickHandler = handler; },
    contains: node => node === button,
  };
  const calls = [];
  new Function('$', 'decideApproval', line("$('approvalList').addEventListener('click'"))(
    () => approvalList, (id, decision) => calls.push({id, decision}),
  );
  clickHandler({target: {closest: () => button}});
  assert.deepEqual(calls, [{id: key, decision: 'approve'}]);
  assert.equal(globalThis.injected, undefined);
});

test('replacement Console renders owned evidence as inert text and records only an explicit owner action',async()=>{
  // The historical control-surface case above remains regression evidence.
  // This case executes the current Console module against isolated DOM/API
  // fixtures, so the replacement retains its own consequential-action checks.
  const descriptors=new Map(['document','window','location','navigator','fetch'].map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  const nodes=new Map(),events=new Map(),requests=[];let htmlWrites=0;
  const node=tag=>({tag,textContent:'',children:[],value:'',disabled:false,handlers:new Map(),append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},setAttribute(){},addEventListener(name,fn){this.handlers.set(name,fn);},set innerHTML(_value){htmlWrites++;throw new Error('Untrusted evidence must never become HTML');}});
  const get=id=>{if(!nodes.has(id))nodes.set(id,node('div'));return nodes.get(id);};
  const dispatch=event=>{for(const handler of events.get(event.type)||[])handler(event);};
  const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
  try {
    globalThis.document={getElementById:get,createElement:node};
    globalThis.window={addEventListener(name,fn){if(!events.has(name))events.set(name,new Set());events.get(name).add(fn);},dispatchEvent:dispatch};
    globalThis.location={href:'https://console-fixture.invalid/pwa/?view=console'};
    Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
    const untrusted='<svg onload="globalThis.__lensInjected=true">user evidence</svg>';
    globalThis.fetch=async(path,options)=>{requests.push({path,options});return new Response(JSON.stringify({scope:'FIXTURE_ONLY',content:untrusted,verification:{status:'NOT_RUN'}}),{status:200,headers:{'Content-Type':'application/json'}});};
    const core=new URL('../clients/pwa/core.mjs',import.meta.url).href;
    const current=readFileSync(new URL('../clients/pwa/command-center.mjs',import.meta.url),'utf8').replaceAll("'./core.mjs'",JSON.stringify(core));
    await import('data:text/javascript;base64,'+Buffer.from(current).toString('base64'));
    dispatch(new CustomEvent('orqevia-session',{detail:{clientId:'fixture-owner',role:'OWNER',generation:1}}));
    assert.equal(requests.length,0,'Opening Console does not record evidence');
    get('lens-task').value='11111111-1111-4111-8111-111111111111';
    get('lens-read').handlers.get('click')();await settle();await settle();
    assert.equal(requests.length,1);assert.equal(requests[0].options.method,'GET');
    assert.equal(get('lens-result').children[0].tag,'pre');
    assert.equal(JSON.parse(get('lens-result').children[0].textContent).content,untrusted);
    assert.equal(htmlWrites,0);assert.equal(globalThis.__lensInjected,undefined);
    get('lens-record').handlers.get('click')();await settle();await settle();
    assert.equal(requests.length,2);assert.equal(requests[1].options.method,'POST');assert.equal(requests[1].options.body,'{}');
    for(const request of requests){assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.cache,'no-store');assert.equal(request.options.redirect,'error');assert.equal(request.options.headers['X-ORQEVIA-PWA'],'1');assert.equal(request.options.headers.Authorization,undefined);}
    dispatch(new CustomEvent('orqevia-session',{detail:{clientId:'fixture-member',role:'MEMBER',generation:2}}));
    assert.equal(get('lens-result').children.length,0);assert.equal(get('lens-task').value,'');assert.equal(get('lens-record').disabled,true);
    get('lens-task').value='11111111-1111-4111-8111-111111111111';get('lens-record').handlers.get('click')();await settle();
    assert.equal(requests.length,2,'A member cannot start a write even through a programmatic click');
  } finally {
    for(const [name,descriptor] of descriptors){if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}
  }
});
