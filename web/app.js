/* ShuttleSync student app - screens: permissions · where to · live tracking · shuttle detail · payment · pay later · profile */
'use strict';

const APPS = ['Google Pay', 'PhonePe', 'Paytm'];
const S = {
  screen: null, stops: [], stop: localStorage.getItem('ss.stop'), shuttle: null, opts: [], track: null, state: null,
  sid: localStorage.getItem('ss.sid') || '25BAI0204', name: localStorage.getItem('ss.name') || 'Shri Nithi',
  ui: {}, recent: {}, waitKey: null, railKey: null, lastP: 0, timeout: 600,
};
const enc = () => encodeURIComponent(S.sid);
const stopName = (id) => (S.stops.find((s) => s.id === id) || {}).name || '';
const fmtTimeout = (s) => (s >= 60 ? `${Math.round(s / 60)} min` : `${s} sec`);
const fmtTimeoutLong = (s) => (s >= 60 ? `${Math.round(s / 60)} minutes` : `${s} seconds`);

/* ================= navigation ================= */
const TAB_ICON = {live: 'bus', payment: 'card', paylater: 'clock', profile: 'user'};
function go(name) {
  if ((name === 'live' || name === 'detail') && !S.stop) name = 'where';
  if (name === 'detail' && !S.shuttle) name = 'live';
  S.screen = name;
  history.replaceState(null, '', '#' + name);
  document.querySelectorAll('.screen').forEach((s) => {
    const on = s.id === 's-' + name; s.classList.remove('on');
    if (on) { void s.offsetWidth; s.classList.add('on'); }
  });
  if (name === 'where') markTiles();
  renderNav(); window.scrollTo(0, 0); refresh();
}
function renderNav() {
  const nav = $('nav'), hidden = ['permissions', 'detail'].includes(S.screen);
  nav.classList.toggle('hide', hidden); if (hidden) return;
  const tabs = S.screen === 'where' ? ['payment', 'paylater', 'profile'] : ['live', 'payment', 'paylater', 'profile'];
  const key = tabs.join();
  if (nav._key !== key) {
    $('navBtns').innerHTML = tabs.map((t) => `<button data-tab="${t}" aria-label="${t}">${ICON[TAB_ICON[t]]}</button>`).join('');
    nav._key = key;
  }
  const active = S.screen === 'where' ? -1 : tabs.indexOf(S.screen);
  [...$('navBtns').children].forEach((b, i) => b.classList.toggle('on', i === active));
  const bub = $('bubble'); bub.style.opacity = active < 0 ? 0 : 1;
  if (active >= 0) bub.style.left = ((active + 0.5) / tabs.length) * 100 + '%';
}
async function refresh() {
  try {
    switch (S.screen) {
      case 'live': await loadLive(); break;
      case 'detail': await Promise.all([loadTrack(), loadState()]); renderDetailButtons(); break;
      case 'payment': await loadState(); renderPayment(); break;
      case 'paylater': await loadState(); renderPayLater(); break;
      case 'profile': await loadState(); renderProfile(); break;
    }
  } catch (e) { console.error(e); }
}
const tick = () => { if (!document.hidden && ['live', 'detail', 'payment', 'paylater', 'profile'].includes(S.screen)) refresh(); };

async function loadState() {
  const prev = S.state, st = await api(`/students/${enc()}/state`);
  if (prev) prev.dues.forEach((d) => {
    if (!st.dues.some((x) => x.id === d.id)) {
      const t = st.history.find((h) => h.id === d.id);
      if (t && t.status === 'paid') { S.recent[t.id] = {trip: t, at: Date.now()}; if (d.status === 'waiting' && t.method === 'cash') toast('Your driver confirmed the cash payment ✓'); }
    }
  });
  S.state = st; S.timeout = st.cash_timeout_seconds || 600;
}

/* ================= 1 · permissions ================= */
function setPerm(which, on) {
  $(which === 'loc' ? 'pcLoc' : 'pcBt').classList.toggle('on', on);
  const b = $(which === 'loc' ? 'allowLoc' : 'allowBt'); b.innerHTML = on ? ICON.check + 'Allowed' : 'Allow'; b.style.gap = '6px';
  b.querySelector('svg') && (b.querySelector('svg').style.cssText = 'width:15px;height:15px');
}
function finishPerms() { localStorage.setItem('ss.perms', '1'); go('where'); }
$('allowLoc').onclick = () => {
  if (!navigator.geolocation) return setPerm('loc', true);
  navigator.geolocation.getCurrentPosition(() => setPerm('loc', true),
    () => toast('Location is blocked - you can enable it in your browser settings.'), {timeout: 8000});
};
$('allowBt').onclick = () => setPerm('bt', true);   // onboard auto-detection needs a native app; the web demo uses "I'm in the shuttle"
$('permGo').onclick = () => { setPerm('loc', true); setPerm('bt', true); if (navigator.geolocation) navigator.geolocation.getCurrentPosition(() => {}, () => {}, {timeout: 5000}); setTimeout(finishPerms, 350); };
$('permSkip').onclick = finishPerms;

/* ================= 2 · where to ================= */
function buildTiles() {
  $('tiles').innerHTML = S.stops.map((s) => `<button class="tile" data-stop="${s.id}"><span class="pin">${ICON.pin}</span><b>${esc(s.name)}</b><span class="tick">${ICON.check}</span></button>`).join('');
}
function markTiles() { document.querySelectorAll('.tile').forEach((t) => t.classList.toggle('sel', !!S.stop && t.dataset.stop === S.stop)); }
document.addEventListener('click', (e) => {
  const t = e.target.closest('.tile'); if (!t) return;
  S.stop = t.dataset.stop; localStorage.setItem('ss.stop', S.stop); markTiles();
  setTimeout(() => go('live'), 420);
});

/* ================= 3 · live tracking ================= */
const clockSvg = svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.4 2"/>');
function rcHTML(o, first) {
  const full = o.is_full;
  return `<button class="rc ${first && !full ? 'first' : ''} ${full ? 'full' : ''}" data-id="${o.shuttle_id}">
    <div class="row"><span class="t">${esc(o.route_name)} · ${esc(o.path)}</span><span class="badge ${full ? 'full' : 'avail'}">${o.badge}</span></div>
    <div class="eta">${clockSvg}<span>${fmtAway(o.eta_seconds)}</span></div></button>`;
}
async function loadLive() {
  const d = await api(`/stops/${S.stop}/options`); S.opts = d.options;
  $('goingTo').textContent = d.stop;
  setHTML($('first'), d.options.length ? rcHTML(d.options[0], true) : `<div class="empty">No shuttles serve this stop right now.</div>`);
  setHTML($('others'), d.options.slice(1).map((o) => rcHTML(o, false)).join(''));
  $('alsoLbl').style.display = d.options.length > 1 ? 'block' : 'none';
}
$('changeStop').onclick = () => go('where');
document.addEventListener('click', (e) => {
  const c = e.target.closest('.rc[data-id]'); if (!c) return;
  c.classList.add('sel'); S.shuttle = c.dataset.id; S.railKey = null;
  setTimeout(() => go('detail'), 300);
});

/* ================= 4 · shuttle detail ================= */
const DONUT = {SEATS_AVAILABLE: ['#146c42', 'Seats available'], FILLING: ['#b7791f', 'Filling up'], STANDING: ['#904110', 'Standing only'], FULL: ['#b5221a', 'Full']};
async function loadTrack() {
  const t = await api(`/shuttles/${S.shuttle}/track?stop_id=${S.stop}`); S.track = t; renderDetail(t);
}
function renderRail(t) {
  const f = t.stop_fractions, last = f[f.length - 1] || 1, pos = f.map((x) => x / last);
  if (S.railKey !== t.route_id) {
    let html = '<div class="line"></div><div class="fill" id="fill"></div>', prevRow = 1, prevPos = -1;
    t.stops.forEach((s, i) => {
      const row = i > 0 && pos[i] - prevPos < 0.26 && prevRow === 1 ? 2 : 1; prevRow = row; prevPos = pos[i];
      html += `<span class="dot" style="left:${pos[i] * 100}%"></span><span class="lb ${row === 2 ? 'r2' : ''}" style="left:${pos[i] * 100}%">${esc(s.name)}</span>`;
    });
    $('rail').innerHTML = html + `<div class="bus" id="bus">${ICON.bus}</div>`; $('rail').classList.toggle('two', html.includes('lb r2')); S.railKey = t.route_id; S.lastP = 0;
  }
  let p = t.progress / last; if (p > 1) p = 0;           // heading back to the first stop
  const bus = $('bus'), fill = $('fill'), jump = p < S.lastP - 0.3;
  if (jump) { bus.classList.add('jump'); fill.style.transition = 'none'; }
  bus.style.left = p * 100 + '%'; fill.style.width = p * 100 + '%';
  if (jump) { void bus.offsetWidth; bus.classList.remove('jump'); fill.style.transition = ''; }
  S.lastP = p;
}
function renderDetail(t) {
  $('dRoute').textContent = t.route_name; $('dPath').textContent = t.path;
  renderRail(t);
  const eta = (t.target || t.upcoming[0]).eta_seconds;
  $('dArr').textContent = 'Arriving at ' + stopName(S.stop); $('dEta').textContent = fmtMins(eta);
  const sc = $('dSched'); sc.textContent = t.schedule; sc.classList.toggle('warn', t.schedule !== 'On schedule');
  const [color, label] = DONUT[t.load] || DONUT.SEATS_AVAILABLE, C = 2 * Math.PI * 32, off = C * (1 - t.occupancy / t.capacity);
  const d = $('donut');
  if (!d._built) {
    d.innerHTML = `<svg viewBox="0 0 76 76"><circle class="trk" cx="38" cy="38" r="32" fill="none" stroke-width="7"/><circle class="arc" cx="38" cy="38" r="32" fill="none" stroke-width="7" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg><div class="in"></div>`;
    d._built = true; d._C = C;
    requestAnimationFrame(() => requestAnimationFrame(() => { d.querySelector('.arc').style.strokeDashoffset = off; }));
  }
  const arc = d.querySelector('.arc'); arc.style.stroke = color; arc.style.strokeDashoffset = off;
  setHTML(d.querySelector('.in'), `<b style="color:${color}">${label}</b><small>${t.occupancy}/${t.capacity}</small>`);
  $('dCapTxt').textContent = t.free > 0 ? `${t.free} more ${t.free === 1 ? 'person' : 'people'} can get in.` : 'This shuttle is full.';
  setHTML($('dUps'), t.upcoming.slice(0, 3).map((u) => `<div class="r"><span>${esc(u.stop)}</span><span>${fmtEtaShort(u.eta_seconds)}</span></div>`).join(''));
}
function renderDetailButtons() {
  const key = `${S.stop}|${S.shuttle}`, w = $('btnWait'), b = $('btnIn');
  const waiting = S.waitKey === key;
  w.classList.toggle('sel', waiting); setHTML(w, waiting ? `${ICON.check}<span>You're waiting here</span>` : `<span>I'm waiting here</span>`);
  const t = S.state && S.state.today_trip, onboard = !!(t && t.shuttle_id === S.shuttle && t.onboard);
  b.classList.toggle('sel-green', onboard); b.classList.toggle('green-outline', !onboard);
  setHTML(b, onboard ? `${ICON.check}<span>You're onboard</span>` : `<span>I'm in the shuttle</span>`);
}
function hint(msg, cls) { const h = $('dHint'); h.textContent = msg || ''; h.className = 'hint ' + (cls || ''); }
$('backLive').innerHTML = ICON.back;
$('backLive').onclick = () => { hint(''); go('live'); };
$('btnWait').onclick = async () => {
  try {
    const r = await post(`/stops/${S.stop}/checkin`, {student_id: S.sid, route_id: S.track && S.track.route_id});
    S.waitKey = `${S.stop}|${S.shuttle}`; renderDetailButtons();
    hint(r.counted ? 'Driver notified — we\'ll see you at the stop.' : 'Already sent a moment ago.', 'ok');
  } catch (e) { hint(errMsg(e), 'err'); }
};
$('btnIn').onclick = async () => {
  const b = $('btnIn'); if (b.classList.contains('busy')) return; b.classList.add('busy');
  try {
    await post(`/students/${enc()}/board`, {shuttle_id: S.shuttle, stop_id: S.stop});
    await loadState(); renderDetailButtons(); hint("You're onboard — pay your fare in Payment.", 'ok');
    setTimeout(() => go('payment'), 950);
  } catch (e) {
    if (e.code === 'CLEAR_DUES_FIRST') openSheet('Pay Later limit reached', e.message);
    else hint(errMsg(e), 'err');
  } finally { b.classList.remove('busy'); }
};
function openSheet(title, text) { $('shTitle').textContent = title; $('shText').textContent = text; $('veil').classList.add('on'); }
const closeSheet = () => $('veil').classList.remove('on');
$('shClose').onclick = closeSheet; $('veil').onclick = (e) => { if (e.target === $('veil')) closeSheet(); };
$('shGo').onclick = () => { closeSheet(); hint(''); go('paylater'); };

/* ================= 5 & 6 · payment + pay later (shared state machine) ================= */
const NOTE = {
  pay: "UPI payments confirm instantly. Cash payments need your driver to confirm once you've handed it over.",
  payUpi: 'UPI payments redirect to your chosen app and confirm instantly once the payment succeeds.',
  payCash: () => `Cash payments need your driver to confirm once you've handed it over. No confirmation within ${fmtTimeoutLong(S.timeout)} marks the trip Unpaid.`,
  later: "UPI payments confirm instantly. Cash payments need your driver to confirm once you've handed it over.",
  laterCash: "Cash on Pay Later only unlocks once you're onboard, and still needs your driver's confirmation in-app.",
};
function tagFor(t, ui) {
  const m = t.status === 'paid' ? t.method : t.status === 'waiting' ? 'cash' : ui.upi ? 'upi' : '';
  return m === 'upi' ? '<span class="tag upi">UPI</span>' : m === 'cash' ? '<span class="tag cash">Cash</span>' : '';
}
function paidBox(t, layout) {
  const when = t.paid_at ? fmtDateTime(t.paid_at) : '';
  let txt;
  if (t.method === 'pass') txt = 'Covered by your digital pass ✓';
  else if (layout === 'later') txt = `₹${t.fare} paid via ${t.method === 'upi' ? t.upi_app : 'Cash'} ✓ — nothing pending`;
  else txt = t.method === 'upi' ? `Paid via ${esc(t.upi_app)} ✓ — show this to your driver` : 'Paid via Cash ✓ — confirmed by your driver';
  return `<div class="stbox green"><div><b>${txt}</b><small>${when}</small></div></div>`;
}
function upiBox(t, ui) {
  const opening = ui.upi === 'opening';
  return `<div class="stbox lav"><b>${opening ? `<span class="spin"></span>Opening ${esc(ui.app)}…` : 'Opening UPI app...'}</b>
    <small>${opening ? 'Confirm the payment in your UPI app' : 'Choose the app to complete payment'}</small>
    <div class="upi-row">${APPS.map((a) => `<button class="upi ${ui.app === a ? 'sel' : ''}" data-act="app" data-app="${a}" data-trip="${t.id}" ${opening ? 'disabled' : ''}>${a}</button>`).join('')}</div></div>`;
}
function cashWaitingBox(t, layout) {
  const m = t.cash_elapsed_minutes || 0;
  return `<div class="stbox peach"><b>Cash selected — ask your driver to confirm once you've paid.</b><small>${m >= 1 ? m + ' min elapsed' : 'Just sent to your driver'}</small>
    ${layout === 'pay' ? `<button class="btn" data-act="check" data-trip="${t.id}">Driver confirms payment</button>
    <button class="lnk" data-act="timeout" data-trip="${t.id}">No response after ${fmtTimeout(t.cash_timeout_seconds)} →</button>` : ''}</div>`;
}
function actionHTML(t, layout) {
  const ui = S.ui[t.id] || {};
  if (t.status === 'paid') return paidBox(t, layout);
  if (ui.upi) return upiBox(t, ui);
  if (t.status === 'waiting') return cashWaitingBox(t, layout);
  let html = '';
  if (t.cash_expired) html += layout === 'pay'
    ? `<div class="stbox red"><b>Cash payment not confirmed — moved to Pay Later</b><small><button class="lnk" style="margin:0;color:inherit" data-go="paylater">→ appears in Pay Later page as due</button></small></div>`
    : `<div class="stbox red"><b>Cash not confirmed — still unpaid, ask driver to confirm again</b><small>Stays on Pay Later as due</small></div>`;
  const noCash = !t.onboard || ui.notOnboard;
  const upiBtn = `<button class="btn green" data-act="upi" data-trip="${t.id}">Pay via UPI</button>`;
  const cashBtn = `<button class="btn outline" data-act="cash" data-trip="${t.id}">Pay with Cash</button>`;
  html += `<div class="actions ${layout === 'pay' ? 'col' : ''}" style="${t.cash_expired ? 'margin-top:12px' : ''}">${upiBtn}${noCash ? '' : cashBtn}</div>`;
  if (noCash) html += `<div class="stbox grey" style="margin-top:10px"><b>Board the shuttle to pay by cash</b><small><s>Pay with Cash</s></small></div>`;
  return html;
}
const wide = (t) => t.paylater === false ? '<p class="desc" style="color:var(--pink-ink);font-weight:500">Pay Later limit reached for today — please pay for this trip now.</p>' : '';

function renderPayment() {
  const t = S.state && S.state.today_trip, tag = $('payTag');
  let body, note = NOTE.pay, tg = '';
  if (!t) body = `<div class="empty">No trip yet today.<br>Board a shuttle to see your fare here.<br><button class="btn sm" style="margin-top:14px" data-go="where">Find a shuttle</button></div>`;
  else {
    const ui = S.ui[t.id] || {}; tg = tagFor(t, ui);
    body = `<div class="tcard"><div class="r1"><b>${esc(t.label)}</b><span>${fmtTime(t.created_at)}</span></div><hr>
      <div class="fare"><span>Fare</span><b>₹${t.fare}</b></div>${actionHTML(t, 'pay')}${wide(t)}</div>`;
    note = t.status === 'waiting' || (t.status === 'unpaid' && (!t.onboard || ui.notOnboard)) ? NOTE.payCash() : ui.upi ? NOTE.payUpi : NOTE.pay;
  }
  setHTML($('payBody'), body); setHTML(tag, tg); $('payNote').textContent = note;
}
function renderPayLater() {
  const dues = S.state ? S.state.dues.slice() : [];
  const rec = Object.values(S.recent).filter((r) => Date.now() - r.at < 9000 && !dues.some((d) => d.id === r.trip.id)).map((r) => r.trip);
  const items = [...rec, ...dues].sort((a, b) => b.id - a.id);
  let note = NOTE.later, tg = '';
  if (!items.length) setHTML($('plBody'), `<div class="empty">Nothing due — all your trips are settled ✓</div>`);
  else {
    tg = tagFor(items[0], S.ui[items[0].id] || {});
    setHTML($('plBody'), items.map((t) => {
      const ui = S.ui[t.id] || {}, cash = t.status === 'waiting' || t.method === 'cash';
      const desc = t.paylater === false ? 'Pay Later limit reached for today — please pay for this trip now.'
        : cash ? 'You chose to pay later for this trip and are paying by cash.'
          : 'You chose to pay later for this trip — settle here, or show cash to your driver at boarding.';
      return `<div class="tcard pl"><div class="r1"><b>${esc(t.label)}</b><span class="badge ${t.status === 'paid' ? 'paid' : 'unpaid-solid'}">${t.status === 'paid' ? 'Paid' : 'Unpaid'}</span></div>
        <p class="desc">${desc}</p><div class="fare"><span>Fare</span><b>₹${t.fare}</b></div>${actionHTML(t, 'later')}</div>`;
    }).join(''));
    if (items.some((t) => t.status !== 'paid' && (t.status === 'waiting' || !t.onboard || (S.ui[t.id] || {}).notOnboard))) note = NOTE.laterCash;
  }
  setHTML($('plTag'), tg); $('plNote').textContent = note;
}
const rerenderPay = () => { if (S.screen === 'payment') renderPayment(); else if (S.screen === 'paylater') renderPayLater(); };

document.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const id = Number(el.dataset.trip), act = el.dataset.act;
  try {
    if (act === 'upi') { S.ui[id] = {upi: 'choose'}; rerenderPay(); }
    else if (act === 'app') {
      const app = el.dataset.app; S.ui[id] = {upi: 'opening', app}; rerenderPay();
      await new Promise((r) => setTimeout(r, 1700));                       // "Opening <UPI app>…" then the app confirms
      try {
        const t = await post(`/students/${enc()}/trips/${id}/pay-upi`, {app});
        delete S.ui[id]; S.recent[id] = {trip: t, at: Date.now()}; await loadState(); rerenderPay(); toast(`Paid via ${app} ✓`);
      } catch (err) { S.ui[id] = {upi: 'choose'}; rerenderPay(); toast(errMsg(err)); }
    } else if (act === 'cash') {
      try { await post(`/students/${enc()}/trips/${id}/pay-cash`); await loadState(); }
      catch (err) { if (err.code === 'NOT_ONBOARD') S.ui[id] = {notOnboard: true}; else toast(errMsg(err)); }
      rerenderPay();
    } else if (act === 'check') {
      el.classList.add('busy'); await loadState(); rerenderPay();
      const t = S.state.history.find((h) => h.id === id);
      toast(t && t.status === 'paid' ? 'Your driver confirmed the payment ✓' : 'Not confirmed yet — please ask your driver to confirm.');
    } else if (act === 'timeout') {
      await loadState(); rerenderPay();
      const t = S.state.history.find((h) => h.id === id);
      if (t && t.status === 'waiting') toast(`Still within the ${fmtTimeout(t.cash_timeout_seconds)} window — ${Math.ceil(t.cash_remaining_seconds / 60)} min left.`);
    }
  } catch (err) { toast(errMsg(err)); }
});

/* ================= 7 · profile ================= */
const initials = (n) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
function bindProfile() {
  $('pfName').value = S.name; $('pfId').value = S.sid; $('avatar').textContent = initials(S.name);
  $('pfName').onchange = () => { S.name = $('pfName').value.trim() || S.name; localStorage.setItem('ss.name', S.name); $('avatar').textContent = initials(S.name); };
  $('pfId').onchange = () => { S.sid = $('pfId').value.trim() || S.sid; localStorage.setItem('ss.sid', S.sid); S.state = null; refresh(); };
}
function renderProfile() {
  const h = S.state ? S.state.history : [];
  setHTML($('hist'), !h.length ? `<div class="empty">No trips today yet.<br>Pick a stop to find your shuttle.</div>` : h.map((t) => {
    const due = t.status !== 'paid';
    return `<div class="hist ${due ? 'due' : ''}"><div class="r1"><b>${esc(t.label)}</b><span class="badge ${due ? (t.status === 'waiting' ? 'wait' : 'unpaid') : 'paid'}">${due ? (t.status === 'waiting' ? 'Waiting' : 'Unpaid') : 'Paid'}</span></div>
      <div class="r2">${fmtTime(t.created_at)}${due ? (t.status === 'waiting' ? ' · Cash awaiting driver confirmation' : ' · Marked Pay Later on this trip') : ''}</div>
      ${due ? `<div class="r3"><b>₹${t.fare} due</b><button class="btn red sm" data-go="paylater">Pay now</button></div>` : ''}</div>`;
  }).join(''));
}

/* ================= global clicks + boot ================= */
document.addEventListener('click', (e) => {
  const g = e.target.closest('[data-go]'); if (g) go(g.dataset.go);
  const n = e.target.closest('#navBtns button');
  if (n) { const t = n.dataset.tab; go(t === 'live' ? (S.stop ? 'live' : 'where') : t); }
});
const SCREENS = ['where', 'live', 'detail', 'payment', 'paylater', 'profile'];
window.addEventListener('hashchange', () => { const w = location.hash.slice(1); if (SCREENS.includes(w) && w !== S.screen) go(w); });
(async function init() {
  document.querySelectorAll('[data-ic]').forEach((el) => { el.innerHTML = ICON[el.dataset.ic]; });
  try { S.stops = await api('/stops'); } catch (e) { toast('Cannot reach the server. Is it running?'); return; }
  buildTiles(); bindProfile();
  const want = location.hash.slice(1);
  go(SCREENS.includes(want) ? want : (localStorage.getItem('ss.perms') ? 'where' : 'permissions'));
  setInterval(tick, 2500);
})();
