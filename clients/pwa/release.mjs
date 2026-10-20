const RELEASE='orqevia-shell-v30';

if((location.protocol==='https:'||['localhost','127.0.0.1'].includes(location.hostname))&&'serviceWorker'in navigator){
  const reloadKey=`${RELEASE}:controller-reload`;
  navigator.serviceWorker.addEventListener('controllerchange',()=>{
    if(globalThis.__ORQEVIA_TEST_SUPPRESS_CONTROLLER_RELOAD__===true)return;
    if(sessionStorage.getItem(reloadKey))return;
    sessionStorage.setItem(reloadKey,'1');
    location.reload();
  });
  navigator.serviceWorker.register('/pwa/sw.js',{scope:'/pwa/'})
    .then(registration=>registration.update()).catch(()=>{});
}
