const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../portal.js'),'utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
function context(room){
  const ctx=vm.createContext({room,state:{user:{username:'viewer'},history:[],chat:[]},ball:8,
    esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    textResultRoom:()=>true,publicRoom:()=>room!=='australia8',
    publicDrawText:()=> 'old draw text',a8DrawBundle:()=>'<div>draw</div>'});
  vm.runInContext(section('const cash =', 'const sharedBalance')+section('function drawPresentation(', 'function drawNumbers(')+
    section('function publicSettlementText(', 'function historyReferenceMessage(')+
    section('function chatMessage(', 'function historyPanel('),ctx);
  return ctx;
}
for(const room of ['canada28','australia8ball','australia8'])test(room+' renders winners and snapshot net in ranking',()=>{
  const c=context(room),a8=room==='australia8';
  const draw={issue:'R1',numbers:a8?[1,2,3,4,5,6,7,14]:[5,2,7],special:a8?14:7,fan:2,drawRule:'sum3',settlementRule:a8?'a8-number-v1':'sum-v4'};
  const rows=[{username:'winner',nickname:'<同名>',balance:100000,profit:-2090,simulated:false},
    {username:'other',nickname:'<同名>',balance:80000,profit:10000,simulated:false},
    {username:'idle',nickname:'静止',balance:0,profit:0,simulated:false}];
  const details={game:room,issue:'R1',draw,rows,winningOrders:[
    {username:'winner',nickname:'<同名>',ball:a8?8:0,selection:'2番',amount:1000,profit:2910,simulated:false}]};
  c.state.history=[draw];
  const message=(kind,content,details)=>({id:kind,kind,content,details,source:'system',username:null,who:'机器人',time:'2026-10-04 15:00:00',avatar:'🤖'});
  c.state.chat=[message('JIEGUO','R1期结果 [手动录入]\n5,2,7'),message('SETTLEMENT','old net body',details),message('YINGLI','old ranking',{game:room,issue:'R1',rows})];
  const text=c.publicSettlementText(details);
  assert.match(text,/获胜名单：/);assert.match(text,/盈：29\.10/);
  assert.doesNotMatch(text,/净输赢|\[1000\.00\]/);
  if(a8)assert.match(text,/第8球/);else assert.doesNotMatch(text,/第0球|第8球/);
  const html=c.renderRoomMessages();
  assert.equal((html.match(/获胜名单：/g)||[]).length,1);
  assert.match(html,/&lt;同名&gt;/);assert.doesNotMatch(html,/<同名>|old draw text|old net body/);
  assert.match(html,/\[1000\] \(-20\.90\)/);
  assert.match(html,/\[800\] \(\+100\)/);
  assert.match(html,/\[0\] \(\+0\)/);
  assert.match(c.publicSettlementText({...details,winningOrders:[]}),/本期暂无获胜注单/);
  const incomplete={...details};delete incomplete.winningOrders;
  assert.match(c.publicSettlementText(incomplete),/资料不完整/);
  const allWinners={...details,winningOrders:[
    ...details.winningOrders,
    {username:'simwinner',nickname:'老兵（模拟）',ball:a8?8:0,selection:'大',amount:160000,profit:155132,simulated:true},
    {username:'legacywinner',nickname:'爱情情侣',ball:a8?8:0,selection:'单',amount:130000,profit:124731},
    {username:'loser',nickname:'本期未中',ball:a8?8:0,selection:'小',amount:100,profit:-100,simulated:true},
    {username:'push',nickname:'本期和局',ball:a8?8:0,selection:'1念2',amount:100,profit:0,simulated:true}
  ]};
  const everyone=c.publicSettlementText(allWinners);
  assert.match(everyone,/\(老兵\)/);assert.match(everyone,/盈：1551\.32/);
  assert.match(everyone,/\(爱情情侣\)/);assert.match(everyone,/盈：1247\.31/);
  assert.doesNotMatch(everyone,/模拟|暂无获胜|本期未中|本期和局/);
});

test('money formatting preserves fractional values, nicknames and member chat',()=>{
 const c=context('canada28');
 for(const [cents,text] of [[0,'0'],[50000,'500'],[120,'1.20'],[50025,'500.25'],[-1,'-0.01'],[-10000,'-100']]){
  assert.equal(vm.runInContext(`cash(${cents})`,c),text);
 }
 assert.equal(c.compactSystemMoney({kind:'RECEIPT',content:'@用户500.00，攻击[1番10]成功\n共享积分：500.00'}),'@用户500.00，攻击[1番10]成功\n共享积分：500');
 assert.equal(c.compactSystemMoney({kind:'REFUND',content:'@用户500.00 已退 1 条，返还 12.34 积分'}),'@用户500.00 已退 1 条，返还 12.34 积分');
 c.state.chat=[{id:'chat',kind:'MESSAGE',username:'viewer',source:'member',who:'用户500.00',avatar:'A',time:'',content:'共享积分：500.00'}];
 assert.match(c.renderRoomMessages(),/共享积分：500\.00/);
 assert.match(c.renderRoomMessages(),/用户500\.00/);
});

test('custom robot text is escaped and never replaced by built-in winner/ranking text',()=>{
 for(const room of ['canada28','australia8ball','australia8']){
  const c=context(room);
  c.state.chat=['JIEGUO','SETTLEMENT','YINGLI','LUZI','A8_CLOSE_RULES'].map((kind,i)=>({id:String(i),kind,username:null,source:'system',who:'助手',avatar:'🤖',time:'',content:'自定义'+kind+'<script>',details:{robotTemplate:'edited'}}));
  const html=c.renderRoomMessages();
  for(const kind of ['JIEGUO','SETTLEMENT','YINGLI','LUZI','A8_CLOSE_RULES'])assert.match(html,new RegExp('自定义'+kind+'&lt;script&gt;'));
  assert.doesNotMatch(html,/<script>|暂无获胜|共享积分总榜/);
 }
});
