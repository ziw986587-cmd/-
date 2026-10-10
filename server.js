'use strict';
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {RoomBridge}=require('./room-engine/bridge');
const PORT=Number(process.env.PORT||8777),ROOT=__dirname,DIR=path.resolve(process.env.LOCAL_CENTER_DATA||path.join(ROOT,'data')),FILE=path.join(DIR,'database.json');
const PUBLIC_ORIGIN=String(process.env.PUBLIC_ORIGIN||'').trim().replace(/\/$/,'');
let publicOrigin;
if(PUBLIC_ORIGIN){
  try{
    const parsed=new URL(PUBLIC_ORIGIN);
    if(!['http:','https:'].includes(parsed.protocol)||parsed.username||parsed.password||parsed.pathname!=='/'||parsed.search||parsed.hash)throw Error();
    publicOrigin=parsed.origin;
  }catch{throw Error('PUBLIC_ORIGIN 必须是形如 http://example.test 或 https://example.test 的地址');}
}
fs.mkdirSync(DIR,{recursive:true});
require('./data-lock')(DIR);
function hash(p,salt=crypto.randomBytes(16).toString('hex')){return {salt,digest:crypto.scryptSync(p,salt,32).toString('hex')};}
function verify(p,h){return typeof p==='string'&&p.length<=128&&crypto.timingSafeEqual(Buffer.from(hash(p,h.salt).digest,'hex'),Buffer.from(h.digest,'hex'));}
let db=fs.existsSync(FILE)?JSON.parse(fs.readFileSync(FILE,'utf8')):{version:2,admin:{username:'localadmin',password:hash('LocalDemo2026!'),credentialRevision:2}};
if(!db.linkSigningKey)db.linkSigningKey=crypto.randomBytes(32).toString('hex');
if(!db.admin.memberPassword)db.admin.memberPassword=hash('admin123');
function save(){fs.writeFileSync(FILE+'.tmp',JSON.stringify(db,null,2));fs.renameSync(FILE+'.tmp',FILE);}
save();
const rooms=new RoomBridge(DIR),sessions=new Map(),attempts=new Map();
const roomAttempts=new Map();
const memberAttempts=new Map();
function checkMemberPassword(req,password,expected=db.admin.memberPassword){
 const key=req.socket.remoteAddress,a=memberAttempts.get(key);
 if(a&&a.n>=10&&a.until>Date.now())fail('尝试过多，请一分钟后重试',429);
 if(!verify(password,expected)){memberAttempts.set(key,{n:a?.until>Date.now()?a.n+1:1,until:a?.until>Date.now()?a.until:Date.now()+60000});fail('用户操作密码错误',403);}
 memberAttempts.delete(key);
}
function roomAccess(s){return {configured:!!db.admin.roomPassword,unlocked:!!s?.roomUnlocked};}
function requireRoomAccess(s){if(!db.admin.roomPassword)fail('请先在“修改密码”中设置四个入口共用的房间访问密码',423);if(!sessions.get(s.token)?.roomUnlocked)fail('请先验证房间访问密码',423);}
function checkRoomAttempt(req){const key=req.socket.remoteAddress,a=roomAttempts.get(key);if(a&&a.n>=10&&a.until>Date.now())fail('尝试过多，请一分钟后重试',429);return key;}
function wrongRoomPassword(key){const a=roomAttempts.get(key);roomAttempts.set(key,{n:a?.until>Date.now()?a.n+1:1,until:a?.until>Date.now()?a.until:Date.now()+60000});fail('密码错误');}
process.on('exit',()=>rooms.close());
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{rooms.close();process.exit(0);});
function fail(message,status=400){throw Object.assign(Error(message),{status});}
function send(res,status,value,headers={}){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',...headers});res.end(JSON.stringify(value));}
function session(req){const token=(req.headers.cookie||'').split(';').map(s=>s.trim()).find(s=>s.startsWith('local_center='))?.slice(13),s=sessions.get(token);if(s&&s.until>Date.now())return {...s,token};if(token)sessions.delete(token);return null;}
async function body(req){let raw='';for await(const c of req){raw+=c;if(Buffer.byteLength(raw)>65536)fail('请求过大',413);}let p;try{p=JSON.parse(raw||'{}');}catch{fail('JSON 格式错误');}if(!p||Array.isArray(p)||typeof p!=='object')fail('请求须为对象');return p;}
function sign(value){return crypto.createHmac('sha256',Buffer.from(db.linkSigningKey,'hex')).update(value).digest('base64url');}
function memberToken(username,version){let data=Buffer.from(JSON.stringify({u:username,v:version})).toString('base64url');return data+'.'+sign(data);}
function requestOrigin(req){
 const proto=String(req.headers['x-forwarded-proto']||'http').split(',')[0].trim().toLowerCase();
 const host=String(req.headers['x-forwarded-host']||req.headers.host||'').split(',')[0].trim();
 return host?`${proto}://${host}`:'';
}
function checkRequestHost(req){
 if(publicOrigin)return requestOrigin(req)===publicOrigin;
 return ['127.0.0.1','localhost'].includes((req.headers.host||'').split(':')[0]);
}
function identity(req){const token=req.headers['x-member-access'];if(typeof token!=='string'||token.length>1024)fail('请使用管理员提供的专属链接进入',401);const parts=token.split('.');if(parts.length!==2||!/^[A-Za-z0-9_-]+$/.test(parts[0]))fail('专属链接无效',401);const signature=sign(parts[0]);if(signature.length!==parts[1].length||!crypto.timingSafeEqual(Buffer.from(signature),Buffer.from(parts[1])))fail('专属链接无效',401);try{const p=JSON.parse(Buffer.from(parts[0],'base64url').toString());if(typeof p.u!=='string'||typeof p.v!=='string')throw Error();return {username:p.u,version:p.v};}catch{fail('专属链接无效',401);}}
function memberDevice(req){const value=req.headers['x-member-device'];if(typeof value!=='string'||!/^[a-f0-9]{64}$/.test(value))fail('前台已更新，请刷新网页后重新进入',401);return crypto.createHash('sha256').update(value).digest('hex');}
const routes={'/portal-gold.jpg':'portal-gold.jpg','/':'index.html','/index.html':'index.html','/admin':'index.html','/user-center':'index.html','/userlogin':'index.html','/portal':'portal.html','/home':'portal.html','/player':'portal.html','/register':'portal.html','/auth':'portal.html','/workbench.js':'workbench.js','/workbench.css':'workbench.css','/app.js':'app.js','/styles.css':'styles.css','/room-admin.js':'room-admin.js','/room-admin.css':'room-admin.css','/portal.js':'portal.js','/portal.css':'portal.css'};
for(const row of JSON.parse(fs.readFileSync(path.join(ROOT,'avatars/catalog.json'),'utf8')))routes['/avatars/'+row.id+'.svg']='avatars/'+row.id+'.svg';
for(const name of ['avatar-library.js','avatar-library.css'])routes['/'+name]=name;
const mime={'.svg':'image/svg+xml','.jpg':'image/jpeg','.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'};
const server=http.createServer(async(req,res)=>{try{
 if(!checkRequestHost(req))fail(publicOrigin?'请求地址与 PUBLIC_ORIGIN 不匹配':'只接受本地访问',403);
 const url=new URL(req.url,`http://127.0.0.1:${PORT}`);
 res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');
 res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
 if(req.method==='GET'&&Object.hasOwn(routes,url.pathname)){const f=path.join(ROOT,routes[url.pathname]);res.writeHead(200,{'Content-Type':mime[path.extname(f)],'Cache-Control':'no-store'});return res.end(fs.readFileSync(f));}
 if(req.method==='POST'){if(req.headers.origin!==requestOrigin(req))fail('来源校验失败',403);if(!String(req.headers['content-type']).startsWith('application/json'))fail('需要 JSON 请求',415);}
 if(url.pathname==='/api/register')fail('前台不开放注册，请由管理员在后台创建用户',403);
 if(url.pathname.startsWith('/api/portal/')){
  const member={...identity(req),deviceHash:memberDevice(req)},game=url.searchParams.get('game')||'canada28';
  if(req.method==='GET'&&url.pathname==='/api/portal/state')return send(res,200,{ok:true,...await rooms.call('portal.state',game,{_identity:member})});
  const operation=url.pathname.slice('/api/portal/'.length);
  if(req.method!=='POST'||!['login','logout','bet','chat','cancel','score-request','transfer','profile'].includes(operation))fail('接口不存在',404);
  const p=await body(req);return send(res,200,{ok:true,...await rooms.call('portal.'+operation,p.game||'canada28',{...p,_identity:member})});
 }
 const s=session(req);
 if(req.method==='GET'&&url.pathname==='/api/session')return send(res,200,{ok:true,role:s?'admin':null,username:s?db.admin.username:null});
 if(req.method==='POST'&&url.pathname==='/api/login'){
  const p=await body(req),key=req.socket.remoteAddress,a=attempts.get(key);if(a&&a.n>=10&&a.until>Date.now())fail('尝试过多，请一分钟后重试',429);
  if(p.username!==db.admin.username||!verify(p.password,db.admin.password)){attempts.set(key,{n:a?.until>Date.now()?a.n+1:1,until:Date.now()+60000});fail('管理员账号或密码错误',401);}
  attempts.delete(key);const token=crypto.randomBytes(32).toString('hex');sessions.set(token,{until:Date.now()+43200000});return send(res,200,{ok:true,role:'admin'},{'Set-Cookie':`local_center=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200`});
 }
 if(req.headers['x-member-access'])fail('会员链接不能访问管理接口',403);
 if(!s)fail('请先登录管理员',401);
 if(req.method==='POST'&&url.pathname==='/api/member-access/password'){
  const p=await body(req);checkMemberPassword(req,p.adminPassword,db.admin.password);
  if(typeof p.newPassword!=='string'||p.newPassword.length<8||p.newPassword.length>128)fail('用户操作密码须为 8 至 128 位');
  db.admin.memberPassword=hash(p.newPassword);save();return send(res,200,{ok:true});
 }
 if(req.method==='GET'&&url.pathname==='/api/room-access')return send(res,200,{ok:true,...roomAccess(s)});
 if(req.method==='POST'&&url.pathname==='/api/room-access/password'){
  const p=await body(req),key=checkRoomAttempt(req);
  if(!verify(p.adminPassword,db.admin.password))wrongRoomPassword(key);
  if(typeof p.newPassword!=='string'||p.newPassword.length<8||p.newPassword.length>128)fail('房间访问密码须为 8 至 128 位');
  db.admin.roomPassword=hash(p.newPassword);save();
  for(const value of sessions.values())value.roomUnlocked=false;
  roomAttempts.delete(key);return send(res,200,{ok:true,configured:true,unlocked:false});
 }
 if(req.method==='POST'&&url.pathname==='/api/room-access/unlock'){
  const p=await body(req),key=checkRoomAttempt(req);
  if(!db.admin.roomPassword)fail('请先设置房间访问密码');
  if(!verify(p.password,db.admin.roomPassword))wrongRoomPassword(key);
  sessions.get(s.token).roomUnlocked=true;roomAttempts.delete(key);return send(res,200,{ok:true,configured:true,unlocked:true});
 }
 if(req.method==='POST'&&url.pathname==='/api/logout'){await body(req);sessions.delete(s.token);return send(res,200,{ok:true},{'Set-Cookie':'local_center=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'});}
 if(req.method==='POST'&&url.pathname==='/api/password'){
  const p=await body(req);if(!verify(p.oldPassword,db.admin.password))fail('旧密码错误');if(typeof p.newPassword!=='string'||p.newPassword.length<8||p.newPassword.length>128)fail('新密码须为 8 至 128 位');db.admin.password=hash(p.newPassword);save();sessions.clear();return send(res,200,{ok:true});
 }
 if(req.method==='GET'&&url.pathname==='/api/rooms/member-link'){
  const u=await rooms.call('member.access','canada28',{username:url.searchParams.get('username')});
  const link=`${publicOrigin||requestOrigin(req)}/portal#access=${memberToken(u.username,u.version)}`;
  return send(res,200,{ok:true,username:u.username,url:link,...await rooms.call('qr','canada28',{url:link})});
 }
 if(req.method==='GET'&&url.pathname==='/api/rooms/member-rebate-preview')return send(res,200,{ok:true,...await rooms.call('member-rebate.preview','canada28',{username:url.searchParams.get('username')})});
 if(req.method==='GET'&&url.pathname==='/api/rooms/force-open-preview'){requireRoomAccess(s);return send(res,200,{ok:true,...await rooms.call('force-open.preview',url.searchParams.get('game')||'canada28')});}
 if(req.method==='GET'&&url.pathname==='/api/rooms'){if(url.searchParams.get('view')==='protected')requireRoomAccess(s);return send(res,200,{ok:true,...await rooms.call('state',url.searchParams.get('game')||'canada28')});}
 if(req.method==='GET'&&url.pathname==='/api/rooms/export')return send(res,200,{exportedAt:new Date().toISOString(),...await rooms.call('export',url.searchParams.get('game')||'canada28')},{'Content-Disposition':'attachment; filename="room-records.json"'});
 if(req.method==='GET'&&url.pathname==='/api/legacy/export'){
  const {admin,linkSigningKey,...legacy}=db;return send(res,200,{...legacy,members:(legacy.members||[]).map(({password,...u})=>u),readOnly:true},{'Content-Disposition':'attachment; filename="legacy-records.json"'});
 }
 if(req.method==='POST'&&url.pathname==='/api/rooms/action'){
  const p=await body(req);if(!['config','close','force-open','draw','import','refund','score','review','notice','member.create','member.edit','member.delete','member.autobet','member.autobet.batch','member.rotate','legacy.settle','legacy.refund','workbench.save','workbench.order','workbench.request','workbench.cancel','workbench.report','workbench.stats.reset','workbench.rebate','workbench.data.clear','workbench.balances.clear','robot.messages.save'].includes(p.operation))fail('未知管理操作',404);
  const needsMemberPassword=p.operation==='member.delete'||['workbench.data.clear','workbench.balances.clear'].includes(p.operation)||(p.operation==='member.edit'&&['robot','enabled','auto'].some(key=>Object.hasOwn(p.data||{},key)))||(['member.autobet','member.autobet.batch'].includes(p.operation)&&p.data?.activateMember===true);
  if(needsMemberPassword){if(typeof p.memberPassword!=='string')fail('请验证用户操作密码',428);checkMemberPassword(req,p.memberPassword);}
  if(['config','close','force-open','draw','import','notice','robot.messages.save'].includes(p.operation))requireRoomAccess(s);
  return send(res,200,{ok:true,...await rooms.call(p.operation,p.game||'canada28',p.data)});
 }
 fail('接口已停用或不存在，请使用统一前后台',404);
 }catch(e){if(!res.headersSent)send(res,e.status||500,{ok:false,message:e.status?e.message:'本地服务内部错误，请查看终端'});if(!e.status)console.error(e);}});
server.on('error',e=>{console.error(e.code==='EADDRINUSE'?`端口 ${PORT} 已占用，请使用已有服务。`:e);process.exitCode=1;});
server.listen(PORT,'127.0.0.1',()=>{rooms.start().catch(e=>console.error('房间服务启动失败：'+e.message));console.log(`统一管理后台：http://127.0.0.1:${PORT}/admin\n会员前台：http://127.0.0.1:${PORT}/portal（使用后台专属链接）\n数据目录：${DIR}`);});
