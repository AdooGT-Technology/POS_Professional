const state = { boot:null, active:'games', filter:'ALL', query:'', mode:'grid', bridge:false, selected:null, authenticated:false };
const $ = id => document.getElementById(id);
const bridge = () => window.pywebview?.api;
function toast(message){ const el=$('toast'); el.textContent=message; el.classList.add('show'); clearTimeout(window.__toast); window.__toast=setTimeout(()=>el.classList.remove('show'),2400); }
function setStatus(text, kind='online'){ const x=$('connection-text'); if(x)x.textContent=text; const d=$('footer-connection-dot'),t=$('footer-connection-text'); if(d)d.classList.toggle('offline',kind!=='online'); if(t)t.textContent=kind==='online'?'Client Online':'Server Offline'; }
function esc(s){ return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function setBridgeStatus(text, ok=false){ const el=$('bridge-status'); if(el){el.textContent=text;el.className='bridge-status '+(ok?'ok':'');} }
function safeApi(name){ const api=bridge(); return api && typeof api[name] === 'function' ? api[name].bind(api) : null; }
function isAuthenticated(){ return state.authenticated === true && !!state.boot?.customer_name; }
function requireAuthentication(){ if(isAuthenticated()) return true; state.authenticated=false; state.boot=state.boot||{}; state.boot.customer_name=''; renderLogin(); return false; }
function setAuthenticated(value){ state.authenticated=!!value; document.body.classList.toggle('client-authenticated',state.authenticated); }

async function publicBoot(){
  const fn=safeApi('get_public_bootstrap');
  if(!fn) throw new Error('واجهة Python غير جاهزة بعد');
  state.boot=await fn(); window.__CLIENT_CONFIG=state.boot.client_config||{};
  $('device-id').textContent=state.boot.client_id||'—';
  applyProfile();
  renderLogin();
}
function renderLogin(){
  setAuthenticated(false);
  $('login-view').hidden=false;
  $('home-view').hidden=true;
  document.body.classList.remove('client-authenticated');
  $('customer-name').value='';
  setTimeout(()=>$('customer-name')?.focus(),0);
}
function applyProfile(){
  const p=state.boot?.profile||{};
  const storeName=state.boot?.store_name||state.boot?.client_config?.store_name||"متجري";
  const clientName=state.boot?.client_config?.device_name||state.boot?.client_id||"CLIENT";
  document.querySelectorAll(".brand-name,.brand-name-small").forEach(x=>x.textContent=storeName);
  document.title=storeName+" — "+clientName;
  const profileLogo=p.logo_asset||state.boot?.store_logo||"";
  const loginLogo=$('login-logo'); if(loginLogo){loginLogo.src=profileLogo||'';loginLogo.hidden=!profileLogo;}
  for(const [k,v] of [['accent',p.accent_color||'#38cfff'],['accent2',p.accent_2||'#8f7bff'],['text',p.text_color||'#edf4ff'],['muted',p.muted_color||'#9fb1c8']]) document.documentElement.style.setProperty('--'+k,v);
  const welcome=p.welcome_text||'اختر لعبتك وابدأ الآن.';
  $('welcome').textContent=welcome;
  $('hero-sub').textContent=p.profile_badge||welcome;
  const badge=$('client-face-badge'); if(badge) badge.textContent=p.profile_badge||'PLAYER SPACE';
  const logo=$('logo'); if(logo){logo.src=profileLogo||'';logo.hidden=!profileLogo;}
  document.body.style.backgroundImage=p.background_asset?`linear-gradient(180deg,rgba(4,7,15,.38),rgba(4,7,15,.92)),url("${p.background_asset}")`:'';
  document.body.style.backgroundSize=p.background_asset?'cover':'';
  document.body.style.backgroundPosition=p.background_asset?'center':'';
  document.body.style.backgroundAttachment=p.background_asset?'fixed':'';
  const mainAsset=p.main_image_asset||'';
  let loginMain=document.getElementById('login-main-image');
  if(mainAsset){ if(!loginMain){loginMain=document.createElement('img');loginMain.id='login-main-image';loginMain.className='login-main-image';const panel=document.querySelector('.login-panel');panel?.insertBefore(loginMain,panel.querySelector('.login-badge'));} loginMain.src=mainAsset;loginMain.hidden=false; }
  else if(loginMain){loginMain.hidden=true;}
  let bgv=document.getElementById('client-bg-video');
  if(p.video_asset){if(!bgv){bgv=document.createElement('video');bgv.id='client-bg-video';bgv.autoplay=true;bgv.muted=true;bgv.loop=true;bgv.playsInline=true;document.body.prepend(bgv);} bgv.src=p.video_asset;bgv.style.cssText='position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:-2;opacity:.30;pointer-events:none';}
  else if(bgv) bgv.remove();
  const icons={games:p.icon_games,apps:p.icon_apps,shop:p.icon_shop,events:p.icon_events,files:p.icon_my_files,profile:p.icon_profile,purchases:'◫',wallet:'◉',rewards:'✦'};
  document.querySelectorAll('.side-link').forEach(btn=>{
    const key=btn.dataset.section; const showKey=key==='files'?'my_files':key;
    btn.hidden=(p['show_'+showKey]===false);
    const icon=btn.querySelector('span'); const src=icons[key];
    if(icon && src){ if(String(src).startsWith('/')) icon.innerHTML=`<img src="${esc(src)}" style="width:22px;height:22px;object-fit:contain">`; else icon.textContent=src; }
  });
  const customer=state.boot?.customer_name||'';
  const player=$('player-name'); if(player) player.textContent=customer||'—';
  const sessionLabel=$('player-session-label'); if(sessionLabel) sessionLabel.textContent=customer?'جلسة نشطة':'تسجيل الدخول';
}
async async function afterLogin(){
  if(!state.boot?.customer_name) throw new Error('لم يتم إنشاء جلسة عميل صالحة');

  const fn=safeApi('get_bootstrap'); if(!fn) throw new Error('دالة تحميل الواجهة غير متاحة');
  state.boot=await fn(); if(!state.boot?.customer_name) throw new Error('الخادم لم يؤكد جلسة العميل'); setAuthenticated(true); applyProfile(); $('login-view').hidden=true; $('home-view').hidden=false;
  const p=state.boot.profile||{}; if(p.kiosk_mode) await safeApi('set_kiosk')?.(true);
  renderHome();
}
function renderHome(){ if(!requireAuthentication()) return;
  const customer=state.boot.customer_name||''; $('player-name').textContent=customer||'—'; $('hero-title').textContent=customer?`مرحبًا ${esc(customer)}`:'مرحبًا';
  state.active='games'; state.filter='ALL'; state.query=''; $('global-search').value=''; $('side-search').value='';
  buildCategories(); renderAds(); renderFavorites(); syncSideLinks(); renderCatalog(); setStatus('متصل');
}
function buildCategories(){
  const p=state.boot.profile||{}; const el=$('categories'); el.innerHTML='';
  const cats=[['ALL','الكل'],['ONLINE','أونلاين'],['ACTION','أكشن'],['SPORT','رياضة'],['RACING','سباق'],['OTHER','أخرى']];
  for(const [key,label] of cats){ const b=document.createElement('button'); b.className='category'+(state.filter===key?' active':''); b.textContent=label; b.onclick=()=>filterCategory(key); el.appendChild(b); }
}
function renderAds(){ const p=state.boot.profile||{}, ads=$('ads'); const list=state.boot.banners||[]; if(!p.show_ads||!list.length){ads.hidden=true;ads.innerHTML='';return;} ads.hidden=false; ads.innerHTML=list.slice(0,3).map(b=>`<article class="ad" style="${b.image_url?`background-image:url("${b.image_url}")`:''}" onclick="openAd('${encodeURIComponent(b.url||'')}')"><div class="ad-shade"><b>${esc(b.title)}</b><span>${esc(b.body)}</span></div></article>`).join(''); }
function renderFavorites(){ if(!requireAuthentication()) return; const list=(state.boot.items||[]).filter(x=>x.favorite||x.is_favorite).slice(0,6); $('favorites').innerHTML=list.length?list.map(x=>`<button onclick="selectGame('${x.id}')" class="favorite-row">${x.icon_url?`<img src="${esc(x.icon_url)}">`:''}<span>${esc(x.name)}</span><em>مفضلة</em></button>`).join(''):'<div class="empty-rail">لا توجد ألعاب مفضلة بعد.</div>'; }
function syncSideLinks(){ document.querySelectorAll('.side-link').forEach(b=>b.classList.toggle('active',b.dataset.section===state.active)); }
function showSection(kind){ if(!requireAuthentication()) return; state.active=kind; syncSideLinks(); if(['games','apps'].includes(kind)){buildCategories();renderCatalog();return;} const titles={shop:['المتجر','الطلبات والعروض المتاحة من الخادم المركزي'],purchases:['مشترياتي','سجل مشترياتك وفواتيرك'],wallet:['المحفظة','رصيد الجلسة والوقت المتاح'],rewards:['المكافآت','النقاط والعروض الخاصة بالعميل'],events:['الفعاليات','البطولات والفعاليات الخاصة بهذا المركز'],profile:['ملفي','بيانات الجلسة والحساب الحالي'],files:['ملفاتي','مساحة الملفات الشخصية']}; const [title,sub]=titles[kind]||['Client','']; $('section-title').textContent=title;$('section-sub').textContent=sub;$('catalog-count').textContent='';$('cards').innerHTML=sectionCards(kind); }
function sectionCards(kind){
  const customer=state.boot?.customer_name||'العميل';
  if(kind==='profile') return `<article class="info-card customer-face-card"><b>${esc(customer)}</b><span>الجهاز: ${esc(state.boot.client_id||'—')}</span><span>المتجر: ${esc(state.boot.store_name||'متجري')}</span><span>الحالة: جلسة نشطة</span></article>`;
  if(kind==='wallet') return `<article class="info-card customer-face-card"><b>المحفظة</b><span>العميل: ${esc(customer)}</span><span>الرصيد والوقت يتم احتسابهما من Server وManager.</span></article>`;
  if(kind==='purchases') return `<article class="info-card customer-face-card"><b>مشترياتي</b><span>سيظهر هنا سجل المشتريات والعروض المرتبطة بجلسة العميل.</span></article>`;
  if(kind==='rewards') return `<article class="info-card customer-face-card"><b>المكافآت</b><span>العروض والنقاط الخاصة بالعميل من النظام المركزي.</span></article>`;
  if(kind==='files') return `<article class="info-card customer-face-card"><b>ملفاتي</b><span>مساحة الملفات الشخصية الخاصة بالعميل.</span></article>`;
  if(kind==='shop') return `<article class="info-card customer-face-card"><b>المتجر</b><span>العروض والمنتجات المتاحة من الخادم المركزي.</span></article>`;
  if(kind==='events') return `<article class="info-card customer-face-card"><b>الفعاليات</b><span>البطولات والفعاليات المنشورة لهذا المركز.</span></article>`;
  return `<article class="info-card customer-face-card"><b>Client</b><span>واجهة العميل المركزية.</span></article>`;
}
function filterCategory(key){ if(!requireAuthentication()) return; state.filter=key; buildCategories(); renderCatalog(); }
function filteredItems(){
  let items=(state.boot.items||[]).filter(x=>x.item_type===(state.active==='apps'?'APP':'GAME'));
  if(state.query.trim()) items=items.filter(x=>`${x.name} ${x.description||''}`.toLowerCase().includes(state.query.trim().toLowerCase()));
  if(state.filter==='ONLINE') items=items.filter(x=>x.online!==false && x.status!=='OFFLINE');
  return items;
}
function renderCatalog(){ if(!requireAuthentication()) return;
  const items=filteredItems(); $('section-title').textContent=state.active==='apps'?'التطبيقات':'الألعاب'; $('section-sub').textContent=`${items.length} عنصر متاح على هذا الجهاز`; $('catalog-count').textContent=`${items.length} عنصر`; document.querySelectorAll('.hero-chip').forEach((b,i)=>b.classList.toggle('active',(state.active==='games'&&i===0)||(state.active==='apps'&&i===1)));
  const cards=$('cards'); cards.classList.toggle('list-mode',state.mode==='list');
  cards.innerHTML=items.length?items.map(card).join(''):`<div class="empty-state"><div class="empty-icon">⌁</div><h3>لا توجد عناصر مطابقة</h3><p>يمكن للمدير إدارة الألعاب والتطبيقات من Client Studio المركزي.</p></div>`;
}
function card(x){ const cover=x.poster_url?`<img class="game-cover-image" src="${esc(x.poster_url)}" alt="">`:''; const icon=x.icon_url?`<img src="${esc(x.icon_url)}" alt="">`:`<span class="fallback-icon">${x.item_type==='GAME'?'⌁':'◈'}</span>`; const online=x.status!=='OFFLINE'; return `<article class="game-card" onclick="selectGame('${x.id}')"><div class="cover">${cover}${icon}<span class="status-pill ${online?'online':'offline'}">● ${online?'Online':'Offline'}</span><button class="fav-btn" onclick="event.stopPropagation();toast('تم تحديث المفضلة')">★</button></div><div class="game-info"><div><h3>${esc(x.name)}</h3><p>${esc(x.description||'')}</p></div><button class="play-btn" onclick="event.stopPropagation();launch('${String(x.id).replace(/'/g,'')}')">تشغيل</button></div></article>`; }
function selectGame(id){ if(!requireAuthentication()) return; state.selected=(state.boot.items||[]).find(x=>String(x.id)===String(id)); if(!state.selected)return; const x=state.selected; $('selected-panel').hidden=false; $('selected-game').innerHTML=`<div class="selected-hero">${x.icon_url?`<img src="${esc(x.icon_url)}">`:''}<div><h4>${esc(x.name)}</h4><span class="status-pill online">● Online</span></div></div><div class="detail-grid"><span>النوع<b>${esc(x.item_type||'GAME')}</b></span><span>الحالة<b>${x.status||'متاح'}</b></span><span>الحجم<b>${esc(x.size||'—')}</b></span><span>اللاعبون<b>${esc(x.players||'—')}</b></span></div><button class="primary-small" onclick="launch('${String(x.id).replace(/'/g,'')}')">تشغيل اللعبة</button>`; }
function setGridMode(mode){ state.mode=mode; document.querySelectorAll('.tool').forEach((b,i)=>b.classList.toggle('active',(mode==='grid'&&i===0)||(mode==='list'&&i===1))); renderCatalog(); }
async function doLogin(){ if(isAuthenticated()) return;
  try{
    $('login-error').textContent=''; const fn=safeApi('authenticate');
    if(!fn){$('login-error').textContent='واجهة الاتصال غير جاهزة. انتظر لحظة ثم حاول مرة أخرى.';return;}
    $('login-button').disabled=true; $('login-button').textContent='جاري الدخول…';
    const r=await fn({customer_name:$('customer-name').value}); state.boot=state.boot||{}; state.boot.customer_name=r.customer_name; await afterLogin(); toast(`مرحبًا ${r.customer_name}`); setBridgeStatus('اتصال Python API جاهز',true);
  }catch(e){ $('login-error').textContent=e?.message||String(e); }
  finally{ $('login-button').disabled=false; $('login-button').textContent='دخول إلى المنصة'; }
}
async function logout(){
  try{
    const fn=safeApi('logout'); if(fn) await fn();
    if(state.boot) state.boot.customer_name='';
    state.selected=null;
    setAuthenticated(false);
    renderLogin();
    history.replaceState(null,'',location.href.split('#')[0]);
  }catch(e){toast(e.message||String(e));}
}
async function launch(id){ if(!requireAuthentication()) return; try{ const fn=safeApi('launch'); if(!fn)throw new Error('واجهة التشغيل غير جاهزة'); setStatus('تشغيل…'); const r=await fn(id); toast(r.message||'تم التشغيل'); setTimeout(()=>setStatus('متصل'),1300);}catch(e){setStatus('متصل');toast(e.message||String(e));} }
function showProfile(){showSection('profile')}
function showFiles(){showSection('files')}
function openAd(encoded){const url=decodeURIComponent(encoded); if(url) safeApi('open_external')?.(url)}
function toggleFullscreen(){safeApi('toggle_fullscreen')?.()}
async function refreshUI(){ try{if(!isAuthenticated()) return publicBoot(); const fn=safeApi('get_bootstrap'); if(!fn) throw new Error('واجهة العميل غير جاهزة'); state.boot=await fn(); if(!state.boot?.customer_name){renderLogin();return;}  applyProfile(); renderHome(); toast('تم تحديث الواجهة');}catch(e){toast(e.message||String(e));} }
function updateQuery(v){ state.query=v||''; renderCatalog(); }
$('login-button')?.addEventListener('click',doLogin);
$('customer-name')?.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
$('global-search')?.addEventListener('input',e=>{ $('side-search').value=e.target.value; updateQuery(e.target.value); });
$('side-search')?.addEventListener('input',e=>{ $('global-search').value=e.target.value; updateQuery(e.target.value); });
window.addEventListener('popstate',()=>{ if(!isAuthenticated()) renderLogin(); else history.go(1); });
window.addEventListener('hashchange',()=>{ if(!isAuthenticated()) renderLogin(); });
document.addEventListener('keydown',e=>{ if(!isAuthenticated() && (e.altKey && e.key==='ArrowLeft' || e.altKey && e.key==='ArrowRight')){ e.preventDefault(); }});
window.addEventListener('pywebviewready',async()=>{ state.bridge=true; setBridgeStatus('واجهة العميل جاهزة',true); try{await publicBoot();setStatus('متصل','online');}catch(e){renderLogin();setStatus('غير متصل','offline');setBridgeStatus('الخادم غير متاح — يمكنك فتح ⚙ وإعداد الاتصال',false);} });
setTimeout(()=>{if(!state.bridge){setAuthenticated(false); renderLogin();setStatus('غير متصل','offline');setBridgeStatus('في انتظار WebView2 Python API…');}},700);

setInterval(async()=>{ try{ if(!isAuthenticated()) return; const fn=safeApi('status'); if(!fn)return; const s=await fn(); setStatus(s?.state==='OFFLINE'?'غير متصل':'متصل',s?.state==='OFFLINE'?'offline':'online'); let overlay=document.getElementById('session-pause-overlay'); if(s.session_paused){ if(!overlay){overlay=document.createElement('div');overlay.id='session-pause-overlay';overlay.className='session-pause-overlay';overlay.innerHTML='<div><div class="pause-icon">⏸</div><h2>الجلسة متوقفة مؤقتًا</h2><p>يرجى مراجعة موظف الصالة.</p></div>';document.body.appendChild(overlay);} overlay.hidden=false;} else if(overlay) overlay.hidden=true; }catch(e){} }, 1500);


function renderModule(module,data){ if(module==='login'){renderLogin();return;} if(!requireAuthentication()) return; if(['games','apps','shop','purchases','wallet','rewards','events','profile','files'].includes(module)){showSection(module);return;} renderHome(); }
window.renderModule=renderModule;

