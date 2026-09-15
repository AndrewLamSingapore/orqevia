import {ClientError,nextSubmission,acknowledge} from './core.mjs';
export class TaskStore {
  async open() { if(this.db)return this.db; this.db=await new Promise((resolve,reject)=>{ const request=indexedDB.open('jarvis-client-reference',1);request.onupgradeneeded=()=>request.result.createObjectStore('state');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new ClientError('storage')); });return this.db; }
  async change(clientId,update) { const db=await this.open();return new Promise((resolve,reject)=>{const tx=db.transaction('state','readwrite',{durability:'strict'});const store=tx.objectStore('state');const request=store.get(clientId);let result;request.onsuccess=()=>{try{result=update(request.result??{pending:null,history:[]});store.put(result,clientId);}catch(error){reject(error);tx.abort();}};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(new ClientError('storage'));tx.onabort=()=>reject(new ClientError('storage'));}); }
  load(clientId) { return this.change(clientId,value=>value); }
  prepare(clientId,digest,uploads=[],action={kind:'new'}) { return this.change(clientId,value=>({...value,pending:{...nextSubmission(value.pending,digest,crypto.randomUUID()),uploads,action:{...action}}})); }
  ack(clientId,key,task) { return this.change(clientId,value=>{const pending=acknowledge(value.pending,key,task.taskId??task.task_id??task.id);return{pending,history:[{id:pending.taskId,state:task.state,updatedAt:Date.now()},...value.history.filter(row=>row.id!==pending.taskId)].slice(0,30)};}); }
  remember(clientId,id,state) { return this.change(clientId,value=>({...value,history:[{id,state,updatedAt:Date.now()},...value.history.filter(row=>row.id!==id)].slice(0,30)})); }
  async clear(clientId) { const db=await this.open();return new Promise((resolve,reject)=>{const tx=db.transaction('state','readwrite',{durability:'strict'});tx.objectStore('state').delete(clientId);tx.oncomplete=resolve;tx.onerror=()=>reject(new ClientError('storage'));}); }
}


