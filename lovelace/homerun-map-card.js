/*! HomeRun Map Card — an interactive robot-vacuum map for Home Assistant.
 *  Renders the vector map from the HomeRun Local backend (rooms, walls, robot,
 *  dock, last path), lets you tap rooms to select them, and clean / dock / find
 *  right from the dashboard. Vanilla custom element, no build step.
 *
 *  Card config:
 *    type: custom:homerun-map-card
 *    url: http://192.168.1.50:8787   # optional; defaults to <this-host>:8787
 *    title: Subhiyya                  # optional
 */
const PALETTE = ['#38bdf8', '#f472b6', '#4ade80', '#fbbf24', '#a78bfa',
  '#fb923c', '#2dd4bf', '#f87171', '#60a5fa', '#c084fc'];

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
`;

class HomerunMapCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._url = (this._config.url || `${location.protocol}//${location.hostname}:8787`).replace(/\/$/, '');
    this._selected = new Set();
    this._vec = null;
    this._state = null;
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
      <div class="hm-map" data-map></div>
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

    this._load();
    this._loadState();
    this._t1 = setInterval(() => this._load(), 8000);
    this._t2 = setInterval(() => this._loadState(), 4000);
  }
  disconnectedCallback() { clearInterval(this._t1); clearInterval(this._t2); }

  async _load() {
    try {
      const r = await fetch(`${this._url}/api/map/vector`, { cache: 'no-store' });
      const vec = await r.json();
      if (vec && vec.ok) { this._vec = vec; this._renderMap(); this._syncBar(); }
      else this._mapEl.innerHTML = `<div class="hm-err">${(vec && vec.error) || 'No map yet — run a mapping pass.'}</div>`;
    } catch (e) {
      this._mapEl.innerHTML = `<div class="hm-err">Can't reach the robot backend at ${this._url}.<br>Set <code>url:</code> in the card config.</div>`;
    }
  }
  async _loadState() {
    try {
      const s = await (await fetch(`${this._url}/api/state`, { cache: 'no-store' })).json();
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
    // walls (single path)
    if (vec.walls && vec.walls.length) {
      const wp = vec.walls.map(([x, y]) => `M${x} ${y}h1v1h-1z`).join('');
      s += `<path d="${wp}" fill="#0b1220" fill-opacity="0.9"/>`;
    }
    // last path
    if (vec.path && vec.path.length > 1) {
      s += `<path d="M${vec.path.map((p) => `${p[0]} ${p[1]}`).join('L')}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="0.6"/>`;
    }
    // dock + robot
    const mark = (p, c) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${c}" fill-opacity="0.28"/><circle cx="${p[0]}" cy="${p[1]}" r="2" fill="${c}" stroke="#fff" stroke-width="0.5"/>`;
    if (vec.charger_px) s += mark(vec.charger_px, '#22c55e');
    if (vec.robot_px) s += mark(vec.robot_px, '#38bdf8');
    // labels (one per group)
    for (const room of vec.rooms || []) {
      if (this._grp(room) !== room.id) continue;
      const [x, y] = room.centroid;
      s += `<text x="${x}" y="${y}" text-anchor="middle" font-size="6" font-weight="600" fill="#0b1220" stroke="#fff" stroke-width="1.6" paint-order="stroke" style="pointer-events:none">${room.name}</text>`;
    }
    s += '</svg>';
    if (vec.robot_px) s += `<div class="hm-hint">Robot = last known position (live isn't available locally)</div>`;
    this._mapEl.innerHTML = s;
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
      await fetch(`${this._url}${path}`, {
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

customElements.define('homerun-map-card', HomerunMapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'homerun-map-card',
  name: 'HomeRun Map',
  description: 'Interactive robot-vacuum map: tap rooms to clean, dock, or locate.'
});
console.info('%c HOMERUN-MAP-CARD %c loaded ', 'background:#0ea5e9;color:#031;font-weight:700', '');
