import test from 'node:test';
import assert from 'node:assert/strict';
import {Voice} from './voice.mjs';

class Utterance {constructor(text){this.text=text;}}
globalThis.SpeechSynthesisUtterance=Utterance;
Object.defineProperty(globalThis,'navigator',{value:{language:'en-SG',userActivation:{isActive:true},standalone:true},configurable:true});

test('iOS Read Aloud retains utterance, delegates usable Chinese voice choice to WebKit, and exposes lifecycle state',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:false,getVoices:()=>[{lang:'zh-CN',name:'Tingting'}],speak:u=>spoken.push(u),cancel:()=>assert.fail('fresh speech must not be pre-cancelled')};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});
  voice.speak('你好，我是 JARVIS。');
  assert.equal(voice.utterance,spoken[0]);assert.equal(spoken[0].voice,null);assert.equal(spoken[0].lang,'zh-CN');assert.equal(spoken[0].volume,1);
  assert.match(states.at(-1)[0],/TTS invoked/);assert.match(states.at(-1)[0],/gesture=1/);assert.match(states.at(-1)[0],/voices=1/);assert.match(states.at(-1)[0],/matching=1/);
  spoken[0].onstart();assert.match(states.at(-1)[0],/TTS start/);spoken[0].onend();assert.equal(voice.utterance,null);assert.match(states.at(-1)[0],/TTS end/);
});

test('Read Aloud errors are visible and never silently treated as success',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>{}};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.speak('Result');spoken[0].onerror({error:'not-allowed'});
  assert.equal(voice.speaking,false);assert.equal(states.at(-1)[1],'error');assert.match(states.at(-1)[0],/not-allowed/);
});

test('paused synthesis is resumed before the user-gesture speak call',()=>{
  const calls=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:true,getVoices:()=>[],resume:()=>calls.push('resume'),speak:u=>{calls.push('speak');spoken.push(u);},cancel:()=>{}};
  const voice=new Voice({onText:()=>{},onState:()=>{}});voice.speak('Result');
  assert.deepEqual(calls,['resume','speak']);spoken[0].onstart();spoken[0].onend();
});

test('end without start is reported as an error, never success',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>{}};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.speak('Result');spoken[0].onend();
  assert.equal(states.at(-1)[1],'error');assert.match(states.at(-1)[0],/ended without a start event/);
});

test('no-start timeout cancels the owned utterance and exposes observable state',()=>{
  const states=[],spoken=[],cancelled=[],realSetTimeout=globalThis.setTimeout,realClearTimeout=globalThis.clearTimeout;
  let timeout;
  globalThis.setTimeout=(callback,delay)=>{timeout={callback,delay};return 1;};globalThis.clearTimeout=()=>{};
  try {
    globalThis.speechSynthesis={speaking:false,pending:true,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>cancelled.push(true)};
    const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.speak('你好');
    assert.equal(timeout.delay,8000);timeout.callback();assert.equal(cancelled.length,1);assert.equal(voice.utterance,null);assert.equal(states.at(-1)[1],'error');assert.match(states.at(-1)[0],/TTS timeout-no-start/);assert.match(states.at(-1)[0],/pending=1/);
  } finally {globalThis.setTimeout=realSetTimeout;globalThis.clearTimeout=realClearTimeout;}
});

test('lifecycle cleanup is silent when no audio is active',()=>{const states=[];globalThis.speechSynthesis={speaking:false,pending:false,paused:false,cancel:()=>{}};const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.stop({announce:false});assert.deepEqual(states,[]);voice.stop();assert.deepEqual(states,[]);});

test('stale browser pending flag does not pre-cancel a fresh iOS user-gesture utterance',()=>{
  const spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:true,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>assert.fail('unowned browser state must not be cancelled before fresh speech')};
  const voice=new Voice({onText:()=>{},onState:()=>{}});voice.speak('你好');
  assert.equal(spoken.length,1);assert.equal(voice.utterance,spoken[0]);spoken[0].onstart();spoken[0].onend();
});

test('a second tap stops owned audio without cancel-and-restart in the same gesture turn',()=>{
  const states=[],spoken=[],cancelled=[];
  globalThis.speechSynthesis={speaking:true,pending:false,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>cancelled.push(true)};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.utterance={};voice.speaking=true;voice.speak('Result');
  assert.equal(spoken.length,0);assert.equal(cancelled.length,1);assert.equal(voice.utterance,null);assert.match(states.at(-1)[0],/Tap Read aloud once more/);
});

test('stop does not cancel synthesis state this Voice instance does not own',()=>{
  const cancelled=[];
  globalThis.speechSynthesis={speaking:true,pending:true,paused:false,getVoices:()=>[],cancel:()=>cancelled.push(true)};
  const voice=new Voice({onText:()=>{},onState:()=>{}});voice.stop();assert.deepEqual(cancelled,[]);
});

test('terminal speech telemetry identifies browser voice-selection limits and elapsed state',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:true,pending:false,paused:false,getVoices:()=>[{name:'Default Voice',lang:'en-SG',localService:true,default:true}],speak:u=>spoken.push(u),cancel:()=>{}};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.speak('Result');spoken[0].onstart();spoken[0].onend();
  assert.match(states.at(-1)[0],/selected=system-auto-unobservable/);assert.match(states.at(-1)[0],/defaults=Default Voice\|en-SG\|local=1/);assert.match(states.at(-1)[0],/elapsed_ms=\d+/);assert.match(states.at(-1)[0],/speaking=1/);
});

test('independent Web Audio control is invoked synchronously and reports its terminal state',()=>{
  const states=[];let oscillator;
  class AudioContext {constructor(){this.state='running';this.currentTime=4;this.destination={};}createOscillator(){oscillator={frequency:{},connect:()=>{},start:()=>{},stop:()=>{}};return oscillator;}createGain(){return {gain:{},connect:()=>{}};}close(){this.state='closed';return Promise.resolve();}}
  globalThis.AudioContext=AudioContext;
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.testOutput();assert.match(states.at(-1)[0],/Audio output control started/);assert.match(states.at(-1)[0],/gesture=1/);oscillator.onended();assert.match(states.at(-1)[0],/Audio output control ended/);assert.match(states.at(-1)[0],/elapsed_ms=\d+/);delete globalThis.AudioContext;
});

test('Stop owns and closes the Web Audio control without leaving speaking UI state',()=>{
  const states=[],contexts=[];
  class AudioContext {constructor(){this.state='running';this.currentTime=0;this.destination={};this.closeCount=0;contexts.push(this);}createOscillator(){return {frequency:{},connect:()=>{},start:()=>{},stop:()=>{},onended:null};}createGain(){return {gain:{},connect:()=>{}};}close(){this.closeCount+=1;this.state='closed';return Promise.resolve();}}
  globalThis.AudioContext=AudioContext;
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.testOutput();voice.stop();assert.equal(contexts[0].closeCount,1);assert.equal(voice.outputContext,null);assert.equal(voice.outputOscillator,null);assert.deepEqual(states.at(-1),['Audio stopped.']);delete globalThis.AudioContext;
});

test('repeated phone-sound control cannot overlap AudioContexts',()=>{
  const contexts=[];
  class AudioContext {constructor(){this.state='running';this.currentTime=0;this.destination={};this.closeCount=0;contexts.push(this);}createOscillator(){return {frequency:{},connect:()=>{},start:()=>{},stop:()=>{},onended:null};}createGain(){return {gain:{},connect:()=>{}};}close(){this.closeCount+=1;this.state='closed';return Promise.resolve();}}
  globalThis.AudioContext=AudioContext;
  const voice=new Voice({onText:()=>{},onState:()=>{}});voice.testOutput();voice.testOutput();assert.equal(contexts.length,2);assert.equal(contexts[0].closeCount,1);assert.equal(contexts[1].closeCount,0);voice.stop({announce:false});assert.equal(contexts[1].closeCount,1);delete globalThis.AudioContext;
});

test('silent offline or visibility cleanup clears stale speaking UI state',()=>{
  const states=[],contexts=[];
  class AudioContext {constructor(){this.state='running';this.currentTime=0;this.destination={};this.closeCount=0;contexts.push(this);}createOscillator(){return {frequency:{},connect:()=>{},start:()=>{},stop:()=>{},onended:null};}createGain(){return {gain:{},connect:()=>{}};}close(){this.closeCount+=1;this.state='closed';return Promise.resolve();}}
  globalThis.AudioContext=AudioContext;
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.testOutput();voice.stop({announce:false});assert.equal(contexts[0].closeCount,1);assert.equal(voice.outputContext,null);assert.deepEqual(states.at(-1),['']);delete globalThis.AudioContext;
});
