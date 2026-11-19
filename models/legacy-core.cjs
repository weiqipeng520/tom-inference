(function (root) {
'use strict';
// Fixed, predeclared hyperparameters. No search/tuning on the holdout.
const VERSION = '1.0.0';
const ZODIAC = Object.freeze(Array.from('鼠牛虎兔龙蛇马羊猴鸡狗猪'));
const NUM_K = [36, 24, 16, 8, 4], ZOD_K = [9, 6, 4, 2];
const C = Object.freeze({longWindow:730,shortWindow:90,dirichletPrior:98,shortPrior:98,shortMix:0.35,halfLife:90,decayPrior:49,markovPrior:98,weightBurnIn:90,learningRate:0.08,weightPrior:0.03,mappingWindow:90});
const ALGORITHMS = Object.freeze([
 Object.freeze({id:'dirichlet',name:'Dirichlet长短窗收缩频率'}),
 Object.freeze({id:'exponential',name:'固定半衰期指数衰减频率'}),
 Object.freeze({id:'markov',name:'一阶Markov先验回退'}),
 Object.freeze({id:'ensemble',name:'逐期对数损失指数加权融合'}),
 Object.freeze({id:'uniform',name:'独立均匀概率基线'})
]);
const ALIASES = {'龍':'龙','馬':'马','雞':'鸡','豬':'猪'};
const uniform = () => Array(49).fill(1/49);
const normalZ = z => ALIASES[z] || z;
function issue(value) {
 const s=String(value===undefined?'':value);
 if (!/^\d{7}$/.test(s) || Number(s.slice(4))<1) throw Error('期号须为7位年份加期次');
 return s;
}
function canonical(records, target) {
 if (!Array.isArray(records)) throw TypeError('records须为数组');
 const byExpect = new Map();
 for (const raw of records) {
  const expect=issue(raw && raw.expect);
  // Exclude future rows BEFORE inspecting any of their outcome/date fields.
  if (target && expect>=target) continue;
  if (!Array.isArray(raw.numbers) || raw.numbers.length!==7) throw Error(expect+': 需要7个开奖号码');
  const numbers=raw.numbers.map(Number);
  if (numbers.some(n=>!Number.isInteger(n)||n<1||n>49)||new Set(numbers).size!==7) throw Error(expect+': 号码范围或唯一性错误');
  const zodiac=Array.isArray(raw.zodiac)?raw.zodiac.map(normalZ):Array(7).fill('');
  if (zodiac.length!==7||zodiac.some(z=>z!==''&&!ZODIAC.includes(z))) throw Error(expect+': 生肖格式错误');
  const openTime=String(raw.openTime||'').replace('T',' ');
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(openTime)||openTime.slice(0,4)!==expect.slice(0,4)) throw Error(expect+': 日期格式或年份错误');
  if (root.LiveCore) root.LiveCore.parseTime(openTime);
  else {
   const p=openTime.split(/[- :]/).map(Number), d=new Date(Date.UTC(p[0],p[1]-1,p[2],p[3],p[4],p[5]));
   if (d.getUTCFullYear()!==p[0]||d.getUTCMonth()+1!==p[1]||d.getUTCDate()!==p[2]||d.getUTCHours()!==p[3]||d.getUTCMinutes()!==p[4]||d.getUTCSeconds()!==p[5]) throw Error(expect+': 日期无效');
  }
  const row={expect,openTime,numbers,zodiac};
  if (byExpect.has(expect)&&JSON.stringify(byExpect.get(expect))!==JSON.stringify(row)) throw Error(expect+': 同期记录冲突');
  byExpect.set(expect,row);
 }
 const result=[...byExpect.values()].sort((a,b)=>a.expect.localeCompare(b.expect));
 for(let i=1;i<result.length;i++) if(result[i].openTime<result[i-1].openTime) throw Error('期号顺序与开奖时间顺序冲突');
 return result;
}
function fingerprint(rows) {
 // Deterministic pair of 32-bit FNV-style hashes; not a security signature.
 let a=0x811c9dc5,b=0x9e3779b9;
 const text=VERSION+'|'+JSON.stringify(C)+'|'+rows.map(r=>[r.expect,r.openTime,r.numbers.join(','),r.zodiac.join(',')].join('|')).join('\n');
 for(let i=0;i<text.length;i++){const c=text.charCodeAt(i);a=Math.imul(a^c,0x01000193)>>>0;b=Math.imul(b^c,0x85ebca6b)>>>0;}
 return 'fnv-pair-'+a.toString(16).padStart(8,'0')+b.toString(16).padStart(8,'0');
}
function trainingFingerprint(records){return fingerprint(canonical(records));}
function normalized(p){const sum=p.reduce((a,b)=>a+b,0);return p.map(v=>v/sum);}
function rankNumbers(p){return Array.from({length:49},(_,i)=>i+1).sort((a,b)=>p[b-1]-p[a-1]||a-b);}
function subsets(rank,sizes){const out={};for(const k of sizes)out[k]=rank.slice(0,k);return out;}
function createState(){return {n:0,previous:-1,long:Array(49).fill(0),short:Array(49).fill(0),decay:Array(49).fill(0),decayTotal:0,trans:Array.from({length:49},()=>Array(49).fill(0)),transTotals:Array(49).fill(0),queue:[],loss:Array(3).fill(0),updates:0};}
function weights(s){
 const min=Math.min(...s.loss),a=s.loss.map(l=>Math.exp(-C.learningRate*(l-min))),sum=a.reduce((x,y)=>x+y,0);
 return a.map(v=>(1-C.weightPrior)*v/sum+C.weightPrior/3);
}
function forecast(s){
 const nl=Math.min(s.n,C.longWindow),ns=Math.min(s.n,C.shortWindow);
 const prior=s.long.map(c=>(c+C.dirichletPrior/49)/(nl+C.dirichletPrior));
 const dir=prior.map((p,i)=>(1-C.shortMix)*p+C.shortMix*(s.short[i]+C.shortPrior*p)/(ns+C.shortPrior));
 const exp=s.decay.map(c=>(c+C.decayPrior/49)/(s.decayTotal+C.decayPrior));
 const mark=s.previous<0?prior.slice():prior.map((p,i)=>(s.trans[s.previous][i]+C.markovPrior*p)/(s.transTotals[s.previous]+C.markovPrior));
 const ps=[normalized(dir),normalized(exp),normalized(mark)],w=weights(s);
 const ensemble=normalized(Array.from({length:49},(_,i)=>ps.reduce((v,p,j)=>v+w[j]*p[i],0)));
 return {ps,w,ensemble};
}
function observe(s,row,fc){
 const x=row.numbers[6]-1;
 // Score the forecast made WITHOUT this row, then reveal and update state.
 if(s.n>=C.weightBurnIn){for(let j=0;j<3;j++)s.loss[j]-=Math.log(fc.ps[j][x]);s.updates++;}
 const decay=Math.pow(0.5,1/C.halfLife);
 for(let i=0;i<49;i++)s.decay[i]*=decay;
 s.decay[x]++;s.decayTotal=s.decayTotal*decay+1;
 s.queue.push(x);s.long[x]++;s.short[x]++;
 if(s.n>=C.longWindow)s.long[s.queue[s.n-C.longWindow]]--;
 if(s.n>=C.shortWindow)s.short[s.queue[s.n-C.shortWindow]]--;
 if(s.previous>=0){s.trans[s.previous][x]++;s.transTotals[s.previous]++;}
 s.previous=x;s.n++;
}
function mapping(rows,target){
 // The latest consistent mapping epoch wins. Scan only earlier visible rows,
 // accumulating number % 12 observations until a contradictory epoch is met.
 const residue=Array(12).fill(null),seen=Array(12).fill(0);let through=null,used=0,conflict=false,epochOffset=null;
 for(let i=rows.length-1;i>=Math.max(0,rows.length-C.mappingWindow);i--){
  const r=rows[i],pairs=[];let bad=false;
  for(let j=0;j<7;j++){
   const z=r.zodiac[j];if(!z)continue;const rem=(r.numbers[j]-1)%12;
   const existing=pairs.find(p=>p[0]===rem);
   if(existing&&existing[1]!==z){bad=true;break;}pairs.push([rem,z]);
  }
  if(bad||pairs.length===0)continue;
  // Even disjoint observed residues must belong to the same zodiac cycle.
  // Without this check, sparse rows on opposite sides of lunar new year can
  // silently mix two epochs before an overlapping residue reveals conflict.
  const offsets=pairs.map(([rem,z])=>(ZODIAC.indexOf(z)+rem)%12);
  if(offsets.some(v=>v!==offsets[0]))continue;
  if(epochOffset!==null&&epochOffset!==offsets[0]){conflict=true;break;}
  if(pairs.some(([rem,z])=>residue[rem]&&residue[rem]!==z)){conflict=true;break;}
  epochOffset=offsets[0];
  if(!through)through=r.expect;used++;
  for(const [rem,z]of pairs){residue[rem]=z;seen[rem]++;}
  if(residue.every(Boolean))break;
 }
 // A standard zodiac cycle is determined by one observed anchor. It is used
 // only to complete sparse observations, never from calendar year or future data.
 let inferred=0,anchor=residue.findIndex(Boolean);
 if(anchor>=0){
  const zi=ZODIAC.indexOf(residue[anchor]);
  for(let r=0;r<12;r++){if(!residue[r]){residue[r]=ZODIAC[(zi-(r-anchor)+24)%12];inferred++;}}
  if(new Set(residue).size!==12)throw Error('历史号码生肖映射不是完整12生肖排列');
 }else{throw Error('至少需要一期包含有效生肖的历史记录以建立预测时映射');}
 const map={};for(let n=1;n<=49;n++)map[n]=residue[(n-1)%12];
 const latest=rows[rows.length-1],yearCross=!!(latest&&target.slice(0,4)!==latest.expect.slice(0,4));
 const note='仅依据预测前可见号码/生肖，按mod12累积最近映射；来源截至'+through+'，使用'+used+'期'+(inferred?'，稀疏余数由观测锚点周期补全'+inferred+'项':'，12余数已观测完整')+'。农历换年边界仍沿用最新已见映射待确认，不按公历年份硬套'+(yearCross?'；目标跨公历年':'' )+'。';
 return {map,note,through,used,inferred,conflict};
}
function zodiacProjection(p,map){
 const probs=Array(12).fill(0);for(let n=1;n<=49;n++)probs[ZODIAC.indexOf(map[n])]+=p[n-1];
 const rank=ZODIAC.slice().sort((a,b)=>probs[ZODIAC.indexOf(b)]-probs[ZODIAC.indexOf(a)]||ZODIAC.indexOf(a)-ZODIAC.indexOf(b));
 return {probs,rank};
}
function generate(records,targetExpect){
 const target=issue(targetExpect),rows=canonical(records,target);
 if(!rows.length)throw Error('预测期之前没有可训练开奖记录');
 const s=createState();for(const row of rows){const f=forecast(s);observe(s,row,f);}
 const f=forecast(s),m=mapping(rows,target),rank=rankNumbers(f.ensemble),z=zodiacProjection(f.ensemble,m.map);
 return {version:VERSION,targetExpect:target,trainingThrough:rows[rows.length-1].expect,trainingCount:rows.length,trainingFingerprint:fingerprint(rows),numberRanking:rank,numberSets:subsets(rank,NUM_K),zodiacRanking:z.rank,zodiacSets:subsets(z.rank,ZOD_K),models:f.ps.map((p,i)=>({id:ALGORITHMS[i].id,name:ALGORITHMS[i].name,weight:f.w[i],probabilities:p,rank:rankNumbers(p)})),probabilities:f.ensemble,zodiacProbabilities:z.probs,zodiacMap:m.map,mappingNote:m.note,modelNote:'确定性统计候选，不声称可预测独立随机开奖；仅特码numbers[6]训练；指数半衰期固定90个已观测开奖期（非日历天），一阶Markov先验强度98。固定超参数：'+JSON.stringify(C)+'；融合仅使用已发生逐期预测的对数损失，权重自第'+C.weightBurnIn+'期后更新；均匀基线仅计分，不参与选号。'};
}
function wilson(hits,total){if(!total)return [0,1];const z=1.959963984540054,p=hits/total,z2=z*z,d=1+z2/total,c=(p+z2/(2*total))/d,half=z*Math.sqrt(p*(1-p)/total+z2/(4*total*total))/d;return [Math.max(0,c-half),Math.min(1,c+half)];}
function metric(hits,total,baseline){const [wilsonLow,wilsonHigh]=wilson(hits,total),rate=total?hits/total:0;return {hits,total,rate,baseline,wilsonLow,wilsonHigh,lift:baseline?rate/baseline:0};}
function backtest(records,options){
 const rows=canonical(records),opts=options||{},holdout=opts.holdout===undefined?365:opts.holdout,burnIn=opts.burnIn===undefined?365:opts.burnIn;
 if(!Number.isInteger(holdout)||holdout<1||!Number.isInteger(burnIn)||burnIn<1)throw Error('holdout和burnIn须为正整数');
 const first=Math.max(burnIn,rows.length-holdout);
 if(first>=rows.length)throw Error('有效历史不足以满足burnIn并留出测试期');
 const s=createState(),acc=ALGORITHMS.map(a=>({id:a.id,name:a.name,number:Object.fromEntries(NUM_K.map(k=>[k,0])),zodiac:Object.fromEntries(ZOD_K.map(k=>[k,0])),coverage:Object.fromEntries(ZOD_K.map(k=>[k,0])),loss:0,brier:0}));
 let count=0,mappingMismatch=0;
 for(let t=0;t<rows.length;t++){
  const row=rows[t],f=forecast(s);
  if(t>=first){
   const map=mapping(rows.slice(0,t),row.expect).map,actual=row.numbers[6],actualZ=row.zodiac[6],ps=[...f.ps,f.ensemble,uniform()];
   if(!actualZ)throw Error(row.expect+': 回测生肖计分需要实际特码生肖，禁止用预测映射代替真实标签');
   count++;
   if(actualZ!==map[actual])mappingMismatch++;
   for(let j=0;j<ps.length;j++){
    const a=acc[j],p=ps[j],rank=rankNumbers(p),z=zodiacProjection(p,map);
    a.loss-=Math.log(p[actual-1]);for(let k=0;k<49;k++)a.brier+=(p[k]-(k===actual-1?1:0))**2;
    if(a.id==='uniform')continue;
    for(const k of NUM_K)if(rank.slice(0,k).includes(actual))a.number[k]++;
    for(const k of ZOD_K){const selected=z.rank.slice(0,k);if(selected.includes(actualZ))a.zodiac[k]++;let covered=0;for(let n=1;n<=49;n++)if(selected.includes(map[n]))covered++;a.coverage[k]+=covered/49;}
   }
  }
  observe(s,row,f);
 }
 const algorithms=acc.map(a=>{
  const numberHits={},zodiacHits={};
  if(a.id!=='uniform'){
   for(const k of NUM_K)numberHits[k]=metric(a.number[k],count,k/49);
   for(const k of ZOD_K)zodiacHits[k]=metric(a.zodiac[k],count,a.coverage[k]/count);
  }
  return {id:a.id,name:a.name,numberHits,zodiacHits,logLoss:a.loss/count,brier:a.brier/count};
 });
 return {version:VERSION,split:{testFirst:rows[first].expect,testLast:rows[rows.length-1].expect,testCount:count,burnIn,method:'chronological expanding-window walk-forward; predict before observe; last holdout periods; ensemble learns past losses only'},algorithms,uniformLogLoss:Math.log(49),notes:['仅特码为49分类目标；所有超参数预先固定，没有在本留出集上调参。','每期预测、生肖选择及融合权重均只取更早期记录；实际当期生肖仅用于事后命中计分。','生肖均匀基线=预测时映射中所选生肖实际覆盖号码数/49，并对测试期取平均，不等同于生肖数/12。','号码TopK固定tie-break可能固定覆盖部分号码；随机独立均匀开奖的参考覆盖为K/49。','Wilson为单模型单集合命中率95%描述区间，未作多重比较校正；lift=实际命中率/均匀覆盖参考。','logLoss为平均自然对数损失，brier为49分类概率平方误差之和的均值；均匀基线只计概率分数。','本结果是历史逐期回测，并非对独立随机开奖可预测性的证明。','预测前映射与当期实际生肖不一致期数：'+mappingMismatch+'；农历换年边界沿用最新映射待确认。']};
}
function audit(records,targetExpect){const r=generate(records,targetExpect);return {version:VERSION,targetExpect:r.targetExpect,trainingThrough:r.trainingThrough,trainingCount:r.trainingCount,trainingFingerprint:r.trainingFingerprint,probabilitySum:r.probabilities.reduce((a,b)=>a+b,0),weightSum:r.models.reduce((a,b)=>a+b.weight,0),parameters:C,weightMethod:'prequential Hedge with uniform weight floor; no current/future outcome',zodiacOrder:ZODIAC.slice()};}
const api={VERSION,ALGORITHMS,generate,backtest,trainingFingerprint,audit};
root.PredictionCore=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
