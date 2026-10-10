

'use strict';
const app=document.getElementById('app');
let state, role=null, selected='', sortBalance=false, query='', busy=false, refreshBusy=false, timer, countdownTimer;
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>(Number(v||0)/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const time=v=>new Date(v).toLocaleString('zh-CN',{hour12:false});
function toast(message,error=false){let e=document.getElementById('notice');e.textContent=message;e.className=error?'notice error':'notice';e.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>e.hidden=true,4200);}
async function api(url,data){let res=await fetch(url,{credentials:'same-origin',signal:AbortSignal.timeout(10000),headers:data?{'Content-Type':'application/json'}:{},method:data?'POST':'GET',body:data?JSON.stringify(data):undefined}),v=await res.json();if(!res.ok) {if(res.status===401&&url!=='/api/login'){role=null;loginView();}throw Error(v.message||'请求失败');}return v;}
async function action(name,data={}){if(busy)return;busy=true;try{let r=await api(role==='member'?'/api/player':'/api/action',{action:name,...data});if(name==='password.change'){role=null;closeModal();loginView();toast('本地密码已修改，请重新登录');return r;}await refresh(true);return r;}finally{busy=false;}}
function check(k,label){return `<label><input type="checkbox" data-setting="${k}" ${state.settings[k]?'checked':''}>${label}</label>`;}
function field(k,label,suffix=''){return `<label>${label}<input class="small-input" type="number" data-setting="${k}" value="${h(state.settings[k])}" aria-label="${label}">${suffix}</label>`;}
function button(action,label,more=''){return `<button data-action="${action}" ${more}>${label}</button>`;}
function memberOptions(){return state.members.map(m=>`<option value="${h(m.id)}" ${selected===m.id?'selected':''}>${h(m.id)} ${h(m.name)}</option>`).join('');}
function loginView(){window.RoomAdmin?.dispose();clearInterval(timer);clearInterval(countdownTimer);app.innerHTML=`<div class="login-page"><form id="login-form" class="login-box"><h1>本地用户中心</h1><p class="muted">独立本地服务 · 虚拟积分</p><label>用户名：<input name="username" autocomplete="username" required value="localadmin"></label><label>密　码：<input name="password" type="password" autocomplete="current-password" required></label><div class="login-actions"><button type="submit">登 录</button><a href="/register">注册会员</a></div><p id="login-error" class="error" role="alert"></p><small>管理员账号：localadmin<br>请使用设置的管理员密码登录。</small></form></div>`;}
function registerView(){app.innerHTML=`<div class="login-page"><form id="register-form" class="login-box"><h1>本地会员注册</h1><label>账　号：<input name="username" pattern="[A-Za-z0-9_]{3,32}" required autocomplete="username"></label><label>昵　称：<input name="name" required maxlength="80"></label><label>密　码：<input name="password" type="password" minlength="4" maxlength="128" autocomplete="new-password" required></label><button type="submit">注册本地会员</button><p id="register-message" role="status"></p><a href="/player">返回登录</a><p class="muted">数据只保存在本机；注册后按设置由管理员审核。</p></form></div>`;}
function dashboard(){
 let s=state.settings;
 app.innerHTML=`<header class="tophead"><div><b class="warning">本地独立版 · 仅虚拟积分</b>，欢迎您：<b>${h(state.username)}</b>，数据：<b>本机文件</b>　${button('password','修改密码')} ${button('logout','退出登录')}</div><nav>${button('open-register','注册入口')} ${button('ledger','积分记录')} ${button('logs','消息日志')} ${button('export','导出数据')} ${button('help','功能说明')}<span class="room-nav-group"><button data-action="room-admin" id="room-admin-entry">房间后台 <span>3</span></button><button data-action="workbench" id="workbench-entry" hidden>返回工作台</button></span></nav></header>
 <div class="local-note">依据已读取的前端结构复刻。外部上报为本地模拟；结算使用手动返还金额，不代表原站算法。<span id="connection-state">已连接本地服务</span></div>
 <main class="workspace">
 <aside class="left-column">
  <section class="panel registration"><div class="section-head">会员注册 / 登录</div><select aria-label="入口类型" id="entry-type"><option value="register">注册登录</option><option value="player">会员登录</option></select><div>${check('review','注册审核')}</div><a href="/register" target="_blank" rel="noopener" id="registration-link"><img src="/register-qr.svg" width="148" height="148" alt="本地注册入口二维码"></a><a href="/register" id="entry-link" target="_blank" rel="noopener">${h(location.origin)}/register</a><small>仅本机可访问；此二维码不是手机联网入口。</small></section>
  <section class="panel bet-panel"><div class="section-head"><b>下注榜：</b><span id="round-label"></span></div><div class="order-controls">${button('new-order','录入本地订单')} ${button('next-round','下一期')} ${button('all-orders','历史订单')}</div><div id="order-list" class="order-list"></div></section>
  <section class="panel command"><div class="section-head">指令查询</div><form id="command-form"><input name="command" placeholder="统计 / 会员 ID / 帮助" aria-label="查询指令" required><button>查询</button></form><pre id="command-result">输入“帮助”查看支持的本地指令。</pre></section>
 </aside>
 <section class="center-column">
  <section class="panel reporting"><div class="section-head">本地模拟上报通道</div><div class="report-toolbar">${check('autoReport','自动上报')} <select aria-label="上报通道" disabled><option>本地模拟通道</option></select> ${check('failCancel','失败撤单')} ${check('errorCancel','异常撤单')} ${button('report-logs','报网日志')}</div><div class="report-state"><b id="report-status">${s.reportConnected?'已连接':'未连接'}</b> ${button('connect',s.reportConnected?'断开模拟通道':'连接模拟通道')}<p>无需网址、账号或密码。仅修改本地订单的模拟上报状态。</p><small>“异常撤单”保留设置；没有原站异常判定逻辑，不会自动推断。</small></div></section>
  <section class="panel config"><div class="game-row"><b>当前游戏：</b><select aria-label="当前游戏"><option>加拿大PC番（本地）</option></select><b>当前状态：</b>${button('open',s.open?'开盘':'收盘',`class="${s.open?'green':'red'}"`)} ${field('odd','赔率：')} ${button('odds','1赔X')}<label>开奖：<select data-setting="place" aria-label="开奖方式"><option value="1" ${s.place==='1'?'selected':''}>后两位相拼</option><option value="2" ${s.place==='2'?'selected':''}>三位数相加</option></select></label></div><div class="settings-row">${check('hideSuccess','隐藏下注成功信息')} ${check('showBegin','显示开始进攻')}　限注：${field('maxBet','最大')} ${field('minBet','最小')}</div><div class="settings-row">${field('reserve','预留封盘：','秒')} ${field('delay','延报：')} ${field('noExt','免抽：')} ${field('rebate','返水：','%')}<span class="muted">更改后自动保存</span></div><small class="config-note">赔率/返水/延报等保留配置，不据此自动计算原站结算。</small></section>
  <section class="panel requests"><div class="section-head"><b>上下分确认：</b>${button('sound','声音'+s.audio)} ${button('new-request','添加本地申请')}<span id="request-count"></span></div><div id="request-list"></div></section>
  <section class="panel scores"><div class="section-head"><b>积分榜：</b>${button('sort','刷新积分排序')} ${button('clear-turnover','全部流水清空')} ${button('alarm','报警')} ${button('ledger','积分记录')}<span id="summary"></span></div><div class="member-tools"><input id="member-search" aria-label="搜索会员" placeholder="搜索 ID / 昵称" value="${h(query)}"><span class="muted">托 / 机为本地标记，未接原站自动下注计划</span></div><div class="member-area"><div id="member-list" class="member-list"></div><aside id="member-detail" class="member-detail"></aside></div></section>
 </section>
 </main>`;
 renderLive();renderDetail();tick();window.RoomAdmin.attach({api,toast});
}
function renderLive(){if(!state||role!=='admin')return;
 let members=state.members.filter(m=>(m.id+' '+m.name+' '+m.remark).toLowerCase().includes(query.toLowerCase()));if(sortBalance)members.sort((a,b)=>b.balance-a.balance);
 document.getElementById('member-list').innerHTML=members.map(m=>`<div class="member-row ${selected===m.id?'selected':''} ${!m.approved?'pending':''}" data-member="${h(m.id)}"><button class="mark ${m.robot?'active':''}" data-toggle-member="robot" data-id="${h(m.id)}" aria-label="切换 ${h(m.id)} 托标记">托</button><button class="mark ${m.auto?'active':''}" data-toggle-member="auto" data-id="${h(m.id)}" aria-label="切换 ${h(m.id)} 机标记">机</button><button class="member-select" data-select="${h(m.id)}" title="流水 ${money(m.turnover)} / 盈亏 ${money(m.profit)}"><b>${h(m.id)}.${h(m.name)}：</b><span>${money(m.balance)}</span>${!m.approved?' <em>待审核</em>':''}</button><button class="delete" data-delete="${h(m.id)}">删除</button></div>`).join('')||'<p class="empty">暂无会员</p>';
 let requests=state.requests.filter(r=>r.state==='待处理');document.getElementById('request-count').textContent=requests.length+' 笔待处理';
 document.getElementById('request-list').innerHTML=requests.map(r=>`<div class="request-row"><span>${h(r.member)}：<b>${h(r.direction)} ${money(r.amount)}</b>（${h(r.name)}）</span><button data-resolve="${h(r.id)}" data-accept="true">同意</button><button data-resolve="${h(r.id)}" data-accept="false">取消</button></div>`).join('')||'<p class="empty">暂无上下分申请</p>';
 let orders=state.orders.filter(o=>o.term===state.round.term);document.getElementById('round-label').textContent=`本地 ${state.round.term} 期（${orders.length} 单）`;
 document.getElementById('order-list').innerHTML=orders.map(o=>`<article class="order-row"><small>${h(o.id)} · ${h(o.member)} · ${h(o.name)}</small><div>${h(o.content)}　<b>${money(o.amount)}</b></div><span class="badge ${o.state==='已撤销'?'muted':''}">${h(o.state)}</span> <span>${h(o.report)}</span>${o.state==='待结算'?`<div class="order-actions"><button data-cancel="${h(o.id)}">撤单</button><button data-report="${h(o.id)}">模拟重发</button><button data-settle="${h(o.id)}">手动结算</button><button data-report-fail="${h(o.id)}">模拟失败</button></div>`:''}</article>`).join('')||'<p class="empty">暂无本期订单<br>点击“录入本地订单”进行本地演示</p>';
 document.getElementById('summary').textContent=`${state.members.length} 人　积分 ${money(state.members.reduce((s,m)=>s+m.balance,0))}`;
 const current=state.members.find(m=>m.id===selected),bal=document.getElementById('selected-balance');if(current&&bal)bal.textContent=money(current.balance);
}
function renderDetail(){const host=document.getElementById('member-detail');if(!host)return;let m=state.members.find(m=>m.id===selected);host.innerHTML=`${button('create-member','创建会员')}${m?`<button class="avatar" data-action="avatar" title="切换本地头像">${['🙂','🌼','🌱','🌞','🌊','🐱','🍀','🌙','⭐','🌸','🐼','🌈'][m.avatar%12]}</button><b>修改积分</b><div>会员ID：${h(m.id)}</div>${m.login?`<small>登录账号：${h(m.login)}</small>`:''}<form id="member-form"><label>昵称：<input name="name" value="${h(m.name)}" required maxlength="80"></label><label>备注：<input name="remark" value="${h(m.remark)}" maxlength="200"></label><label>返水：<input name="rebate" type="number" min="0" max="100" step="0.01" value="${m.rebate}"></label><button>修改</button></form>${!m.approved?button('approve','审核通过'):''}<p>积分：<b id="selected-balance">${money(m.balance)}</b></p><form id="balance-form"><label class="inline"><input type="radio" name="direction" value="上分">上分</label><label class="inline"><input type="radio" name="direction" value="下分" checked>下分</label><input name="amount" type="number" min="0.01" step="0.01" required aria-label="积分变动金额"><button>确认</button></form><small>流水：${money(m.turnover)}<br>盈亏：${money(m.profit)}</small><div>${button('member-ledger','该会员记录')}</div>`:'<p class="empty">从左侧选择会员<br>查看资料和修改积分</p>'}`;}
function tick(){let el=document.getElementById('connection-state');if(!el||!state)return;let sec=Math.max(0,Math.ceil((state.round.endsAt-Date.now())/1000));el.textContent=`已连接本地服务 · ${sec>0?'本期剩余 '+sec+' 秒':'本期时间已到，等待手动处理/下一期'}`;}
async function refresh(full=false){if(refreshBusy){if(!full)return;await new Promise(resolve=>setTimeout(resolve,30));return refresh(full);}refreshBusy=true;try{if(role==='admin'){state=await api('/api/state');if(full||!document.getElementById('member-list'))dashboard();else renderLive();}else if(role==='member'){state=await api('/api/player');if(full)playerView();} }finally{refreshBusy=false;}}
function modal(title,body){const root=document.getElementById('modal-root');root.innerHTML=`<div class="modal-shade"><section class="modal" role="dialog" aria-modal="true" aria-label="${h(title)}"><header><b>${h(title)}</b><button data-close aria-label="关闭弹窗">×</button></header><div class="modal-body">${body}</div></section></div>`;root.querySelector('input,button')?.focus();}
function closeModal(){document.getElementById('modal-root').innerHTML='';}
function table(headers,rows){return `<div class="table-scroll"><table><thead><tr>${headers.map(x=>`<th>${h(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(c=>`<td>${h(c)}</td>`).join('')}</tr>`).join('')||`<tr><td colspan="${headers.length}">暂无记录</td></tr>`}</tbody></table></div>`;}
function showLedger(filter){let rows=state.ledger.filter(r=>!filter||r.member===filter);modal('积分记录',table(['时间','会员','操作','变动','操作后余额','关联编号'],rows.map(r=>[time(r.time),r.member+' '+r.name,r.reason,money(r.delta),money(r.balance),r.ref])));}
function showOrders(){modal('历史订单',table(['编号','本地期','会员','内容','金额','状态','返还'],state.orders.map(o=>[o.id,o.term,o.member,o.content,money(o.amount),o.state,o.payout===null?'—':money(o.payout)])));}
function orderForm(){modal('录入本地订单',`<form id="order-form"><label>会员<select name="memberId">${memberOptions()}</select></label><label>内容<input name="content" required maxlength="200" placeholder="填写本地演示内容"></label><label>金额<input name="amount" type="number" min="${state.settings.minBet}" max="${state.settings.maxBet}" step="0.01" required value="${state.settings.minBet}"></label><p class="muted">提交后扣除虚拟积分；撤单退回。结算由本地手动输入返还金额。</p><button>确认录入</button></form>`);}
function requestForm(){modal('添加本地积分申请',`<form id="request-form"><label>会员<select name="memberId">${memberOptions()}</select></label><label>类型<select name="direction"><option>上分</option><option>下分</option></select></label><label>金额<input type="number" name="amount" min="0.01" step="0.01" required></label><button>提交申请</button></form>`);}
function help(){modal('功能范围与运行说明',`<h3>已经实现的本地功能</h3><p>管理员登录、会员注册审核、资料修改、上下分申请及审核、积分账本、订单录入/撤销/手动结算、流水统计、设置持久化、日志、查询、数据导出、修改本地密码。</p><h3>房间后台</h3><p>顶部“房间后台”包含三个独立房间，支持房间设置、开奖控制、公告消息、会员积分及注单记录。房间引擎支持本地自动结算与机器人播报，数据保存在 data/rooms/state.json，与原工作台积分分别保存。</p><h3>原工作台与原站的差异</h3><p>仅取得原站前端结构，未取得原站后端、CSS 原文件、结算公式、开奖来源、机器人计划、盘口协议。当前是相近布局与本地业务流程，不能保证像素或全部业务规则一致。</p><p>托/机开关是资料标记；没有自动产生订单。赔率、延报、免抽、返水等为持久化配置，不参与未确认的原站结算。外部上报只有本地模拟成功/失败。公众号二维码、外部消息发送和真实盘口不接入。</p><p>本地期为 180 秒；时间到达后停止录入，处理完订单后手动进入下一期。手动返还额包含本金，不根据赔率自动计算。</p><p>数据存入 <code>data/database.json</code>；重新启动服务后保留。导出不含密码。仅监听本机 127.0.0.1。</p>`);}
function playerView(){let m=state.member;app.innerHTML=`<header class="tophead"><b>本地会员中心 · ${h(m.name)}</b>${button('logout','退出登录')}</header><main class="player-page"><h2>虚拟积分：${money(m.balance)}</h2><p>${h(m.id)} · 本地 ${state.round.term} 期</p><section class="panel"><div class="section-head">上分 / 下分申请</div><form id="player-request"><select name="direction" aria-label="请求类型"><option>上分</option><option>下分</option></select><input name="amount" type="number" min="0.01" step="0.01" aria-label="申请积分" required><button>提交</button></form></section><section class="panel"><div class="section-head">本地订单录入</div><form id="player-order"><input name="content" placeholder="内容" required><input name="amount" type="number" min="${state.settings.minBet}" max="${state.settings.maxBet}" step="0.01" aria-label="订单金额" required><button>提交</button></form><p class="muted">仅虚拟积分，已到期时需管理员进入下一本地期。</p></section><h3>我的请求</h3>${table(['编号','类型','金额','状态'],state.requests.map(r=>[r.id,r.direction,money(r.amount),r.state]))}<h3>我的订单</h3>${table(['编号','内容','金额','状态'],state.orders.map(o=>[o.id,o.content,money(o.amount),o.state]))}${button('player-refresh','刷新')}</main>`;}
async function onClick(e){const target=e.target.closest('button,a[data-action]');if(!target)return;
 if(target.hasAttribute('data-close')){closeModal();return;}
 if(target.dataset.select){selected=target.dataset.select;renderLive();renderDetail();return;}
 if(target.dataset.toggleMember){let m=state.members.find(m=>m.id===target.dataset.id);await action('member.edit',{memberId:m.id,[target.dataset.toggleMember]:!m[target.dataset.toggleMember]});return;}
 if(target.dataset.delete){if(confirm('删除这个本地会员？只有零积分且无待处理事项的会员可以删除。'))await action('member.delete',{memberId:target.dataset.delete});return;}
 if(target.dataset.resolve){await action('request.resolve',{id:target.dataset.resolve,accept:target.dataset.accept==='true'});toast('请求已处理');return;}
 if(target.dataset.cancel){if(confirm('撤销本地订单并退还虚拟积分？'))await action('order.cancel',{id:target.dataset.cancel});return;}
 if(target.dataset.report||target.dataset.reportFail){await action('order.report',{id:target.dataset.report||target.dataset.reportFail,fail:!!target.dataset.reportFail});return;}
 if(target.dataset.settle){modal('本地手动结算',`<form id="settle-form"><input type="hidden" name="id" value="${h(target.dataset.settle)}"><p>输入实际返还虚拟积分（含本金）。此处不使用原站结算规则。</p><label>返还积分<input name="payout" type="number" min="0" step="0.01" value="0" required></label><button>确认本地结算</button></form>`);return;}
 switch(target.dataset.action){
 case 'room-admin':await window.RoomAdmin.open();break;
 case 'workbench':window.RoomAdmin.hide();break;
 case 'logout':await api('/api/logout',{});role=null;loginView();break;
 case 'help':help();break;
 case 'sort':sortBalance=true;renderLive();break;
 case 'ledger':showLedger();break;
 case 'member-ledger':showLedger(selected);break;
 case 'logs':case 'report-logs':{let ls=state.logs.filter(l=>target.dataset.action==='logs'||l.action.includes('上报'));modal('操作日志',table(['时间','操作','详情'],ls.map(l=>[time(l.time),l.action,l.detail])));break;}
 case 'export':{let a=document.createElement('a');a.href='/api/export';a.download='local-center-export.json';a.click();break;}
 case 'new-order':orderForm();break;
 case 'new-request':requestForm();break;
 case 'all-orders':showOrders();break;
 case 'open-register':modal('本地注册 / 登录入口',`<p><a href="/register" target="_blank" rel="noopener">打开本地会员注册</a></p><p><a href="/player" target="_blank" rel="noopener">打开本地会员登录</a></p><p>审核与积分由管理员管理。不同浏览器配置可分别登录管理员和会员。</p>`);break;
 case 'connect':await action('settings.save',{reportConnected:!state.settings.reportConnected});break;
 case 'open':await action('settings.save',{open:!state.settings.open});break;
 case 'next-round':await action('round.next');toast('已开始下一本地期');break;
 case 'clear-turnover':if(confirm('清空本地流水/盈亏统计？积分与历史账本保留。'))await action('turnover.clear');break;
 case 'create-member':modal('创建本地会员',`<form id="create-form"><label>昵称<input name="name" required maxlength="80"></label><label>初始积分<input name="amount" type="number" min="0" step="0.01" value="0"></label><label><input name="robot" type="checkbox">托标记</label><button>创建</button></form>`);break;
 case 'approve':await action('member.edit',{memberId:selected,approved:true});break;
 case 'avatar':await action('member.edit',{memberId:selected,avatar:true});break;
 case 'password':modal('修改本地管理员密码',`<form id="password-form"><label>旧密码<input name="oldPassword" type="password" autocomplete="current-password" required></label><label>新密码<input name="newPassword" type="password" minlength="4" maxlength="128" autocomplete="new-password" required></label><label>确认密码<input name="confirmPassword" type="password" minlength="4" autocomplete="new-password" required></label><button>修改本地密码</button></form>`);break;
 case 'odds':modal('赔率 / 结算说明',`<p>当前赔率配置：${h(state.settings.odd)}。</p><p>原站“1赔X”详情和计算规则未取得。当前不自动套用此配置，订单由“手动结算”输入返还总额。</p>`);break;
 case 'sound':await action('settings.save',{audio:state.settings.audio%3+1});beep();break;
 case 'alarm':beep();toast('本地报警提示');break;
 case 'player-refresh':await refresh(true);break;
 }
}
async function onSubmit(e){e.preventDefault();let f=e.target,data=Object.fromEntries(new FormData(f));
 switch(f.getAttribute('id')){
 case 'login-form':{let result=await api('/api/login',data);role=result.role;history.replaceState(null,'',role==='admin'?(location.pathname==='/admin'?'/admin':'/user-center'):'/player');await refresh(true);startTimers();break;}
 case 'register-form':{let r=await api('/api/register',data);document.getElementById('register-message').textContent=r.approved?'注册成功，可登录本地会员中心。':'注册成功，请管理员在积分榜选择该会员并审核。';f.reset();break;}
 case 'member-form':await action('member.edit',{memberId:selected,...data});toast('会员资料已保存');break;
 case 'balance-form':await action('balance.change',{memberId:selected,...data});toast('积分和账本已更新');break;
 case 'create-form':{let r=await action('member.create',{...data,robot:data.robot==='on'});if(r){selected=r.id;renderLive();renderDetail();closeModal();toast('会员已创建');}break;}
 case 'order-form':case 'player-order':await action('order.create',data);closeModal();toast('本地订单已录入');break;
 case 'request-form':case 'player-request':await action('request.create',data);closeModal();toast('申请已提交');break;
 case 'settle-form':await action('order.settle',data);closeModal();toast('本地订单已结算');break;
 case 'password-form':if(data.newPassword!==data.confirmPassword)throw Error('两次密码不一致');await action('password.change',data);break;
 case 'command-form':{let r=await api('/api/command',data);document.getElementById('command-result').textContent=r.result;break;}
 }
}
function beep(){const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext)return;let ctx=new AudioContext(),osc=ctx.createOscillator(),gain=ctx.createGain();osc.frequency.value=440+(state?.settings?.audio||1)*110;gain.gain.value=.07;osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+.2);osc.onended=()=>ctx.close();}
function handleError(err){toast(err.message,true);const label=document.getElementById('login-error');if(label)label.textContent=err.message;}
document.addEventListener('click',e=>{onClick(e).catch(handleError);if(e.target.classList.contains('modal-shade'))closeModal();});
document.addEventListener('submit',e=>onSubmit(e).catch(handleError));
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
document.addEventListener('input',e=>{if(e.target.id==='member-search'){query=e.target.value;renderLive();}});
document.addEventListener('change',e=>{let el=e.target;if(el.dataset.setting)action('settings.save',{[el.dataset.setting]:el.type==='checkbox'?el.checked:el.value}).then(()=>toast('设置已保存')).catch(async err=>{handleError(err);await refresh(true);});if(el.id==='entry-type'){let a=document.getElementById('entry-link'),p=el.value==='player'?'/player':'/register';a.href=p;a.textContent=location.origin+p;document.getElementById('registration-link').href=p;document.getElementById('registration-link').hidden=p==='/player';}});
function startTimers(){clearInterval(timer);clearInterval(countdownTimer);timer=setInterval(()=>{if(role==='admin'&&!document.hidden&&!busy)refresh().catch(err=>{let e=document.getElementById('connection-state');if(e)e.textContent='本地连接中断：'+err.message;});},3000);countdownTimer=setInterval(tick,1000);}
async function init(){document.body.insertAdjacentHTML('beforeend','<div id="modal-root"></div><div id="notice" class="notice" role="status" hidden></div>');if(location.protocol==='file:'){app.innerHTML='<div class="login-box"><h1>请启动本地服务</h1><p>双击同目录“启动本地网站.cmd”，然后打开 http://127.0.0.1:8777 。完整功能需要本地数据接口。</p></div>';return;}if(location.pathname==='/register'){registerView();return;}let session=await api('/api/session');role=session.role;if(role){await refresh(true);startTimers();}else loginView();}
init().catch(handleError);
