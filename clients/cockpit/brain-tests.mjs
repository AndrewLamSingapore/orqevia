import assert from 'node:assert/strict';
import {projectTask,mergeGraph,neighbors,shortestPath,searchGraph} from './brain.mjs';

const task={taskId:'real-1',state:'COMPLETED',revision:3,steps:[{agent_id:'a12',job:{id:'job-1',status:'COMPLETED'}}]};
const artifact={artifact_id:'artifact-1',task_id:'real-1',sha256:'f'.repeat(64),validation_state:'VERIFIED'};
const graph=projectTask(task,[artifact,{...artifact,artifact_id:'foreign',task_id:'other'}]);
assert.equal(graph.nodes.length,4);
assert.equal(graph.edges.length,3);
assert.equal(graph.nodes.find(n=>n.id==='artifact:artifact-1').provenance.sha256,'f'.repeat(64));
assert.deepEqual(shortestPath(graph,'agent:a12','artifact:artifact-1'),['agent:a12','job:job-1','task:real-1','artifact:artifact-1']);
assert.equal(neighbors(graph,'task:real-1').length,2);
assert.equal(searchGraph(graph,'artifact','artifact').length,1);
assert.equal(mergeGraph([graph,graph]).nodes.length,4);
assert.throws(()=>projectTask({taskId:'../bad'}),TypeError);
assert.equal(projectTask({taskId:'empty',state:'UNKNOWN'}).nodes.length,1);
console.log('brain-tests: 8 passed');
