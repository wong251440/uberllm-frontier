/* Frontier Atlas UI - no API keys, external calls, or server-side code in browser. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sourceColors = ['#b9e987','#6bd8c1','#93b8f3','#f6bf82','#e7a2ca','#bf9def','#d1d998','#ec8d9f','#82bfa0','#94a5f5','#e2c9ac','#9ecbd0'];
  const state = {latest:null,history:null,events:null, selectedDate:'latest', provider:'all',scoreFilter:'all',search:'',ratio:150,cache:0.9,
    mode:'all',rangeMode:'focus',rangeMax:null,activeId:null,availableOnly:true,showLabels:false,view:[],frontier:[],dates:[]};
  const escapeHTML = s => String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const costFmt = n => n == null || !isFinite(n) ? '—' : n >= 1000 ? '$'+n.toLocaleString('en-US',{maximumFractionDigits:1}) : n >= 1 ? '$'+n.toFixed(3) : n >= .01 ? '$'+n.toFixed(4) : '$'+n.toPrecision(3);
  const shortFmt = n => n == null || !isFinite(n) ? '—' : (n < .001 ? n.toPrecision(4): n < .1 ? n.toFixed(5) :n.toFixed(3));
  const priceFmt = n => n == null || !isFinite(n) ? '—' : '$'+Number(n.toPrecision(6)).toString();
  const numFmt = n => n == null || !isFinite(n) ? '—' : Number(n).toFixed(1).replace(/\.0$/,'');
  const median = nums => {const a=nums.filter(Number.isFinite).sort((x,y)=>x-y);if(!a.length)return 0;const k=a.length>>1;return a.length%2 ? a[k] :(a[k]+a[k-1])/2;};
  const nameLabel = m => {
    let last=m.id.split('/').pop().replace(/-/g,' ');
    return last.replace(/\b\w/g,c=>c.toUpperCase());
  };
  const kindLabel = v=> ({v5:'OFFICIAL V5',v4_calibrated:'V4 → V5',heuristic:'ESTIMATED'})[v] || v;
  function currentDate(){return state.selectedDate==='latest' ? state.dates[state.dates.length-1] : state.selectedDate;}
  function snapshotFor(date,m){
    if(!date)return null;
    const a=state.history?.by_date?.[date]?.[m.id];
    if(!a)return null;
    return {input:Number(a[0]),output:Number(a[1]),cached:Number(a[2]),score:Number(a[3]),scoreKind:a[4],status:a[5]};
  }
  function buildAllModels(){
    const date=currentDate();
    return state.latest.models.map(m=>{
      const s=snapshotFor(date,m);
      if(!s || !Number.isFinite(s.input)||!Number.isFinite(s.output)||!Number.isFinite(s.cached)||!Number.isFinite(s.score))return null;
      const cost=state.ratio*(1-state.cache)*s.input+state.ratio*state.cache*s.cached+s.output;
      if(!Number.isFinite(cost)||cost<=0)return null;
      return {...m,scoreValue:s.score,cost,px:s,source:s.scoreKind||m.score.kind,status:s.status||m.status,snapshotDate:date};
    }).filter(Boolean);
  }
  function paretoOf(rows){
    const sorted=[...rows].sort((a,b)=>a.cost-b.cost||b.scoreValue-a.scoreValue);
    let high=-Infinity;
    return sorted.filter(m=>{if(m.scoreValue>high+1e-8){high=m.scoreValue;return true}return false;});
  }
  function displayRows(all){
    const statusFiltered=all.filter(m=> !state.availableOnly || !['unavailable','not_listed'].includes(m.status));
    const basePareto=paretoOf(statusFiltered);
    let list=statusFiltered.filter(m=>{
      if(state.provider!=='all' && m.provider!==state.provider)return false;
      if(state.scoreFilter!=='all' && m.source!==state.scoreFilter)return false;
      if(state.search && !(m.id+' '+m.name+' '+m.provider).toLowerCase().includes(state.search))return false;
      return true;
    });
    if(state.mode==='pareto')list=list.filter(m=>basePareto.some(x=>x.id===m.id));
    return {visible:list,frontier:basePareto,base:statusFiltered};
  }
  function providerColor(p){
    const major={'openai':'#b8e885','anthropic':'#f5b182','google':'#91b8fa','qwen':'#6bd9c1','z-ai':'#d69bf2','deepseek':'#e69aaa','moonshotai':'#9ad8e9','minimax':'#f7d28c','meta-llama':'#98a2fa'};
    if(major[p])return major[p];
    let hash=0;for(const c of p)hash=(hash*31+c.charCodeAt(0))|0;
    return sourceColors[Math.abs(hash)%sourceColors.length];
  }
  const formatDate=s=>s ? s.slice(0,10).replace(/-/g,'.'):'—';
  function updateKpis(base,frontier){
    $('kpi-models').textContent=base.length.toLocaleString('en-US');
    $('kpi-frontier').textContent=frontier.length;
    const v5=base.filter(m=>m.score?.kind==='v5').length;
    $('kpi-v5').innerHTML=`${v5} <small>/ ${base.length}</small>`;
    $('kpi-median').textContent=shortFmt(median(base.map(m=>m.cost))).replace(/\.000$/,'');
    $('kpi-models-sub').textContent=`${new Set(base.map(m=>m.provider)).size} 個供應商 · ${base.length} 個可比較路由`;
    $('formula-display').textContent=`${(state.ratio*(1-state.cache)).toFixed(2).replace(/\.00$/,'')} × input + ${(state.ratio*state.cache).toFixed(2).replace(/\.00$/,'')} × cached + output`;
  }
  function updateHeader(){
    const d=state.latest.price_observed_at;
    $('header-date').textContent=formatDate(d)+' DATA';
    $('freshness-date').textContent=formatDate(d);
    const millis=d && Date.parse(d+'T00:00:00Z');
    const days=millis ? Math.round((Date.now()-millis)/(86400*1000)) : 999;
    const live=state.latest.monitoring_active && days<=2;
    const old=state.latest.monitoring_active && days>2;
    $('freshness-orb').className='status-orb '+(live?'':old?'warn':'muted');
    $('freshness-title').textContent=live?'DAILY FEED ACTIVE':old?'DATA OUT OF DATE':'BASELINE SNAPSHOT';
    const aa=state.latest.sources?.artificial_analysis;
    const aaSuffix=aa==='licensing_guard'?' · V5 公開同步受授權限制':aa==='not_configured'?' · V5 未連接 API':aa==='fetch_failed'?' · V5 抓取暫時失敗':aa==='artificial_analysis_free_api'?' · V5 已檢查':'';
    $('freshness-info').textContent=live?'Price now · 每日快照 '+(state.latest.market_observed_at || state.latest.generated_at || '').replace('T',' ').replace('Z',' UTC')+aaSuffix:old?`距上次價格更新 ${days} 天`:'尚未完成 GitHub 定時更新';
  }
  function renderChart(visible,frontier,base){
    const scatter=$('scatter-chart');
    $('visible-count').textContent=visible.length+' POINTS';
    const midCost=median(base.map(m=>m.cost));
    const midScore=median(base.map(m=>m.scoreValue));
    $('chart-median-label').textContent=`MEDIAN INDEX ${numFmt(midScore)} · ${costFmt(midCost)}`;
    if(!visible.length){
      scatter.innerHTML='<div style="padding:110px 12px;text-align:center;color:#829986;font-size:14px">沒有符合篩選條件的模型。請清除搜尋或調整篩選。</div>';
      return;
    }
    const allCosts=visible.map(m=>m.cost).filter(x=>x>0).sort((a,b)=>a-b);
    const lo=0;
    const focusMax=allCosts[Math.max(0,Math.ceil(allCosts.length*.9)-1)]*1.05;
    const hi=state.rangeMode==='full' ? Math.max(...allCosts)*1.05 : state.rangeMax || focusMax;
    $('range-max').value=Number(hi.toPrecision(5));
    const outside=visible.filter(m=>m.cost>hi).length;
    $('range-note').textContent=`線性刻度 · 設定上限 ${costFmt(hi)} · ${outside} 個模型超出上限；可向右平移、調整上限或查看完整範圍。`;
    document.querySelectorAll('[data-range]').forEach(el=>el.classList.toggle('is-active',el.dataset.range===state.rangeMode));
    const ymin=Math.min(0,Math.floor(Math.min(...base.map(m=>m.scoreValue))-6));
    const ymax=Math.max(65,Math.max(...base.map(m=>m.scoreValue))+7);
    const ratioX=Math.max(0,Math.min(1,(midCost-lo)/(hi-lo)));
    const ratioY=Math.max(.09,Math.min(.91,(midScore-ymin)/(ymax-ymin)));
    const lines=[...frontier].sort((a,b)=>a.cost-b.cost);
    const traces=[{
      type:'scatter',mode:'lines',x:lines.map(m=>m.cost),y:lines.map(m=>m.scoreValue),
      line:{color:'#bde978',width:2.4,shape:'hv'},hoverinfo:'skip',showlegend:false,name:'Pareto',opacity:.96
    },{
      type:'scatter',mode:'markers',x:visible.map(m=>m.cost),y:visible.map(m=>m.scoreValue),
      text:visible.map(m=>nameLabel(m)),customdata:visible.map(m=>m.id),
      marker:{color:visible.map(m=>providerColor(m.provider)),size:visible.map(m=>frontier.some(f=>f.id===m.id)?10.7:8.1),
        opacity:.85,line:{width:.55,color:'#172019'}},
      hovertemplate:'<b>%{text}</b><br>Intelligence V5：%{y:.1f}<br>有效成本：$%{x:.6g}<br>點擊查看歷史<extra></extra>',
      showlegend:false,name:'Models'
    }];
    if(state.showLabels){
      const shown=lines.filter(x=>visible.some(y=>y.id===x.id));
      traces.push({type:'scatter',mode:'text',x:shown.map(m=>m.cost),y:shown.map(m=>m.scoreValue),
        text:shown.map(m=>nameLabel(m).slice(0,28)),textposition:'top center',
        textfont:{color:'#d5ebb5',size:9},hoverinfo:'skip',showlegend:false});
    }
    const shapes=[
      {type:'rect',xref:'paper',yref:'paper',x0:0,x1:ratioX,y0:ratioY,y1:1,fillcolor:'#c3e37e',opacity:.055,line:{width:0},layer:'below'},
      {type:'rect',xref:'paper',yref:'paper',x0:ratioX,x1:1,y0:0,y1:ratioY,fillcolor:'#f0a38b',opacity:.03,line:{width:0},layer:'below'},
      {type:'line',xref:'x',x0:midCost,x1:midCost,yref:'paper',y0:0,y1:1,line:{color:'#66816c',width:1,dash:'dot'},layer:'below'},
      {type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:midScore,y1:midScore,line:{color:'#66816c',width:1,dash:'dot'},layer:'below'}
    ];
    const annotations=[
      {xref:'paper',yref:'paper',x:Math.min(.3,ratioX*.5),y:.965,text:'HIGH INTELLIGENCE / LOW COST',showarrow:false,font:{size:8,color:'#769d70'}},
      {xref:'paper',yref:'paper',x:.78,y:.965,text:'HIGH COST / HIGH INTELLIGENCE',showarrow:false,font:{size:8,color:'#69806c'}},
      {xref:'paper',yref:'paper',x:Math.min(.30,ratioX*.48),y:.045,text:'LOW COST / LOWER INDEX',showarrow:false,font:{size:8,color:'#68816b'}},
      {xref:'paper',yref:'paper',x:.79,y:.045,text:'HIGH COST / LOWER INDEX',showarrow:false,font:{size:8,color:'#697d6d'}}
    ];
    const layout={
      paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#9eb3a0',size:11,family:'Inter, system-ui, sans-serif'},
      margin:{l:51,r:20,t:33,b:58},showlegend:false,dragmode:'pan',hovermode:'closest',hoverlabel:{bgcolor:'#27372c',bordercolor:'#56805b',font:{color:'#f4faef',size:12}},
      xaxis:{type:'linear',range:[lo,hi],title:{text:'BLENDED COST · USD / 1M OUTPUT →',font:{size:9,color:'#93a994'},standoff:15},
        gridcolor:'rgba(120,153,120,.10)',zeroline:false,color:'#8a9e8e',tickfont:{size:10},tickformat:'~g',showline:false},
      yaxis:{range:[ymin,ymax],title:{text:'INTELLIGENCE INDEX V5 ↑',font:{size:9,color:'#93a994'},standoff:13},
        gridcolor:'rgba(120,153,120,.10)',zeroline:false,color:'#8a9e8e',tickfont:{size:10},dtick:10,showline:false},
      shapes,annotations,hoverdistance:28,spikedistance:20,uirevision:'dynamic-'+state.selectedDate+'-'+state.ratio+'-'+state.cache+'-'+state.rangeMode+'-'+state.rangeMax+'-'+state.search+'-'+state.provider+'-'+state.scoreFilter+'-'+state.mode
    };
    const cfg={responsive:true,displaylogo:false,toImageButtonOptions:{format:'png',filename:'uberllm-frontier-atlas',scale:2},
      modeBarButtonsToRemove:['lasso2d','select2d','toggleSpikelines'],modeBarButtonsToAdd:[],scrollZoom:true};
    Plotly.react(scatter,traces,layout,cfg).then(()=>{
      if(typeof scatter.removeAllListeners==='function') scatter.removeAllListeners('plotly_click');
      scatter.on('plotly_click',event=>{
        const pt=event?.points?.[0];
        const id=pt?.customdata;
        if(id && typeof id==='string')selectModel(id);
      });
    });
  }
  function renderTable(frontier,view){
    $('pareto-table-count').textContent=frontier.length+' MODELS';
    const table=$('pareto-body');
    const visibleSet=new Set(view.map(m=>m.id));
    const display=frontier.filter(m=>visibleSet.has(m.id));
    table.innerHTML=display.length ? display.map(m=>`<tr data-model-id="${escapeHTML(m.id)}"><td><span class="table-model-name">${escapeHTML(nameLabel(m))}</span><span class="table-model-provider">${escapeHTML(m.provider)}</span></td><td><span class="score-pill">${numFmt(m.scoreValue)}</span></td><td>${costFmt(m.cost)}</td><td class="last-table-col"><span class="method-label">${escapeHTML(kindLabel(m.source))}</span></td></tr>`).join('') : '<tr><td colspan="4" style="color:#819782;padding:24px 8px">目前篩選條件下沒有 Pareto 模型。</td></tr>';
    table.querySelectorAll('tr[data-model-id]').forEach(tr=>tr.addEventListener('click',()=>selectModel(tr.getAttribute('data-model-id'))));
  }
  function selectModel(id){
    state.activeId=id;
    const list=buildAllModels();const m=list.find(m=>m.id===id);
    if(!m)return;
    const isPareto=state.frontier.some(x=>x.id===id);
    const scoreLabel=kindLabel(m.source);
    const p=m.px;
    const src=m.score.source_url && /^https:\/\//.test(m.score.source_url)?m.score.source_url:'https://artificialanalysis.ai/';
    const url=m.model_url && /^https:\/\//.test(m.model_url)?m.model_url:'https://uberllm.dev/';
    const confidence=m.score.confidence || (m.score.kind==='v5'?'measured':'estimated');
    const cacheMsg=({'live_market':'市場最低 cache 價快照','live_catalog':'目錄 cache 價快照','observed':'基準時觀察到的 cache 價','estimated_from_prior_ratio':'依上次輸入/快取比率估計','proxy':'供應商平均折扣代理','assumed_uncached':'假設沒有 cache 折扣'})[m.cache_quality]||m.cache_quality;
    const verified=m.source==='v5';
    $('model-inspector').innerHTML=`
      <h2 class="detail-heading">${escapeHTML(nameLabel(m))}</h2><div class="model-id">${escapeHTML(m.id)}</div>
      <div class="detail-meta"><span class="detail-badge ${verified?'':'badge-estimate'}">${escapeHTML(scoreLabel)}</span>${isPareto?'<span class="detail-badge">PARETO EFFICIENT</span>':''}${m.status==='not_listed'||m.status==='unavailable'?'<span class="detail-badge badge-unavailable">NOT LISTED</span>':''}</div>
      <div class="detail-stats"><div class="detail-stat"><span>V5 EQUIVALENT INDEX</span><strong class="green">${numFmt(m.scoreValue)}</strong></div><div class="detail-stat"><span>BLENDED COST (USD)</span><strong>${costFmt(m.cost)}</strong></div></div>
      <div class="detail-cost-breakdown"><span>INPUT / 1M</span><b>${priceFmt(p.input)}</b><span>CACHED INPUT / 1M</span><b>${priceFmt(p.cached)}</b><span>OUTPUT / 1M</span><b>${priceFmt(p.output)}</b><span>CACHE 品質</span><b>${escapeHTML(cacheMsg)}</b><span>分數信心</span><b>${escapeHTML(confidence)}</b></div>
      <div class="detail-copy"><strong>分數依據：</strong>${escapeHTML(m.score.basis||'—')} ${m.score.uncertainty ? '(參考估計幅度 ±'+numFmt(m.score.uncertainty)+'；非統計信賴區間)':''}</div>
      <a class="detail-link" href="${escapeHTML(url)}" target="_blank" rel="noreferrer">查看 UberLLM 模型 ↗</a><br>
      <a class="detail-link" href="${escapeHTML(src)}" target="_blank" rel="noreferrer">查看分數來源 ↗</a>
      <div class="detail-mini-title">MODEL COST HISTORY <span style="color:#739374;font-size:9px">/ 同一工作負載</span></div><div id="price-trend"></div><div class="trend-info" id="trend-info"></div>`;
    renderTrend(id);
  }
  function renderTrend(id){
    const dates=state.dates;
    const pts=dates.map(d=>{
      const s=state.history.by_date?.[d]?.[id];if(!s)return null;
      const y=state.ratio*(1-state.cache)*s[0]+state.ratio*state.cache*s[2]+s[1];
      return {x:d,y};
    }).filter(v=>v && v.y>0);
    const el=$('price-trend'); if(!el)return;
    $('trend-info').textContent=pts.length<2?'目前只有一日快照，排程上線後將開始累積價格走勢。':`${pts[0].x} ～ ${pts[pts.length-1].x} · 共 ${pts.length} 個快照`;
    Plotly.react(el,[{type:'scatter',mode:'lines+markers',x:pts.map(p=>p.x),y:pts.map(p=>p.y),
      line:{color:'#c9f785',width:2.4,shape:'linear'},marker:{color:'#c9f785',size:5},
      fill:'tozeroy',fillcolor:'rgba(197,239,117,.08)',hovertemplate:'%{x}<br>$%{y:.4f}<extra></extra>'}],{
        paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',margin:{l:52,r:8,t:10,b:32},showlegend:false,
        font:{color:'#829886',size:9},xaxis:{type:'date',gridcolor:'#2b3b2f',tickfont:{size:8}},yaxis:{gridcolor:'#2b3b2f',tickfont:{size:9},rangemode:'tozero',tickprefix:'$'},
        hoverlabel:{bgcolor:'#263b2d',font:{size:10}}},{responsive:true,displayModeBar:false});
  }
  function renderEvents(){
    const items=state.events.items||[];
    if(!items.length)return;
    $('activity-list').innerHTML=items.slice(0,7).map(e=>{
      const type=e.type==='new_v5'?'V5 發布':e.type==='v5_revised'?'V5 更新':e.type==='new_model'?'新模型':e.type==='price_change'?'價格變動':'指數版本';
      return `<div class="event-item"><div class="event-time">${escapeHTML(e.date)} <span class="event-type ${e.type==='price_change'?'price':''}">${type}</span></div><div class="event-title">${escapeHTML(e.model_id)}</div><div class="event-note">${escapeHTML(e.note||'')}</div></div>`;
    }).join('');
  }
  function update(){
    if(!state.latest)return;
    const all=buildAllModels();const {visible,frontier,base}=displayRows(all);
    state.view=visible;state.frontier=frontier;
    updateKpis(base,frontier);renderChart(visible,frontier,base);renderTable(frontier,visible);
    if(state.activeId)selectModel(state.activeId);
  }
  function setHandlers(){
    document.querySelectorAll('[data-range]').forEach(el=>el.addEventListener('click',()=>{
      state.rangeMode=el.dataset.range;state.rangeMax=null;update();
    }));
    function applyRange(){
      const n=Number($('range-max').value);
      if(Number.isFinite(n)&&n>0){state.rangeMode='custom';state.rangeMax=n;}
      update();
    }
    $('range-apply').addEventListener('click',applyRange);
    $('range-max').addEventListener('keydown',e=>{if(e.key==='Enter')applyRange();});
    $('provider-select').addEventListener('change',e=>{state.provider=e.target.value;update();});
    $('score-filter').addEventListener('change',e=>{state.scoreFilter=e.target.value;update();});
    $('model-search').addEventListener('input',e=>{state.search=e.target.value.trim().toLowerCase();update();});
    $('ratio-input').addEventListener('change',e=>{let n=Number(e.target.value);state.ratio=Number.isFinite(n)?Math.max(0,Math.min(2000,n)):150;e.target.value=state.ratio;update();});
    $('cache-slider').addEventListener('input',e=>{state.cache=Number(e.target.value)/100;$('cache-percent').textContent=e.target.value+'%';update();});
    $('date-select').addEventListener('change',e=>{state.selectedDate=e.target.value;update();});
    $('available-only').addEventListener('change',e=>{state.availableOnly=e.target.checked;update();});
    $('labels-toggle').addEventListener('change',e=>{state.showLabels=e.target.checked;update();});
    document.querySelectorAll('.chip[data-mode]').forEach(el=>el.addEventListener('click',()=>{
      state.mode=el.getAttribute('data-mode');document.querySelectorAll('.chip[data-mode]').forEach(n=>n.classList.toggle('is-active',n===el));update();
    }));
    $('reset-btn').addEventListener('click',()=>{
      state.provider='all';state.scoreFilter='all';state.search='';state.ratio=150;state.cache=.9;state.mode='all';state.rangeMode='focus';state.rangeMax=null;state.selectedDate='latest';state.availableOnly=true;state.showLabels=false;
      $('provider-select').value='all';$('score-filter').value='all';$('model-search').value='';$('ratio-input').value=150;$('cache-slider').value=90;$('cache-percent').textContent='90%';$('date-select').value='latest';$('available-only').checked=true;$('labels-toggle').checked=false;
      document.querySelectorAll('.chip[data-mode]').forEach(x=>x.classList.toggle('is-active',x.dataset.mode==='all'));update();
    });
    $('reload-btn').addEventListener('click',()=>location.reload());
    $('csv-btn').addEventListener('click',()=>{
      const cols=['model_id','provider','intelligence_v5_equiv','score_source','input_per_1m','cached_input_per_1m','output_per_1m','blended_cost_usd','cache_source'];
      const lines=[cols,...state.view.map(m=>[m.id,m.provider,m.scoreValue,m.source,m.px.input,m.px.cached,m.px.output,m.cost,m.cache_quality])];
      const csv=lines.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\n');
      const href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
      const a=document.createElement('a');a.href=href;a.download=`uberllm-frontier-${currentDate()||'snapshot'}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
    });
  }
  async function loadData(){
    const boot=window.FRONTIER_BOOTSTRAP;
    const out={...boot};
    try{
      const nonce='?v='+Date.now();
      const sources=await Promise.all(['latest','history','events'].map(n=>fetch(`data/${n}.json${nonce}`,{cache:'no-store'})));
      if(sources.some(x=>!x.ok))throw new Error('One or more data files unavailable');
      const values=await Promise.all(sources.map(x=>x.json()));
      if(!values[0]?.models?.length||!values[1]?.by_date)throw new Error('Invalid snapshot JSON');
      [out.latest,out.history,out.events]=values;
    }catch(err){
      console.info('Loaded baseline fallback. Use HTTP server for dynamic snapshots.',err);
    }
    return out;
  }
  async function init(){
    const data=await loadData();
    state.latest=data.latest;state.history=data.history;state.events=data.events;
    state.dates=(data.history.dates || Object.keys(data.history.by_date||{})).sort();
    if(!state.latest?.models?.length){$('scatter-chart').textContent='讀取失敗：缺少價格資料';return;}
    const providers=[...new Set(state.latest.models.map(m=>m.provider))].sort();
    for(const p of providers){const opt=document.createElement('option');opt.value=p;opt.textContent=p;$('provider-select').appendChild(opt);}
    for(const d of [...state.dates].reverse()){
      const opt=document.createElement('option');opt.value=d;opt.textContent=d;$('date-select').appendChild(opt);
    }
    setHandlers();updateHeader();renderEvents();update();
    // Select highest intelligence Pareto point by default to demonstrate inspector.
    if(state.frontier.length){const last=state.frontier[state.frontier.length-1];selectModel(last.id);}
  }
  init().catch(err=>{console.error(err);$('scatter-chart').textContent='圖表暫時無法顯示：'+String(err);});
})();
