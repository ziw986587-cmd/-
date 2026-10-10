'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');
test('one independent room password protects all rooms and robot configuration',async()=>{
 const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'room-access-test-'));
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 const base=`http://127.0.0.1:${port}`;let child,cookie='';
 async function start(){child=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,PORT:String(port),LOCAL_CENTER_DATA:dir},stdio:['ignore','pipe','pipe'],windowsHide:true});await new Promise((resolve,reject)=>{let logs='';child.stderr.on('data',s=>logs+=s);const timer=setTimeout(()=>reject(Error(logs)),15000);child.stdout.once('data',()=>{clearTimeout(timer);resolve();});child.once('exit',()=>{clearTimeout(timer);reject(Error(logs));});});}
 async function stop(){if(child?.exitCode===null)await new Promise(r=>{child.once('exit',r);child.kill();});}
 async function call(url,data,token=cookie){const r=await fetch(base+url,{method:data===undefined?'GET':'POST',headers:{Cookie:token,...(data===undefined?{}:{Origin:base,'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data)});return {status:r.status,value:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]};}
 async function login(password='LocalDemo2026!'){const r=await call('/api/login',{username:'localadmin',password});assert.equal(r.status,200);return r.cookie;}
 async function unlock(password='RoomTest2026!'){const r=await call('/api/room-access/unlock',{password});assert.equal(r.status,200,JSON.stringify(r));}
 try{
  await start();assert.equal((await call('/api/room-access')).status,401);cookie=await login();
  assert.deepEqual((await call('/api/room-access')).value,{ok:true,configured:false,unlocked:false});
  assert.equal((await call('/api/rooms?view=protected')).status,423);
  assert.equal((await call('/api/room-access/password',{adminPassword:'wrong',newPassword:'RoomTest2026!'})).status,400);
  assert.equal((await call('/api/room-access/password',{adminPassword:'LocalDemo2026!',newPassword:'short'})).status,400);
  assert.equal((await call('/api/room-access/password',{adminPassword:'LocalDemo2026!',newPassword:'RoomTest2026!'})).status,200);
  assert.equal((await call('/api/room-access/unlock',{password:'LocalDemo2026!'})).status,400,'login password must not unlock rooms');
  for(const game of ['canada28','australia8','australia8ball']){
   assert.equal((await call('/api/rooms?game='+game)).status,200,'home/member operations remain accessible');
   assert.equal((await call('/api/rooms?view=protected&game='+game)).status,423);
   for(const operation of ['config','close','force-open','draw','import','notice','robot.messages.save'])assert.equal((await call('/api/rooms/action',{operation,game,data:{}})).status,423,operation);
  }
  assert.equal((await call('/api/rooms/force-open-preview')).status,423);
  await unlock();
  for(const game of ['canada28','australia8','australia8ball'])assert.equal((await call('/api/rooms?view=protected&game='+game)).status,200);
  assert.equal((await call('/api/rooms/action',{operation:'config',game:'canada28',data:{requestId:require('node:crypto').randomUUID(),mode:'manual',period:600,closeSeconds:10}})).status,200);
  const snapshot=(await call('/api/rooms')).value,cfg=snapshot.robotConfig;
  assert.equal((await call('/api/rooms/action',{operation:'robot.messages.save',game:'canada28',data:{requestId:require('node:crypto').randomUUID(),revision:cfg.revision,bot:cfg.bot,name:cfg.name,entries:Object.fromEntries(cfg.entries.map(e=>[e.key,{text:e.text,enabled:e.enabled}]))}})).status,200);
  const another=await login();assert.equal((await call('/api/rooms?view=protected',undefined,another)).status,423);
  assert.equal((await call('/api/room-access/unlock',{password:'RoomTest2026!'},another)).status,200);
  assert.equal((await call('/api/room-access/password',{adminPassword:'LocalDemo2026!',newPassword:'RoomNext2026!'})).status,200);
  for(const token of [cookie,another])assert.equal((await call('/api/rooms?view=protected',undefined,token)).status,423,'rotation revokes every session');
  assert.equal((await call('/api/room-access/unlock',{password:'RoomTest2026!'})).status,400);await unlock('RoomNext2026!');
  assert.equal((await call('/api/logout',{})).status,200);cookie=await login();assert.equal((await call('/api/rooms?view=protected')).status,423);
  await unlock('RoomNext2026!');await stop();await start();cookie=await login();assert.equal((await call('/api/room-access')).value.configured,true);assert.equal((await call('/api/rooms?view=protected')).status,423);await unlock('RoomNext2026!');
  const stored=fs.readFileSync(path.join(dir,'database.json'),'utf8');assert.ok(!stored.includes('RoomNext2026!'));assert.ok(JSON.parse(stored).admin.roomPassword.digest);
  assert.equal((await call('/api/password',{oldPassword:'LocalDemo2026!',newPassword:'AdminNext2026!'})).status,200);assert.equal((await call('/api/room-access')).status,401);
  cookie=await login('AdminNext2026!');assert.equal((await call('/api/room-access')).value.unlocked,false);await unlock('RoomNext2026!');
  for(let i=0;i<10;i++)assert.equal((await call('/api/room-access/unlock',{password:'wrong'})).status,400);
  assert.equal((await call('/api/room-access/unlock',{password:'RoomNext2026!'})).status,429);
  assert.equal((await call('/api/room-access/password',{adminPassword:'AdminNext2026!',newPassword:'RoomFinal2026!'})).status,429);
 }finally{await stop();assert.equal(path.dirname(dir),path.resolve(os.tmpdir()));assert.ok(path.basename(dir).startsWith('room-access-test-'));fs.rmSync(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});}
});
