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
