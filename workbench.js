/* Compact reference-layout workbench, backed by the unified room service. */
window.Workbench=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const cash=v=>(Number(v||0)/100).toLocaleString('zh-CN',{minimumFractionDigits:Number(v||0)%100===0?0:2,maximumFractionDigits:2});
 const labels={canada28:'加拿大PC番（本地）',australia8:'澳洲8番摊（本地）',australia8ball:'澳洲3（本地）'};
 const roomLabels={canada28:'加拿大28',australia8:'澳洲8',australia8ball:'澳洲3'};
 const balance=u=>u.balance??u.wallets?.canada28??0;
 let ctx,host,state,game='canada28',selected='',active=false,working=false,polling=false,interval,clock,sequence=0,query='',sort=false,detailDirty=false,memberLink='',linkRequest=0;
 const pending=new Map(),q=s=>host?.querySelector(s),users=()=>state?.users.filter(u=>u.role==='member'&&!u.deleted)||[],current=()=>users().find(u=>u.username===selected),id=u=>u.legacyId||'@'+u.username;
 const realUsers=()=>state?.users.filter(u=>u.role==='member'&&!u.robot)||[];
 // Use the current member identity, including orders placed before the identity changed.
 function realRecords(records){const names=new Set(realUsers().map(u=>u.username));return records.filter(row=>names.has(row.username));}
 const button=(action,label,more='')=>`<button type="button" data-wb="${action}" ${more}>${label}</button>`;
 const check=(key,label)=>`<label><input type="checkbox" data-pref="${key}" ${state.workbench[key]?'checked':''}>${label}</label>`;
 const field=(key,label,value,group='pref',options='')=>`<label>${label}<input class="small-input" type="number" data-${group}="${key}" value="${esc(value)}" aria-label="${label}" ${options}></label>`;
 function newRequestId(){
   if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
   const bytes=crypto.getRandomValues(new Uint8Array(16));
   bytes[6]=(bytes[6]&0x0f)|0x40;
   bytes[8]=(bytes[8]&0x3f)|0x80;
   const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
   return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
 }
 function attach(context){dispose();ctx=context;host=document.createElement('section');host.id='workbench-view';host.hidden=true;document.getElementById('app').appendChild(host);host.addEventListener('click',e=>click(e).catch(error));host.addEventListener('keydown',e=>{if(e.target.id==='wb-qr'&&e.key==='Enter')commandAction('qr').catch(error);});host.addEventListener('submit',e=>{e.preventDefault();submit(e).catch(error);});host.addEventListener('change',e=>change(e).catch(error));host.addEventListener('input',e=>{const tf=e.target.closest('#wb-a8-thresholds');if(tf){tf.dataset.dirty='1';tf.querySelector('[data-a8-status]').textContent='有未保存的修改';window.RoomAdmin.syncThresholdTime(tf);}if(e.target.id==='wb-member-search'){query=e.target.value;updateList();}if(e.target.closest('#wb-member-form'))detailDirty=true;});}
 function dispose(){clearInterval(interval);clearInterval(clock);active=false;sequence++;host?.remove();host=null;state=null;}
 function hide(){if((detailDirty||q('#wb-a8-thresholds')?.dataset.dirty==='1')&&!confirm('当前会员资料尚未保存，确定离开？'))return false;detailDirty=false;active=false;clearInterval(interval);clearInterval(clock);if(host)host.hidden=true;return true;}
 async function show(nextGame=game){game=labels[nextGame]?nextGame:game;active=true;host.hidden=false;await load();if(!active)return;render();history.replaceState(null,'','/admin');clearInterval(interval);clearInterval(clock);interval=setInterval(()=>{if(active&&!document.hidden&&!polling&&!working){polling=true;load().then(update).catch(error).finally(()=>polling=false);}},2500);clock=setInterval(tick,1000);}
 async function load(){const wanted=game,ticket=++sequence,data=await ctx.api('/api/rooms?game='+game);if(ticket!==sequence||wanted!==game)return;state=data;if(!users().some(u=>u.username===selected))selected=users().find(u=>u.legacyId)?.username||users()[0]?.username||'';}
 function error(e){ctx.toast(e.message,true);}
 function autoConfig(u,key=game){
  const limits=state.games[key],min=Math.max(limits.minBet,Math.min(100,limits.maxBet));
  return u.autoBet?.[key]||{enabled:false,amountMin:min,amountMax:Math.min(limits.maxBet,Math.max(min,1000)),selections:['1番','2番','3番','4番'],intervalSeconds:10,betsPerRound:3,ball:8};
 }
 function autoRooms(u){return Object.keys(roomLabels).filter(key=>autoConfig(u,key).enabled);}
 function autoSummary(u,key=game){const status=u.autoBetStatus?.[key],cfg=autoConfig(u,key);return (status?.message||(cfg.enabled?'等待运行':'未启用'))+(cfg.enabled&&status?' · 本期 '+status.count+'/'+cfg.betsPerRound+' 笔':'');}
 function autoOverview(u){const rooms=autoRooms(u);return rooms.length?rooms.map(key=>roomLabels[key]+'：'+autoSummary(u,key)).join('；'):'三个房间自动下注均已关闭';}
 function autoStatus(u){return Object.keys(roomLabels).map(key=>`<div><b>${roomLabels[key]}</b><span>${esc(autoSummary(u,key))}</span></div>`).join('');}
 function modalChange(form){
  if(form.dataset.kind!=='autobet'||!state)return;
  const rooms=[...form.querySelectorAll('[name="rooms"]:checked')].map(el=>el.value);
  const lower=rooms.length?Math.max(...rooms.map(key=>state.games[key].minBet)):1;
  const upper=rooms.length?Math.min(...rooms.map(key=>state.games[key].maxBet)):100000000;
  for(const name of ['amountMin','amountMax']){form.elements[name].min=Math.max(1,Math.ceil(lower/100));form.elements[name].max=Math.floor(upper/100);}
  form.querySelector('.wb-auto-limits').textContent=rooms.length?(lower<=upper?'所选房间共同限注：'+cash(lower)+' 至 '+cash(upper)+' 积分。':'所选房间限注没有交集，请调整房间或房间限注。'):'请选择至少一个房间后启用。';

 }
 function openAutoSettings(username){
  const u=users().find(v=>v.username===username);if(!u)throw Error('会员不存在，请刷新');
  const cfg=autoConfig(u),enabledRooms=autoRooms(u),selectedRooms=enabledRooms.length?enabledRooms:[game],canEnable=u.robot&&u.enabled;
  ctx.modal('自动下注设置 · '+id(u),`<form id="wb-modal-form" class="wb-auto-form" data-kind="autobet" novalidate>
   <input type="hidden" name="username" value="${esc(u.username)}"><input type="hidden" name="game" value="${game}">
   <fieldset class="wb-auto-rooms"><legend>选择自动下注房间（可多选）</legend>${Object.entries(roomLabels).map(([key,label])=>`<label><input type="checkbox" name="rooms" value="${key}" ${selectedRooms.includes(key)?'checked':''}><span>${label}</span></label>`).join('')}</fieldset>
   <hr>
   <p><b>${esc(u.nickname)}</b> · <span class="wb-auto-identity">${u.robot?'托（模拟用户）':'普通会员'} · ${u.enabled?'账号已启用':'账号已停用'}</span> · 共用积分 <b class="wb-auto-balance">${cash(balance(u))}</b></p>
   <div class="wb-auto-status" role="status">${autoStatus(u)}</div>
   <div class="wb-auto-activate" ${canEnable?'hidden':''}><p class="error">该账号已停用或尚未设为模拟用户。要自动下注，请明确勾选下面的账号设置。</p><label><input name="activateMember" type="checkbox" ${canEnable?'disabled':''}>同时启用账号并设为模拟用户（托）</label><small>保存后账号将可用；若此前停用，请重新领取专属链接。</small></div>
   <label class="wb-auto-switch"><input name="enabled" type="checkbox" ${enabledRooms.length&&canEnable?'checked':''}>启用所选房间自动下注（虚拟积分）</label>
   <p class="wb-auto-parameter-note">参数默认来自${roomLabels[game]}。点击保存后，下面同一组参数会应用到所有选中房间，未选房间的自动下注会关闭。关闭弹窗不会修改设置。</p>
   <div class="wb-auto-grid">
    <label>每笔最小积分<input name="amountMin" type="number" min="1" max="1000000" step="1" required value="${cfg.amountMin/100}"></label>
    <label>每笔最大积分<input name="amountMax" type="number" min="1" max="1000000" step="1" required value="${cfg.amountMax/100}"></label>
    <label>下注间隔（秒）<input name="intervalSeconds" type="number" min="5" max="3600" step="1" required value="${cfg.intervalSeconds}"></label>
    <label>每房间每期最多笔数<input name="betsPerRound" type="number" min="1" max="100" step="1" required value="${cfg.betsPerRound}"></label>
   </div>
   <small class="wb-auto-limits"></small>
   <label>随机投注选项<input name="selections" required maxlength="400" value="${esc(cfg.selections.join('，'))}" placeholder="1番，2番，3番，4番"></label>
   <small>每笔随机选一项，并在金额范围内随机取值。选项不填金额，用逗号分隔，例如：1番、12角、1念2、01特、大、双。</small>
   <input type="hidden" name="ball" value="8"><p class="muted">澳洲3按三个号码的和值取番，无需选择球位。</p>
   <p class="muted">保存启用后，服务器按间隔运行，关闭后台页面仍会继续。封盘、暂停时不会下注；托额度不足时自动上分1000～5000并自动审核通过；取消“托”或停用账号会停止自动下注。重新开关不会清零本期笔数。</p>
   <div class="wb-auto-actions"><button type="submit" class="admin-primary" value="save">保存全部房间设置</button><button type="submit" value="stop" formnovalidate ${enabledRooms.length?'':'disabled'}>停止所有房间自动下注</button></div>
  </form>`);
  modalChange(document.getElementById('wb-modal-form'));
 }
 function render(){if(!host||!state)return;const s=state.workbench,g=state.games[game];
 host.innerHTML=`<div class="local-note">本地工作台 · 前后台共用用户、积分和订单；房间规则与设置实时同步。<span id="wb-connection">已连接本地服务</span></div><main class="workspace">
 <aside class="left-column"><section class="panel registration"><div class="section-head">会员注册 / 登录</div><select id="wb-entry-select" aria-label="入口类型"><option value="personal">专属链接登录</option><option value="copy">复制当前用户专属链接</option><option value="create">后台创建会员</option><option value="manage">用户与专属链接管理</option></select><div><label><input type="checkbox" checked disabled>仅后台创建</label> <span id="wb-entry-user"></span></div><div class="wb-qr-area"><button id="wb-qr-button" class="wb-qr-button" type="button" data-wb="qr" aria-label="放大用户专属二维码" hidden><img id="wb-qr" alt="所选用户专属入口二维码"></button><span id="wb-qr-empty">选择会员后生成专属入口</span></div><a id="wb-entry-link" target="_blank" rel="noopener noreferrer">${esc(location.origin)}/portal</a><small>每位会员使用独立专属链接，请勿转发给他人。</small></section>
 <section class="panel bet-panel"><div class="section-head"><b>下注榜：</b><span id="wb-round-label"></span></div><div class="order-controls">${button('new-order','录入本地订单')}${button('next-round','下一期')}${button('orders','历史订单')}</div><div id="wb-orders" class="order-list"></div></section>
 <section class="panel command"><div class="section-head">指令查询</div><form id="wb-command-form"><input name="command" placeholder="统计 / 会员 ID / 帮助" aria-label="查询指令" required><button>查询</button></form><pre id="wb-command-result">输入“帮助”查看支持的本地指令。</pre></section></aside>
 <section class="center-column"><section class="panel reporting"><div class="section-head">本地模拟上报通道</div><div class="report-toolbar">${check('autoReport','自动上报')}<select aria-label="上报通道" disabled><option>本地模拟通道</option></select>${check('failCancel','失败撤单')}${check('errorCancel','异常撤单')}${button('report-logs','报网日志')}</div><div class="report-state"><b id="wb-report-status"></b>${button('connect',s.reportConnected?'断开模拟通道':'连接模拟通道','id="wb-connect"')}<p>无需网址、账号或密码。仅修改本地订单的模拟上报状态。</p><small>“异常撤单”保留设置；没有外部异常事件时不会自动触发。</small></div></section>
 <section class="panel config"><div class="game-row"><b>当前游戏：</b><select id="wb-game" aria-label="当前游戏">${Object.entries(labels).map(([k,v])=>`<option value="${k}" ${k===game?'selected':''}>${v}</option>`).join('')}</select><b>当前状态：</b>${button('open','开盘','id="wb-open" class="green"')}${field('rate','赔率：',g.odds['番'],'config','min="0.0001" max="100" step="0.0001"')}${button('odds','1赔X')}<label>开奖：<select id="wb-mode" aria-label="开奖方式">${Object.entries({simulation:'本地模拟开奖',manual:'手动录入开奖',external:'外部开奖接口'}).map(([k,v])=>`<option value="${k}" ${k===g.mode?'selected':''}>${v}</option>`).join('')}</select></label></div>
 <div class="settings-row">${check('hideSuccess','隐藏下注成功信息')}${check('showBegin','显示开始进攻')}　限注：${field('maxBet','最大',g.maxBet/100,'config','min="0.01" max="1000000" step="0.01"')}${field('minBet','最小',g.minBet/100,'config','min="0.01" max="1000000" step="0.01"')}</div>
 <div class="settings-row">${field('closeSeconds','预留封盘：',g.closeSeconds,'config','min="0" max="3599"')}秒 ${field('delay','延报：',s.delay,'pref','min="0" max="3600"')}${field('noExt','免抽：',s.noExt,'pref','min="0" max="3600"')}${field('rebate','返水：',s.rebate,'pref','min="0" max="100"')}% <span class="muted">更改后自动保存</span></div>${game==='australia8'?`<form id="wb-a8-thresholds" class="wb-a8-thresholds"><b>澳洲8 · 三段分时限额</b>${window.RoomAdmin.thresholdFields(g)}<div class="a8-threshold-save"><span data-a8-status>配置已保存</span><button type="submit">保存三段限额</button></div></form>`:''}<small class="config-note">赔率、限注和封盘同步房间；延报 / 免抽 / 返水保留参数，不改变结算规则。</small></section>
 <section class="panel requests"><div class="section-head"><b>上下分确认（全部房间）：</b>${button('sound','声音'+s.audio,'id="wb-sound"')}${button('new-request','添加本地申请')}<span id="wb-request-count"></span></div><div id="wb-requests"></div></section>
 <section class="panel scores"><div class="section-head"><b>积分榜：</b>${button('sort','刷新积分排序')}${button('clear-stats','全部流水清空')}${button('clear-data','一键清除数据')}${button('alarm','报警')}${button('ledger','积分记录')}${button('accounting','总盈亏')}${button('balances','余分','id="wb-summary"')}</div><div class="member-tools"><input id="wb-member-search" aria-label="搜索会员" placeholder="搜索 ID / 昵称" value="${esc(query)}"><span class="muted">托：模拟用户；机：选择房间并设置自动下注</span></div><div class="member-area"><div id="wb-members" class="member-list"></div><aside id="wb-detail" class="member-detail"></aside></div></section></section></main>`;
 update();renderDetail();showLink();}
 function update(){if(!host||!active||!state)return;updateList();renderAccountingRows();renderBalances();const requests=state.requests.filter(r=>r.status==='待审核');q('#wb-request-count').textContent=requests.length+' 笔待处理';q('#wb-requests').innerHTML=requests.map(r=>`<div class="request-row"><span>${esc(r.username)}：<b>${esc(r.action)} ${cash(r.amount)}</b> <small>〔${esc(roomLabels[r.game]||r.game)}〕</small></span><button data-review="${esc(r.id)}" data-approve="true">同意</button><button data-review="${esc(r.id)}" data-approve="false">取消</button></div>`).join('')||'<p class="empty">暂无上下分申请</p>';
 let orders=realRecords(state.orders).filter(o=>o.game===game&&o.issue===state.round.issue);q('#wb-round-label').textContent=`${state.round.issue} 期（${orders.length} 单）`;q('#wb-orders').innerHTML=orders.map(o=>`<article class="order-row"><small>${esc(o.id)} · ${esc(o.username)}${o.simulated?' · 模拟用户':''}${o.source==='simulated-auto'?' · 自动下注':''}</small><div>${game==='australia8'?'第'+(o.ball??8)+'球 · ':''}${esc(o.selection)}　<b>${cash(o.amount)}</b></div><span class="badge">${esc(o.status)}</span> <span>${esc(o.report||'未上报')}</span>${o.status==='待开奖'?`<div class="order-actions"><button data-cancel="${esc(o.id)}">撤单</button><button data-report="${esc(o.id)}">模拟重发</button><button data-report-fail="${esc(o.id)}">模拟失败</button></div>`:''}</article>`).join('')||'<p class="empty">暂无本期订单<br>前台提交后在此同步显示</p>';
 q('#wb-summary').title='查看所有真实用户余分';
 const u=current();if(u&&q('#wb-current-avatar'))q('#wb-current-avatar').innerHTML=globalThis.AvatarLibrary?.render(u.avatar)||esc(u.avatar);if(u&&q('#wb-selected-balance')){q('#wb-selected-balance').textContent=cash(balance(u));}
 if(u&&q('#wb-member-kind')){q('#wb-member-kind').textContent=u.robot?'身份：托（模拟用户）':'身份：普通会员';q('#wb-member-auto').textContent=autoOverview(u);}
 const autoForm=document.querySelector('#wb-modal-form[data-kind="autobet"]');
 if(autoForm&&autoForm.elements.game.value===game){
  const target=users().find(member=>member.username===autoForm.elements.username.value);
  if(target){
   autoForm.querySelector('.wb-auto-status').innerHTML=autoStatus(target);
   autoForm.querySelector('.wb-auto-balance').textContent=cash(balance(target));
   autoForm.querySelector('.wb-auto-identity').textContent=(target.robot?'托（模拟用户）':'普通会员')+' · '+(target.enabled?'账号已启用':'账号已停用');
   const allowed=target.robot&&target.enabled;
   autoForm.querySelector('.wb-auto-activate').hidden=allowed;autoForm.elements.activateMember.disabled=allowed;
   autoForm.querySelector('[value="stop"]').disabled=!autoRooms(target).length||!!autoForm.dataset.saving;
  }
 }
 const prefs=state.workbench;q('#wb-report-status').textContent=prefs.reportConnected?'已连接':'未连接';q('#wb-connect').textContent=prefs.reportConnected?'断开模拟通道':'连接模拟通道';q('#wb-sound').textContent='声音'+prefs.audio;
 const g=state.games[game],tf=q('#wb-a8-thresholds');if(tf&&tf.dataset.dirty!=='1'){const r=g.a8Thresholds||{};tf.elements.a8_middle_start.value=r.middleSwitchSeconds??r.switchSeconds;tf.elements.a8_final_start.value=r.finalSwitchSeconds??(g.period-g.closeSeconds);tf.elements.a8_first.value=r.firstMax/100;tf.elements.a8_middle.value=(r.middleMax??r.secondMax)/100;tf.elements.a8_final.value=r.finalTotal==null?'':r.finalTotal/100;window.RoomAdmin.syncThresholdTime(tf);}const b=q('#wb-open');b.textContent=g.paused?'收盘':state.round.closed?'封盘':'开盘';b.className=g.paused||state.round.closed?'red':'green';
 host.querySelectorAll('[data-pref]').forEach(el=>{if(el===document.activeElement)return;el.type==='checkbox'?el.checked=!!prefs[el.dataset.pref]:el.value=prefs[el.dataset.pref];});
 host.querySelectorAll('[data-config]').forEach(el=>{if(el===document.activeElement)return;const k=el.dataset.config;el.value=k==='rate'?g.odds['番']:k==='minBet'||k==='maxBet'?g[k]/100:g[k];});
 if(q('#wb-mode')!==document.activeElement)q('#wb-mode').value=g.mode;tick();}
 function updateList(){if(!state||!q('#wb-members'))return;let list=users().filter(u=>[u.username,u.nickname,u.legacyId,u.remark].join(' ').toLowerCase().includes(query.toLowerCase()));list.sort(sort?(a,b)=>balance(b)-balance(a):(a,b)=>Number(!a.legacyId)-Number(!b.legacyId));q('#wb-members').innerHTML=list.map(u=>`<div class="member-row ${u.username===selected?'selected':''} ${u.enabled?'':'pending'}"><button class="mark ${u.robot?'active':''}" data-mark="robot" data-user="${esc(u.username)}" aria-label="切换 ${esc(id(u))} 托标记" aria-pressed="${!!u.robot}" title="${u.robot?'模拟用户（托）':'普通会员'}">托</button><button class="mark ${autoRooms(u).length?'active':''}" data-mark="auto" data-user="${esc(u.username)}" aria-label="设置 ${esc(id(u))} 自动下注" aria-pressed="${!!autoRooms(u).length}" title="${esc(autoOverview(u))}">机</button><button class="member-select" data-select="${esc(u.username)}"><b>${esc(id(u))}.${esc(u.nickname)}${u.robot?' <em class="wb-sim-tag">托</em>':''}：</b><span>${cash(balance(u))}</span>${u.enabled?'':'<em>停用</em>'}</button><button class="delete" data-disable="${esc(u.username)}">${u.enabled?'停用':'启用'}</button><button class="delete" data-delete-member="${esc(u.username)}">删除</button></div>`).join('')||'<p class="empty">暂无会员</p>';}
 function renderDetail(){detailDirty=false;const u=current();q('#wb-detail').innerHTML=`${button('create','创建会员')}${u?`<div class="avatar" id="wb-current-avatar">${globalThis.AvatarLibrary?.render(u.avatar)||esc(u.avatar)}</div><b>修改积分</b><div>会员ID：${esc(id(u))}</div><div id="wb-member-kind">${u.robot?'身份：托（模拟用户）':'身份：普通会员'}</div><small id="wb-member-auto">${esc(autoOverview(u))}</small><button type="button" data-mark="auto" data-user="${esc(u.username)}">自动下注设置</button><form id="wb-member-form">${globalThis.AvatarLibrary?.picker(u.avatar)||''}<label>昵称：<input name="nickname" value="${esc(u.nickname)}" required maxlength="20"></label><label>备注：<input name="remark" value="${esc(u.remark)}" maxlength="200"></label><label>返水：<input name="rebate" type="number" min="0" max="100" step="0.01" value="${u.rebate||0}" title="会员一键回水百分比，例如1表示1%；修改后保存"></label><button>修改</button></form><p>共用积分：<b id="wb-selected-balance">${cash(balance(u))}</b></p><form id="wb-balance-form"><label class="inline"><input type="radio" name="action" value="上分">上分</label><label class="inline"><input type="radio" name="action" value="下分" checked>下分</label><input name="amount" type="number" min="0.01" max="1000000" step="0.01" aria-label="积分变动金额" required><button>确认</button></form>`:'<p class="empty">创建或选择会员<br>管理资料和积分</p>'}`;}
 async function showLink(){const u=current(),ticket=++linkRequest;memberLink='';q('#wb-qr-button').hidden=true;q('#wb-qr-empty').hidden=false;q('#wb-entry-link').removeAttribute('href');q('#wb-entry-user').textContent=u?id(u):'';if(!u||!u.enabled){q('#wb-qr-empty').textContent=u?'用户已停用':'选择会员后生成专属入口';return;}q('#wb-qr-empty').textContent='正在生成专属入口…';try{const r=await ctx.api('/api/rooms/member-link?username='+encodeURIComponent(u.username));if(ticket!==linkRequest||!active)return;memberLink=r.url;q('#wb-qr').src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(r.svg);q('#wb-qr-button').hidden=false;q('#wb-qr-empty').hidden=true;q('#wb-entry-link').href=r.url;q('#wb-entry-link').textContent=location.origin+'/portal · '+id(u);}catch(e){if(ticket===linkRequest&&q('#wb-qr-empty'))q('#wb-qr-empty').textContent=e.message;}}
 function tick(){const el=q('#wb-connection');if(el&&state){const sec=Math.max(0,Math.ceil(state.round.endAt-Date.now()/1000));el.textContent='已连接本地服务 · '+(state.round.paused?'房间已暂停':state.round.closed?'已封盘，等待开奖':'本期剩余 '+sec+' 秒');}}
 async function act(operation,data={},targetGame=game){if(working)return false;working=true;const key=JSON.stringify([operation,targetGame,data]);if(!pending.has(key))pending.set(key,newRequestId());const buttons=[...host.querySelectorAll('button')];buttons.forEach(b=>{b.dataset.disabled=String(b.disabled);b.disabled=true;});try{const r=await ctx.api('/api/rooms/action',{operation,game:targetGame,data:{...data,requestId:pending.get(key)}});pending.delete(key);await load();update();ctx.toast(r.message||'已保存');return r;}finally{working=false;buttons.forEach(b=>b.disabled=b.dataset.disabled==='true');}}
 function table(head,rows){return `<div class="table-scroll"><table><thead><tr>${head.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>'<tr>'+row.map(v=>`<td>${esc(v)}</td>`).join('')+'</tr>').join('')||`<tr><td colspan="${head.length}">暂无记录</td></tr>`}</tbody></table></div>`;}
 async function openBalances(){
  await load();if(!active)return;update();
  ctx.modal('余分',`<section id="wb-balances"><p>三个房间共用余额，仅统计真实用户（含停用用户）。</p><div class="wb-account-toolbar"><input id="wb-balance-search" placeholder="搜索 ID / 账号 / 昵称" aria-label="搜索余分用户"><button type="button" id="wb-balance-refresh">刷新</button><button type="button" id="wb-clear-balances" class="danger">一键清除余分</button></div><p id="wb-balance-total"></p><div id="wb-balance-rows"></div></section>`);
  document.getElementById('wb-balance-search').addEventListener('input',renderBalances);
  document.getElementById('wb-balance-refresh').addEventListener('click',async()=>{try{await load();update();}catch(e){error(e);}});
  document.getElementById('wb-clear-balances').addEventListener('click',async()=>{
   if(!confirm('确定清除所有会员的共享余分吗？此操作会先自动备份，并保留清零前后的账本审计记录。待开奖订单或待审核申请存在时不会执行。'))return;
   try{await act('workbench.balances.clear');await load();update();renderBalances();}catch(e){error(e);}
  });
  renderBalances();
 }
 function renderBalances(){
  const body=document.getElementById('wb-balance-rows');if(!body||!body.closest('dialog')?.open)return;
  const all=realUsers(),needle=document.getElementById('wb-balance-search').value.trim().toLowerCase();
  const rows=all.filter(u=>[u.username,id(u),u.nickname].join(' ').toLowerCase().includes(needle)).sort((a,b)=>balance(b)-balance(a));
  document.getElementById('wb-balance-total').textContent=`真实用户 ${all.length} 人 · 余分合计 ${cash(all.reduce((n,u)=>n+balance(u),0))}${needle?' · 当前筛选 '+rows.length+' 人，余分 '+cash(rows.reduce((n,u)=>n+balance(u),0)):''}`;
  body.innerHTML=table(['会员ID','账号','昵称','余分','状态'],rows.map(u=>[id(u),u.username,u.nickname,cash(balance(u)),u.deleted?'已删除':u.enabled?'启用':'停用']));
 }
 let accountScope='',accountSearch='',accountDate='all',accountData=null;
 const accountingBack=()=>'<button type="button" class="wb-account-back" data-account-back>‹ 返回总盈亏</button>';
 const accountDay=value=>String(value||'').slice(0,10);
 function accountDates(){
  const dates=new Set();
  for(const item of realRecords((accountData?.orders||[]).concat(accountData?.ledger||[],accountData?.requests||[]))){
   const day=accountDay(item.time);if(/^\d{4}-\d{2}-\d{2}$/.test(day))dates.add(day);
  }
  return [...dates].sort().reverse();
 }
 function accountMatches(item){return accountDate==='all'||accountDay(item.time)===accountDate;}
 function accountOrders(){return realRecords(accountData?.orders||[]).filter(o=>(accountScope==='all'||o.game===accountScope)&&accountMatches(o));}
 function orderEffectiveTurnover(o){
  const amount=Number.isSafeInteger(o.amount)?Math.max(0,o.amount):0;
  if(o.status==='未中')return amount;
  if(o.status!=='中奖')return 0;
  const profit=Number.isSafeInteger(o.profit)?Math.max(0,o.profit):0,selection=String(o.selection||'');
  if(['大','小','单','双','小单','小双','大单','大双'].includes(selection))return amount;
  if(/^(?:[1-4]{2}无[1-4]|[1-4]通[1-4]{2})$/.test(selection))return Math.floor((amount+1)/2);
  if(/^[1-4]{1,3}车$/.test(selection))return Math.floor((amount+1)/3);
  if(/^(?:[1-4]{1,3}(?:番|正)|[1-4]{2}角|[1-4]念[1-4]{1,2}|[1-4]无[1-4])$/.test(selection))return Math.min(amount,profit+Math.floor((amount+10)/20));
  return profit;
 }
 function accountSummary(){
  const orders=accountOrders(),valid=orders.filter(o=>['中奖','未中','和局'].includes(o.status)),active=orders.filter(o=>o.status!=='已退单');
  const ledger=realRecords(accountData?.ledger||[]).filter(l=>(accountScope==='all'||l.game===accountScope)&&accountMatches(l));
  const rebate=ledger.filter(l=>l.source==='rebate'||/返水|回水/.test(String(l.reason||''))).reduce((n,l)=>n+(Number(l.delta)||0),0);
  const requests=realRecords(accountData?.requests||[]).filter(r=>(accountScope==='all'||r.game===accountScope)&&accountMatches(r));
  const reported=orders.filter(o=>o.report&&o.report!=='模拟失败').length,failed=orders.filter(o=>o.report==='模拟失败').length;
  return {orders,active,valid,turnover:active.reduce((n,o)=>n+(Number(o.amount)||0),0),validTurnover:orders.reduce((n,o)=>n+orderEffectiveTurnover(o),0),profit:active.reduce((n,o)=>n+(Number(o.profit)||0),0),rebate,requests,reported,failed,unreported:orders.length-reported-failed};
 }
 function renderAccountingSummary(){
  const days=document.getElementById('wb-account-days'),summary=document.getElementById('wb-account-summary');if(!days||!summary)return;
  const dates=accountDates();if(accountDate!=='all'&&!dates.includes(accountDate))accountDate=dates[0]||'all';
  days.innerHTML=`<button type="button" class="wb-account-date ${accountDate==='all'?'selected':''}" data-account-date="all">全部日期</button>${dates.slice(0,7).map(day=>`<button type="button" class="wb-account-date ${accountDate===day?'selected':''}" data-account-date="${day}">${day}</button>`).join('')}`;
  const s=accountSummary(),current=realUsers().reduce((n,u)=>n+balance(u),0),approved=s.requests.filter(r=>r.status==='已通过'||r.status==='同意').length,unapproved=s.requests.filter(r=>r.status==='待审核').length;
  summary.innerHTML=`<div class="wb-account-summary-line"><span>总盈亏：<b class="${s.profit<0?'negative':'positive'}">${s.profit>0?'+':''}${cash(s.profit)}</b></span><span>总流水：<b>${cash(s.turnover)}</b></span><span>总有效流水：<b>${cash(s.validTurnover)}</b></span><span>合计总返水：<b>${cash(s.rebate)}</b></span></div><div class="wb-account-summary-line"><span>当前积分对账：<b>${cash(current)}</b></span><span>统计周期：<b>0点—${accountDate==='all'?'当前':accountDate}</b></span><span>已报：<b>${s.reported}</b></span><span>未报：<b>${s.unreported}</b></span><span>失败：<b>${s.failed}</b></span><span>上下分：<b>${approved}-${unapproved}</b></span></div>`;
 }
 async function openAccounting(reset=true){
  if(reset){accountScope=game;accountSearch='';}
  await load();accountData=await ctx.api('/api/rooms/export?game='+game);
  if(!active)return;
  const dates=accountDates();if(reset)accountDate=dates[0]||'all';
  ctx.modal('总盈亏',`<section id="wb-accounting"><div id="wb-account-days" class="wb-account-days"></div><div id="wb-account-summary" class="wb-account-summary"></div><div class="wb-account-toolbar"><label>统计范围 <select id="wb-account-scope"><option value="all">三个房间合计</option>${Object.entries(roomLabels).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><input id="wb-account-search" placeholder="搜索账号 / 昵称" aria-label="搜索真实会员"><button type="button" data-account-refresh>刷新</button></div><p class="wb-account-note">仅显示真实会员（含停用会员）。总流水按成功下注金额统计，退单和取消单不计；有效流水：输单计本金；大/小、单/双、小单/小双、大单/大双结算后输赢均计本金；番、角、念、无、正中奖计净盈利加本金5%，不超过本金；双无、通中奖计本金一半，车中奖计本金三分之一（四舍五入到分）；其他玩法中奖仍计净盈利。和局、待开奖及退单不计。返水按有效流水和已记录的回水账本统计。</p><div id="wb-account-rows" class="wb-account-members"></div><p id="wb-account-total"></p></section>`);
  const scope=document.getElementById('wb-account-scope'),search=document.getElementById('wb-account-search');
  scope.value=accountScope;search.value=accountSearch;
  scope.addEventListener('change',()=>{accountScope=scope.value;renderAccountingRows();});
  search.addEventListener('input',()=>{accountSearch=search.value;renderAccountingRows();});
  bindAccountingActions();renderAccountingRows();
 }
 function renderAccountingRows(){
  const body=document.getElementById('wb-account-rows');if(!body||!body.closest('dialog')?.open)return;renderAccountingSummary();
  const needle=accountSearch.trim().toLowerCase();
  const rows=realUsers().filter(u=>[u.username,id(u),u.nickname].join(' ').toLowerCase().includes(needle));
  const orders=accountOrders(),ledger=realRecords(accountData?.ledger||[]).filter(l=>(accountScope==='all'||l.game===accountScope)&&accountMatches(l));let total=0,profit=0,totalRebate=0;
  body.innerHTML=rows.map(u=>{
   const mine=orders.filter(o=>o.username===u.username),active=mine.filter(o=>o.status!=='已退单'),rebate=ledger.filter(l=>l.username===u.username&&(l.source==='rebate'||/返水|回水/.test(String(l.reason||'')))).reduce((n,l)=>n+(Number(l.delta)||0),0),turnover=active.reduce((n,o)=>n+(Number(o.amount)||0),0),effective=mine.reduce((n,o)=>n+orderEffectiveTurnover(o),0),memberProfit=active.reduce((n,o)=>n+(Number(o.profit)||0),0),scoreChange=realRecords(accountData?.requests||[]).filter(r=>r.username===u.username&&(accountScope==='all'||r.game===accountScope)&&accountMatches(r)&&r.status==='已通过').reduce((n,r)=>n+(r.action==='上分'?Number(r.amount)||0:-(Number(r.amount)||0)),0);
   total+=turnover;profit+=memberProfit;totalRebate+=rebate;
   return `<article class="wb-account-member" data-account-user="${esc(u.username)}"><div class="wb-account-member-head"><b>会员ID：${esc(id(u))}，昵称：${esc(u.nickname)}</b><span>当前积分：<b>${cash(balance(u))}</b></span></div><div class="wb-account-member-stats">总流水：${cash(turnover)}　有效流水：${cash(effective)}　总盈亏：<strong class="${memberProfit<0?'negative':'positive'}">${memberProfit>0?'+':''}${cash(memberProfit)}</strong>　已返水：${cash(rebate)}　上下分：${cash(scoreChange)}</div><div class="wb-account-actions"><button type="button" data-account-ledger="${esc(u.username)}">该会员记录</button><button type="button" data-account-rebate="${esc(u.username)}">一键返水</button></div></article>`;
  }).join('')||'<tr><td colspan="5">暂无符合条件的真实会员</td></tr>';
  document.getElementById('wb-account-total').textContent=`当前列表 ${rows.length} 位会员 · 总流水 ${cash(total)} · 总盈亏 ${profit>0?'+':''}${cash(profit)} · 总已返水 ${cash(totalRebate)}`;
 }
 function bindAccountingActions(){
  document.getElementById('admin-dialog').addEventListener('click',async e=>{
   const b=e.target.closest('button');if(!b||working||b.disabled)return;
   try{
    if(b.hasAttribute('data-account-date')){accountDate=b.dataset.accountDate||'all';renderAccountingRows();return;}
    if(b.hasAttribute('data-account-back')||b.hasAttribute('data-account-refresh')){await openAccounting(false);return;}
    const username=b.dataset.accountLedger||b.dataset.accountRebate;if(!username)return;
    const user=users().find(u=>u.username===username&&!u.robot);if(!user)throw Error('会员身份已变化，请刷新列表');
    if(b.dataset.accountLedger)await ledger(username,true);
    else await openRebate(username,true);
   }catch(err){error(err);}
  });
 }
 let rebateLoading=false;
 async function openRebate(username=selected,fromAccounting=false){
  if(rebateLoading)return;
  if(detailDirty)throw Error('请先点击“修改”保存会员资料，再计算回水');
  if(!username)throw Error('请先选择会员');
  rebateLoading=true;
  try{
   const plan=await ctx.api('/api/rooms/member-rebate-preview?username='+encodeURIComponent(username));
   if(!active||(!fromAccounting&&username!==selected))return;
   const canPay=plan.count>0&&plan.amount>0&&Number(plan.rate)>0;
   ctx.modal('一键返水 · 三个房间合计',`${fromAccounting?accountingBack():''}<form id="wb-modal-form" data-kind="rebate" data-accounting="${fromAccounting}"><input type="hidden" name="username" value="${esc(plan.username)}"><input type="hidden" name="fingerprint" value="${esc(plan.fingerprint)}"><p><b>${esc(plan.nickname)}</b>（${esc(plan.username)}） · 已保存返水比例 <b>${esc(plan.rate)}%</b></p>${table(['房间','已结算未回水笔数','有效流水'],Object.entries(plan.rooms).map(([key,row])=>[roomLabels[key],row.count,cash(row.turnover)]))}<p>合计流水：<b>${cash(plan.turnover)}</b> × ${esc(plan.rate)}%<br>本次回水：<b>${cash(plan.amount)} 积分</b>（四舍五入至0.01）</p><p>首次包含现存符合条件的历史注单。仅计已结算且未回水的下注，排除退单、待开奖和迁入旧单；页面统计清零不影响回水记录。</p><p>确认后计入会员共用积分，并记录在“该会员记录”；同一注单只回水一次。</p>${canPay?'':'<p class="error">'+(Number(plan.rate)<=0?'请先在会员资料设置返水比例并保存。':!plan.count?'暂无已结算且未回水的注单。':'回水不足0.01积分，流水将保留待累计。')+'</p>'}<button type="submit" class="admin-primary" ${canPay?'':'disabled'}>确认发放 ${cash(plan.amount)} 积分</button></form>`);
   if(fromAccounting)bindAccountingActions();
  }finally{rebateLoading=false;}
 }
 async function ledger(user,fromAccounting=false){const data=await ctx.api('/api/rooms/export?game='+game),actions=user?`<div class="wb-ledger-footer"><button type="button" data-account-rebate="${esc(user)}">一键返水</button></div>`:'';ctx.modal(user?'该会员共用积分记录':'全部房间积分记录',(fromAccounting?accountingBack():'')+table(['时间','会员','来源房间','原因','变动','记录余额','余额类型'],data.ledger.filter(l=>!user||l.username===user).reverse().map(l=>[l.time,l.username,roomLabels[l.game]||l.game||'账户',l.reason,cash(l.delta),cash(l.balance),l.walletScope==='shared'?'共用积分':'历史房间积分']))+actions);if(fromAccounting)bindAccountingActions();}
 function options(){return users().filter(u=>u.enabled).map(u=>`<option value="${esc(u.username)}" ${u.username===selected?'selected':''}>${esc(id(u))} ${esc(u.nickname)}</option>`).join('');}
 function openForm(kind){const common=`<label>会员<select name="username">${options()}</select></label>`;const bodies={create:`${globalThis.AvatarLibrary?.picker()||''}<label>账号<input name="username" pattern="[A-Za-z0-9_]{3,32}" required maxlength="32"></label><label>昵称<input name="nickname" required maxlength="20"></label><label>返水（%）<input name="rebate" type="number" min="0" max="100" step="0.01" value="0.8" required></label><label>初始共用积分<input name="amount" type="number" min="0" max="1000000" step="0.01" value="0" required></label><p>由后台创建，并生成该用户专属前台链接。</p>`,order:common+`<label>玩法指令<input name="text" required placeholder="例如 1番10，12角5"></label><p>使用当前房间真实规则扣分、封盘和结算；前台同步显示。</p>`,request:common+'<label>类型<select name="action"><option>上分</option><option>下分</option></select></label><label>积分<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required></label>'};ctx.modal({create:'创建会员',order:'录入本地订单',request:'添加本地积分申请'}[kind],`<form id="wb-modal-form" data-kind="${kind}">${bodies[kind]}<button type="submit">确认</button></form>`);}
 async function modalSubmit(form,submitter){
  if(form.dataset.saving)return;form.dataset.saving='true';
  const buttons=[...form.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
  try{
   const data=Object.fromEntries(new FormData(form)),kind=form.dataset.kind;
   if(kind==='rebate'){
    if(await act('workbench.rebate',{username:data.username,fingerprint:data.fingerprint,confirmed:true})){if(form.dataset.accounting==='true')await openAccounting(false);else ctx.closeModal();}
    return;
   }
   if(kind==='autobet'){
    if(data.game!==game)throw Error('当前房间已变化，请重新打开设置');
    const enabled=submitter?.value!=='stop'&&form.elements.enabled.checked;
    const rooms=[...form.querySelectorAll('[name="rooms"]:checked')].map(el=>el.value);
    const target=users().find(u=>u.username===data.username),activateMember=!!form.elements.activateMember?.checked;
    if(enabled){
     if(!rooms.length)throw Error('请至少选择一个自动下注房间');
     if(!target)throw Error('会员不存在，请刷新后重试');
     if((!target.enabled||!target.robot)&&!activateMember)throw Error('请勾选“同时启用账号并设为模拟用户（托）”后再保存');
     if(!form.reportValidity())return;
     if(Number(data.amountMin)>Number(data.amountMax))throw Error('每笔最小积分不能大于最大积分');
    }
    const payload=enabled?{
     username:data.username,rooms,enabled:true,...(activateMember&&!form.elements.activateMember.disabled?{activateMember:true}:{}),
     amountMin:data.amountMin,amountMax:data.amountMax,selections:data.selections.split(/[,，、\s]+/).filter(Boolean),
     intervalSeconds:Number(data.intervalSeconds),betsPerRound:Number(data.betsPerRound),ball:Number(data.ball)
    }:{username:data.username,rooms:[],enabled:false};
    if(await act('member.autobet.batch',payload)){ctx.closeModal();if(data.username===selected)await showLink();}
    return;
   }
   const r=await act({create:'member.create',order:'workbench.order',request:'workbench.request'}[kind],data);
   if(r){ctx.closeModal();if(kind==='create'){selected=r.username;updateList();renderDetail();await showLink();}}
  }finally{delete form.dataset.saving;buttons.forEach((b,i)=>b.disabled=disabled[i]);}
 }
 async function click(e){const b=e.target.closest('button,[data-wb]');if(!b||working)return;
 if(b.dataset.select){if((detailDirty||q('#wb-a8-thresholds')?.dataset.dirty==='1')&&!confirm('放弃未保存的会员资料并切换？'))return;selected=b.dataset.select;updateList();renderDetail();await showLink();return;}
 if(b.dataset.mark){const u=users().find(u=>u.username===b.dataset.user);if(!u)return;if(b.dataset.mark==='auto'){openAutoSettings(u.username);return;}await act('member.edit',{username:u.username,robot:!u.robot});return;}
 if(b.dataset.deleteMember){const u=users().find(u=>u.username===b.dataset.deleteMember);if(!u)return;if(!confirm('删除用户“'+u.nickname+'”？删除后该用户无法进入前台，历史注单、余额和账本保留供对账。'))return;await act('member.delete',{username:u.username});renderDetail();await showLink();return;}if(b.dataset.disable){const u=users().find(u=>u.username===b.dataset.disable);if(confirm(u.enabled?'停用后该用户所有旧链接立即失效，历史账本保留。确定停用？':'重新启用此用户？启用后请领取新链接。')){await act('member.edit',{username:u.username,enabled:!u.enabled});await showLink();}return;}
 if(b.dataset.review){const request=state.requests.find(r=>r.id===b.dataset.review);if(!request)throw Error('申请已变化，请刷新后重试');await act('review',{id:request.id,approve:b.dataset.approve==='true'},request.game);return;}
 if(b.dataset.cancel){await act('workbench.cancel',{id:b.dataset.cancel});return;}
 if(b.dataset.report||b.dataset.reportFail){await act('workbench.report',{id:b.dataset.report||b.dataset.reportFail,fail:!!b.dataset.reportFail});return;}
 await commandAction(b.dataset.wb);}
 async function commandAction(action){switch(action){case 'qr':if(memberLink)ctx.modal('用户专属入口',`<div style="text-align:center"><img src="${q('#wb-qr').src}" width="320" height="320" alt="完整用户专属二维码"><p><a href="${esc(memberLink)}" target="_blank" rel="noopener noreferrer">打开此用户前台</a></p><p>请仅向对应用户提供专属链接，可在首页入口菜单复制完整链接。</p></div>`);break;case 'connect':await act('workbench.save',{reportConnected:!state.workbench.reportConnected});break;case 'open':if(state.round.closed&&!state.round.paused)ctx.openRoom('draw',game);else await act('config',{paused:!state.round.paused});break;case 'odds':ctx.openRoom('config',game);break;case 'next-round':ctx.openRoom('draw',game);break;case 'orders':ctx.openRoom('orders',game);break;case 'user-manage':ctx.openRoom('members',game);break;case 'create':openForm('create');break;case 'new-order':openForm('order');break;case 'new-request':openForm('request');break;case 'sort':sort=!sort;await load();updateList();break;case 'ledger':await ledger();break;case 'accounting':await openAccounting();break;case 'balances':await openBalances();break;case 'member-ledger':await ledger(selected);break;case 'member-rebate':await openRebate();break;case 'clear-stats':if(confirm('清零当前房间本页显示的流水和盈亏？历史订单、积分账本及前台累计记录不会删除。'))await act('workbench.stats.reset');break;case 'clear-data':if(confirm('确定清除三间房的历史订单、上下分申请、开奖历史、聊天和统计吗？会员、房间配置、当前余分及账本会保留。执行前自动备份；有待开奖订单或待审核申请时不会执行。'))await act('workbench.data.clear');break;case 'sound':await act('workbench.save',{audio:state.workbench.audio%3+1});sound();break;case 'alarm':sound();ctx.toast('提醒已播放；待处理申请 '+state.requests.filter(r=>r.status==='待审核').length+' 笔');break;case 'copy-link':if(!memberLink)throw Error('请先选择已启用的会员');try{await navigator.clipboard.writeText(memberLink);ctx.toast('专属链接已复制');}catch{ctx.modal('复制专属链接',`<input style="width:100%" value="${esc(memberLink)}" readonly><p>选中后按 Ctrl+C 复制。</p>`);}break;case 'logs':ctx.modal('当前房间消息',table(['时间','用户','消息'],state.chat.slice(-100).reverse().map(m=>[m.time,m.who,m.content])));break;case 'report-logs':ctx.modal('本地模拟上报记录',table(['期号','会员','内容','积分','上报状态'],state.orders.filter(o=>o.game===game).map(o=>[o.issue,o.username,o.selection,cash(o.amount),o.report||'未上报'])));break;case 'export':{const a=document.createElement('a');a.href='/api/rooms/export?game='+game;a.download='room-records.json';a.click();break;}}}
 function sound(){try{const Audio=window.AudioContext||window.webkitAudioContext,a=new Audio(),osc=a.createOscillator(),gain=a.createGain();osc.frequency.value=500+state.workbench.audio*150;gain.gain.value=.06;osc.connect(gain);gain.connect(a.destination);osc.start();osc.stop(a.currentTime+.2);osc.onended=()=>a.close();}catch{}}
 async function change(e){const el=e.target;if(working)return;if(el.id==='wb-entry-select'){if(el.value==='copy')await commandAction('copy-link');if(el.value==='create')openForm('create');if(el.value==='manage')ctx.openRoom('members',game);el.value='personal';return;}if(el.id==='wb-game'){if((detailDirty||q('#wb-a8-thresholds')?.dataset.dirty==='1')&&!confirm('放弃未保存的会员资料并切换房间？')){el.value=game;return;}game=el.value;await load();render();return;}if(el.id==='wb-mode'){try{await act('config',{mode:el.value});}catch(e){el.value=state.games[game].mode;throw e;}return;}if(el.dataset.pref)await act('workbench.save',{[el.dataset.pref]:el.type==='checkbox'?el.checked:Number(el.value)});if(el.dataset.config){if(!el.checkValidity()){el.reportValidity();return;}const key=el.dataset.config;const data=key==='rate'?{odds:{...state.games[game].odds,'番':Number(el.value)}}:{[key]:Number(el.value)};await act('config',data);}}
 async function submit(e){const f=e.target,d=Object.fromEntries(new FormData(f));if(f.id==='wb-a8-thresholds'){if(await act('config',{a8Thresholds:window.RoomAdmin.thresholdData(f)})){f.dataset.dirty='0';f.querySelector('[data-a8-status]').textContent='配置已保存';update();}return;}if(f.id==='wb-member-form'){if(await act('member.edit',{...d,username:selected})){detailDirty=false;updateList();await showLink();}}if(f.id==='wb-balance-form'){if(await act('score',{...d,username:selected}))f.reset();}if(f.id==='wb-command-form'){const raw=d.command.trim(),u=users().find(u=>[u.username,u.nickname,id(u)].includes(raw.replace(/^会员\s+/,'')));q('#wb-command-result').textContent=raw==='帮助'?'支持：统计、期号、订单、会员账号 / ID / 昵称':raw==='统计'?`会员 ${users().length} 人\n积分 ${cash(users().reduce((n,u)=>n+balance(u),0))}\n待开奖 ${state.pendingCount} 单`:raw==='期号'?state.round.issue:raw==='订单'?state.orders.filter(o=>o.game===game).slice(0,10).map(o=>`${o.username} ${game==='australia8'?'第'+(o.ball??8)+'球 ':''}${o.selection} ${cash(o.amount)} ${o.status}`).join('\n')||'暂无订单':u?`${id(u)} ${u.nickname}\n积分 ${cash(balance(u))}\n流水 ${cash(state.memberStats[u.username]?.turnover)}`:'未找到，输入“帮助”查看指令。';}}
 async function openRobot(target=game){
  if(!await ctx.ensureRoomAccess())return;
  const snapshot=await ctx.api('/api/rooms?game='+encodeURIComponent(target)+'&view=protected'),config=snapshot.robotConfig;
  if(!config)throw Error('请刷新后台后重试');
  let phase='';
  const cards=config.entries.map((entry,index)=>{
   const heading=phase!==entry.phase?`<h3 class="robot-phase">${esc(entry.phase)}</h3>`:'';phase=entry.phase;
   return heading+`<details class="robot-message-card" data-template="${esc(entry.key)}" ${index===0?'open':''}><summary>${index+1}. ${esc(entry.title)}</summary><label class="robot-enable"><input type="checkbox" data-enabled ${entry.enabled?'checked':''}>发送这条回复</label><textarea data-text rows="4" maxlength="2000" aria-label="${esc(entry.title)}回复内容">${esc(entry.text)}</textarea><div class="robot-tokens">自动填入：${Object.keys(entry.sample).map(token=>`<button type="button" data-token="${esc(token)}">{${esc(token)}}</button>`).join('')}</div><button type="button" data-reset="${esc(entry.key)}">恢复本条默认</button><small>示例预览（金额和昵称仅供预览）</small><pre data-preview></pre>${entry.key==='draw'?'<p class="muted">默认保留现有开奖图。自定义此条后按编辑的文字发送。</p>':''}</details>`;
  }).join('');
  ctx.modal('机器人回复设置',`<form id="robot-settings-form" class="robot-settings"><div class="robot-toolbar"><label>房间<select data-robot-room>${Object.entries(roomLabels).map(([key,label])=>`<option value="${key}" ${key===target?'selected':''}>${label}</option>`).join('')}</select></label><label>机器人名称<input name="robotName" maxlength="20" required value="${esc(config.name)}"></label><label><input name="robotEnabled" type="checkbox" ${config.bot?'checked':''}>机器人总开关</label></div><p>按开奖到封盘的流程排列；下注、退单、上下分回复在对应操作发生时发送。三个房间分别保存，保存后用于新消息。</p><p class="muted">花括号中的内容会自动替换成真实数据。关闭回复只停止播报，下注、结算和审核仍正常执行。</p>${cards}<div class="robot-save"><span data-status>当前设置已加载</span><button type="submit" class="admin-primary">保存本房间设置</button></div></form>`);
  const form=document.getElementById('robot-settings-form'),dialog=form.closest('dialog');let dirty=false,saving=false,retry=null;
  dialog.classList.add('robot-dialog');
  function changed(){dirty=true;retry=null;form.querySelector('[data-status]').textContent='有未保存的修改';}
  function preview(card){
   const entry=config.entries.find(row=>row.key===card.dataset.template),value=card.querySelector('[data-text]').value;
   const unknown=[...value.matchAll(/\{([^{}]+)\}/g)].map(m=>m[1]).filter(token=>!(token in entry.sample));
   card.querySelector('[data-preview]').textContent=!card.querySelector('[data-enabled]').checked?'此条已关闭，不会发送':unknown.length?'未知占位符：'+unknown.join('、'):value.replace(/\{([^{}]+)\}/g,(_,token)=>entry.sample[token]);
  }
  form.querySelectorAll('[data-template]').forEach(preview);
  form.addEventListener('input',event=>{if(event.target.matches('[data-robot-room]'))return;changed();const card=event.target.closest('[data-template]');if(card)preview(card);});
  form.addEventListener('change',async event=>{
   if(event.target.matches('[data-robot-room]')){
    if(dirty&&!confirm('当前房间有未保存的回复，放弃修改并切换房间？')){event.target.value=target;return;}
    event.target.disabled=true;
    try{await openRobot(event.target.value);}catch(e){event.target.value=target;event.target.disabled=false;error(e);}return;
   }
   changed();const card=event.target.closest('[data-template]');if(card)preview(card);
  });
  form.addEventListener('click',event=>{
   const b=event.target.closest('[data-token],[data-reset]');if(!b||saving)return;
   const card=b.closest('[data-template]'),textarea=card.querySelector('[data-text]');
   if(b.hasAttribute('data-token')){textarea.setRangeText('{'+b.dataset.token+'}',textarea.selectionStart,textarea.selectionEnd,'end');textarea.focus();}
   else{textarea.value=config.entries.find(row=>row.key===b.dataset.reset).default;card.querySelector('[data-enabled]').checked=true;}
   changed();preview(card);
  });
  function preventClose(event){if(saving||(dirty&&!confirm('放弃未保存的机器人回复修改？'))){event.preventDefault();event.stopImmediatePropagation();}}
  dialog.addEventListener('cancel',preventClose);
  dialog.querySelector('[data-close-dialog]').addEventListener('click',preventClose);
  form.addEventListener('submit',async event=>{
   event.preventDefault();if(saving)return;
   const entries={};form.querySelectorAll('[data-template]').forEach(card=>{entries[card.dataset.template]={enabled:card.querySelector('[data-enabled]').checked,text:card.querySelector('[data-text]').value};});
   const data={revision:config.revision,bot:form.elements.robotEnabled.checked,name:form.elements.robotName.value,entries};
   const fingerprint=JSON.stringify(data);if(!retry||retry.fingerprint!==fingerprint)retry={fingerprint,id:newRequestId()};
   saving=true;const controls=[...form.querySelectorAll('button,input,textarea,select')];controls.forEach(el=>el.disabled=true);
   try{
    const result=await ctx.api('/api/rooms/action',{operation:'robot.messages.save',game:target,data:{...data,requestId:retry.id}});
    dirty=false;ctx.toast(result.message);await openRobot(target);
   }catch(e){form.querySelector('[data-status]').textContent=e.message;error(e);}
   finally{saving=false;controls.forEach(el=>el.disabled=false);}
  });
 }
 return {attach,dispose,hide,show,openRobot,action:commandAction,modalSubmit,modalChange,get game(){return game;},get active(){return active;}};
})();
