/* Panasonic Cascade heating curve. MIT. No external scripts or chart dependencies. */
export const KEYS = ['water_max', 'outdoor_max', 'water_min', 'outdoor_min'];
export function temperatureAt(outdoor, v) {
  if (!KEYS.every(k => Number.isFinite(v[k])) || v.outdoor_min >= v.outdoor_max || v.water_min > v.water_max) return null;
  const ratio = Math.max(0, Math.min(1, (outdoor - v.outdoor_min) / (v.outdoor_max - v.outdoor_min)));
  return v.water_max + ratio * (v.water_min - v.water_max);
}
const LABELS = {
  en: { water_max: 'Max. water temperature', outdoor_max: 'Max. outdoor temperature', water_min: 'Min. water temperature', outdoor_min: 'Min. outdoor temperature',
    title: 'Zone 1 – Heating curve', apply: 'Apply', reset: 'Discard preview', preview: 'Preview — changes not applied', waiting: 'Waiting for controller values…',
    saved: 'Defaults sent. Schedules or overrides may change effective operation.', read: 'Read-only. Enable experimental controls to edit.', unavailable: 'Controller values unavailable.', invalid: 'Check limits: min. outdoor must be below max.; min. water must not exceed max.', water: 'Water', outdoor: 'Outdoor', failed: 'Could not apply all values. Check the controller before retrying.',
    current: 'Configured curve', saving: 'Applying…' },
  de: { water_max: 'Max. Wassertemperatur', outdoor_max: 'Max. Außentemperatur', water_min: 'Min. Wassertemperatur', outdoor_min: 'Min. Außentemperatur',
    title: 'Zone 1 – Heizkurve', apply: 'Übernehmen', reset: 'Vorschau verwerfen', preview: 'Vorschau – noch nicht übernommen', waiting: 'Warte auf Controllerwerte…',
    saved: 'Standardwerte gesendet. Zeitprogramme oder Übersteuerungen können abweichen.', read: 'Nur Anzeige. Zum Bearbeiten experimentelle Steuerungen aktivieren.', unavailable: 'Controllerwerte nicht verfügbar.', invalid: 'Grenzen prüfen: Min. außen muss unter Max. liegen; Min. Wasser darf Max. nicht überschreiten.', water: 'Wasser', outdoor: 'Außen', failed: 'Nicht alle Werte übernommen. Vor erneutem Versuch im Controller prüfen.',
    current: 'Eingestellte Kurve', saving: 'Wird übernommen…' }
};
export class HeatingCurveCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}); this._draft = {}; this._pending = {}; }
  setConfig(config) {
    if (!config.entities || !KEYS.every(k => /^(number|sensor)\.[a-z0-9_]+$/.test(config.entities[k] || ''))) throw new Error('Four heating curve entities are required');
    this._config = config; this._draft = {}; this._pending = {}; this._built = false;
    if (this._hass) this._render();
  }
  set hass(hass) {
    this._hass = hass;
    for (const [key, expected] of Object.entries(this._pending)) {
      const raw = hass.states[this._config?.entities[key]]?.state;
      if (raw !== undefined && raw !== '' && Number(raw) === expected) { delete this._pending[key]; delete this._draft[key]; }
    }
    if (this._config) this._render();
  }
  getCardSize() { return 7; }
  _values() {
    const values = {}, limits = {}; let available = true;
    for (const key of KEYS) {
      const state = this._hass.states[this._config.entities[key]];
      const raw = state?.state;
      if (!state || raw === '' || !Number.isFinite(Number(raw)) || ['unknown', 'unavailable'].includes(raw)) available = false;
      const draft = this._draft[key];
      values[key] = draft === undefined ? Number(raw) : draft.trim() === '' ? NaN : Number(draft);
      limits[key] = [Number(state?.attributes.min ?? (key.startsWith('water') ? 20 : -20)), Number(state?.attributes.max ?? (key.startsWith('water') ? 75 : 15))];
    }
    const valid = available && KEYS.every(k => Number.isFinite(values[k]) && values[k] >= limits[k][0] && values[k] <= limits[k][1]) && temperatureAt(0, values) !== null;
    return {values, limits, available, valid};
  }
  _render() {
    const t = LABELS[this._hass.language?.startsWith('de') ? 'de' : 'en']; this._t = t;
    if (!this._built) {
      this.shadowRoot.innerHTML = `<style>
        :host{display:block;container-type:inline-size}ha-card{display:block;padding:20px;color:var(--primary-text-color,#222);background:var(--ha-card-background,var(--card-background-color,#fff));border-radius:var(--ha-card-border-radius,12px)}
        h2{font-size:20px;font-weight:500;margin:0 0 20px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{font-size:14px;display:flex;flex-direction:column;gap:6px}input{box-sizing:border-box;width:100%;padding:10px;font:inherit;color:inherit;background:var(--secondary-background-color,#f5f5f5);border:1px solid var(--divider-color,#ccc);border-radius:6px}input:disabled{opacity:.7}
        svg{width:100%;height:auto;display:block;margin-top:14px;touch-action:pan-y}.grid{stroke:var(--divider-color,#ddd);stroke-width:1}.axis{fill:var(--secondary-text-color,#666);font:14px sans-serif}.curve{fill:none;stroke:var(--primary-color,#ef852b);stroke-width:3}.dot{fill:var(--primary-color,#ef852b)}
        .status{font-size:13px;min-height:2.6em;color:var(--secondary-text-color,#666)}.status.error{color:var(--error-color,#b00020)}.readout{font-variant-numeric:tabular-nums;text-align:center;min-height:1.4em;font-size:14px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}button{padding:10px 14px;border:1px solid var(--primary-color,#267ab5);border-radius:6px;font:inherit;background:transparent;color:var(--primary-color,#267ab5);cursor:pointer}button:disabled{opacity:.45;cursor:default}button:first-child{background:var(--primary-color,#267ab5);color:var(--text-primary-color,#fff)}
        @container(max-width:480px){.axis{font-size:24px}}
        @media(max-width:380px){ha-card{padding:14px}.fields{gap:10px}label{font-size:12px}}
        </style><ha-card><h2></h2><div class="fields">${KEYS.map(k => `<label><span data-label="${k}"></span><input type="number" data-key="${k}" step="1"></label>`).join('')}</div><svg viewBox="0 0 680 300" role="img"></svg><div class="readout"></div><div class="status" role="status" aria-live="polite"></div><div class="actions"><button class="apply"></button><button class="reset"></button></div></ha-card>`;
      for (const input of this.shadowRoot.querySelectorAll('input')) input.addEventListener('input', () => { this._draft[input.dataset.key] = input.value; this._message = ''; this._error = false; this._draw(); });
      this.shadowRoot.querySelector('.apply').addEventListener('click', () => this._apply());
      this.shadowRoot.querySelector('.reset').addEventListener('click', () => { this._draft = {}; this._pending = {}; this._message = ''; this._error = false; this._render(); });
      const svg = this.shadowRoot.querySelector('svg');
      const readPoint = event => {
        const {values, valid} = this._values(); if (!valid) return;
        const box = svg.getBoundingClientRect(), x = (event.clientX - box.left) * 680 / box.width;
        const outdoor = this._axisMin + Math.max(0, Math.min(1, (x - 60) / 590)) * (this._axisMax - this._axisMin);
        this.shadowRoot.querySelector('.readout').textContent = `${t.outdoor}: ${outdoor.toFixed(1)} °C → ${t.water}: ${temperatureAt(outdoor, values).toFixed(1)} °C`;
      };
      svg.addEventListener('pointermove', readPoint);
      svg.addEventListener('pointerdown', readPoint);
      svg.addEventListener('pointerleave', () => { this.shadowRoot.querySelector('.readout').textContent = ''; });
      this._built = true;
    }
    this.shadowRoot.querySelector('h2').textContent = this._config.title || t.title;
    const {values, limits, available} = this._values();
    for (const k of KEYS) {
      this.shadowRoot.querySelector(`[data-label="${k}"]`).textContent = `${t[k]} (°C)`;
      const input = this.shadowRoot.querySelector(`[data-key="${k}"]`);
      input.setAttribute('aria-label', t[k]); input.min = limits[k][0]; input.max = limits[k][1];
      input.disabled = !available || this._saving || !this._config.entities[k].startsWith('number.');
      if (this.shadowRoot.activeElement !== input) input.value = this._draft[k] ?? (Number.isFinite(values[k]) && available ? values[k] : '');
    }
    this.shadowRoot.querySelector('.apply').textContent = this._saving ? t.saving : t.apply;
    this.shadowRoot.querySelector('.reset').textContent = t.reset;
    this._draw();
  }
  _draw() {
    const {values: v, available, valid} = this._values(), t = this._t;
    this.shadowRoot.querySelector('.readout').textContent = '';
    const dirty = Object.keys(this._draft).length > 0, pending = Object.keys(this._pending).length > 0;
    const editable = KEYS.every(k => this._config.entities[k].startsWith('number.'));
    this.shadowRoot.querySelector('.apply').disabled = !valid || !dirty || !editable || this._saving || pending;
    this.shadowRoot.querySelector('.reset').disabled = !dirty || this._saving;
    const status = this.shadowRoot.querySelector('.status');
    status.textContent = !available ? t.unavailable : this._message || (!valid ? t.invalid : pending ? t.waiting : dirty ? t.preview : editable ? t.current : t.read);
    status.classList.toggle('error', !available || !valid || this._error);
    const svg = this.shadowRoot.querySelector('svg'); svg.setAttribute('aria-label', `${t.title}. ${status.textContent}`);
    if (!valid) { svg.replaceChildren(); this.shadowRoot.querySelector('.readout').textContent = ''; return; }
    const xmin = Math.floor((v.outdoor_min - 5) / 5) * 5, xmax = Math.ceil((v.outdoor_max + 5) / 5) * 5;
    this._axisMin = xmin; this._axisMax = xmax;
    const ymin = Math.floor((v.water_min - 3) / 5) * 5, ymax = Math.ceil((v.water_max + 3) / 5) * 5;
    const x = n => 60 + (n - xmin) / (xmax - xmin) * 590, y = n => 245 - (n - ymin) / (ymax - ymin) * 210;
    let content = '';
    for (let a = xmin; a <= xmax; a += xmax - xmin <= 40 ? 5 : 10) {
      content += `<path class="grid" d="M${x(a)},35V245"/><text class="axis" x="${x(a)}" y="268" text-anchor="middle">${a}</text>`;
    }
    for (let b = ymin; b <= ymax; b += ymax - ymin <= 40 ? 5 : 10) {
      content += `<path class="grid" d="M60,${y(b)}H650"/><text class="axis" x="49" y="${y(b)+5}" text-anchor="end">${b}</text>`;
    }
    content += `<text class="axis" x="60" y="19">${t.water} / °C</text><text class="axis" x="650" y="294" text-anchor="end">${t.outdoor} / °C</text>`;
    const pairs = [[xmin,v.water_max],[v.outdoor_min,v.water_max],[v.outdoor_max,v.water_min],[xmax,v.water_min]];
    content += `<polyline class="curve" points="${pairs.map(([a,b]) => `${x(a)},${y(b)}`).join(' ')}"/>`;
    for (const [a,b] of pairs.slice(1,3)) content += `<circle class="dot" cx="${x(a)}" cy="${y(b)}" r="4"/><text class="axis" x="${x(a)}" y="${y(b)-10}" text-anchor="middle">${a} / ${b} °C</text>`;
    svg.innerHTML = content;
  }
  async _apply() {
    const {values, valid} = this._values();
    if (!valid || this._saving || Object.keys(this._pending).length || !KEYS.every(k => this._config.entities[k].startsWith('number.'))) return;
    this._saving = true; this._error = false; this._message = ''; this._render();
    try {
      for (const key of KEYS) {
        if (this._draft[key] === undefined) continue;
        const entity = this._config.entities[key];
        this._pending[key] = values[key];
        try { await this._hass.callService('number', 'set_value', {entity_id: entity, value: values[key]}); }
        catch (error) { delete this._pending[key]; throw error; }
        // State events may arrive before or after the service response.
        if (Number(this._hass.states[entity]?.state) === values[key]) { delete this._pending[key]; delete this._draft[key]; }
      }
      this._message = Object.keys(this._pending).length ? '' : this._t.saved;
    } catch (_) { this._error = true; this._message = this._t.failed; }
    finally { this._saving = false; this._render(); }
  }
}
if (!customElements.get('panasonic-cascade-heating-curve')) customElements.define('panasonic-cascade-heating-curve', HeatingCurveCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === 'panasonic-cascade-heating-curve')) window.customCards.push({type: 'panasonic-cascade-heating-curve', name: 'Panasonic Cascade heating curve', description: 'Zone 1 heating curve with immediate local preview.'});
