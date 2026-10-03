import {sha256,submissionPayload,taskID} from '../pwa/core.mjs';

// The PWA journal's strict IndexedDB transaction must finish before a POST.
// An uncertain response leaves the same digest/key pending for exact replay.
export async function submitObjective(objective,clientId,api,store) {
  const payload=submissionPayload(objective,[],{kind:'new'});
  const digest=await sha256(new TextEncoder().encode(JSON.stringify(payload)));
  const prepared=await store.prepare(clientId,digest,[],{kind:'new'});
  const key=prepared.pending.key;
  const task=await api.submit(payload.objective,key,[]);
  const id=taskID(task);
  await store.ack(clientId,key,task);
  return {task,id};
}
