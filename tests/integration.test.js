'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
test('unified frontend and administration',async t=>{
 const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'unified-portal-test-'));
 const port=await new Promise(resolve=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const p=server.address().port;server.close(()=>resolve(p));});});
 const base=`http://127.0.0.1:${port}`;let child,cookie='',alice,bob,logs='';
 const salt=crypto.randomBytes(16).toString('hex');
 fs.writeFileSync(path.join(dir,'database.json'),JSON.stringify({version:2,admin:{username:'localadmin',password:{salt,digest:crypto.scryptSync('LocalDemo2026!',salt,32).toString('hex')},credentialRevision:2},members:[{id:'@v0001',name:'旧会员',balance:12345,approved:true}],orders:[{id:'O1',member:'@v0001',content:'旧文本订单',term:1,state:'待结算',amount:1000,payout:null,createdAt:'2026-09-29'}],requests:[]}));
 async function start(){logs='';child=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,PORT:String(port),LOCAL_CENTER_DATA:dir},stdio:['ignore','pipe','pipe'],windowsHide:true});child.stderr.on('data',s=>logs+=s);await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('启动超时 '+logs)),12000);child.stdout.once('data',()=>{clearTimeout(timer);resolve();});child.once('exit',c=>{clearTimeout(timer);reject(Error('启动失败 '+c+' '+logs));});});}
 async function stop(){if(child&&child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});}
 async function call(url,data,opts={}){const res=await fetch(base+url,{method:data===undefined?'GET':'POST',headers:{Cookie:opts.cookie??cookie,...(data===undefined?{}:{'Content-Type':'application/json',Origin:base}),...opts.headers},body:data===undefined?undefined:JSON.stringify(data)});return {status:res.status,data:await res.json(),cookie:res.headers.get('set-cookie')?.split(';')[0]};}
 async function ok(url,data,opts){const r=await call(url,data,opts);assert.equal(r.status,200,JSON.stringify(r.data));return r.data;}
 const admin=async(operation,data={},game='canada28',requestId=crypto.randomUUID())=>{const access=await ok('/api/room-access');if(!access.configured)await ok('/api/room-access/password',{adminPassword:'LocalDemo2026!',newPassword:'TestRooms2026!'});if(!access.unlocked)await ok('/api/room-access/unlock',{password:'TestRooms2026!'});return ok('/api/rooms/action',{operation,game,memberPassword:'admin123',data:{...data,requestId}});};
 const adminFail=(operation,data={},game='canada28')=>call('/api/rooms/action',{operation,game,memberPassword:'admin123',data:{...data,requestId:crypto.randomUUID()}});
 const state=game=>ok('/api/rooms?game='+(game||'canada28'));
 async function link(username){const r=await ok('/api/rooms/member-link?username='+username);const token=new URL(r.url).hash.slice('#access='.length);await ok('/api/portal/login',{},memberOpts(token));return token;}
 const memberOpts=token=>({cookie:'',headers:{'X-Member-Access':token,'X-Member-Device':'a'.repeat(64)}});
 const portal=(token,operation,data={},game='canada28',requestId=crypto.randomUUID())=>ok('/api/portal/'+operation,{...data,game,requestId},memberOpts(token));
 const memberState=(token,game='canada28')=>ok('/api/portal/state?game='+game,undefined,memberOpts(token));
 try{
  await start();
  await t.test('admin authentication, migration and closed public registration',async()=>{
   assert.equal((await call('/api/rooms')).status,401);
   assert.equal((await call('/api/register',{username:'intruder',password:'abc12345'})).status,403);
   assert.equal((await call('/api/portal/state')).status,401);
   cookie=(await call('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;assert.ok(cookie);
   const s=await state();assert.equal(s.users.filter(u=>u.role==='member').length,1);assert.equal(s.users.find(u=>u.username==='legacy_v0001').wallets.canada28,12345);
   assert.equal(s.legacyPending.length,1);assert.ok(fs.existsSync(path.join(dir,'backups','before-unified-portal','database.json')));
   await admin('legacy.settle',{id:'legacy-O1',payout:12.5});assert.equal((await state()).users.find(u=>u.username==='legacy_v0001').wallets.canada28,13595);
   assert.equal((await adminFail('legacy.refund',{id:'legacy-O1'})).status,400);
   for(const game of Object.keys(s.games))await admin('config',{mode:'manual',period:600,closeSeconds:10,paused:false},game);
   assert.equal((await call('/api/rooms/action',{operation:'notice',data:{}},{headers:{Origin:'http://evil.invalid'}})).status,403);
   assert.equal((await call('/api/action',{action:'member.create',name:'绕过'})).status,404);
   const createId=crypto.randomUUID();await admin('member.create',{username:'alice',nickname:'用户甲',amount:100},'canada28',createId);await admin('member.create',{username:'alice',nickname:'用户甲',amount:100},'canada28',createId);
   await admin('member.create',{username:'bob',nickname:'用户乙',amount:20});alice=await link('alice');bob=await link('bob');
   assert.equal((await memberState(alice)).score,10000);assert.equal((await memberState(bob)).score,2000);
   assert.equal((await call('/api/rooms',undefined,memberOpts(alice))).status,403);
   assert.equal((await call('/api/rooms',undefined,{headers:{'X-Member-Access':alice}})).status,403);
   assert.equal((await call('/api/portal/state',undefined,memberOpts(alice+'x'))).status,401);
   assert.equal((await call('/api/login',{username:'alice',password:'LocalDemo2026!'})).status,401);
  });
  await t.test('one active member device is enforced on every route and survives restart',async()=>{
   const device=value=>({cookie:'',headers:{'X-Member-Access':alice,'X-Member-Device':value.repeat(64)}}),A=device('a'),B=device('b'),C=device('c');
   assert.equal((await call('/api/portal/state',undefined,{cookie:'',headers:{'X-Member-Access':alice}})).status,401);
   await ok('/api/portal/login',{},B);
   for(const game of ['canada28','australia8','australia8ball'])assert.equal((await call('/api/portal/state?game='+game,undefined,B)).status,200);
   const before=await state();
   for(const operation of ['bet','chat','cancel','score-request','transfer','profile','logout']){
    const r=await call('/api/portal/'+operation,{game:'canada28',text:'1番1',message:'上分1',action:'上分',amount:1,requestId:crypto.randomUUID(),_identity:{username:'alice',deviceHash:'b'.repeat(64)}},A);assert.equal(r.status,403,operation);
   }
   for(let i=0;i<3;i++)assert.equal((await call('/api/portal/state',undefined,A)).status,403);
   assert.equal((await call('/api/portal/state',undefined,B)).status,200);
   const after=await state();assert.deepEqual(after.orders,before.orders);assert.deepEqual(after.requests,before.requests);assert.deepEqual(after.ledger,before.ledger);
   assert.ok(!JSON.stringify(after.users).includes('memberDevice'));
   assert.equal((await call('/api/portal/login',{}, {cookie:'',headers:{'X-Member-Access':alice+'x','X-Member-Device':'c'.repeat(64)}})).status,401);
   await stop();await start();cookie=(await call('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;
   assert.equal((await call('/api/portal/state',undefined,A)).status,403);assert.equal((await call('/api/portal/state',undefined,B)).status,200);
   await Promise.all([ok('/api/portal/login',{},B),ok('/api/portal/login',{},C)]);
   const statuses=await Promise.all([call('/api/portal/state',undefined,B),call('/api/portal/state',undefined,C)]);assert.deepEqual(statuses.map(r=>r.status).sort(),[200,403]);
   const winner=statuses[0].status===200?B:C;await ok('/api/portal/logout',{},winner);assert.equal((await call('/api/portal/state',undefined,winner)).status,403);
   await ok('/api/portal/login',{},A);assert.equal((await memberState(alice)).user.username,'alice');assert.equal((await memberState(bob)).user.username,'bob');
  });
  await t.test('configuration, profile, announcement and live wallet share one state',async()=>{
   await admin('config',{notice:'后台公告同步',minBet:2,maxBet:100,odds:{...(await state()).games.canada28.odds,'番':3}});
   let a=await memberState(alice);assert.equal(a.notice,'后台公告同步');assert.equal(a.odds['番'],3);assert.equal(a.limits.minBet,200);
   await portal(alice,'profile',{nickname:'前台修改昵称',avatar:'🐱',username:'bob'});
   assert.equal((await state()).users.find(u=>u.username==='alice').nickname,'前台修改昵称');assert.equal((await memberState(bob)).user.nickname,'用户乙');
   await admin('member.edit',{username:'alice',nickname:'后台修改昵称',remark:'仅管理员可见'});
   assert.equal((await memberState(alice)).user.nickname,'后台修改昵称');assert.ok(!JSON.stringify(await memberState(alice)).includes('仅管理员可见'));
   await admin('notice',{text:'统一公告消息'});assert.ok((await memberState(alice)).chat.some(x=>x.content==='统一公告消息'));
   const id=crypto.randomUUID();await Promise.all([admin('score',{username:'alice',action:'上分',amount:12.34},'canada28',id),admin('score',{username:'alice',action:'上分',amount:12.34},'canada28',id)]);
   assert.equal((await memberState(alice)).score,11234);
   const ledgerBefore=(await state()).ledger;
   assert.equal((await call('/api/portal/transfer',{target:'australia8',amount:10,game:'canada28',requestId:crypto.randomUUID()},memberOpts(alice))).status,400);
   a=await memberState(alice);assert.equal(a.score,11234);assert.equal(a.balance,11234);assert.deepEqual(Object.values(a.wallets),[11234,11234,11234]);
   assert.deepEqual((await state()).ledger,ledgerBefore,'shared funds must not produce transfer entries');
   assert.equal((await state()).users.find(u=>u.username==='alice').balance,11234);
   const old=(await state()).games.canada28;assert.equal((await adminFail('config',{minBet:30,maxBet:2})).status,400);assert.deepEqual((await state()).games.canada28,old);
   assert.equal((await adminFail('score',{username:'alice',action:'下分',amount:1000000})).status,400);
  });
  await t.test('member orders, isolation, duplicate protection, cancellation and settlement',async()=>{
   let before=(await memberState(alice)).score;
   const bad=await call('/api/portal/bet',{game:'canada28',text:'1番1',requestId:crypto.randomUUID()},memberOpts(alice));assert.equal(bad.status,400);
   const id=crypto.randomUUID();await Promise.all([portal(alice,'bet',{text:'1番10',username:'bob'},'canada28',id),portal(alice,'bet',{text:'1番10',username:'bob'},'canada28',id)]);
   const a=await memberState(alice),o=a.orders[0];assert.equal(a.orders.length,1);assert.equal(o.username,'alice');assert.equal(a.score,before-1000);assert.equal((await memberState(bob)).orders.length,0);
   assert.equal((await state()).orders.find(x=>x.id===o.id).amount,1000);
   assert.equal((await call('/api/portal/cancel',{game:'canada28',id:o.id,requestId:crypto.randomUUID()},memberOpts(bob))).status,400);
   assert.equal((await call('/api/portal/bet',{game:'canada28',text:'2番10',username:'bob',requestId:id},memberOpts(alice))).status,400);
   await portal(alice,'cancel',{id:o.id});assert.equal((await memberState(alice)).score,before);
   assert.equal((await call('/api/portal/cancel',{game:'canada28',id:o.id,requestId:crypto.randomUUID()},memberOpts(alice))).status,400);
   await portal(alice,'chat',{message:'1番10'});
   await portal(alice,'chat',{message:'查'});
   const detailsReply=(await memberState(alice)).chat.at(-1).content;
   assert.match(detailsReply,/当局下注明细/);assert.match(detailsReply,/1番：10/);assert.match(detailsReply,/合计：10（1笔）/);
   await admin('config',{odds:{...(await state()).games.canada28.odds,'番':4}});
   let s=await state(),drawId=crypto.randomUUID();await admin('close');
   assert.equal((await memberState(alice)).accepting,false);
   assert.equal((await call('/api/portal/bet',{game:'canada28',text:'1番10',requestId:crypto.randomUUID()},memberOpts(alice))).status,400);
   await admin('draw',{numbers:'0,0,1',issue:s.round.issue},'canada28',drawId);await admin('draw',{numbers:'0,0,1',issue:s.round.issue},'canada28',drawId);
   assert.equal((await memberState(alice)).score,before+3000); // Odds locked at order time: 3, not the new 4.
   assert.equal((await memberState(alice)).orders[0].status,'中奖');assert.equal((await state()).history.length,1);
   assert.equal((await adminFail('draw',{numbers:'0,0,1',issue:s.round.issue})).status,400);
   const second=await memberState(alice);assert.equal(second.history[0].issue,s.round.issue);
  });
  await t.test('invalid chat is private and only accepted bets are broadcast',async()=>{
   for(const game of ['canada28','australia8','australia8ball']){
    const before=await memberState(alice,game);
    for(const message of ['3在100','普通聊天','1番1.50','1番10,错误信息']){
     const failed=await call('/api/portal/chat',{game,message,ball:8,requestId:crypto.randomUUID()},memberOpts(alice));
     assert.equal(failed.status,400);
    }
    await portal(alice,'chat',{message:'帮助'},game);
    const after=await memberState(alice,game);
    assert.equal(after.balance,before.balance);assert.deepEqual(after.orders,before.orders);assert.deepEqual(after.chat,before.chat);
    for(const message of ['查','查流水']){
     await portal(alice,'chat',{message},game);
     const queried=await memberState(alice,game);
     assert.equal(queried.chat.at(-2).content,message);
     assert.match(queried.chat.at(-1).content,/有效流水/);
     assert.equal(queried.balance,before.balance);assert.deepEqual(queried.orders,before.orders);
    }
   }
  });
  await t.test('score application review and room orders share one balance',async()=>{
   const before=(await memberState(bob)).score;await portal(bob,'score-request',{action:'上分',amount:5.67});let r=(await memberState(bob)).requests[0];assert.equal((await state()).requests.find(x=>x.id===r.id).username,'bob');
   await admin('review',{id:r.id,approve:true});assert.equal((await memberState(bob)).score,before+567);assert.equal((await memberState(bob)).requests[0].status,'已通过');
   for(const game of ['canada28','australia8','australia8ball'])assert.equal((await memberState(bob,game)).balance,before+567);
   assert.equal((await adminFail('review',{id:r.id,approve:true})).status,400);
   await portal(bob,'score-request',{action:'下分',amount:1});r=(await memberState(bob)).requests[0];await admin('review',{id:r.id,approve:false});assert.equal((await memberState(bob)).score,before+567);
   await admin('score',{username:'alice',action:'上分',amount:20},'australia8ball');
   await portal(alice,'bet',{text:'1番2',ball:1},'australia8ball');
   const s=await state('australia8ball');await admin('draw',{numbers:'0,0,1',issue:s.round.issue},'australia8ball');
   assert.equal((await memberState(alice,'australia8ball')).orders[0].status,'中奖');
   const shared=(await memberState(alice,'australia8ball')).score;
   for(const game of ['canada28','australia8','australia8ball'])assert.equal((await memberState(alice,game)).score,shared);
   assert.equal((await memberState(bob,'australia8ball')).orders.length,0);
   await admin('config',{paused:true});assert.equal((await memberState(alice)).accepting,false);await admin('config',{paused:false});
  });
  await t.test('chat score commands reach administration and require exactly one review',async()=>{
   const username='scorecommands',games=['canada28','australia8','australia8ball'];
   await admin('member.create',{username,nickname:'聊天申请测试',amount:1000});
   await admin('member.edit',{username,robot:false});
   const token=await link(username);let balance=100000;
   const commands=[
    ['上500','上分',50000],['下50','下分',5000],
    ['上分12.34','上分',1234],['下分2.34','下分',234],
    ['上 0.01','上分',1],['下 0.01','下分',1],
    ['上分 1.20','上分',120],['下分 1.20','下分',120]
   ];
   for(const [index,[message,action,amount]] of commands.entries()){
    const game=games[index%games.length],requestId=crypto.randomUUID();
    const before=(await memberState(token,game)).requests;
    // A retried HTTP chat submission must create only one pending application.
    await Promise.all([portal(token,'chat',{message},game,requestId),portal(token,'chat',{message},game,requestId)]);
    const p=await memberState(token,game),pending=p.requests.filter(r=>!before.some(old=>old.id===r.id));
    assert.equal(pending.length,1,message);assert.equal(p.score,balance,'application cannot credit or debit funds');
    const req=pending[0];assert.equal(req.username,username);assert.equal(req.game,game);assert.equal(req.action,action);assert.equal(req.amount,amount);assert.equal(req.status,'待审核');
    const formatted=n=>(n/100).toFixed(2).replace(/\.00$/,'');
    assert.equal(p.chat.findLast(m=>m.kind==='SCORE_REQUEST').content,`@聊天申请测试${action}${formatted(amount)}，待管理员审核请稍后`);
    const adminRequest=(await state(game)).requests.find(r=>r.id===req.id);assert.deepEqual(adminRequest,req,'front and back office must see the same request');
    if(index===0){
     await admin('score',{username,action:'上分',amount:2.34},games[1]);balance+=234;
    }
    const reviewId=crypto.randomUUID();await admin('review',{id:req.id,approve:true},game,reviewId);
    await admin('review',{id:req.id,approve:true},game,reviewId);
    assert.equal((await adminFail('review',{id:req.id,approve:true},game)).status,400,'a new review cannot apply an already completed request again');
    balance+=action==='上分'?amount:-amount;
    const approved=(await memberState(token,game)).chat.filter(m=>m.kind==='SCORE_REVIEW'&&m.details?.requestId===req.id);
    assert.equal(approved.length,1);
    assert.equal(approved[0].content,`@聊天申请测试 ${action[0]}${formatted(amount)}成功，剩余共享积分${formatted(balance)}`);
    assert.equal(approved[0].details.balance,balance);
    for(const room of games){const current=await memberState(token,room);assert.equal(current.score,balance);assert.equal(current.balance,balance);assert.deepEqual(Object.values(current.wallets),[balance,balance,balance]);}
    assert.equal((await memberState(token,game)).requests.find(r=>r.id===req.id).status,'已通过');
    const ledger=(await state()).ledger.filter(row=>row.username===username);assert.equal(ledger.reduce((sum,row)=>sum+row.delta,0),balance);
    assert.equal(ledger.filter(row=>row.ref===req.id).length,1,'one approved request creates one wallet entry');
   }
   const beforeInvalid=await memberState(token);
   for(const message of ['上0','下-1','上1.234','上500元']){
    const failed=await call('/api/portal/chat',{game:'canada28',message,requestId:crypto.randomUUID()},memberOpts(token));
    assert.equal(failed.status,400,message);
   }
   let current=await memberState(token);assert.deepEqual(current.requests,beforeInvalid.requests);assert.equal(current.score,balance);
   assert.equal((await call('/api/portal/chat',{game:'canada28',message:'下午3点',requestId:crypto.randomUUID()},memberOpts(token))).status,400);current=await memberState(token);
   assert.deepEqual(current.chat,beforeInvalid.chat,'ordinary text beginning with 下 must not be broadcast');assert.deepEqual(current.requests,beforeInvalid.requests);
   const oldBot=(await state('australia8')).games.australia8.bot;
   try{
    await admin('config',{bot:false},'australia8');
    const before=await memberState(token,'australia8');
    await portal(token,'chat',{message:'上3.21'},'australia8');
    current=await memberState(token,'australia8');const req=current.requests.find(r=>!before.requests.some(old=>old.id===r.id));
    assert.ok(req,'disabling robot replies must not disable score requests');assert.equal(req.amount,321);assert.equal(req.status,'待审核');assert.equal(current.score,balance);
    assert.equal((await state()).requests.find(r=>r.id===req.id).username,username);
    await admin('review',{id:req.id,approve:false},'australia8');assert.equal((await memberState(token)).score,balance);
   }finally{await admin('config',{bot:oldBot},'australia8');}
  });
  await t.test('decimal stakes are rejected through member chat, quick bets and admin orders',async()=>{
   await admin('member.create',{username:'integerbets',nickname:'整数下注',amount:100});
   const token=await link('integerbets');
   for(const game of ['canada28','australia8ball','australia8']){
    for(const text of ['单/59.60','2番/72.67','4番/20.00','1番1,2番2.50']){
     for(const operation of ['chat','bet']){
      const r=await call('/api/portal/'+operation,{game,text,message:text,ball:8,requestId:crypto.randomUUID()},memberOpts(token));
      assert.equal(r.status,400,JSON.stringify(r.data));
     }
     assert.equal((await adminFail('workbench.order',{username:'integerbets',text,ball:8},game)).status,400);
    }
    const p=await memberState(token,game);assert.equal(p.balance,10000);assert.equal(p.orders.length,0);
    await portal(token,'bet',{text:'单/10',ball:8},game);
    await admin('refund',{},game);
   }
  });
  await t.test('concurrent room bets cannot overspend and refunds share the same balance',async()=>{
   await admin('member.create',{username:'sharedrace',nickname:'并发测试',amount:10});
   const token=await link('sharedrace'),games=['canada28','australia8','australia8ball'];
   const attempts=await Promise.all(games.map(game=>call('/api/portal/bet',{game,text:'1番7',ball:1,requestId:crypto.randomUUID()},memberOpts(token))));
   assert.deepEqual(attempts.map(r=>r.status).sort(),[200,400,400]);
   let s=await state(),orders=s.orders.filter(o=>o.username==='sharedrace');assert.equal(orders.length,1);
   assert.equal(s.users.find(u=>u.username==='sharedrace').balance,300);
   for(const game of games){const p=await memberState(token,game);assert.equal(p.score,300);assert.deepEqual(Object.values(p.wallets),[300,300,300]);}
   await admin('refund',{},orders[0].game);
   for(const game of games)assert.equal((await memberState(token,game)).score,1000);
   await portal(token,'score-request',{action:'上分',amount:1.23},'australia8ball');
   const req=(await memberState(token,'australia8ball')).requests[0];await admin('review',{id:req.id,approve:true});
   for(const game of games)assert.equal((await memberState(token,game)).score,1123);
   s=await state();assert.equal(s.users.find(u=>u.username==='sharedrace').balance,1123);
   assert.equal(s.ledger.filter(l=>l.username==='sharedrace').reduce((sum,l)=>sum+l.delta,0),1123);
  });
  await t.test('link revocation, export privacy and ledger reconciliation',async()=>{
   await admin('member.rotate',{username:'alice'});assert.equal((await call('/api/portal/state',undefined,memberOpts(alice))).status,403);alice=await link('alice');assert.equal((await memberState(alice)).user.username,'alice');
   await admin('member.edit',{username:'bob',enabled:false});assert.equal((await call('/api/portal/state',undefined,memberOpts(bob))).status,403);assert.equal((await call('/api/rooms/member-link?username=bob')).status,400);
   await admin('member.edit',{username:'bob',enabled:true});assert.equal((await call('/api/portal/state',undefined,memberOpts(bob))).status,403);bob=await link('bob');
   await admin('config',{feed:{url:'https://example.invalid/draw',headers:{Authorization:'SECRET_TEST'}}});
   const exported=await ok('/api/rooms/export'),serialized=JSON.stringify(exported);assert.ok(!serialized.includes('SECRET_TEST'));assert.ok(!serialized.includes('accessVersion'));assert.ok(!serialized.includes('linkSigningKey'));assert.equal(exported.games.canada28.feed.url,'');
   for(const u of exported.users){assert.equal(exported.ledger.filter(l=>l.username===u.username).reduce((sum,l)=>sum+l.delta,0),u.balance,u.username);assert.deepEqual(Object.values(u.wallets),[u.balance,u.balance,u.balance]);}
   const old=JSON.stringify(await ok('/api/legacy/export'));assert.ok(!old.includes('digest'));assert.ok(!old.includes('linkSigningKey'));
  });
  await t.test('reference workbench shares members, orders, score requests and QR links',async()=>{
   const before=(await memberState(alice)).score;
   await admin('member.edit',{username:'alice',robot:true,auto:true,rebate:2});
   let s=await state();assert.equal(s.users.find(u=>u.username==='alice').robot,true);
   assert.equal((await adminFail('member.edit',{username:'alice',rebate:101})).status,400);
   await admin('workbench.save',{reportConnected:true,autoReport:true,failCancel:true});
   const rid=crypto.randomUUID();await admin('workbench.order',{username:'alice',text:'1番10'},'canada28',rid);await admin('workbench.order',{username:'alice',text:'1番10'},'canada28',rid);
   let a=await memberState(alice),o=a.orders[0];assert.equal(a.score,before-1000);assert.equal(o.report,'模拟成功');
   await admin('workbench.report',{id:o.id,fail:true});a=await memberState(alice);assert.equal(a.score,before);assert.equal(a.orders[0].status,'已退单');
   assert.equal((await adminFail('workbench.report',{id:o.id,fail:true})).status,400);
   await admin('workbench.order',{username:'alice',text:'1番10'});o=(await memberState(alice)).orders[0];await admin('workbench.cancel',{id:o.id});assert.equal((await memberState(alice)).score,before);
   await admin('workbench.request',{username:'alice',action:'下分',amount:8});const req=(await memberState(alice)).requests[0];await admin('review',{id:req.id,approve:false});assert.equal((await memberState(alice)).requests[0].status,'已拒绝');
   const led=(await state()).ledger;await admin('workbench.stats.reset');s=await state();assert.deepEqual(s.ledger,led);assert.equal(s.memberStats.alice.turnover,0);assert.equal((await memberState(alice)).score,before);
   const qr=await ok('/api/rooms/member-link?username=alice');assert.match(qr.svg,/^<svg/);assert.match(qr.svg,/shape-rendering="crispEdges"/);assert.equal(new URL(qr.url).hash.slice('#access='.length),alice);
  });
  await t.test('australia8 combo odds enable selected-ball number settlement',async()=>{
   const game='australia8',config=(await state(game)).games[game];
   await admin('refund',{},game);
   await admin('config',{mode:'manual',period:600},game);
   await admin('member.create',{username:'a8number',nickname:'球号规则验证',amount:100});
   const token=await link('a8number');
   assert.equal((await memberState(token,game)).odds['大双'],null);
   const rejected=await call('/api/portal/bet',{game,text:'大双10',ball:3,requestId:crypto.randomUUID()},memberOpts(token));
   assert.equal(rejected.status,400);assert.equal((await memberState(token,game)).score,10000);
   const odds={...config.odds,'小单':2,'小双':2,'大单':2,'大双':2};
   await admin('config',{odds},game);
   assert.equal((await memberState(token,game)).odds['大双'],2);
   for(const [text,ball] of [['小双10',1],['大单10',2],['大双10',3],['大单10',4]])await portal(token,'bet',{text,ball},game);
   await admin('draw',{numbers:'10,11,14,15,1,2,19,20',issue:(await state(game)).round.issue},game);
   const result=await memberState(token,game);
   assert.equal(result.orders.length,4);
   assert.ok(result.orders.every(o=>o.status==='中奖'&&o.settlementRule==='a8-number-v1'));
   assert.equal(result.score,18000);
   assert.equal(result.history[0].settlementRule,'a8-number-v1');
   await admin('config',{odds:config.odds},game);
  });
  await t.test('bundled avatars create, edit, persist and render without accepting external URLs',async()=>{
   for(const route of ['/avatar-library.js','/avatar-library.css','/avatars/nature-01.svg','/avatars/toy-01.svg']){
    const r=await fetch(base+route);assert.equal(r.status,200);if(route.endsWith('.svg')){assert.match(r.headers.get('content-type'),/image\/svg\+xml/);assert.match(await r.text(),/<svg/);}
   }
   await admin('member.create',{username:'avataruser',nickname:'图片头像',amount:100,avatar:'/avatars/nature-04.svg'});
   const token=await link('avataruser');assert.equal((await memberState(token)).user.avatar,'/avatars/nature-04.svg');
   await admin('member.edit',{username:'avataruser',avatar:'/avatars/toy-03.svg'});
   for(const game of ['canada28','australia8','australia8ball'])assert.equal((await memberState(token,game)).user.avatar,'/avatars/toy-03.svg');
   await portal(token,'chat',{message:'查'});
   await portal(token,'profile',{nickname:'图片头像',avatar:'/avatars/toy-07.svg'});
   const updated=await memberState(token);assert.equal(updated.user.avatar,'/avatars/toy-07.svg');assert.equal(updated.chat.findLast(m=>m.username==='avataruser').avatar,'/avatars/toy-07.svg');
   for(const avatar of ['https://example.com/x.svg','/avatars/../data/database.json','/avatars/missing.svg','<img onerror=alert(1)>']){
    assert.equal((await adminFail('member.edit',{username:'avataruser',avatar})).status,400);
    assert.equal((await call('/api/portal/profile',{nickname:'图片头像',avatar,game:'canada28',requestId:crypto.randomUUID()},memberOpts(token))).status,400);
   }
   assert.equal((await memberState(token)).user.avatar,'/avatars/toy-07.svg');
   await stop();await start();cookie=(await call('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;
   assert.equal((await memberState(token)).user.avatar,'/avatars/toy-07.svg');
  });
  await t.test('robot templates are admin-only, room-scoped, versioned and applied to new replies',async()=>{
   const game='canada28',initial=(await state(game)).robotConfig;
   const payload={revision:initial.revision,bot:true,name:'测试助手',entries:Object.fromEntries(initial.entries.map(r=>[r.key,{text:r.text,enabled:r.enabled}]))};
   payload.entries.down_success.text='@{昵称} 已下{金额}，余额{余额}';
   const denied=await call('/api/rooms/action',{operation:'robot.messages.save',game,data:{...payload,requestId:crypto.randomUUID()}},memberOpts(alice));assert.ok([401,403].includes(denied.status));
   const id=crypto.randomUUID();await admin('robot.messages.save',payload,game,id);await admin('robot.messages.save',payload,game,id);
   assert.equal((await state(game)).robotConfig.revision,initial.revision+1);
   assert.equal((await adminFail('robot.messages.save',payload,game)).status,400);
   await admin('member.create',{username:'robotreply',nickname:'机器人配置测试',amount:100});
   await admin('score',{username:'robotreply',action:'下分',amount:10},game);
   const msg=(await state(game)).chat.findLast(m=>m.kind==='SCORE_ADJUSTMENT');
   assert.equal(msg.who,'测试助手');assert.equal(msg.content,'@机器人配置测试 已下10，余额90');assert.equal(msg.details.robotTemplate,'down_success');
   assert.equal((await state('australia8')).robotConfig.revision,0);
   const current=(await state(game)).robotConfig;
   await admin('robot.messages.save',{revision:current.revision,bot:initial.bot,name:initial.name,entries:Object.fromEntries(initial.entries.map(r=>[r.key,{text:r.text,enabled:r.enabled}]))},game);
   assert.equal((await state(game)).chat.find(m=>m.id===msg.id).content,msg.content);
  });
  await t.test('only server-marked simulated users receive automatic top-up approval exactly once',async()=>{
   await admin('member.create',{username:'autofund',nickname:'上分测试',amount:0});
   await admin('member.edit',{username:'autofund',robot:true});
   const token=await link('autofund'),id=crypto.randomUUID();
   await portal(token,'chat',{message:'上分1000'},'canada28',id);
   await portal(token,'chat',{message:'上分1000'},'canada28',id);
   let s=await state(),requests=s.requests.filter(r=>r.username==='autofund');
   assert.equal(requests.length,1);assert.equal(requests[0].status,'已通过');assert.equal(requests[0].autoApproved,true);
   assert.equal((await memberState(token)).balance,100000);
   assert.equal(s.ledger.filter(l=>l.username==='autofund'&&l.source==='simulated-auto-topup').length,1);
   assert.equal(s.chat.filter(m=>m.kind==='SCORE_REVIEW'&&m.details?.username==='autofund').length,1);
   assert.ok(s.chat.some(m=>m.username==='autofund'&&m.content==='上分1000'));
   assert.equal((await adminFail('review',{id:requests[0].id,approve:true})).status,400);
   await portal(token,'score-request',{action:'下分',amount:100});
   s=await state();assert.equal(s.requests.find(r=>r.username==='autofund'&&r.action==='下分').status,'待审核');
   await admin('member.edit',{username:'autofund',robot:false});
   await portal(token,'score-request',{action:'上分',amount:5000,robot:true,autoApproved:true});
   s=await state();assert.equal(s.requests.find(r=>r.username==='autofund'&&r.amount===500000).status,'待审核');
   assert.equal((await memberState(token)).balance,100000);
  });
  await t.test('default rebate, per-operation password and deletion preserve accounting and revoke access',async()=>{
   await admin('member.create',{username:'deletetest',nickname:'删除测试',amount:100});
   assert.equal((await state()).users.find(u=>u.username==='deletetest').rebate,0.8);
   await admin('member.create',{username:'zerorebate',nickname:'零返水',rebate:0});
   assert.equal((await state()).users.find(u=>u.username==='zerorebate').rebate,0);
   assert.equal((await adminFail('member.create',{username:'badrebate',nickname:'超出',rebate:101})).status,400);
   const token=await link('deletetest');await portal(token,'bet',{text:'1番10'});
   const direct=(operation,data,memberPassword)=>call('/api/rooms/action',{operation,game:'canada28',data:{...data,requestId:crypto.randomUUID()},...(memberPassword===undefined?{}:{memberPassword})});
   for(const [operation,data] of [['member.edit',{username:'deletetest',robot:true}],['member.edit',{username:'deletetest',enabled:false}],['member.delete',{username:'deletetest'}],['member.autobet.batch',{username:'deletetest',activateMember:true,enabled:true,rooms:['canada28']}]]){
    assert.equal((await direct(operation,data)).status,428);assert.equal((await direct(operation,data,'wrong')).status,403);
   }
   assert.equal((await direct('member.edit',{username:'deletetest',enabled:false},'admin123')).status,200);
   assert.equal((await direct('member.edit',{username:'deletetest',enabled:true})).status,428,'previous success must not unlock later actions');
   await admin('member.edit',{username:'deletetest',enabled:true});const freshToken=await link('deletetest');
   const before=await state(),id=crypto.randomUUID();await admin('member.delete',{username:'deletetest'},'canada28',id);await admin('member.delete',{username:'deletetest'},'canada28',id);
   const after=await state(),user=after.users.find(u=>u.username==='deletetest');assert.equal(user.deleted,true);assert.equal(user.enabled,false);assert.equal(user.balance,9000);assert.deepEqual(after.orders,before.orders);assert.deepEqual(after.ledger,before.ledger);
   assert.equal((await call('/api/portal/state',undefined,memberOpts(freshToken))).status,403);
   assert.equal((await adminFail('member.edit',{username:'deletetest',enabled:true})).status,400);
   assert.equal((await adminFail('member.autobet.batch',{username:'deletetest',activateMember:true,enabled:true,rooms:['canada28']})).status,400);
   assert.equal((await adminFail('member.create',{username:'deletetest',nickname:'重用'})).status,400);
   assert.equal((await call('/api/member-access/password',{adminPassword:'wrong',newPassword:'NewMember2026!'})).status,403);
   await ok('/api/member-access/password',{adminPassword:'LocalDemo2026!',newPassword:'NewMember2026!'});
   assert.equal((await direct('member.edit',{username:'zerorebate',enabled:false},'admin123')).status,403);
   assert.equal((await direct('member.edit',{username:'zerorebate',enabled:false},'NewMember2026!')).status,200);
   assert.ok(!fs.readFileSync(path.join(dir,'database.json'),'utf8').includes('NewMember2026!'));
   assert.ok(!fs.readFileSync(path.join(dir,'rooms','state.json'),'utf8').includes('NewMember2026!'));
   await ok('/api/member-access/password',{adminPassword:'LocalDemo2026!',newPassword:'admin123'});
  });
  await t.test('restart preserves identity, balances and migration idempotence',async()=>{
   const before=await state();await stop();await start();assert.equal((await call('/api/rooms')).status,401);
   assert.equal((await memberState(alice)).user.username,'alice');assert.equal((await memberState(bob)).user.username,'bob');
   cookie=(await call('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).cookie;
   const after=await state();assert.deepEqual(after.users,before.users);assert.deepEqual(after.orders,before.orders);assert.deepEqual(after.migration,before.migration);
   await ok('/api/password',{oldPassword:'LocalDemo2026!',newPassword:'ChangedLocal2026!'});assert.equal((await call('/api/rooms')).status,401);assert.equal((await call('/api/login',{username:'localadmin',password:'LocalDemo2026!'})).status,401);
   assert.equal((await call('/api/login',{username:'localadmin',password:'ChangedLocal2026!'})).status,200);assert.equal((await memberState(alice)).user.username,'alice');
  });
 }finally{await stop();assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));assert.ok(path.basename(dir).startsWith('unified-portal-test-'));fs.rmSync(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});}
});

test('fresh install creates no public member and rejects a second writer',async()=>{
 const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'unified-empty-test-'));let child,second;
 async function launch(){const c=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,PORT:'0',LOCAL_CENTER_DATA:dir},stdio:['ignore','pipe','pipe'],windowsHide:true});return c;}
 try{
  // Use a free real port so the HTTP origin check can be exercised.
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  child=spawn(process.execPath,[path.join(root,'server.js')],{env:{...process.env,PORT:String(port),LOCAL_CENTER_DATA:dir},stdio:['ignore','pipe','pipe'],windowsHide:true});
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('startup timeout')),12000);child.stdout.once('data',()=>{clearTimeout(timer);resolve();});child.once('exit',c=>{clearTimeout(timer);reject(Error('startup '+c));});});
  const base=`http://127.0.0.1:${port}`;let response=await fetch(base+'/api/login',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},body:JSON.stringify({username:'localadmin',password:'LocalDemo2026!'})});const cookie=response.headers.get('set-cookie').split(';')[0];
  response=await fetch(base+'/api/rooms',{headers:{Cookie:cookie}});const s=await response.json();assert.equal(response.status,200,JSON.stringify(s));assert.equal(s.users.filter(u=>u.role==='member').length,0);
  let stderr='';second=await launch();second.stderr.on('data',s=>stderr+=s);const code=await new Promise(r=>second.once('exit',r));assert.notEqual(code,0);assert.match(stderr,/已有软件实例/);
  response=await fetch(base+'/api/rooms',{headers:{Cookie:cookie}});assert.equal(response.status,200);
 }finally{for(const c of [child,second])if(c&&c.exitCode===null)await new Promise(r=>{c.once('exit',r);c.kill();});assert.equal(path.dirname(dir),path.resolve(os.tmpdir()));assert.ok(path.basename(dir).startsWith('unified-empty-test-'));fs.rmSync(dir,{recursive:true,force:true,maxRetries:5,retryDelay:100});}
});
