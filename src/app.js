'use strict';
const $ = s => document.querySelector(s);
let csrf = '', state = null, currentTab = 'devices', loading = false, modalAction = null, toastTimer;
const titles = {devices:'设备管理',users:'用户管理',keys:'接入密钥',connect:'连接指南',settings:'后台设置'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function date(value) { if (!value) return '长期有效'; const d = new Date(Number(value)*1000); return isNaN(d) ? '—' : d.toLocaleString('zh-CN',{hour12:false}); }
function notify(message,bad=false) { const box=$('#toast');box.textContent=message;box.classList.toggle('bad',bad);box.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,bad?8000:3500); }
async function api(path,data) {
 const options={credentials:'same-origin'};
 if(data!==undefined) {options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':csrf};options.body=JSON.stringify(data);}
 const response=await fetch(new URL('api/'+path,document.baseURI),options);const result=await response.json();
 if(!response.ok) {if(response.status===401&&path!=='login') showLogin();throw new Error(result.error||'操作失败');}return result;
}
function showLogin() {csrf='';state=null;$('#dashboard').hidden=true;$('#login').hidden=false;if($('#modal').open)$('#modal').close();}
function showDashboard() {$('#login').hidden=true;$('#dashboard').hidden=false;}
function tab(name) {currentTab=name;$('#page-title').textContent=titles[name];document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===name));document.querySelectorAll('[data-page]').forEach(p=>p.hidden=p.dataset.page!==name);}
function render() {
 document.querySelectorAll('[data-server-url]').forEach(el=>el.textContent=state.server);
 document.querySelectorAll('[data-admin-url]').forEach(el=>el.textContent=new URL('.',document.baseURI).href);
 $('#stat-devices').textContent=state.devices.length;$('#stat-online').textContent=state.devices.filter(n=>n.online).length;$('#stat-users').textContent=state.users.length;$('#server-version').textContent='版本 '+state.version+' · 自建网络';
 renderDevices();
 $('#user-list').innerHTML=state.users.map(u=>`<article class="list-row"><div><h3>${esc(u.display_name||u.name)}<span class="badge">用户 #${u.id}</span></h3><p>${state.devices.filter(n=>String(n.user_id)===String(u.id)).length} 台设备 · 创建于 ${esc(date(u.created))}</p></div><div class="row-actions"><button class="primary" data-action="group-devices" data-id="${u.id}">查看设备</button><button data-action="group-keys" data-id="${u.id}">注册密钥</button><button class="mutual-toggle ${u.mutual_access?'enabled':''}" role="switch" aria-checked="${u.mutual_access?'true':'false'}" data-action="mutual-access" data-id="${u.id}">客户端互访：${u.mutual_access?'开启':'关闭'}</button><button data-action="user-key" data-id="${u.id}">为此用户添加设备</button><button class="danger" data-action="delete-user" data-id="${u.id}">删除</button></div></article>`).join('')||'<div class="empty">尚无用户。</div>';
 $('#key-list').innerHTML=state.keys.map(k=>{const expired=k.expires&&Number(k.expires)<Date.now()/1000;const used=k.used&&!k.reusable;return `<article class="list-row"><div><h3>接入密钥 #${k.id}<span class="badge">${expired?'已过期':used?'已使用':'可使用'}</span></h3><p>${esc(k.user)} · ${k.reusable?'可重复使用':'仅使用一次'}${k.ephemeral?' · 临时设备':''}</p><p>到期时间 ${esc(date(k.expires))}</p></div><div class="row-actions">${!expired&&!used?`<button class="danger" data-action="expire-key" data-id="${k.id}">使密钥失效</button>`:''}</div></article>`;}).join('')||'<div class="empty">暂无接入密钥。已加入的设备不需要保留接入密钥。</div>';
 $('#last-updated').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});
}
let deviceSort = {key:'online',direction:'desc'};
const deviceColumns = [['name','设备名称'],['online','连接状态'],['user','所属用户组'],['ip','网络地址'],['last_seen','最近在线']];
function deviceValue(n,key) {
 if(key==='name')return n.name||n.hostname||'';
 if(key==='online')return Number(Boolean(n.online));
 if(key==='ip')return n.ip.find(a=>!a.includes(':'))||'';
 if(key==='last_seen')return n.online?Number.MAX_SAFE_INTEGER:Number(n.last_seen)||0;
 return n[key]||'';
}
function sortedDevices() {
 const collator=new Intl.Collator('zh-CN',{numeric:true,sensitivity:'base'});
 return [...state.devices].sort((a,b)=>{
  const av=deviceValue(a,deviceSort.key),bv=deviceValue(b,deviceSort.key);
  const cmp=typeof av==='number'?av-bv:collator.compare(String(av),String(bv));
  return (deviceSort.direction==='asc'?cmp:-cmp)||Number(a.id)-Number(b.id);
 });
}
function renderDevices() {
 const headers=deviceColumns.map(([key,label])=>{
  const active=deviceSort.key===key;
  return `<th scope="col" aria-sort="${active?(deviceSort.direction==='asc'?'ascending':'descending'):'none'}"><button type="button" data-action="sort-devices" data-key="${key}">${label}<span aria-hidden="true">${active?(deviceSort.direction==='asc'?'↑':'↓'):'↕'}</span></button></th>`;
 }).join('');
 const rows=sortedDevices().map(n=>{
  const ip=deviceValue(n,'ip'),ip6=n.ip.find(a=>a.includes(':'))||'';
  return `<tr><td><strong class="device-name">${esc(n.name||n.hostname)}</strong><small>客户端 · ${esc(n.client_name||n.hostname)}</small>${n.admin?'<span class="badge admin-device">管理员设备</span>':''}</td><td><span class="status ${n.online?'':'offline'}"><i class="dot"></i>${n.online?'在线':'离线'}</span></td><td>${esc(n.user)}</td><td><div class="table-ip">${esc(ip||'—')}${ip?`<button type="button" data-action="copy" data-value="${esc(ip)}" aria-label="复制 ${esc(ip)}">复制</button>`:''}</div><small class="table-ipv6">${esc(ip6)}</small></td><td class="last-seen">${n.online?'当前已连接':n.last_seen?esc(date(n.last_seen)):'暂无记录'}</td><td><div class="device-actions">${ip?`<a href="http://${esc(ip)}/" target="_blank" rel="noopener noreferrer">管理 ↗</a>`:''}<button type="button" data-action="rename" data-id="${n.id}">重命名</button><button type="button" data-action="expire-device" data-id="${n.id}">注销连接</button><button type="button" class="danger" data-action="delete-device" data-id="${n.id}">移除</button>${n.registration_history?.length?`<button type="button" data-action="registration-history" data-id="${n.id}">注册历史 (${n.registration_history.length})</button>`:''}</div></td></tr>`;
 }).join('');
 $('#device-list').innerHTML=`<table class="device-table"><caption class="sr-only">网络设备列表，点击表头可切换升序或降序</caption><thead><tr>${headers}<th scope="col">操作</th></tr></thead><tbody>${rows||'<tr><td colspan="6" class="table-empty">暂无设备，先生成接入密钥让设备加入网络。</td></tr>'}</tbody></table>`;
}
async function groupKeys(id) {
 const user=state.users.find(u=>String(u.id)===String(id));if(!user)throw new Error('用户组不存在');
 const result=await api('keys/group',{user:id});
 const content=result.keys.map(k=>`<article class="group-device"><div class="group-device-heading"><h3>密钥 #${esc(k.id)}</h3><span class="badge">${k.expired?'已过期':k.used?'已使用':'可使用'}</span></div><p>${k.reusable?'可重复使用':'仅使用一次'}${k.ephemeral?' · 临时设备':''} · 到期：${esc(date(k.expires))}</p>${k.key?`<code class="key-secret">${esc(k.key)}</code><button type="button" data-action="copy" data-value="${esc(k.key)}">复制注册密钥</button>`:`<code>${esc(k.prefix)}…</code><p>${k.expired||k.used?'此密钥已不可用于新设备注册。':'历史密钥未保存完整值，无法恢复，可重新生成。'}</p>`}</article>`).join('');
 modal((user.display_name||user.name)+' · 注册密钥',`<p>完整密钥仅供管理员查看。普通分组密钥不会授予设备管理员权限。</p><div class="group-device-list">${content||'<div class="empty">此分组暂无注册密钥。</div>'}</div><div class="row-actions"><button type="button" class="primary" data-action="user-key" data-id="${user.id}">生成新密钥</button><button type="button" data-action="group-keys" data-id="${user.id}">刷新</button></div>`,'',null);
 $('#modal').classList.add('group-devices-dialog');
}
function groupDevices(id) {
 const user=state.users.find(u=>String(u.id)===String(id));if(!user){notify('用户组不存在',true);return;}
 const devices=state.devices.filter(n=>String(n.user_id)===String(id));
 const online=devices.filter(n=>n.online).length;
 const content=devices.map(n=>`<article class="group-device"><div class="group-device-heading"><h3>${esc(n.name||n.hostname)}</h3><span class="status ${n.online?'':'offline'}"><i class="dot"></i>${n.online?'在线':'离线'}</span></div><dl class="group-device-details"><div><dt>客户端名称</dt><dd>${esc(n.client_name||'—')}</dd></div><div><dt>原始主机名</dt><dd>${esc(n.hostname||'—')}</dd></div><div><dt>IPv4 地址</dt><dd>${esc(n.ip.filter(a=>!a.includes(':')).join('、')||'—')}</dd></div><div><dt>IPv6 地址</dt><dd>${esc(n.ip.filter(a=>a.includes(':')).join('、')||'—')}</dd></div><div><dt>设备权限</dt><dd>${n.admin?'管理员 · 可访问所有设备':'普通设备'}</dd></div><div><dt>设备编号</dt><dd>#${esc(n.id)}</dd></div><div><dt>加入时间</dt><dd>${n.created?esc(date(n.created)):'—'}</dd></div><div><dt>最近在线</dt><dd>${n.online?'当前在线':n.last_seen?esc(date(n.last_seen)):'暂无记录'}</dd></div><div><dt>设备授权到期</dt><dd>${esc(date(n.expiry))}</dd></div></dl></article>`).join('');
 modal((user.display_name||user.name)+' · 设备详情',`<div class="group-device-summary"><strong>${devices.length} 台设备</strong><span>${online} 台在线 · ${devices.length-online} 台离线</span></div><p>更新于 ${esc(new Date().toLocaleTimeString('zh-CN',{hour12:false}))}</p><div class="group-device-list">${content||'<div class="empty">此用户组暂无设备。</div>'}</div><button type="button" class="quiet" data-action="group-devices" data-id="${user.id}">刷新设备状态</button>`,'',null);
 $('#modal').classList.add('group-devices-dialog');
}
async function refresh(silent=false) {if(loading||!csrf)return;loading=true;$('#refresh').disabled=true;try{state=await api('state');render();}catch(e){if(!silent)notify(e.message,true);else $('#last-updated').textContent='读取失败 · '+e.message;}finally{loading=false;$('#refresh').disabled=false;}}
function modal(title,html,label,action) {$('#modal').classList.remove('group-devices-dialog');$('#modal-title').textContent=title;$('#modal-body').innerHTML=html;$('#modal-submit').textContent=label;$('#modal-submit').hidden=!action;$('#modal-cancel').textContent=action?'取消':'关闭';$('#modal-error').textContent='';modalAction=action;if(!$('#modal').open)$('#modal').showModal();}
async function mutate(path,payload,message) {await api(path,payload);$('#modal').close();notify(message);await refresh();}
function confirmAction(title,message,path,payload) {modal(title,`<p>${esc(message)}</p>`,'确认',()=>mutate(path,payload,'操作成功'));}
function keyDialog(user) {
 if(!state?.users.length){notify('请先新建一个用户',true);return;}
 modal('添加新设备',`<p>生成后复制密钥或命令到需要接入的设备。</p><label>所属用户<select name="user">${state.users.map(u=>`<option value="${u.id}" ${String(u.id)===String(user)?'selected':''}>${esc(u.display_name||u.name)}</option>`).join('')}</select></label><label>接入期限<select name="expiration"><option value="10m">10 分钟</option><option value="1h" selected>1 小时</option><option value="24h">24 小时</option><option value="168h">7 天</option><option value="never">长期有效（不过期）</option></select></label><label class="check"><input name="reusable" type="checkbox">允许多台设备重复使用</label><label class="check"><input name="ephemeral" type="checkbox">临时设备（离线后自动移除）</label>`,'生成密钥',async()=>{
  const f=$('#modal-form');const result=await api('keys/create',{user:f.elements.user.value,expiration:f.elements.expiration.value,reusable:f.elements.reusable.checked,ephemeral:f.elements.ephemeral.checked});
  const command='tailscale up --login-server='+state.server+' --auth-key='+result.key+' --accept-dns=false --accept-routes=false';
  modal('接入密钥已生成',`<p class="secret-warning">密钥已保存。之后可在用户管理 → 注册密钥中查看，请妥善保管。</p><label>设备接入密钥<code class="key-secret">${esc(result.key)}</code></label><button type="button" class="quiet" data-action="copy" data-value="${esc(result.key)}">复制密钥</button><label>电脑 / Linux 登录命令<code>${esc(command)}</code></label><button type="button" class="primary" data-action="copy" data-value="${esc(command)}">复制登录命令</button><p>在路由器上使用时，还需按设备防火墙配置选择 netfilter 模式。</p>`,'',null);await refresh();
 });
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;e.preventDefault();const id=Number(b.dataset.id),action=b.dataset.action;
 try{
 if(action==='registration-history'){const n=state.devices.find(n=>Number(n.id)===id);if(!n)return;modal('注册历史 · '+n.name,`<p>主列表显示最新注册，旧记录保留在服务器中。名称关联仅用于后台展示，不改变设备权限；重刷后的网络 IP 可能变化。</p><div class="group-device-list">${[n,...(n.registration_history||[])].map((d,i)=>`<article class="group-device"><div class="group-device-heading"><h3>${i===0?'当前注册':'历史注册'} #${esc(d.id)}</h3><span class="status ${d.online?'':'offline'}">${d.online?'在线':'离线'}</span></div><dl class="group-device-details"><div><dt>设备名称</dt><dd>${esc(d.name)}</dd></div><div><dt>客户端名称</dt><dd>${esc(d.client_name)}</dd></div><div><dt>网络地址</dt><dd>${esc(d.ip.join(' / '))}</dd></div><div><dt>注册时间</dt><dd>${d.created?esc(date(d.created)):'—'}</dd></div></dl></article>`).join('')}</div>`,'',null);$('#modal').classList.add('group-devices-dialog');return;}
 if(action==='sort-devices'){const key=b.dataset.key;if(!deviceColumns.some(c=>c[0]===key))return;deviceSort={key,direction:deviceSort.key===key?(deviceSort.direction==='asc'?'desc':'asc'):(['online','last_seen'].includes(key)?'desc':'asc')};renderDevices();document.querySelector(`[data-action="sort-devices"][data-key="${key}"]`)?.focus({preventScroll:true});return;}
 if(action==='copy'){await navigator.clipboard.writeText(b.dataset.value);notify('已复制');return;}
 if(action==='group-keys'){b.disabled=true;try{await groupKeys(id);}finally{b.disabled=false;}return;}
 if(action==='group-devices'){b.disabled=true;try{state=await api('state');render();groupDevices(id);}finally{b.disabled=false;}return;}
 if(action==='mutual-access'){const u=state.users.find(u=>Number(u.id)===id);b.disabled=true;try{await api('users/mutual-access',{id,enabled:!u.mutual_access});notify(u.mutual_access?'已关闭该用户组客户端互访':'已开启该用户组客户端互访');await refresh();}finally{b.disabled=false;}return;}
 if(action==='user-key'){keyDialog(id);return;}
 if(action==='rename'){const n=state.devices.find(n=>n.id===id);modal('编辑设备名称',`<label>后台显示名称<input name="name" value="${esc(n.name)}" required maxlength="63"></label><p>支持中文，显示在后台设备列表。</p><label>客户端名称<input name="client_name" value="${esc(n.client_name||n.hostname)}" required maxlength="63" pattern="[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"></label><p>同步至 Windows、手机等官方客户端。仅支持英文、数字和短横线；修改后 MagicDNS 地址也会改变，设备 IP 保持不变。</p>`,'保存',()=>mutate('devices/rename',{id,name:$('#modal-form').elements.name.value,client_name:$('#modal-form').elements.client_name.value},'设备名称已保存，客户端名称正在同步'));}
 if(action==='expire-device')confirmAction('注销设备连接','该设备需要重新登录才能连接。此操作会立即中断它的远程访问。','devices/expire',{id});
 if(action==='delete-device')confirmAction('移除设备','将从网络中删除该设备，其远程连接会立即中断。重新加入需要新的认证。','devices/delete',{id});
 if(action==='delete-user')confirmAction('删除用户','仅可删除没有设备的用户。请确认不再使用此用户。','users/delete',{id});
 if(action==='expire-key')confirmAction('使接入密钥失效','新设备将无法再使用此密钥加入，已加入设备保持连接。','keys/expire',{id});
 }catch(err){notify(err.message,true);}
});
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button');b.disabled=true;$('#login-error').textContent='';try{const r=await api('login',{username:f.elements.username.value,password:f.elements.password.value});csrf=r.csrf;f.elements.password.value='';showDashboard();await refresh();}catch(err){$('#login-error').textContent=err.message;}finally{b.disabled=false;}});
$('#modal-form').addEventListener('submit',async e=>{e.preventDefault();if(!modalAction)return;const action=modalAction;$('#modal-submit').disabled=true;$('#modal-error').textContent='';try{await action();}catch(err){$('#modal-error').textContent=err.message;}finally{$('#modal-submit').disabled=false;}});
function closeModal(){ $('#modal').close();$('#modal-body').replaceChildren();modalAction=null; }
$('#modal-close').onclick=closeModal;$('#modal-cancel').onclick=closeModal;$('#modal').addEventListener('cancel',()=>{setTimeout(()=>$('#modal-body').replaceChildren(),0);modalAction=null;});
$('#refresh').onclick=()=>refresh();$('#logout').onclick=async()=>{try{await api('logout',{});showLogin();}catch(e){notify(e.message,true);}};
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$('#add-user').onclick=()=>modal('新建网络用户','<p>所有普通设备默认禁止互访，仅管理员设备可以主动连接。建议按个人或组织建立用户。</p><label>用户名称<input name="name" placeholder="例如 company-a" required maxlength="63" autocomplete="off"></label>','新建用户',()=>mutate('users/create',{name:$('#modal-form').elements.name.value},'用户已创建'));
$('#add-key').onclick=()=>keyDialog();$('#guide-key').onclick=()=>keyDialog();document.querySelectorAll('.copy-server').forEach(b=>b.onclick=()=>navigator.clipboard.writeText(state.server).then(()=>notify('已复制')).catch(()=>notify('复制失败，请手动复制地址',true)));
$('#password-form').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button');if(f.elements.password.value!==f.elements.confirm.value){notify('两次输入的新密码不一致',true);return;}b.disabled=true;try{await api('password',{current:f.elements.current.value,password:f.elements.password.value});f.reset();notify('密码已保存，其他后台会话已退出');}catch(err){notify(err.message,true);}finally{b.disabled=false;}};
setInterval(()=>{if(!document.hidden&&csrf)refresh(true);},15000);
async function init(){try{const s=await api('session');if(s.authenticated){csrf=s.csrf;showDashboard();await refresh();}else showLogin();}catch(e){showLogin();$('#login-error').textContent='无法连接服务，请刷新重试。';}}
init();
