import test from 'node:test';
import assert from 'node:assert/strict';
import {Voice} from './voice.mjs';

class Utterance {constructor(text){this.text=text;}}
globalThis.SpeechSynthesisUtterance=Utterance;
Object.defineProperty(globalThis,'navigator',{value:{language:'en-SG'},configurable:true});

test('iOS Read Aloud retains utterance, selects Chinese voice, and exposes lifecycle state',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:false,getVoices:()=>[{lang:'zh-CN',name:'Tingting'}],speak:u=>spoken.push(u),cancel:()=>assert.fail('fresh speech must not be pre-cancelled')};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});
  voice.speak('你好，我是 JARVIS。');
  assert.equal(voice.utterance,spoken[0]);assert.equal(spoken[0].voice.name,'Tingting');assert.equal(spoken[0].volume,1);
  spoken[0].onstart();assert.match(states.at(-1)[0],/Reading/);spoken[0].onend();assert.equal(voice.utterance,null);assert.match(states.at(-1)[0],/Finished/);
});

test('Read Aloud errors are visible and never silently treated as success',()=>{
  const states=[],spoken=[];
  globalThis.speechSynthesis={speaking:false,pending:false,paused:false,getVoices:()=>[],speak:u=>spoken.push(u),cancel:()=>{}};
  const voice=new Voice({onText:()=>{},onState:(...value)=>states.push(value)});voice.speak('Result');spoken[0].onerror({error:'not-allowed'});
  assert.equal(voice.speaking,false);assert.equal(states.at(-1)[1],'error');assert.match(states.at(-1)[0],/not-allowed/);
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
