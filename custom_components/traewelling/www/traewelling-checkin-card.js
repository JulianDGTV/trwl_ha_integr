/*
 * Träwelling Check-in-Karte für Home Assistant
 *
 * Zeigt die laufende Fahrt oder – wenn du gerade nicht unterwegs bist –
 * einen kompletten Check-in: Station suchen → Live-Abfahrten → Ziel → einchecken.
 * Alle API-Aufrufe laufen über die Services der Integration, der Token
 * bleibt also in Home Assistant.
 *
 *   type: custom:traewelling-checkin-card
 *   # optional:
 *   entity: binary_sensor.trawelling_xyz_unterwegs
 *   show_current_trip: true      # false = Karte ausblenden, solange du fährst
 *   title: Einchecken
 */

const DOMAIN = "traewelling";
const VERSION = "1.3.1";

const TYPES = [
  ["", "Alle"],
  ["express", "Fern"],
  ["regional", "Regio"],
  ["suburban", "S-Bahn"],
  ["subway", "U-Bahn"],
  ["tram", "Tram"],
  ["bus", "Bus"],
  ["ferry", "Fähre"],
];

const VISIBILITY = [
  ["public", "Öffentlich"],
  ["unlisted", "Nicht gelistet"],
  ["followers", "Nur Follower"],
  ["authenticated", "Nur angemeldete Nutzer"],
  ["private", "Privat"],
];

const BUSINESS = [
  ["private", "Privat"],
  ["business", "Geschäftlich"],
  ["commute", "Pendeln"],
];

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const toDate = (v) => (v ? new Date(v) : null);
const hhmm = (d) => (d ? d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "–");
const delayMin = (planned, real) => {
  const p = toDate(planned), r = toDate(real);
  if (!p || !r) return 0;
  return Math.round((r - p) / 60000);
};

const store = {
  get(key, fallback) {
    try {
      const v = window.localStorage.getItem(`traewelling-card:${key}`);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(`traewelling-card:${key}`, value);
    } catch (e) {
      /* egal */
    }
  },
};

function lineColor(dep) {
  if (dep.color) return [dep.color, dep.text_color || "#fff"];
  const p = String(dep.product || "").toLowerCase();
  if (p.includes("national") || (p.includes("express") && !p.includes("regional"))) return ["#ec0016", "#fff"];
  if (p.includes("regional")) return ["#6a737d", "#fff"];
  if (p.includes("suburban")) return ["#408335", "#fff"];
  if (p.includes("subway")) return ["#1455c0", "#fff"];
  if (p.includes("tram")) return ["#a9455d", "#fff"];
  if (p.includes("bus")) return ["#814997", "#fff"];
  if (p.includes("ferry")) return ["#309fd1", "#fff"];
  return ["var(--primary-color)", "#fff"];
}

class TraewellingCheckinCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._s = this._initialState();
    this._timers = {};
  }

  _initialState() {
    return {
      step: "start", // start | departures | destination | confirm | done
      loading: false,
      error: null,
      query: "",
      results: null,
      recent: null,
      home: null,
      station: null,
      travelType: store.get("travelType", ""),
      when: null,
      times: {},
      departures: [],
      departure: null,
      stops: null,
      stop: null,
      body: "",
      visibility: store.get("visibility", "public"),
      business: store.get("business", "private"),
      result: null,
    };
  }

  setConfig(config) {
    this._config = { show_current_trip: true, title: "Einchecken", ...(config || {}) };
    if (this._hass) this._render();
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const key = this._travelKey();
    if (first || key !== this._lastKey) {
      this._lastKey = key;
      if (!["confirm", "done"].includes(this._s.step) || this._isTravelling()) {
        if (this._isTravelling() && this._s.step !== "done") this._s.step = "start";
        this._render();
      }
    }
  }

  connectedCallback() {
    this._timers.tick = setInterval(() => {
      if (this._isTravelling()) this._render();
    }, 30000);
  }

  disconnectedCallback() {
    Object.values(this._timers).forEach((t) => {
      clearInterval(t);
      clearTimeout(t);
    });
    this._timers = {};
  }

  // ------------------------------------------------------------------ //
  // Home-Assistant-Helfer
  // ------------------------------------------------------------------ //

  _entityId() {
    if (this._config?.entity) return this._config.entity;
    const hass = this._hass;
    if (hass?.entities) {
      const hit = Object.values(hass.entities).find(
        (e) => e.platform === DOMAIN && e.entity_id.startsWith("binary_sensor.")
      );
      if (hit) return hit.entity_id;
    }
    return Object.keys(hass?.states || {}).find(
      (id) => id.startsWith("binary_sensor.") && hass.states[id].attributes.attribution === "Daten von traewelling.de"
    );
  }

  _travelState() {
    const id = this._entityId();
    return id ? this._hass.states[id] : undefined;
  }

  _isTravelling() {
    return this._travelState()?.state === "on";
  }

  _travelKey() {
    const st = this._travelState();
    return st ? `${st.state}|${st.attributes.status_id || ""}|${st.attributes.arrival_real || ""}` : "none";
  }

  async _call(service, data = {}) {
    const res = await this._hass.connection.sendMessagePromise({
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: data,
      return_response: true,
    });
    return res?.response ?? {};
  }

  async _run(fn) {
    this._s.loading = true;
    this._s.error = null;
    this._render();
    try {
      await fn();
    } catch (err) {
      this._s.error = err?.message || String(err);
    } finally {
      this._s.loading = false;
      this._render();
    }
  }

  // ------------------------------------------------------------------ //
  // Aktionen
  // ------------------------------------------------------------------ //

  async _loadRecent() {
    if (this._s.recent !== null) return;
    this._s.recent = [];
    try {
      const r = await this._call("search_stations", {});
      this._s.recent = r.stations || [];
      this._s.home = r.home || null;
    } catch (err) {
      this._s.error = err?.message || String(err);
    }
    this._render();
  }

  _onSearch(value) {
    this._s.query = value;
    clearTimeout(this._timers.search);
    if (value.trim().length < 2) {
      this._s.results = null;
      this._renderResults();
      return;
    }
    this._timers.search = setTimeout(async () => {
      try {
        const r = await this._call("search_stations", { query: value.trim() });
        if (this._s.query === value) {
          this._s.results = r.stations || [];
          this._s.error = null;
        }
      } catch (err) {
        this._s.error = err?.message || String(err);
      }
      this._renderResults();
    }, 350);
  }

  _nearby() {
    if (!navigator.geolocation) {
      this._s.error = "Standort wird von diesem Gerät nicht unterstützt.";
      this._render();
      return;
    }
    this._s.loading = true;
    this._s.error = null;
    this._render();
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        this._run(async () => {
          const r = await this._call("search_stations", {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          });
          const st = (r.stations || [])[0];
          if (!st) throw new Error("Keine Station in der Nähe gefunden.");
          await this._openStation(st, false);
        }),
      (err) => {
        this._s.loading = false;
        this._s.error = `Standort nicht verfügbar: ${err.message}`;
        this._render();
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
  }

  async _openStation(station, wrap = true) {
    this._s.station = station;
    this._s.when = null;
    this._s.step = "departures";
    const load = () => this._loadDepartures();
    if (wrap) await this._run(load);
    else await load();
    this._startLiveRefresh();
  }

  async _loadDepartures() {
    const data = { station_id: this._s.station.id };
    if (this._s.when) data.when = this._s.when;
    if (this._s.travelType) data.travel_type = this._s.travelType;
    const r = await this._call("get_departures", data);
    if (r.station?.name) this._s.station = { ...this._s.station, ...r.station };
    this._s.times = r.times || {};
    this._s.departures = r.departures || [];
  }

  _startLiveRefresh() {
    clearInterval(this._timers.live);
    this._timers.live = setInterval(async () => {
      if (this._s.step !== "departures" || this._s.when || this._s.loading) return;
      try {
        await this._loadDepartures();
        this._render();
      } catch (e) {
        /* nächster Versuch in 60 s */
      }
    }, 60000);
  }

  async _pickDeparture(index) {
    const dep = this._s.departures[index];
    if (!dep || dep.cancelled) return;
    this._s.departure = dep;
    this._s.step = "destination";
    this._s.stops = null;
    await this._run(async () => {
      const r = await this._call("get_trip", { trip_id: dep.trip_id, line_name: dep.line_name });
      const stops = r.stops || [];
      const planned = toDate(dep.planned)?.getTime();
      let idx = stops.findIndex(
        (s) => String(s.id) === String(dep.station_id) && toDate(s.departure_planned)?.getTime() === planned
      );
      if (idx < 0) idx = stops.findIndex((s) => String(s.id) === String(dep.station_id));
      if (idx < 0) idx = stops.findIndex((s) => s.name === dep.station_name);
      this._s.stops = idx >= 0 ? stops.slice(idx + 1) : stops;
      this._s.tripDestination = r.destination;
    });
  }

  _pickStop(index) {
    const stop = this._s.stops?.[index];
    if (!stop || stop.cancelled) return;
    this._s.stop = stop;
    this._s.step = "confirm";
    this._render();
  }

  async _checkin() {
    const { departure: dep, stop } = this._s;
    store.set("visibility", this._s.visibility);
    store.set("business", this._s.business);
    await this._run(async () => {
      const data = {
        trip_id: dep.trip_id,
        line_name: dep.line_name,
        start_id: dep.station_id ?? this._s.station.id,
        destination_id: stop.id,
        departure: dep.planned,
        arrival: stop.arrival_planned,
        visibility: this._s.visibility,
        business: this._s.business,
      };
      if (this._s.body.trim()) data.body = this._s.body.trim();
      this._s.result = await this._call("checkin", data);
      this._s.step = "done";
      clearInterval(this._timers.live);
    });
  }

  _reset() {
    clearInterval(this._timers.live);
    const keep = { recent: this._s.recent, home: this._s.home };
    this._s = { ...this._initialState(), ...keep };
    this._render();
  }

  _back() {
    const order = { departures: "start", destination: "departures", confirm: "destination" };
    const prev = order[this._s.step];
    if (!prev) return this._reset();
    if (prev === "start") return this._reset();
    this._s.step = prev;
    this._s.error = null;
    this._render();
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-a]");
    if (!el || el.disabled) return;
    const a = el.dataset.a;
    const i = el.dataset.i !== undefined ? Number(el.dataset.i) : undefined;
    switch (a) {
      case "station": {
        const list = el.dataset.src === "recent" ? this._s.recent : el.dataset.src === "home" ? [this._s.home] : this._s.results;
        const st = list?.[i ?? 0];
        if (st) this._openStation(st);
        break;
      }
      case "nearby":
        this._nearby();
        break;
      case "type":
        this._s.travelType = el.dataset.v;
        store.set("travelType", el.dataset.v);
        this._run(() => this._loadDepartures());
        break;
      case "earlier":
      case "later": {
        const t = a === "earlier" ? this._s.times.prev : this._s.times.next;
        if (t) {
          this._s.when = t;
          this._run(() => this._loadDepartures());
        }
        break;
      }
      case "now":
        this._s.when = null;
        this._run(() => this._loadDepartures());
        break;
      case "refresh":
        this._run(() => this._loadDepartures());
        break;
      case "dep":
        this._pickDeparture(i);
        break;
      case "stop":
        this._pickStop(i);
        break;
      case "checkin":
        this._checkin();
        break;
      case "back":
        this._back();
        break;
      case "reset":
        this._reset();
        break;
      default:
        break;
    }
  }

  _onInput(ev) {
    const t = ev.target;
    if (t.id === "search") this._onSearch(t.value);
    if (t.id === "body") {
      this._s.body = t.value;
      const c = this.shadowRoot.getElementById("count");
      if (c) c.textContent = `${t.value.length}/280`;
    }
  }

  _onChange(ev) {
    const t = ev.target;
    if (t.id === "visibility") this._s.visibility = t.value;
    if (t.id === "business") this._s.business = t.value;
  }

  // ------------------------------------------------------------------ //
  // Rendering
  // ------------------------------------------------------------------ //

  _render() {
    if (!this._hass || !this._config) return;
    const root = this.shadowRoot;
    if (!this._wired) {
      root.addEventListener("click", (e) => this._onClick(e));
      root.addEventListener("input", (e) => this._onInput(e));
      root.addEventListener("change", (e) => this._onChange(e));
      this._wired = true;
    }

    if (this._isTravelling() && this._s.step !== "done") {
      if (!this._config.show_current_trip) {
        this.style.display = "none";
        root.innerHTML = "";
        return;
      }
      this.style.display = "";
      root.innerHTML = `${STYLE}<ha-card>${this._renderCurrent()}</ha-card>`;
      return;
    }
    this.style.display = "";

    if (!this._entityId()) {
      root.innerHTML = `${STYLE}<ha-card><div class="pad err">Keine Träwelling-Entität gefunden. Ist die Integration eingerichtet?</div></ha-card>`;
      return;
    }

    let body = "";
    switch (this._s.step) {
      case "departures":
        body = this._renderDepartures();
        break;
      case "destination":
        body = this._renderDestination();
        break;
      case "confirm":
        body = this._renderConfirm();
        break;
      case "done":
        body = this._renderDone();
        break;
      default:
        body = this._renderStart();
    }

    const err = this._s.error ? `<div class="err">⚠️ ${esc(this._s.error)}</div>` : "";
    const loading = this._s.loading ? `<div class="loading"><span></span></div>` : "";

    // Fokus und Cursor im Suchfeld über das Neu-Rendern retten.
    const active = root.activeElement;
    const focusId = active && active.id ? active.id : null;
    const sel = focusId && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;

    root.innerHTML = `${STYLE}<ha-card>${loading}${body}${err}</ha-card>`;

    const input = root.getElementById("search");
    if (input && this._s.query) input.value = this._s.query;
    if (focusId) {
      const el = root.getElementById(focusId);
      if (el) {
        el.focus();
        if (sel) {
          try {
            el.setSelectionRange(sel[0], sel[1]);
          } catch (e) {
            /* select-Felder */
          }
        }
      }
    }
    if (this._s.step === "start") this._loadRecent();
  }

  _renderResults() {
    const box = this.shadowRoot.getElementById("results");
    if (!box || this._s.error) return this._render();
    box.innerHTML = this._resultsHtml();
    const err = this.shadowRoot.querySelector(".err");
    if (err && !this._s.error) err.remove();
  }

  _resultsHtml() {
    const { results, recent, home, query } = this._s;
    const item = (st, i, src, icon) => `
      <button class="row" data-a="station" data-src="${src}" data-i="${i}">
        <ha-icon icon="${icon}"></ha-icon>
        <span class="grow">${esc(st.name)}</span>
        <ha-icon class="chev" icon="mdi:chevron-right"></ha-icon>
      </button>`;

    if (query.trim().length >= 2) {
      if (results === null) return `<div class="hint">Suche …</div>`;
      if (!results.length) return `<div class="hint">Keine Station gefunden.</div>`;
      return results.map((s, i) => item(s, i, "results", "mdi:map-marker")).join("");
    }
    let html = "";
    if (home) html += `<div class="label">Heimatbahnhof</div>${item(home, 0, "home", "mdi:home")}`;
    if (recent?.length) {
      html += `<div class="label">Zuletzt genutzt</div>`;
      html += recent.map((s, i) => item(s, i, "recent", "mdi:history")).join("");
    }
    return html || `<div class="hint">Tippe den Namen einer Station ein.</div>`;
  }

  _renderStart() {
    return `
      <div class="head">
        <ha-icon icon="mdi:ticket-confirmation"></ha-icon>
        <span class="title">${esc(this._config.title)}</span>
      </div>
      <div class="pad">
        <div class="search">
          <ha-icon icon="mdi:magnify"></ha-icon>
          <input id="search" type="search" autocomplete="off" enterkeyhint="search"
                 placeholder="Bahnhof oder Haltestelle suchen …">
        </div>
        <button class="chip wide" data-a="nearby">
          <ha-icon icon="mdi:crosshairs-gps"></ha-icon> Station in meiner Nähe
        </button>
      </div>
      <div id="results" class="list">${this._resultsHtml()}</div>`;
  }

  _renderDepartures() {
    const { station, departures, travelType, when } = this._s;
    const chips = TYPES.map(
      ([v, label]) =>
        `<button class="chip ${v === travelType ? "on" : ""}" data-a="type" data-v="${v}">${label}</button>`
    ).join("");

    const rows = departures.length
      ? departures
          .map((d, i) => {
            const delay = delayMin(d.planned, d.real);
            const [bg, fg] = lineColor(d);
            const platformChanged = d.planned_platform && d.platform && d.platform !== d.planned_platform;
            return `
            <button class="row dep ${d.cancelled ? "cancelled" : ""}" data-a="dep" data-i="${i}" ${d.cancelled ? "disabled" : ""}>
              <span class="time">
                <b>${hhmm(toDate(d.planned))}</b>
                ${d.cancelled ? `<small class="late">fällt aus</small>` : delay > 0 ? `<small class="late">+${delay}</small>` : d.real ? `<small class="ok">pünktlich</small>` : ""}
              </span>
              <span class="badge" style="background:${esc(bg)};color:${esc(fg)}">${esc(d.line_name)}</span>
              <span class="grow dir">${esc(d.direction)}</span>
              ${d.platform ? `<span class="plat ${platformChanged ? "late" : ""}">Gl. ${esc(d.platform)}</span>` : ""}
            </button>`;
          })
          .join("")
      : `<div class="hint">${this._s.loading ? "Lade Abfahrten …" : "Keine Abfahrten gefunden."}</div>`;

    return `
      <div class="head">
        <button class="icon" data-a="back" title="Zurück"><ha-icon icon="mdi:arrow-left"></ha-icon></button>
        <span class="title grow">${esc(station?.name)}</span>
        ${when ? `<button class="chip" data-a="now">Jetzt</button>` : `<span class="live">● live</span>`}
        <button class="icon" data-a="refresh" title="Aktualisieren"><ha-icon icon="mdi:refresh"></ha-icon></button>
      </div>
      <div class="chips">${chips}</div>
      <div class="list">${rows}</div>
      <div class="pager">
        <button class="chip" data-a="earlier" ${this._s.times.prev ? "" : "disabled"}>‹ Früher</button>
        <button class="chip" data-a="later" ${this._s.times.next ? "" : "disabled"}>Später ›</button>
      </div>`;
  }

  _renderDestination() {
    const d = this._s.departure;
    const [bg, fg] = lineColor(d);
    const stops = this._s.stops;
    const rows =
      stops === null
        ? `<div class="hint">Lade Halte …</div>`
        : stops.length
          ? stops
              .map((s, i) => {
                const delay = delayMin(s.arrival_planned, s.arrival_real);
                return `
            <button class="row ${s.cancelled ? "cancelled" : ""}" data-a="stop" data-i="${i}" ${s.cancelled ? "disabled" : ""}>
              <span class="time">
                <b>${hhmm(toDate(s.arrival_planned))}</b>
                ${s.cancelled ? `<small class="late">entfällt</small>` : delay > 0 ? `<small class="late">+${delay}</small>` : ""}
              </span>
              <span class="grow">${esc(s.name)}</span>
              ${s.platform ? `<span class="plat">Gl. ${esc(s.platform)}</span>` : ""}
            </button>`;
              })
              .join("")
          : `<div class="hint">Keine weiteren Halte.</div>`;

    return `
      <div class="head">
        <button class="icon" data-a="back" title="Zurück"><ha-icon icon="mdi:arrow-left"></ha-icon></button>
        <span class="badge" style="background:${esc(bg)};color:${esc(fg)}">${esc(d.line_name)}</span>
        <span class="title grow">→ ${esc(d.direction)}</span>
      </div>
      <div class="sub">Ab ${esc(d.station_name || this._s.station?.name)} · ${hhmm(toDate(d.planned))} — wo steigst du aus?</div>
      <div class="list">${rows}</div>`;
  }

  _renderConfirm() {
    const d = this._s.departure;
    const s = this._s.stop;
    const [bg, fg] = lineColor(d);
    const opt = (list, cur) => list.map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`).join("");
    return `
      <div class="head">
        <button class="icon" data-a="back" title="Zurück"><ha-icon icon="mdi:arrow-left"></ha-icon></button>
        <span class="title grow">Check-in bestätigen</span>
      </div>
      <div class="pad">
        <div class="summary">
          <span class="badge" style="background:${esc(bg)};color:${esc(fg)}">${esc(d.line_name)}</span>
          <div class="route">
            <div><b>${hhmm(toDate(d.planned))}</b> ${esc(d.station_name || this._s.station?.name)}</div>
            <div class="line-v"></div>
            <div><b>${hhmm(toDate(s.arrival_planned))}</b> ${esc(s.name)}</div>
          </div>
        </div>
        <label class="field">
          <span>Statustext (optional) <small id="count">${this._s.body.length}/280</small></span>
          <textarea id="body" maxlength="280" rows="2" placeholder="Was geht auf der Fahrt?">${esc(this._s.body)}</textarea>
        </label>
        <div class="two">
          <label class="field"><span>Sichtbarkeit</span><select id="visibility">${opt(VISIBILITY, this._s.visibility)}</select></label>
          <label class="field"><span>Reiseart</span><select id="business">${opt(BUSINESS, this._s.business)}</select></label>
        </div>
        <button class="primary" data-a="checkin" ${this._s.loading ? "disabled" : ""}>
          <ha-icon icon="mdi:check-circle"></ha-icon> Jetzt einchecken
        </button>
      </div>`;
  }

  _renderDone() {
    const r = this._s.result || {};
    const also = (r.also_on_this_connection || []).filter(Boolean);
    return `
      <div class="pad done">
        <div class="big">✅</div>
        <div class="title">Eingecheckt!</div>
        ${r.points != null ? `<div class="pts">+${esc(r.points)} Punkte</div>` : ""}
        ${also.length ? `<div class="sub">Auch in diesem Zug: ${also.map(esc).join(", ")}</div>` : ""}
        <div class="actions">
          ${r.url ? `<a class="chip" href="${esc(r.url)}" target="_blank" rel="noopener">Status öffnen</a>` : ""}
          <button class="chip on" data-a="reset">Fertig</button>
        </div>
      </div>`;
  }

  _renderCurrent() {
    const a = this._travelState()?.attributes || {};
    const dep = toDate(a.departure_real || a.departure_planned);
    const arr = toDate(a.arrival_real || a.arrival_planned);
    const now = new Date();
    let p = 0;
    if (dep && arr && arr > dep) p = Math.max(0, Math.min(100, ((now - dep) / (arr - dep)) * 100));
    const left = arr ? Math.max(0, Math.round((arr - now) / 60000)) : null;
    const delay = delayMin(a.arrival_planned, a.arrival_real);
    const [bg, fg] = lineColor({ product: a.category });
    return `
      <div class="head">
        <ha-icon icon="mdi:train"></ha-icon>
        <span class="title grow">Unterwegs</span>
        ${a.url ? `<a class="chip" href="${esc(a.url)}" target="_blank" rel="noopener">Status</a>` : ""}
      </div>
      <div class="pad">
        <div class="summary">
          <span class="badge" style="background:${bg};color:${fg}">${esc(a.line || "Fahrt")}</span>
          <div class="route">
            <div><b>${hhmm(toDate(a.departure_planned) || dep)}</b>${delayMin(a.departure_planned, a.departure_real) > 0 ? ` <small class="late">+${delayMin(a.departure_planned, a.departure_real)}</small>` : ""} ${esc(a.origin)}${a.origin_platform ? ` <small>Gl. ${esc(a.origin_platform)}</small>` : ""}</div>
            <div class="line-v"></div>
            <div><b>${hhmm(toDate(a.arrival_planned) || arr)}</b>${delay > 0 ? ` <small class="late">+${delay}</small>` : ""} ${esc(a.destination)}${a.destination_platform ? ` <small>Gl. ${esc(a.destination_platform)}</small>` : ""}</div>
          </div>
        </div>
        <div class="bar"><div style="width:${p.toFixed(1)}%"></div></div>
        <div class="sub">${Math.round(p)} % · ${left !== null ? `noch ${left} min` : ""}${a.distance_km ? ` · ${esc(a.distance_km)} km` : ""}${a.points ? ` · ${esc(a.points)} Punkte` : ""}</div>
      </div>`;
  }
}

const STYLE = `<style>
  :host { display: block; }
  ha-card { overflow: hidden; position: relative; }
  button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
  button[disabled] { cursor: default; opacity: .5; }
  .head { display: flex; align-items: center; gap: 10px; padding: 14px 16px 8px; }
  .head > ha-icon { color: var(--primary-color); }
  .title { font-size: 1.15em; font-weight: 600; }
  .grow { flex: 1; min-width: 0; }
  .pad { padding: 8px 16px 16px; }
  .sub { padding: 0 16px 8px; color: var(--secondary-text-color); font-size: .92em; }
  .pad .sub { padding: 6px 0 0; }
  .hint { padding: 16px; color: var(--secondary-text-color); text-align: center; }
  .label { padding: 12px 16px 4px; font-size: .8em; text-transform: uppercase; letter-spacing: .05em; color: var(--secondary-text-color); }
  .err { margin: 8px 16px 16px; padding: 10px 12px; border-radius: 10px; background: rgba(219, 68, 55, .12); color: var(--error-color, #db4437); }
  .search { display: flex; align-items: center; gap: 8px; padding: 0 12px; border-radius: 12px; background: var(--secondary-background-color); }
  .search ha-icon { color: var(--secondary-text-color); }
  .search input { flex: 1; min-width: 0; height: 46px; border: 0; outline: 0; background: none; color: var(--primary-text-color); font: inherit; font-size: 16px; }
  .list { display: flex; flex-direction: column; max-height: 460px; overflow-y: auto; }
  .row { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 6px 16px; text-align: left; border-top: 1px solid var(--divider-color); }
  .row:hover:not([disabled]) { background: var(--secondary-background-color); }
  .row .chev { color: var(--secondary-text-color); }
  .row.cancelled .dir, .row.cancelled .grow { text-decoration: line-through; }
  .time { display: flex; flex-direction: column; align-items: flex-start; width: 52px; flex: none; line-height: 1.2; }
  .time small { font-size: .78em; }
  .late { color: var(--error-color, #db4437); }
  .ok { color: var(--success-color, #43a047); }
  .badge { flex: none; padding: 3px 8px; border-radius: 6px; font-weight: 700; font-size: .85em; white-space: nowrap; }
  .dir { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .plat { flex: none; font-size: .85em; color: var(--secondary-text-color); }
  .plat.late { color: var(--error-color, #db4437); font-weight: 600; }
  .chips { display: flex; gap: 6px; padding: 4px 16px 10px; overflow-x: auto; scrollbar-width: none; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 18px; background: var(--secondary-background-color); white-space: nowrap; text-decoration: none; color: var(--primary-text-color); font-size: .9em; }
  .chip ha-icon { --mdc-icon-size: 18px; }
  .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .chip.wide { width: 100%; justify-content: center; margin-top: 10px; padding: 11px; }
  .icon { display: inline-flex; padding: 6px; border-radius: 50%; }
  .icon:hover { background: var(--secondary-background-color); }
  .live { color: var(--success-color, #43a047); font-size: .85em; font-weight: 600; }
  .pager { display: flex; justify-content: space-between; padding: 10px 16px 14px; border-top: 1px solid var(--divider-color); }
  .summary { display: flex; gap: 12px; align-items: flex-start; padding: 12px; border-radius: 12px; background: var(--secondary-background-color); }
  .route { flex: 1; display: flex; flex-direction: column; }
  .route small { color: var(--secondary-text-color); }
  .line-v { width: 2px; height: 14px; margin: 3px 0 3px 18px; background: var(--divider-color); }
  .field { display: flex; flex-direction: column; gap: 4px; margin-top: 12px; font-size: .9em; color: var(--secondary-text-color); }
  .field span { display: flex; justify-content: space-between; }
  textarea, select { font: inherit; font-size: 16px; color: var(--primary-text-color); background: var(--secondary-background-color); border: 1px solid var(--divider-color); border-radius: 10px; padding: 10px; }
  textarea { resize: vertical; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .primary { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; margin-top: 16px; padding: 13px; border-radius: 12px; background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 600; font-size: 1.05em; }
  .bar { height: 10px; margin-top: 14px; border-radius: 5px; background: var(--secondary-background-color); overflow: hidden; }
  .bar > div { height: 100%; border-radius: 5px; background: var(--primary-color); transition: width .6s; }
  .done { text-align: center; padding: 24px 16px; }
  .done .big { font-size: 42px; }
  .done .pts { margin-top: 4px; font-size: 1.2em; font-weight: 700; color: var(--primary-color); }
  .actions { display: flex; justify-content: center; gap: 10px; margin-top: 16px; }
  .loading { position: absolute; inset: 0 0 auto 0; height: 3px; overflow: hidden; }
  .loading span { position: absolute; height: 100%; width: 30%; background: var(--primary-color); animation: slide 1s infinite ease-in-out; }
  @keyframes slide { from { left: -30%; } to { left: 100%; } }
  @media (max-width: 420px) { .two { grid-template-columns: 1fr; } }
</style>`;

if (!customElements.get("traewelling-checkin-card")) {
  customElements.define("traewelling-checkin-card", TraewellingCheckinCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "traewelling-checkin-card",
    name: "Träwelling Check-in",
    description: "Laufende Fahrt oder Check-in mit Live-Abfahrten",
    preview: false,
  });
  console.info(`%c TRÄWELLING-CHECKIN-CARD %c ${VERSION} `, "background:#c72730;color:#fff", "background:#333;color:#fff");
}
