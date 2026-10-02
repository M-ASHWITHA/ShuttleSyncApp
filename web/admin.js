'use strict';
const kpi = (l, v) => `<div class="card kpi"><small>${l}</small><b>${v}</b></div>`;
async function refresh() {
  const a = await api('/admin/insights'), k = a.kpis;
  setHTML($('kpis'), kpi('Avg wait time', `${k.avg_wait_minutes} min`) + kpi('Trips today', k.trips_today.toLocaleString('en-IN'))
    + kpi('Fleet utilization', `${k.fleet_utilization_pct}%`) + kpi('Pay Later dues outstanding', `₹${k.paylater_outstanding.toLocaleString('en-IN')}`));
  const h = a.heatmap;
  setHTML($('hm'), `<span></span>${h.slots.map((s) => `<span class="col-h">${s}</span>`).join('')}` + h.rows.map((r) =>
    `<span class="row-h">${r.name}</span>` + r.cells.map((c) => `<span class="cell l${c.level}" title="${r.name} · ${Math.round(c.pressure * 100)}% of fleet capacity (~${c.demand} students/h)"></span>`).join('')).join(''));
  $('realloc').textContent = a.reallocation.message; $('eff').textContent = a.efficiency.message;
  $('alertsCard').style.display = a.alerts.length ? 'block' : 'none';
  setHTML($('alerts'), a.alerts.map((x) => `<div class="r">${esc(x.message)}</div>`).join(''));
}
refresh().catch(() => toast('Cannot reach the server. Is it running?'));
setInterval(() => { if (!document.hidden) refresh().catch(console.error); }, 3000);
