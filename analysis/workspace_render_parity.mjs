// Explicit opt-in Node diagnostic: compare extracted services with archived page functions.
// node analysis/workspace_render_parity.mjs OLD_INDEX PROJECTION PLAYERS [CANDIDATE_MODULE]
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const [oldPath,projectionPath,playersPath,candidate]=process.argv.slice(2);
if(!oldPath||!projectionPath||!playersPath)throw Error('Pass archived index.html, projection.json and players.json');
const Workspace=await import(candidate?pathToFileURL(candidate):new URL('../scripts/webapp/workspace.mjs',import.meta.url));
const result=JSON.parse(readFileSync(projectionPath,'utf8')),players=JSON.parse(readFileSync(playersPath,'utf8'));
globalThis.document={getElementById:()=>null,addEventListener(){}};globalThis.window=globalThis;globalThis.__workspaceServices=Workspace;
async function load(path){
 const source=readFileSync(path,'utf8').match(/<script>([\s\S]*)<\/script>/)[1].replace(/\nboot\(\);\s*$/,'\n');
 const bridge=`
 if(typeof setWorkspaceServices==='function')setWorkspaceServices(globalThis.__workspaceServices);
 globalThis.__parity={scatter,lineChart,playerLeadersData,LC,
   setup(state){RESULT=state.result;PLAYERS=state.players;PLAYERS_FOR=RESULT;PLAYERS_STATUS='ready';
     BADGES=state.badges;FOCUS=state.focus;VIZOPT.marks=state.marks;
     for(const key of Object.keys(HL))delete HL[key];for(const key of Object.keys(HLCOL))delete HLCOL[key];
     HL.Test=['Alpha','Beta'];HLCOL.Test={Alpha:0,Beta:1};}
 };`;
 await import('data:text/javascript;base64,'+Buffer.from(source+bridge).toString('base64'));
 return globalThis.__parity;
}
const old=await load(oldPath),next=await load(new URL('../scripts/webapp/index.html',import.meta.url));
let charts=0,playerSelections=0;
const state={result,players,badges:{Alpha:'1.png'},focus:null,marks:'badges'};
const pts=[{team:'Alpha',x:1,y:2,tone:'good',tip:'Alpha:1,2',from:[.8,1.7]},{team:'Beta',x:2,y:1,tone:'bad',tip:'Beta:2,1'}];
for(const focus of [null,'Alpha','Beta'])for(const marks of ['badges','dots'])for(const options of [{},{invertY:true,same:true},{domain:[0,3],noTeams:true,diag:[[0,'Equal']],quad:{x:1,y:1},corners:{tl:'Top left',br:'Bottom right'}}]){
 state.focus=focus;state.marks=marks;old.setup(state);next.setup(state);
 const config={xlab:'X',ylab:'Y',title:'Parity',...options};
 if(old.scatter(pts,config)!==next.scatter(pts,config))throw Error(`scatter parity failed:focus=${focus},marks=${marks},options=${JSON.stringify(options)}`);
 charts++;
}
for(const realUpTo of [0,1,2])for(const invert of [false,true]){
 old.setup(state);next.setup(state);
 const config={block:{competition:'Test',teams:[{team:'Alpha',mean_pos:1},{team:'Beta',mean_pos:2}]},id:'parity',vals:new Map([['Alpha',[1,null,3]],['Beta',[null,2,null]]]),labels:['One','Two','Three'],realUpTo,invert,mark:1,markLabel:'Window'};
 if(old.lineChart(config)!==next.lineChart(config))throw Error(`line parity failed:realUpTo=${realUpTo},invert=${invert}`);
 for(const name of ['lit','col','labels','n'])if(JSON.stringify(old.LC.parity[name])!==JSON.stringify(next.LC.parity[name]))throw Error('line registry differs:'+name);
 for(let i=0;i<3;i++)if(old.LC.parity.X(i)!==next.LC.parity.X(i)||old.LC.parity.Y(i)!==next.LC.parity.Y(i))throw Error('crosshair coordinate differs');
 charts++;
}
old.setup(state);next.setup(state);
for(const [competition,block] of Object.entries(players.competitions||{})){
 const club=block.players?.find(p=>Object.keys(p.by_team||{}).length>1)?.teams[0]||block.players?.[0]?.teams[0];
 for(const metric of ['goals','xg','finishing','xg90','assists','shots'])for(const team of ['all',...(club?[club]:[])])for(const floor of metric==='xg90'?[90,180,900]:[180]){
  const before=old.playerLeadersData(competition,metric,team,floor),after=next.playerLeadersData(competition,metric,team,floor);
  if(JSON.stringify(before)!==JSON.stringify(after))throw Error(`player selector differs:${competition}/${metric}/${team}/${floor}`);
  playerSelections++;
 }
}
if(!charts||!playerSelections)throw Error('empty parity population');
console.log(`PASS ${charts} byte-identical scatter/line renders and crosshair states; ${playerSelections} exact player selections against archived implementation`);
