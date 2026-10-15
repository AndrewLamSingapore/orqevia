const RELEASE='orqevia-shell-v23';

if(location.protocol==='https:'&&'serviceWorker'in navigator){
  const reloadKey=`${RELEASE}:controller-reload`;
  navigator.serviceWorker.addEventListener('controllerchange',()=>{
    if(sessionStorage.getItem(reloadKey))return;
    sessionStorage.setItem(reloadKey,'1');
    location.reload();
  });
  navigator.serviceWorker.register('/pwa/sw.js',{scope:'/pwa/'})
    .then(registration=>registration.update()).catch(()=>{});
}
