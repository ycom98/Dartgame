/* Only the host owns handoff timers. Each mutation is checked against its revision. */
(()=>{const $=s=>document.querySelector(s);let state=null,busy=false,ring=1,timer=null,tick=null,pausedRevision=null,showSetup=false,entryReadyAt=0,checking=false,lastHealthy=0;
 const notice=m=>$('#notice').textContent=m;
 document.querySelectorAll('a.brand').forEach(a=>a.href='#');
 document.querySelector('footer a').href='/?t='+encodeURIComponent(DartRoom.token);
 const back=document.createElement('button');back.type='button';back.id='back-to-match';back.textContent='Back to the match';back.hidden=true;back.style.marginTop='12px';$('#setup').append(back);back.onclick=()=>{showSetup=false;paint();};
 function cancel(){clearTimeout(timer);clearInterval(tick);timer=tick=null;$('#handoff').textContent='';$('#cancel').hidden=true;}
 function done(){return state?.game&&state.game.winner===null&&(state.game.bust||state.game.darts.length===3);}
 function paint(){DartRoom.render(state?.game);const g=state?.game;$('#setup').hidden=!!g&&!showSetup;$('#entry').hidden=!g||showSetup;
 $('#display-link').href=state?.presentation_path||'/play';back.hidden=!g||!showSetup;
 if(!g)return;$('#prompt').textContent=g.winner!==null?g.names[g.winner]+' wins!':done()?'Turn complete · '+g.names[(g.player+1)%g.names.length]+' up next':g.names[g.player]+' · dart '+(g.darts.length+1)+' of 3';
 $('#record').disabled=busy||Date.now()<entryReadyAt||done()||g.winner!==null;$('#next').disabled=busy||!done();$('#undo').disabled=busy;const tap=tapAllowed();$('#tap-board').classList.toggle('disabled',!tap);$('#miss').disabled=!tap;paintCamera();
 
 }
 function schedule(){
  cancel();
  if(!done()||!$('#auto').checked||pausedRevision===state.revision)return;
  const rev=state.revision;
  let left=4;
  $('#cancel').hidden=false;
  $('#handoff').textContent='Next player in '+left+' seconds · Undo or pause to review.';
  tick=setInterval(()=>{left--;$('#handoff').textContent='Next player in '+Math.max(left,0)+' seconds · Undo or pause to review.';},1000);
  timer=setTimeout(()=>handoff(rev,0),4000);
 }
 // QA M1-17 #4: the handoff used to give up when a state poll happened to be in flight (every 0.4 s in camera
 // games) or a write was running at that instant. Now it waits for them; it pauses only on a real connection problem.
 function handoff(rev,waited){
  if(state.revision!==rev||!done()){cancel();return;}
  if((checking||busy)&&waited<3000){timer=setTimeout(()=>handoff(rev,waited+100),100);return;}
  cancel();
  if(busy||Date.now()-lastHealthy>3000){
   pausedRevision=rev;
   notice('Connection check pending. Handoff paused; review the turn before choosing Next player.');
   return;
  }
  mutate('/api/next',{},false);
 }
 // Sends one write. Resolves to true if the server recorded it, false if not (QA M1-17 #5: callers show that).
 async function mutate(path,body={},allowSchedule=true){
  if(busy)return false;
  if(['/api/throw','/api/correct','/api/turn/fill_misses'].includes(path)){
   if(Date.now()<entryReadyAt)return false;
   entryReadyAt=Date.now()+600;
   setTimeout(paint,610);
  }
  cancel();
  busy=true;
  notice('');
  paint();
  const revision=state?.revision;
  try{
   const payload={...body,expected_revision:revision};
   state=await DartRoom.request(path,payload);
   showSetup=false;
   pausedRevision=null;
   paint();
   if(allowSchedule)schedule();
   return true;
  }catch(e){
   pausedRevision=e.state?.revision??revision;
   if(e.state?.game!==undefined)state=e.state;  // a 409 carries the current match: show it
   notice(e.status===409?e.message:e.status?'Could not save: '+e.message:'Connection interrupted. Check the current match before trying again.');
   if(!e.status){try{state=await DartRoom.request('/api/state');}catch{}}
   return false;
  }finally{
   busy=false;
   paint();
  }
 }
 function names(){const old=[...$('#names').querySelectorAll('input')].map(i=>i.value);$('#names').replaceChildren();for(let i=0;i<Number($('#count').value);i++){const l=document.createElement('label');l.textContent='Player '+(i+1);const input=document.createElement('input');input.name='player';input.required=true;input.maxLength=30;input.placeholder=['Alex','Maya','Jordan','Sam'][i];input.value=old[i]||'';input.autocomplete='off';l.append(input);$('#names').append(l);}}
 $('#count').onchange=names;names();
 $('#setup').onsubmit=e=>{e.preventDefault();mutate('/api/game',{names:[...document.querySelectorAll('#names input')].map(i=>i.value.trim()),start:Number($('#start').value),double_out:$('#finish').value==='double',camera:false});};
 $('#value').replaceChildren();for(const [v,title] of [[0,'Miss'],...[...Array(20)].map((_,i)=>[i+1,String(i+1)]),[25,'Bull / outer bull']]){const o=document.createElement('option');o.value=v;o.textContent=title;$('#value').append(o);}$('#value').value=20;
 function normalize(){const v=Number($('#value').value);if(v===0)ring=1;if(v===25&&ring===3)ring=2;document.querySelectorAll('[data-ring]').forEach(b=>{const r=Number(b.dataset.ring);b.disabled=(v===0&&r!==1)||(v===25&&r===3);b.setAttribute('aria-pressed',String(r===ring));});$('#entry-preview').textContent=DartRoom.label({value:v,multiplier:ring})+' · '+(v*ring)+' points';}
 document.querySelectorAll('[data-ring]').forEach(b=>b.onclick=()=>{ring=Number(b.dataset.ring);normalize();});$('#value').onchange=normalize;normalize();
 $('#dart-form').onsubmit=e=>{e.preventDefault();if($('#record').disabled)return;mutate('/api/throw',{value:Number($('#value').value),multiplier:ring});};


 /* ---- Tap-the-board entry (M1-11) and camera darts (M1-12) ----
    A tap does one of three things:
      - a committed dart chip is selected: correct that dart (/api/correct; 2 taps in all);
      - a camera dart is pending: commit the tapped value instead of it (1 tap; logged as a correction);
      - otherwise: record a manual dart (also how a missed detection is entered).
    Camera darts auto-accept on the server after a few seconds unless corrected or paused (owner decision #1). */
 let correcting=null,polledAt=performance.now();
 const pending=()=>state?.camera_game?state.camera?.pending||null:null;
 function tapAllowed(){
  const g=state?.game;
  if(!g||busy||Date.now()<entryReadyAt)return false;
  if(correcting!==null)return correcting<g.darts.length;
  return !done()&&g.winner===null;
 }
 function tapScore(value,multiplier,key){
  if(!tapAllowed())return;
  if(key)DartBoard.flash($('#tap-board'),key);
  const text=value===0?'Miss':DartBoard.label(value,multiplier);
  if(correcting!==null){
   const index=correcting;
   correcting=null;
   report('Dart '+(index+1)+' corrected to '+text,mutate('/api/correct',{dart_index:index,value,multiplier}));
   return;
  }
  const p=pending();
  if(p){report(text+' (instead of camera '+p.label+')',mutate('/api/throw',{value,multiplier,replaces_proposal_id:p.id}));return;}
  report(text,mutate('/api/throw',{value,multiplier}));
 }
 // Tap feedback follows the server's answer: "saving…", then the value, or "Not recorded" (QA M1-17 #5).
 function report(text,result){
  const feedback=$('#tap-feedback');
  feedback.textContent=text+' · saving…';
  feedback.classList.remove('refused');
  result.then(ok=>{
   if(feedback.textContent!==text+' · saving…')return;
   feedback.textContent=ok?text:'Not recorded: '+text+'. Check the turn and tap again.';
   feedback.classList.toggle('refused',!ok);
  });
 }
 DartBoard.tapBoard($('#tap-board'),tapScore);
 $('#miss').onclick=()=>tapScore(0,1,null);
 // Accept names the value the host saw: a near-wire label that flipped since then gives 409 (QA Q4).
 $('#accept').onclick=()=>{
  const p=pending();
  if(p&&!busy&&!p.turn_over)mutate('/api/throw',{proposal_id:p.id,label:p.label});
 };
 $('#auto-pause').onclick=()=>{if(!busy)mutate('/api/camera/auto_commit',{paused:!state.camera.auto_commit.paused},false);};
 $('#end-turn').onclick=()=>{if(!busy)mutate('/api/turn/fill_misses',{});};
 function dartText(d){return d.value===0?(d.filled?'Miss · filled in':'Miss'):DartBoard.label(d.value,d.multiplier);}
 function chip(d,i){
  // Short visible text so all three chips fit a phone row (demo: dart 3 was off-screen); full text for screen readers.
  const b=document.createElement('button');
  b.type='button';
  b.className='dart-chip'+(correcting===i?' selected':'')+(d.filled?' filled':'');
  const full=document.createElement('span');
  full.className='visually-hidden';
  full.textContent='Dart '+(i+1)+': '+dartText(d);
  b.append((i+1)+' · '+DartRoom.label(d)+(d.filled?'*':''),full);
  b.setAttribute('aria-pressed',String(correcting===i));
  b.onclick=()=>{correcting=correcting===i?null:i;paint();};
  return b;
 }
 // The camera panel has fixed-height lines (QA R1): a headline and a two-line detail.
 function pendingText(p){
  if(!p){
   const v=state.vision||{};
   if(v.verified)return ['Camera: watching for the next dart',''];
   // Say what is wrong and what to do (QA M1-17 #3); tapping the board always works meanwhile.
   const phases={
    camera_disconnected:['Camera reconnecting…','Phone stream lost. It reconnects by itself; tap darts on the board meanwhile.'],
    needs_alignment:['Board check needed',v.message&&/Camera back/.test(v.message)?v.message:
     'Checking the board… If this stays: on the Mac press Check / realign board, then Markers correct.'],
    review_overlay:['Check the overlay on the Mac','Then press Markers correct · Ready to play.'],
    calibrating:['Calibrating on the Mac','Select the four points on the setup page.'],
    waiting_camera:['Camera not connected','Connect the phone on the Mac setup page.'],
    ready_to_calibrate:['Camera not calibrated','Set the four points on the Mac setup page.'],
   };
   return phases[v.phase]||['Camera: not ready',v.message||'Check the setup page on the Mac.'];
  }
  const notes=[];
  if(p.near_wire)notes.push('near a wire, check it');
  if(p.label_changes)notes.push('value changed, check it');
  if(p.turn_over)notes.push('turn is over: Undo, End turn or Next player');
  else if(p.commit_in==null)notes.push('waiting for Accept');
  else notes.push('auto-accept in '+Math.max(0,p.commit_in-(performance.now()-polledAt)/1000).toFixed(1)+' s');
  return ['Camera: '+p.label+' ('+p.score+')',notes.join(' · ')];
 }
 // Compact match status for phones, where the full scoreboard is hidden (live demo finding).
 function entryMode(){
  $('#entry-mode').textContent=state?.camera_game?'CAMERA SCORING · TAP TO CORRECT':'MANUAL SCORE ENTRY';
 }
 function compactStatus(g){
  const box=$('#compact-status');
  document.body.classList.toggle('in-game',!!g&&!showSetup);
  if(!g){box.replaceChildren();return;}
  // One fixed-height line for all players (QA M1-16 L4: the board must start on the first phone screen).
  const players=document.createElement('div');
  players.className='compact-players';
  g.names.forEach((name,i)=>{
   const who=document.createElement('span');
   who.className='compact-player'+(i===g.player?' current':'');
   who.textContent=(i===g.player?'▶ ':'')+name+' '+(g.scores?g.scores[i]:'');
   players.append(who);
  });
  const rows=[players];
  const darts=document.createElement('div');
  darts.className='compact-darts';
  darts.textContent='This turn: '+([0,1,2].map(i=>g.darts[i]?dartText(g.darts[i]):'—').join(' · '))+
   (g.bust?' · BUST':'')+(g.winner!==null?' · '+g.names[g.winner]+' wins':'');
  box.replaceChildren(...rows,darts);
 }
 function paintCamera(full=true){
  compactStatus(state?.game);
  entryMode();
  const g=state?.game,p=pending(),camera=!!state?.camera_game;
  // Committed darts of this turn: tap one, then tap the board to correct it.
  const chips=$('#turn-darts'),signature=JSON.stringify([g?.darts,correcting]);
  if(full&&signature!==chips.dataset.signature){
   chips.dataset.signature=signature;
   chips.replaceChildren(...(g?g.darts.map(chip):[]));
  }
  if(correcting!==null&&(!g||correcting>=g.darts.length))correcting=null;
  $('#tap-hint').textContent=correcting!==null?'Tap the board (or Miss) to correct dart '+(correcting+1)+'. Tap its chip to cancel.':
   p?'Camera dart pending: tap the board for another value.':'Tap where the dart landed.';
  $('#camera-panel').hidden=!camera;
  if(camera){
   const auto=state.camera.auto_commit;
   const [headline,detail]=pendingText(p);
   $('#pending').textContent=headline;
   $('#pending-detail').textContent=detail;
   $('#pending').classList.toggle('active',!!p);
   $('#accept').style.visibility=!p||p.turn_over?'hidden':'visible';  // keeps its space: no layout shift
   $('#accept').disabled=busy||!p||p.turn_over;
   $('#auto-status').textContent=!auto.enabled?'Auto-accept is off (--auto-commit 0).':
    auto.paused?'Auto-accept paused: camera darts wait for Accept.':'Camera darts auto-accept after '+auto.seconds+' s.';
   $('#auto-pause').style.visibility=auto.enabled?'visible':'hidden';
   $('#auto-pause').textContent=auto.paused?'Resume auto-accept':'Pause auto-accept';
   $('#auto-pause').disabled=busy;
  }
  $('#end-turn').hidden=!camera||!g||g.winner!==null||g.bust||g.darts.length>=3||!!p;
  $('#end-turn').disabled=busy;
  // Pending dart marker on the tap board (board mm -> tap board picture units).
  const markers=$('#tap-board .markers');
  if(markers){
   const at=p&&p.x!=null?DartBoard.tapPoint(p.x,p.y):null;
   markers.innerHTML=at?`<circle class="pending-marker" cx="${at[0]}" cy="${at[1]}" r="9"/>`:'';
  }
 }
 setInterval(()=>{if(pending())paintCamera(false);},200);
 $('#undo').onclick=()=>mutate('/api/undo',{},false);$('#next').onclick=()=>mutate('/api/next',{},false);
 $('#cancel').onclick=()=>{pausedRevision=state.revision;cancel();$('#handoff').textContent='Handoff paused. Review the turn, then choose Next player.';};
 $('#auto').onchange=()=>{pausedRevision=null;schedule();};$('#new-game').onclick=()=>{cancel();pausedRevision=state.revision;showSetup=true;paint();$('#start').focus();};
 async function poll(){
  checking=true;
  try{
   const fresh=await DartRoom.request('/api/state');
   lastHealthy=Date.now();
   DartRoom.connection('CONNECTED · HOST');
   if(!busy&&(!state||fresh.revision>state.revision)){
    // Camera games change the match on their own (auto-accept): no review notice for those.
    if(state&&!fresh.camera_game){
     cancel();
     pausedRevision=fresh.revision;
     notice('Match updated. Review the current turn before continuing.');
    }
    state=fresh;
    paint();
    if(fresh.camera_game)schedule();
   }else if(!busy&&fresh.revision===state.revision){
    state=fresh;
    polledAt=performance.now();
    paint();
   }
  }catch(e){
   cancel();
   pausedRevision=state?.revision;
   DartRoom.connection(e.status===401?'PAIRING LINK REQUIRED':'CONNECTION LOST');
   notice(e.status===401?'Open the full private controller link printed by the host.':'Connection lost. Automatic handoff is paused.');
  }finally{
   checking=false;
   setTimeout(poll,state?.camera_game?400:1000);
  }
 }
 poll();
})();
