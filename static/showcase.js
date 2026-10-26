/* A local scripted 301 match. No fetch, camera access, or live mutations. */
(()=>{let timer,playing=true,index=0,due=0,remaining=2700;const snapshots=[];
 const g={names:['Kapil','Aita'],scores:[301,301],start:301,double_out:false,player:0,turn_start:301,darts:[],bust:false,winner:null,turn:1};
 const save=()=>snapshots.push(structuredClone(g));save();
 function hit(value,multiplier){g.darts.push({value,multiplier,score:value*multiplier});g.scores[g.player]-=value*multiplier;if(!g.scores[g.player])g.winner=g.player;save();}
 function next(){g.player=1-g.player;g.turn++;g.turn_start=g.scores[g.player];g.darts=[];save();}
 hit(20,3);hit(20,3);hit(20,3);next();hit(20,3);hit(5,1);hit(20,1);next();hit(20,3);hit(11,1);hit(25,2);
 function render(restart=false){DartRoom.render(snapshots[index],{restart});}
 function queue(reset=true){clearTimeout(timer);if(reset)remaining=snapshots[index].winner!==null?6500:snapshots[index].darts.length===3?5500:2700;if(!playing)return;due=performance.now()+remaining;timer=setTimeout(()=>{index=(index+1)%snapshots.length;render();queue();},remaining);}
 document.querySelector('#pause').onclick=()=>{if(playing)remaining=Math.max(0,due-performance.now());playing=!playing;DartRoom.setPaused(!playing);document.querySelector('#pause').textContent=playing?'Pause':'Play';queue(false);};document.querySelector('#restart').onclick=()=>{playing=true;DartRoom.setPaused(false);document.querySelector('#pause').textContent='Pause';index=0;render(true);queue();};render();queue();
})();
