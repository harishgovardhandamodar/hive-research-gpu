/* Hive Research — Chat Module */

(function(){
'use strict';
const $=window.$, api=window.api, esc=window.esc, log=window.log;

window.C={
  async send(){
    const input=$('chatIn');const q=input.value.trim();if(!q)return;
    input.value='';const cont=$('chatM');
    cont.innerHTML+=`<div class="chat-b q">${esc(q)}</div>`;cont.scrollTop=cont.scrollHeight;
    try{
      const r=await api('/api/query','POST',{question:q});
      const answer=r.answer||r.response||JSON.stringify(r);
      cont.innerHTML+=`<div class="chat-b r">${esc(answer)}</div>`;cont.scrollTop=cont.scrollHeight;
    }catch(e){cont.innerHTML+=`<div class="chat-b r" style="color:#f87171">Error: ${esc(e.message)}</div>`}
  }
};
})();
