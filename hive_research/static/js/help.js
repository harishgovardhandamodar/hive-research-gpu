/* Hive Research — Help Page & Init */

(function(){
'use strict';
const $=window.$, api=window.api;

window.switchHelpTab=function(el){
  const parent=el.closest('.help-tabs');
  parent.querySelectorAll('.help-tab').forEach(t=>t.classList.remove('active'));
  parent.querySelectorAll('.help-tab-content').forEach(c=>c.classList.remove('active'));
  el.classList.add('active');
  const target=parent.querySelector('#'+el.dataset.tab);
  if(target)target.classList.add('active');
};

document.addEventListener('DOMContentLoaded',async ()=>{
  $('load').classList.remove('h');
  try{await Promise.all([window.G.refresh(),window.D.load(),window.P.load()])}catch(e){}
  $('load').classList.add('h');
});
})();
