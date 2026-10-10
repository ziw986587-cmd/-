'use strict';
const $=s=>document.querySelector(s),h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let currentUser='';
async function api(url,data,retry=true){const res=await fetch(url,{cache:'no-store',...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})});const value=await res.json();if(!res.ok){if(res.status===428&&retry&&data)return memberOperation(url,data);if(res.status===423&&retry&&await ensureRoomAccess())return api(url,data,false);if(res.status===401&&url!=='/api/login')loginView();throw Error(value.message||'请求失败');}return value;}
function toast(message,error=false){let el=$('#admin-toast');if(!el){el=document.createElement('div');el.id='admin-toast';el.setAttribute('role','status');document.body.appendChild(el);}el.textContent=message;el.className='admin-toast visible'+(error?' error':'');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.className='admin-toast',5000);}
function loginView(){$('#member-access-dialog')?.close();$('#room-access-dialog')?.close();$('#admin-dialog')?.close();window.RoomAdmin?.dispose();window.Workbench?.dispose();$('#app').innerHTML=`<main class="admin-login"><div class="login-brand">本地运营中心</div><h1>管理员登录</h1><p>会员、房间与前台数据统一管理</p><form id="admin-login-form"><label>后台账号<input name="username" value="localadmin" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><button class="admin-primary" type="submit">登录后台</button><p id="login-error" role="alert"></p></form><small>会员请使用后台分配的专属链接进入前台。</small></main>`;}
function setRoomHeader(active,game){$('#home-entry').hidden=!active;document.querySelectorAll('[data-room-entry]').forEach(b=>b.classList.toggle('selected',active&&b.dataset.roomEntry===game));}
async function openRoom(pane='config',game=Workbench.game){if(pane!=='members'&&!await ensureRoomAccess())return;if(!Workbench.hide())return;await RoomAdmin.navigate(pane,game);}
async function showHome(){if(!RoomAdmin.hide())return;setRoomHeader(false);await Workbench.show();}
function dashboard(){document.title='本地运营工作台';$('#app').innerHTML=`<header class="tophead reference-head"><div class="wb-account"><b class="warning">本地独立版 · 仅虚拟积分</b>，欢迎您：<b>${h(currentUser)}</b>，数据：<b>本机文件</b>　<button id="password-entry">修改密码</button> <button id="logout-entry">退出登录</button></div><div class="wb-room-entries" aria-label="三个房间后台"><button data-room-entry="canada28">加拿大28后台</button><button data-room-entry="australia8">澳洲8后台</button><button data-room-entry="australia8ball">澳洲3后台</button><button id="robot-entry">机器人</button></div><nav><button id="members-entry">用户入口</button><button data-global-wb="ledger">积分记录</button><button data-global-wb="logs">消息日志</button><button data-global-wb="export">导出数据</button><button id="help-entry">功能说明</button><button id="home-entry" hidden>返回主页面</button></nav></header>`;Workbench.attach({api,toast,modal,ensureRoomAccess,closeModal:()=>$('#admin-dialog')?.close(),openRoom});RoomAdmin.attach({api,toast,ensureRoomAccess,onAccessCancelled:showHome,onOpen:game=>{Workbench.hide();setRoomHeader(true,game);}});if(!location.hash.startsWith('#rooms'))Workbench.show().catch(e=>toast(e.message,true));}
function modal(title,body){$('#admin-dialog')?.remove();const d=document.createElement('dialog');d.id='admin-dialog';d.innerHTML=`<div class="admin-dialog-head"><h2>${h(title)}</h2><button type="button" data-close-dialog aria-label="关闭">×</button></div>${body}`;document.body.appendChild(d);d.showModal();}
document.addEventListener('change',e=>{const form=e.target.closest('#wb-modal-form');if(form)Workbench.modalChange(form);});
document.addEventListener('submit',async e=>{const form=e.target;if(form.id==='wb-modal-form'){e.preventDefault();Workbench.modalSubmit(form,e.submitter).catch(err=>toast(err.message,true));return;}if(!['admin-login-form','password-form'].includes(form.id))return;e.preventDefault();const d=Object.fromEntries(new FormData(form)),b=form.querySelector('button[type=submit]');if(b.disabled)return;b.disabled=true;try{if(form.id==='admin-login-form'){await api('/api/login',d);currentUser=d.username;dashboard();}else{if(d.newPassword!==d.confirmPassword)throw Error('两次新密码不一致');await api('/api/password',d);$('#admin-dialog').close();loginView();toast('密码已修改，请重新登录');}}catch(err){const el=$('#login-error');if(el)el.textContent=err.message;else toast(err.message,true);}finally{b.disabled=false;}});
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.dataset.roomEntry){await openRoom('config',b.dataset.roomEntry);return;}if(b.dataset.globalWb){if(!Workbench.active){if(!RoomAdmin.hide())return;await showHome();}await Workbench.action(b.dataset.globalWb);return;}switch(b.id){case 'robot-entry':await Workbench.openRobot(document.querySelector('[data-room-entry].selected')?.dataset.roomEntry||Workbench.game);break;case 'home-entry':await showHome();break;case 'members-entry':await openRoom('members');break;case 'logout-entry':await api('/api/logout',{});loginView();break;case 'password-entry':await passwordSettings();break;case 'help-entry':modal('前后台使用说明',`<ol><li>在首页右侧“创建会员”创建用户。左侧二维码和入口链接对应当前选中的用户。</li><li>在首页左侧入口菜单复制该用户的专属链接；更多用户设置位于顶部“用户入口”。</li><li>房间设置、会员积分、注单、审核、公告和结算均使用同一套数据。</li><li>停用用户会立即撤销其旧链接；启用后领取新链接。重新生成链接也会立即使旧链接失效。</li><li>顶部三个按钮分别打开三个房间的详细后台；点“返回主页面”回到工作台。三个房间使用同一份共用积分，订单按房间分别展示。</li><li>工作台赔率、限注、封盘直接修改房间配置。“托”标记模拟用户，“机”可多选房间并统一设置自动下注；保存启用后服务器持续执行，封盘、暂停时停止提交；托额度不足时自动上分1000～5000并自动审核通过。延报、免抽、返水为保留参数；模拟上报仅修改本地状态。</li><li>原有房间余额一次合并为共用积分，旧记录保留。<a href="/api/legacy/export" download>导出旧工作台档案</a>。</li></ol><p>专属链接等同该用户的访问凭证，请只交给对应用户。本机地址仅在运行软件的电脑可用。</p>`);break;}if(b.hasAttribute('data-close-dialog'))$('#admin-dialog').close();}catch(err){toast(err.message,true);}});
api('/api/session').then(s=>{if(s.role==='admin'){currentUser=s.username;dashboard();}else loginView();}).catch(e=>{loginView();toast(e.message,true);});

let roomAccessPending=null;
async function ensureRoomAccess(){
 if(roomAccessPending)return roomAccessPending;
 roomAccessPending=(async()=>{
  const state=await api('/api/room-access');
  if(state.unlocked)return true;
  if(!state.configured){await passwordSettings();toast('请先设置四个入口共用的房间访问密码');return false;}
  return new Promise(resolve=>{
   const dialog=document.createElement('dialog');dialog.id='room-access-dialog';dialog.className='room-access-dialog';
   dialog.innerHTML='<div class="admin-dialog-head"><h2>验证房间访问密码</h2><button type="button" data-cancel aria-label="关闭">×</button></div><p>加拿大28后台、澳洲8后台、澳洲3后台和机器人共用一组密码，本次登录只需验证一次。</p><form><label>房间访问密码<input name="password" type="password" maxlength="128" autocomplete="off" required></label><p data-error role="alert"></p><button type="submit" class="admin-primary">验证并进入</button></form>';
   let accepted=false;
   dialog.addEventListener('close',()=>{dialog.remove();resolve(accepted);},{once:true});
   dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
   dialog.querySelector('form').addEventListener('submit',async event=>{
    event.preventDefault();event.stopPropagation();const button=dialog.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;
    try{await api('/api/room-access/unlock',{password:dialog.querySelector('input').value});accepted=true;dialog.close();}
    catch(error){dialog.querySelector('[data-error]').textContent=error.message;dialog.querySelector('input').select();}
    finally{button.disabled=false;}
   });
   document.body.appendChild(dialog);dialog.showModal();dialog.querySelector('input').focus();
  });
 })();
 try{return await roomAccessPending;}finally{roomAccessPending=null;}
}
async function passwordSettings(){
 const state=await api('/api/room-access');
 modal('修改密码',`<details class="login-password-section"><summary>修改管理员登录密码</summary><form id="password-form"><label>原密码<input name="oldPassword" type="password" autocomplete="current-password" required></label><label>新密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><label>确认新密码<input name="confirmPassword" type="password" autocomplete="new-password" required></label><button type="submit" class="admin-primary">保存密码</button></form></details><hr><h3>四个入口共用的房间访问密码</h3><p>加拿大28后台、澳洲8后台、澳洲3后台、机器人共用。本次登录验证一次，退出后需重新验证。</p><p>当前状态：${state.configured?'已设置（可在此重置）':'尚未设置，请先设置再进入房间后台'}</p><form id="room-password-form"><label>管理员登录密码<input name="adminPassword" type="password" autocomplete="current-password" required></label><label>新房间访问密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><label>确认房间访问密码<input name="confirmPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><button type="submit" class="admin-primary">保存共用访问密码</button><p data-error role="alert"></p></form>`);
 memberPasswordSettings();
 const form=$('#room-password-form');
 form.addEventListener('submit',async event=>{
  event.preventDefault();event.stopPropagation();const button=form.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;
  try{const data=Object.fromEntries(new FormData(form));if(data.newPassword!==data.confirmPassword)throw Error('两次房间访问密码不一致');await api('/api/room-access/password',data);$('#admin-dialog').close();RoomAdmin.dispose();Workbench.dispose();history.replaceState(null,'','/admin');dashboard();toast('共用访问密码已保存，四个入口需重新验证');}
  catch(error){form.querySelector('[data-error]').textContent=error.message;}finally{button.disabled=false;}
 });
}

function memberOperation(url,data){
 return new Promise((resolve,reject)=>{
  const dialog=document.createElement('dialog');dialog.id='member-access-dialog';dialog.className='room-access-dialog';
  const operation=data.operation==='member.delete'?'删除用户':data.operation==='workbench.data.clear'?'一键清除数据':data.operation==='workbench.balances.clear'?'一键清除余分':data.operation==='member.edit'&&typeof data.data?.robot==='boolean'?(data.data.robot?'设为托':'取消托标记'):data.operation==='member.edit'&&typeof data.data?.enabled==='boolean'?(data.data.enabled?'启用用户':'停用用户'):'修改用户状态';
  dialog.innerHTML='<div class="admin-dialog-head"><h2>验证用户操作密码</h2><button type="button" data-cancel aria-label="关闭">×</button></div><p>'+h(operation)+'：'+h(data.data?.username||'')+'</p><p>每次修改用户状态均需验证，此密码可在“修改密码”中设置。</p><form><label>用户操作密码<input name="password" type="password" autocomplete="off" maxlength="128" required></label><p data-error role="alert"></p><button type="submit" class="admin-primary">验证并执行</button></form>';
  let accepted=false;
  dialog.addEventListener('close',()=>{dialog.remove();if(!accepted)reject(Error('已取消操作'));},{once:true});
  dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
  dialog.querySelector('form').addEventListener('submit',async event=>{
   event.preventDefault();event.stopPropagation();const button=dialog.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;
   try{const result=await api(url,{...data,memberPassword:dialog.querySelector('input').value},false);accepted=true;dialog.close();resolve(result);}
   catch(error){dialog.querySelector('[data-error]').textContent=error.message;dialog.querySelector('input').select();}
   finally{button.disabled=false;}
  });
  document.body.appendChild(dialog);dialog.showModal();dialog.querySelector('input').focus();
 });
}
function memberPasswordSettings(){
 $('#password-form').closest('details').insertAdjacentHTML('afterend','<hr><details class="login-password-section"><summary>修改用户操作密码（托 / 启停 / 删除）</summary><form id="member-password-form"><label>管理员登录密码<input name="adminPassword" type="password" autocomplete="current-password" required></label><label>新用户操作密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><label>确认用户操作密码<input name="confirmPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><button type="submit" class="admin-primary">保存用户操作密码</button><p data-error role="alert"></p></form></details>');
 const form=$('#member-password-form');
 form.addEventListener('submit',async event=>{
  event.preventDefault();event.stopPropagation();const button=form.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;
  try{const data=Object.fromEntries(new FormData(form));if(data.newPassword!==data.confirmPassword)throw Error('两次用户操作密码不一致');await api('/api/member-access/password',data);form.reset();toast('用户操作密码已修改，下次操作使用新密码');}
  catch(error){form.querySelector('[data-error]').textContent=error.message;}finally{button.disabled=false;}
 });
}
