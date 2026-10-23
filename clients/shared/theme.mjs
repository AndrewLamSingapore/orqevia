const key='orqevia-appearance-v1';
export function setTheme(value,{persist=true}={}){
  if(!['light','dark'].includes(value))return;
  document.documentElement.dataset.theme=value;
  document.querySelectorAll('[data-theme-toggle]').forEach(button=>{
    button.setAttribute('aria-pressed',String(value==='light'));
    button.setAttribute('aria-label',value==='light'?'Switch to dark appearance':'Switch to light appearance');
    button.textContent=value==='light'?'Dark mode':'Light mode';
  });
  if(persist)try{localStorage.setItem(key,value);}catch{}
  document.dispatchEvent(new CustomEvent('orqevia-theme',{detail:{theme:value}}));
}
if(typeof document!=='undefined'){
  let preferred;try{preferred=localStorage.getItem(key);}catch{}
  setTheme(['light','dark'].includes(preferred)?preferred:matchMedia('(prefers-color-scheme: light)').matches?'light':'dark',{persist:false});
  document.querySelectorAll('[data-theme-toggle]').forEach(button=>button.addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='light'?'dark':'light')));
}
