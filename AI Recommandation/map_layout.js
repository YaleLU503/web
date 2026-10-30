/* Map-first layout. Existing chat/state handlers keep their DOM references. */
(() => {
 const chat=document.querySelector('#chat-log')?.closest('section');
 const form=document.querySelector('#form');
 if(!chat||!form)return;
 const dock=document.createElement('aside');dock.id='chat-dock';dock.setAttribute('aria-label','Green-space assistant');
 dock.innerHTML='<div class="dock-heading"><div><span class="dock-eyebrow">YOUR OUTDOOR COMPANION</span><h2>Plan your escape</h2></div><button type="button" id="chat-minimize" aria-label="Minimize chat" title="Minimize chat">−</button></div><details class="trip-settings" open><summary>Origin & travel time</summary><div class="trip-settings-body"></div></details>';
 const launcher=document.createElement('button');launcher.id='chat-launcher';launcher.type='button';launcher.textContent='Chat with your guide';launcher.setAttribute('aria-controls','chat-dock');launcher.setAttribute('aria-expanded','true');launcher.hidden=true;
 document.body.append(dock,launcher);
 const settings=dock.querySelector('.trip-settings-body');
 const city=document.querySelector('#city'),originLabel=document.querySelector('label[for="city"]');
 const hint=city.nextElementSibling;
 settings.append(originLabel,city);
 if(hint?.classList.contains('note'))settings.append(hint);
 settings.append(document.querySelector('label[for="travelMinutes"]'),document.querySelector('.range-row'));
 dock.append(chat,form);chat.classList.add('dock-conversation');form.classList.add('dock-composer');
 chat.style.marginTop='0';
 chat.querySelector('h2').hidden=true;
 chat.querySelector('.note').textContent='Tell me what you would enjoy. You can keep exploring the map as we chat.';
 const actions=document.querySelector('#chat-export').parentElement;actions.classList.add('dock-actions');
 // Put secondary actions in the header, freeing the entire body for messages.
 const tools=document.createElement('details');tools.className='chat-tools';
 tools.innerHTML='<summary aria-label="Conversation actions" title="Conversation actions">•••</summary>';
 tools.append(actions);dock.querySelector('.dock-heading').insertBefore(tools,document.querySelector('#chat-minimize'));
 actions.addEventListener('click',()=>{tools.open=false});
 settings.append(document.querySelector('#chat-state'));

 form.querySelectorAll('h2,hr').forEach(el=>el.hidden=true);
 form.querySelector('label[for="exploreScore"]').hidden=true;
 document.querySelector('#exploreScore').hidden=true;
 form.querySelector('.map-hint').hidden=true;
 document.querySelector('label[for="note"]').textContent='Your next adventure';
 document.querySelector('#note').placeholder='A nature walk with the kids, somewhere with toilets…';
 document.querySelector('#submit').textContent='↑';
 document.querySelector('#submit').setAttribute('aria-label','Send message');
 document.querySelector('#submit').title='Send message';
 const status=document.querySelector('#status');status.setAttribute('role','status');dock.insertBefore(status,form);
 const log=document.querySelector('#chat-log');
 if(!log.children.length){const welcome=document.createElement('p');welcome.id='chat-welcome';welcome.textContent='Start with an idea. Drag the map marker, choose an origin above, or tell me where you would like to start.';log.append(welcome)}
 function openChat(open){
  dock.hidden=!open;launcher.hidden=open;launcher.setAttribute('aria-expanded',String(open));
  if(open)document.querySelector('#note').focus();else launcher.focus();
  if(map)requestAnimationFrame(()=>map.resize());
 }
 document.querySelector('#chat-minimize').onclick=()=>openChat(false);
 launcher.onclick=()=>openChat(true);
 dock.addEventListener('keydown',event=>{if(event.key==='Escape'){openChat(false);event.preventDefault()}});
 const observer=new MutationObserver(()=>{
  if(log.children.length>1)document.querySelector('#chat-welcome')?.remove();
  log.scrollTop=log.scrollHeight;
  if(dock.hidden){launcher.textContent='Chat · new activity';launcher.classList.add('has-activity')}
 });observer.observe(log,{childList:true});
 launcher.addEventListener('click',()=>{launcher.textContent='Chat with your guide';launcher.classList.remove('has-activity')});
 const resizeMap=new ResizeObserver(()=>{if(map)map.resize()});resizeMap.observe(document.querySelector('#map'));
 document.querySelector('.map-panel > .map-hint').textContent='Drag the marker to set your origin. Explore the activity colours and click a station to see its name.';

 // Keep the complete score profile inside the map, beside the chat dock.
 scoreProfileObserver.disconnect();scoreProfileSizeObserver.disconnect();profileDesignObserver.disconnect();
 scoreProfilePanel.id='floating-score-profile';
 scoreProfilePanel.setAttribute('aria-label','Green-space score profile');
 document.querySelector('#map').append(scoreProfilePanel);
 scoreProfilePanel.removeAttribute('style');
 scoreProfilePanel.innerHTML='<div class="profile-caption">GREEN-SPACE SCORES</div><p class="profile-empty">Hover over a green space to compare all eight scores.</p>';
 renderScoreProfile=function(properties){
  const key=profileScoreFields.map(field=>properties[field]).join('|')+'|'+(properties.name||'');
  if(scoreProfilePanel.dataset.profileKey===key)return;
  scoreProfilePanel.dataset.profileKey=key;
  const rows=profileScoreFields.map(field=>{
   const score=Math.max(0,Math.min(1,Number(properties[field])||0));
   const colour=(palettes[field]||palettes.best_overall)[1];
   return `<div class="profile-row"><span class="profile-label">${esc(scoreNames[field])}</span><span class="profile-track"><span style="width:${score*100}%;background:${colour}"></span></span><span class="profile-value">${score.toFixed(2)}</span></div>`;
  }).join('');
  scoreProfilePanel.innerHTML=`<div class="profile-caption">GREEN-SPACE SCORES</div><h3>${esc(properties.name||'Unnamed green space')}</h3><div class="profile-rows">${rows}</div>`;
 };
})();
