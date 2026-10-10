'use strict';

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');

test('atomic multi-room automation uses live scheduler and one shared member balance',async()=>{
 const root=path.resolve(__dirname,'..');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'autobet-http-test-'));
 const port=await new Promise(resolve=>{const listener=net.createServer();listener.listen(0,'127.0.0.1',()=>{const value=listener.address().port;listener.close(()=>resolve(value));});});
 const base=`http://127.0.0.1:${port}`;
 let child,cookie='',stderr='';
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 async function start(){
  stderr='';
  child=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,PORT:String(port),PUBLIC_ORIGIN:base,LOCAL_CENTER_DATA:dir},stdio:['ignore','pipe','pipe'],windowsHide:true});
  child.stderr.on('data',value=>stderr+=value);
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('startup timeout: '+stderr)),15000);child.stdout.once('data',()=>{clearTimeout(timer);resolve();});child.once('exit',code=>{clearTimeout(timer);reject(Error('startup '+code+': '+stderr));});});
 }
 async function stop(){if(child&&child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});}
 async function request(url,data,options={}){
  const result=await fetch(base+url,{method:data===undefined?'GET':'POST',headers:{Cookie:options.cookie??cookie,...(data===undefined?{}:{'Content-Type':'application/json',Origin:base}),...options.headers},body:data===undefined?undefined:JSON.stringify(data)});
  return {status:result.status,data:await result.json(),cookie:result.headers.get('set-cookie')?.split(';')[0]};
 }
 async function ok(url,data,options){const response=await request(url,data,options);assert.equal(response.status,200,JSON.stringify(response.data));return response.data;}
 const action=async(operation,data={},game='canada28',requestId=crypto.randomUUID())=>{const access=await ok('/api/room-access');if(!access.configured)await ok('/api/room-access/password',{adminPassword:'LocalDemo2026!',newPassword:'TestRooms2026!'});if(!access.unlocked)await ok('/api/room-access/unlock',{password:'TestRooms2026!'});return ok('/api/rooms/action',{operation,game,memberPassword:'admin123',data:{...data,requestId}});};
 const state=()=>ok('/api/rooms?game=canada28');
 const games=['canada28','australia8','australia8ball'];
 const settings={username:'simulated1',rooms:games,enabled:true,amountMin:'14',amountMax:'14',selections:['1番'],intervalSeconds:5,betsPerRound:1,ball:8};
 try{
  await start();
  assert.equal((await request('/api/rooms/action',{operation:'member.autobet.batch',memberPassword:'admin123',game:'canada28',data:{...settings,requestId:crypto.randomUUID()}},{cookie:''})).status,401);
  cookie=(await request('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;
  assert.ok(cookie);
  for(const game of games)await action('config',{mode:'manual',period:600,closeSeconds:10,paused:false},game);
  await action('member.create',{username:'simulated1',nickname:'自动测试会员',amount:'100'});
  await action('member.edit',{username:'simulated1',robot:true,auto:true});
  // A legacy display-only auto flag must not implicitly opt a user into automation.
  await sleep(1200);
  assert.equal((await state()).orders.length,0);
  const link=await ok('/api/rooms/member-link?username=simulated1');
  const oldToken=new URL(link.url).hash.slice('#access='.length);
  let portalOptions={cookie:'',headers:{'X-Member-Access':oldToken,'X-Member-Device':'a'.repeat(64)}};
  await ok('/api/portal/login',{},portalOptions);
  assert.equal((await request('/api/rooms/action',{operation:'member.autobet.batch',memberPassword:'admin123',game:'canada28',data:{...settings,requestId:crypto.randomUUID()}},portalOptions)).status,403);
  await action('member.edit',{username:'simulated1',robot:false,enabled:false});
  const beforeInvalid=await state();
  const blocked=await request('/api/rooms/action',{operation:'member.autobet.batch',memberPassword:'admin123',game:'canada28',data:{...settings,requestId:crypto.randomUUID()}});
  assert.equal(blocked.status,400,'disabled ordinary account requires explicit activation');
  const invalid=await request('/api/rooms/action',{operation:'member.autobet.batch',memberPassword:'admin123',game:'canada28',data:{...settings,activateMember:true,amountMin:'0',requestId:crypto.randomUUID()}});
  assert.equal(invalid.status,400,JSON.stringify(invalid.data));
  assert.deepEqual((await state()).users,beforeInvalid.users,'invalid batch must not activate identity or any room');
  const saveId=crypto.randomUUID();
  await action('member.autobet.batch',{...settings,activateMember:true},'canada28',saveId);
  await action('member.autobet.batch',{...settings,activateMember:true},'canada28',saveId);
  assert.equal((await request('/api/portal/state?game=canada28',undefined,portalOptions)).status,403,'previously disabled identity must keep old links revoked');
  const renewed=await ok('/api/rooms/member-link?username=simulated1');
  const token=new URL(renewed.url).hash.slice('#access='.length);
  assert.notEqual(token,oldToken);
  portalOptions={cookie:'',headers:{'X-Member-Access':token,'X-Member-Device':'a'.repeat(64)}};
  await ok('/api/portal/login',{},portalOptions);
  let snapshot=await state();
  let user=snapshot.users.find(value=>value.username==='simulated1');
  assert.equal(user.enabled,true);assert.equal(user.robot,true);
  for(const game of games){assert.equal(user.autoBet[game].amountMin,1400);assert.equal(user.autoBet[game].amountMax,1400);assert.equal(user.autoBet[game].enabled,true);}
  const deadline=Date.now()+9000;
  while(snapshot.orders.length<3&&Date.now()<deadline){await sleep(250);snapshot=await state();}
  assert.equal(snapshot.orders.length,3,JSON.stringify({status:snapshot.users.find(value=>value.username==='simulated1').autoBetStatus,stderr}));
  const order=snapshot.orders.find(row=>row.game==='canada28');
  assert.equal(order.source,'simulated-auto');assert.equal(order.simulated,true);
  assert.equal(order.amount,1400);assert.equal(order.status,'待开奖');
  let portal=await ok('/api/portal/state?game=canada28',undefined,portalOptions);
  assert.equal(portal.orders[0].id,order.id);assert.equal(portal.score,5800);
  assert.equal(snapshot.users.find(value=>value.username==='simulated1').balance,portal.score);
  for(const game of games){const p=await ok('/api/portal/state?game='+game,undefined,portalOptions);assert.equal(p.balance,5800);assert.equal(p.orders.length,1);assert.deepEqual(Object.values(p.wallets),[5800,5800,5800]);}
  assert.ok(snapshot.ledger.some(row=>row.ref===order.batch&&row.delta===-1400&&row.simulated));
  assert.ok(snapshot.chat.some(row=>row.username==='simulated1'&&row.simulated));
  await action('member.autobet.batch',{username:'simulated1',rooms:[],enabled:false});
  await action('member.autobet.batch',settings);
  await stop();await start();
  cookie=(await request('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;
  await sleep(6200);
  snapshot=await state();
  assert.equal(snapshot.orders.length,3,'each room cap must survive toggling and restart');
  user=snapshot.users.find(value=>value.username==='simulated1');
  for(const game of games){assert.equal(user.autoBetStatus[game].count,1);assert.equal(user.autoBet[game].enabled,true);}
  await action('member.autobet.batch',{username:'simulated1',rooms:[],enabled:false});
  await action('draw',{numbers:'0,0,1',issue:snapshot.round.issue});
  snapshot=await state();portal=await ok('/api/portal/state?game=canada28',undefined,portalOptions);
  assert.equal(portal.orders[0].status,'中奖');
  assert.equal(portal.score,5800+portal.orders[0].payout);
  assert.equal(snapshot.users.find(value=>value.username==='simulated1').balance,portal.score);
  for(const game of games)assert.equal((await ok('/api/portal/state?game='+game,undefined,portalOptions)).score,portal.score);
  assert.equal(snapshot.ledger.filter(row=>row.username==='simulated1').reduce((sum,row)=>sum+row.delta,0),portal.score);
  assert.doesNotMatch(stderr,/Room scheduler:|Traceback/);
 }finally{
  await stop();
  assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));
  assert.ok(path.basename(dir).startsWith('autobet-http-test-'));
  fs.rmSync(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});
 }
});
