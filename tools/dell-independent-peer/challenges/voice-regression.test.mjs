import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Portable challenge suite. Source binding must be supplied independently by
// the runner from its verified, frozen checkout. This suite does not establish
// Git provenance, physical Dell execution, or audible iPhone behavior.
const rootInput = process.env.PRIME_CANDIDATE_ROOT;
const digestInput = process.env.EXPECTED_VOICE_SHA256;
assert.ok(rootInput && path.isAbsolute(rootInput), 'PRIME_CANDIDATE_ROOT must be an absolute path to the verified frozen checkout.');
assert.match(digestInput || '', /^[a-fA-F0-9]{64}$/, 'EXPECTED_VOICE_SHA256 must be an independently supplied 64-character SHA-256 digest.');
const SOURCE_DIGEST = digestInput.toLowerCase();
const CANDIDATE = process.env.PRIME_CANDIDATE_SHA || 'UNSPECIFIED';
if(CANDIDATE !== 'UNSPECIFIED') assert.match(CANDIDATE,/^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$/, 'PRIME_CANDIDATE_SHA must be an exact full Git revision when supplied.');
const root = realpathSync(rootInput);
const sourcePath = realpathSync(path.join(root, 'clients', 'pwa', 'voice.mjs'));
const relative = path.relative(root, sourcePath);
assert.ok(relative && relative !== '..' && !relative.startsWith('..'+path.sep) && !path.isAbsolute(relative), 'Voice source must resolve inside the candidate checkout.');
const sourceHash = () => createHash('sha256').update(readFileSync(sourcePath)).digest('hex');
assert.equal(sourceHash(), SOURCE_DIGEST, 'Candidate voice source digest differs from independent runner expectation.');
const { Voice } = await import(pathToFileURL(sourcePath).href);
assert.equal(typeof Voice, 'function', 'Candidate must export Voice.');
assert.equal(sourceHash(), SOURCE_DIGEST, 'Candidate voice source changed while importing.');
console.log(JSON.stringify({type:'voice-challenge-binding',candidateClaim:CANDIDATE,sourcePath,sourceSha256:SOURCE_DIGEST,proof:'PROVEN_BY_AUTOMATION',nativeDell:'UNPROVEN',note:'Caller must preserve immutable checkout and separately attest runner machine identity.'}));

function fixture(id, run, overrides = {}) {
  const keys = ['navigator', 'speechSynthesis', 'SpeechSynthesisUtterance', 'setTimeout', 'clearTimeout'];
  const descriptors = new Map(keys.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const states = [], spoken = [], calls = [], timers = new Map();
  let clock = 0, serial = 0;
  const synthesis = {
    speaking: false, pending: false, paused: false,
    getVoices() { calls.push('getVoices'); return [{lang:'en-SG',name:'Mock voice'}]; },
    speak(u) { calls.push('speak'); spoken.push(u); this.pending = true; },
    cancel() { calls.push('cancel'); this.speaking = false; this.pending = false; },
    ...overrides.synthesis,
  };
  const globals = {
    navigator: {language:'en-SG',userActivation:{isActive:true},standalone:true},
    speechSynthesis: synthesis,
    SpeechSynthesisUtterance: overrides.Utterance || class { constructor(text) {this.text=text;} },
    setTimeout(callback, delay) {const id=++serial; timers.set(id,{callback,at:clock+delay}); return id;},
    clearTimeout(id) {timers.delete(id);},
  };
  for (const [key,value] of Object.entries(globals)) Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});
  const voice = new Voice({onText(){},onState(message,state){states.push({message,state:state??null});}});
  function advance(duration) {
    const end=clock+duration;
    while(true) {
      const next=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!next)break;
      clock=next[1].at;timers.delete(next[0]);next[1].callback();
    }
    clock=end;
  }
  let failure;
  try {run({voice,states,spoken,calls,synthesis,advance,timers});}
  catch(error) {failure={name:error.name,message:error.message};throw error;}
  finally {
    console.log(JSON.stringify({type:'voice-challenge-observation',candidateClaim:CANDIDATE,sourceSha256:SOURCE_DIGEST,proof:'PROVEN_BY_AUTOMATION',authorship:'independently authored outside ABEX',nativeDell:'UNPROVEN',id,states,calls,clock,ownedUtterance:!!voice.utterance,speaking:voice.speaking,timers:timers.size,failure,physicalAudioObserved:false}));
    for(const [key,descriptor] of descriptors) {
      if(descriptor) Object.defineProperty(globalThis,key,descriptor); else delete globalThis[key];
    }
  }
}

test('DV-01: a queued start callback after STOP cannot revive the stopped UI',()=>fixture('DV-01',({voice,states,spoken})=>{
  voice.speak('Result');
  const old=spoken[0];
  voice.stop();
  const checkpoint=states.length;
  assert.equal(voice.utterance,null);
  old.onstart(); // A callback already queued before cancellation is delivered late.
  assert.equal(states.length,checkpoint,'Late start after STOP must be ignored; current implementation changes UI to speaking.');
}));

test('DV-02: an older attempt cannot emit a start receipt bearing the new attempt number',()=>fixture('DV-02',({voice,states,spoken})=>{
  voice.speak('Old result');const old=spoken[0];voice.stop();
  voice.speak('New result');const current=spoken[1];const checkpoint=states.length;
  assert.equal(voice.speechAttempt,2);
  old.onstart();
  assert.equal(voice.utterance,current);
  assert.equal(states.length,checkpoint,'Old callback writes TTS start; attempt=2 although attempt 2 has never started.');
}));

test('DV-03: start with no end/error must eventually terminate and expose a timeout',()=>fixture('DV-03',({voice,states,spoken,synthesis,advance})=>{
  voice.speak('One short sentence.');synthesis.speaking=true;synthesis.pending=false;spoken[0].onstart();
  advance(60*60*1000); // One simulated hour, no real waiting or resource load.
  assert.equal(voice.utterance,null,'An owned short utterance remains stuck indefinitely after start; no terminal watchdog exists.');
  assert.equal(voice.speaking,false);
  assert.equal(states.at(-1).state,'error');
  assert.match(states.at(-1).message,/timeout|timed out|did not finish/i);
}));

test('DV-04: voice service exception must be visible and contained',()=>fixture('DV-04',({voice,states})=>{
  assert.doesNotThrow(()=>voice.speak('Result'),'getVoices is an external service boundary and must share the failure handling.');
  assert.equal(voice.speaking,false);assert.equal(states.at(-1).state,'error');
},{synthesis:{getVoices(){throw new DOMException('Voice service unavailable','InvalidStateError');}}}));

test('DV-05: utterance construction exception must be visible and contained',()=>fixture('DV-05',({voice,states})=>{
  assert.doesNotThrow(()=>voice.speak('Result'),'Utterance construction failure must reach a user-visible error.');
  assert.equal(voice.speaking,false);assert.equal(states.at(-1).state,'error');
},{Utterance:class {constructor(){throw new DOMException('Speech engine unavailable','InvalidStateError');}}}));

test('DV-06: speak invocation exception is contained and releases owned state',()=>fixture('DV-06',({voice,states})=>{
  assert.doesNotThrow(()=>voice.speak('Result'));
  assert.equal(voice.utterance,null);assert.equal(voice.speaking,false);
  assert.equal(states.at(-1).state,'error');assert.match(states.at(-1).message,/TTS exception/);
},{synthesis:{speak(){throw new DOMException('Blocked','NotAllowedError');}}}));

test('DV-07: a late end from the old attempt cannot terminate the current attempt',()=>fixture('DV-07',({voice,states,spoken})=>{
  voice.speak('Old result');const old=spoken[0];voice.stop();voice.speak('New result');
  const checkpoint=states.length,current=spoken[1];old.onend();
  assert.equal(voice.utterance,current);assert.equal(states.length,checkpoint);
}));

test('DV-08: software lifecycle completion is observable without asserting physical audio',()=>fixture('DV-08',({voice,states,spoken})=>{
  voice.speak('Result');spoken[0].onstart();spoken[0].onend();
  assert.equal(voice.utterance,null);assert.equal(voice.speaking,false);
  assert.match(states[0].message,/TTS invoked; attempt=1; gesture=1/);
  assert.match(states[1].message,/TTS start; attempt=1/);
  assert.match(states[2].message,/TTS end; attempt=1/);
}));

// Optional robustness injection; native WebKit synchronous delivery UNPROVEN.
test('DV-09: reentrant terminal callback cannot be overwritten with Starting', {skip:process.env.PRIME_INCLUDE_SYNCHRONOUS_FAULT !== '1'}, ()=>fixture('DV-09',({voice,states})=>{
  voice.speak('Result');
  assert.equal(voice.utterance,null);
  assert.match(states.at(-1).message,/TTS end/,'A terminal state was overwritten by Starting after synchronous completion.');
},{synthesis:{speak(u){u.onstart();u.onend();}}}));

test('Source remains bound to the runner-supplied digest after challenges',()=>{
  assert.equal(sourceHash(),SOURCE_DIGEST,'Candidate voice source drifted while testing.');
});
