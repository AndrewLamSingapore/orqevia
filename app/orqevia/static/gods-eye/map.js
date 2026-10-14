(function () {
  'use strict';
  const canvas = document.getElementById('map');
  const ctx = canvas.getContext('2d');
  function lonToX(lon) { return (lon + 180) / 360 * canvas.width; }
  function latToY(lat) { return (90 - lat) / 180 * canvas.height; }
  function drawGrid() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#15304d'; ctx.lineWidth = 1;
    for (let lon = -180; lon <= 180; lon += 30) {
      ctx.beginPath(); ctx.moveTo(lonToX(lon), 0); ctx.lineTo(lonToX(lon), canvas.height); ctx.stroke();
    }
    for (let lat = -90; lat <= 90; lat += 30) {
      ctx.beginPath(); ctx.moveTo(0, latToY(lat)); ctx.lineTo(canvas.width, latToY(lat)); ctx.stroke();
    }
  }
  async function refresh() {
    const status = document.getElementById('status');
    status.textContent = 'LOADING';
    try {
      const res = await fetch('/api/orqevia/intelligence/geo/events?limit=500', { headers: { Accept: 'application/json' } });
      const body = await res.json();
      const records = Array.isArray(body.records) ? body.records : [];
      drawGrid();
      document.getElementById('count').textContent = records.length + ' observations';
      const list = document.getElementById('events'); list.replaceChildren();
      records.forEach(function (r) {
        const loc = r.location || {};
        if (typeof loc.lat !== 'number' || typeof loc.lon !== 'number') return;
        ctx.fillStyle = '#5cc8ff';
        ctx.beginPath(); ctx.arc(lonToX(loc.lon), latToY(loc.lat), 4, 0, Math.PI * 2); ctx.fill();
        const li = document.createElement('li');
        li.textContent = (r.place || r.event_id) + ' · M' + r.magnitude + ' · ' + r.observed_at + ' · ' + r.source + ' · ingested ' + r.ingested_at;
        list.appendChild(li);
      });
      status.textContent = 'OK';
    } catch (e) {
      status.textContent = 'DEGRADED';
    }
  }
  document.getElementById('refresh').addEventListener('click', refresh);
  refresh();
})();
