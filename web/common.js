/* ShuttleSync - shared helpers (API, icons, formatting, ripple, toast) */
const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch('/api' + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw (j.detail && typeof j.detail === 'object' ? j.detail : {code: 'ERROR', message: j.detail || 'Something went wrong'});
  return j;
}
const post = (p, body) => api(p, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});

const svg = (inner, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${extra}>${inner}</svg>`;
const ICON = {
  bus: svg('<rect x="4.5" y="3.5" width="15" height="14" rx="3.2"/><path d="M4.5 11h15"/><path d="M8 20.5h.01M16 20.5h.01" stroke-width="3"/>'),
  card: svg('<rect x="2.5" y="5" width="19" height="14" rx="2.8"/><path d="M2.5 10h19"/>'),
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.4 2"/>'),
  user: svg('<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-4 3.4-6.2 7.5-6.2s7.5 2.2 7.5 6.2"/>'),
  pin: svg('<path d="M12 21.5s-7-6.3-7-11.6a7 7 0 1 1 14 0c0 5.3-7 11.6-7 11.6z"/><circle cx="12" cy="9.9" r="2.6"/>'),
  check: svg('<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="3"/>'),
  back: svg('<path d="M15 5l-7 7 7 7" stroke-width="2.4"/>'),
  bt: svg('<path d="M7 7.5l10 9-5 4.5V3l5 4.5-10 9"/>'),
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtTime(iso) { const d = new Date(iso); let h = d.getHours(); const m = String(d.getMinutes()).padStart(2, '0'); const ap = h >= 12 ? 'PM' : 'AM'; h = h % 12 || 12; return `${h}:${m} ${ap}`; }
function fmtDateTime(iso) { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${fmtTime(iso)}`; }
function fmtAway(s) { return s < 20 ? 'Arriving now' : `${Math.max(1, Math.ceil(s / 60))} min away`; }
function fmtMins(s) { if (s < 20) return 'Arriving now'; const n = Math.max(1, Math.ceil(s / 60)); return `${n} min${n > 1 ? 's' : ''}`; }
function fmtEtaShort(s) { return s < 20 ? 'now' : `${Math.max(1, Math.ceil(s / 60))} min`; }
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

/* only touch the DOM when the markup really changed (keeps hover / focus / animations smooth) */
function setHTML(el, html) { if (el._h !== html) { el.innerHTML = html; el._h = html; } }

let _toastT;
function toast(msg) {
  let t = $('toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add('on'); clearTimeout(_toastT); _toastT = setTimeout(() => t.classList.remove('on'), 3200);
}

/* material-style ripple on any pressable element */
document.addEventListener('pointerdown', (e) => {
  const el = e.target.closest('.btn, .pill-btn, .tile, .rc, .upi, .back, .nav button');
  if (!el || el.disabled) return;
  const r = el.getBoundingClientRect(), size = Math.max(r.width, r.height) * 2;
  const s = document.createElement('span'); s.className = 'rp';
  s.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
  el.appendChild(s); setTimeout(() => s.remove(), 650);
});
const errMsg = (e) => (e && e.message) || 'Something went wrong. Please try again.';
