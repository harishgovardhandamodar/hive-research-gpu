/* Hive Research — Bootstrap & Navigation */

(function(){
'use strict';

window.$=id=>document.getElementById(id);
window.esc=s=>{const d=document.createElement('div');d.textContent=s;return d.innerHTML};
window.api=async(p,method,body)=>{const o={method:method||'GET',headers:{'Content-Type':'application/json'}};if(body)o.body=JSON.stringify(body);const r=await fetch(p,o);return r.json()};
window.log=(msg,type='i')=>{const e=$('log');const d=document.createElement('div');d.className='log-e '+type;d.textContent=msg;e.appendChild(d);setTimeout(()=>d.remove(),4000)};

// ── Theme ──
const saved=localStorage.getItem('hive_theme');
if(saved==='light'){document.body.classList.add('light');$('themeBtn').textContent='\u2600'}
window.theme={
  toggle(){document.body.classList.toggle('light');const isLight=document.body.classList.contains('light');
    localStorage.setItem('hive_theme',isLight?'light':'dark');$('themeBtn').textContent=isLight?'\u2600':'\u263E'}
};

// ── Navigation ──
window.nav={
  current:'dash',
  switch(name,el){
    document.querySelectorAll('.p').forEach(p=>p.classList.remove('a'));
    const target=$('p-'+name);
    if(target)target.classList.add('a');
    document.querySelectorAll('.nv').forEach(n=>n.classList.remove('a'));
    if(el)el.classList.add('a');
    this.current=name;
    if(name==='graph')setTimeout(()=>G.render(),50);
    if(name==='papers')P.load();
    if(name==='similarity')S.render();
  }
};
window.H=nav;

window.statsEl=()=>$('statsR');

// ── Dashboard ──
window.D={
  async load(){
    try{
      const stats=await api('/api/stats');
      if(!stats)return;
      const items=[
        {v:stats.papers||0,l:'Papers'},{v:stats.concepts||0,l:'Concepts'},
        {v:stats.relations||0,l:'Edges'},{v:stats.graph_papers||0,l:'Graph Papers'},
        {v:stats.graph_refs||0,l:'Refs'},{v:stats.cross_edges||0,l:'Cross Edges'},
      ];
      $('statsR').innerHTML=items.map(i=>`<div class="stat-c"><div class="v">${i.v}</div><div class="l">${i.l}</div></div>`).join('');
    }catch(e){}
  }
};

// ── Similarity ──
window.S={
  data:null,
  async load(){
    try{
      const algo=$('simAlgo').value;log('Computing similarity...','i');
      this.data=await api('/api/similarity','POST',{algorithm:algo});
      this.render();log(`Similarity: ${(this.data||[]).length} pairs`,'d');
    }catch(e){log('Similarity error','e')}
  },
  render(){
    if(!this.data||!this.data.length){$('simR').innerHTML='<div style="color:var(--text3);padding:10px">No data. Click Compute.</div>';return}
    const items=this.data.slice(0,200);
    $('simR').innerHTML='<table class="sim-t"><thead><tr><th>Paper A</th><th>Paper B</th><th>Score</th></tr></thead><tbody>'+
      items.map(s=>{const cls=s.score>.3?'h':s.score>.15?'m':'l';
        return '<tr><td>'+esc(s.source_title.substring(0,50))+'</td><td>'+esc(s.target_title.substring(0,50))+'</td><td><span class="sc '+cls+'">'+(s.score*100).toFixed(0)+'%</span></td></tr>'}).join('')+
      '</tbody></table>'+(this.data.length>200?`<div style="color:var(--text3);font-size:10px;padding:6px">Showing 200 of ${this.data.length} pairs</div>`:'');
  }
};

// ── Import ──
window.I={
  async add(){
    const val=$('impId').value.trim();if(!val)return;
    log('Adding paper...','i');$('impId').value='';
    try{const r=await api('/api/add','POST',{id:val});
      if(r.status==='added')log(`Added: ${r.paper_id} (${r.concepts||0} concepts)`,'d');
      else log(r.message||'Already exists','w');G.refresh();
    }catch(e){log('Error adding paper','e')}
  },
  async web(){
    const val=$('impUrl').value.trim();if(!val)return;
    log('Ingesting web page...','i');$('impUrl').value='';
    try{const r=await api('/api/web/add','POST',{url:val});
      if(r.status==='added')log(`Ingested: ${r.title||r.id}`,'d');
      else log(r.message||'Error','w');G.refresh();
    }catch(e){log('Error ingesting','e')}
  },
  async search(){
    const val=$('impQ').value.trim();if(!val)return;
    log('Searching arXiv...','i');
    try{const r=await api('/api/search','POST',{query:val});
      if(r.status==='ok')log(`Search: ${r.added||0} added, ${r.exists||0} existed`,'d');
      else log(r.message||'Error','w');G.refresh();
    }catch(e){log('Error searching','e')}
  }
};

})();
