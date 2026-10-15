'use strict';
const paths = {
 bell:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4',
 eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0',
 overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 devices:'M3 4h14v12H3z M7 20h6 M10 16v4 M20 8h2v13h-7v-2',
 computer:'M3 4h18v13H3z M8 21h8 M12 17v4',
 phone:'M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1 M10 18h4',
 tv:'M3 7h18v14H3z M8 2l4 5 4-5',
 router:'M3 14h18v7H3z M7 14V6 M17 14V6 M6 18h.01 M10 18h.01 M4 3q3-3 6 0 M14 3q3-3 6 0',
 device:'M12 3l9 5v9l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v9',
 activity:'M2 12h5l3-9 4 18 3-9h5',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M10 2h4l1 3 3 1 3 2-1 3v2l1 3-3 2-3 1-1 3h-4l-1-3-3-1-3-2 1-3v-2L3 8l3-2 3-1z',
 scan:'M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5 M7 12a5 5 0 1 0 10 0 5 5 0 1 0-10 0 M12 9v3l2 2',
 shield:'M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6',
 home:'M3 10l9-8 9 8 M5 9v12h14V9 M9 21v-8h6v8',
 help:'M9 8a3 3 0 1 1 4 3c-1 1-1 1-1 3 M12 18h.01 M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
 search:'M10 3a7 7 0 1 0 0 14 7 7 0 1 0 0-14 M15 15l6 6',
 arrow:'M7 17L17 7 M7 7h10v10',
 chevron:'M9 5l7 7-7 7',
 download:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',
 check:'M5 12l4 4L19 6',
 info:'M12 10v7 M12 6h.01 M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
 clock:'M12 7v5l3 2 M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
 wifi:'M2 8q10-9 20 0 M5 12q7-6 14 0 M9 16q3-3 6 0 M12 20h.01',
 plus:'M12 5v14 M5 12h14',
};
function icon(name, cls='') {return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.device}"/></svg>`;}
function hydrateIcons(root=document) {root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});}
const $ = s=>document.querySelector(s);
const esc = v=>String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, page='overview', query='', filter='all', roomFilter='', selectedId=null, requestPending=false, toastTimer;
const notifier=new LanternNotifier(api,{
 getItem:key=>window.localStorage.getItem(key),
 setItem:(key,value)=>window.localStorage.setItem(key,value),
},window.Notification);
const titles={alerts:['The changes worth knowing about.','New discoveries and updates from the devices you watch.'],overview:['Your network, in the clear.','Know what’s connected. Notice what changes. Make yourself at home.'],devices:['Every device. One familiar place.','Put names to devices and keep your network feeling like home.'],activity:['The little things that change.','A running record of discoveries, sightings, and devices you recognize.'],settings:['Make yourself at home.','Connect your local network and choose how Lantern keeps watch.']};
async function api(path, method='GET', body) {
 const response=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-Lantern':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json(); if(!response.ok) throw new Error(data.error || 'This request could not be completed.'); return data;
}
function toast(message) {$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
function ago(value) {if(!value)return 'Never';const seconds=Math.max(0,(Date.now()-new Date(value).getTime())/1000);if(seconds<60)return 'Just now';if(seconds<3600)return Math.floor(seconds/60)+'m ago';if(seconds<86400)return Math.floor(seconds/3600)+'h ago';return Math.floor(seconds/86400)+'d ago';}
const timeLabel=v=>new Date(v).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const displayName=d=>d.label||d.hostname||'Unrecognized device';
function stats() {const d=state.devices;return {total:d.length,online:d.filter(d=>d.online).length,trusted:d.filter(d=>d.trusted).length,review:d.filter(d=>!d.trusted).length};}
function renderHeader(){
 const [title,description]=titles[page];$('#page-title').textContent=title;$('#page-description').textContent=description;
 $('#breadcrumb').textContent=page[0].toUpperCase()+page.slice(1);document.title=`${$('#breadcrumb').textContent} · Lantern`;
 document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.dataset.page===page);if(a.dataset.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('#nav-count').textContent=state.devices.length;
 const unread=state.alerts.filter(a=>!a.read).length;$('#alert-count').textContent=unread;$('#alert-count').hidden=!unread;
 $('#activity-dot').hidden=!stats().review;
 $('#mode-banner').classList.toggle('live-banner',!state.demo);
 $('#mode-banner').innerHTML=state.demo?'<div><span class="demo-pill">DEMO SPACE</span><span>You’re exploring a sample network. Your real devices haven’t been scanned.</span></div><button id="connect-button">Connect my network <span>↗</span></button>':`<div><span class="demo-pill">LIVE NETWORK</span><span>Discovering devices on <strong>${esc(state.config.network)}</strong>. All data stays on this computer.</span></div><button id="connect-button">Network settings <span>↗</span></button>`;
 $('#connect-button').onclick=()=>location.hash='settings';
 const scanning=state.scan.running||requestPending;$('#scan-button').disabled=scanning;
 $('#scan-button').classList.toggle('scanning',scanning);$('#scan-label').textContent=scanning?'Scanning…':state.demo?'Run demo scan':'Scan network';
 $('#error-banner').hidden=!state.scan.error;$('#error-banner').textContent=state.scan.error?`Scan could not finish: ${state.scan.error}`:'';
}
function metric(label,value,iconName,note,cls='') {return `<article class="metric ${cls}"><div class="metric-top"><span>${label}</span><span class="metric-icon">${icon(iconName)}</span></div><div class="metric-value">${value}<span>${cls==='review'&&value?'to recognize':''}</span></div><div class="metric-note">${note}</div></article>`;}
function activeInterface(){
 const [address,prefix]=state.config.network.split('/');
 const toInt=ip=>ip.split('.').reduce((n,v)=>(n<<8)|Number(v),0)>>>0;
 if(!address||!prefix)return null;
 const mask=(0xffffffff << (32-Number(prefix)))>>>0;
 return state.interfaces.find(i=>(toInt(i.ip)&mask)===(toInt(address)&mask));
}
function overview(){
 const s=stats(),last=state.scans.at(-1),network=state.demo?'192.168.1.0/24':state.config.network||'Not configured';
 return `<section class="metrics" aria-label="Network summary">${metric('Devices seen',s.online,'devices',`<span class="green-dot"></span> Responded to the latest scan`)}${metric('Trusted devices',s.trusted,'shield','A familiar face on your network')}${metric('Needs a look',s.review,'search',s.review?'A quick hello goes a long way.':'You recognize every device.','review')}${metric('Last scan',last?timeLabel(last.at):'—','clock',last?`${ago(last.at)} <span class="metric-zone">${state.demo?'Sample network':'Local time'}</span>`:'Your first scan is a click away.')}</section>
 <div class="overview-grid"><section class="panel network-panel"><div class="panel-heading"><div><h2>Your little corner of the internet</h2><p>A snapshot of your local network.</p></div><span class="soft-badge">${state.demo?'Sample network':'Local network'}</span></div><div class="network-map"><div class="map-line line-left"></div><div class="map-line line-right"></div><div class="map-node node-internet"><div class="node-circle">${icon('wifi')}</div><span>Local network</span><small>${esc(network)}</small></div><div class="map-node node-router"><div class="router-illustration"><i></i><i></i><div>${icon('router')}<span><b></b><b></b><b></b></span></div></div><span>${state.demo?'Home gateway':'Discovery host'}</span><small>${state.demo?'192.168.1.1':esc(activeInterface()?.ip||'Not connected')}</small></div><div class="map-node node-devices"><div class="node-circle green">${icon('devices')}<b>${s.online}</b></div><span>Devices seen</span><small>${s.total-s.online} not seen recently</small></div></div><div class="network-bottom"><span><i></i>${state.scan.running?'Discovery in progress':last?'Last scan completed':'Ready when you are'}</span><span>${state.demo?'Illustrative topology':'IPv4 discovery'} <span class="footer-dot">·</span> ${state.config.interval?`Every ${state.config.interval/60} min`:'Manual scans'}</span></div></section>
 <section class="panel review-panel"><div class="review-symbol">${icon(s.review?'search':'shield')}</div><span class="eyebrow">A FAMILIAR NETWORK IS A HAPPY ONE</span><h2>${s.review===1?'One unfamiliar face.':s.review===2?'A couple of new faces.':s.review?'A few unfamiliar faces.':'Looking familiar.'}</h2><p>${s.review?`You have ${s.review} device${s.review===1?'':'s'} to recognize. Give them a name so they feel a little more at home.`:'Keep your inventory up to date by naming devices and marking the ones you recognize.'}</p><button class="button dark" id="review-button">Review devices ${icon('arrow')}</button></section></div>
 ${watchPanel()}
 ${devicePanel(true)}
 <div class="bottom-grid"><section class="panel"><div class="panel-heading"><div><h2>Recent activity <span class="subtle-count">${state.events.length}</span></h2><p>The latest little changes.</p></div><a class="text-link" href="#activity">View all ${icon('chevron')}</a></div>${eventList(state.events.slice(0,4))}</section><section class="panel scan-history"><div class="panel-heading"><div><h2>Discovery history</h2><p>Devices responding per scan.</p></div><span class="soft-badge">${state.demo?'DEMO':'LOCAL'}</span></div>${historyChart()}<div class="chart-foot">${icon('info')} Scan results show visibility, not bandwidth or internet speed.</div></section></div>`;
}
function devicePanel(compact=false){
 const s=stats();return `<section class="panel device-panel"><div class="panel-heading"><div><h2>${compact?'Your devices':'Device inventory'} <span class="subtle-count">${s.total}</span></h2><p>A place for everything connected.</p></div><button class="button secondary export-button">${icon('download')} Export</button></div><div class="table-toolbar"><div class="tabs" role="group" aria-label="Filter devices">${[['all','All devices',s.total],['online','Seen',s.online],['review','Needs a look',s.review],['trusted','Trusted',s.trusted],['watched','Watched',state.devices.filter(d=>d.watched).length]].map(([key,label,count])=>`<button class="filter-button ${filter===key?'selected':''}" data-filter="${key}" aria-pressed="${filter===key}">${label}<span>${count}</span></button>`).join('')}</div><label class="room-filter"><span class="sr-only">Filter by room</span><select id="room-filter"><option value="">All rooms</option>${[...new Set(state.devices.map(d=>d.room).filter(Boolean))].sort().map(r=>`<option value="${esc(r)}" ${roomFilter===r?'selected':''}>${esc(r)}</option>`).join('')}</select></label><label class="search">${icon('search')}<input id="search" type="search" aria-label="Search devices" placeholder="Search devices…" value="${esc(query)}"></label></div><div id="device-table">${deviceTable(compact)}</div>${compact?'<div class="table-footer"><span>Good to know: a sleeping device may not respond to a scan.</span><a class="text-link" href="#devices">All devices '+icon('chevron')+'</a></div>':'<div class="table-footer"><span>Discovery is best effort. Not seen ≠ disconnected.</span><span>Click a device to edit its details.</span></div>'}</section>`;
}
function filteredDevices(){return state.devices.filter(d=>(filter==='all'||filter==='online'&&d.online||filter==='review'&&!d.trusted||filter==='trusted'&&d.trusted||filter==='watched'&&d.watched)&&(!roomFilter||d.room===roomFilter)&&[d.label,d.hostname,d.ip,d.mac,d.room,d.notes].join(' ').toLowerCase().includes(query.toLowerCase())).sort((a,b)=>b.online-a.online||a.ip.localeCompare(b.ip,undefined,{numeric:true}));}
function deviceTable(compact=false){
 const all=filteredDevices(),devices=compact?all.slice(0,5):all;
 if(!devices.length)return `<div class="empty-state">${icon('devices')}<h3>${state.devices.length?'No matching devices':'A clear view starts with a scan.'}</h3><p>${state.devices.length?'Try another search or filter.':'Choose your network in Settings, then run your first scan.'}</p>${state.devices.length?'':'<a class="button secondary" href="#settings">Set up network</a>'}</div>`;
 return `<div class="table-scroll"><table><thead><tr><th>DEVICE</th><th>IP ADDRESS</th><th>STATUS</th><th>RECOGNITION</th><th>LAST SEEN</th><th><span class="sr-only">Details</span></th></tr></thead><tbody>${devices.map(d=>`<tr><td><button class="device-name" data-device="${d.id}"><span class="device-icon ${d.kind}">${icon(d.kind)}</span><span><strong>${esc(displayName(d))}${d.watched?icon('eye','watch-mini'):''}</strong><small>${esc(d.room||d.mac||'MAC not available')}</small></span></button></td><td class="mono">${esc(d.ip)}</td><td><span class="status ${d.online?'online':'offline'}"><i></i>${d.online?'Seen':'Not seen'}</span></td><td><span class="trust ${d.trusted?'trusted':'unrecognized'}">${icon(d.trusted?'shield':'search')}${d.trusted?'Trusted':'Needs a look'}</span></td><td class="last-seen">${ago(d.last_seen)}</td><td><button class="icon-button row-arrow" data-device="${d.id}" aria-label="Edit ${esc(displayName(d))}">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>`;
}
function eventList(events){
 if(!events.length)return '<div class="empty-state"><h3>No changes just yet.</h3><p>Discoveries and recognition updates will appear here.</p></div>';
 return `<div class="event-list">${events.map(e=>`<div class="event"><span class="event-icon ${e.type}">${icon(e.type==='trusted'?'shield':e.type==='discovered'?'plus':e.type==='returned'?'wifi':'clock')}</span><div><strong>${esc(e.label||e.hostname||e.ip||'Device')}</strong><p>${esc(e.message)}</p></div><time datetime="${esc(e.at)}" title="${esc(new Date(e.at).toLocaleString())}">${ago(e.at)}</time></div>`).join('')}</div>`;
}
function historyChart(){
 const scans=state.scans.slice(-18);if(!scans.length)return '<div class="empty-state"><h3>Your history starts here.</h3><p>Run a scan to begin tracking visible devices.</p></div>';
 const max=Math.max(4,...scans.map(s=>s.count)),width=520,height=110,barWidth=Math.min(40,400/scans.length),gap=(width-40)/scans.length;
 return `<div class="chart-number">${scans.at(-1).count}<span>devices in the latest scan</span></div><svg class="history-chart" viewBox="0 0 520 150" role="img" aria-label="Devices responding per scan: ${scans.map(s=>s.count).join(', ')}"><path d="M10 30H510 M10 65H510 M10 100H510 M10 135H510" stroke="#e9eee7" stroke-dasharray="4 4"/>${scans.map((s,i)=>{const h=Math.max(2,s.count/max*height);return `<rect x="${20+i*gap}" y="${135-h}" width="${barWidth}" height="${h}" rx="4" fill="${i===scans.length-1?'#9ab663':'#dce8ca'}"><title>${esc(timeLabel(s.at))}: ${s.count} devices</title></rect>`;}).join('')}</svg><div class="chart-labels"><span>${timeLabel(scans[0].at)}</span><span>${scans.length} recorded scan${scans.length===1?'':'s'}</span><span>${timeLabel(scans.at(-1).at)}</span></div>`;
}
function watchPanel(){
 const devices=state.devices.filter(d=>d.watched);
 return `<section class="panel watch-panel"><div class="panel-heading"><div><h2>Keeping an eye on <span class="subtle-count">${devices.length}</span></h2><p>${devices.length?'Status from successful scans. Failed scans do not count as misses.':'Open a device and turn on Watch to track your printer, server, or hub.'}</p></div>${icon('eye')}</div>${devices.length?`<div class="watch-grid">${devices.map(d=>`<button class="watch-card" data-device="${d.id}"><span class="device-icon">${icon(d.kind)}</span><span><strong>${esc(displayName(d))}</strong><small>${esc(d.room||d.ip)}</small><span class="watch-status ${d.online?'trusted':d.watch_alerted?'unrecognized':''}">${d.online?'Responded':`${d.misses} missed scan${d.misses===1?'':'s'}${d.watch_alerted?' · alert raised':''}`}</span></span>${icon('chevron')}</button>`).join('')}</div>`:''}<div class="watch-foot">Alerts after each device’s missed-scan threshold; a return alert follows recovery. Last scan: ${state.scans.length?ago(state.scans.at(-1).at):'not yet run'}.</div></section>`;
}
function alertPanel(){
 const unread=state.alerts.filter(a=>!a.read).length;
 return `<section class="panel alert-panel"><div class="panel-heading"><div><h2>Alert inbox <span class="subtle-count">${unread} unread</span></h2><p>First scans establish a baseline. New discoveries after that can raise alerts.</p></div><button class="button secondary" id="read-all" ${unread?'':'disabled'}>Mark all read</button></div>${state.alerts.length?`<div class="alert-list">${state.alerts.map(a=>`<article class="alert-row ${a.read?'':'unread'}"><span class="event-icon ${a.kind}">${icon(a.kind==='new_device'?'plus':a.kind==='watch_returned'?'wifi':'eye')}</span><div><button class="alert-device" data-device="${a.device_id}">${esc(a.label||a.hostname||a.ip)}</button>${a.room?`<span class="alert-room">${esc(a.room)}</span>`:''}<p>${esc(a.message)}</p><small>${esc(new Date(a.created).toLocaleString())}${state.demo?' · Demo':''}</small></div>${a.read?'<span class="read-label">Read</span>':`<button class="button secondary read-alert" data-alert="${a.id}">Mark read</button>`}</article>`).join('')}</div>`:'<div class="empty-state">'+icon('bell')+'<h3>Nothing needs your attention.</h3><p>New devices after your baseline scan and watched-device changes will appear here. Alerts stay saved even while the browser is closed.</p></div>'}<div class="table-footer"><span>Unread ≠ unsafe. Discovery is best effort. Latest 1,000 alerts retained.</span><a class="text-link" href="#settings">Notification settings →</a></div></section>`;
}
function notificationPanel(){
 const permission=notifier.permission;
 const enabled=notifier.enabled&&permission==='granted';
 return `<section class="panel notification-panel"><div class="panel-heading"><div><h2>Desktop notifications</h2><p>${enabled?'Enabled in this browser':permission==='denied'?'Blocked in browser settings':permission==='unsupported'?'Not supported in this browser':'Optional · alert inbox is always available'}</p></div>${icon('bell')}</div><div class="settings-section"><p>Get a desktop notification for new devices and watched-device changes while a Lantern tab is open. Background tabs may be delayed by your browser.</p><button class="button secondary" id="desktop-toggle" ${permission==='unsupported'?'disabled':''}>${enabled?'Turn off desktop notifications':permission==='denied'?'Check notification permission':'Enable desktop notifications'}</button><small>With the tab closed, the server still records alerts. Open the inbox to review them later. Desktop delivery is best effort.</small></div></section>`;
}
function routerPanel(){
 const r=state.router;
 return `<section class="panel router-panel"><div class="panel-heading"><div><h2>Router lease connection</h2><p>dnsmasq / compatible OpenWrt DHCP lease snapshots</p></div>${icon('router')}</div><div class="settings-section">${state.demo?'<p>Switch to live mode to connect router lease data.</p>':`<div class="router-status"><span class="soft-badge">${esc(r.source==='none'?'NOT CONNECTED':r.source.toUpperCase())}</span><span>${r.stale?'Snapshot is stale':r.updated?'Updated '+ago(r.updated):'No lease snapshot yet'}</span></div><p>A lease lists an address assigned by your router. It does not prove the device is connected now. Fresh matching leases can supply device names during scans.</p>${r.error?`<p class="router-error" role="alert">${esc(r.error)}</p>`:''}${r.source==='dnsmasq file'?'<button class="button secondary" id="refresh-router">Refresh lease file</button>':`<form id="router-form"><label class="field">Paste a dnsmasq lease export<textarea name="leases" rows="4" maxlength="65536" required spellcheck="false" placeholder="expiry MAC IP hostname client-id"></textarea></label><button type="submit" class="button secondary">Import snapshot</button><small>Manual snapshots stay in memory until server restart. Use --leases-file with a regularly synced file for ongoing updates.</small></form>`}${r.leases.length?`<div class="lease-table table-scroll"><table><thead><tr><th>DHCP NAME</th><th>ASSIGNED IP</th><th>LEASE EXPIRY</th></tr></thead><tbody>${r.leases.map(l=>`<tr><td>${esc(l.hostname||l.mac)}</td><td class="mono">${esc(l.ip)}</td><td>${l.expires?esc(new Date(l.expires).toLocaleString()):'No expiry'}</td></tr>`).join('')}</tbody></table></div>`:r.configured?'<p>No unexpired IPv4 leases in this subnet.</p>':''}${r.skipped?`<small>${r.skipped} invalid row(s) ignored.</small>`:''}`}</div></section>`;
}
function settings(){return `<div class="settings-layout"><section class="panel settings-panel"><div class="panel-heading"><div><h2>Your network connection</h2><p>Choose what Lantern watches and how often.</p></div>${icon('wifi')}</div><form id="settings-form"><label class="field">Workspace mode<select name="mode"><option value="demo" ${state.demo?'selected':''}>Demo · explore a sample network</option><option value="live" ${!state.demo?'selected':''}>Live · discover my local network</option></select></label><label class="field">Local subnet<input name="network" value="${esc(state.config.network)}" placeholder="192.168.1.0/24" list="network-options" autocomplete="off"><small>A directly connected private IPv4 subnet, /24 through /30.</small></label><datalist id="network-options">${state.interfaces.map(i=>`<option value="${esc(i.cidr)}">${esc(i.name)} · ${esc(i.ip)}</option>`).join('')}</datalist><label class="field">Scan schedule<select name="interval">${[[0,'Manual scans only'],[60,'Every minute'],[300,'Every 5 minutes']].map(([v,l])=>`<option value="${v}" ${state.config.interval===v?'selected':''}>${l}</option>`).join('')}</select></label><label class="checkbox-field"><input type="checkbox" name="resume_schedule" ${state.config.resume_schedule?'checked':''}><span>Resume this schedule when Lantern starts<small>Enable for an always-on computer. Scans run even when the browser is closed.</small></span></label><label class="checkbox-field"><input type="checkbox" name="alert_new" ${state.config.alert_new?'checked':''}><span>Alert on newly discovered devices<small>The first scan of a subnet sets the baseline. Watching devices works independently.</small></span></label><div class="settings-note">${icon('info')}<span>Missed responses may mean sleep or a firewall. Only scan networks you own or have permission to monitor.</span></div><button class="button primary" type="submit" ${state.scan.running?'disabled':''}>Save settings ${icon('check')}</button></form></section><div>${notificationPanel()}<section class="panel interface-panel"><div class="panel-heading"><div><h2>Local interfaces</h2><p>Detected on this computer.</p></div></div>${state.interfaces.length?state.interfaces.map(i=>`<div class="interface-row"><span class="device-icon">${icon('computer')}</span><div><strong>${esc(i.name)}</strong><span class="mono">${esc(i.ip)}</span><small>${esc(i.cidr)}</small></div></div>`).join(''):'<div class="empty-state"><p>No supported private interfaces detected. Connect to Wi-Fi or Ethernet, then restart Lantern.</p></div>'}</section><section class="settings-help"><span class="eyebrow">KEEP A LIGHT ON</span><h3>Built for an always-on home.</h3><p>Use the included service generator for macOS login or Linux / Raspberry Pi startup. Choose a schedule and enable resume before installing the service.</p><p>On a remote Linux host, reach this private dashboard through an SSH tunnel to localhost:8765. Setup commands are in the project README.</p><button class="text-link" id="settings-about">How Lantern works ↗</button></section></div></div>${routerPanel()}`;}

function render(){
 if(!state)return; renderHeader();
 $('#page-content').innerHTML=page==='overview'?overview():page==='devices'?watchPanel()+devicePanel():page==='alerts'?alertPanel():page==='activity'?`<section class="panel activity-panel"><div class="panel-heading"><div><h2>Network journal</h2><p>${state.demo?'Sample activity':'Local observations'} · latest 100 events</p></div><button class="button secondary export-button">${icon('download')} Export</button></div>${eventList(state.events)}</section>`:settings();
 bindContent();
}
function bindDeviceButtons(){document.querySelectorAll('[data-device]').forEach(b=>b.onclick=()=>openDevice(Number(b.dataset.device)));}
function bindContent(){
 bindDeviceButtons();
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;render();});
 const search=$('#search');if(search)search.oninput=()=>{query=search.value;$('#device-table').innerHTML=deviceTable(page==='overview');bindDeviceButtons();};
 document.querySelectorAll('.export-button').forEach(b=>b.onclick=exportData);
 if($('#review-button'))$('#review-button').onclick=()=>{filter='review';query='';location.hash='devices';};
 if($('#settings-about'))$('#settings-about').onclick=()=>$('#about-dialog').showModal();
 if($('#settings-form'))$('#settings-form').onsubmit=saveSettings;
 if($('#room-filter'))$('#room-filter').onchange=e=>{roomFilter=e.target.value;render();};
 document.querySelectorAll('.read-alert').forEach(b=>b.onclick=()=>ackAlerts([Number(b.dataset.alert)]));
 if($('#read-all'))$('#read-all').onclick=()=>ackAlerts();
 if($('#desktop-toggle'))$('#desktop-toggle').onclick=async()=>{try{if(notifier.enabled&&notifier.permission==='granted'){notifier.setEnabled(false);toast('Desktop notifications turned off.');}else{await notifier.enable();toast('Desktop notifications enabled for this browser.');}render();await notifier.deliver(state);}catch(e){toast(e.message);}};
 if($('#router-form'))$('#router-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await api('router/import','POST',{text:e.target.elements.leases.value});await refresh();toast('Lease snapshot imported. Run a scan to match device names.');}catch(e){toast(e.message);b.disabled=false;}};
 if($('#refresh-router'))$('#refresh-router').onclick=async()=>{try{await api('router/refresh','POST',{});await refresh();toast('Router source checked.');}catch(e){toast(e.message);}};
}
function openDevice(id){
 const d=state.devices.find(d=>d.id===id);if(!d)return;selectedId=id;
 const form=$('#device-form');form.elements.label.value=d.label||'';form.elements.kind.value=d.kind;form.elements.trusted.checked=!!d.trusted;form.elements.room.value=d.room||'';form.elements.notes.value=d.notes||'';
 form.elements.watched.checked=!!d.watched;form.elements.miss_threshold.value=String(d.miss_threshold);
 $('#room-options').innerHTML=[...new Set(state.devices.map(d=>d.room).filter(Boolean))].sort().map(r=>`<option value="${esc(r)}"></option>`).join('');
 $('#device-info').innerHTML=`<div class="device-detail-hero"><span class="device-icon">${icon(d.kind)}</span><div><strong>${esc(displayName(d))}</strong><small>${esc(d.ip)} · ${d.online?'Seen in latest scan':'Not seen in latest scan'}</small></div></div><dl class="detail-grid"><div><dt>MAC address</dt><dd>${esc(d.mac||'Not available')}</dd></div><div><dt>Response time</dt><dd>${d.latency===null?'Not available':esc(d.latency)+' ms'}</dd></div><div><dt>First discovered</dt><dd>${esc(new Date(d.first_seen).toLocaleString())}</dd></div><div><dt>Last seen</dt><dd>${esc(new Date(d.last_seen).toLocaleString())}</dd></div></dl>`;
 $('#device-dialog').showModal();
}
async function ackAlerts(ids){try{await api('alerts/ack','POST',ids?{ids}:{});await refresh();}catch(e){toast(e.message);}}
async function refresh(renderPage=true){state=await api('state');if(renderPage)render();else renderHeader();}
async function saveSettings(e){e.preventDefault();const form=e.target,button=form.querySelector('[type=submit]');button.disabled=true;try{state=await api('settings','PATCH',{mode:form.elements.mode.value,network:form.elements.network.value.trim(),interval:Number(form.elements.interval.value),resume_schedule:form.elements.resume_schedule.checked,alert_new:form.elements.alert_new.checked});render();toast('Settings saved. Your workspace is ready.');}catch(e){toast(e.message);button.disabled=false;}}
async function exportData(){try{const data=await api('export'),blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`lantern-${data.demo?'demo':'live'}-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Network snapshot exported.');}catch(e){toast(e.message);}}
$('#device-form').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('[type=submit]');b.disabled=true;try{await api('devices/'+selectedId,'PATCH',{label:f.elements.label.value.trim(),kind:f.elements.kind.value,trusted:f.elements.trusted.checked,room:f.elements.room.value.trim(),notes:f.elements.notes.value.trim(),watched:f.elements.watched.checked,miss_threshold:Number(f.elements.miss_threshold.value)});$('#device-dialog').close();await refresh();toast('A little more familiar. Device updated.');}catch(e){toast(e.message);}finally{b.disabled=false;}};
$('#scan-button').onclick=async()=>{requestPending=true;renderHeader();try{await api('scan','POST',{});await refresh();toast(state.demo?'Sample scan started.':'Local discovery started. This can take around 20 seconds.');}catch(e){toast(e.message);}finally{requestPending=false;renderHeader();}};
function route(){const next=location.hash.slice(1);page=Object.hasOwn(titles,next)?next:'overview';query='';roomFilter='';render();}
window.addEventListener('hashchange',route);
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
for(const id of ['about-button','help-button'])$('#'+id).onclick=()=>$('#about-dialog').showModal();
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
hydrateIcons();
(async()=>{try{await refresh(false);route();}catch(e){$('#page-content').innerHTML='<div class="panel empty-state"><h2>Couldn’t reach Lantern.</h2><p>Make sure the local server is running, then reload this page.</p></div>';toast(e.message);}})();
let polling=false;
setInterval(async()=>{
 if(polling||!state)return;polling=true;
 try{const next=await api('state');const changed=JSON.stringify([next.devices,next.events,next.scan,next.config,next.alerts,next.router])!==JSON.stringify([state.devices,state.events,state.scan,state.config,state.alerts,state.router]);
 if(state.scan.running&&!next.scan.running&&!next.scan.error)toast('Scan complete. Your network view is up to date.');
 state=next;
 await notifier.deliver(state).catch(e=>toast('Desktop delivery unavailable. Your alerts are saved in the inbox.'));
 if(changed){const editing=page==='settings'||$('#search')===document.activeElement||$('#device-dialog').open;if(!editing)render();else renderHeader();}else renderHeader();
 }catch(e){$('#error-banner').hidden=false;$('#error-banner').textContent='Connection lost. Keep the local server running; Lantern will reconnect automatically.';}finally{polling=false;}
},2500);
