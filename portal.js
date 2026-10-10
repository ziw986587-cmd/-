const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cash = n => (n/100).toFixed(2).replace(/\.00$/, '');
const sharedBalance = () => state?.balance??state?.score??state?.wallets?.canada28??0;
let state, panel='', busy=false, polling=false, chatSignature='', chatDraft='', serverOffset=0;
let access=new URLSearchParams(location.hash.slice(1)).get('access')||'';
const pendingRequests=new Map();let loadSequence=0;
let bootSequence=0;
function memberDevice(){
  const key='local-center.member-device.v1';
  try{
    let value=localStorage.getItem(key);
    if(!/^[a-f0-9]{64}$/.test(value||'')){
      value=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
      localStorage.setItem(key,value);
    }
    return localStorage.getItem(key);
  }catch{throw Error('无法保存本机登录信息，请允许浏览器使用网站存储后重试。');}
}
let room = new URLSearchParams(location.search).get('game') || 'canada28';
if(!['canada28','australia8','australia8ball'].includes(room))room='canada28';
let view = location.pathname==='/home' ? 'room' : 'portal';
let ball = 8;
const modeName = m => ({simulation:'模拟开奖',manual:'手动开奖',external:'外部开奖源'}[m]);
const roomTitle = () => room==='canada28'?'加拿大28番摊':state.games[room];
function newRequestId(){
  if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&0x0f)|0x40;
  bytes[8]=(bytes[8]&0x3f)|0x80;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
}
async function request(path,data){
  path=path.replace('/api/','/api/portal/');
  const key=data===undefined?null:JSON.stringify([path,room,data]);
  if(key&&!pendingRequests.has(key))pendingRequests.set(key,newRequestId());
  const options={headers:{'X-Member-Access':access,'X-Member-Device':memberDevice()},cache:'no-store',credentials:'omit'};
  if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify({...data,game:room,requestId:pendingRequests.get(key)});}
  let r;
  try{r=await fetch(path,options);}catch{throw Error('连接中断，操作结果尚未确认。恢复后重试同一操作可安全核对。');}
  const value=await r.json();
  if(key)pendingRequests.delete(key);
  if(!r.ok){const e=Object.assign(Error(value.message||'请求失败'),{status:r.status});if([401,403].includes(r.status))locked(e.message);throw e;}
  return value;
}
function locked(message='请使用管理员提供的个人专属链接进入大厅。'){
  ++loadSequence;++bootSequence;
  state=null;panel='';$('#overlay').hidden=true;syncRoomViewport();
  $('#app').innerHTML=`<div class="portal"><section class="portal-card"><div class="emblem">◈</div><h1>会员入口</h1><p>${esc(message)}</p><div class="notice">每个账号同一时间仅允许一台设备登录。重新登录后，其他设备会退出。</div><button data-action="retry">重新登录</button></section></div>`;
}
function route(next=view){return (next==='room'?'/home?game='+encodeURIComponent(room):'/portal')+'#access='+encodeURIComponent(access);}
function notify(msg,error=false){const e=$('#toast');e.textContent=msg;e.className='toast visible'+(error?' error':'');clearTimeout(notify.timer);notify.timer=setTimeout(()=>e.className='toast',4000)}
function setBusy(value){busy=value;document.querySelectorAll('[type="submit"],.composer button,.composer select,.summary button[data-action="cancel"]').forEach(b=>{if(value){b.dataset.wasDisabled=String(b.disabled);b.disabled=true;}else{b.disabled=b.dataset.wasDisabled==='true';}});if(!value)refreshPanel();}
async function mutate(path,data={}){if(busy)return false;setBusy(true);try{const r=await request(path,data);notify(r.message||'已完成');if(path!=='/api/chat'&&path!=='/api/score-request')await load();else if(path==='/api/chat'){chatSignature='';updateLive();}refreshPanel();return true}catch(e){notify(e.message,true);return false}finally{setBusy(false)}}
async function boot(){if(!access){locked();return;}const ticket=++bootSequence;try{await request('/api/login',{});if(ticket!==bootSequence)return;await load();if(ticket!==bootSequence)return;render();const target=new URLSearchParams(location.hash.slice(1)).get('panel');if(panelFactories[target])openPanel(target,false);}catch(e){locked(e.message);}}
async function load(){const wanted=room,identityAtStart=access,ticket=++loadSequence;const result=await request('/api/state?game='+encodeURIComponent(wanted));if(wanted!==room||identityAtStart!==access||ticket!==loadSequence)return;state=result;serverOffset=state.serverTime*1000-Date.now();if(view==='room'&&$('#messages'))updateLive();else if($('#portal-nickname')){$('#portal-nickname').textContent=frontNickname(state.user.nickname);const el=$('[data-shared-balance]');if(el)el.textContent=cash(sharedBalance());}}
function setView(next){if(busy||!state)return;view=next;closePanel(false);history.pushState({},'',route(next));render();}
async function openRoom(key){if(busy)return;setBusy(true);const previous=room;try{room=key;await load();view='room';panel='';chatDraft='';history.pushState({},'',route());render();}catch(e){room=previous;notify(e.message,true);}finally{setBusy(false)}}
function render(){if(!state)return;document.title=view==='room'?roomTitle()+' · 会员前台':'会员大厅';$('#app').innerHTML=view==='portal'?portal():roomShell();if(view==='room'){chatSignature='';updateLive();$('#message-input').value=chatDraft;}syncRoomViewport();}
function portal(){return `<div class="portal"><nav><b>本地游戏大厅</b><div><span id="portal-nickname">${esc(frontNickname(state.user.nickname))}</span><button data-action="panel" data-value="account">会员中心</button></div></nav><section class="portal-card"><div class="emblem" aria-hidden="true">✦</div><h1>游戏大厅</h1><p>欢迎入座 · 请选择游戏房间</p><div class="portal-wallet"><span>共用积分</span><strong data-shared-balance>${cash(sharedBalance())}</strong><small>三个房间共用同一份余额</small></div><div class="room-buttons">${[['australia8','澳洲8番摊',5],['australia8ball','澳洲3翻摊',2],['canada28','加拿大翻摊',3]].map(([k,v,minutes])=>`<button data-action="room" data-value="${k}"><span>${esc(v)}<small>（${minutes}分钟一期）</small></span><span><small>使用共用积分</small>进入 ›</span></button>`).join('')}</div></section></div>`}
function keyboardMarkup(){const rows=[['查','上','下','无','加','大','小','单','双','×'],['番','角','车','严','正','堂','通','特','取消'],['1','2','3','4','5','6','7','8','9','0'],['+','-','/','=','，','。','空格','历史','换']];return `<div id="quick-keyboard" class="quick-keyboard" hidden>${rows.map(row=>{const keys=row.filter(key=>key!=='特'||room==='australia8');return `<div class="quick-keyboard-row" data-count="${keys.length}">${keys.map(key=>`<button type="button" data-key="${esc(key)}" aria-label="快捷输入 ${esc(key)}">${esc(key)}</button>`).join('')}</div>`}).join('')}</div>`}
function roomShell(){return `<div class="room"><header class="room-header"><button data-action="view" data-value="portal">‹ <span id="room-name"></span></button><b id="current-nickname">${esc(frontNickname(state.user.nickname))}</b><button class="balance" data-action="panel" data-value="account"><span id="balance"></span> ›</button></header><div class="draw-strip"><span id="issue"></span><button id="last-balls" data-action="panel" data-value="history" aria-label="查看开奖记录"></button><span id="countdown"></span></div><div id="messages" class="messages" aria-label="群聊消息"></div><button class="jump" data-action="bottom">↓ 最新消息</button><div class="room-bottom">${keyboardMarkup()}<form data-submit="sendChat" class="composer${room==='australia8'?' has-ball-select':''}"><button type="button" class="keyboard-toggle" title="快捷输入" aria-label="快捷输入" data-action="keyboard-toggle"><svg class="keyboard-icon" viewBox="0 0 24 20" aria-hidden="true" focusable="false"><rect x="1.5" y="3.5" width="21" height="13" rx="2"/><path d="M5 7h1m3 0h1m3 0h1m3 0h2M5 10h1m3 0h1m3 0h1m3 0h2M7 13h10"/></svg></button><textarea id="message-input" rows="1" autocomplete="off" aria-label="聊天或下注指令" title="Enter发送，Shift+Enter换行；支持逗号或换行分隔多注" placeholder=""></textarea>${room==='australia8'?`<select id="ball-select" aria-label="下注球位">${['一','二','三','四','五','六','七','八'].map((n,i)=>`<option value="${i+1}" ${ball===i+1?'selected':''}>第${n}球</option>`).join('')}</select>`:''}<button type="submit" class="primary">发送</button></form></div></div>`}
function updateLive(){
  $('#current-nickname').textContent=frontNickname(state.user.nickname);$('#room-name').textContent=roomTitle();$('#balance').textContent='共用积分 '+cash(sharedBalance());
  const h=state.history[0];$('#issue').textContent=h?h.issue+' 期':'暂无开奖';$('#issue').title=h?'最近已开奖期号，与右侧开奖号码对应':'等待首期开奖';$('#last-balls').innerHTML=h?headerBalls(h.numbers):'等待首期开奖';
  updateClock();
  const sig=JSON.stringify([room,ball,room==='australia8'?[...a8HighlightedBalls()]:[],state.chat,state.history]);
  if(sig!==chatSignature){
    const box=$('#messages'),near=box.scrollHeight-box.scrollTop-box.clientHeight<100||!chatSignature,top=box.scrollTop,boxTop=box.getBoundingClientRect().top;
    const visible=Array.from(box.children).find(el=>el.getBoundingClientRect().bottom>boxTop);
    const anchor=visible?{id:visible.dataset.messageId,offset:visible.getBoundingClientRect().top-boxTop}:null;
    box.innerHTML=renderRoomMessages()||'<div class="empty">本房间暂无消息</div>';
    const restored=anchor&&Array.from(box.children).find(el=>el.dataset.messageId===anchor.id);
    if(near)box.scrollTop=box.scrollHeight;
    else if(restored)box.scrollTop+=restored.getBoundingClientRect().top-boxTop-anchor.offset;
    else box.scrollTop=top;
    chatSignature=sig;
  }
}
function updateClock(){if(!$('#countdown')||!state)return;const n=Math.max(0,Math.ceil(state.round.endAt-(Date.now()+serverOffset)/1000));$('#countdown').textContent=state.round.paused?'暂停中':n===0?'等待开奖':state.round.closed||n<=state.round.closeSeconds?`已封盘 ${n}秒`:`距开奖 ${n}秒`;}
function scrollBottom(){$('#messages').scrollTop=$('#messages').scrollHeight}
async function sendChat(e){e.preventDefault();const text=$('#message-input').value.trim();if(!text||busy)return;if(await mutate('/api/chat',{message:text,ball})){chatDraft='';$('#message-input').value='';scrollBottom();}}
function hideQuickKeyboard(){pendingQuickKeyboard=false;const panel=$('#quick-keyboard');const toggle=$('.keyboard-toggle');const jump=$('.jump');if(panel){panel.hidden=true;}if(toggle)toggle.classList.remove('active');if(jump)jump.hidden=false;syncRoomViewport();}
let viewportFrame=0,roomViewportBase=0,roomViewportWidth=0,roomKeyboardActive=false,pendingQuickKeyboard=false;
function syncRoomViewport(){
  cancelAnimationFrame(viewportFrame);
  viewportFrame=requestAnimationFrame(()=>{
    const viewport=window.visualViewport,style=document.documentElement.style;
    const inRoom=!!document.querySelector('.room');
    document.documentElement.classList.toggle('room-page',inRoom);
    // Continue syncing during the browser's focus transition as well. Some
    // mobile Safari versions briefly report a scale different from 1 while
    // opening the native keyboard; skipping that frame leaves the old room
    // height in place and makes the page appear zoomed or require scrolling.
    const rawHeight=viewport?.height||window.innerHeight,rawWidth=viewport?.width||window.innerWidth;
    // Safari can briefly report a zero or oversized visual viewport while
    // opening the keyboard. Keep the room in a usable range during that
    // transition instead of applying a zero height that hides the composer.
    const height=Math.max(320,Math.min(window.innerHeight||rawHeight,rawHeight));
    const width=Math.max(280,Math.min(window.innerWidth||rawWidth,rawWidth));
    const focused=document.activeElement?.id==='message-input';
    if(!inRoom||!roomViewportBase||(!focused&&Math.abs(width-roomViewportWidth)>80)){
      roomViewportBase=height;roomKeyboardActive=false;
    }
    roomViewportWidth=width;
    const deficit=roomViewportBase-height;
    // Treat the keyboard as open only while the field is focused and the
    // visual viewport has actually lost a keyboard-sized portion.  Do not
    // retain a stale state after the keyboard closes or Safari changes its
    // browser chrome height.
    roomKeyboardActive=inRoom&&focused&&deficit>120;
    if(!roomKeyboardActive&&(!focused||height>roomViewportBase))roomViewportBase=height;
    document.documentElement.classList.toggle('room-system-keyboard',roomKeyboardActive);
    // The system keyboard belongs to ordinary text entry: resize the visible
    // room so the composer and its controls stay inside the viewport. The
    // shortcut keyboard is handled as an overlay in CSS and never changes the
    // room height or pushes the chat history upward.
    const layoutHeight=height;
    const box=$('#messages'),near=box&&box.scrollHeight-box.scrollTop-box.clientHeight<100;
    style.setProperty('--room-viewport-height',layoutHeight+'px');
    style.setProperty('--room-visible-height',height+'px');
    style.setProperty('--room-viewport-width',width+'px');
    style.setProperty('--room-viewport-top',(viewport?.offsetTop||0)+'px');
    style.setProperty('--room-viewport-left',(viewport?.offsetLeft||0)+'px');
    const keyboardOffset=viewport
      ?Math.max(0,(window.innerHeight||rawHeight)-((viewport.offsetTop||0)+rawHeight))
      :0;
    style.setProperty('--room-keyboard-bottom','0px');
    style.setProperty('--room-keyboard-offset',keyboardOffset+'px');
    if(pendingQuickKeyboard&&!roomKeyboardActive){
      pendingQuickKeyboard=false;
      const keys=$('#quick-keyboard');if(keys)keys.hidden=false;
      const jump=$('.jump');if(jump)jump.hidden=true;
      $('.keyboard-toggle')?.classList.add('active');
    }
    if(near)box.scrollTop=box.scrollHeight;
  });
}
window.visualViewport?.addEventListener('resize',syncRoomViewport);
window.visualViewport?.addEventListener('scroll',syncRoomViewport);
window.addEventListener('resize',syncRoomViewport);
syncRoomViewport();
 function appendQuickKey(key){const input=$('#message-input');if(!input)return;if(key==='×'){input.value=input.value.slice(0,-1);}else if(key==='取消'){input.value='';}else if(key==='空格'){input.value+=' ';}else if(key==='历史'){hideQuickKeyboard();openPanel('history');return;}else if(key==='换'){if(room==='australia8'){ball=ball%8+1;const select=$('#ball-select');if(select)select.value=String(ball);updateLive();}else{hideQuickKeyboard();openPanel('history');return;}}else{const aliases={'，':',','。':'.'};input.value+=aliases[key]??key;}chatDraft=input.value;}
async function command(text){await mutate('/api/chat',{message:text,ball})}
const panelFactories={tools:roomToolsPanel,history:historyPanel,trend:trendPanel,orders:ordersPanel,odds:oddsPanel,ranking:rankingPanel,account:accountPanel,bet:betPanel};
function closePanel(update=true){$('#overlay').hidden=true;panel='';if(update&&state)history.replaceState({},'',route());}
function openPanel(name,update=true){if(!state||!panelFactories[name])return;panel=name;$('#overlay').hidden=false;const titles={tools:'房间功能',history:'开奖记录',trend:'历史走势',orders:'我的注单',odds:'规则与赔率',ranking:'本地积分榜',account:'会员中心',bet:'快捷下注'};$('#panel-title').textContent=titles[name];$('#panel-body').innerHTML=panelFactories[name]();if(update)history.replaceState({},'',route()+'&panel='+name);}
function refreshPanel(){if(!state||!panel)return;if(panel==='account'){const el=$('#account-live');if(el)el.innerHTML=accountLive();const balance=$('#account-balance');if(balance)balance.textContent=cash(sharedBalance());const name=$('#account-nickname');if(name)name.textContent=frontNickname(state.user.nickname);const avatar=$('#account-avatar');if(avatar)avatar.innerHTML=globalThis.AvatarLibrary?.render(state.user.avatar)||esc(state.user.avatar);}else if(panel==='bet'){const el=$('#bet-availability');if(el)el.textContent=state.round.issue+'期 · '+(state.accepting?'开放':'已封盘');const button=$('#panel-body button[type=submit]');if(button)button.disabled=busy||!state.accepting;if(room==='australia8'){const amount=$('#panel-body input[name=amount]');if(amount){amount.min=Math.max(1,Math.ceil(state.limits.minBet/100));amount.max=Math.floor(state.limits.maxBet/100);}const note=$('#bet-limits-note');if(note)note.textContent='每条限额 '+cash(state.limits.minBet)+' 至 '+cash(state.limits.maxBet)+' 积分；封盘前60秒内禁止取消';}}else if(['orders','history','trend','odds','ranking'].includes(panel)){const top=$('#panel-body').scrollTop;$('#panel-body').innerHTML=panelFactories[panel]();$('#panel-body').scrollTop=top;}}
function table(headers,rows){return `<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows||`<tr><td colspan="${headers.length}" class="empty">暂无记录</td></tr>`}</tbody></table></div>`}
function roomToolsPanel(){return `<div class="room-function-list">${[['history','开奖记录'],['trend','走势'],['orders','我的注单'],['odds','规则与赔率'],['ranking','积分榜'],['bet','快捷下注']].map(([key,label])=>`<button data-action="panel" data-value="${key}">${label}<span aria-hidden="true">›</span></button>`).join('')}<button data-action="help">机器人帮助<span aria-hidden="true">›</span></button></div>`}
function drawPresentation(record){
  if(!record||!Array.isArray(record.numbers)||typeof record.issue!=='string')return null;
  const numbers=record.numbers,canada=room==='canada28',sum3=(room==='australia8ball'&&numbers.length===3)||(canada&&(record.drawRule==='sum3'||record.drawRule==='natural3'));
  const digits=canada||sum3;
  if(numbers.length!==(digits?3:8)||numbers.some(n=>!Number.isInteger(n)||n<0||n>(digits?9:20))||(!digits&&new Set(numbers).size!==8))return null;
  if((canada||room==='australia8ball')&&['sum-v3','sum-v4'].includes(record.settlementRule)){
    const total=numbers.reduce((sum,n)=>sum+n,0),fan=total%4||4,special=Number(numbers.join(''))%20||20;
    if(record.special!==special||record.fan!==fan)return null;
    const size=record.settlementRule==='sum-v4'?(total>=14?'大':'小'):(fan>=3?'大':'小');
    const parity=record.settlementRule==='sum-v4'?(total%2?'单':'双'):(fan%2?'单':'双');
    return {issue:record.issue,numbers,special,displaySpecial:total,fan,sum3:true,valueLabel:'和值',time:String(record.time||''),source:({simulation:'模拟开奖',manual:'手动录入',external:'外部开奖'})[record.source]||'来源未标注',context:'三号码相加取番',shape:size+' '+parity};
  }
  const natural=sum3?(record.settlementRule==='sum-v2'?(Number(record.natural)||Number(numbers.join(''))):numbers.reduce((sum,n)=>sum+n,0)):canada?(record.settlementRule==='sum-v2'?(Number(record.natural)||Number(numbers.join(''))):(numbers[1]*10+numbers[2]))%20||20:numbers[7];
  const special=sum3?(record.settlementRule==='sum-v2'?(natural%20||20):natural):canada?(natural%20||20):natural;
  const fan=(sum3||canada)?natural%4||4:special%4||4;
  if(record.special!==special||record.fan!==fan)return null;
  const shape=room==='australia8'&&record.settlementRule==='a8-number-v1'?(special>=11?'大':'小')+' '+(special%2?'单':'双'):record.settlementRule==='sum-v1'&&sum3?(special>=14?'大':'小')+' '+(special%2?'单':'双'):(fan>=3?'大':'小')+' '+(fan%2?'单':'双');
  return {issue:record.issue,numbers,special,displaySpecial:(sum3||canada)&&record.settlementRule==='sum-v2'?natural:special,fan,sum3,time:String(record.time||''),source:({simulation:'模拟开奖',manual:'手动录入',external:'外部开奖'})[record.source]||'来源未标注',context:sum3?'三号码自然数':canada?(record.settlementRule==='sum-v2'?'三号码自然数':'加拿大后2（旧规则）'):room==='australia8ball'?'旧版第8球':'第8球',shape};
}
function drawNumbers(result,small=false){return `<div class="${small?'draw-small-numbers':'draw-number-line'}${result.numbers.length===8?' eight-numbers':''}">${result.numbers.map((n,i)=>`<span class="draw-number${i===0?' first':''}">${n}</span>`).join('')}</div>`;}
function fanTile(fan){return `<span class="fan-tile fan-${fan}" aria-label="${fan}番">${fan}</span>`;}
function a8BallFan(number){return number%4||4;}
function a8HighlightedBalls(){
  const selected=new Set((state?.orders||[]).filter(o=>o.game==='australia8'&&o.username===state.user.username&&o.issue===state.round.issue&&o.status==='待开奖'&&Number.isInteger(o.ball)&&o.ball>=1&&o.ball<=8).map(o=>o.ball));
  return selected.size?selected:new Set([ball]);
}
function a8BallColor(index){return a8HighlightedBalls().has(index+1)?'a8-selected-ball':'a8-normal-ball';}
function headerBalls(numbers){return numbers.map((n,i)=>`<i class="ball ${room==='australia8'?a8BallColor(i):'b'+i%4}" title="第${i+1}球">${n}</i>`).join('');}
function a8IssueCell(record){return `<td class="a8-period" title="${esc(record.issue)}期">${esc(record.issue.slice(-2))}</td>`;}
function a8HistoryTable(records){
  const rows=records.slice(0,15).map(record=>{
    const r=drawPresentation(record);if(!r)return `<tr>${a8IssueCell(record)}<td colspan="11">记录待核对</td></tr>`;
    const clock=r.time.match(/\d{2}:\d{2}:\d{2}/)?.[0]||'—';
    return `<tr data-issue="${esc(r.issue)}">${a8IssueCell(record)}<td class="a8-clock" title="${esc(r.time)} 北京时间 · ${esc(r.source)}">${esc(clock)}</td>${r.numbers.map((n,i)=>`<td><span class="a8-number ${a8BallColor(i)}" title="第${i+1}球：${n}，${a8BallFan(n)}番">${String(n).padStart(2,'0')}</span></td>`).join('')}<td><span class="a8-history-fan fan-${r.fan}">${r.fan}</span></td><td class="a8-shape">${esc(r.shape)}</td></tr>`;
  }).join('');
  return `<section class="a8-history"><h3>最近${Math.min(15,records.length)}期开奖</h3><table class="a8-results-table"><colgroup><col style="width:8%"><col style="width:16%">${'<col style="width:7.5%">'.repeat(8)}<col style="width:7%"><col style="width:9%"></colgroup><thead><tr><th rowspan="2">期数</th><th rowspan="2">时间</th><th colspan="8">开奖结果</th><th rowspan="2">番</th><th rowspan="2">形态</th></tr><tr>${Array.from({length:8},(_,i)=>`<th>${i+1}<br>球</th>`).join('')}</tr></thead><tbody>${rows||'<tr><td colspan="12">等待首期开奖</td></tr>'}</tbody></table></section>`;
}
function a8Roadmap(records){
  const rows=records.slice(0,15).map(record=>{const r=drawPresentation(record);return `<tr data-issue="${esc(record.issue)}">${a8IssueCell(record)}${r?r.numbers.map((n,i)=>`<td><span class="a8-road-fan fan-${a8BallFan(n)}" title="${esc(r.issue)}期 · 第${i+1}球 ${String(n).padStart(2,'0')}：${a8BallFan(n)}番">${a8BallFan(n)}</span></td>`).join(''):'<td colspan="8">记录待核对</td>'}</tr>`;}).join('');
  return `<section class="a8-roadmap"><h3>路 子 图</h3><table class="a8-road-table"><thead><tr><th>期数</th>${Array.from({length:8},(_,i)=>`<th>${i+1}球</th>`).join('')}</tr></thead><tbody>${rows||'<tr><td colspan="9">等待首期开奖</td></tr>'}</tbody></table><p class="a8-result-note">最近${Math.min(15,records.length)}期 · 最新一期在上方 · 每列对应同一球位</p></section>`;
}
function a8DrawBundle(records){
  const r=drawPresentation(records[0]);
  const result=r?`<section class="a8-current-result"><header><strong>开奖结果</strong><span>第${esc(r.issue)}期</span></header><div class="a8-result-meta"><span>澳洲幸运8 <time title="${esc(r.time)} 北京时间">${esc(r.time.match(/\d{2}:\d{2}:\d{2}/)?.[0]||'—')}</time><small>${esc(r.source)} · 北京时间</small></span><b class="a8-main-fan fan-${r.fan}">${r.fan}番</b></div><div class="a8-ball-columns">${r.numbers.map((n,i)=>`<div><small>${i+1}球</small><span class="a8-number ${a8BallColor(i)}">${String(n).padStart(2,'0')}</span><span class="a8-ball-fan fan-${a8BallFan(n)}">${a8BallFan(n)}</span></div>`).join('')}</div><p class="a8-result-note">第8球特号：${String(r.special).padStart(2,'0')} · ${r.fan}番</p></section>`:'<p class="a8-result-note">等待有效开奖结果</p>';
  return `<div class="a8-draw-bundle">${result}${a8HistoryTable(records)}${a8Roadmap(records)}</div>`;
}
// A chat card is anchored to its own draw, so older messages never show a later period.
function sumDrawBundle(records){
  const current=drawPresentation(records[0]);
  if(!publicRoom()||!current||current.numbers.length!==3)return null;
  const clock=r=>r.time.match(/\d{2}:\d{2}:\d{2}/)?.[0]||'—';
  const total=current.numbers.reduce((sum,n)=>sum+n,0);
  const name=room==='canada28'?'加拿大28':'澳洲3';
  const rows=records.slice(0,15).map(record=>{
    const r=drawPresentation(record);
    const issue=`<td title="${esc(record.issue)}期">${esc(String(record.issue).slice(-2))}</td>`;
    if(!r||r.numbers.length!==3)return `<tr>${issue}<td colspan="5">记录待核对</td></tr>`;
    return `<tr data-issue="${esc(r.issue)}">${issue}<td title="${esc(r.time)} 北京时间">${esc(clock(r))}</td><td><div class="sum-mini-numbers">${r.numbers.map(n=>`<span class="sum-number">${n}</span>`).join('')}</div></td><td>${r.numbers.reduce((s,n)=>s+n,0)}</td><td><span class="sum-fan fan-${r.fan}">${r.fan}</span></td><td>${esc(r.shape)}</td></tr>`;
  }).join('');
  return `<section class="sum-draw-bundle" data-issue="${esc(current.issue)}" aria-label="${name}${esc(current.issue)}期开奖结果"><header><h3>开奖结果</h3><span>第${esc(current.issue)}期</span></header><div class="sum-result-meta"><div>${name} ${esc(clock(current))}<small>北京时间${records[0].source==='simulation'?' · 模拟开奖':''}</small></div><b class="sum-main-fan fan-${current.fan}">${current.fan}番</b></div><div class="sum-number-line">${current.numbers.map((n,i)=>`${i?'<span class="sum-sign">+</span>':''}<span class="sum-number">${n}</span>`).join('')}<span class="sum-sign">=</span><b class="sum-total">${total}</b></div><div class="sum-result-tags"><span>${current.fan}番</span>${current.shape.split(' ').map(v=>`<span>${esc(v)}</span>`).join('')}</div><p class="sum-result-note">${current.numbers.join(' + ')} = ${total} · ${current.fan}番 · ${esc(current.shape.replace(' ',''))}</p><section class="sum-draw-history"><h4>最近${Math.min(15,records.length)}期开奖</h4><table><colgroup><col style="width:12%"><col style="width:23%"><col style="width:29%"><col style="width:10%"><col style="width:10%"><col style="width:16%"></colgroup><thead><tr><th>期数</th><th>时间</th><th>开奖结果</th><th>合计</th><th>番</th><th>形态</th></tr></thead><tbody>${rows}</tbody></table></section><p class="sum-result-footer">${esc(current.time.slice(0,10))} · 北京时间 · 最新一期在上方</p></section>`;
}
function sumDrawMessageCard(message,index){
  if(!publicRoom()||message.kind!=='JIEGUO')return null;
  const next=state.chat[index+1];
  const paired=next?.kind==='SETTLEMENT'&&next.username==null&&(!next.source||next.source==='system')&&next.details?.game===room?next.details.issue:null;
  const issue=String(message.content).match(/^([A-Za-z0-9_-]+)期结果\s*\[/)?.[1]||paired;
  const at=state.history.findIndex(r=>r.issue===issue);
  return at>=0&&at<4?sumDrawBundle(state.history.slice(at)):null;
}
function drawCard(record){
  const result=drawPresentation(record);if(!result)return '<div class="notice">该期记录待核对</div>';
  return `<section class="draw-card${result.numbers.length===8?' eight-ball-card':''}" aria-label="${esc(result.issue)}期开奖结果"><header class="draw-card-heading"><strong>开奖结果</strong><span class="draw-issue">${esc(result.issue)}期</span></header><div class="draw-card-result">${drawNumbers(result)}<div class="draw-outcomes"><span class="draw-special">${String(result.displaySpecial??result.special).padStart(2,'0')}<small>${result.valueLabel||(result.sum3?'自然数':'特')}</small></span><span class="fan-tile fan-${result.fan}">${result.fan}<small>番</small></span></div></div><div class="draw-meta"><span>${esc(result.source)}</span><span>${esc(result.context)} · ${result.shape}</span></div><time class="draw-time">北京时间 ${esc(result.time.replace(/-/g,'/'))||'未记录'}</time></section>`;
}
function drawHistoryTable(records,limit=15,compact=false){
  const hideHistoryLabels=room==='canada28'||room==='australia8ball';
  const rows=records.slice(0,limit).map((record,index)=>{
    const result=drawPresentation(record);if(!result)return `<tr><td>${esc(record.issue)}</td><td colspan="3">记录待核对</td></tr>`;
    const clock=result.time.match(/\d{2}:\d{2}:\d{2}/)?.[0]||'—';
    const source=compact?({simulation:'模',manual:'手',external:'外'})[record.source]||'?':result.source;
    const valueLabel=hideHistoryLabels?'':(result.valueLabel||(result.sum3?'自然数':'特'));
    const sourceLabel=hideHistoryLabels?'':`<small class="draw-row-source" title="${esc(result.source)}">${esc(source)}</small>`;
    return `<tr${index===0?' class="latest"':''}><td><span class="draw-period" title="完整期号 ${esc(result.issue)}" aria-label="${esc(result.issue)}期">${esc(compact?result.issue.slice(-2):result.issue)}</span><time title="${esc(result.time)} 北京时间">${esc(clock)}</time></td><td>${drawNumbers(result,true)}<span class="draw-equals"> = </span><span class="draw-special-text">${String(result.displaySpecial??result.special).padStart(2,'0')}${valueLabel}</span></td><td>${fanTile(result.fan)}</td><td>${result.shape}${sourceLabel}</td></tr>`;
  }).join('');
  const shapeHeader=hideHistoryLabels?'形态':(compact?'形态':'形态 / 来源');
  return `<div class="draw-history-scroll"><table class="draw-history-table${room==='australia8'?' eight-balls':''}${compact?' compact':''}"><thead><tr><th>期数 / 时间</th><th>结果</th><th>番</th><th>${shapeHeader}</th></tr></thead><tbody>${rows||'<tr><td colspan="4" class="empty">暂无开奖记录</td></tr>'}</tbody></table></div>`;
}
function recentTrend(records){
  const selected=records.slice(0,18).reverse();
  const results=selected.map((record,index)=>{const result=drawPresentation(record);return `<li class="recent-trend-result${index===selected.length-1?' latest':''}" title="${esc(record.issue)}期${result?' · '+result.fan+'番 · '+esc(result.source):' · 记录待核对'}" aria-label="${esc(record.issue)}期${result?' '+result.fan+'番':'记录待核对'}"><span class="${result?'trend-value fan-'+result.fan:'trend-value invalid'}">${result?result.fan:'?'}</span></li>`;}).join('');
  return `<section class="recent-trend"><h4>历史走势 · 最近${selected.length}期</h4>${selected.length?`<ol class="recent-trend-results" aria-label="最近${selected.length}期番数结果，由旧到新">${results}</ol><p class="roadmap-note">从左到右、从上到下，末尾为最新一期${room==='australia8ball'?' · 三号码和值取番，旧记录按原规则保留':''}</p>`:'<p class="roadmap-note">等待首期开奖</p>'}</section>`;
}
function roadmap(records,limit=48,showRecent=true){
  const selected=records.slice(0,limit).reverse();
  const cells=selected.map((record,index)=>{const result=drawPresentation(record);return result?`<span class="roadmap-cell fan-${result.fan}${index===selected.length-1?' latest':''}" title="${esc(result.issue)}期 · ${result.fan}番 · ${esc(result.source)}" aria-label="${esc(result.issue)}期 ${result.fan}番">${result.fan}</span>`:'<span class="roadmap-cell invalid" title="记录待核对">?</span>';}).join('');
  const blanks=selected.length?'<span class="roadmap-cell blank" aria-hidden="true"></span>'.repeat((12-selected.length%12)%12):'';
  return `<section class="roadmap"><h3>路 子 图</h3><div class="roadmap-grid" aria-label="历史番数路子图">${cells+blanks}</div><p class="roadmap-note">${selected.length?`最近 ${selected.length} 期 · 从左到右、从上到下，由旧到新`:'等待首期开奖'}${room==='australia8ball'?' · 三号码和值取番，旧记录按原规则保留':''}</p>${showRecent?recentTrend(records):''}</section>`;
}
function historySnapshot(records,limit=15,showAll=false,showRecent=true){const hideHistoryLabels=room==='canada28'||room==='australia8ball';const sourceNote=hideHistoryLabels?'':(showAll?'期数显示后2位；模＝模拟，手＝手动，外＝外部。<br>':'');const timeNote=hideHistoryLabels?'时间为北京时间':`时间为北京时间${showAll?'':'，来源逐期标注'}`;return `<section class="draw-history"><header class="draw-history-heading"><span>历史开奖 · ${room==='canada28'?'加拿大28（逐期规则）':room==='australia8ball'?'澳洲3和值':'第8球'}</span>${showAll?'<button data-action="panel" data-value="history">查看全部 ›</button>':''}</header>${drawHistoryTable(records,limit,showAll)}<p class="draw-context">${sourceNote}${timeNote}</p>${roadmap(records,48,showRecent)}</section>`;}
function settlementSummary(details){
  if(!details||details.game!==room||typeof details.issue!=='string'||!Array.isArray(details.rows)||!Number.isSafeInteger(details.totalProfit))return null;
  const rows=details.rows;
  if(rows.some(row=>!row||typeof row.username!=='string'||typeof row.nickname!=='string'||typeof row.simulated!=='boolean'||!Number.isSafeInteger(row.balance)||row.balance<0||!Number.isSafeInteger(row.profit)||!Number.isSafeInteger(row.betCount)||row.betCount<0)||new Set(rows.map(row=>row.username)).size!==rows.length||rows.reduce((sum,row)=>sum+row.profit,0)!==details.totalProfit)return null;
  return `<section class="settlement-summary"><header class="settlement-heading"><strong>用户输赢结果</strong><span>${esc(details.issue)}期</span></header><p class="settlement-note">结算后共用积分 · 本房间本期净输赢${room==='australia8ball'?'（三号码和值）':''}</p><div class="settlement-rows">${rows.map(row=>`<div class="settlement-row"><span class="settlement-user">${esc(frontNickname(row.nickname))}</span><span class="settlement-balance">[${cash(row.balance)}]</span><span class="settlement-profit ${row.profit>0?'win':row.profit<0?'lose':'neutral'}">(${row.profit>=0?'+':''}${cash(row.profit)})</span></div>`).join('')||'<p class="empty">本期暂无会员</p>'}</div></section>`;
}
function publicRoom(){return room==='canada28'||room==='australia8ball';}
function textResultRoom(){return publicRoom()||room==='australia8';}
function resultNumbersText(numbers){return room==='australia8'?numbers.map(n=>String(n).padStart(2,'0')).join(' '):numbers.join('');}
function publicDrawText(message,index){
  const issue=String(message.content).match(/^([A-Za-z0-9_-]+)期结果\s*\[/)?.[1];
  const record=issue&&state.history.find(item=>item.issue===issue);
  if(record&&Array.isArray(record.numbers))return `${record.issue}期开奖结果：${resultNumbersText(record.numbers)}`;
  const first=String(message.content).split('\n')[0].replace(/期结果\s*\[[^\]]+\]/,'期开奖结果');
  const numbers=String(message.content).split('\n')[1]?.match(/^\s*([\d,， ]+)/)?.[1];
  return numbers?`${first}：${room==='australia8'?resultNumbersText(numbers.trim().split(/[，, ]+/)):numbers.replace(/[，, ]/g,'')}`:first;
}
function publicSettlementText(details,fallback=''){
  if(details?.game===room&&typeof details.issue==='string'&&Array.isArray(details.winningOrders)){
    const record=details.draw?.issue===details.issue?details.draw:state.history.find(r=>r.issue===details.issue);
    const draw=drawPresentation(record);
    if(draw){
      const lines=['------------',details.issue+'结果：',draw.numbers.map(n=>room==='australia8'?String(n).padStart(2,'0'):String(n)).join(','),'=> '+draw.fan+','+draw.shape.split(' ').reverse().join(','),'获胜名单：'];
      const groups=new Map();
      for(const order of details.winningOrders){
        if(!order||!(order.profit>0)||(room==='australia8'&&(!Number.isInteger(order.ball)||order.ball<1||order.ball>8)))continue;
        if(!groups.has(order.username))groups.set(order.username,{nickname:order.nickname,orders:[]});
        groups.get(order.username).orders.push(order);
      }
      for(const group of groups.values()){
        lines.push('('+frontNickname(group.nickname)+')');
        for(const order of group.orders)lines.push('　“'+(room==='australia8'?'第'+order.ball+'球/':'')+order.selection+'/'+cash(order.amount).replace(/\.00$/,'')+'” 盈：'+cash(order.profit));
      }
      if(!groups.size)lines.push('本期暂无获胜注单');
      lines.push('（盈为该获胜注单净盈利，不含本金）');
      return lines.join('\n');
    }
  }
  if(details&&details.game===room&&typeof details.issue==='string'&&Array.isArray(details.rows)){
    return `${details.issue}结果：\n历史获胜注单资料不完整，请查看我的注单。`;
  }
  const lines=String(fallback).split('\n').filter(line=>!/(用户|〔用户〕|\[用户\]|未参与)/.test(line));
  return lines.join('\n');
}
function publicRankingText(text,details){
  if(details?.game===room&&typeof details.issue==='string'&&Array.isArray(details.rows)){
    return '共享积分总榜\n'+(details.rows.map(row=>`${frontNickname(row.nickname)} [${cash(row.balance)}] (${row.profit>=0?'+':''}${cash(row.profit)})`).join('\n')||'暂无可显示会员');
  }
  const lines=String(text).split('\n');
  const visible=lines.filter((line,index)=>index===0||!/(用户|〔用户〕|\[用户\])/.test(line)).map(hideSimulatedLabels);
  return visible.length>1?visible.join('\n'):'共享积分总榜\n暂无可显示会员';
}
function historyReferenceMessage(text,records=null){
  const original=String(text),parts=original.split('\n---------------\n');
  const fallback=original;
  if(parts.length!==2||!parts[0].startsWith('历史参考：\n'))return fallback;
  const values=parts[0].slice('历史参考：\n'.length).trim();
  let fans=values?values.split(/[\s-]+/):[];
  if(fans.some(fan=>!/^[1-4]$/.test(fan)))return fallback;
  fans=fans.slice(-48);
  if(room==='australia8'){
    const results=records?.slice(0,48).map(drawPresentation);
    if(results?.length&&results.every(Boolean))fans=results.reverse().map(result=>String(a8BallFan(result.numbers[ball-1])));
    else if(ball!==8)return '第'+ball+'球历史参考：\n该期逐球记录未加载，请在开奖记录中查看。\n---------------\n'+parts[1].replace(/期开始$/,'期开始攻击');
  }else if(records){
    const results=records.slice(0,48).map(drawPresentation);
    if(results.length===fans.length&&results.every(Boolean)){
      fans=results.reverse().map(result=>String(result.fan));
    }
  }
  const lines=[];for(let start=0;start<fans.length;start+=12)lines.push(fans.slice(start,start+12).join(' - '));
  const phase=parts[1].replace(/^([A-Za-z0-9_-]+)期开始$/gm,'$1期开始攻击');
  return (room==='australia8'?'第'+ball+'球历史参考：\n':'历史参考：\n')+lines.join('\n')+'\n---------------\n'+phase;
}
function chatMessage(message,content,rich=false){return `<article data-message-id="${esc(message.id)}" class="message ${message.username===state.user.username?'mine':''}${rich?' draw-message'+(content.includes('class="a8-draw-bundle"')?' a8-draw-message':content.includes('class="sum-draw-bundle"')?' sum-draw-message':''):''}"><div class="avatar">${globalThis.AvatarLibrary?.render(message.avatar)||esc(message.avatar)}</div><div class="message-body"><div class="message-name">${esc(message.username?frontNickname(message.who):hideSimulatedLabels(message.who))} <time title="${esc(message.time)} 北京时间">${esc(String(message.time||'').slice(11,16))}</time></div><div class="bubble ${message.kind==='HEDUI'?'checklist':''}${rich?' draw-bubble':''}">${content}</div></div></article>`;}
function hideSimulatedLabels(text){return String(text).replace(/(?:〔|【|\[)\s*模拟(?:用户)?\s*(?:〕|】|\])/g,'').replace(/[（(]\s*模拟(?:用户)?\s*[）)]/g,'').replace(/[ \t]{2,}/g,' ');}
function compactSystemMoney(message){
  let text=String(message.content);
  if(message.kind==='RECEIPT')return text.replace(/(\n共享积分：)(-?\d+)\.00(?=\n|$)/g,'$1$2');
  if(message.kind==='REFUND')return text.replace(/(已退 \d+ 条，返还 )(\d+)\.00( 积分)$/,'$1$2$3');
  if(message.kind==='MESSAGE'){
    if(text.startsWith('共享积分：'))text=text.replace(/(^共享积分：|\n累计盈亏：|\n累计流水：|\n当局下注（[^\n]*期）：)(-?\d+)\.00(?=（|\n|$)/g,'$1$2');
    text=text.replace(/([，](?:上分|下分))(\d+)\.00(，待本地管理员审核。)$/,'$1$2$3');
  }
  return text;
}
function renderRoomMessages(){
  let anchor=null,rendered=[],previousPublicDraw=null;const names=publicNameMap();
  for(let messageIndex=0;messageIndex<state.chat.length;messageIndex++){
    const original=state.chat[messageIndex];const systemMessage=original.username==null&&(!original.source||original.source==='system');const message=systemMessage?{...original,content:shortMessageNames(publicCloseText(original),names)}:original;
    const system=message.username==null&&(!message.source||message.source==='system');
    let content=esc(hideSimulatedLabels(system?compactSystemMoney(message):message.content)),rich=false,legacy='',before='';
    const sumCard=system?sumDrawMessageCard(message,messageIndex):null;
    if(sumCard){
      rendered.push(chatMessage(message,sumCard,true));
      previousPublicDraw=null;anchor=null;
      continue;
    }
    if(system&&message.kind==='HEDUI')content=closeMessageHtml(message,names);
    if(system&&message.details?.robotTemplate){
      const output=chatMessage(message,content);
      if(message.kind==='SETTLEMENT'&&previousPublicDraw&&previousPublicDraw.index===messageIndex-1&&message.details.issue===previousPublicDraw.issue){
        rendered[previousPublicDraw.outputIndex]=output;
      }else rendered.push(output);
      previousPublicDraw=null;
      if(message.kind!=='YINGLI')anchor=null;
      continue;
    }
    if(system&&room==='australia8'&&message.kind==='A8_CLOSE_RULES'){
      content='<span class="a8-closing-rules">'+String(message.content).split('\n').map((line,i)=>'<span class="a8-rule-line a8-rule-'+i+'">'+esc(line)+'</span>').join('')+'</span>';
    }else if(system&&message.kind==='JIEGUO'){
      const marker=String(message.content).indexOf('\n获胜名单：');
      if(marker>=0){
        const original=String(message.content).slice(marker+'\n获胜名单：'.length).trim();
        content=esc(String(message.content).slice(0,marker));
        const issue=String(message.content).match(/^([A-Za-z0-9_-]+)期结果 \[/)?.[1];
        const visibleLegacy=publicRoom()?hideSimulatedLabels(original).split('\n').filter(line=>!/(用户|〔用户〕|\[用户\]|)/.test(line)).join('\n'):hideSimulatedLabels(original);
        if(visibleLegacy.trim())legacy=chatMessage({...message,id:message.id+'-legacy-winners',kind:'LEGACY_WINNERS'},`<span class="legacy-winners-title">历史中奖注单（旧版记录）${issue?'<br>'+esc(issue)+'期':''}</span>\n${esc(visibleLegacy)}\n<span class="legacy-winners-note">旧版仅记录中奖注单，不代表本期净输赢。</span>`);
      }
      const issue=String(message.content).match(/^([A-Za-z0-9_-]+)期结果 \[/)?.[1];
      const historyIndex=state.history.findIndex(record=>record.issue===issue);
      anchor=historyIndex>=0&&drawPresentation(state.history[historyIndex])?historyIndex:null;
      // Bound rich chat snapshots; every saved record stays available in the history panel.
      if(room==='australia8'&&anchor!==null&&anchor<4){content=a8DrawBundle(state.history.slice(anchor));rich=true;}
      else if(textResultRoom())content=esc(publicDrawText(message,historyIndex));
      else if(anchor!==null&&anchor<4){content=drawCard(state.history[anchor]);rich=true;}
    }else if(system&&message.kind==='SETTLEMENT'){
      if(textResultRoom())content=esc(publicSettlementText(message.details,message.content));
      else{
        content=esc(String(message.content).replace(/(\([+-]\d+\.\d{2}\)) 未参与(?=\r?$)/gm,'$1'));
        const summary=settlementSummary(message.details);
        if(summary){content=summary;rich=true;}
      }
      const settlementIssue=message.details?.game===room&&typeof message.details.issue==='string'?message.details.issue:String(message.content).match(/^([A-Za-z0-9_-]+)期用户输赢结果/)?.[1];
      if(textResultRoom()&&previousPublicDraw&&previousPublicDraw.index===messageIndex-1&&settlementIssue===previousPublicDraw.issue){
        const settlementText=publicSettlementText(message.details,message.content);
        rendered[previousPublicDraw.outputIndex]=chatMessage(message,esc(settlementText),false)+previousPublicDraw.legacy;
        previousPublicDraw=null;
        continue;
      }
    }else if(system&&message.kind==='YINGLI'&&textResultRoom()){
      content=esc(publicRankingText(message.content,message.details));
    }else if(system&&message.kind==='LUZI'){
      const separate=textResultRoom();
      const records=anchor===null?null:state.history.slice(anchor);
      const reference=historyReferenceMessage(message.content,separate?records:null);
      content=esc(reference);
      if(!publicRoom()&&room!=='australia8'&&anchor!==null&&anchor<4&&String(message.content).startsWith('历史参考：\n')){
        if(separate){
          before=chatMessage({...message,id:message.id+'-history-card'},historySnapshot(records,15,true,false),true);
        }else{
          const phase=reference.split('\n---------------\n').slice(1).join('\n');
          content=historySnapshot(records,15,true)+(phase?`<div class="draw-phase">${esc(phase)}</div>`:'');rich=true;
        }
      }
      anchor=null;
    }else if(!(system&&message.kind==='YINGLI'))anchor=null;
    const output=before+chatMessage(message,content,rich)+legacy;
    const outputIndex=rendered.length;
    rendered.push(output);
    const drawIssue=String(message.content).match(/^([A-Za-z0-9_-]+)期结果 \[/)?.[1];
    previousPublicDraw=room!=='australia8'&&textResultRoom()&&!rich&&system&&message.kind==='JIEGUO'&&drawIssue?{index:messageIndex,outputIndex,message,content,legacy,issue:drawIssue}:null;
  }
  return rendered.join('');
}
function historyPanel(){if(room==='australia8')return `<div class="history-view">${a8DrawBundle(state.history)}</div>`;return `<div class="history-view">${state.history.length?drawCard(state.history[0]):''}${historySnapshot(state.history,state.history.length)}</div>`;}
function trendPanel(){if(room==='australia8')return `<div class="history-view a8-draw-bundle">${a8Roadmap(state.history)}${a8HistoryTable(state.history)}</div>`;return `<div class="history-view"><p class="note">${room==='australia8ball'?'三个号码相加取和值；和值0至13为小，14至27为大，按和值奇偶判单双，旧记录保留原结果。':''}展示已保存的历史结果。</p>${roadmap(state.history)}${drawHistoryTable(state.history,15)}</div>`;}
function ordersPanel(){return `<div class="summary"><b>共用积分 ${cash(sharedBalance())}</b><span>累计盈亏 ${cash(state.profit)}</span><button data-action="cancel">退还当前待开奖注单</button><button data-action="export">导出 CSV</button></div>`+table(['期号','来源','玩法','球位','积分','状态','盈亏','操作'],state.orders.map(o=>`<tr><td>${esc(o.issue)}</td><td>会员</td><td>${esc(o.selection)}</td><td>${room==='australia8ball'?(o.ball===0?'和值':'旧第'+o.ball+'球'):room==='australia8'?'第'+(o.ball??8)+'球':'—'}</td><td>${cash(o.amount)}</td><td>${esc(o.status)}</td><td>${o.profit===null?'—':cash(o.profit)}</td><td>${o.status==='待开奖'?`<button data-action="cancel" data-value="${o.id}">退单</button>`:'—'}</td></tr>`).join(''))}
async function cancelOrder(id){if(room==='australia8'&&state.round.endAt-state.round.closeSeconds-(Date.now()+serverOffset)/1000<=60){notify('澳洲8离封盘60秒以内禁止取消注单',true);return;}if(await mutate('/api/cancel',{id}))openPanel('orders')}
function exportOrders(){const rows=[['单号','期号','来源','玩法','积分','状态','盈亏'],...state.orders.map(o=>[o.id,o.issue,'会员',o.selection,cash(o.amount),o.status,o.profit===null?'':cash(o.profit)])];if(room==='australia8'){rows[0].splice(4,0,'球位');state.orders.forEach((o,i)=>rows[i+1].splice(4,0,'第'+(o.ball??8)+'球'));}const csv='\ufeff'+rows.map(r=>r.map(s=>'"'+String(s).replace(/"/g,'""')+'"').join(',')).join('\r\n');download(new Blob([csv],{type:'text/csv;charset=utf-8'}),'本地注单.csv')}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
function oddsPanel(){if(room==='canada28'||room==='australia8ball')return sumOddsPanel();const labels={'番':'选中一番获胜，其余输','角':'相邻两番中任一获胜','念':'首号码赢，后号码和，其余输','无':'前号码赢，末号码输，其余和','双无':'前两个号码赢，末号码输，其余和','通':'首号码和，后两个号码赢，其余输','正':'选中号码赢，对面号码输，相邻号码和','车':'选中号码输，其余赢','大小单双':'所选球号码01–10为小，11–20为大；奇数为单，偶数为双','小单':'所选球01–10且为奇数','小双':'所选球01–10且为偶数','大单':'所选球11–20且为奇数','大双':'所选球11–20且为偶数','特':'选中01至20特号获胜'};return `<div class="notice">当前房间规则与后台配置一致。倍率为净盈利倍率，胜出时另返还本金；和局返还本金。</div><p>${room==='australia8'?'澳洲8按提交注单时所选第1至第8球结算；番摊玩法按所选球号码除以4取余，余0记4番；大小单双按该球实际号码判定：01–10为小，11–20为大，奇数为单、偶数为双；四种组合同时满足大小与单双。特码按实际号码结算。旧注单按提交时规则结算，旧开奖记录保留原规则。默认第8球。':'澳洲8番摊使用第8球；'}${room==='australia8'?(()=>{const r=state.a8Thresholds||{};const middle=r.middleSwitchSeconds??r.switchSeconds??50;const final=r.finalSwitchSeconds??(state.round?.period-state.round?.closeSeconds??290);const total=r.finalTotal==null?'不限':cash(r.finalTotal);return '澳洲8开奖后0至'+esc(middle)+'秒单注最高'+cash(r.firstMax??3000000)+'积分；'+middle+'至'+esc(final)+'秒按单个用户当前期所有玩法累计最高'+cash(r.middleMax??r.secondMax??1000)+'积分；'+final+'秒起至封盘按单个用户当前期所有玩法累计最高'+total+'积分，单笔也不能超过剩余额度。最后60秒禁止取消。';})():''}组合玩法倍率留空表示未启用。</p>`+table(['玩法','净盈利倍率','结算方式'],Object.entries(state.odds).map(([k,v])=>`<tr><td>${k}</td><td>${v==null?'未启用':esc(v)}</td><td>${esc(labels[k]||'')}</td></tr>`).join(''))+'<p class="note">特码示例：01/10＝01号10积分；11/18/10＝11号和18号各10，共20积分；特12/20＝12号20积分；特1/2/3/4/5各30＝1至5号各下注30。特码按当前所选球位的实际号码01至20判定。同次发送均使用当前球位，可与番摊混合：01/10,11/18/10,特12/20,2番10。多注用英文逗号、中文逗号或换行分隔。保留番摊简写：12/100仍为12角；有歧义的特码请加“特”前缀，例如特12/100。</p>'}
function rankingPanel(){return table(['排名','昵称','本地积分'],state.ranking.map((u,i)=>`<tr><td>${i+1}</td><td>${esc(frontNickname(u.nickname))}</td><td>${cash(u.balance)}</td></tr>`).join(''))}
function accountLive(){return `<h3>我的申请</h3>${table(['时间','房间','类型','积分','状态'],state.requests.map(r=>`<tr><td>${esc(r.time)}</td><td>${esc(state.games[r.game])}</td><td>${esc(r.action)}</td><td>${cash(r.amount)}</td><td>${esc(r.status)}</td></tr>`).join(''))}<h3>全部房间积分流水</h3>${table(['时间','来源房间','原因','变动','记录余额','余额类型'],state.ledger.map(l=>`<tr><td>${esc(l.time)}</td><td>${esc(state.games[l.game]||'账户')}</td><td>${esc(l.reason)}</td><td>${cash(l.delta)}</td><td>${cash(l.balance)}</td><td>${l.walletScope==='shared'?'共用积分':'历史房间积分'}</td></tr>`).join(''))}`;}
function accountPanel(){return `<div class="summary"><div class="big-avatar" id="account-avatar">${globalThis.AvatarLibrary?.render(state.user.avatar)||esc(state.user.avatar)}</div><div><b id="account-nickname">${esc(frontNickname(state.user.nickname))}</b><p>${esc(state.user.username)}</p></div><button data-action="exit">离开前台</button></div><form data-submit="saveProfile"><h3>个人资料</h3><div class="form-row"><label>昵称<input name="nickname" value="${esc(frontNickname(state.user.nickname))}" maxlength="20" required></label>${globalThis.AvatarLibrary?.picker(state.user.avatar)||''}<button type="submit" class="primary">保存</button></div></form><div class="notice">申请来源房间：${esc(state.games[room])} · 共用积分 <b id="account-balance">${cash(sharedBalance())}</b>。三个房间使用同一份余额，下注、结算和上下分均实时同步，无需转分。</div><form data-submit="scoreRequest"><div class="form-row"><label>申请类型<select name="action"><option>上分</option><option>下分</option></select></label><label>积分<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required></label><button type="submit">提交审核</button></div></form><div id="account-live">${accountLive()}</div>`;}
async function saveProfile(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(data.nickname===frontNickname(state.user.nickname))data.nickname=state.user.nickname;if(await mutate('/api/profile',data)){render();openPanel('account');}}
async function scoreRequest(e){e.preventDefault();if(await mutate('/api/score-request',Object.fromEntries(new FormData(e.target)))){e.target.reset();refreshPanel();}}
function betPanel(){return `${room==='australia8'?'<p class="notice">下注球位：第'+ball+'球。可关闭此面板，在输入框右侧切换球位。特码按所选球的实际号码01至20判定，不取番数。</p>':''}<div id="bet-availability" class="notice">当前：${esc(state.round.issue)}期 · ${state.accepting?'开放':'已封盘'}。提交后由本地机器人确认。</div><form data-submit="quickBet"><label>玩法<select name="selection">${['1番','2番','3番','4番','12角','23角','34角','14角','大','小','单','双','小单','小双','大单','大双',...(room==='australia8'?Array.from({length:20},(_,i)=>String(i+1).padStart(2,'0')+'特'):[])].map(x=>`<option>${x}</option>`).join('')}</select></label><label>积分<input name="amount" type="number" min="${Math.max(1,Math.ceil(state.limits.minBet/100))}" max="${Math.floor(state.limits.maxBet/100)}" step="1" value="${Math.max(10,Math.max(1,Math.ceil(state.limits.minBet/100)))}" required></label><p id="bet-limits-note" class="note">下注金额必须为正整数，每条限额 ${cash(state.limits.minBet)} 至 ${cash(state.limits.maxBet)} 积分</p><button type="submit" class="primary" ${state.accepting?'':'disabled'}>提交本地注单</button></form><p>复杂指令可直接在聊天输入框输入，如：12无3/20，1念2/10。</p>`}
async function quickBet(e){e.preventDefault();const d=Object.fromEntries(new FormData(e.target));if(!/^[0-9]+$/.test(d.amount)||Number(d.amount)<1){notify('下注金额必须为正整数，不能包含小数点',true);return;}if(await mutate('/api/bet',{text:d.selection+'/'+d.amount,ball}))closePanel()}

document.body.insertAdjacentHTML('beforeend','<div id="overlay" class="overlay" hidden><section class="sheet" role="dialog" aria-modal="true" aria-labelledby="panel-title"><header><h2 id="panel-title"></h2><button aria-label="关闭面板" data-action="close">×</button></header><div id="panel-body"></div></section></div><div id="toast" class="toast" role="status"></div>');
document.addEventListener('click',async e=>{const key=e.target.closest('[data-key]');if(key){appendQuickKey(key.dataset.key);return;}const b=e.target.closest('[data-action]');if(!b)return;try{switch(b.dataset.action){case 'keyboard-toggle':{const panel=$('#quick-keyboard');if(panel){const show=panel.hidden&&!pendingQuickKeyboard;if(show){pendingQuickKeyboard=true;$('#message-input')?.blur();syncRoomViewport();}else hideQuickKeyboard();}break;}case 'panel':openPanel(b.dataset.value);break;case 'view':setView(b.dataset.value);break;case 'room':await openRoom(b.dataset.value);break;case 'close':closePanel();break;case 'cancel':await cancelOrder(b.dataset.value);break;case 'export':exportOrders();break;case 'bottom':scrollBottom();break;case 'help':closePanel();await command('帮助');break;case 'retry':await boot();break;case 'exit':if(busy)return;await request('/api/logout',{});access='';history.replaceState({},'','/portal');locked('已离开前台。请使用个人专属链接重新进入。');break;}}catch(err){notify(err.message,true);}});
const submitters={sendChat,saveProfile,scoreRequest,quickBet};
document.addEventListener('submit',e=>{e.preventDefault();const fn=submitters[e.target.dataset.submit];if(fn)fn(e).catch(err=>notify(err.message,true));});
document.addEventListener('input',e=>{if(e.target.id==='message-input')chatDraft=e.target.value;});
document.addEventListener('focusin',e=>{if(e.target.id==='message-input')hideQuickKeyboard();});
document.addEventListener('focusout',e=>{if(e.target.id==='message-input')syncRoomViewport();});
document.addEventListener('change',e=>{if(e.target.id==='ball-select'){ball=Number(e.target.value);if(state&&view==='room'){updateLive();refreshPanel();}}});
$('#overlay').addEventListener('click',e=>{if(e.target===$('#overlay'))closePanel();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closePanel();if(e.target.id==='message-input'&&e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.target.form.requestSubmit();}});
async function restoreRoute(){view=location.pathname==='/home'?'room':'portal';const next=new URLSearchParams(location.search).get('game');room=['canada28','australia8','australia8ball'].includes(next)?next:'canada28';access=new URLSearchParams(location.hash.slice(1)).get('access')||'';await boot();}
window.addEventListener('popstate',restoreRoute);window.addEventListener('hashchange',restoreRoute);
setInterval(updateClock,1000);
setInterval(async()=>{if(!state||polling||busy||document.hidden)return;polling=true;try{await load();refreshPanel();}catch(e){notify(e.message,true);}finally{polling=false;}},2000);
boot();

function sumOddsPanel(){
  const labels={'番':'选中一番获胜，其余输','角':'相邻两番中任一获胜','念':'首号码赢，后号码和，其余输','无':'前号码赢，末号码输，其余和','双无':'前两个号码赢，末号码输，其余和','通':'首号码输，后两个号码赢，剩余号码和','正':'选中号码赢，对面号码输，相邻号码和','车':'选中三个号码中任一获胜，其余输','大/小':'和值0至13为小，14至27为大','单/双':'和值奇数为单，偶数为双','小单':'和值0至13且为奇数','小双':'和值0至13且为偶数','大单':'和值14至27且为奇数','大双':'和值14至27且为偶数'};
  return '<div class="notice">净盈利倍率：中奖返还本金，另加本金×倍率。留空的玩法暂未启用。</div><p>开奖为3个0至9的号码，和值范围0至27。和值0至13（含13）为小，和值14至27（含14）为大；奇数为单，偶数为双。小单、小双、大单、大双按大小与奇偶同时满足。这两个房间不支持特码下注。旧注单按提交时规则结算，旧开奖记录保留原规则。</p>'+table(['玩法','净盈利倍率','结算方式'],Object.entries(state.odds).filter(([k])=>!['大小单双','特'].includes(k)).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v==null?'未启用':esc(v)}</td><td>${esc(labels[k]||'')}</td></tr>`).join(''))+'<p class="note">示例：大10、小10、单10、双10、小单10、小双10、大单10、大双10、1番10。多条可用英文逗号、中文逗号或换行分隔，例如：12角100,12念100；12念100等同1念2/100。</p>';
}

// Display aliases never overwrite saved nicknames or identify betting accounts.
function frontNickname(value){
 const text=hideSimulatedLabels(value??'');
 return typeof Intl.Segmenter==='function'?[...new Intl.Segmenter('zh',{granularity:'grapheme'}).segment(text)].slice(0,2).map(x=>x.segment).join(''):Array.from(text).slice(0,2).join('');
}
function publicNameMap(){
 const names=new Set([state.user.nickname,...(state.ranking||[]).map(r=>r.nickname)]);
 for(const m of state.chat){if(m.username)names.add(m.who);for(const key of ['rows','winningOrders','closeOrders'])for(const row of m.details?.[key]||[])if(row.nickname)names.add(row.nickname);}
 return [...names].filter(n=>n&&frontNickname(n)!==hideSimulatedLabels(n)).sort((a,b)=>b.length-a.length);
}
function shortMessageNames(value,names){
 let text=hideSimulatedLabels(value);
 // Match nickname positions, never bare numeric strings in issues or bets.
 const aliases=names.map(hideSimulatedLabels).filter(Boolean);
 if(aliases.length){const escaped=aliases.map(n=>n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));const pattern=new RegExp('(^|[@(（])('+escaped.join('|')+')(?=[)）\\s，,:：]|上|下|\\[|$)','gm');text=text.replace(pattern,(_,prefix,name)=>prefix+frontNickname(name));}
 text=text.replace(/(^|\n)\(([^()\n]+)\)(?=\s*[“"第\d])/g,(_,prefix,name)=>prefix+'('+frontNickname(name)+')');
 text=text.replace(/@([^@\n，,：:]+?)(?=上分|下分| 上\d| 下\d|，| 已退| 攻击)/g,(_,name)=>'@'+frontNickname(name));
 text=text.replace(/(^|\n)([^\n[\]]+?)(?=\s+\[-?\d)/g,(_,prefix,name)=>prefix+frontNickname(name.trim()));
 return text;
}
function compactCloseBet(selection,amount,ballNumber){return (ballNumber?'第'+ballNumber+'球 ':'')+selection+(/\d$/.test(selection)?'/':'')+amount;}
function closeMessageHtml(message,names){
 const text=hideSimulatedLabels(message.content),saved=message.details?.closeFooter;
 let footer=typeof saved==='string'?hideSimulatedLabels(shortMessageNames(saved,names)):null;
 // Old messages predate footer snapshots; recognize the original fixed ending.
 if(footer===null){const marker='\n以系统注单记录和退单状态为准。\n',at=text.indexOf(marker);footer=at<0?'':text.slice(at+marker.length);}
 const at=footer?text.lastIndexOf(footer):-1;
 return at<0?esc(text):esc(text.slice(0,at))+'<span class="close-footer">'+esc(footer)+'</span>'+esc(text.slice(at+footer.length));
}
function publicCloseText(message){
 if(Array.isArray(message.details?.publicNameParts))message={...message,content:message.details.publicNameParts.map(part=>typeof part==='string'?part:frontNickname(part.nickname)).join('')};
 if(message.kind!=='HEDUI')return message.content;
 const d=message.details;
 if(d?.game===room&&Array.isArray(d.closeOrders)&&typeof d.closeList==='string'){
  const groups=new Map();for(const o of d.closeOrders){if(!groups.has(o.username))groups.set(o.username,{nickname:o.nickname,bets:[]});groups.get(o.username).bets.push(compactCloseBet(o.selection,cash(o.amount),room==='australia8'?o.ball:null));}
  const list=[...groups.values()].map(g=>'('+frontNickname(g.nickname)+') “'+g.bets.join(', ')+'”').join('\n')||'本期暂无注单';
  return String(message.content).split(d.closeList).join(list);
 }
 // Legacy text has no account IDs: group by the full original name before shortening.
 const lines=hideSimulatedLabels(message.content).split('\n'),groups=new Map();
 const parsed=lines.map(line=>{const match=line.match(/^\((.+)\)\s+(?:第([1-8])球\s+)?(.+)\/(\d+(?:\.\d+)?)$/);if(!match)return null;const [,name,ball,selection,amount]=match;if(!groups.has(name))groups.set(name,[]);groups.get(name).push(compactCloseBet(selection,amount,ball));return name;});
 const emitted=new Set();return lines.flatMap((line,index)=>{const name=parsed[index];if(name===null)return [line];if(emitted.has(name))return [];emitted.add(name);return ['('+frontNickname(name)+') “'+groups.get(name).join(', ')+'”'];}).join('\n');
}
