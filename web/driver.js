'use strict';
let skipStop = null;
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
async function init() {
  const list = await api('/driver/shuttles');
  $('shuttleSel').innerHTML = list.map((s) => `<option value="${s.id}">${s.name} · Route ${s.route_code}</option>`).join('');
  const saved = localStorage.getItem('ss.driver'); if (saved && list.some((s) => s.id === saved)) $('shuttleSel').value = saved;
  refresh(); setInterval(() => { if (!document.hidden) refresh().catch(console.error); }, 2000);
}
function badge(r) {
  const w = r.waiting, cls = w === 0 ? 'zero' : w >= 5 ? 'hi' : 'lo';
  return `<span class="wb ${cls}">${w} waiting</span>`;
}
async function refresh() {
  const id = $('shuttleSel').value, o = await api(`/driver/${id}/overview`);
  $('pill').textContent = o.status_pill;
  const cl = $('capLabel'); cl.textContent = o.status_label;
  cl.style.color = o.load === 'FULL' ? 'var(--red)' : o.load === 'STANDING' ? 'var(--amber)' : 'var(--green)';
  $('capNum').textContent = `${o.occupancy} of ${o.capacity} onboard`;
  const s = o.suggestion; skipStop = s && s.type === 'SKIP' ? s.stop_id : null;
  $('aiCard').classList.toggle('alert', !!s && s.type === 'ALERT');
  $('aiText').textContent = s ? s.message : 'All upcoming stops need service. No changes suggested.';
  const sb = $('skipBtn'); sb.style.display = skipStop ? 'inline-flex' : 'none'; if (skipStop) sb.textContent = `Skip ${s.stop}`;
  const p = o.paylater_today;
  $('plTotal').textContent = plural(p.total, 'trip');
  $('plSub').textContent = p.pending ? `${p.pending} awaiting verification` : 'All verified at boarding';
  setHTML($('stops'), o.upcoming.map((r) => `<div class="srow ${r.recommendation === 'SKIP' ? 'skip' : ''}"><i></i><span class="nm">${esc(r.stop)}</span>
      <span class="eta">${fmtEtaShort(r.eta_seconds)}</span>${badge(r)}</div>`).join(''));
  const q = $('queue'); q.classList.toggle('hide', !o.queue.length); q.style.display = o.queue.length ? 'block' : 'none';
  setHTML($('qList'), o.queue.map((t) => `<div class="qrow"><div><b>${esc(t.student_id)}</b><span>${t.kind === 'cash'
      ? `Cash ₹${t.fare} · ${t.cash_elapsed_minutes || 0} min ago` : 'Pay Later boarding · verify ID'}</span></div>
      <button class="btn sm" data-trip="${t.id}" data-kind="${t.kind}">${t.kind === 'cash' ? 'Confirm cash' : 'Verify'}</button></div>`).join(''));
}
$('skipBtn').onclick = async () => {
  try { await post(`/driver/${$('shuttleSel').value}/skip`, {stop_id: skipStop}); toast('Skip noted — passengers on board are unaffected.'); }
  catch (e) { toast(errMsg(e)); } refresh();
};
document.addEventListener('click', async (e) => {
  const b = e.target.closest('button[data-trip]'); if (!b) return;
  b.classList.add('busy'); const path = b.dataset.kind === 'cash' ? 'confirm-cash' : 'verify';
  try { await post(`/driver/${$('shuttleSel').value}/trips/${b.dataset.trip}/${path}`); toast(b.dataset.kind === 'cash' ? 'Cash payment confirmed ✓' : 'Boarding verified ✓'); }
  catch (err) { toast(errMsg(err)); } refresh();
});
$('shuttleSel').onchange = () => { localStorage.setItem('ss.driver', $('shuttleSel').value); refresh(); };
init().catch(() => toast('Cannot reach the server. Is it running?'));
