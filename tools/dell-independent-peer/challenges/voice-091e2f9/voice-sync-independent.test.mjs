import test from 'node:test';
import assert from 'node:assert/strict';
import { Voice } from '../../../candidate-091e2f9/clients/pwa/voice.mjs';

// Supplemental fault injection only: synchronous callbacks are not evidence of
// native WebKit behavior. This must not be presented as a confirmed iPhone bug.
test('DV-09: reentrant terminal callback cannot be overwritten with Starting',()=>{
  const keys=['navigator','speechSynthesis','SpeechSynthesisUtterance','setTimeout','clearTimeout'];
  const saved=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  const states=[];
  const globals={
    navigator:{language:'en-SG',userActivation:{isActive:true}},
    SpeechSynthesisUtterance:class {constructor(text){this.text=text;}},
    speechSynthesis:{speaking:false,pending:false,paused:false,getVoices:()=>[],speak(u){u.onstart();u.onend();},cancel(){}},
    setTimeout:()=>1,clearTimeout:()=>{},
  };
  try {
    for(const[key,value]of Object.entries(globals))Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});
    const voice=new Voice({onText(){},onState:(message,state)=>states.push({message,state})});
    voice.speak('Result');
    assert.equal(voice.utterance,null);
    assert.match(states.at(-1).message,/TTS end/,'A terminal state was overwritten by Starting after synchronous completion.');
  } finally {
    for(const[key,descriptor]of saved)if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];
  }
});
