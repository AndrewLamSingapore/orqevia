// Graph facts are projected only from responses of PRIME's authenticated
// Interface contract. Missing entities remain absent, never invented.
const text = value => typeof value === 'string' ? value.trim() : '';
const bounded = value => text(value).slice(0, 200);

export function projectTask(task, artifacts = []) {
  const id = text(task?.taskId || task?.task_id || task?.id);
  if (!/^[A-Za-z0-9._:-]{1,128}$/.test(id)) throw new TypeError('Invalid task identity');
  const nodes = [{id:`task:${id}`, kind:'task', label:id, state:bounded(task.internal_state || task.state) || 'UNKNOWN',
    provenance:{source:'PRIME_INTERFACE', taskId:id, revision:Number.isSafeInteger(task.revision)?task.revision:null}}];
  const edges = [];
  const seen = new Set(nodes.map(node => node.id));
  const add = (node, edge) => { if (!seen.has(node.id)) { nodes.push(node); seen.add(node.id); } edges.push(edge); };
  for (const [index, step] of (Array.isArray(task.steps) ? task.steps : []).entries()) {
    const job = step?.job;
    const jobId = text(job?.id);
    if (!jobId || !/^[A-Za-z0-9._:-]{1,128}$/.test(jobId)) continue;
    add({id:`job:${jobId}`,kind:'job',label:jobId,state:bounded(job.status) || 'UNKNOWN',
      provenance:{source:'PRIME_INTERFACE',taskId:id,step:index}},
      {from:`task:${id}`,to:`job:${jobId}`,kind:'executes'});
    const agentId = text(step.agent_id || step.agentId || job.agent_id);
    if (agentId && /^[A-Za-z0-9._:-]{1,128}$/.test(agentId)) add(
      {id:`agent:${agentId}`,kind:'agent',label:agentId,state:'UNVERIFIED',provenance:{source:'PRIME_INTERFACE',taskId:id,step:index}},
      {from:`agent:${agentId}`,to:`job:${jobId}`,kind:'assigned_to'});
  }
  for (const artifact of artifacts) {
    const artifactId = text(artifact.artifactId || artifact.artifact_id);
    if (!artifactId || !/^[A-Za-z0-9._:-]{1,128}$/.test(artifactId)) continue;
    if (text(artifact.taskId || artifact.task_id) !== id) continue;
    add({id:`artifact:${artifactId}`,kind:'artifact',label:artifactId,state:bounded(artifact.status || artifact.validation_state) || 'UNKNOWN',
      provenance:{source:'ARTIFACT_STORE',taskId:id,sha256:artifact.sha256 || null}},
      {from:`task:${id}`,to:`artifact:${artifactId}`,kind:'produced'});
  }
  return {nodes,edges};
}

export function mergeGraph(parts) {
  const nodes = new Map(), edges = new Map();
  for (const part of parts) {
    for (const node of part.nodes || []) nodes.set(node.id,node);
    for (const edge of part.edges || []) edges.set(`${edge.from}|${edge.kind}|${edge.to}`,edge);
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]};
}

export function neighbors(graph, id) {
  const adjacent = new Set();
  for (const edge of graph.edges) {
    if (edge.from === id) adjacent.add(edge.to);
    if (edge.to === id) adjacent.add(edge.from);
  }
  return graph.nodes.filter(node => adjacent.has(node.id));
}

export function shortestPath(graph, from, to) {
  if (from === to) return [from];
  const queue = [[from]], visited = new Set([from]);
  while (queue.length) {
    const path = queue.shift();
    for (const node of neighbors(graph,path.at(-1))) {
      if (visited.has(node.id)) continue;
      const next = [...path,node.id];
      if (node.id === to) return next;
      visited.add(node.id); queue.push(next);
    }
  }
  return null;
}

export function searchGraph(graph, query, kind = 'all', limit = 50) {
  const q = text(query).toLocaleLowerCase();
  return graph.nodes.filter(node => (kind === 'all' || node.kind === kind) &&
    (!q || `${node.label} ${node.id} ${node.state}`.toLocaleLowerCase().includes(q))).slice(0,limit);
}
