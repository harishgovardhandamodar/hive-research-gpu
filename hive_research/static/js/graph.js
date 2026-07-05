/* Hive Research — Knowledge Graph Module */

(function(){
'use strict';
const $=window.$, api=window.api, log=window.log, esc=window.esc;

window.G={
  data:null,
  async refresh(){
    try{
      const [g,stats]=await Promise.all([api('/api/graph'),api('/api/stats')]);
      this.data=g;if(stats)window.D.load();
      if(window.nav.current==='graph')this.render();
      log('Graph refreshed','d');
    }catch(e){log('Failed to load graph','e')}
  },
  render(){
    const wrap=$('graphWrap');const empty=$('gEmpty');
    if(!this.data||!this.data.nodes||!this.data.nodes.length){empty.style.display='flex';return}
    empty.style.display='none';
    const svg=d3.select('#graphWrap svg');
    if(svg.empty()){d3.select('#graphWrap').insert('svg',':first-child');}
    const rect=wrap.getBoundingClientRect();
    const W=rect.width||800,H=rect.height||500;
    const svgEl=d3.select('#graphWrap svg').attr('width',W).attr('height',H).attr('viewBox',[0,0,W,H]);
    svgEl.selectAll('*').remove();
    const links=this.data.links.map(d=>({...d}));
    const nodes=this.data.nodes.map(d=>({...d}));
    const sim=d3.forceSimulation(nodes)
      .force('link',d3.forceLink(links).id(d=>d.id).distance(100))
      .force('charge',d3.forceManyBody().strength(-200))
      .force('center',d3.forceCenter(W/2,H/2))
      .force('collision',d3.forceCollide(12))
      .alphaDecay(.03);
    const defs=svgEl.append('defs');
    defs.append('marker').attr('id','ar').attr('viewBox','0 -5 10 10').attr('refX',14).attr('refY',0).attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
      .append('path').attr('d','M0,-5L10,0L0,5').attr('fill','var(--border)');
    const link=svgEl.append('g').selectAll('line').data(links).join('line')
      .attr('stroke','var(--border)').attr('stroke-width',d=>d.relation==='cites'?1.2:.6).attr('stroke-opacity',.6).attr('marker-end','url(#ar)');
    const node=svgEl.append('g').selectAll('g').data(nodes).join('g').call(d3.drag()
      .on('start',(e,d)=>{if(!e.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y})
      .on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y})
      .on('end',(e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));
    node.append('title').text(d=>d.label||'');
    const ps=Math.min(14,36/Math.max(Math.sqrt(nodes.length),1));
    node.filter(d=>d.group===0).append('rect').attr('width',ps).attr('height',ps).attr('x',-ps/2).attr('y',-ps/2).attr('rx',3)
      .attr('fill','var(--accent)').attr('stroke','var(--accent)').attr('stroke-width',1.5).attr('stroke-opacity',.4);
    node.filter(d=>d.group===1).append('circle').attr('r',ps/1.6)
      .attr('fill','var(--purple)').attr('stroke','var(--purple)').attr('stroke-width',1.5).attr('stroke-opacity',.4);
    node.filter(d=>d.type==='web').append('rect').attr('width',ps+2).attr('height',ps+2).attr('x',-(ps+2)/2).attr('y',-(ps+2)/2).attr('rx',2).attr('transform','rotate(45)')
      .attr('fill','var(--orange)').attr('stroke','var(--orange)').attr('stroke-width',1.5).attr('stroke-opacity',.4);
    node.append('text').text(d=>{
      const l=d.label||'';return l.length>25?l.substring(0,22)+'…':l;
    }).attr('font-size','7px').attr('text-anchor','middle').attr('dy',d=>d.group===1?-ps/1.6-3:ps/2+10).attr('fill','var(--text2)').attr('pointer-events','none');
    node.on('click',(e,d)=>{e.stopPropagation();window.showDetail(d)});
    sim.on('tick',()=>{
      link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
      node.attr('transform',d=>`translate(${d.x},${d.y})`);
    });
  },
  search(q){
    if(!this.data)return;
    q=q.toLowerCase();
    d3.selectAll('#graphWrap g g').attr('opacity',d=>!q||(d.label||'').toLowerCase().includes(q)?1:.15);
  }
};
})();
