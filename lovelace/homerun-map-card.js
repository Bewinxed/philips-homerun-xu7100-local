/*! HomeRun Map Card v0.5.0 — an interactive robot-vacuum map for Home Assistant.
 *  Renders the vector map from the HomeRun Local backend (rooms, walls, the
 *  robot's no-go zones and virtual walls, robot, dock, last path), lets you
 *  tap rooms to select them, switch floors and layers, and clean / dock / find
 *  right from the dashboard. Vanilla custom element, no build step.
 *
 *  The card only talks to Home Assistant itself (same origin, your login), so it
 *  works on homeassistant.local, through Home Assistant Cloud and on a custom
 *  domain, and the app needs no open port:
 *    - proxy:   the Philips HomeRun (Local) integration's authenticated proxy
 *               (/api/homerun_local/proxy/...); works for every user
 *    - ingress: the app's Supervisor ingress (/api/hassio_ingress/...); needs an
 *               administrator, like every ingress page
 *    - auto (default): proxy, falling back to ingress when the integration
 *               isn't set up
 *
 *  Card config:
 *    type: custom:homerun-map-card
 *    title: Timmy                     # optional
 *    connection: auto                 # optional; auto | proxy | ingress
 *    entry: <config entry id>         # optional; proxy, only with more than one robot
 *    app: 7b10aef2_homerun-local      # optional; ingress, the app's slug (found by itself)
 *    url: http://192.168.1.50:8787   # optional; call the backend directly (needs its port open)
 *    hide: [route, nogo]              # optional; layers hidden until tapped in the legend
 *                                     # (walls, nogo, nomop, vwalls, route, dock, robot, labels)
 */
// Own scope: a second copy (an old resource next to the Marketplace one) must
// not clash on these names, and define() below skips if the card already exists.
(() => {
const PALETTE = ['#38bdf8', '#f472b6', '#4ade80', '#fbbf24', '#a78bfa',
  '#fb923c', '#2dd4bf', '#f87171', '#60a5fa', '#c084fc'];
const NOGO = '#ef4444';
const NOMOP = '#3b82f6';
const LAYERS_KEY = 'homerun-map-card.layers';
// legend entries: [layer, label, swatch svg]
const LEGEND = [
  ['walls', 'Walls', '<rect x="1" y="1" width="10" height="10" rx="1" fill="#0b1220" stroke="#94a3b8" stroke-width=".8"/>'],
  ['nogo', 'No-go zones', `<rect x="1" y="1" width="10" height="10" rx="1" fill="${NOGO}" fill-opacity=".3" stroke="${NOGO}"/>`],
  ['nomop', 'No-mop zones', `<rect x="1" y="1" width="10" height="10" rx="1" fill="${NOMOP}" fill-opacity=".3" stroke="${NOMOP}"/>`],
  ['vwalls', 'Virtual walls', `<line x1="1.5" y1="10.5" x2="10.5" y2="1.5" stroke="${NOGO}" stroke-width="2" stroke-linecap="round"/>`],
  ['route', 'Last route', '<path d="M1 9 Q4 2 6 6 T11 3" fill="none" stroke="currentColor" stroke-width="1.4"/>'],
  ['dock', 'Dock', '<circle cx="6" cy="6" r="4" fill="#22c55e" stroke="#fff"/>'],
  ['robot', 'Last position', '<circle cx="6" cy="6" r="4" fill="#38bdf8" stroke="#fff"/>'],
  ['labels', 'Room names', '<text x="6" y="9.5" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">A</text>'],
];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const CSS = `
  .hm { padding: 8px 12px 12px; }
  .hm-top { display:flex; align-items:center; gap:10px; padding:6px 4px 10px; }
  .hm-state { font-weight:600; font-size:1rem; }
  .hm-sub { color: var(--secondary-text-color); font-size:.8rem; }
  .hm-batt { margin-left:auto; font-variant-numeric:tabular-nums; font-weight:600; }
  .hm-map { position:relative; border-radius:14px; overflow:hidden;
            background:#0e1626; aspect-ratio: var(--hm-ar, 1); }
  .hm-map svg { width:100%; height:100%; display:block; }
  .hm-room { cursor:pointer; transition:fill-opacity .12s; }
  .hm-hint { position:absolute; inset:auto 0 8px 0; text-align:center;
             color:#cbd5e1; font-size:.72rem; pointer-events:none;
             text-shadow:0 1px 2px #000; }
  .hm-bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding-top:10px; }
  .hm-sel { color: var(--secondary-text-color); font-size:.82rem; margin-right:auto; }
  .hm-btn { border:none; border-radius:999px; padding:.5rem .9rem; font-weight:600;
            font-size:.82rem; cursor:pointer; display:inline-flex; align-items:center; gap:.4rem;
            background: var(--secondary-background-color); color: var(--primary-text-color);
            transition: transform .1s, filter .2s; }
  .hm-btn:active { transform: scale(.96); }
  .hm-btn[disabled] { opacity:.45; cursor:default; }
  .hm-btn.primary { background: var(--primary-color); color:#0b1220; }
  .hm-err { color: var(--error-color, #f87171); padding:24px; text-align:center; font-size:.85rem; }
  .hm-chips { display:flex; flex-wrap:wrap; gap:6px; align-items:center; padding:0 0 8px; font-size:.78rem; }
  .hm-chips:empty { display:none; }
  .hm-legend { padding:8px 0 0; }
  .hm-chip { border:1px solid var(--divider-color, #334155); border-radius:999px; padding:.25rem .65rem;
             background:none; color: var(--primary-text-color); cursor:pointer; font:inherit;
             display:inline-flex; align-items:center; gap:.35rem; }
  .hm-chip svg { width:12px; height:12px; }
  .hm-chip.on { background: color-mix(in srgb, var(--primary-color) 22%, transparent); border-color: var(--primary-color); }
  .hm-chip.off { opacity:.4; text-decoration: line-through; }
  .hm-chip small { color: var(--secondary-text-color); }
  .hm-chips .hm-lbl { color: var(--secondary-text-color); margin-right:2px; }
`;

class HomerunMapCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._url = this._config.url ? this._config.url.replace(/\/$/, '') : null;
    this._selected = new Set();
    this._vec = null;
    this._state = null;
    this._floors = [];
    this._floor = null;
    const hidden = new Set(this._config.hide || []);
    this._layers = Object.fromEntries(LEGEND.map(([l]) => [l, !hidden.has(l)]));
    try { Object.assign(this._layers, JSON.parse(localStorage.getItem(LAYERS_KEY) || '{}')); } catch (e) { /* defaults */ }
  }
  set hass(hass) { this._hass = hass; if (!this._built) this._build(); }
  getCardSize() { return 9; }
  static getConfigElement() { return document.createElement('div'); }
  static getStubConfig() { return { type: 'custom:homerun-map-card' }; }

  _build() {
    this._built = true;
    const card = document.createElement('ha-card');
    const style = document.createElement('style'); style.textContent = CSS;
    const root = document.createElement('div'); root.className = 'hm';
    root.innerHTML = `
      <div class="hm-top">
        <div>
          <div class="hm-state" data-state>—</div>
          <div class="hm-sub" data-sub></div>
        </div>
        <div class="hm-batt" data-batt></div>
      </div>
      <div class="hm-chips" data-floors></div>
      <div class="hm-map" data-map></div>
      <div class="hm-chips hm-legend" data-legend></div>
      <div class="hm-bar">
        <span class="hm-sel" data-sel>Tap rooms to select</span>
        <button class="hm-btn primary" data-act="clean" disabled>Clean selected</button>
        <button class="hm-btn" data-act="clear" disabled>Clear</button>
        <button class="hm-btn" data-act="home">Dock</button>
        <button class="hm-btn" data-act="locate">Find</button>
      </div>`;
    card.appendChild(style); card.appendChild(root);
    this.appendChild(card);
    this._root = root;
    this._mapEl = root.querySelector('[data-map]');

    root.querySelector('.hm-bar').addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]'); if (!b) return;
      const a = b.dataset.act;
      if (a === 'clean') this._clean();
      else if (a === 'clear') { this._selected.clear(); this._renderMap(); this._syncBar(); }
      else if (a === 'home') this._cmd('home');
      else if (a === 'locate') this._cmd('locate');
    });
    this._mapEl.addEventListener('click', (e) => {
      const p = e.target.closest('[data-room]'); if (!p) return;
      this._toggle(parseInt(p.dataset.room, 10));
    });
    root.querySelector('[data-floors]').addEventListener('click', (e) => {
      const b = e.target.closest('[data-floor]'); if (!b) return;
      this._selectFloor(parseInt(b.dataset.floor, 10));
    });
    root.querySelector('[data-legend]').addEventListener('click', (e) => {
      const b = e.target.closest('[data-layer]'); if (!b) return;
      const l = b.dataset.layer;
      this._layers[l] = !this._layers[l];
      try { localStorage.setItem(LAYERS_KEY, JSON.stringify(this._layers)); } catch (err) { /* per session only */ }
      this._renderMap();
    });

    this._loadFloors();
    this._load();
    this._loadState();
    this._t1 = setInterval(() => this._load(), 8000);
    this._t2 = setInterval(() => this._loadState(), 4000);
  }
  disconnectedCallback() { clearInterval(this._t1); clearInterval(this._t2); }

  // Every backend call goes through Home Assistant (see the header) unless a url is set
  async _fetch(path, init = {}) {
    if (this._url) return fetch(`${this._url}${path}`, { cache: 'no-store', ...init });
    const mode = this._config.connection || 'auto';
    if (mode !== 'ingress' && this._route !== 'ingress') {
      const sep = path.includes('?') ? '&' : '?';
      const p = `/api/homerun_local/proxy${path}${this._config.entry ? `${sep}entry=${encodeURIComponent(this._config.entry)}` : ''}`;
      const r = await this._hass.fetchWithAuth(p, { cache: 'no-store', ...init });
      if (mode === 'proxy' || !(await this._noProxy(r))) {
        this._route = 'proxy';
        return r;
      }
      this._route = 'ingress';   // auto: the integration isn't there, use the app's ingress
    }
    const base = await this._ingressBase();
    const r = await fetch(`${base}${path.slice(1)}`, { cache: 'no-store', credentials: 'same-origin', ...init });
    if (r.status === 401 || r.status === 403) {   // session expired: once more with a new one
      this._ingress = null;
      return fetch(`${await this._ingressBase()}${path.slice(1)}`, { cache: 'no-store', credentials: 'same-origin', ...init });
    }
    return r;
  }

  // A 404 that means "no proxy here": Home Assistant's own (plain text, the
  // integration isn't installed) or the view's "no HomeRun backend" (not set up).
  // A JSON 404 from the backend itself, e.g. "no stored map yet", is a real answer.
  async _noProxy(r) {
    if (r.status !== 404) return false;
    if (!(r.headers.get('content-type') || '').includes('json')) return true;
    const body = await r.clone().json().catch(() => ({}));
    return body.error === 'no HomeRun backend';
  }

  // Supervisor ingress: an ingress session cookie for /api/hassio_ingress/, the
  // same way Home Assistant opens an app's sidebar page (administrators only).
  async _ingressBase() {
    if (this._ingress && Date.now() < this._ingressUntil) return this._ingress;
    const sv = (endpoint, method = 'get') => this._hass.callWS({ type: 'supervisor/api', endpoint, method });
    let slug = this._config.app;
    if (!slug) {
      const apps = await sv('/addons');
      const found = (apps.addons || []).find((a) => /(^|_)homerun-local$/.test(a.slug) && a.state === 'started');
      if (!found) throw new Error('HomeRun Local app not found');
      slug = found.slug;
    }
    const info = await sv(`/addons/${slug}/info`);
    const session = await sv('/ingress/session', 'post');
    document.cookie = `ingress_session=${session.session}; path=/api/hassio_ingress/; SameSite=Strict`
      + (location.protocol === 'https:' ? '; Secure' : '');
    this._ingress = info.ingress_url || `${info.ingress_entry}/`;
    this._ingressUntil = Date.now() + 10 * 60 * 1000;   // sessions last 15 minutes
    return this._ingress;
  }

  async _load() {
    try {
      const r = await this._fetch('/api/map/vector');
      const vec = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      if (vec && vec.ok) { this._vec = vec; this._renderMap(); this._syncBar(); }
      else this._mapEl.innerHTML = `<div class="hm-err">${esc((vec && vec.error) || 'No map yet — run a mapping pass.')}</div>`;
    } catch (e) {
      console.warn('homerun-map-card:', e);
      this._mapEl.innerHTML = this._url
        ? `<div class="hm-err">Can't reach the robot backend at ${esc(this._url)}.</div>`
        : `<div class="hm-err">Can't reach the robot (${esc(e.message || e)}). Set up the Philips HomeRun (Local) integration, or use an administrator account for the app's ingress.</div>`;
    }
  }
  async _loadFloors() {
    try {
      const f = await (await this._fetch('/api/floors')).json();
      this._floors = (f && f.floors) || []; this._floor = f && f.selected;
    } catch (e) { this._floors = []; }
    this._renderFloors();
  }
  _renderFloors() {
    const el = this._root.querySelector('[data-floors]');
    el.innerHTML = this._floors.length < 2 ? '' : '<span class="hm-lbl">Floor</span>' + this._floors.map((f) =>
      `<button class="hm-chip ${f.id === this._floor ? 'on' : ''}" data-floor="${f.id}">${esc(f.name)}</button>`).join('');
  }
  // the floor choice is the backend's: the HA camera and the web UI follow it
  async _selectFloor(id) {
    if (id === this._floor) return;
    this._floor = id; this._selected.clear(); this._renderFloors(); this._syncBar();
    await this._post('/api/floors/select', { id });
    await this._fetch('/api/map/vector?force=1').catch(() => {});
    this._load();
  }
  async _loadState() {
    try {
      const s = await (await this._fetch('/api/state')).json();
      this._state = s; this._renderTop();
    } catch (e) { /* keep last */ }
  }

  _renderTop() {
    const s = this._state; if (!s) return;
    const LABEL = { idle: 'Idle', cleaning: 'Cleaning', paused: 'Paused',
      returning: 'Heading to dock', docked: 'Docked', charging: 'Charging', error: 'Needs a hand' };
    const COLOR = { cleaning: 'var(--primary-color)', returning: 'var(--primary-color)',
      charging: '#34d399', docked: '#34d399', paused: '#fbbf24', error: '#f87171',
      idle: 'var(--secondary-text-color)' };
    const st = s.state || 'idle';
    const el = this._root.querySelector('[data-state]');
    el.textContent = LABEL[st] || st; el.style.color = COLOR[st] || '';
    this._root.querySelector('[data-sub]').textContent =
      st === 'cleaning' ? `${s.clean_area || 0} m² · ${s.clean_time || 0} min this run` : (this._config.title || 'Philips HomeRun');
    this._root.querySelector('[data-batt]').textContent =
      (s.battery != null ? s.battery + '%' : '');
  }

  _ring(r) { return 'M' + r.map((p) => `${p[0]} ${p[1]}`).join('L') + 'Z'; }
  _grp(r) { return r.group != null ? r.group : r.id; }

  _renderMap() {
    const vec = this._vec; if (!vec) return;
    this._mapEl.style.setProperty('--hm-ar', (vec.width / vec.height).toFixed(3));
    const pad = 2;
    let s = `<svg viewBox="-${pad} -${pad} ${vec.width + 2 * pad} ${vec.height + 2 * pad}" preserveAspectRatio="xMidYMid meet" shape-rendering="geometricPrecision">`;
    // rooms
    for (const room of vec.rooms || []) {
      const col = PALETTE[this._grp(room) % PALETTE.length];
      const sel = this._selected.has(room.id);
      const d = (room.rings || []).map((r) => this._ring(r)).join(' ');
      s += `<path class="hm-room" data-room="${room.id}" d="${d}" fill="${col}" fill-rule="evenodd"
             fill-opacity="${sel ? 0.95 : 0.5}" stroke="${sel ? '#fff' : col}" stroke-width="${sel ? 1.2 : 0.5}"
             stroke-linejoin="round"/>`;
    }
    const L = this._layers;
    // walls (single path)
    if (L.walls && vec.walls && vec.walls.length) {
      const wp = vec.walls.map(([x, y]) => `M${x} ${y}h1v1h-1z`).join('');
      s += `<path d="${wp}" fill="#0b1220" fill-opacity="0.9"/>`;
    }
    // robot-side no-go zones + virtual walls (non-interactive)
    for (const z of vec.no_go_zones || []) {
      const nomop = z.mode === 2;
      if (!(nomop ? L.nomop : L.nogo)) continue;
      const col = nomop ? NOMOP : NOGO;
      s += `<path d="${this._ring(z.px)}" fill="${col}" fill-opacity="0.22" stroke="${col}" stroke-width="0.5" style="pointer-events:none"/>`;
    }
    for (const w of L.vwalls ? vec.virtual_walls || [] : []) {
      const [x1, y1, x2, y2] = w.px;
      s += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${NOGO}" stroke-width="1" stroke-linecap="round" style="pointer-events:none"/>`;
    }
    // last path
    if (L.route && vec.path && vec.path.length > 1) {
      s += `<path d="M${vec.path.map((p) => `${p[0]} ${p[1]}`).join('L')}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="0.6"/>`;
    }
    // dock + robot
    const mark = (p, c) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${c}" fill-opacity="0.28"/><circle cx="${p[0]}" cy="${p[1]}" r="2" fill="${c}" stroke="#fff" stroke-width="0.5"/>`;
    if (L.dock && vec.charger_px) s += mark(vec.charger_px, '#22c55e');
    if (L.robot && vec.robot_px) s += mark(vec.robot_px, '#38bdf8');
    // labels (one per group)
    for (const room of L.labels ? vec.rooms || [] : []) {
      if (this._grp(room) !== room.id) continue;
      const [x, y] = room.centroid;
      s += `<text x="${x}" y="${y}" text-anchor="middle" font-size="6" font-weight="600" fill="#0b1220" stroke="#fff" stroke-width="1.6" paint-order="stroke" style="pointer-events:none">${esc(room.name)}</text>`;
    }
    s += '</svg>';
    if (L.robot && vec.robot_px) s += `<div class="hm-hint">Last position of the last completed run (live isn't available locally)</div>`;
    this._mapEl.innerHTML = s;
    this._renderLegend();
  }
  // legend chips: how each layer is drawn, tap to show or hide it
  _renderLegend() {
    const vec = this._vec;
    const zones = vec.no_go_zones || [];
    const nNogo = zones.filter((z) => z.mode !== 2).length, nNomop = zones.length - nNogo;
    const present = { walls: vec.walls?.length, nogo: nNogo, nomop: nNomop, vwalls: vec.virtual_walls?.length,
      route: vec.path?.length > 1, dock: vec.charger_px, robot: vec.robot_px, labels: vec.rooms?.length };
    const count = { nogo: nNogo, nomop: nNomop, vwalls: vec.virtual_walls?.length };
    this._root.querySelector('[data-legend]').innerHTML = LEGEND.filter(([l]) => present[l]).map(([l, label, sw]) =>
      `<button class="hm-chip ${this._layers[l] ? '' : 'off'}" data-layer="${l}" aria-pressed="${!!this._layers[l]}">` +
      `<svg viewBox="0 0 12 12" aria-hidden="true">${sw}</svg>${label}${count[l] ? ` <small>${count[l]}</small>` : ''}</button>`).join('');
  }

  _toggle(id) {
    const room = this._vec.rooms.find((r) => r.id === id); if (!room) return;
    const g = this._grp(room);
    const members = this._vec.rooms.filter((r) => this._grp(r) === g).map((r) => r.id);
    const on = members.some((m) => this._selected.has(m));
    for (const m of members) on ? this._selected.delete(m) : this._selected.add(m);
    this._renderMap(); this._syncBar();
  }
  _syncBar() {
    const n = this._selected.size;
    this._root.querySelector('[data-sel]').textContent = n ? `${n} room${n > 1 ? 's' : ''} selected` : 'Tap rooms to select';
    this._root.querySelector('[data-act="clean"]').disabled = !n;
    this._root.querySelector('[data-act="clear"]').disabled = !n;
  }

  async _post(path, body) {
    try {
      await this._fetch(path, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body || {})
      });
    } catch (e) { /* surfaced via toast below */ this._toast('Command failed — backend unreachable'); }
  }
  async _clean() {
    if (!this._selected.size) return;
    const names = [...this._selected].map((id) => this._vec.rooms.find((r) => r.id === id)?.name).filter(Boolean);
    await this._post('/api/rooms/clean', { rooms: [...this._selected], passes: 1 });
    this._toast(`Cleaning ${names.join(', ') || 'selected rooms'}`);
    this._selected.clear(); this._renderMap(); this._syncBar();
  }
  async _cmd(action) {
    await this._post('/api/command', { action });
    this._toast(action === 'home' ? 'Sending it home' : 'Making it beep');
  }
  _toast(msg) {
    this.dispatchEvent(new CustomEvent('hass-notification', { detail: { message: msg }, bubbles: true, composed: true }));
  }
}

// Loaded twice (an old resource next to the Marketplace one) must not break the card
if (!customElements.get('homerun-map-card')) customElements.define('homerun-map-card', HomerunMapCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'homerun-map-card')) window.customCards.push({
  type: 'homerun-map-card',
  name: 'HomeRun Map',
  description: 'Interactive robot-vacuum map: floors, layers and a legend; tap rooms to clean, dock, or locate.'
});
console.info('%c HOMERUN-MAP-CARD %c loaded ', 'background:#0ea5e9;color:#031;font-weight:700', '');
})();
