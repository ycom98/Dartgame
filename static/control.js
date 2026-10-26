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
 $('#record').disabled=busy||Date.now()<entryReadyAt||done()||g.winner!==null||state.camera_game;$('#next').disabled=busy||!done()||state.camera_game;$('#undo').disabled=busy;$('#auto').disabled=state.camera_game;const tap=tapAllowed();$('#tap-board').classList.toggle('disabled',!tap);$('#miss').disabled=!tap;
 if(state.camera_game){$('#handoff').textContent='Camera match: continue using camera setup controls. Automatic handoff is paused.';}
 }
 function schedule(){cancel();if(!done()||!$('#auto').checked||state.camera_game||pausedRevision===state.revision)return;const rev=state.revision;let left=4;$('#cancel').hidden=false;$('#handoff').textContent='Next player in '+left+' seconds · Undo or pause to review.';tick=setInterval(()=>{left--;$('#handoff').textContent='Next player in '+Math.max(left,0)+' seconds · Undo or pause to review.';},1000);timer=setTimeout(()=>{cancel();if(checking||Date.now()-lastHealthy>1500){pausedRevision=rev;notice('Connection check pending. Handoff paused; review the turn before choosing Next player.');return;}if(state.revision===rev&&!busy)mutate('/api/next',{},false);},4000);}
 async function mutate(path,body={},allowSchedule=true){if(busy)return;if(path==='/api/throw'){if(Date.now()<entryReadyAt)return;entryReadyAt=Date.now()+600;setTimeout(paint,610);}cancel();busy=true;notice('');paint();const revision=state?.revision;try{const payload=path==='/api/game'?body:{...body,expected_revision:revision};state=await DartRoom.request(path,payload);showSetup=false;pausedRevision=null;paint();if(allowSchedule)schedule();}catch(e){pausedRevision=e.state?.revision??revision;if(e.state?.game!==undefined)state=e.state;notice(e.status===409?e.message:e.status?'Could not save: '+e.message:'Connection interrupted. Check the current match before trying again.');if(!e.status){try{state=await DartRoom.request('/api/state');}catch{} } }finally{busy=false;paint();}}
 function names(){const old=[...$('#names').querySelectorAll('input')].map(i=>i.value);$('#names').replaceChildren();for(let i=0;i<Number($('#count').value);i++){const l=document.createElement('label');l.textContent='Player '+(i+1);const input=document.createElement('input');input.name='player';input.required=true;input.maxLength=30;input.placeholder=['Alex','Maya','Jordan','Sam'][i];input.value=old[i]||'';input.autocomplete='off';l.append(input);$('#names').append(l);}}
 $('#count').onchange=names;names();
 $('#setup').onsubmit=e=>{e.preventDefault();mutate('/api/game',{names:[...document.querySelectorAll('#names input')].map(i=>i.value.trim()),start:Number($('#start').value),double_out:$('#finish').value==='double',camera:false});};
 $('#value').replaceChildren();for(const [v,title] of [[0,'Miss'],...[...Array(20)].map((_,i)=>[i+1,String(i+1)]),[25,'Bull / outer bull']]){const o=document.createElement('option');o.value=v;o.textContent=title;$('#value').append(o);}$('#value').value=20;
 function normalize(){const v=Number($('#value').value);if(v===0)ring=1;if(v===25&&ring===3)ring=2;document.querySelectorAll('[data-ring]').forEach(b=>{const r=Number(b.dataset.ring);b.disabled=(v===0&&r!==1)||(v===25&&r===3);b.setAttribute('aria-pressed',String(r===ring));});$('#entry-preview').textContent=DartRoom.label({value:v,multiplier:ring})+' · '+(v*ring)+' points';}
 document.querySelectorAll('[data-ring]').forEach(b=>b.onclick=()=>{ring=Number(b.dataset.ring);normalize();});$('#value').onchange=normalize;normalize();
 $('#dart-form').onsubmit=e=>{e.preventDefault();if($('#record').disabled)return;mutate('/api/throw',{value:Number($('#value').value),multiplier:ring});};

 /* Tap-the-board entry (M1-11). Same 600 ms duplicate guard as Record dart (mutate). */
 function tapAllowed(){const g=state?.game;return !!g&&!busy&&Date.now()>=entryReadyAt&&!done()&&g.winner===null&&!state.camera_game;}
 function tapScore(value,multiplier,key){if(!tapAllowed())return;if(key)DartBoard.flash($('#tap-board'),key);$('#tap-feedback').textContent=value===0?'Miss':DartBoard.label(value,multiplier);mutate('/api/throw',{value,multiplier});}
 DartBoard.tapBoard($('#tap-board'),tapScore);
 $('#miss').onclick=()=>tapScore(0,1,null);
 $('#undo').onclick=()=>mutate('/api/undo',{},false);$('#next').onclick=()=>mutate('/api/next',{},false);
 $('#cancel').onclick=()=>{pausedRevision=state.revision;cancel();$('#handoff').textContent='Handoff paused. Review the turn, then choose Next player.';};
 $('#auto').onchange=()=>{pausedRevision=null;schedule();};$('#new-game').onclick=()=>{cancel();pausedRevision=state.revision;showSetup=true;paint();$('#start').focus();};
 async function poll(){checking=true;try{const fresh=await DartRoom.request('/api/state');lastHealthy=Date.now();DartRoom.connection('CONNECTED · HOST');if(!busy&&(!state||fresh.revision>state.revision)){if(state){cancel();pausedRevision=fresh.revision;notice('Match updated. Review the current turn before continuing.');}state=fresh;paint();}}catch(e){cancel();pausedRevision=state?.revision;DartRoom.connection(e.status===401?'PAIRING LINK REQUIRED':'CONNECTION LOST');notice(e.status===401?'Open the full private controller link printed by the host.':'Connection lost. Automatic handoff is paused.');}finally{checking=false;setTimeout(poll,1000);}}poll();
})();
