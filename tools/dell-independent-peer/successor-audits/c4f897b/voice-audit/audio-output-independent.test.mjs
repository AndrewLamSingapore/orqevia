import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {Voice} from '../source/clients/pwa/voice.mjs';

const source = new URL('../source/clients/pwa/voice.mjs',import.meta.url);
const digest='040e9406333c7577264bc5a3215d9031a688ffc2564d89ad59b916facf5d1078';
assert.equal(createHash('sha256').update(readFileSync(source)).digest('hex'),digest);
const candidate='c4f897b0d311a4c15be27df52f14d4c9e6ab5702';

function fixture(id,run,{suspended=false,constructionFailure=false}={}) {
  const keys=['AudioContext','webkitAudioContext','navigator','setTimeout','clearTimeout'];
  const original=new Map(keys.map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  const contexts=[],states=[],timers=new Map();let clock=0,serial=0;
  class Context {
    constructor(){this.state=suspended?'suspended':'running';this.currentTime=0;this.destination={};this.closeCalls=0;this.resumeCalls=0;contexts.push(this);}
    createOscillator(){if(constructionFailure)throw new DOMException('Injected node error','InvalidStateError');this.oscillator={frequency:{},stopTimes:[],connect(){},start(){},stop(time){this.stopTimes.push(time);}};return this.oscillator;}
    createGain(){return {gain:{},connect(){}};}
    resume(){this.resumeCalls++;return new Promise(()=>{});}
    close(){this.closeCalls++;this.state='closed';return Promise.resolve();}
  }
  const globals={AudioContext:Context,webkitAudioContext:undefined,navigator:{language:'en-SG',userActivation:{isActive:true}},setTimeout(callback,delay){const id=++serial;timers.set(id,{at:clock+delay,callback});return id;},clearTimeout(id){timers.delete(id);}};
  for(const[k,value]of Object.entries(globals))Object.defineProperty(globalThis,k,{value,writable:true,configurable:true});
  const voice=new Voice({onText(){},onState(message,state){states.push({message,state:state??null});}});
  const advance=duration=>{const end=clock+duration;while(true){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;clock=next[1].at;timers.delete(next[0]);next[1].callback();}clock=end;};
  try {run({voice,states,contexts,advance});}
  finally {
    console.log(JSON.stringify({candidate,sourceSha256:digest,id,classification:'PROVEN_BY_AUTOMATION',nativeDell:'UNPROVEN',physicalAudioObserved:false,clock,states,contexts:contexts.map(c=>({state:c.state,closeCalls:c.closeCalls,resumeCalls:c.resumeCalls,stopTimes:c.oscillator?.stopTimes}))}));
    for(const[k,descriptor]of original)if(descriptor)Object.defineProperty(globalThis,k,descriptor);else delete globalThis[k];
  }
}

test('DA-01: Stop audio must cancel a diagnostic tone it started',()=>fixture('DA-01',({voice,contexts})=>{
  voice.testOutput();voice.stop();
  assert.ok(contexts[0].closeCalls>0 || contexts[0].oscillator.stopTimes.some(time=>time==null || time<=contexts[0].currentTime),'Stop ignores the tone: context remains running, only the original future stop is scheduled.');
}));

test('DA-02: pending resume must have a wall-clock bound and cleanup',()=>fixture('DA-02',({voice,contexts,states,advance})=>{
  voice.testOutput();advance(60_000);
  assert.ok(contexts[0].closeCalls>0,'Suspended context is never closed when resume remains pending; audio-clock stop cannot expire.');
  assert.equal(states.at(-1).state,'error');
},{suspended:true}));

test('DA-03: repeat test-sound taps cannot accumulate unowned pending contexts',()=>fixture('DA-03',({voice,contexts})=>{
  voice.testOutput();voice.testOutput();voice.testOutput();
  assert.ok(contexts.filter(c=>c.state!=='closed').length<=1,'Three safe test taps created three live pending contexts with no ownership/replacement policy.');
},{suspended:true}));

test('DA-04: synchronous node-creation failure is visible and closes context',()=>fixture('DA-04',({voice,contexts,states})=>{
  voice.testOutput();assert.equal(contexts[0].closeCalls,1);assert.equal(states.at(-1).state,'error');assert.match(states.at(-1).message,/failed.*InvalidStateError/);
},{constructionFailure:true}));

test('DA-05: ended tone still requests physical audibility confirmation',()=>fixture('DA-05',({voice,contexts,states})=>{
  voice.testOutput();contexts[0].oscillator.onended();
  assert.match(states.at(-1).message,/Confirm whether the tone was physically audible/);
  assert.equal(contexts[0].closeCalls,1);
}));

for(const mode of ['resume','close'])test(`DA-${mode==='resume'?'06':'07'}: rejected ${mode} Promise must be contained`,()=>{
  // Isolate genuine unhandled-rejection behavior from the Node test runner.
  const code=`
    import {Voice} from ${JSON.stringify(source.href)};
    const states=[],unhandled=[];let oscillator;
    process.on('unhandledRejection',error=>unhandled.push(error.name));
    Object.defineProperty(globalThis,'navigator',{value:{language:'en-SG',userActivation:{isActive:true}},configurable:true});
    globalThis.AudioContext=class {
      constructor(){this.state=${JSON.stringify(mode==='resume'?'suspended':'running')};this.currentTime=0;this.destination={};}
      createOscillator(){oscillator={frequency:{},connect(){},start(){},stop(){}};return oscillator;}
      createGain(){return {gain:{},connect(){}};}
      resume(){return Promise.reject(new DOMException('Injected resume failure','NotAllowedError'));}
      close(){this.state='closed';return ${mode==='close'?'Promise.reject(new DOMException("Injected close failure","InvalidStateError"))':'Promise.resolve()'};}
    };
    const voice=new Voice({onText(){},onState:(message,state)=>states.push({message,state})});voice.testOutput();
    ${mode==='close'?'oscillator.onended();':''}
    setTimeout(()=>{console.log(JSON.stringify({mode:${JSON.stringify(mode)},states,unhandled,classification:'PROVEN_BY_AUTOMATION',nativeDell:'UNPROVEN',physicalAudioObserved:false}));process.exitCode=unhandled.length?17:0;},10);
  `;
  const result=spawnSync(process.execPath,['--input-type=module','-e',code],{encoding:'utf8',timeout:5000});
  console.log(result.stdout.trim());
  assert.equal(result.status,0,`${mode} rejection escapes handling. Child observation: ${result.stdout.trim()} ${result.stderr}`);
});
