const DATA='../export/';
const $=s=>document.querySelector(s);
const escHTML=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const FAMILY_DEFS=[
 {id:'lfi',short:'EG',label:'Extrême gauche',color:'#8F3441',hatch:false,groups:['La France insoumise - Nouveau Front Populaire']},
 {id:'left',short:'G',label:'Gauche',color:'#B85E43',hatch:false,groups:['Écologiste et Social','Socialistes et apparentés','Gauche Démocrate et Républicaine']},
 {id:'center',short:'C',label:'Centre',color:'#D39476',hatch:false,groups:['Ensemble pour la République','Les Démocrates','Horizons & Indépendants']},
 {id:'right',short:'DR',label:'Droite républicaine',color:'#829DA0',hatch:false,groups:['Droite Républicaine']},
 {id:'national',short:'ED',label:'Extrême droite',color:'#4E7883',hatch:false,groups:['Rassemblement National','Union des droites pour la République']},
 {id:'territorial',short:'T',label:'Territoires',color:'#B8BCAE',hatch:false,groups:[]},
 {id:'other',short:'NI',label:'Autres',color:'#EEE8D8',hatch:false,groups:['Non inscrit','Libertés, Indépendants, Outre-mer et Territoires']}
];
const FAMILY_BY_GROUP=new Map(FAMILY_DEFS.flatMap(f=>f.groups.map(g=>[g,f])));
const FAMILY_BY_BLOC=new Map([['lfi',FAMILY_DEFS[0]],['left',FAMILY_DEFS[1]],['centre',FAMILY_DEFS[2]],['right',FAMILY_DEFS[3]],['far_right',FAMILY_DEFS[4]],['other',FAMILY_DEFS[6]]]);
let CURRENT=null,ELECTION=null,HEMICYCLE_LAYOUT=null,PROJECTION=null,PARTISAN=null,DEPARTMENT_DISTANCES=null,distancePromise=null,viewMode='current',partisanChoice=0,map,currentLayer=null,proposalLayer=null,proposalVisible=false,officialRound=2,proposalRound=2,cache={},toastTimer,proposalTransitionTimer,assemblyView="projected",assemblyGroups=new Map(),selectedDepartment="",departments=[],activeDepartmentOption=-1;
let guidedTourActive=false,guidedTourStep=0,guidedTourFrame=0,guidedTourReturnFocus=null;
const GUIDED_TOUR_STEPS=[
  {target:'#map',title:'Commencez par la carte',description:'Chaque contour est une circonscription. Sa couleur montre le résultat du tour sélectionné. Cliquez sur une circonscription pour en voir le détail.'},
  {target:'#view-tomorrow',title:'Une carte électorale mieux équilibrée ?',description:'On cherche un compromis entre trois critères : rapprocher la population des circonscriptions, garder des formes compactes et éviter de séparer les communes d’une même intercommunalité.'},
  {target:'#view-partisan',title:'Et si le découpage favorisait un camp ?',description:'On repart des résultats de 2024 pour chercher une carte où une famille politique pourrait obtenir plus de sièges.'},
  {target:'#partisan-control .scenario-slider-wrap',title:'Choisissez le camp à favoriser',description:''},
  {target:'#department-query',title:'Chercher un département',description:'La carte zoome sur le département choisi.'},
  {target:'#map',title:'Un département à la loupe',description:''}
];
function family(group){return FAMILY_BY_GROUP.get(group)||FAMILY_BY_BLOC.get(group)||FAMILY_DEFS[6]}
async function load(file){const key=file==='election-2024.js'?'election-2024':file==='current-assembly.js'?'current-assembly':file==='hemicycle-layout.js'?'hemicycle-layout':file==='projection-2026.js'?'projection-2026':file==='partisan-scenarios.js'?'partisan-scenarios':file==='department-distances.js'?'department-distances':file.startsWith('maps/')?'map:'+file.split('/')[1].replace('.geojson',''):null;if(!key)throw Error('Donnée inconnue: '+file);if(cache[key])return cache[key];const src=key==='election-2024'?DATA+'browser/election-2024.js?v=12':key==='current-assembly'?DATA+'browser/current-assembly.js':key==='hemicycle-layout'?DATA+'browser/hemicycle-layout.js':key==='projection-2026'?DATA+'browser/projection-2026.js?v=9':key==='partisan-scenarios'?DATA+'browser/partisan-scenarios.js?v=9':key==='department-distances'?DATA+'browser/department-distances.js?v=2':DATA+'browser/maps/'+key.slice(4)+'.js';cache[key]=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=src;script.onload=async()=>{try{const value=await window.REDISTRICTING_DATA?.[key];if(value)resolve(value);else reject(Error('Donnée absente: '+key))}catch(e){reject(e)}};script.onerror=()=>{delete cache[key];reject(Error('Impossible de lire '+src))};document.head.appendChild(script)});return cache[key]}
function metro(feature){const d=String(feature.properties.department||feature.properties.dept||'');return Number(d)<96||d==='2A'||d==='2B'}
function seatsLeftToRight(layout){const probe=document.createElementNS('http://www.w3.org/2000/svg','svg');probe.setAttribute('viewBox',layout.viewBox);probe.style.cssText='position:absolute;left:-10000px;top:0;width:1000px;height:700px;overflow:visible';const measured=layout.seats.map(seat=>{const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',seat.path);path.setAttribute('transform',seat.transform||'');probe.appendChild(path);return {seat,path}});document.body.appendChild(probe);const ordered=measured.map(({seat,path})=>{const box=path.getBBox();return {seat,x:box.x+box.width/2}}).sort((a,b)=>a.x-b.x).map(item=>item.seat);probe.remove();return ordered}
function addHatches(layer){const paths=layer.getLayers().filter(l=>l._path),root=paths[0]?._path?.ownerSVGElement;if(!root)return;let defs=root.querySelector('#family-hatches');if(!defs){defs=document.createElementNS('http://www.w3.org/2000/svg','defs');defs.id='family-hatches';root.prepend(defs);FAMILY_DEFS.filter(f=>f.hatch).forEach(f=>{const pat=document.createElementNS('http://www.w3.org/2000/svg','pattern');pat.id='family-'+f.id;pat.setAttribute('patternUnits','userSpaceOnUse');pat.setAttribute('width','16');pat.setAttribute('height','16');const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('width','16');rect.setAttribute('height','16');rect.setAttribute('fill',f.color);pat.appendChild(rect);const stroke=document.createElementNS('http://www.w3.org/2000/svg','path');stroke.setAttribute('d','M-4 16L16-4M4 20L20 4');stroke.setAttribute('stroke','#f5eddd');stroke.setAttribute('stroke-opacity','.17');stroke.setAttribute('stroke-width','.45');pat.appendChild(stroke);defs.appendChild(pat)})}for(const item of paths){const f=family(item.feature.properties.bloc||item.feature.properties.group);if(f.hatch&&(!selectedDepartment||departmentCode(item.feature)===selectedDepartment))item._path.style.fill='url(#family-'+f.id+')'}}
function localDistrictNumber(properties){if(properties.district_number!==undefined&&properties.district_number!==null){const value=Number(properties.district_number);if(Number.isFinite(value)&&value>0)return value}if(properties.district!==undefined&&properties.district!==null){const value=Number(properties.district);if(Number.isFinite(value)&&value>=0)return value+1}const department=String(properties.department||properties.dept||''),code=String(properties.code||properties.district_id||'');if(department&&code.startsWith(department)){const suffix=code.slice(department.length),value=Number(suffix);if(suffix&&Number.isFinite(value)&&value>0)return value}const label=String(properties.label||''),match=label.match(/(?:^|\s)(\d+)(?:re|e|ème)?\s+circonscription/i);return match?Number(match[1]):null}
function tooltipContent(properties,projected){const box=document.createElement('div'),dept=String(properties.department||properties.dept||''),deptName=properties.department_name||dept,number=localDistrictNumber(properties),kicker=document.createElement('div');kicker.className='tip-kicker';kicker.textContent=projected?(properties.estimated?deptName:'Données de vote indisponibles · '+deptName):deptName;const name=document.createElement('div');name.className='tip-name';name.textContent=number===null?(properties.label||'Circonscription'):districtLabel(number);box.append(kicker,name);const party=document.createElement('div');party.className='tip-party';if(projected&&proposalRound===2&&properties.round2){const r=properties.round2;party.textContent=r.estimated?'Dans un tirage représentatif : '+family(r.winner_bloc).label:'Estimation du second tour indisponible'}else{party.textContent=projected?(properties.estimated?'Bloc en tête : '+family(properties.bloc).label+' · '+fmtPct(properties.vote_share,1)+' des voix estimées':'Les données de vote ne couvrent pas cette circonscription'):(properties.candidate||'Siège vacant')+' · '+(properties.group_label||'Non inscrit')+' · famille '+family(properties.group).label}box.appendChild(party);return box}
function officialFirstRoundFor(properties){const dept=String(properties.department||properties.dept||''),number=localDistrictNumber(properties);if(!dept||number===null)return null;return PROJECTION?.officialFirstRoundById?.get(dept+'-'+String(number).padStart(2,'0'))||null}
function officialFirstRoundTooltip(properties,result){const box=document.createElement('div'),deptName=properties.department_name||String(properties.department||properties.dept||''),number=localDistrictNumber(properties),kicker=document.createElement('div'),name=document.createElement('div'),detail=document.createElement('div');kicker.className='tip-kicker';kicker.textContent='Résultat officiel · premier tour 2024 · '+deptName;name.className='tip-name';name.textContent=number===null?(properties.label||'Circonscription'):districtLabel(number);detail.className='tip-party';detail.textContent=result?'Bloc en tête : '+family(result.bloc).label+' · '+fmtPct(result.vote_share,1)+' des suffrages exprimés'+(result.margin===null?'':' · avance '+fmtPct(result.margin,1)):'Résultat non disponible pour cette circonscription';box.append(kicker,name,detail);return box}
function paintCurrent(features,fit){
  if(currentLayer)map.removeLayer(currentLayer);
  const shown=features.filter(metro).map(feature=>{
    const result=officialRound===1?officialFirstRoundFor(feature.properties):null;
    const winner=ELECTION.byCode.get(String(feature.properties.code));
    return {...feature,properties:{...feature.properties,bloc:officialRound===1?(result?.bloc||'unknown'):(winner?.bloc||'unknown')}};
  });
  currentLayer=L.geoJSON({type:'FeatureCollection',features:shown},{
    style:f=>({color:'#504735',weight:.52,fillOpacity:.94,fillColor:f.properties.bloc==='unknown'?'#ded4bd':family(f.properties.bloc).color}),
    onEachFeature:(feature,layer)=>{
      const result=officialFirstRoundFor(feature.properties),winner=ELECTION.byCode.get(String(feature.properties.code));
      layer.bindTooltip(officialRound===1?officialFirstRoundTooltip(feature.properties,result):officialSecondRoundTooltip(feature.properties,winner),{sticky:true,direction:'top',offset:[0,-5]});
      layer.on('mouseover',()=>{if(!selectedDepartment||departmentCode(feature)===selectedDepartment)layer.setStyle({weight:1.35,color:'#241f18',fillOpacity:1})});
      layer.on('mouseout',()=>applyDepartmentStyles(currentLayer));
      layer.on('click',e=>handleDistrictClick(e,feature));
    }
  }).addTo(map);
  const rendered=currentLayer;requestAnimationFrame(()=>applyDepartmentStyles(rendered));
  if(fit&&currentLayer.getLayers().length){map.invalidateSize();map.fitBounds(currentLayer.getBounds(),{...mapPadding(),animate:false})}
}
function projectionProperties(feature){const p=feature.properties||{},dept=String(p.department||p.dept||''),number=Number(p.district_number??(Number(p.district)+1)),key=dept+'-'+String(number).padStart(2,'0');return PROJECTION?.districtsById?.get(key)||null}
function signedPoints(value,digits=2){const points=Number(value||0)*100;return (points>0?'+':'')+fmtNum(points,digits)+' pt'}
function renderTerritorialComparison(data){
  const official=data?.official,proposal=data?.proposal;if(!official||!proposal)return;
  const specs=[
    {key:'population_max_abs_deviation_from_national_target',title:'Écart de population à la moyenne nationale, dans la circonscription la plus éloignée',format:v=>fmtPct(v,1),delta:v=>signedPoints(v,1)},
    {key:'compactness_loss_mean_1_minus_polsby_popper',title:'Circonscriptions aux formes allongées ou découpées',format:v=>fmtNum(v,3),delta:v=>(v>0?'+':'')+fmtNum(v,3)},
    {key:'epci_pooled_avoidable_ratio',title:'Fragmentation des intercommunalités',format:v=>fmtPct(v,1),delta:v=>signedPoints(v,1)}
  ];
  $('#territory-grid').innerHTML=specs.map(item=>{
    const before=Number(official[item.key]),after=Number(proposal[item.key]),delta=after-before;
    return '<article class="metric-card '+(Math.abs(delta)<1e-9?'neutral':delta<0?'good':'bad')+'"><h4>'+escHTML(item.title)+'</h4><strong>'+item.format(after)+'</strong><span class="metric-delta">'+item.delta(delta)+' · aujourd’hui '+item.format(before)+'</span></article>';
  }).join('');
}
function renderComparison(projection){
  renderTerritorialComparison(projection.territorial_comparison);
  $('#mmd-grid').innerHTML=['lfi','left','centre','right','far_right','other'].map(block=>{
    const before=projection.official.blocks[block]?.mmd,after=projection.proposal.blocks[block]?.mmd;
    return '<article class="mmd-card"><span><i style="background:'+family(block).color+'"></i>'+escHTML(BLOC_LABELS[block])+'</span><strong>'+(before==null||after==null?'—':signedPoints(after-before,2))+'</strong></article>';
  }).join('');
  renderHemicycle();
}
function applyProposalRound(round){
  proposalRound=round;syncRoundSwitch();if(!proposalLayer)return;
  proposalLayer.eachLayer(layer=>{
    const base=layer.feature.properties,result=base.round2,isSecond=round===2;
    base.bloc=isSecond?(result?.winner_bloc||'unknown'):(base.firstRoundBloc||'unknown');
    layer.setStyle({fillColor:isSecond?(result?.estimated?family(result.winner_bloc).color:'#ded4bd'):(base.estimated?family(base.bloc).color:'#ded4bd'),fillOpacity:.94});
    if(layer._path)layer._path.style.fill='';
    layer.unbindTooltip();layer.bindTooltip(tooltipContent(base,true),{sticky:true,direction:'top',offset:[0,-5]});
  });
  requestAnimationFrame(()=>applyDepartmentStyles(proposalLayer));
}
async function showProposal(){if(proposalVisible){resetCurrent();return}try{[PROJECTION,HEMICYCLE_LAYOUT]=await Promise.all([load('projection-2026.js'),load('hemicycle-layout.js')]);PROJECTION.districtsById=new Map(PROJECTION.districts.map(row=>[row.department+'-'+String(row.district_number).padStart(2,'0'),row]));PROJECTION.officialFirstRoundById=new Map(PROJECTION.official_first_round.map(row=>[row.department+'-'+String(row.district_number).padStart(2,'0'),row]));const roundTwoById=new Map((PROJECTION.round_two?.districts||[]).map(row=>[row.department+'-'+String(row.district_number).padStart(2,'0'),row]));const shown=PROJECTION.map.features.filter(metro).map(feature=>{const result=projectionProperties(feature);return result?{...feature,properties:{...feature.properties,...result,firstRoundBloc:result.bloc,round2:(()=>{const r=roundTwoById.get(String(result.department)+'-'+String(result.district_number).padStart(2,'0'));return r?{...r,winner_bloc:r.representative_winner_bloc}:r})()}}:feature});proposalLayer=L.geoJSON({type:'FeatureCollection',features:shown},{style:f=>({color:'#504735',weight:.48,fillColor:'#ded4bd',fillOpacity:0}),onEachFeature:(f,l)=>{l.bindTooltip(tooltipContent(f.properties,true),{sticky:true,direction:'top',offset:[0,-5]});l.on('click',e=>handleDistrictClick(e,f))}}).addTo(map);requestAnimationFrame(()=>addHatches(proposalLayer));if(currentLayer)currentLayer.setStyle({fillOpacity:.05,opacity:.25});setTimeView(true);$('#results').hidden=false;$('#results-cue').hidden=false;$('#map-scenario').hidden=false;$('#map-scenario').textContent='Scénario exploratoire · votes de 2024';$('#proposal-error').hidden=true;map.invalidateSize();proposalVisible=true;renderComparison(PROJECTION);applyProposalRound(proposalRound);loadDepartmentMapNote();proposalTransitionTimer=setTimeout(()=>{if(!proposalVisible||!proposalLayer)return;if(currentLayer){map.removeLayer(currentLayer);currentLayer=null}if(selectedDepartment)applyDepartmentStyles(proposalLayer);else map.fitBounds(proposalLayer.getBounds(),{...mapPadding(),animate:!matchMedia('(prefers-reduced-motion: reduce)').matches,duration:.7})},700)}catch(error){console.error(error);$('#proposal-error').hidden=false;if(proposalLayer){map.removeLayer(proposalLayer);proposalLayer=null}resetCurrent()}}
async function showPartisan(){
  try{
    const [projection,layout,data]=await Promise.all([ensureProjection(),HEMICYCLE_LAYOUT?Promise.resolve(HEMICYCLE_LAYOUT):load('hemicycle-layout.js'),PARTISAN?Promise.resolve(PARTISAN):load('partisan-scenarios.js')]);
    PROJECTION=projection;HEMICYCLE_LAYOUT=layout;PARTISAN=data;
    clearTimeout(proposalTransitionTimer);
    if(proposalLayer)map.removeLayer(proposalLayer);if(currentLayer)map.removeLayer(currentLayer);
    const names=['Extrême gauche','Gauche','Centre','Droite républicaine','Extrême droite'], s=data.scenarios[['lfi','left','centre','right','far_right'][partisanChoice]],changed=new Set(s.changed_departments);
    const originals=CURRENT.features.filter(f=>metro(f)&&!changed.has(departmentCode(f))).map(f=>{const dep=departmentCode(f),number=localDistrictNumber(f.properties);return {...f,properties:{...f.properties,map_id:dep+'-'+String(number).padStart(2,'0')}}});
    const features=originals.concat(s.features.features.filter(metro)).map(f=>{const row=s.districts[f.properties.map_id];return {...f,properties:{...f.properties,estimated:!!row,firstRoundBloc:row?.first_bloc||'unknown',round2:{estimated:!!row?.estimated,winner_bloc:row?.runoff_bloc||'unknown'}}}});
    proposalLayer=L.geoJSON({type:'FeatureCollection',features},{style:()=>({color:'#504735',weight:.48,fillColor:'#ded4bd',fillOpacity:.94}),onEachFeature:(feature,layer)=>{layer.bindTooltip(tooltipContent(feature.properties,true),{sticky:true,direction:'top',offset:[0,-5]});layer.on('click',event=>handleDistrictClick(event,feature))}}).addTo(map);
    const sliderWasHidden=$('#partisan-control').hidden;
    proposalVisible=true;viewMode='partisan';$('#view-today').setAttribute('aria-pressed','false');$('#view-tomorrow').setAttribute('aria-pressed','false');$('#view-partisan').setAttribute('aria-pressed','true');$('#partisan-control').hidden=false;if(sliderWasHidden)map.invalidateSize({pan:false});$('#partisan-slider').setAttribute('aria-valuetext',names[partisanChoice]);document.title='La carte fait loi · Partisane';loadDepartmentMapNote();
    $('#results').hidden=false;$('#results-cue').hidden=false;$('#map-scenario').hidden=false;$('#map-scenario').textContent='Scénario exploratoire · votes de 2024';$('#proposal-error').hidden=true;
    const before=PROJECTION.territorial_comparison.official, after=s.territorial_metrics||{};
    const specs=[{key:'population_max_abs_deviation_from_national_target',title:'Écart de population à la moyenne nationale, dans la circonscription la plus éloignée',format:v=>fmtPct(v,1),delta:v=>signedPoints(v,1)},{key:'compactness_loss_mean_1_minus_polsby_popper',title:'Circonscriptions aux formes allongées ou découpées',format:v=>fmtNum(v,3),delta:v=>(v>0?'+':'')+fmtNum(v,3)},{key:'epci_pooled_avoidable_ratio',title:'Fragmentation des intercommunalités',format:v=>fmtPct(v,1),delta:v=>signedPoints(v,1)}];
    $('#territory-grid').innerHTML=specs.map(item=>{const v=after[item.key];if(v==null)return '<article class="metric-card neutral"><h4>'+item.title+'</h4><strong>Non calculé</strong></article>';const delta=v-before[item.key];return '<article class="metric-card '+(Math.abs(delta)<1e-9?'neutral':delta<0?'good':'bad')+'"><h4>'+item.title+'</h4><strong>'+item.format(v)+'</strong><span class="metric-delta">'+item.delta(delta)+' · aujourd’hui '+item.format(before[item.key])+'</span></article>'}).join('');
    $('#mmd-grid').innerHTML=['lfi','left','centre','right','far_right','other'].map(block=>'<article class="mmd-card"><span><i style="background:'+family(block).color+'"></i>'+escHTML(BLOC_LABELS[block])+'</span><strong>'+(s.mmd_delta?.[block]==null?'—':signedPoints(s.mmd_delta[block],2))+'</strong></article>').join('');
    renderHemicycle();applyProposalRound(proposalRound);if(selectedDepartment)focusDepartment();
  }catch(error){console.error(error);$('#proposal-error').hidden=false}
}
function resetCurrent(){
  clearTimeout(proposalTransitionTimer);
  if(proposalLayer){map.removeLayer(proposalLayer);proposalLayer=null}
  if(currentLayer){map.removeLayer(currentLayer);currentLayer=null}
  proposalVisible=false;paintCurrent(CURRENT.features,false);
  setTimeView(false);$('#results').hidden=true;$('#results-cue').hidden=true;$('#map-scenario').hidden=true;renderDepartmentMapNote();map.invalidateSize();syncRoundSwitch();if(selectedDepartment)applyDepartmentStyles(currentLayer);else recenterMap();
  window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}

function districtLabel(number){return number+(number===1?'re':'e')+' circonscription'}
function setTimeView(tomorrow){viewMode=tomorrow?'neutral':'current';$('#view-today').setAttribute('aria-pressed',String(!tomorrow));$('#view-tomorrow').setAttribute('aria-pressed',String(tomorrow));$('#view-partisan').setAttribute('aria-pressed','false');$('#partisan-control').hidden=true;document.title='La carte fait loi · '+(tomorrow?'Neutre':'Actuelle')}
function mapPadding(){
  return {paddingTopLeft:[12,12],paddingBottomRight:[12,46]};
}
function recenterMap(){if(selectedDepartment){clearDepartment();return}const layer=proposalVisible?proposalLayer:currentLayer;if(layer?.getLayers().length){map.invalidateSize();map.fitBounds(layer.getBounds(),{...mapPadding(),animate:!matchMedia('(prefers-reduced-motion: reduce)').matches,duration:.6})}}
function syncRoundSwitch(){
  const round=proposalVisible?proposalRound:officialRound;
  $('#round-first').setAttribute('aria-pressed',String(round===1));$('#round-second').setAttribute('aria-pressed',String(round===2));
  $('#round-switch').classList.toggle('first-selected',round===1);
  $('#round-first').textContent=proposalVisible?'1er tour estimé':'1er tour 2024';
  $('#round-second').textContent=proposalVisible?'2nd tour estimé':'2nd tour 2024';
}
function setMapRound(round){
  if(proposalVisible)applyProposalRound(round);else{officialRound=round;paintCurrent(CURRENT.features,false);syncRoundSwitch()}
}
function officialSecondRoundTooltip(properties,winner){
  const box=document.createElement('div'),kicker=document.createElement('div'),name=document.createElement('div'),detail=document.createElement('div');
  kicker.className='tip-kicker';kicker.textContent=properties.department_name||properties.department;
  name.className='tip-name';name.textContent=districtLabel(localDistrictNumber(properties));
  detail.className='tip-party';detail.textContent=winner?winner.candidate+' · '+BLOC_LABELS[winner.bloc]+(winner.round==='1er tour'?' · élu dès le 1er tour':' · élu au 2nd tour'):'Résultat indisponible';
  box.append(kicker,name,detail);return box;
}
function setAssemblyView(view){assemblyView=view;renderHemicycle()}
function renderHemicycle(){
  const svg=$('#hemicycle'),current=assemblyView==='current',layout=HEMICYCLE_LAYOUT;
  const simulated=viewMode==='partisan'||!current;
  $('#assembly-current').textContent=viewMode==='partisan'?'Carte actuelle (modèle)':'Assemblée actuelle';$('#assembly-projected').textContent=viewMode==='partisan'?'Scénario (modèle)':'Projection';
  $('#assembly-current').setAttribute('aria-pressed',String(current));$('#assembly-projected').setAttribute('aria-pressed',String(!current));
  $('#assembly-switch').classList.toggle('first-selected',current);
  $('#assembly-tooltip').hidden=true;svg.removeAttribute('data-active-bloc');assemblyGroups=new Map();
  svg.setAttribute('viewBox',layout.viewBox);
  const paths=new Map(),add=(bloc,seat)=>{if(!paths.has(bloc))paths.set(bloc,[]);paths.get(bloc).push(seat)};
  if(current && viewMode!=='partisan'){
    const byPlace=new Map(CURRENT.meta.hemicycle.filter(d=>d.place&&d.group).map(d=>[Number(d.place),d]));
    let vacancies=Math.max(0,577-byPlace.size);
    for(const seat of layout.seats){const deputy=byPlace.get(Number(seat.place));if(deputy)add(family(deputy.group).id,seat);else if(vacancies>0){add('vacant',seat);vacancies--}}
    for(const [bloc,seats] of paths){const f=FAMILY_DEFS.find(f=>f.id===bloc);assemblyGroups.set(bloc,{color:f?.color||'#d4c8b1',label:f?.label||'Sièges vacants',detail:fmtNum(seats.length)+' '+(bloc==='vacant'?'sièges vacants':'sièges actuels')})}
  }else{
    const estimates=viewMode==='partisan'?PARTISAN.scenarios[current?'other':['lfi','left','centre','right','far_right'][partisanChoice]].seat_projection:(PROJECTION.round_two?.seat_projection||{}),ordered=seatsLeftToRight(layout).slice(0,577);let index=0;
    for(const bloc of ['lfi','left','centre','right','far_right','other']){
      const row=estimates[bloc];if(!row)continue;
      const count=Math.round((simulated?row.representative:row.seats)||0);for(let i=0;i<count&&index<ordered.length;i++)add(bloc,ordered[index++]);
      assemblyGroups.set(bloc,{color:family(bloc).color,label:BLOC_LABELS[bloc],detail:simulated?fmtNum(row.low)+'–'+fmtNum(row.high)+' sièges simulés':fmtNum(count)+' sièges estimés',range:null});
    }
    while(index<ordered.length)add('unknown',ordered[index++]);
    assemblyGroups.set('unknown',{color:'#d4c8b1',label:'Sans estimation',detail:fmtNum(paths.get('unknown')?.length||0)+' sièges'});
  }
  svg.innerHTML=[...paths].map(([bloc,seats])=>{const info=assemblyGroups.get(bloc),label=info.label+' · '+info.detail+(info.range?' · '+info.range:'');return '<g data-bloc="'+bloc+'" tabindex="0" role="group" aria-label="'+escHTML(label)+'"><title>'+escHTML(label)+'</title>'+seats.map(seat=>'<path class="hemicycle-seat" d="'+escHTML(seat.path)+'" transform="'+escHTML(seat.transform||'')+'" fill="'+info.color+'"/>').join('')+'</g>'}).join('');
  svg.setAttribute('aria-label',current?(viewMode==='partisan'?'Carte actuelle : projection du second tour':'Assemblée actuelle, par famille politique'):'Projection du second tour, par bloc');
}
function bindHemicycleTooltip(){
  const svg=$('#hemicycle'),tip=$('#assembly-tooltip');
  const show=(target,event)=>{
    const group=target.closest?.('[data-bloc]');if(!group)return;
    const info=assemblyGroups.get(group.getAttribute('data-bloc'));if(!info)return;
    tip.innerHTML='<strong>'+escHTML(info.label)+'</strong><span>'+escHTML(info.detail)+'</span>'+(info.range?'<span>'+escHTML(info.range)+'</span>':'');tip.hidden=false;
    positionFloatingTip(tip,event?.clientX!==undefined?{left:event.clientX,right:event.clientX,top:event.clientY-8,bottom:event.clientY+10}:group.getBoundingClientRect());
    svg.setAttribute('data-active-bloc',group.getAttribute('data-bloc'));
    svg.querySelectorAll('[data-bloc]').forEach(node=>{node.style.opacity=node===group?'1':'.3'});
  };
  const clear=()=>{tip.hidden=true;svg.removeAttribute('data-active-bloc');svg.querySelectorAll('[data-bloc]').forEach(node=>{node.style.opacity='1'})};
  svg.addEventListener('pointerover',event=>show(event.target,event));svg.addEventListener('focusin',event=>show(event.target));svg.addEventListener('click',event=>show(event.target,event));
  svg.addEventListener('pointerleave',clear);svg.addEventListener('focusout',event=>{if(!svg.contains(event.relatedTarget))clear()});
}

function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),2600)}
const fmtNum=(value,digits=0)=>Number(value||0).toLocaleString('fr-FR',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const fmtPct=(value,digits=1)=>fmtNum(Number(value||0)*100,digits)+' %';
const BLOC_LABELS={lfi:'Extrême gauche',left:'Gauche',centre:'Centre',right:'Droite républicaine',far_right:'Extrême droite',other:'Autres'};
function positionFloatingTip(tip,rect){
  const bounds=tip.getBoundingClientRect(),viewportWidth=window.innerWidth,viewportHeight=window.innerHeight;
  const left=Math.max(10,Math.min(viewportWidth-bounds.width-10,(rect.left+rect.right-bounds.width)/2));
  let top=rect.top-bounds.height-10;
  if(top<10)top=rect.bottom+10;
  top=Math.max(10,Math.min(viewportHeight-bounds.height-10,top));
  tip.style.left=left+'px';tip.style.top=top+'px';
}

function bindInfoDialog(buttonId,dialogId){
  const button=$('#'+buttonId),dialog=$('#'+dialogId),tip=$('#info-tooltip');
  const showHint=()=>{tip.textContent=button.getAttribute('data-tooltip');tip.hidden=false;positionFloatingTip(tip,button.getBoundingClientRect())};
  const hideHint=()=>{tip.hidden=true};
  button.addEventListener('pointerenter',showHint);button.addEventListener('pointerleave',hideHint);
  button.addEventListener('focus',showHint);button.addEventListener('blur',hideHint);
  button.addEventListener('click',()=>{hideHint();dialog.showModal()});
  dialog.addEventListener('click',event=>{
    if(event.target!==dialog)return;
    const rect=dialog.getBoundingClientRect();
    if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();
  });
  dialog.addEventListener('close',()=>button.focus({preventScroll:true}));
}

async function ensureProjection(){
  PROJECTION=PROJECTION||await load('projection-2026.js');
  PROJECTION.officialFirstRoundById=PROJECTION.officialFirstRoundById||new Map(PROJECTION.official_first_round.map(row=>[row.department+'-'+String(row.district_number).padStart(2,'0'),row]));
  return PROJECTION;
}
function ensureDepartmentDistances(){
  if(DEPARTMENT_DISTANCES)return Promise.resolve(DEPARTMENT_DISTANCES);
  if(!distancePromise)distancePromise=load('department-distances.js').then(data=>(DEPARTMENT_DISTANCES=data)).catch(error=>{distancePromise=null;throw error});
  return distancePromise;
}
function visibleProposalDepartmentCount(department){return proposalLayer?.getLayers().filter(layer=>departmentCode(layer.feature)===department).length||0}
function currentDepartmentCount(department){return CURRENT.features.filter(feature=>departmentCode(feature)===department).length}
function activeDepartmentDistance(){
  if(!DEPARTMENT_DISTANCES)return null;
  return viewMode==='neutral'?DEPARTMENT_DISTANCES.maps?.neutral:DEPARTMENT_DISTANCES.partisan?.[['lfi','left','centre','right','far_right'][partisanChoice]];
}
function renderDepartmentMapNote(){
  const panel=$('#map-distance-panel');
  const isProposal=proposalVisible&&(viewMode==='neutral'||viewMode==='partisan');
  panel.hidden=!isProposal||!selectedDepartment;
  if(panel.hidden)return;
  const data=activeDepartmentDistance();
  const name=departments.find(item=>item.code===selectedDepartment)?.name||selectedDepartment;
  const row=data?.departments?.[selectedDepartment];
  const currentCount=currentDepartmentCount(selectedDepartment),proposedCount=visibleProposalDepartmentCount(selectedDepartment);
  $('#map-distance-department-name').textContent=name;
  $('#map-distance-seat-count').textContent=currentCount+' siège'+(currentCount===1?'':'s')+' aujourd’hui · '+proposedCount+' proposé'+(proposedCount===1?'':'s');
  $('#map-distance-department-score').textContent=row?'Moins remanié que '+row.closer_than_percent+' % des départements':data?'Classement non disponible':'Calcul…';
}
function renderDepartmentDistanceCard(unavailable=false){
  const grid=$('#territory-grid');let card=$('#department-distance-card');
  if(!card){card=document.createElement('article');card.id='department-distance-card';card.className='metric-card distance';card.innerHTML='<h4>Distance à la carte actuelle</h4><strong></strong><span class="metric-delta"></span>';grid.append(card)}
  const data=activeDepartmentDistance();
  card.querySelector('strong').textContent=data?fmtPct(data.department_average,1):unavailable?'Indisponible':'Calcul…';
  card.querySelector('.metric-delta').textContent=data?'Moyenne égale des '+data.department_count+' départements · plus bas = plus proche':'Moyenne égale par département';
}
function loadDepartmentMapNote(){
  renderDepartmentMapNote();renderDepartmentDistanceCard();
  ensureDepartmentDistances().then(()=>{renderDepartmentMapNote();renderDepartmentDistanceCard()}).catch(error=>{console.error(error);renderDepartmentDistanceCard(true);if(selectedDepartment)$('#map-distance-department-score').textContent='Classement indisponible'});
}
function departmentCode(feature){return String(feature.properties.department||feature.properties.dept||'')}
function normalizeDepartment(value){return value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr')}
function populateDepartments(){
  const names=new Map(CURRENT.features.filter(metro).map(f=>[departmentCode(f),f.properties.department_name||departmentCode(f)]));
  departments=[...names].map(([code,name])=>({code,name})).sort((a,b)=>a.name.localeCompare(b.name,'fr'));
  $('#department-query').disabled=false;
}
function applyDepartmentStyles(layer){
  if(!layer)return;
  layer.eachLayer(item=>{
    const p=item.feature.properties,dim=selectedDepartment&&departmentCode(item.feature)!==selectedDepartment;
    let color=p.bloc==='unknown'?'#ded4bd':family(p.bloc).color;
    if(proposalVisible&&layer===proposalLayer){const available=proposalRound===2?p.round2?.estimated:p.estimated;if(!available)color='#ded4bd'}
    item.setStyle({color:dim?'#928c7e':'#504735',weight:dim?.45:.52,opacity:dim?.65:1,fillColor:dim?'#b9b4a9':color,fillOpacity:dim?.6:.94});
    if(item._path)item._path.style.fill='';
  });
  addHatches(layer);
}
function focusDepartment(){
  const layer=proposalVisible?proposalLayer:currentLayer;
  const relevant=layer?.getLayers().filter(item=>departmentCode(item.feature)===selectedDepartment)||[];
  if(relevant.length)map.fitBounds(L.featureGroup(relevant).getBounds(),{paddingTopLeft:[50,120],paddingBottomRight:[55,70],animate:!matchMedia('(prefers-reduced-motion: reduce)').matches});
}
function closeDepartmentOptions(){const list=$('#department-options');list.hidden=true;$('#department-query').setAttribute('aria-expanded','false');$('#department-query').removeAttribute('aria-activedescendant');activeDepartmentOption=-1}
function renderDepartmentOptions(){
  const query=normalizeDepartment($('#department-query').value.trim()),list=$('#department-options');
  const matches=departments.filter(item=>!query||normalizeDepartment(item.name+' ('+item.code+')').includes(query)||item.code.toLowerCase().includes(query));
  list.replaceChildren();activeDepartmentOption=-1;
  if(!matches.length){const empty=document.createElement('li');empty.className='department-empty';empty.textContent='Aucun département trouvé';list.append(empty)}
  matches.forEach((item,index)=>{const option=document.createElement('li');option.id='department-option-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=item.name+' ('+item.code+')';option.addEventListener('pointerdown',event=>event.preventDefault());option.addEventListener('click',()=>selectDepartment(item));list.append(option)});
  list.hidden=false;$('#department-query').setAttribute('aria-expanded','true');
}
function selectDepartment(item){
  const keepSearchOpen=guidedTourActive&&guidedTourStep===4;
  selectedDepartment=item.code;$('#department-query').value=item.name+' ('+item.code+')';$('#department-clear').hidden=false;$('#department-toggle').classList.add('has-selection');closeDepartmentPanel();
  if(keepSearchOpen){$('#department-panel').hidden=false;$('#department-toggle').setAttribute('aria-expanded','true')}
  $('#department-toggle').focus({preventScroll:true});
  applyDepartmentStyles(proposalVisible?proposalLayer:currentLayer);
  if(!keepSearchOpen)focusDepartment();
  if(keepSearchOpen)$('#tour-next').disabled=false;
  const before=CURRENT.features.filter(f=>departmentCode(f)===item.code).length,summary=$('#department-summary');
  summary.hidden=false;summary.textContent=before+' sièges aujourd’hui';
  ensureProjection().then(data=>{if(selectedDepartment!==item.code)return;const after=proposalVisible?visibleProposalDepartmentCount(item.code):data.map.features.filter(feature=>departmentCode(feature)===item.code).length;summary.textContent=before+' sièges aujourd’hui · '+after+' proposé'+(after===1?'':'s')}).catch(()=>{});
  renderDepartmentMapNote();
}
function clearDepartment(){
  selectedDepartment='';$('#department-query').value='';$('#department-clear').hidden=true;$('#department-summary').hidden=true;$('#department-toggle').classList.remove('has-selection');closeDepartmentPanel();
  renderDepartmentMapNote();applyDepartmentStyles(proposalVisible?proposalLayer:currentLayer);recenterMap();
}
function handleDistrictClick(event,feature){
  L.DomEvent.stopPropagation(event);
  if(selectedDepartment&&departmentCode(feature)!==selectedDepartment)clearDepartment();
}
function closeDepartmentPanel(){closeDepartmentOptions();$('#department-panel').hidden=true;$('#department-toggle').setAttribute('aria-expanded','false')}
function bindDepartmentSearch(){
  const input=$('#department-query'),list=$('#department-options'),toggle=$('#department-toggle');
  toggle.addEventListener('click',()=>{if(!$('#department-panel').hidden){closeDepartmentPanel();return}$('#department-panel').hidden=false;toggle.setAttribute('aria-expanded','true');input.focus();if(selectedDepartment)input.select()});
  input.addEventListener('focus',renderDepartmentOptions);input.addEventListener('input',renderDepartmentOptions);
  input.addEventListener('keydown',event=>{
    const options=[...list.querySelectorAll('[role="option"]')];
    if(event.key==='Escape'){closeDepartmentPanel();toggle.focus();return}
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      event.preventDefault();if(list.hidden){renderDepartmentOptions();return}if(!options.length)return;
      activeDepartmentOption=(activeDepartmentOption+(event.key==='ArrowDown'?1:-1)+options.length)%options.length;
      options.forEach((option,index)=>option.setAttribute('aria-selected',String(index===activeDepartmentOption)));
      input.setAttribute('aria-activedescendant',options[activeDepartmentOption].id);options[activeDepartmentOption].scrollIntoView({block:'nearest'});
    }else if(event.key==='Enter'&&!list.hidden&&options.length){event.preventDefault();options[Math.max(activeDepartmentOption,0)].click()}
  });
  $('#department-clear').addEventListener('click',clearDepartment);
  document.addEventListener('pointerdown',event=>{if(!$('#department-search').contains(event.target))closeDepartmentPanel()});
  map.on('click',()=>{if(selectedDepartment)clearDepartment()});
}
async function start(){
  try{
    if(typeof L==='undefined')throw Error('Leaflet indisponible');
    map=L.map('map',{zoomControl:false,attributionControl:false,scrollWheelZoom:false,doubleClickZoom:false,zoomSnap:.25,zoomDelta:.25});
    const [snapshot,election]=await Promise.all([load('current-assembly.js'),load('election-2024.js')]);
    CURRENT=snapshot;ELECTION=election;
    const blocs={extreme_gauche:'lfi',gauche:'left',centre:'centre',droite:'right',rn:'far_right',autres:'other'};
    ELECTION.byCode=new Map(election.features.map(f=>[String(f.properties.code),{...f.properties,bloc:blocs[f.properties.group]||'other'}]));
    paintCurrent(snapshot.features,true);syncRoundSwitch();populateDepartments();bindDepartmentSearch();$('#map-loading').hidden=true;$('#map').setAttribute('aria-busy','false');
    $('#round-first').addEventListener('click',async()=>{try{await ensureProjection();setMapRound(1);applyDepartmentStyles(proposalVisible?proposalLayer:currentLayer)}catch(error){toast('Les résultats du premier tour sont indisponibles.')}});$('#round-second').addEventListener('click',()=>{setMapRound(2);applyDepartmentStyles(proposalVisible?proposalLayer:currentLayer)});
    $('#recenter-map').addEventListener('click',recenterMap);$('#zoom-in').addEventListener('click',()=>map.zoomIn());$('#zoom-out').addEventListener('click',()=>map.zoomOut());
    $('#results-cue').addEventListener('click',event=>{event.preventDefault();$('#results').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});$('#results-title').setAttribute('tabindex','-1');$('#results-title').focus({preventScroll:true})});
    $('#view-partisan').addEventListener('click',()=>explainFirst('partisan',selectPartisan));
    $('#footer-partisan').addEventListener('click',event=>{event.preventDefault();explainFirst('partisan',()=>{showPartisan();$('#atlas').scrollIntoView()})});
    $('#partisan-slider').addEventListener('input',event=>{partisanChoice=Number(event.target.value);showPartisan()});
    $('#view-today').addEventListener('click',()=>{if(proposalVisible)resetCurrent()});
    $('#view-tomorrow').addEventListener('click',()=>explainFirst('neutral',selectNeutral));
    $('#assembly-current').addEventListener('click',()=>setAssemblyView('current'));
    $('#assembly-projected').addEventListener('click',()=>setAssemblyView('projected'));
    bindInfoDialog('mmd-info','mmd-dialog');bindInfoDialog('round2-info','round2-dialog');
    if(new URLSearchParams(location.search).get('view')==='neutral') await showProposal();
    load('partisan-scenarios.js').then(data=>{PARTISAN=data}).catch(()=>{});
    bindHemicycleTooltip();window.addEventListener('resize',()=>{map.invalidateSize();if(selectedDepartment)focusDepartment();else recenterMap()});
    bindGuidedTour();
    let welcomeSeen=false;try{welcomeSeen=localStorage.getItem('gerard-welcome-seen')==='1'}catch{}
    if(!welcomeSeen)$('#welcome-dialog').showModal();
  }catch(error){console.error(error);$('#map-loading').hidden=true;$('#map').setAttribute('aria-busy','false');$('#map-error').hidden=false}
}
async function selectNeutral(){
  if(viewMode==='neutral')return;
  if(viewMode==='partisan'){proposalVisible=false;if(proposalLayer)map.removeLayer(proposalLayer);proposalLayer=null}
  const button=$('#view-tomorrow');button.disabled=true;$('#view-today').disabled=true;button.setAttribute('aria-busy','true');
  try{await showProposal()}finally{button.disabled=false;$('#view-today').disabled=false;button.removeAttribute('aria-busy')}
}
async function selectPartisan(){
  const button=$('#view-partisan');button.disabled=true;button.setAttribute('aria-busy','true');
  try{await showPartisan()}finally{button.disabled=false;button.removeAttribute('aria-busy')}
}
function bindGuidedTour(){
  const welcome=$('#welcome-dialog'),tour=$('#guided-tour'),card=$('#tour-card');
  const markWelcomeSeen=()=>{try{localStorage.setItem('gerard-welcome-seen','1')}catch{}};
  $('#welcome-start').addEventListener('click',()=>{markWelcomeSeen();welcome.close();startGuidedTour($('#view-today'))});
  $('#welcome-skip').addEventListener('click',()=>{markWelcomeSeen();welcome.close()});
  welcome.addEventListener('cancel',markWelcomeSeen);
  $('#replay-tour').addEventListener('click',event=>{event.preventDefault();startGuidedTour(event.currentTarget)});
  document.addEventListener('click',event=>{
    if(!guidedTourActive||card.contains(event.target))return;
    if(event.target.closest('#replay-tour,#welcome-start,#welcome-skip'))return;
    if(guidedTourStep===4&&$('#department-search').contains(event.target))return;
    endGuidedTour();
  });
  $('#tour-close').addEventListener('click',endGuidedTour);
  $('#tour-back').addEventListener('click',()=>setGuidedTourStep(guidedTourStep-1));
  $('#tour-next').addEventListener('click',()=>{
    if(guidedTourStep===GUIDED_TOUR_STEPS.length-1){endGuidedTour();return}
    if(guidedTourStep===4&&!selectedDepartment){
      const query=normalizeDepartment($('#department-query').value.trim());
      const department=query?departments.find(item=>normalizeDepartment(item.name+' ('+item.code+')').includes(query)||item.code.toLowerCase().includes(query)):null;
      const fallback=departments.find(item=>String(item.code)==='33')||departments[0];
      if(department||fallback)selectDepartment(department||fallback);
    }
    setGuidedTourStep(guidedTourStep+1);
  });
  document.addEventListener('keydown',event=>{
    if(!guidedTourActive)return;
    if(event.key==='Escape'){event.preventDefault();endGuidedTour();return}
    if(event.key==='Tab'){
      const searchInput=guidedTourStep===4?$('#department-query'):null;
      const focusable=[...(searchInput?[searchInput]:[]),...card.querySelectorAll('button:not([disabled])')],activeIndex=focusable.indexOf(document.activeElement);
      if(activeIndex<0){event.preventDefault();(event.shiftKey?focusable.at(-1):focusable[0]).focus()}
      else if(event.shiftKey&&activeIndex===0){event.preventDefault();focusable.at(-1).focus()}
      else if(!event.shiftKey&&activeIndex===focusable.length-1){event.preventDefault();focusable[0].focus()}
      else{event.preventDefault();focusable[activeIndex+(event.shiftKey?-1:1)].focus()}
    }
  });
  window.addEventListener('resize',scheduleTourPosition);
  window.addEventListener('scroll',scheduleTourPosition,true);
}
function startGuidedTour(returnFocus){
  resetGuidedTourMap();guidedTourReturnFocus=returnFocus||document.activeElement;guidedTourActive=true;guidedTourStep=0;$('#guided-tour').hidden=false;
  $('#atlas').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});setGuidedTourStep(0);
}
function resetGuidedTourMap(){
  selectedDepartment='';$('#department-query').value='';$('#department-clear').hidden=true;$('#department-summary').hidden=true;$('#department-toggle').classList.remove('has-selection');closeDepartmentPanel();
  partisanChoice=0;$('#partisan-slider').value='0';$('#partisan-slider').setAttribute('aria-valuetext','Extrême gauche');officialRound=2;proposalRound=2;
  resetCurrent();
}
function endGuidedTour(){
  guidedTourActive=false;$('#guided-tour').hidden=true;resetGuidedTourMap();
  const fallback=$('#view-today');if(guidedTourReturnFocus?.isConnected&&!guidedTourReturnFocus.closest('[hidden]'))guidedTourReturnFocus.focus({preventScroll:true});else fallback.focus({preventScroll:true});
}
function setGuidedTourStep(index){
  guidedTourStep=Math.max(0,Math.min(index,GUIDED_TOUR_STEPS.length-1));
  const step=GUIDED_TOUR_STEPS[guidedTourStep],target=$(step.target);
  $('#tour-card').classList.toggle('tour-search-step',step.target==='#department-query');
  $('#tour-card').classList.toggle('tour-department-step',guidedTourStep===5);
  $('#tour-count').textContent=String(guidedTourStep+1).padStart(2,'0')+' / '+String(GUIDED_TOUR_STEPS.length).padStart(2,'0');
  $('#tour-title').textContent=step.title;
  const selectedName=departments.find(item=>item.code===selectedDepartment)?.name;
  const description=guidedTourStep===0&&viewMode==='neutral'?'La carte montre les résultats de 2024 reportés sur le découpage neutre. Cliquez une circonscription pour en voir le détail.':guidedTourStep===0&&viewMode==='partisan'?'La couleur montre le bloc dont le modèle estime qu’il remporterait chaque circonscription dans ce scénario partisan.':guidedTourStep===5&&selectedName?'La carte zoome sur '+selectedName+' et ses circonscriptions.':step.description;
  $('#tour-description').textContent=description;
  $('#tour-back').hidden=guidedTourStep===0;
  $('#tour-next').setAttribute('aria-label',guidedTourStep===GUIDED_TOUR_STEPS.length-1?'Terminer la visite':'Étape suivante');
  $('#tour-back').disabled=false;$('#tour-next').disabled=false;
  if(guidedTourStep===4){showDepartmentTourDemo()}
  else if(guidedTourStep===5){closeDepartmentPanel();prepareDepartmentFocusStep()}
  else if(!$('#department-panel').hidden)closeDepartmentPanel();
  if(target)target.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  scheduleTourPosition();requestAnimationFrame(()=>$('#tour-next').focus({preventScroll:true}));
  prepareGuidedTourMap(guidedTourStep);
}
function prepareGuidedTourMap(index){
  const expected=index===1?'neutral':index===2?'partisan':null;
  if(!expected||viewMode===expected)return;
  const transition=expected==='neutral'?selectNeutral():selectPartisan();
  $('#tour-back').disabled=true;$('#tour-next').disabled=true;$('#tour-next').setAttribute('aria-busy','true');
  Promise.resolve(transition).then(()=>{
    if(!guidedTourActive||guidedTourStep!==index)return;
    if(viewMode===expected){try{localStorage.setItem('gerard-first-use-'+expected,'1')}catch{}}
    else $('#tour-description').textContent=expected==='neutral'?'La carte neutre est indisponible pour le moment. Vous pouvez continuer la visite ou la fermer.':'La carte partisane est indisponible pour le moment. Vous pouvez continuer la visite ou la fermer.';
  }).finally(()=>{
    if(!guidedTourActive||guidedTourStep!==index)return;
    $('#tour-back').disabled=false;$('#tour-next').disabled=false;$('#tour-next').removeAttribute('aria-busy');scheduleTourPosition();
  });
}
function showDepartmentTourDemo(){
  const panel=$('#department-panel'),toggle=$('#department-toggle'),input=$('#department-query');
  panel.hidden=false;toggle.setAttribute('aria-expanded','true');
  input.value=departments.find(item=>item.code===selectedDepartment)?.name||'Gironde';renderDepartmentOptions();
  requestAnimationFrame(()=>input.focus({preventScroll:true}));
}
function prepareDepartmentFocusStep(){
  if(!selectedDepartment)return;
  $('#tour-next').disabled=true;
  const finish=()=>{if(guidedTourActive&&guidedTourStep===5)$('#tour-next').disabled=false};
  map.once('moveend',finish);focusDepartment();setTimeout(finish,700);
}
function scheduleTourPosition(){if(!guidedTourActive)return;cancelAnimationFrame(guidedTourFrame);guidedTourFrame=requestAnimationFrame(positionGuidedTour)}
function positionGuidedTour(){
  const step=GUIDED_TOUR_STEPS[guidedTourStep],target=$(step.target),spot=$('#tour-spotlight'),card=$('#tour-card');
  if(!target||target.hidden)return;
  let rect=target.getBoundingClientRect();
  if(step.target==='#results-title'){const range=document.createRange();range.selectNodeContents(target);rect=range.getBoundingClientRect()}
  const tight=step.target==='#view-tomorrow'||step.target==='#view-partisan'||step.target==='#partisan-control .scenario-slider-wrap',pad=step.target==='#map'||tight?0:5;
  spot.style.left=Math.max(4,rect.left-pad)+'px';spot.style.top=Math.max(4,rect.top-pad)+'px';spot.style.width=Math.min(innerWidth-8,rect.width+pad*2)+'px';spot.style.height=Math.min(innerHeight-8,rect.height+pad*2)+'px';
  const cardRect=card.getBoundingClientRect(),large=rect.width*rect.height>innerWidth*innerHeight*.32;
  let left,top;
  if(step.target==='#results-title'){
    left=Math.max(14,(innerWidth-cardRect.width)/2);top=16;
  }
  else if(step.target==='#department-query'){
    left=14;top=14;
  }
  else if(guidedTourStep===5){
    left=Math.max(14,innerWidth-cardRect.width-14);top=14;
  }
  else if(large){left=Math.max(14,Math.min(innerWidth-cardRect.width-14,rect.left+18));top=Math.max(14,Math.min(innerHeight-cardRect.height-14,rect.top+18))}
  else{left=Math.max(14,Math.min(innerWidth-cardRect.width-14,rect.left+rect.width/2-cardRect.width/2));top=rect.bottom+cardRect.height+18<innerHeight?rect.bottom+14:Math.max(14,rect.top-cardRect.height-14)}
  card.style.left=left+'px';card.style.top=top+'px';
}
const FIRST_USE={neutral:{title:'Que veut dire « mieux équilibrée » ?'},partisan:{title:'Et si le découpage favorisait un camp ?'}};
function explainFirst(kind,action){
  let seen=false;try{seen=localStorage.getItem('gerard-first-use-'+kind)==='1'}catch{}
  if(seen){action();return}
  const content=FIRST_USE[kind],dialog=$('#first-use-dialog');
  $('#first-use-title').textContent=content.title;
  const button=$('#first-use-continue');button.onclick=()=>{try{localStorage.setItem('gerard-first-use-'+kind,'1')}catch{}dialog.close();action()};
  dialog.onclick=event=>{if(event.target===dialog)dialog.close()};
  dialog.showModal();
}
start();
