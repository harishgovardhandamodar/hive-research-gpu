/* Hive Research — Papers Module & Detail Overlay */

(function(){
'use strict';
const $=window.$, api=window.api, esc=window.esc;

window.P={
  data:null,
  async load(){
    try{
      this.data=await api('/api/papers');
      this.render();
    }catch(e){}
  },
  render(){
    if(!this.data||!this.data.length){$('pList').innerHTML='<div style="color:var(--text3);font-size:12px">No papers</div>';return}
    $('pList').innerHTML=this.data.map(p=>`<div class="paper-row" onclick="showDetailById('${esc(p.id)}')">
      <div class="t">${esc(p.title||'')}</div>
      <div class="a">${esc((p.authors||'').substring(0,60))}</div>
      <div class="d">${p.published||''}</div>
    </div>`).join('');
  }
};

window.showDetail=async function(node){
  const id=node.id||node.arxiv_id;
  const detail=$('detail');
  const p=node;
  let sim=[];
  try{sim=await api('/api/similarity','POST',{paper_ids:[id],algorithm:'combined'})}catch(e){}
  const si=(sim||[]).filter(s=>s.source!==s.target&&(s.source===id||s.target===id)).sort((a,b)=>b.score-a.score).slice(0,8);
  let sh='';
  if(si.length){
    sh='<div class="sb"><b>Similar</b><ul class="sl">'+si.map(s=>{
      const oid=s.source===id?s.target:s.source;const ot=s.source===id?s.target_title:s.source_title;
      return '<li><a href="#" onclick="event.preventDefault();showDetailById(\''+esc(oid)+'\')">'+esc(ot.substring(0,50))+'</a><span class="p">'+(s.score*100).toFixed(0)+'%</span></li>';
    }).join('')+'</ul></div>';
  }
  detail.innerHTML='<button class="x" onclick="closeDetail()">&#x2716;</button>'+
    '<h2>'+esc(p.label||p.title||'')+'</h2>'+
    '<div class="m">'+(p.authors?esc(p.authors):'')+(p.published?' &middot; '+p.published:'')+'</div>'+
    (p.abstract?'<div class="sb"><b>Abstract</b><p>'+esc(p.abstract.substring(0,400))+'</p></div>':'')+
    sh;
  detail.classList.add('open');
};

window.showDetailById=async function(id){
  try{
    const papers=await api('/api/papers');
    const p=papers.find(x=>x.id===id);
    if(p)window.showDetail(p);
  }catch(e){}
};

window.closeDetail=function(){$('detail').classList.remove('open')};
})();
