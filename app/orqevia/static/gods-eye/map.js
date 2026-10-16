import {mountCommandMap} from '/pwa/command-map.mjs';
const view=await mountCommandMap(document.getElementById('interactive-map'));
document.getElementById('refresh').addEventListener('click',()=>view.reload?.());
