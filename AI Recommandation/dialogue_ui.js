/* Conversation UI: page changes become explicit patches, never overwrite chat state. */
(() => {
 const form=document.querySelector('#form'), input=document.querySelector('#note'), submit=document.querySelector('#submit');
 const origin=document.querySelector('#city');
 document.querySelector('label[for="city"]').textContent='Origin';
 origin.insertAdjacentHTML('afterbegin','<option value="">Select a city or drag the marker</option>');origin.value='';
 let originChosen=false;
 origin.addEventListener('change',()=>{originChosen=!!origin.value});
 const originHint=document.createElement('p');originHint.className='note';originHint.textContent='Drag the map marker to your starting point. You can also choose a city or describe your origin in chat.';origin.after(originHint);
 document.querySelector('#transport').hidden=true;
 document.querySelector('label[for="transport"]').hidden=true;
 document.querySelector('#access').checked=true;
 document.querySelector('#maps').checked=true;
 document.querySelector('.checks').remove();
 document.querySelector('#transport').remove();
 document.querySelector('label[for="transport"]').remove();
 input.placeholder='For example: Start from Edinburgh. I would like to watch birds and take a short walk.';
 submit.textContent='Send message';
 document.querySelector('.sub').textContent='Reach a station by public transport or taxi, then travel by train and on foot. Add details as you chat.';
 document.querySelector('button[type="submit"] + .note').textContent='Travel estimates use a reference departure time, not a selected journey date.';
 const markerTimer=setInterval(()=>{if(marker){
  clearInterval(markerTimer);
  marker.getPopup().setText('Drag this marker to your starting point.');
  if(!originChosen&&!marker.getPopup().isOpen())marker.togglePopup();
  marker.on('dragend',()=>{
   const point=marker.getLngLat();
   selectedPoint=[point.lat,point.lng];
   startAtNewOrigin();
   originChosen=true;origin.value='';origin.options[0].textContent='Selected by dragging';
   summary.textContent=`Map origin set · ${Number(document.querySelector('#travelMinutes').value)} min · Transit / taxi + train + walking`;
   document.querySelector('#status').textContent='New starting point set. A new conversation is ready; previous preferences have been cleared.';
   originHint.textContent='Starting point set on the map. Drag the marker again to change it.';
   marker.getPopup().remove();
  });
 }},100);
 document.querySelector('#travelMinutes').min='5';document.querySelector('#travelMinutes').step='1';
 const chat=document.createElement('section');chat.className='card';chat.style.marginTop='16px';
 chat.innerHTML='<h2>Chat with your green-space assistant</h2><p class="note">Transit / taxi + train + walking · Destination stations within 2 km of the green-space boundary. No station-distance limit at your origin. Distances are straight-line, not walking routes.</p><div id="chat-state" class="intent"></div><div id="chat-log" aria-live="polite"></div><div id="chat-options"></div><div style="display:flex;gap:10px"><button type="button" id="chat-export">Export conversation</button><button type="button" id="chat-reset">New conversation</button></div>';
 document.querySelector('#status').before(chat);
 const log=chat.querySelector('#chat-log'),options=chat.querySelector('#chat-options'),summary=chat.querySelector('#chat-state');
 let sid=sessionStorage.getItem('green-dialogue-v2-id'),lastUI=null,busy=false,generation=0;
 function startAtNewOrigin(){
  focusedCandidate=null;if(map?.getSource('selected-candidate'))map.getSource('selected-candidate').setData({type:'FeatureCollection',features:[]});
  generation++;sid=null;sessionStorage.removeItem('green-dialogue-v2-id');lastUI=null;
  log.replaceChildren();options.replaceChildren();document.querySelector('#results').replaceChildren();
  busy=false;submit.disabled=false;document.querySelector('#chat-reset').disabled=false;document.querySelector('#chat-export').disabled=false;
  if(map?.getSource('travel-area'))map.getSource('travel-area').setData({type:'FeatureCollection',features:[]});
 }
 function ui(){const value={minutes:Number(document.querySelector('#travelMinutes').value)};if(originChosen){if(cities[origin.value])value.city=origin.value;value.latitude=selectedPoint[0];value.longitude=selectedPoint[1]}else value.city=null;return value}
 function addMessage(role,text){const entry=document.createElement('div');entry.style.cssText='white-space:pre-wrap;padding:12px;margin-top:10px;border-radius:10px;background:'+(role==='You'?'#edf7ef':'#f7f8fa');const name=document.createElement('strong');name.textContent=role+':\n';entry.append(name,document.createTextNode(text));log.append(entry);return entry}
 function sync(state){
  originChosen=state.latitude!=null;origin.value=originChosen&&cities[state.city]?state.city:'';
  origin.options[0].textContent=originChosen&&!cities[state.city]?'Selected by dragging':'Select a city or drag the marker';
  if(originChosen&&!cities[state.city])originHint.textContent='Starting point set on the map. Drag the marker again to change it.';
  if(state.minutes){document.querySelector('#travelMinutes').value=state.minutes;document.querySelector('#travelOut').textContent=state.minutes+' min'}
  if(state.latitude!=null){selectedPoint=[state.latitude,state.longitude];if(marker)marker.setLngLat([state.longitude,state.latitude])}
  const labels={hiking:'Walking / hiking',birdwatching:'Birdwatching',nature:'Nature',cycling:'Cycling',camping:'Camping',beach_coast:'Coast',geology:'Geology',toilets:'Toilets',family_friendly:'Family-friendly',pet_friendly:'Pet-friendly',parking:'Parking',accessibility:'Accessibility'};
  labels.playground='Playground';
  summary.textContent=[state.city||'Origin not set',state.minutes?state.minutes+' min':'Time not set','Transit / taxi + train + walking',...Object.keys(state.activities||{}).map(k=>labels[k]||k),...Object.entries(state.needs||{}).map(([k,v])=>(labels[k]||k)+(v==='required'?' (required)':' (preferred)'))].join(' · ');
  if(state.travel_party?.children)summary.textContent+=' · Travelling with children';
  lastUI=ui();
 }
 let focusedCandidate=null;
 function restoreFocusedCandidate(){
  if(!map||!focusedCandidate||!map.isStyleLoaded())return;
  const data={type:'FeatureCollection',features:[focusedCandidate]};
  if(map.getSource('selected-candidate')){if(map.__focusedCandidateData!==focusedCandidate)map.getSource('selected-candidate').setData(data)}
  else map.addSource('selected-candidate',{type:'geojson',data});
  map.__focusedCandidateData=focusedCandidate;
  if(!map.getLayer('selected-candidate-fill'))map.addLayer({id:'selected-candidate-fill',type:'fill',source:'selected-candidate',slot:'top',paint:{'fill-color':'#f6c85b','fill-opacity':.28}});
  if(!map.getLayer('selected-candidate-outline'))map.addLayer({id:'selected-candidate-outline',type:'line',source:'selected-candidate',slot:'top',paint:{'line-color':'#164d35','line-width':3,'line-opacity':1}});
 }
 async function focusCandidate(item){
  if(!map)return;
  try{
   if(!greenSpaces)greenSpaces=await fetch('/api/green-spaces').then(response=>{if(!response.ok)throw new Error('Map data unavailable');return response.json()});
   const matches=greenSpaces.features.filter(feature=>feature.properties.name===item.name);
   // Disambiguate duplicate names using the returned candidate centre.
   const centre=item.geometry_center;
   if(centre)matches.sort((a,b)=>{
    function distance(feature){const points=[];function visit(c){if(typeof c[0]==='number')points.push(c);else c.forEach(visit)}visit(feature.geometry.coordinates);const lon=(Math.min(...points.map(p=>p[0]))+Math.max(...points.map(p=>p[0])))/2,lat=(Math.min(...points.map(p=>p[1]))+Math.max(...points.map(p=>p[1])))/2;return (lon-centre.longitude)**2+(lat-centre.latitude)**2}
    return distance(a)-distance(b);
   });
   const feature=matches[0];if(!feature){document.querySelector('#status').textContent='This green space could not be located on the map.';return}
   focusedCandidate=feature;
   if(!map.isStyleLoaded()){map.once('idle',()=>focusCandidate(item));return}
   restoreFocusedCandidate();renderScoreProfile(feature.properties);
   document.querySelectorAll('.chat-candidate').forEach(row=>row.classList.toggle('is-map-selected',row.dataset.placeKey===String(item.place_id??item.name)));
   const bounds=new mapboxgl.LngLatBounds();
   function extend(c){if(typeof c[0]==='number')bounds.extend(c);else c.forEach(extend)}extend(feature.geometry.coordinates);
   const dock=document.querySelector('#chat-dock'),desktop=window.innerWidth>700;
   if(!desktop&&dock&&!dock.hidden)document.querySelector('#chat-minimize').click();
   const mapWidth=map.getContainer().clientWidth;
   const right=desktop&&dock&&!dock.hidden?Math.min(dock.getBoundingClientRect().width+52,mapWidth*.60):45;
   if(!bounds.isEmpty())map.fitBounds(bounds,{padding:{top:50,bottom:65,left:45,right},maxZoom:14,duration:900});
   document.querySelector('#status').textContent='Showing '+item.name+' on the map.';
  }catch(error){document.querySelector('#status').textContent='Could not focus this green space. Please try again.'}
 }
 const selectedLayerTimer=setInterval(()=>{if(map){clearInterval(selectedLayerTimer);map.on('style.load',restoreFocusedCandidate);map.on('idle',restoreFocusedCandidate)}},100);
 function renderResult(result, messageEntry=null){
  if(!result)return;
  document.querySelector('#results').replaceChildren();
  if(messageEntry){
   const list=document.createElement('div');list.className='chat-candidates';list.setAttribute('aria-label','Recommended green spaces');
   const labels={hiking:'Walking / hiking',birdwatching:'Birdwatching',nature:'Nature',cycling:'Cycling',camping:'Camping',beach_coast:'Coast',geology:'Geology',toilets:'Toilets',family_friendly:'Family-friendly',pet_friendly:'Pet-friendly',parking:'Parking',accessibility:'Accessibility'};
   for(const [index,item] of result.recommendations.entries()){
    const details=document.createElement('details');details.className='chat-candidate';details.dataset.placeKey=String(item.place_id??item.name);
    const summary=document.createElement('summary');
    summary.innerHTML=`<span class="candidate-rank">${item.display_rank||index+1}</span><span class="candidate-name">${esc(item.name)}</span><span class="candidate-score" title="Recommendation score">${Number(item.final_score).toFixed(2)}</span><span class="candidate-chevron" aria-hidden="true">⌄</span>`;
    summary.title='Show '+item.name+' on the map and expand details';
    summary.addEventListener('click',()=>focusCandidate(item));
    const body=document.createElement('div');body.className='candidate-detail';
    const heading=document.createElement('strong');heading.textContent='Why this place';body.append(heading);
    const reason=document.createElement('p');reason.textContent=item.llm_recommendation_reason||'Ranked by your activity preferences and location.';body.append(reason);
    for(const match of item.requirement_matches||[]){
     const line=document.createElement('p');line.className='candidate-requirement-match';
     const label=document.createElement('strong');label.textContent=match.requirement+': ';
     line.append(label,document.createTextNode(match.explanation));body.append(line);
    }
    if(item.google_context?.scope==='geographic_alias'){
     const context=document.createElement('p');context.className='candidate-scope-note';context.textContent='Google source: '+item.google_context.place_name+'. The related name and location match this green space, so its information is used as supporting evidence. Conditions may vary across the site.';body.append(context);
     if(!item.maps_support){const quote=document.createElement('p');quote.textContent='Google place-summary excerpt: '+item.google_context.excerpt;body.append(quote)}
    }
    if(item.google_context?.scope==='component_only'){
     const context=document.createElement('p');context.className='candidate-scope-note';context.textContent='Google returned '+item.google_context.place_name+' only. This is a component of the combined green space, not evidence for the entire area.';body.append(context);
     const quote=document.createElement('p');quote.textContent='Place-summary excerpt (not a review): '+item.google_context.excerpt;body.append(quote);
    }
    if(item.visitor_reviews){
     const section=document.createElement('section');section.className='candidate-maps-support';
     const heading=document.createElement('strong');heading.textContent='Visitor review cross-check';section.append(heading);
     const reviews=item.visitor_reviews;
     const summary=reviews.review_summary;
     if(summary?.text?.text&&summary.reviewsUri&&summary.disclosureText?.text){
      const title=document.createElement('strong');title.textContent='Google review summary · '+(reviews.place_name||item.name);section.append(title);
      const text=document.createElement('p');text.textContent=summary.text.text;section.append(text);
      const disclosure=document.createElement('p');disclosure.textContent=summary.disclosureText.text;section.append(disclosure);
      for(const [label,url] of [['Read reviews on Google Maps',summary.reviewsUri],['Report this summary',summary.flagContentUri]]){
       if(url&&/^https?:\/\//i.test(url)){const link=document.createElement('a');link.textContent=label;link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='candidate-source';section.append(link)}
      }
     }else if(reviews.status==='ok'){
      const text=document.createElement('p');text.textContent='Google did not return a displayable review summary for this place.';section.append(text);
     }
     const note=document.createElement('p');note.textContent=reviews.status==='ok'&&!reviews.returned_count?'Google returned no individual review text for this request.':reviews.scope==='geographic_alias'?'Visitor feedback from the geographically matched Google place '+reviews.place_name+'. Conditions may vary across the site.':reviews.scope==='component_only'?'Reviews concern '+reviews.place_name+' only, not the entire combined area.':reviews.status==='ok'?'Individual visitor opinions; not proof of facilities or suitability.':'Individual reviews are unavailable or not sufficiently matched. Place summaries are not review text.';section.append(note);
     for(const review of reviews.excerpts||[]){
      const text=document.createElement('blockquote');text.textContent=review.quote;section.append(text);
      const attribution=document.createElement('p');attribution.textContent=review.author+' · '+(review.published_at||'Date not returned').slice(0,10);section.append(attribution);
      for(const [label,url] of [['Reviewer',review.author_url],['Original review',review.review_url]]){
       if(url&&/^https?:\/\//i.test(url)){const link=document.createElement('a');link.textContent=label;link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='candidate-source';section.append(link)}
      }
     }
     const reviewLink=reviews.reviews_url||item.google_context?.reviews_url;
     if(reviewLink&&/^https?:\/\//i.test(reviewLink)){const link=document.createElement('a');link.textContent='Read reviews on Google Maps';link.href=reviewLink;link.target='_blank';link.rel='noopener noreferrer';section.append(link)}
     body.append(section);
    }
    for(const explanation of item.score_explanations||[]){
     const section=document.createElement('section');section.className='candidate-score-explanation';
     const title=document.createElement('strong');title.textContent=explanation.label+' '+Number(explanation.score).toFixed(2);
     const text=document.createElement('p');text.textContent=explanation.explanation;
     const limit=document.createElement('p');limit.className='score-limitation';limit.textContent=explanation.limitation;
     section.append(title,text,limit);body.append(section);
    }
    if(item.maps_support){
     const section=document.createElement('section');section.className='candidate-maps-support';
     const title=document.createElement('strong');title.textContent='Google Maps context';
     const text=document.createElement('p');text.textContent=item.maps_support.summary;
     section.append(title,text);
     if(item.maps_support.retrieved_at){const time=document.createElement('small');time.textContent='Retrieved: '+item.maps_support.retrieved_at;section.append(time)}
     body.append(section);
    }
    if(item.scoring_note){const method=document.createElement('details');method.className='candidate-method';const title=document.createElement('summary');title.textContent='How these scores are calculated';const text=document.createElement('p');text.textContent=item.scoring_note;const source=document.createElement('small');source.textContent='Source: Project scoring guide and dataset.';method.append(title,text,source);body.append(method)}
    const scores=document.createElement('div');scores.className='candidate-activity-scores';
    for(const [tag,value] of Object.entries(item.activity_score_breakdown||{})){
     const score=document.createElement('span');score.textContent=(labels[tag]||tag)+' '+Number(value.raw_score).toFixed(2);scores.append(score);
    }body.append(scores);
    if(item.nearest_station){const station=document.createElement('p');station.textContent='Nearby station: '+item.nearest_station.name+' · '+Number(item.nearest_station.boundary_distance_km).toFixed(2)+' km to the boundary (straight line, not a walking route).';body.append(station)}
    for(const [tag,evidence] of Object.entries(item.facility_evidence||{})){
     const fact=document.createElement('p');fact.className='candidate-facility';fact.textContent=(labels[tag]||tag)+': '+({yes:'Supported by evidence',no:'Evidence of unavailability',unknown:'Not confirmed'}[evidence.status]||'Not confirmed')+(evidence.quote?' — '+evidence.quote:'');body.append(fact);
    }
    for(const place of item.maps_grounding?.places||[]){
     const url=place.attribution?.url;if(!url||!/^https?:\/\//i.test(url))continue;
     const link=document.createElement('a');link.href=url;link.textContent=place.attribution.title||'View source';link.target='_blank';link.rel='noopener noreferrer';link.className='candidate-source';body.append(link);
    }
    details.append(summary,body);list.append(details);
   }
   messageEntry.append(list);
   requestAnimationFrame(()=>{log.scrollTop=log.scrollHeight});
  }
  if(result.explanation_only){document.querySelector('#status').textContent='Recommendation evidence shown in this reply.';return}
  showIsochrone(result.travel_time?.geojson);
  document.querySelector('#status').textContent='Results · Eligible: '+result.candidate_count_after_filters+' · Checked: '+(result.checked_candidate_count??0)+' · Reused: '+(result.reused_candidate_count??0)+' · Newly checked: '+(result.newly_checked_candidate_count??0)+' · Shown: '+result.recommendations.length;
 }
 function renderOptions(values){options.replaceChildren();for(const text of values||[]){const button=document.createElement('button');button.type='button';button.textContent=text;button.style.cssText='width:auto;margin:10px 8px 0 0;padding:7px 12px';button.onclick=()=>send(text);options.append(button)}}
 async function api(payload){const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed');return data}
 async function send(message){
  if(busy||!message.trim())return;
  const requestGeneration=generation;
  busy=true;submit.disabled=true;options.querySelectorAll('button').forEach(b=>b.disabled=true);document.querySelector('#chat-reset').disabled=true;document.querySelector('#chat-export').disabled=true;
  document.querySelector('#status').textContent='Processing your message…';
  try{
   const current=ui(),patch={};for(const [k,v] of Object.entries(current))if(!lastUI||v!==lastUI[k])patch[k]=v;
   const data=await api({session_id:sid,message,ui:patch,use_maps:true});
   if(requestGeneration!==generation)return;
   sid=data.session_id;sessionStorage.setItem('green-dialogue-v2-id',sid);sync(data.state);addMessage('You',data.turn.user);const assistantEntry=addMessage('Assistant',data.turn.assistant);renderOptions(data.turn.suggestions);if(data.turn.evidence_candidate)renderResult({recommendations:[data.turn.evidence_candidate],explanation_only:true},assistantEntry);
   if(data.clear_results){document.querySelector('#results').replaceChildren();lastUI=null;}
   else if(data.result)renderResult(data.result,assistantEntry);
   else if(!data.turn.evidence_candidate)document.querySelector('#status').textContent='No updated recommendations this turn. Any cards below are from the previous search.';
   input.value='';
  }catch(error){if(requestGeneration!==generation)return;document.querySelector('#status').textContent=error.message+' (You can retry your message.)'}
  finally{if(requestGeneration===generation){busy=false;submit.disabled=false;document.querySelector('#chat-reset').disabled=false;document.querySelector('#chat-export').disabled=false;options.querySelectorAll('button').forEach(b=>b.disabled=false)}}
 }
 form.addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();send(input.value)},true);
 document.querySelector('#chat-reset').onclick=()=>{startAtNewOrigin();originChosen=false;origin.value='';origin.options[0].textContent='Select a city or drag the marker';log.replaceChildren();options.replaceChildren();summary.textContent='New conversation: choose an origin or describe it in chat.';document.querySelector('#results').replaceChildren();document.querySelector('#status').textContent='New conversation ready. Previous conversations remain saved locally.';if(map?.getSource('travel-area'))map.getSource('travel-area').setData({type:'FeatureCollection',features:[]})};
 document.querySelector('#chat-export').onclick=async()=>{if(!sid)return;try{const data=await api({session_id:sid,command:'export'});const url=URL.createObjectURL(new Blob([data.markdown],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='green-space-conversation-'+sid.slice(0,8)+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){document.querySelector('#status').textContent=e.message}};
 const restoreGeneration=generation;
 if(sid){busy=true;submit.disabled=true;api({session_id:sid,command:'load'}).then(data=>{if(restoreGeneration!==generation)return;sync(data.state);for(const t of data.turns){addMessage('You',t.user);const entry=addMessage('Assistant',t.assistant);if(t.result)renderResult(t.result,entry);if(t.evidence_candidate)renderResult({recommendations:[t.evidence_candidate],explanation_only:true},entry)}renderOptions(data.turns.at(-1)?.suggestions);renderResult(data.result)}).catch(e=>{if(restoreGeneration!==generation)return;document.querySelector('#status').textContent=e.message;sid=null;lastUI=null;sessionStorage.removeItem('green-dialogue-v2-id')}).finally(()=>{if(restoreGeneration===generation){busy=false;submit.disabled=false}})}
})();
