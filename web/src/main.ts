import {Deck, MapView, WebMercatorViewport, type Layer} from '@deck.gl/core';
import {GeoJsonLayer} from '@deck.gl/layers';
import area from '@turf/area';
import bboxPolygon from '@turf/bbox-polygon';
import buffer from '@turf/buffer';
import {analysisBitmap, basemap, footprints, terrain, surfaceTerrain} from './layers';
import type {BBox,Run,Scene,Stats,Surface} from './types';
import './style.css';

const $ = <T extends HTMLElement=HTMLElement>(id:string) => document.getElementById(id) as T;
const state = {provider:'demo',bbox:[-44.75,-22.5,-44.55,-22.3] as BBox,scenes:[] as Scene[],
  selected:undefined as Scene|undefined,run:undefined as Run|undefined,index:'ndvi',maxCloud:100,
  surface:undefined as Surface|undefined,opacity:.87,terrain:false,footprints:true,base:true,buffer:0,busy:false};
let requestNumber=0;
let analysisNumber=0;

$('app').innerHTML = `
  <header class="topbar"><a class="brand" href="/" aria-label="RSLIB home"><span class="brand-icon">◈</span>RSLIB<span class="brand-version"> / 0.1</span></a><span class="product-label">EARTH OBSERVATION WORKBENCH</span><div class="header-right"><span class="signal"></span><span id="connection">Connecting</span><a href="/workflows.html">Optical analysis</a><a href="/showcase/" target="_blank" rel="noopener">Development captures</a><a href="/docs" target="_blank" rel="noopener">API ↗</a><button id="sources-open" class="quiet">Sources ↗</button></div></header>
  <div class="workspace">
  <aside class="left-panel"><div class="panel-title"><span>01 / DISCOVER</span><span class="eyebrow">STAC</span></div>
    <div class="workspace-name"><h1>Scene explorer</h1><p>Search a catalog and inspect a masked raster preview.</p></div>
    <form id="search-form"><label>Data connection<select id="provider"><option value="demo">Synthetic demonstration</option><option value="earth-search">Earth Search · AWS Open Data</option><option value="planetary-computer">Microsoft Planetary Computer</option></select></label>
    <label>Collection<select id="collection"><option value="rslib-demo">Synthetic multispectral fixture</option></select></label>
    <label>Area of interest <span class="field-hint">WGS84 · W,S,E,N</span><input id="bbox" value="-44.75, -22.5, -44.55, -22.3" spellcheck="false" required aria-label="Bounding box west south east north"></label>
    <div class="aoi-summary"><span class="aoi-dot"></span><span id="aoi-area">— km²</span><button id="use-view" type="button" class="text-button">Use map extent ↙</button></div>
    <div class="date-row"><label>From<input id="date-start" type="date" value="2026-06-01"></label><label>To<input id="date-end" type="date" value="2026-08-01"></label></div>
    <label class="slider-label">Maximum scene cloud <output id="cloud-value">100%</output><input id="cloud" type="range" min="0" max="100" value="100"></label>
    <label class="check-label"><input id="date-enabled" type="checkbox" checked>Apply date and cloud filters <span title="Disable both for elevation collections">ⓘ</span></label>
    <button id="search" class="primary" type="submit"><span>Search catalog</span><span>→</span></button>
    </form>
    <div class="section-divider"></div><div class="panel-title"><span>02 / ANALYZE</span><span class="eyebrow">OPTICAL</span></div>
    <div class="index-grid" role="group" aria-label="Analysis index"><button data-index="ndvi" class="active">NDVI<span>Vegetation</span></button><button data-index="ndmi">NDMI<span>Moisture</span></button><button data-index="nbr">NBR<span>Burn response</span></button><button data-index="evi">EVI<span>Vegetation</span></button><button data-index="rgb">RGB<span>True color</span></button></div>
    <label>Mask buffer <span class="field-hint">output pixels</span><select id="mask-buffer"><option value="0">0 pixels</option><option value="1" selected>1 pixel · conservative</option><option value="2">2 pixels</option><option value="4">4 pixels</option></select></label>
    <button id="analyze" class="secondary" disabled>Run analysis <span>↗</span></button>
    <p class="small muted">Bounded COG reads. Band calibration and pixel QA retained in every report.</p>
    <button id="hydro-open" class="hydro-link"><span>◩</span><div>Rainfall & slope laboratory<small>Native Rust · reference equations</small></div><span>↗</span></button>
    <div class="panel-bottom"><span class="signal"></span>LOCAL WORKSPACE<span>EPSG:4326</span></div>
  </aside>
  <main class="map-panel"><div id="map" aria-label="Interactive geospatial map"></div><div class="map-heading"><span class="map-chip"><i></i> AOI / WGS84</span><span id="mode-badge" class="demo-chip">SYNTHETIC DEMO</span></div>
    <div class="map-toolbar"><button id="home-view" title="Fit area of interest" aria-label="Fit area of interest">⌖</button><button id="view-3d" title="Toggle terrain" aria-label="Toggle 3D terrain">3D</button><button id="layers-open" title="Layer controls" aria-label="Toggle layer controls">▱</button></div>
    <div id="layers-panel" class="layers-panel" hidden><h3>Layer stack</h3><label class="check-label"><input id="footprints-toggle" type="checkbox" checked>Scene footprints</label><label class="check-label"><input id="base-toggle" type="checkbox" checked>OpenStreetMap</label><label>Analysis opacity<input id="opacity" type="range" min="0" max="100" value="87"></label><label>AOI buffer<input id="aoi-buffer" type="range" min="0" max="3000" step="100" value="0"><output id="buffer-value">0 m</output></label><p class="small muted">Buffer is a visual planning overlay; the search uses the bounding box.</p></div>
    <div id="map-empty" class="map-empty" hidden><span>◈</span><strong>Map rendering unavailable</strong><p>Search, analysis and reports remain available. Enable WebGL2 to display the map.</p></div>
    <div class="map-bottom"><div class="legend"><div class="legend-title"><span id="legend-name">NDVI / VEGETATION</span><span id="legend-detail">Clear pixels only</span></div><div class="legend-gradient"></div><div class="legend-ticks"><span>−1.0</span><span>0.0</span><span>+1.0</span></div></div><div class="attribution">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a><br><span id="terrain-credit" hidden>Terrain: <a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md" target="_blank" rel="noopener">Mapzen / Tilezen & sources</a></span><span id="coordinates">44.6500° W · 22.4000° S</span></div></div>
    <div id="progress" role="status" class="progress" hidden><span class="spinner"></span><span id="progress-text">Working…</span></div>
  </main>
  <aside class="right-panel"><div class="panel-title"><span>OBSERVATION STACK</span><span id="scene-count" class="count">0</span></div><div class="stack-description"><span id="stack-title">Multispectral exploration</span><span id="search-note" class="small muted">Select an observation to begin</span></div>
    <div id="scene-list" class="scene-list" aria-label="Scene results"></div>
    <div class="inspector"><div class="panel-title"><span>PREVIEW STATISTICS</span><span id="run-state" class="status-tag">IDLE</span></div><h2 id="inspector-title">NDVI</h2><div class="main-stat"><span id="mean-stat">—</span><small id="mean-label">MEAN NDVI</small></div><div class="stats-grid"><div><span>Valid sampled pixels</span><strong id="clear-stat">—</strong></div><div><span>Processing time</span><strong id="time-stat">—</strong></div></div>
    <div id="distribution" class="distribution"><span>Run an analysis to inspect the sampled distribution.</span></div>
    <p id="sampling-note" class="small muted">Statistics describe the preview grid. Export preserves its georeferencing and provenance.</p>
    <div id="exports" class="exports" hidden><a id="report-link" target="_blank" rel="noopener">Analysis report ↗</a><a id="cog-link" download>Export COG ↓</a><a id="manifest-link" download>Provenance JSON ↓</a></div>
    </div><div class="science-note"><span>◉</span><p><strong>Sampling method</strong><br>Scene cloud cover ranks acquisitions. Pixel masks govern the analysis. Preview statistics are sampled estimates.</p></div>
  </aside></div>
  <footer><span>RSLIB <span class="muted">/ SCENE EXPLORER</span></span><span id="footer-status">Ready</span><span>SAMPLED PREVIEW</span></footer>
  <div id="toast" role="alert" hidden></div>
  <dialog id="sources-dialog"><div class="dialog-heading"><span class="eyebrow">OPEN DATA / PROVENANCE</span><button data-close="sources-dialog" aria-label="Close sources">×</button></div><h2>Data sources</h2><p>Catalog access, resolution and processing limitations.</p><div id="source-cards"></div></dialog>
  <dialog id="hydro-dialog"><div class="dialog-heading"><span class="eyebrow">RSLIB HYDRO / NATIVE RUST</span><button data-close="hydro-dialog" aria-label="Close laboratory">×</button></div><h2>Infiltration and slope stability</h2><p>Hypothetical wet-initial-condition column. Finite 3 m basal boundary, 32° slope, 1.5 m water table. This is a research scenario.</p><label>Rainfall intensity <span class="field-hint">mm/hour · 6-hour pulse</span><input id="rainfall" type="number" min="0" max="300" step="1" value="18"></label><button id="hydro-run" class="primary">Simulate storm →</button><div id="hydro-result"><p class="muted">USGS equations implemented in Rust: transient pressure diffusion and infinite-slope stress balance.</p></div><p class="small muted">Saturated/tension-saturated model. Unsaturated coupling is not implemented. Critical depth/time are sampled; these results are not a validated hazard forecast.</p></dialog>`;

async function api<T>(path:string,body?:unknown):Promise<T> {
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let message=`Request failed (${response.status})`;try {const e=await response.json(); message=typeof e.detail==='string'?e.detail:JSON.stringify(e.detail);}catch{/* use status */}throw new Error(message);}
  return response.json() as Promise<T>;
}
function toast(message:string){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,9000);}
function busy(value:boolean,text='Working…') {state.busy=value;$('progress').hidden=!value;$('progress-text').textContent=text;$<HTMLButtonElement>('analyze').disabled=value||!state.selected;$<HTMLButtonElement>('search').disabled=value;$<HTMLSelectElement>('provider').disabled=value;$<HTMLSelectElement>('collection').disabled=value;$<HTMLInputElement>('bbox').disabled=value;document.querySelectorAll<HTMLButtonElement>('[data-index]').forEach(b=>b.disabled=value);$('footer-status').textContent=value?text:'Ready';}
function readBBox():BBox {
  const values=$<HTMLInputElement>('bbox').value.split(',').map(Number);
  if(values.length!==4||!values.every(Number.isFinite)||values[0]>=values[2]||values[1]>=values[3]||values[0]<-180||values[2]>180||values[1]<-85||values[3]>85)throw new Error('Use a valid WGS84 bounding box: west, south, east, north. Split antimeridian areas.');
  return values as BBox;
}
let deck:Deck<MapView>|undefined;
let view={longitude:-44.65,latitude:-22.4,zoom:11,pitch:0,bearing:0};
function fitAOI(){if(!deck)return;const el=$('map');const fitted=new WebMercatorViewport({width:el.clientWidth,height:el.clientHeight}).fitBounds([[state.bbox[0],state.bbox[1]],[state.bbox[2],state.bbox[3]]],{padding:70});view={...view,longitude:fitted.longitude,latitude:fitted.latitude,zoom:Math.min(16,fitted.zoom)};deck.setProps({initialViewState:view});}
function layers(){
  const outline=bboxPolygon(state.bbox);
  $('aoi-area').textContent=`${(area(outline)/1e6).toFixed(1)} km²`;
  const mesh=state.terrain&&state.surface&&state.run&&JSON.stringify(state.surface.bbox)===JSON.stringify(state.bbox);
  const list:Layer[]=[basemap(state.base&&!state.terrain),terrain(state.terrain&&!mesh)];
  if(mesh)list.push(surfaceTerrain(state.surface!.elevation_url,state.run!.preview_url,state.bbox,state.opacity));
  else if(state.run&&!state.terrain)list.push(analysisBitmap(state.run.preview_url,state.bbox,state.opacity,false));
  if(state.footprints)list.push(footprints(state.scenes,$<HTMLInputElement>('date-enabled').checked?state.maxCloud:101,state.selected?.id,selectScene));
  if(state.buffer){const buffered=buffer(outline,state.buffer,{units:'meters'});if(buffered)list.push(new GeoJsonLayer({id:'aoi-buffer',data:buffered,filled:true,getFillColor:[176,232,198,12],getLineColor:[176,232,198,90],lineWidthMinPixels:1}));}
  list.push(new GeoJsonLayer({id:'aoi',data:outline,filled:false,getLineColor:[203,241,173,255],lineWidthMinPixels:2}));
  deck?.setProps({layers:list});
}
function clearRun(){analysisNumber++;state.run=undefined;$('mean-stat').textContent='—';$('clear-stat').textContent='—';$('time-stat').textContent='—';$('run-state').textContent='IDLE';$('exports').hidden=true;$('distribution').textContent='Run an analysis to inspect the sampled distribution.';}
function selectScene(scene:Scene){if(state.selected?.id!==scene.id)clearRun();state.selected=scene;renderScenes();$<HTMLButtonElement>('analyze').disabled=state.busy;layers();}
function renderScenes(){
  const container=$('scene-list');container.replaceChildren();
  const visible=state.scenes.filter(s=>!$<HTMLInputElement>('date-enabled').checked||(s.properties?.['eo:cloud_cover']??101)<=state.maxCloud);
  $('scene-count').textContent=String(visible.length);
  if(!visible.length){const p=document.createElement('p');p.className='empty-results';p.textContent='No observations match these filters. Adjust the AOI, dates or cloud threshold.';container.append(p);}
  visible.forEach(s=>{const button=document.createElement('button');button.className=`scene ${s.id===state.selected?.id?'selected':''}`;const cloud=s.properties?.['eo:cloud_cover'];

    const desc=document.createElement('span');desc.className='scene-description';const title=document.createElement('strong');title.textContent=(s.properties?.datetime??'Undated').slice(0,10);const subtitle=document.createElement('small');subtitle.textContent=s.id;desc.append(title,subtitle);
    const quality=document.createElement('span');quality.className='scene-cloud';quality.textContent=cloud===undefined?'—':`${cloud.toFixed(1)}%`;quality.title='Scene-wide cloud cover';button.append(desc,quality);button.onclick=()=>selectScene(s);container.append(button);});
}
function showRun(run:Run){state.run=run;const stats='valid_fraction' in run.statistics?run.statistics as Stats:(run.statistics as Record<string,Stats>).red;
  $('mean-stat').textContent=stats.mean===null?'No clear pixels':stats.mean.toFixed(3);$('clear-stat').textContent=`${(stats.valid_fraction*100).toFixed(1)}%`;$('time-stat').textContent=`${run.elapsed_seconds.toFixed(2)} s`;$('run-state').textContent='EXPORTED';$('exports').hidden=false;
  $<HTMLAnchorElement>('report-link').href=run.report_url;$<HTMLAnchorElement>('cog-link').href=run.cog_url;$<HTMLAnchorElement>('manifest-link').href=run.manifest_url;
  $('sampling-note').textContent=run.sampling;const dist=$('distribution');dist.replaceChildren();const range=document.createElement('div');range.className='range-track';if(stats.p05!==null&&stats.p95!==null){const band=document.createElement('div');band.className='range-band';band.style.left=`${Math.max(0,(stats.p05+1)*50)}%`;band.style.width=`${Math.min(100,Math.max(1,(stats.p95-stats.p05)*50))}%`;range.append(band);}const text=document.createElement('span');text.textContent=`P05 ${stats.p05?.toFixed(3)??'—'}    ·    Median ${stats.median?.toFixed(3)??'—'}    ·    P95 ${stats.p95?.toFixed(3)??'—'}`;dist.append(range,text);layers();}

async function loadDemo(){state.provider='demo';const result=await api<{features:Scene[]}>('/api/demo');state.scenes=result.features;state.selected=undefined;clearRun();if(state.scenes[0])selectScene(state.scenes[0]);renderScenes();layers();}
$<HTMLSelectElement>('provider').onchange=async()=>{
  const provider=$<HTMLSelectElement>('provider').value;const number=++requestNumber;state.provider=provider;state.scenes=[];state.selected=undefined;clearRun();renderScenes();layers();$('mode-badge').textContent=provider==='demo'?'SYNTHETIC DEMO':'LIVE CATALOG';
  busy(true,'Discovering collections…');
  try{if(provider==='demo'){await loadDemo();$<HTMLSelectElement>('collection').replaceChildren(new Option('Synthetic multispectral fixture','rslib-demo'));}
    else{const result=await api<{collections:{id:string;title:string}[]}>(`/api/collections/${provider}`);if(number!==requestNumber)return;const select=$<HTMLSelectElement>('collection');select.replaceChildren(...result.collections.map(c=>new Option(c.title,c.id)));const preferred=provider==='earth-search'?'sentinel-2-c1-l2a':'sentinel-2-l2a';if(result.collections.some(c=>c.id===preferred))select.value=preferred;}}
  catch(e){toast(String(e));}finally{if(number===requestNumber)busy(false);}
};
$<HTMLFormElement>('search-form').onsubmit=async e=>{e.preventDefault();busy(true,'Searching STAC catalog…');const number=++requestNumber;
  try{state.bbox=readBBox();clearRun();if(state.provider==='demo'){await loadDemo();$('search-note').textContent='3 fixture timestamps · identical synthetic raster';}
    else{const dates=$<HTMLInputElement>('date-enabled').checked;const start=$<HTMLInputElement>('date-start').value;const end=$<HTMLInputElement>('date-end').value;if(dates&&(!start||!end||start>end))throw new Error('Choose a valid date interval.');
      const result=await api<{features:Scene[];rslib:{truncated:boolean;stop_reason:string;examined:number;coverage_plan?:{selected:{id:string}[];sampled_footprint_coverage:number}}}>('/api/search',{provider:state.provider,collections:[$<HTMLSelectElement>('collection').value],bbox:{west:state.bbox[0],south:state.bbox[1],east:state.bbox[2],north:state.bbox[3]},datetime:dates?`${start}T00:00:00Z/${end}T23:59:59Z`:null,max_cloud:dates?state.maxCloud:null,max_items:50,max_pages:10});if(number!==requestNumber)return;state.scenes=result.features;state.selected=undefined;const proposed=result.rslib.coverage_plan?.selected[0]?.id;const first=state.scenes.find(s=>s.id===proposed)??state.scenes[0];if(first)selectScene(first);$('search-note').textContent=`${result.rslib.examined} examined${result.rslib.truncated?' · bounded: '+result.rslib.stop_reason:''} · plan ${((result.rslib.coverage_plan?.sampled_footprint_coverage??0)*100).toFixed(0)}% footprint`;renderScenes();}
    fitAOI();layers();}catch(error){toast(String(error));}finally{if(number===requestNumber)busy(false);}};
$('analyze').onclick=async()=>{if(!state.selected)return;const number=++analysisNumber;busy(true,'Reading COG windows & masking pixels…');
  try{const b=state.bbox;const run=await api<Run>('/api/analyze',{provider:state.provider,collection:state.selected.collection,item_id:state.selected.id,bbox:{west:b[0],south:b[1],east:b[2],north:b[3]},index:state.index,size:512,cloud_buffer:Number($<HTMLSelectElement>('mask-buffer').value)});if(number===analysisNumber)showRun(run);}
  catch(error){toast(String(error));}finally{busy(false);}};
document.querySelectorAll<HTMLButtonElement>('[data-index]').forEach(button=>button.onclick=()=>{state.index=button.dataset.index!;clearRun();document.querySelectorAll('[data-index]').forEach(b=>b.classList.toggle('active',b===button));const names:Record<string,string>={ndvi:'NDVI',ndmi:'NDMI',nbr:'NBR',evi:'EVI',rgb:'RGB reflectance'};$('inspector-title').textContent=names[state.index];$('mean-label').textContent=`MEAN ${state.index.toUpperCase()}`;$('legend-name').textContent=state.index.toUpperCase();document.querySelector('.legend')?.classList.toggle('rgb-mode',state.index==='rgb');layers();});
$<HTMLInputElement>('cloud').oninput=e=>{state.maxCloud=Number((e.target as HTMLInputElement).value);$('cloud-value').textContent=`${state.maxCloud}%`;renderScenes();layers();};
$<HTMLInputElement>('date-enabled').onchange=()=>{renderScenes();layers();};
$<HTMLInputElement>('bbox').onchange=()=>{try{state.bbox=readBBox();clearRun();layers();}catch(e){toast(String(e));}};
$('use-view').onclick=()=>{if(!deck)return;const b=new WebMercatorViewport({...view,width:$('map').clientWidth,height:$('map').clientHeight}).getBounds();$<HTMLInputElement>('bbox').value=b.map(v=>v.toFixed(5)).join(', ');state.bbox=readBBox();clearRun();layers();};
$('home-view').onclick=fitAOI;
$('view-3d').onclick=async()=>{
  if(state.busy)return;
  const next=!state.terrain;
  if(next&&state.run&&JSON.stringify(state.surface?.bbox)!==JSON.stringify(state.bbox)){
    busy(true,'Reading Copernicus elevation for the analysis mesh…');
    try{const b=state.bbox;state.surface=await api<Surface>('/api/surface',{bbox:{west:b[0],south:b[1],east:b[2],north:b[3]},size:256});}
    catch(e){toast(String(e));return;}finally{busy(false);}
  }
  state.terrain=next;view={...view,pitch:next?55:0};deck?.setProps({initialViewState:view});$('view-3d').classList.toggle('active',next);$('terrain-credit').hidden=!next;
  if(next&&state.surface){$('terrain-credit').innerHTML='Elevation: <a href="https://registry.opendata.aws/copernicus-dem/" target="_blank" rel="noopener">Copernicus DEM GLO-30</a>';}
  layers();
};
$('layers-open').onclick=()=>$('layers-panel').hidden=!$('layers-panel').hidden;
$<HTMLInputElement>('footprints-toggle').onchange=e=>{state.footprints=(e.target as HTMLInputElement).checked;layers();};
$<HTMLInputElement>('base-toggle').onchange=e=>{state.base=(e.target as HTMLInputElement).checked;layers();};
$<HTMLInputElement>('opacity').oninput=e=>{state.opacity=Number((e.target as HTMLInputElement).value)/100;layers();};
$<HTMLInputElement>('aoi-buffer').oninput=e=>{state.buffer=Number((e.target as HTMLInputElement).value);$('buffer-value').textContent=`${state.buffer} m`;layers();};
$('sources-open').onclick=()=>$<HTMLDialogElement>('sources-dialog').showModal();
$('hydro-open').onclick=()=>$<HTMLDialogElement>('hydro-dialog').showModal();
document.querySelectorAll<HTMLButtonElement>('[data-close]').forEach(b=>b.onclick=()=>$<HTMLDialogElement>(b.dataset.close!).close());
$('hydro-run').onclick=async()=>{const button=$<HTMLButtonElement>('hydro-run');button.disabled=true;button.textContent='Computing in Rust…';
  try{const value=Number($<HTMLInputElement>('rainfall').value);const r=await api<{minimum_factor_of_safety:number;critical_depth_m:number;critical_time_s:number;samples:{time_s:number;depth_m:number;factor_of_safety:number}[]}>('/api/hydro/demo',{rainfall_mm_h:value});const target=$('hydro-result');target.replaceChildren();const stat=document.createElement('p');stat.className='hydro-stat';stat.textContent=`Minimum FS ${r.minimum_factor_of_safety.toFixed(3)}`;const description=document.createElement('p');description.textContent=`At ${r.critical_depth_m.toFixed(2)} m depth, ${(r.critical_time_s/3600).toFixed(1)} hours. Hypothetical scenario.`;target.append(stat,description);const chart=document.createElement('div');chart.className='hydro-chart';const times=[...new Set(r.samples.map(s=>s.time_s))];times.forEach(t=>{const fs=Math.min(...r.samples.filter(s=>s.time_s===t).map(s=>s.factor_of_safety));const bar=document.createElement('div');bar.style.height=`${Math.min(100,Math.max(2,fs*35))}%`;bar.style.background=fs<1?'#d39a6b':'#88c8a0';bar.title=`${t/3600} h: min FS ${fs.toFixed(3)}`;chart.append(bar);});target.append(chart);}
  catch(e){toast(String(e));}finally{button.disabled=false;button.textContent='Simulate storm →';}};

async function boot(){
  try{deck=new Deck({parent:$<HTMLDivElement>('map'),views:new MapView({repeat:true}),initialViewState:view,controller:true,
    getTooltip:info=>info.object?.id?{text:String(info.object.id),style:{backgroundColor:'#142a21',color:'#dbeadd'}}:null,
    onViewStateChange:({viewState})=>{view={...view,...viewState};},
    onHover:info=>{if(info.coordinate)$('coordinates').textContent=`${info.coordinate[0].toFixed(4)}°, ${info.coordinate[1].toFixed(4)}°`;},
    onError:error=>{$('map-empty').hidden=false;console.error(error);},layers:[]});}
  catch(e){$('map-empty').hidden=false;console.error(e);}
  try{await api('/api/health');$('connection').textContent='Local engine connected';await loadDemo();fitAOI();$('search-note').textContent='3 fixture timestamps · identical synthetic raster';
    const r=await api<{sources:{title:string;kind:string;resolution:string;access:string;url:string;attribution:string}[]}>('/api/sources');r.sources.forEach(s=>{const card=document.createElement('article');const title=document.createElement('a');title.href=s.url;title.target='_blank';title.rel='noopener';title.textContent=s.title+' ↗';const p=document.createElement('p');p.textContent=`${s.kind} · ${s.resolution} · ${s.access}`;const credit=document.createElement('small');credit.textContent=s.attribution;card.append(title,p,credit);$('source-cards').append(card);});
    $<HTMLButtonElement>('analyze').click();
  }catch(e){$('connection').textContent='Engine unavailable';toast(String(e));}
}
void boot();
