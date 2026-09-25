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
 *   location_entity: device_tracker.mein_handy   # Standortquelle für „In meiner Nähe“
 *   upcoming_entity: sensor.trawelling_xyz_nachste_fahrt   # sonst automatisch
 */

const DOMAIN = "traewelling";
const VERSION = "1.9.1";

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
const pad2 = (n) => String(n).padStart(2, "0");
const isoDay = (d) => (d ? `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}` : null);
const deDate = (v) => {
  if (!v) return null;
  const [y, m, d] = String(v).slice(0, 10).split("-");
  return y && m && d ? `${d}.${m}.${y}` : String(v);
};
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

function modeIcon(category) {
  const c = String(category || "").toLowerCase();
  if (c.includes("tram")) return "mdi:tram";
  if (c.includes("subway")) return "mdi:subway-variant";
  if (c.includes("bus")) return "mdi:bus";
  if (c.includes("ferry")) return "mdi:ferry";
  if (c.includes("plane")) return "mdi:airplane";
  if (c.includes("taxi")) return "mdi:taxi";
  return "mdi:train";
}

/** Fahrt-Block (Linie, Zeitleiste, Fortschritt) – für eigene und Freundes-Fahrten. */
function tripHtml(t, opts = {}) {
  const dep = toDate(t.departure_real || t.departure || t.departure_planned);
  const arr = toDate(t.arrival_real || t.arrival || t.arrival_planned);
  const depPlanned = toDate(t.departure_planned) || dep;
  const arrPlanned = toDate(t.arrival_planned) || arr;
  const now = new Date();
  let p = 0;
  if (dep && arr && arr > dep) p = Math.max(0, Math.min(100, ((now - dep) / (arr - dep)) * 100));
  const left = arr ? Math.max(0, Math.round((arr - now) / 60000)) : null;
  const until = dep ? Math.max(0, Math.round((dep - now) / 60000)) : null;
  const ride = dep && arr ? Math.round((arr - dep) / 60000) : null;
  const dDep = depPlanned && dep ? Math.round((dep - depPlanned) / 60000) : 0;
  const dArr = arrPlanned && arr ? Math.round((arr - arrPlanned) / 60000) : 0;
  const [bg, fg] = lineColor({ product: t.category });

  let pill;
  if (opts.upcoming) pill = `<span class="pill soon">${until === 0 ? "jetzt" : `in ${until} min`}</span>`;
  else if (dArr > 0) pill = `<span class="pill late">+${dArr} min</span>`;
  else if (t.arrival_real || t.departure_real) pill = `<span class="pill ok">pünktlich</span>`;
  else pill = "";

  const stop = (cls, time, delay, name, platform) => `
      <div class="stop ${cls}">
        <span class="dot"></span>
        <span class="t">${hhmm(time)}</span>
        ${delay > 0 ? `<span class="d">+${delay}</span>` : ""}
        <span class="name">${esc(name)}</span>
        ${platform ? `<span class="plat">Gl. ${esc(platform)}</span>` : ""}
      </div>`;

  const meta = (opts.upcoming
    ? [until !== null ? (until === 0 ? "fährt jetzt ab" : `Abfahrt in ${until} min`) : null, ride ? `${ride} min Fahrt` : null]
    : [`${Math.round(p)} %`, left !== null ? (left === 0 ? "kommt an" : `noch ${left} min`) : null]
  )
    .concat([t.distance_km ? `${esc(t.distance_km)} km` : null, t.points ? `${esc(t.points)} Punkte` : null])
    .filter(Boolean)
    .map((x) => `<span>${x}</span>`)
    .join("");

  return `
    <div class="trip" style="--line:${esc(bg)};--line-fg:${esc(fg)}">
      <div class="trip-top">
        <span class="badge">${esc(t.line || "Fahrt")}</span>
        <span class="dir">${t.body ? `„${esc(t.body)}“` : ""}</span>
        ${pill}
      </div>
      <div class="stops">
        ${stop("from", depPlanned, dDep, t.origin, t.origin_platform)}
        ${stop("to", arrPlanned, dArr, t.destination, t.destination_platform)}
      </div>
      ${opts.upcoming ? "" : `
      <div class="progress" role="progressbar" aria-valuenow="${Math.round(p)}" aria-valuemin="0" aria-valuemax="100">
        <div class="fill" style="width:${p.toFixed(1)}%"></div>
        <div class="knob" style="left:${p.toFixed(1)}%"><ha-icon icon="${modeIcon(t.category)}"></ha-icon></div>
      </div>`}
      <div class="meta">${meta}</div>
    </div>`;
}

const XFER = {
  ok: ["mdi:swap-horizontal", "Umstieg", "ok"],
  tight: ["mdi:run-fast", "Knapp", "warn"],
  risk: ["mdi:alert", "Gefährdet", "bad"],
  missed: ["mdi:alert-octagon", "Verpasst?", "bad"],
  cancelled: ["mdi:cancel", "Fällt aus", "bad"],
  unknown: ["mdi:help-circle-outline", "Unklar", "warn"],
  conflict: ["mdi:alert-circle", "Unlogisch", "bad"],
};
const XFER_ALERT = ["risk", "missed", "cancelled", "unknown", "conflict"];

/** Umstieg zwischen zwei Fahrten (Minuten nach Echtzeit, Plan in Klammern). */
function transferHtml(x) {
  if (!x) return "";
  const [icon, label, cls] = XFER[x.rating] || XFER.ok;
  const min = typeof x.minutes === "number" ? x.minutes : null;
  const unknown = x.rating === "unknown" && typeof x.minutes_planned === "number";
  const mins = unknown
    ? `Plan ${x.minutes_planned} min`
    : min === null ? "" : `${min < 0 ? "−" : ""}${Math.abs(min)} min`;
  const plan =
    !unknown && typeof x.minutes_planned === "number" && x.minutes_planned !== min
      ? `<s title="laut Fahrplan ${x.minutes_planned} min">${x.minutes_planned}</s>`
      : "";
  const where = x.same_station === false && x.to_station
    ? `🚶 ${x.walk_m ? `${x.walk_m >= 1000 ? `${(x.walk_m / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} km` : `${x.walk_m} m`} → ` : "→ "}${esc(x.to_station)}`
    : x.arrival_platform && x.departure_platform
      ? `Gl. ${esc(x.arrival_platform)} → ${esc(x.departure_platform)}`
      : x.departure_platform
        ? `weiter ab Gl. ${esc(x.departure_platform)}`
        : esc(x.station || "");
  return `
    <div class="xfer ${cls}">
      <ha-icon icon="${icon}"></ha-icon>
      <span class="xl"><b>${label}</b>${mins ? ` · <b>${mins}</b>` : ""}${plan ? ` ${plan}` : ""}</span>
      <span class="xw">${where}</span>
      ${x.live ? `<span class="xlive" title="${x.departure_source === "board" ? "Echtzeit von der Abfahrtstafel" : "Echtzeit"}">●</span>` : ""}
      ${x.warning ? `<div class="xwarn">${esc(x.warning)}</div>` : ""}
      ${!x.warning && x.departure_source === "board" ? `<div class="xnote">Abfahrt laut Live-Abfahrtstafel</div>` : ""}
    </div>`;
}

/** Kompakte Zeile für einen Anschluss. */
function legHtml(t) {
  const depP = toDate(t.departure_planned);
  const arrP = toDate(t.arrival_planned);
  const dDep = delayMin(t.departure_planned, t.departure_real);
  const est = !t.arrival_real && t.arrival_estimated;
  const dArr = delayMin(t.arrival_planned, t.arrival_real || (est ? t.arrival_expected : null));
  const [bg, fg] = lineColor({ product: t.category });
  const dep = toDate(t.departure_real) || depP;
  const until = dep ? Math.round((dep - new Date()) / 60000) : null;
  return `
    <div class="leg ${t.cancelled ? "cancelled" : ""}" style="--line:${esc(bg)};--line-fg:${esc(fg)}">
      <span class="badge">${esc(t.line || "Fahrt")}</span>
      <div class="leg-main">
        <div class="leg-l"><b>${hhmm(depP)}</b>${dDep > 0 ? `<span class="d">+${dDep}</span>` : ""}
          <span class="nm">${esc(t.origin)}</span>${t.origin_platform ? `<span class="plat">Gl. ${esc(t.origin_platform)}</span>` : ""}</div>
        <div class="leg-l sub2"><span>${hhmm(arrP)}</span>${dArr > 0 ? `<span class="d" ${est ? `title="geschätzt aus der Abfahrtsverspätung"` : ""}>${est ? "~" : ""}+${dArr}</span>` : ""}
          <span class="nm">${esc(t.destination)}</span>${until !== null && until > 0 && until < 120 ? `<span class="in">in ${until} min</span>` : ""}</div>
      </div>
    </div>`;
}

/** Anschlusskette: Umstieg → Fahrt → Umstieg → Fahrt … */
function chainHtml(legs, title) {
  if (!legs?.length) return "";
  const last = legs[legs.length - 1];
  const arr = toDate(last.arrival_real) || toDate(last.arrival_expected) || toDate(last.arrival_planned);
  const alerts = legs.filter((l) => XFER_ALERT.includes(l.transfer?.rating));
  const worst = alerts.find((l) => l.transfer.rating !== "unknown") || alerts[0];
  const banner = worst
    ? `<div class="alert ${worst.transfer.rating === "unknown" ? "warn" : "bad"}">
        <ha-icon icon="${worst.transfer.rating === "unknown" ? "mdi:help-circle-outline" : "mdi:alert"}"></ha-icon>
        <span>${
          worst.transfer.rating === "unknown"
            ? `Anschluss in ${esc(worst.transfer.station || "?")} unklar – keine Echtzeit`
            : worst.transfer.rating === "conflict"
              ? `Check-in prüfen: ${esc(worst.line || "Anschluss")} passt zeitlich nicht`
              : `Anschluss ${esc(worst.line || "")} in ${esc(worst.transfer.station || "?")} ${worst.transfer.rating === "cancelled" ? "fällt aus" : worst.transfer.rating === "missed" ? "wohl nicht erreichbar" : "gefährdet"}`
        }${alerts.length > 1 ? ` · ${alerts.length} Warnungen` : ""}</span>
      </div>`
    : "";
  return `
    ${banner}
    <div class="chain">
      <div class="chain-h"><span>${esc(title)}</span>${arr ? `<span>an ${esc(last.destination)} ${hhmm(arr)}</span>` : ""}</div>
      ${legs.map((l) => `${transferHtml(l.transfer)}${legHtml(l)}`).join("")}
    </div>`;
}

// Live-Abfahrten so oft neu laden (nur sichtbar und ohne gewählte Uhrzeit).
const LIVE_REFRESH_MS = 60000;

// Laufende Check-ins überleben ein Neu-Erzeugen der Karte durch Home Assistant.
const FLOWS = new Map();
const FLOW_TTL = 20 * 60 * 1000;

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
      travelType: "",
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
      tickets: null, // null = lädt, sonst { available, tickets, suggested }
      ticketsDate: null,
      ticketId: undefined, // undefined = noch nicht gewählt → Vorschlag übernehmen
    };
  }

  setConfig(config) {
    this._config = { show_current_trip: true, title: "Einchecken", ...(config || {}) };
    this._flowKey = JSON.stringify([this._config.entity || "", this._config.title]);
    const saved = FLOWS.get(this._flowKey);
    if (saved && saved.s !== this._s && Date.now() - saved.t < FLOW_TTL && saved.s.step !== "start") {
      this._s = saved.s;
      this._s.loading = false;
    }
    if (this._hass) this._render();
  }

  _saveFlow() {
    if (!this._flowKey) return;
    if (this._s.step === "start" && !this._s.whileTravelling) FLOWS.delete(this._flowKey);
    else FLOWS.set(this._flowKey, { s: this._s, t: Date.now() });
  }

  /** Nutzer steckt gerade mitten im Check-in → nichts dazwischenfunken. */
  _busy() {
    return this._s.step !== "start" || this._s.whileTravelling || Boolean(this._s.query);
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
      // Nur im Ruhezustand zwischen „Unterwegs“ und Check-in umschalten –
      // ein angefangener Check-in wird nie unterbrochen.
      if (first || !this._busy()) this._render();
    }
  }

  connectedCallback() {
    this._timers.tick = setInterval(() => {
      if (!document.hidden && (this._isTravelling() || this._upcomingState()) && !this._busy()) this._render();
    }, 30000);
    if (this._s.step === "departures" && this._s.station) this._startLiveRefresh();
  }

  disconnectedCallback() {
    Object.values(this._timers).forEach((t) => {
      clearInterval(t);
      clearTimeout(t);
    });
    this._timers = {};
    if (this._onVisible) {
      document.removeEventListener("visibilitychange", this._onVisible);
      this._onVisible = null;
    }
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

  /** Sensor „Nächste Fahrt“ – eigene Fahrt, die in der nächsten Stunde startet. */
  _upcomingState() {
    const hass = this._hass;
    if (!hass) return undefined;
    let id = this._config?.upcoming_entity;
    if (!id) {
      const own = Object.values(hass.entities || {})
        .filter((e) => e.platform === DOMAIN && e.entity_id.startsWith("sensor."))
        .map((e) => e.entity_id);
      const all = Object.keys(hass.states || {}).filter((x) => x.startsWith("sensor."));
      id = own.find((x) => /_nachste_fahrt$/.test(x)) || all.find((x) => /tra?e?welling.*_nachste_fahrt$/.test(x));
    }
    const st = id ? hass.states[id] : undefined;
    return st && st.attributes?.origin && !["unknown", "unavailable"].includes(st.state) ? st : undefined;
  }

  _travelKey() {
    const st = this._travelState();
    const up = this._upcomingState();
    return [
      st ? `${st.state}|${st.attributes.status_id || ""}|${st.attributes.arrival_real || ""}` : "none",
      up ? `${up.attributes.status_id}|${up.state}|${up.last_updated || ""}` : "-",
    ].join("#");
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
      this._s.home = r.home || null;
      const homeId = this._s.home?.id;
      this._s.recent = (r.stations || []).filter((st) => st.id !== homeId).slice(0, 5);
    } catch (err) {
      this._s.error = err?.message || String(err);
    }
    this._render();
  }

  _onSearch(value) {
    this._s.query = value;
    this._s.nearby = null;
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

  _inCompanionApp() {
    return Boolean(
      window.externalApp ||
        window.webkit?.messageHandlers?.getExternalAuth ||
        window.webkit?.messageHandlers?.externalBus ||
        /Home ?Assistant/i.test(navigator.userAgent)
    );
  }

  /** Standort, den die HA-App an Home Assistant meldet (person/device_tracker). */
  _haLocation() {
    const states = this._hass?.states || {};
    const candidates = [];
    if (this._config?.location_entity) candidates.push(this._config.location_entity);
    const meId = Object.keys(states).find(
      (id) => id.startsWith("person.") && states[id]?.attributes?.user_id === this._hass.user?.id
    );
    const me = meId ? states[meId] : null;
    if (me) {
      candidates.push(meId);
      candidates.push(...(me.attributes.device_trackers || []));
    }
    let best = null;
    for (const id of candidates) {
      const st = states[id];
      const lat = st?.attributes?.latitude;
      const lon = st?.attributes?.longitude;
      if (typeof lat !== "number" || typeof lon !== "number") continue;
      const updated = new Date(st.last_updated || st.last_changed || 0);
      if (!best || updated > best.updated) best = { lat, lon, updated, id };
    }
    return best;
  }

  async _searchAt(lat, lon, hint) {
    this._s.nearby = null;
    const r = await this._call("search_stations", { latitude: lat, longitude: lon });
    const stations = r.stations || [];
    const km = (m) => (m >= 1000 ? `${(m / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} km` : `${m} m`);
    if (!stations.length) {
      throw new Error(`Keine Station im Umkreis von ${km(r.radius_m || 2000)} gefunden.`);
    }
    this._s.locationHint = hint || null;
    if (!r.expanded) {
      // Direkt am Standort gefunden → gleich die Abfahrten zeigen.
      await this._openStation(stations[0], false);
      return;
    }
    // Suchradius musste vergrößert werden → Auswahl mit Entfernungen anbieten.
    this._s.nearby = { stations, radius: km(r.radius_m) };
  }

  _useHaLocation(reason) {
    const loc = this._haLocation();
    if (!loc) {
      this._s.loading = false;
      this._s.error =
        (reason ? `${reason} ` : "") +
        "Und in Home Assistant ist kein Standort für dich hinterlegt – in der HA-App unter " +
        "Einstellungen → Companion App → Standort die Standortfreigabe aktivieren.";
      this._render();
      return;
    }
    const mins = Math.max(0, Math.round((Date.now() - loc.updated) / 60000));
    const age = mins < 1 ? "gerade eben" : mins < 60 ? `vor ${mins} min` : `vor ${Math.round(mins / 60)} h`;
    this._run(() => this._searchAt(loc.lat, loc.lon, `📍 Standort aus der HA-App (${age})`));
  }

  _nearby() {
    this._s.error = null;
    // In der Companion-App gibt die WebView den Browser-Standort oft nicht frei –
    // dort direkt den Standort nehmen, den die App an HA meldet.
    if (this._inCompanionApp() && this._haLocation()) {
      this._useHaLocation();
      return;
    }
    if (!navigator.geolocation) {
      this._useHaLocation("Der Browser kann keinen Standort ermitteln.");
      return;
    }
    this._s.loading = true;
    this._render();
    navigator.geolocation.getCurrentPosition(
      (pos) => this._run(() => this._searchAt(pos.coords.latitude, pos.coords.longitude, null)),
      (err) => this._useHaLocation(`Browser-Standort nicht verfügbar (${err.message}).`),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
  }

  async _openStation(station, wrap = true) {
    this._s.station = station;
    this._s.when = null;
    this._s.travelType = "";
    this._s.filterHint = null;
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
    let r;
    try {
      r = await this._call("get_departures", data);
    } catch (err) {
      // Mit Verkehrsmittel-Filter meldet Träwelling bei Haltestellen ohne dieses
      // Verkehrsmittel teils „Station nicht gefunden“ – dann ohne Filter laden.
      if (!this._s.travelType) throw err;
      const label = (TYPES.find(([v]) => v === this._s.travelType) || [, "diesem Filter"])[1];
      delete data.travel_type;
      this._s.travelType = "";
      r = await this._call("get_departures", data);
      this._s.filterHint = `Keine Abfahrten mit Filter „${label}“ – zeige alle Verkehrsmittel.`;
    }
    if (r.station?.name) this._s.station = { ...this._s.station, ...r.station };
    this._s.times = r.times || {};
    this._s.departures = r.departures || [];
    this._s.loadedAt = Date.now();
  }

  /** Live-Abfahrten jede Minute neu laden – nur solange sie sichtbar sind. */
  _startLiveRefresh() {
    clearInterval(this._timers.live);
    this._timers.live = setInterval(() => this._refreshLive(), LIVE_REFRESH_MS);
    if (!this._onVisible) {
      this._onVisible = () => {
        if (document.visibilityState === "visible" && Date.now() - (this._s.loadedAt || 0) >= LIVE_REFRESH_MS) {
          this._refreshLive();
        }
      };
      document.addEventListener("visibilitychange", this._onVisible);
    }
  }

  async _refreshLive() {
    const s = this._s;
    if (s.step !== "departures" || s.when || s.loading || document.hidden || !this.isConnected) return;
    try {
      await this._loadDepartures();
      this._render();
    } catch (e) {
      /* nächster Versuch in 60 s */
    }
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
    this._loadTickets();
  }

  async _loadTickets() {
    const day = isoDay(toDate(this._s.departure?.planned)) || isoDay(new Date());
    if (this._s.tickets && this._s.ticketsDate === day) return;
    this._s.tickets = null;
    this._s.ticketsDate = day;
    this._render();
    try {
      const r = await this._call("get_tickets", { date: day });
      const list = r.tickets || [];
      this._s.tickets = { available: r.available !== false, tickets: list };
      if (this._s.ticketId === undefined) {
        // Vorschlag: zuletzt genutzte Fahrkarte laut Träwelling, sonst die
        // zuletzt in dieser Karte gewählte – jeweils nur, wenn am Tag gültig.
        const local = store.get("lastTicket", "");
        const valid = (id) => id && list.some((t) => t.id === id);
        this._s.ticketId = valid(r.suggested) ? r.suggested : valid(local) ? local : "";
      }
    } catch (err) {
      this._s.tickets = { available: false, tickets: [], error: err?.message || String(err) };
      if (this._s.ticketId === undefined) this._s.ticketId = "";
    }
    if (this._s.step === "confirm") this._render();
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
      if (this._s.ticketId) {
        data.ticket_id = this._s.ticketId;
        store.set("lastTicket", this._s.ticketId);
      }
      this._s.result = await this._call("checkin", data);
      this._s.result.ticket_name = (this._s.tickets?.tickets || []).find((t) => t.id === this._s.ticketId)?.name;
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
        const list =
          el.dataset.src === "recent"
            ? this._s.recent
            : el.dataset.src === "home"
              ? [this._s.home]
              : el.dataset.src === "nearby"
                ? this._s.nearby?.stations
                : this._s.results;
        const st = list?.[i ?? 0];
        if (st) {
          this._s.locationHint = null;
          this._openStation(st);
        }
        break;
      }
      case "nearby":
        this._nearby();
        break;
      case "connection":
        this._startConnection();
        break;
      case "type":
        this._s.travelType = el.dataset.v;
        this._s.filterHint = null;
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
    if (t.id === "ticket") this._s.ticketId = t.value;
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

    this._saveFlow();
    if (this._isTravelling() && !this._busy()) {
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

    if (this._upcomingState() && !this._busy()) {
      root.innerHTML = `${STYLE}<ha-card>${this._renderUpcoming()}</ha-card>`;
      return;
    }

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
    const dist = (m) =>
      typeof m === "number" ? (m >= 1000 ? `${(m / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} km` : `${m} m`) : "";
    const item = (st, i, src, icon) => `
      <button class="row" data-a="station" data-src="${src}" data-i="${i}">
        <ha-icon icon="${icon}"></ha-icon>
        <span class="grow">${esc(st.name)}</span>
        ${src === "nearby" && st.distance_m != null ? `<span class="plat">${dist(st.distance_m)}</span>` : ""}
        <ha-icon class="chev" icon="mdi:chevron-right"></ha-icon>
      </button>`;

    if (query.trim().length >= 2) {
      if (results === null) return `<div class="hint">Suche …</div>`;
      if (!results.length) return `<div class="hint">Keine Station gefunden.</div>`;
      return results.map((s, i) => item(s, i, "results", "mdi:map-marker")).join("");
    }
    let html = "";
    const nb = this._s.nearby;
    if (nb?.stations?.length) {
      html += `<div class="label">In der Nähe · erweiterte Suche (bis ca. ${esc(nb.radius)})</div>`;
      html += nb.stations.map((s, i) => item(s, i, "nearby", "mdi:map-marker-radius")).join("");
    }
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
        <span class="title grow">${esc(this._config.title)}</span>
        ${this._isTravelling() || this._upcomingState() ? `<button class="chip" data-a="reset">Zur Fahrt</button>` : ""}
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
      ${this._s.locationHint ? `<div class="sub">${esc(this._s.locationHint)}</div>` : ""}
      ${this._s.filterHint ? `<div class="sub">ℹ️ ${esc(this._s.filterHint)}</div>` : ""}
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
        ${this._ticketField()}
        <div class="two">
          <label class="field"><span>Sichtbarkeit</span><select id="visibility">${opt(VISIBILITY, this._s.visibility)}</select></label>
          <label class="field"><span>Reiseart</span><select id="business">${opt(BUSINESS, this._s.business)}</select></label>
        </div>
        <button class="primary" data-a="checkin" ${this._s.loading ? "disabled" : ""}>
          <ha-icon icon="mdi:check-circle"></ha-icon> Jetzt einchecken
        </button>
      </div>`;
  }

  _ticketField() {
    const t = this._s.tickets;
    if (t === null) {
      return `<label class="field"><span>🎫 Fahrkarte</span><select disabled><option>Lade Fahrkarten …</option></select></label>`;
    }
    if (!t.available || !t.tickets.length) return "";
    const label = (x) =>
      `${esc(x.name)} · ${x.valid_until ? `gültig bis ${esc(deDate(x.valid_until))}` : "unbefristet"}`;
    const opts = [`<option value="" ${!this._s.ticketId ? "selected" : ""}>Keine Fahrkarte</option>`]
      .concat(t.tickets.map((x) => `<option value="${esc(x.id)}" ${x.id === this._s.ticketId ? "selected" : ""}>${label(x)}</option>`))
      .join("");
    return `<label class="field"><span>🎫 Fahrkarte</span><select id="ticket">${opts}</select></label>`;
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
        ${r.ticket_assigned ? `<div class="sub">🎫 ${esc(r.ticket_name || "Fahrkarte")} hinterlegt</div>` : ""}
        ${r.ticket_assigned === false ? `<div class="err">⚠️ Fahrkarte konnte nicht hinterlegt werden${r.ticket_error ? `: ${esc(r.ticket_error)}` : ""}</div>` : ""}
        <div class="actions">
          ${r.url ? `<a class="chip" href="${esc(r.url)}" target="_blank" rel="noopener">Status öffnen</a>` : ""}
          <button class="chip on" data-a="reset">Fertig</button>
        </div>
      </div>`;
  }

  /** Alle eingecheckten Anschlüsse (Sensor „Nächste Fahrt“, Attribut chain). */
  _chain() {
    const a = this._upcomingState()?.attributes;
    if (!a) return [];
    if (Array.isArray(a.chain) && a.chain.length) return a.chain;
    return [{ ...a, transfer: null }]; // ältere Integration ohne Kette
  }

  /** Letzte Fahrt der Kette (bzw. die laufende) – dort geht es weiter. */
  _lastLeg() {
    const chain = this._isTravelling() || this._upcomingState() ? this._chain() : [];
    if (chain.length) return chain[chain.length - 1];
    return this._isTravelling() ? this._travelState()?.attributes : null;
  }

  _connectionLabel() {
    const l = this._lastLeg();
    return l?.destination ? `Anschluss ab ${esc(l.destination)} einchecken` : "Anschluss einchecken";
  }

  /** Check-in direkt an der Ankunftsstation zur Ankunftszeit starten. */
  async _startConnection() {
    this._s.whileTravelling = true;
    const l = this._lastLeg();
    const id = l?.destination_station_id;
    if (id == null) {
      this._render();
      return;
    }
    const arr = toDate(l.arrival_real) || toDate(l.arrival_planned);
    this._s.station = { id, name: l.destination };
    this._s.when = arr && arr > new Date() ? arr.toISOString() : null;
    this._s.travelType = "";
    this._s.filterHint = null;
    this._s.locationHint = arr ? `🔁 Anschluss nach Ankunft um ${hhmm(arr)}` : null;
    this._s.step = "departures";
    await this._run(() => this._loadDepartures());
    this._startLiveRefresh();
  }

  _renderUpcoming() {
    const up = this._upcomingState();
    const a = up.attributes;
    const dep = toDate(a.departure_real || a.departure_planned);
    const mins = dep ? Math.max(0, Math.round((dep - new Date()) / 60000)) : null;
    return `
      <div class="head">
        <ha-icon icon="mdi:clock-start"></ha-icon>
        <span class="title grow">${mins === 0 ? "Fährt jetzt ab" : `Bald unterwegs${mins !== null ? ` · in ${mins} min` : ""}`}</span>
        ${a.url ? `<a class="chip" href="${esc(a.url)}" target="_blank" rel="noopener">Status</a>` : ""}
      </div>
      <div class="pad">
        ${tripHtml(a, { upcoming: true })}
        ${chainHtml(this._chain().slice(1), "Danach")}
        <button class="chip wide" data-a="connection">
          <ha-icon icon="mdi:plus"></ha-icon><span class="ell">${this._connectionLabel()}</span>
        </button>
      </div>`;
  }

  _renderCurrent() {
    const a = this._travelState()?.attributes || {};
    return `
      <div class="head">
        <ha-icon icon="mdi:train"></ha-icon>
        <span class="title grow">Unterwegs</span>
        ${a.url ? `<a class="chip" href="${esc(a.url)}" target="_blank" rel="noopener">Status</a>` : ""}
      </div>
      <div class="pad">
        ${tripHtml(a)}
        ${this._upcomingState() ? chainHtml(this._chain(), this._chain().length > 1 ? "Deine Anschlüsse" : "Dein Anschluss") : ""}
        <button class="chip wide" data-a="connection">
          <ha-icon icon="mdi:swap-horizontal"></ha-icon><span class="ell">${this._connectionLabel()}</span>
        </button>
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
  .trip { position: relative; padding: 14px 14px 12px; border-radius: 14px; background: var(--secondary-background-color); overflow: hidden; }
  .trip::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--line); }
  .trip-top { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .trip .badge { background: var(--line); color: var(--line-fg); }
  .dir { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--secondary-text-color); font-size: .88em; font-style: italic; }
  .pill { flex: none; padding: 2px 8px; border-radius: 10px; font-size: .78em; font-weight: 600; }
  .pill.ok { background: rgba(67, 160, 71, .16); color: var(--success-color, #43a047); }
  .pill.late { background: rgba(219, 68, 55, .16); color: var(--error-color, #db4437); }
  .pill.soon { background: rgba(3, 169, 244, .16); color: var(--primary-color); }
  .stops { position: relative; margin: 12px 0 4px; }
  .stops::before { content: ""; position: absolute; left: 5px; top: 12px; bottom: 12px; width: 2px; border-radius: 1px; background: var(--line); opacity: .55; }
  .stop { position: relative; display: flex; align-items: baseline; gap: 8px; padding: 3px 0 3px 22px; min-width: 0; }
  .stop + .stop { margin-top: 6px; }
  .stop .dot { position: absolute; left: 0; top: 50%; width: 12px; height: 12px; margin-top: -6px; border-radius: 50%; background: var(--card-background-color, #1c1c1c); border: 3px solid var(--line); box-sizing: border-box; }
  .stop.to .dot { background: var(--line); }
  .stop .t { font-weight: 700; font-size: 1.05em; font-variant-numeric: tabular-nums; }
  .stop .d { color: var(--error-color, #db4437); font-size: .8em; font-weight: 600; }
  .stop .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .stop .plat { flex: none; padding: 1px 6px; border-radius: 6px; border: 1px solid var(--divider-color); color: var(--secondary-text-color); font-size: .78em; }
  .progress { position: relative; height: 8px; margin: 18px 12px 8px 0; border-radius: 4px; background: rgba(127, 127, 127, .22); }
  .progress .fill { height: 100%; border-radius: 4px; background: var(--line); transition: width .6s; }
  .progress .knob { position: absolute; top: 50%; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--line); color: var(--line-fg); box-shadow: 0 0 0 3px var(--secondary-background-color); transition: left .6s; }
  .progress .knob ha-icon { --mdc-icon-size: 16px; }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--secondary-text-color); font-size: .85em; }
  .meta span:first-child { color: var(--primary-text-color); font-weight: 600; }
  .next { display: flex; gap: 8px; align-items: flex-start; margin-top: 10px; padding: 10px 12px; border-radius: 10px; background: var(--secondary-background-color); font-size: .92em; }
  .next ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); flex: none; }
  .chain { margin-top: 12px; }
  .chain-h { display: flex; justify-content: space-between; gap: 8px; margin: 0 2px 6px; font-size: .78em; text-transform: uppercase; letter-spacing: .05em; color: var(--secondary-text-color); }
  .chain-h span:last-child { text-transform: none; letter-spacing: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .xfer { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px; margin: 0 0 0 10px; padding: 7px 10px 7px 14px; border-left: 2px dashed var(--divider-color); font-size: .86em; color: var(--secondary-text-color); min-width: 0; }
  .xfer ha-icon { --mdc-icon-size: 18px; flex: none; }
  .xfer .xl { flex: none; }
  .xfer .xl s { opacity: .7; }
  .xfer .xw { flex: 1 1 auto; min-width: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
  .xfer .xlive { flex: none; color: var(--success-color, #43a047); font-size: .8em; }
  .xfer .xwarn, .xfer .xnote { flex: 1 0 100%; box-sizing: border-box; padding-left: 26px; font-size: .92em; line-height: 1.3; }
  .xfer .xnote { color: var(--secondary-text-color); }
  .alert { display: flex; align-items: flex-start; gap: 8px; margin-top: 12px; padding: 10px 12px; border-radius: 10px; font-size: .92em; line-height: 1.3; }
  .alert ha-icon { --mdc-icon-size: 18px; flex: none; }
  .alert.bad { background: rgba(219, 68, 55, .14); color: var(--error-color, #db4437); }
  .alert.warn { background: rgba(255, 166, 0, .14); color: var(--warning-color, #ffa600); }
  .xfer.ok ha-icon { color: var(--primary-color); }
  .xfer.warn, .xfer.warn ha-icon { color: var(--warning-color, #ffa600); }
  .xfer.bad, .xfer.bad ha-icon { color: var(--error-color, #db4437); }
  .leg { position: relative; display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px 10px 14px; border-radius: 12px; background: var(--secondary-background-color); overflow: hidden; }
  .leg::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--line); }
  .leg .badge { background: var(--line); color: var(--line-fg); margin-top: 1px; }
  .leg.cancelled .leg-main { text-decoration: line-through; opacity: .7; }
  .leg-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .leg-l { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-variant-numeric: tabular-nums; }
  .leg-l .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .leg-l .d { color: var(--error-color, #db4437); font-size: .8em; font-weight: 600; }
  .leg-l .plat { padding: 0 6px; border-radius: 6px; border: 1px solid var(--divider-color); }
  .leg-l .in { flex: none; font-size: .8em; color: var(--primary-color); font-weight: 600; }
  .leg-l.sub2 { font-size: .88em; color: var(--secondary-text-color); }
  .chip .ell { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
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

/* ---------------------------------------------------------------------- */
/* Freunde unterwegs                                                      */
/* ---------------------------------------------------------------------- */
/*
 *   type: custom:traewelling-friends-card
 *   # optional:
 *   entity: sensor.trawelling_xyz_freunde_unterwegs
 *   empty_text: Gerade ist niemand unterwegs.
 */
class TraewellingFriendsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = {}; // status_id → { liked, likes } bis der Sensor nachzieht
    this._error = null;
    this.shadowRoot.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-like]");
      if (btn && !btn.disabled) {
        ev.preventDefault();
        this._toggleLike(btn.dataset.like);
      }
    });
  }

  async _toggleLike(statusId) {
    const trip = this._trips().find((t) => String(t.status_id) === String(statusId));
    if (!trip) return;
    const cur = this._view(trip);
    const want = !cur.liked;
    const likes = typeof cur.likes === "number" ? Math.max(0, cur.likes + (want ? 1 : -1)) : cur.likes;
    this._pending[statusId] = { liked: want, likes, busy: true };
    this._error = null;
    this._render();
    try {
      await this._hass.connection.sendMessagePromise({
        type: "call_service",
        domain: DOMAIN,
        service: "like",
        service_data: { status_id: Number(statusId), like: want },
        return_response: true,
      });
      this._pending[statusId] = { liked: want, likes, busy: false };
    } catch (err) {
      delete this._pending[statusId];
      this._error = err?.message || String(err);
    }
    this._render();
  }

  /** Sensorwerte + noch nicht bestätigte eigene Änderung. */
  _view(t) {
    const p = this._pending[t.status_id];
    if (p && p.liked === Boolean(t.liked) && !p.busy) {
      delete this._pending[t.status_id]; // Sensor ist nachgezogen
      return t;
    }
    return p ? { ...t, liked: p.liked, likes: p.likes, busy: p.busy } : t;
  }

  setConfig(config) {
    this._config = { empty_text: "Gerade ist niemand unterwegs.", ...(config || {}) };
    if (this._hass) this._render();
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 3 + 3 * this._trips().length;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    const key = JSON.stringify(this._trips());
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._render();
    }
  }

  connectedCallback() {
    this._tick = setInterval(() => !document.hidden && this._render(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
  }

  _entityId() {
    if (this._config?.entity) return this._config.entity;
    const hass = this._hass;
    const own = Object.values(hass?.entities || {})
      .filter((e) => e.platform === DOMAIN && e.entity_id.startsWith("sensor."))
      .map((e) => e.entity_id);
    const all = Object.keys(hass?.states || {}).filter((id) => id.startsWith("sensor."));
    for (const ids of [own, all]) {
      const hit =
        ids.find((id) => /freunde_unterwegs$/.test(id)) ||
        ids.find((id) => Array.isArray(hass.states[id]?.attributes?.trips) && /tra?e?welling/.test(id));
      if (hit) return hit;
    }
    return undefined;
  }

  _trips() {
    const id = this._entityId();
    const trips = id ? this._hass?.states[id]?.attributes?.trips : null;
    return Array.isArray(trips) ? trips : [];
  }

  /** Startet noch – live nach Uhrzeit, nicht nur nach dem letzten Poll. */
  _isSoon(t) {
    const dep = toDate(t.departure || t.departure_planned);
    return dep ? dep > new Date() : Boolean(t.upcoming);
  }

  _nextHtml(n) {
    const dep = toDate(n.departure_planned || n.departure);
    const dDep = delayMin(n.departure_planned, n.departure);
    return `<div class="next"><ha-icon icon="mdi:arrow-right-bottom"></ha-icon>
      <span>Danach: <b>${esc(n.line || "Fahrt")}</b> um <b>${hhmm(dep)}</b>${dDep > 0 ? ` <span class="late">+${dDep}</span>` : ""} ab ${esc(n.origin)}${n.origin_platform ? ` · Gl. ${esc(n.origin_platform)}` : ""} → ${esc(n.destination)}</span></div>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const trips = this._trips();
    const initials = (n) =>
      String(n || "?")
        .split(/\s+/)
        .map((x) => x[0])
        .join("")
        .slice(0, 2)
        .toUpperCase();
    const body = trips.length
      ? trips
          .map((raw) => {
            const t = this._view(raw);
            const likeBtn =
              t.status_id != null && t.likable !== false
                ? `<button class="like ${t.liked ? "on" : ""}" data-like="${esc(t.status_id)}" ${t.busy ? "disabled" : ""}
                     aria-pressed="${t.liked ? "true" : "false"}" title="${t.liked ? "Like zurücknehmen" : "Gefällt mir"}">
                     <ha-icon icon="${t.liked ? "mdi:heart" : "mdi:heart-outline"}"></ha-icon>${
                       typeof t.likes === "number" && t.likes > 0 ? `<span>${t.likes}</span>` : ""
                     }</button>`
                : "";
            const profile = t.profile_url || (t.username ? `https://traewelling.de/@${t.username}` : null);
            const avatar = t.avatar
              ? `<img class="avatar" src="${esc(t.avatar)}" alt="" loading="lazy">`
              : `<span class="avatar initials">${esc(initials(t.name))}</span>`;
            const who = `${avatar}<span class="names"><span class="title">${esc(t.name)}</span>${
              t.username ? `<small>@${esc(t.username)}</small>` : ""
            }</span>`;
            return `
            <div class="friend">
              <div class="head">
                ${profile ? `<a class="who grow" href="${esc(profile)}" target="_blank" rel="noopener">${who}</a>` : `<span class="who grow">${who}</span>`}
                ${likeBtn}
                ${t.url ? `<a class="chip" href="${esc(t.url)}" target="_blank" rel="noopener">Status</a>` : ""}
              </div>
              <div class="pad">
                ${tripHtml({ ...t, points: null }, { upcoming: this._isSoon(t) })}
                ${t.next && !this._isSoon(t) ? this._nextHtml(t.next) : ""}
              </div>
            </div>`;
          })
          .join("")
      : `<div class="empty"><ha-icon icon="mdi:sofa-outline"></ha-icon><span>${esc(this._config.empty_text)}</span></div>`;
    const err = this._error ? `<div class="err">⚠️ ${esc(this._error)}</div>` : "";
    this.shadowRoot.innerHTML = `${STYLE}${FRIENDS_STYLE}<ha-card>${body}${err}</ha-card>`;
  }
}

const FRIENDS_STYLE = `<style>
  .friend + .friend { border-top: 1px solid var(--divider-color); }
  .friend .pad { padding-top: 4px; }
  .who { display: flex; align-items: center; gap: 12px; min-width: 0; color: var(--primary-text-color); text-decoration: none; }
  .names { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }
  .names .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .names small { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .avatar { width: 38px; height: 38px; border-radius: 50%; object-fit: cover; flex: none; background: var(--secondary-background-color); }
  .avatar.initials { display: flex; align-items: center; justify-content: center; background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 700; font-size: .9em; }
  .like { display: inline-flex; align-items: center; gap: 4px; padding: 6px 10px; border-radius: 18px; background: var(--secondary-background-color); color: var(--secondary-text-color); font-size: .9em; font-variant-numeric: tabular-nums; }
  .like ha-icon { --mdc-icon-size: 18px; }
  .like.on { color: #e91e63; background: rgba(233, 30, 99, .14); }
  .like.on ha-icon { animation: pop .3s ease-out; }
  @keyframes pop { 0% { transform: scale(.6); } 60% { transform: scale(1.25); } 100% { transform: scale(1); } }
  .empty { display: flex; align-items: center; gap: 12px; padding: 18px 16px; color: var(--secondary-text-color); }
  .empty ha-icon { color: var(--secondary-text-color); }
</style>`;

if (!customElements.get("traewelling-friends-card")) {
  customElements.define("traewelling-friends-card", TraewellingFriendsCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "traewelling-friends-card",
    name: "Träwelling Freunde unterwegs",
    description: "Laufende und bald startende Fahrten der Leute, denen du folgst",
    preview: false,
  });
}

/* ---------------------------------------------------------------------- */
/* Statistik                                                              */
/* ---------------------------------------------------------------------- */
/*
 *   type: custom:traewelling-stats-card
 *   # optional:
 *   title: Statistik
 *   show_leaderboard: true
 *   show_favorites: true
 *   metric: checkins
 *   header: true                # false = ohne eigene Kopfzeile (für Dashboard-Überschriften)
 *   show: [kpis, facts]         # nur bestimmte Bausteine: kpis, facts, chart, longest,
 *                               # favorites | fav_stations | fav_lines | fav_routes, leaderboard            # oder km – Startansicht des Diagramms
 */
const MONTHS_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const fmt0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

class TraewellingStatsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._metric = null;
    this._hover = null;
  }

  setConfig(config) {
    this._config = {
      title: "Statistik",
      show_leaderboard: true,
      show_favorites: true,
      metric: "checkins",
      ...(config || {}),
    };
    this._metric = this._metric || store.get("statsMetric", this._config.metric);
    if (this._hass) this._render();
  }

  static getStubConfig() {
    return {};
  }

  /** Welche Bausteine diese Karte zeigt (Standard: alle). */
  _parts() {
    const all = ["kpis", "facts", "chart", "longest", "fav_stations", "fav_lines", "fav_routes", "leaderboard"];
    let show = this._config.show;
    if (typeof show === "string") show = [show];
    if (!Array.isArray(show) || !show.length) {
      show = all.filter(
        (p) =>
          (this._config.show_favorites !== false || !p.startsWith("fav_")) &&
          (this._config.show_leaderboard !== false || p !== "leaderboard")
      );
    }
    return show.flatMap((p) => (p === "favorites" ? ["fav_stations", "fav_lines", "fav_routes"] : [p]));
  }

  /** Alles-in-einer-Karte → Zwischenüberschriften zeigen. */
  _full() {
    return this._config.header !== false && this._parts().length > 3;
  }

  getCardSize() {
    return Math.max(2, Math.min(9, this._parts().length * 2));
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    const key = JSON.stringify(this._snapshot());
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._render();
    }
  }

  _ents() {
    if (this._entCache && this._entCacheSize === Object.keys(this._hass.states).length) return this._entCache;
    const hass = this._hass;
    const own = Object.values(hass.entities || {})
      .filter((e) => e.platform === DOMAIN && e.entity_id.startsWith("sensor."))
      .map((e) => e.entity_id);
    this._entCache = own.length ? own : Object.keys(hass.states).filter((id) => /^sensor\.tra?e?welling/.test(id));
    this._entCacheSize = Object.keys(hass.states).length;
    return this._entCache;
  }

  _st(suffix) {
    const id = this._ents().find((x) => x.endsWith(`_${suffix}`));
    return id ? this._hass.states[id] : undefined;
  }

  _num(suffix) {
    const v = parseFloat(this._st(suffix)?.state);
    return Number.isFinite(v) ? v : null;
  }

  _snapshot() {
    const keys = [
      "check_ins_diese_woche", "check_ins_diesen_monat", "check_ins_dieses_jahr", "check_ins_gesamt",
      "distanz_diese_woche", "distanz_diesen_monat", "distanz_dieses_jahr", "distanz_gesamt",
      "punkte_gesamt", "reisezeit_gesamt", "aktive_reisetage", "durchschnittsdistanz",
    ];
    return {
      v: keys.map((k) => this._st(k)?.state),
      m: this._st("monatsverlauf")?.attributes?.months,
      l: this._st("langste_fahrt_dieses_jahr")?.attributes,
      r: this._config?.show_leaderboard ? this._st("rang_unter_freunden")?.attributes?.leaderboard : null,
      f: this._config?.show_favorites
        ? ["lieblingsstation", "lieblingslinie", "lieblingsstrecke"].map((k) => this._st(k)?.attributes?.top)
        : null,
    };
  }

  _n(v) {
    return v === null || v === undefined ? "–" : fmt0.format(v);
  }

  _chart(months) {
    const metric = this._metric === "km" ? "km" : "checkins";
    const vals = months.map((m) => (typeof m[metric] === "number" ? m[metric] : null));
    const max = Math.max(1, ...vals.filter((v) => v !== null));
    // „schöne" Skala: 0, ½, 1 × gerundetes Maximum
    const mag = Math.pow(10, Math.floor(Math.log10(max)));
    const top = Math.ceil(max / mag) * mag;
    const W = 420, H = 180, padL = 32, padR = 4, padT = 20, padB = 22;
    const cw = (W - padL - padR) / months.length;
    const bw = Math.max(6, cw - 6);
    const y = (v) => padT + (H - padT - padB) * (1 - v / top);
    const maxIdx = vals.indexOf(Math.max(...vals.filter((v) => v !== null)));
    const unit = metric === "km" ? " km" : "";

    const grid = [0, top / 2, top]
      .map(
        (g) => `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y(g)}" y2="${y(g)}"></line>
                <text class="axis" x="${padL - 6}" y="${y(g) + 4}" text-anchor="end">${fmt0.format(g)}</text>`
      )
      .join("");

    const bars = months
      .map((m, i) => {
        const v = vals[i];
        const x = padL + i * cw + (cw - bw) / 2;
        const label = MONTHS_DE[parseInt(m.month.slice(5, 7), 10) - 1] || m.month;
        let bar = "";
        if (v !== null && v > 0) {
          const h = Math.max(2, H - padB - y(v));
          const r = Math.min(4, bw / 2, h);
          const yt = H - padB - h;
          bar = `<path class="bar ${m.current ? "cur" : ""} ${this._hover === i ? "hot" : ""}"
            d="M${x},${H - padB} V${yt + r} Q${x},${yt} ${x + r},${yt} H${x + bw - r} Q${x + bw},${yt} ${x + bw},${yt + r} V${H - padB} Z"></path>`;
        }
        const showVal = v !== null && (m.current || i === maxIdx || this._hover === i);
        return `${bar}
          ${showVal ? `<text class="val" x="${x + bw / 2}" y="${(v > 0 ? y(v) : H - padB) - 6}" text-anchor="middle">${fmt0.format(v)}</text>` : ""}
          <text class="axis ${m.current ? "cur" : ""}" x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${label}</text>
          <rect class="hit" data-i="${i}" x="${padL + i * cw}" y="0" width="${cw}" height="${H}">
            <title>${label} ${m.month.slice(0, 4)}: ${v === null ? "keine Daten" : fmt0.format(v) + unit}</title></rect>`;
      })
      .join("");

    const hv = this._hover !== null ? months[this._hover] : null;
    const tip = hv
      ? `${MONTHS_DE[parseInt(hv.month.slice(5, 7), 10) - 1]} ${hv.month.slice(0, 4)} · <b>${this._n(hv.checkins)}</b> Check-ins · <b>${this._n(hv.km)}</b> km`
      : `Letzte 12 Monate · ${metric === "km" ? "Kilometer" : "Check-ins"} pro Monat`;

    return `
      <div class="chart-head">
        <span class="tip">${tip}</span>
        <div class="seg" role="tablist">
          <button role="tab" class="${metric === "checkins" ? "on" : ""}" data-metric="checkins">Check-ins</button>
          <button role="tab" class="${metric === "km" ? "on" : ""}" data-metric="km">km</button>
        </div>
      </div>
      <svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${metric === "km" ? "Kilometer" : "Check-ins"} pro Monat, letzte 12 Monate">
        ${grid}<line class="base" x1="${padL}" x2="${W - padR}" y1="${H - padB}" y2="${H - padB}"></line>${bars}
      </svg>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const kpi = (label, c, km) => `
      <div class="kpi">
        <span class="k-label">${label}</span>
        <span class="k-val">${this._n(this._num(c))}</span>
        <span class="k-sub">${this._n(this._num(km))} km</span>
      </div>`;
    const months = this._st("monatsverlauf")?.attributes?.months;
    const longest = this._st("langste_fahrt_dieses_jahr");
    const lr = longest?.attributes || {};
    const board = this._config.show_leaderboard ? this._st("rang_unter_freunden")?.attributes?.leaderboard : null;

    const facts = [
      ["mdi:star-four-points", this._n(this._num("punkte_gesamt")), "Punkte"],
      ["mdi:timer-outline", this._n(this._num("reisezeit_gesamt")), "Std. unterwegs"],
      ["mdi:calendar-check", this._n(this._num("aktive_reisetage")), "Reisetage"],
      ["mdi:map-marker-distance", this._n(this._num("durchschnittsdistanz")), "km Ø pro Fahrt"],
    ]
      .map(([i, v, l]) => `<div class="fact"><ha-icon icon="${i}"></ha-icon><b>${v}</b><span>${l}</span></div>`)
      .join("");

    const longestHtml =
      lr.origin && longest
        ? `<a class="longest" ${lr.url ? `href="${esc(lr.url)}" target="_blank" rel="noopener"` : ""}>
            <ha-icon icon="mdi:trophy"></ha-icon>
            <span class="grow"><small>Längste Fahrt ${new Date().getFullYear()}</small>
              <span>${esc(lr.line || "")} ${esc(lr.origin)} → ${esc(lr.destination)}</span></span>
            <b>${this._n(parseFloat(longest.state))} km</b></a>`
        : "";

    const medal = (r) => (r === 1 ? "🥇" : r === 2 ? "🥈" : r === 3 ? "🥉" : r);
    const boardHtml =
      Array.isArray(board) && board.length
        ? `${this._full() ? `<div class="sec-title"><ha-icon icon="mdi:podium"></ha-icon> Freunde · letzte 7 Tage</div>` : ""}
           <div class="board">${board
             .slice(0, 5)
             .map(
               (p) => `
              <a class="brow ${p.me ? "me" : ""}" ${!p.me && p.username ? `href="https://traewelling.de/@${esc(p.username)}" target="_blank" rel="noopener"` : ""}>
                <span class="rank">${medal(p.rank)}</span>
                <span class="grow">${esc(p.name)}${p.me ? " <small>(du)</small>" : ""}</span>
                <span class="pts">${this._n(p.points)} P</span>
                <span class="bkm">${this._n(p.distance_km)} km</span>
              </a>`
             )
             .join("")}</div>`
        : "";

    const favList = (suffix, icon, title, label) => {
      const top = this._st(suffix)?.attributes?.top;
      if (!Array.isArray(top) || !top.length) return "";
      const maxCount = Math.max(1, ...top.map((x) => x.count || 0));
      return `<div class="fav">
          <div class="fav-title"><ha-icon icon="${icon}"></ha-icon>${title}</div>
          ${top
            .slice(0, 3)
            .map(
              (x) => `<div class="fav-row">
                <span class="fav-name">${esc(label(x))}</span>
                <span class="fav-count">${this._n(x.count)}×</span>
                <span class="fav-bar"><span style="width:${((x.count || 0) / maxCount) * 100}%"></span></span>
              </div>`
            )
            .join("")}
        </div>`;
    };
    const favParts = {
      fav_stations: () => favList("lieblingsstation", "mdi:bank", "Stationen", (x) => x.name),
      fav_lines: () =>
        favList("lieblingslinie", "mdi:train-variant", "Linien", (x) =>
          /^\d+$/.test(String(x.linename)) ? `Linie ${x.linename}` : x.linename
        ),
      fav_routes: () =>
        favList("lieblingsstrecke", "mdi:swap-horizontal", "Strecken", (x) => `${x.origin} → ${x.destination}`),
    };
    const parts = this._parts();
    const favs = Object.keys(favParts)
      .filter((k) => parts.includes(k))
      .map((k) => favParts[k]())
      .join("");
    const favHtml = favs
      ? `${this._full() ? `<div class="sec-title"><ha-icon icon="mdi:heart"></ha-icon> Favoriten ${new Date().getFullYear()}</div>` : ""}<div class="favs">${favs}</div>`
      : "";

    const blocks = {
      kpis: () => `<div class="kpis">
          ${kpi("Woche", "check_ins_diese_woche", "distanz_diese_woche")}
          ${kpi("Monat", "check_ins_diesen_monat", "distanz_diesen_monat")}
          ${kpi("Jahr", "check_ins_dieses_jahr", "distanz_dieses_jahr")}
          ${kpi("Gesamt", "check_ins_gesamt", "distanz_gesamt")}
        </div>`,
      facts: () => `<div class="facts">${facts}</div>`,
      chart: () =>
        Array.isArray(months) && months.length
          ? this._chart(months)
          : `<div class="hint">Monatsverlauf wird geladen …</div>`,
      longest: () => longestHtml,
      favorites: () => favHtml,
      leaderboard: () =>
        boardHtml || (this._full() ? "" : `<div class="hint">Noch keine Rangliste – folgst du schon jemandem?</div>`),
    };
    const order = ["kpis", "facts", "chart", "longest", "favorites", "leaderboard"];
    const want = new Set(parts.map((p) => (p.startsWith("fav_") ? "favorites" : p)));
    const inner = order
      .filter((k) => want.has(k))
      .map((k) => blocks[k]())
      .join("");
    const header =
      this._config.header === false
        ? ""
        : `<div class="head">
        <ha-icon icon="mdi:chart-bar"></ha-icon>
        <span class="title grow">${esc(this._config.title)}</span>
        <a class="chip" href="https://traewelling.de/statistics" target="_blank" rel="noopener">traewelling.de <ha-icon icon="mdi:open-in-new"></ha-icon></a>
      </div>`;
    this.shadowRoot.innerHTML = `${STYLE}${STATS_STYLE}<ha-card>
      ${header}
      <div class="pad ${header ? "" : "nohead"} parts-${want.size === 1 ? [...want][0] : "multi"}">${inner}</div>
    </ha-card>`;
    this._wire();
  }

  _wire() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-metric]").forEach((b) =>
      b.addEventListener("click", () => {
        this._metric = b.dataset.metric;
        store.set("statsMetric", this._metric);
        this._render();
      })
    );
    root.querySelectorAll("rect.hit").forEach((r) => {
      const i = Number(r.dataset.i);
      const on = () => {
        if (this._hover !== i) {
          this._hover = i;
          this._render();
        }
      };
      r.addEventListener("pointerenter", on);
      r.addEventListener("click", on);
    });
    const svg = root.querySelector("svg.chart");
    if (svg)
      svg.addEventListener("pointerleave", () => {
        if (this._hover !== null) {
          this._hover = null;
          this._render();
        }
      });
  }
}

const STATS_STYLE = `<style>
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  .kpi { display: flex; flex-direction: column; gap: 2px; padding: 10px 10px 9px; border-radius: 12px; background: var(--secondary-background-color); min-width: 0; }
  .k-label { font-size: .75em; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .k-val { font-size: 1.6em; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .k-sub { font-size: .8em; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .facts { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px 12px; margin: 12px 2px 4px; }
  .fact { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: .9em; }
  .fact ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); flex: none; }
  .fact span { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chart-head { display: flex; align-items: center; gap: 10px; margin: 14px 0 4px; }
  .chart-head .tip { flex: 1; min-width: 0; font-size: .85em; color: var(--secondary-text-color); }
  .chart-head .tip b { color: var(--primary-text-color); }
  .seg { display: inline-flex; padding: 2px; border-radius: 10px; background: var(--secondary-background-color); flex: none; }
  .seg button { padding: 5px 10px; border-radius: 8px; font-size: .82em; color: var(--secondary-text-color); }
  .seg button.on { background: var(--card-background-color, #1c1c1c); color: var(--primary-text-color); box-shadow: 0 1px 2px rgba(0,0,0,.25); }
  svg.chart { display: block; width: 100%; height: auto; overflow: visible; touch-action: pan-y; }
  .chart .grid { stroke: var(--divider-color); stroke-width: 1; stroke-dasharray: 2 4; }
  .chart .base { stroke: var(--divider-color); stroke-width: 1; }
  .chart .axis { fill: var(--secondary-text-color); font-size: 11px; }
  .chart .axis.cur { fill: var(--primary-text-color); font-weight: 700; }
  .chart .val { fill: var(--primary-text-color); font-size: 11px; font-weight: 700; }
  .chart .bar { fill: var(--primary-color); opacity: .45; transition: opacity .2s; }
  .chart .bar.cur, .chart .bar.hot { opacity: 1; }
  .chart .hit { fill: transparent; cursor: pointer; }
  .longest { display: flex; align-items: center; gap: 12px; margin-top: 12px; padding: 10px 12px; border-radius: 12px; background: var(--secondary-background-color); color: var(--primary-text-color); text-decoration: none; }
  .longest ha-icon { color: #f6b400; flex: none; }
  .longest .grow { display: flex; flex-direction: column; min-width: 0; }
  .longest .grow span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .longest small { color: var(--secondary-text-color); }
  .longest b { flex: none; font-variant-numeric: tabular-nums; }
  .sec-title { display: flex; align-items: center; gap: 8px; margin: 16px 0 6px; font-size: .85em; font-weight: 600; color: var(--secondary-text-color); }
  .sec-title ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); }
  .board { display: flex; flex-direction: column; }
  .brow { display: flex; align-items: center; gap: 10px; padding: 7px 4px; border-top: 1px solid var(--divider-color); color: var(--primary-text-color); text-decoration: none; font-variant-numeric: tabular-nums; }
  .brow:first-child { border-top: 0; }
  .brow.me { font-weight: 700; }
  .brow small { color: var(--secondary-text-color); font-weight: 400; }
  .rank { width: 24px; text-align: center; flex: none; }
  .pts { flex: none; min-width: 52px; text-align: right; }
  .bkm { flex: none; min-width: 64px; text-align: right; color: var(--secondary-text-color); }
  .chip ha-icon { --mdc-icon-size: 14px; }
  .pad.nohead { padding-top: 16px; }
  .parts-chart .chart-head { margin-top: 0; }
  .parts-longest .longest, .parts-favorites .favs { margin-top: 0; }
  .parts-facts .facts { margin: 0; }
  .parts-longest .longest { padding: 0; background: none; }
  .parts-favorites .fav { padding: 0; background: none; }
  .favs { display: grid; gap: 10px; }
  .fav { padding: 10px 12px; border-radius: 12px; background: var(--secondary-background-color); }
  .fav-title { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: .8em; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .fav-title ha-icon { --mdc-icon-size: 16px; color: var(--primary-color); }
  .fav-row { display: grid; grid-template-columns: 1fr auto; align-items: center; column-gap: 10px; padding: 4px 0; }
  .fav-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fav-count { font-variant-numeric: tabular-nums; color: var(--secondary-text-color); font-size: .9em; }
  .fav-bar { grid-column: 1 / -1; height: 4px; margin-top: 4px; border-radius: 2px; background: rgba(127, 127, 127, .18); overflow: hidden; }
  .fav-bar span { display: block; height: 100%; border-radius: 2px; background: var(--primary-color); opacity: .7; }
  @media (max-width: 460px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
</style>`;

if (!customElements.get("traewelling-stats-card")) {
  customElements.define("traewelling-stats-card", TraewellingStatsCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "traewelling-stats-card",
    name: "Träwelling Statistik",
    description: "Kennzahlen, Monatsdiagramm und Freunde-Rangliste",
    preview: false,
  });
}
