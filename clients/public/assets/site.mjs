const toggle=document.querySelector('.menu-toggle');
const navigation=document.getElementById('public-navigation');
toggle?.addEventListener('click',()=>{
  const expanded=toggle.getAttribute('aria-expanded')!=='true';
  toggle.setAttribute('aria-expanded',String(expanded));
  navigation.dataset.open=String(expanded);
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&toggle?.getAttribute('aria-expanded')==='true'){
    toggle.setAttribute('aria-expanded','false');navigation.dataset.open='false';toggle.focus();
  }
});
