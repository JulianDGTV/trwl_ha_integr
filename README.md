# 🚆 Träwelling für Home Assistant

Custom Integration für [traewelling.de](https://traewelling.de): deine laufende
Fahrt, die Fahrten deiner Freunde, deine Reisestatistiken – und Check-in direkt
aus dem Dashboard.

## ✨ Features

- **Meine Fahrt** – Linie, Start/Ziel, Zeiten, Verspätung, Gleis, Fortschritt, Restzeit
- **Freunde unterwegs** – alle gerade laufenden Fahrten der Accounts, denen du folgst, mit Link zum Profil
- **Check-in-Karte** – Station suchen (oder per Standort), Live-Abfahrten mit Verspätung und Gleis, Ausstieg wählen, einchecken
- **Statistik** – Check-ins und Distanz für Monat, Jahr und gesamt, Punkte, Reisezeit, aktive Tage
- **Services** für Stationssuche, Abfahrten, Fahrtverlauf und Check-in – nutzbar in eigenen Automationen

## 📦 Installation

**HACS (empfohlen):** HACS → ⋮ → *Benutzerdefinierte Repositories* →
`https://github.com/JulianDGTV/trwl_ha_integr`, Kategorie *Integration* →
*Träwelling* herunterladen → Home Assistant neu starten.

**Manuell:** Ordner `custom_components/traewelling` nach
`<config>/custom_components/traewelling` kopieren und neu starten.

Danach: **Einstellungen → Geräte & Dienste → Integration hinzufügen → Träwelling**.

## 🔑 Access Token

Auf traewelling.de unter **Einstellungen → API / Anwendungen** einen persönlichen
Access Token anlegen:

| Scope | Wofür |
|---|---|
| `read-statuses` | aktive Fahrt und Fahrten deiner Freunde |
| `read-statistics` | Statistik-Sensoren |
| `write-statuses` | Check-in-Karte (Stationen, Abfahrten, Einchecken) |

Fehlt ein Scope, läuft der Rest trotzdem weiter – nur der betroffene Teil bleibt
leer bzw. zeigt einen Hinweis.

**Token austauschen** (z. B. um `write-statuses` nachzurüsten):
Einstellungen → Geräte & Dienste → Träwelling → ⋮ → **Neu konfigurieren**.

## 📊 Entitäten

> Die Entity-IDs enthalten den Gerätenamen, z. B.
> `sensor.trawelling_deinname_punkte_gesamt`. Unten steht jeweils nur das Ende.
> Die Dashboard-Vorlage findet die Entitäten automatisch.

**Aktive Fahrt** (Abfrage standardmäßig alle 60 s)

| Entität endet auf | Beschreibung |
|---|---|
| `binary_sensor…_unterwegs` | An, solange ein Check-in läuft; alle Fahrtdetails als Attribute |
| `…_aktuelle_fahrt` | Linienname, z. B. „RE 5“ |
| `…_start` / `…_ziel` | Start- und Zielhaltestelle |
| `…_abfahrt` / `…_ankunft` | Zeitstempel (Echtzeit, sonst Plan) |
| `…_verspatung_abfahrt` / `…_verspatung_ankunft` | Minuten |
| `…_restfahrzeit` | Minuten bis Ankunft |
| `…_fahrtfortschritt` | 0–100 % |
| `…_distanz_aktuelle_fahrt` / `…_punkte_aktuelle_fahrt` | km / Punkte |

**Freunde unterwegs** (zusammen mit der aktiven Fahrt abgefragt)

| Entität endet auf | Beschreibung |
|---|---|
| `…_freunde_unterwegs` | Anzahl der Freunde, die gerade fahren |

„Freunde“ sind alle Accounts, denen du folgst (Quelle `/dashboard`, inkl.
privater Profile, die dich zugelassen haben). Das Attribut `trips` enthält pro
Person die laufende Fahrt, nach Ankunft sortiert:

| Feld | Inhalt |
|---|---|
| `name`, `username`, `avatar`, `profile_url` | Anzeigename, Benutzername, Profilbild, Link zum Profil |
| `line`, `category` | Linie und Verkehrsmittel |
| `origin`, `destination` | Start- und Zielhaltestelle |
| `departure`, `arrival` | Abfahrt/Ankunft (Echtzeit, sonst Plan) |
| `departure_planned`, `arrival_planned`, `delay_arrival` | Planzeiten, Verspätung in Minuten |
| `progress`, `minutes_left` | Fortschritt und Restzeit (Stand letzte Abfrage) |
| `distance_km`, `body`, `url` | Distanz, Status-Text, Link zum Status |

**Statistik** (standardmäßig alle 30 min – die API cacht serverseitig 1–6 h)

| Entität endet auf | Quelle |
|---|---|
| `…_punkte_gesamt`, `…_distanz_gesamt`, `…_reisezeit_gesamt` | Profil |
| `…_check_ins_gesamt`, `…_aktive_reisetage` | `/statistics/overview` |
| `…_check_ins_diesen_monat`, `…_distanz_diesen_monat` | `/statistics/overview` ab Monatsanfang |
| `…_check_ins_dieses_jahr`, `…_distanz_dieses_jahr` | `/statistics/overview` ab Jahresanfang |

Intervalle und Statistik-Startdatum: Integration → **Konfigurieren**.

## 🎫 Check-in-Karte

Die Karte wird von der Integration automatisch mitgeliefert – keine Ressource,
kein HACS-Frontend-Repo nötig. Im Karten-Picker heißt sie **„Träwelling Check-in“**.

```yaml
type: custom:traewelling-checkin-card
# alles optional:
title: Einchecken
show_current_trip: true   # false = Karte ausblenden, solange du unterwegs bist
entity: binary_sensor.trawelling_deinname_unterwegs   # sonst automatisch
```

**So funktioniert sie:**

1. **Nicht unterwegs** → Suchfeld, Button „Station in meiner Nähe“, dazu Heimatbahnhof und zuletzt genutzte Stationen
2. **Station gewählt** → Live-Abfahrten (aktualisieren sich jede Minute) mit Verspätung, Gleis(wechsel) und Ausfällen, Filter nach Verkehrsmittel, blättern mit „Früher/Später“
3. **Abfahrt gewählt** → alle folgenden Halte mit Ankunftszeiten
4. **Ausstieg gewählt** → Statustext, Sichtbarkeit und Reiseart, dann „Jetzt einchecken“
5. **Unterwegs** → die Karte zeigt deine laufende Fahrt mit Fortschrittsbalken

Sichtbarkeit, Reiseart und Verkehrsmittel-Filter merkt sich die Karte pro Gerät.
Der Token bleibt dabei in Home Assistant – die Karte spricht nur mit den
Services der Integration.

## 🛠️ Services

| Service | Rückgabe | Zweck |
|---|---|---|
| `traewelling.search_stations` | ✅ | `query` → Treffer · `latitude`/`longitude` → nächste Station · ohne Angaben → Heimatbahnhof + zuletzt genutzt |
| `traewelling.get_departures` | ✅ | `station_id`, optional `when`, `travel_type` |
| `traewelling.get_trip` | ✅ | `trip_id`, `line_name` → alle Halte |
| `traewelling.checkin` | optional | `trip_id`, `line_name`, `start_id`, `destination_id`, `departure`, `arrival`, optional `body`, `visibility`, `business`, `toot` |

Beispiel (Entwicklerwerkzeuge → Aktionen, „Antwort zurückgeben“):

```yaml
action: traewelling.search_stations
data:
  query: Hannover Hbf
```

## 🖥️ Dashboard

Fertige Ansicht mit **Meine Fahrt** (Check-in-Karte), **Freunde unterwegs**
(Name antippen → Profil) und **Statistik**.

Einfügen: Dashboard bearbeiten → **„+“** (neue Ansicht) → ⋮ →
**„In YAML bearbeiten“** → Inhalt ersetzen → Speichern.

```yaml
title: Träwelling
path: traewelling
icon: mdi:train
type: sections
max_columns: 3
sections:
  - type: grid
    cards:
      - type: heading
        heading: Meine Fahrt
        icon: mdi:train
      - type: custom:traewelling-checkin-card
        grid_options:
          columns: full

  - type: grid
    cards:
      - type: heading
        heading: Freunde unterwegs
        icon: mdi:account-group
      - type: markdown
        grid_options:
          columns: full
        content: |-
          {% set e = integration_entities('traewelling') %}
          {% set f = e | select('search', 'freunde_unterwegs$') | first | default(none) %}
          {% set trips = state_attr(f, 'trips') if f else [] %}
          {% if trips %}
          {% for t in trips %}
          {% set dep = as_datetime(t.departure) %}
          {% set arr = as_datetime(t.arrival) %}
          {% set p = ((now() - dep).total_seconds() / ((arr - dep).total_seconds() or 1) * 100) | round(0) | int %}
          {% set p = [0, [100, p] | min] | max %}
          {% set n = (p / 5) | round(0) | int %}
          {% set left = [0, ((arr - now()).total_seconds() / 60) | int] | max %}

          ### 👤 [{{ t.name }}](https://traewelling.de/@{{ t.username }}){% if t.line %} · {{ t.line }}{% endif %}

          **{{ t.origin }}** → **{{ t.destination }}**

          🕐 {{ as_local(dep).strftime('%H:%M') }} → {{ as_local(arr).strftime('%H:%M') }}{% if t.delay_arrival and t.delay_arrival > 0 %} (+{{ t.delay_arrival }}){% endif %}

          `{{ '█' * n }}{{ '░' * (20 - n) }}` **{{ p }} %** · noch {{ left }} min
          {% if not loop.last %}

          ---
          {% endif %}
          {% endfor %}
          {% else %}
          Gerade ist niemand unterwegs.
          {% endif %}

  - type: grid
    cards:
      - type: heading
        heading: Statistik
        icon: mdi:chart-bar
      - type: markdown
        grid_options:
          columns: full
        content: |-
          {% set e = integration_entities('traewelling') %}
          {% macro v(key) -%}
          {%- set x = e | select('search', '_' ~ key ~ '$') | first | default(none) -%}
          {%- if x and states(x) not in ['unknown', 'unavailable'] -%}
          {{ (states(x) ~ ' ' ~ (state_attr(x, 'unit_of_measurement') or '')) | trim }}
          {%- else -%}–{%- endif -%}
          {%- endmacro %}

          | | Monat | Jahr | Gesamt |
          |---|---:|---:|---:|
          | 🎫 Check-ins | {{ v('check_ins_diesen_monat') }} | {{ v('check_ins_dieses_jahr') }} | {{ v('check_ins_gesamt') }} |
          | 📏 Distanz | {{ v('distanz_diesen_monat') }} | {{ v('distanz_dieses_jahr') }} | {{ v('distanz_gesamt') }} |

          ⭐ **{{ v('punkte_gesamt') }}** Punkte · ⏱️ **{{ v('reisezeit_gesamt') }}** Reisezeit · 📅 **{{ v('aktive_reisetage') }}** aktive Tage
```

## 🤖 Automatisierungs-Beispiele

```yaml
automation:
  - alias: "Benachrichtigung, wenn ein Freund losfährt"
    triggers:
      - trigger: state
        entity_id: sensor.traewelling_freunde_unterwegs
    conditions:
      - condition: template
        value_template: >-
          {{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    actions:
      - action: notify.notify
        data:
          message: >-
            {% set t = state_attr('sensor.traewelling_freunde_unterwegs', 'trips') | sort(attribute='departure') | last %}
            {{ t.name }} fährt gerade {{ t.line }} von {{ t.origin }} nach {{ t.destination }}.

  - alias: "Licht an, wenn Zug bald ankommt"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.traewelling_restfahrzeit
        below: 10
    conditions:
      - condition: state
        entity_id: binary_sensor.traewelling_unterwegs
        state: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.flur
```

Entity-IDs an deine Installation anpassen.

## 🔌 Verwendete Endpunkte

| Endpunkt | Scope |
|---|---|
| `GET /api/v1/auth/user` | – |
| `GET /api/v1/user/statuses/active` (404 = keine Fahrt) | `read-statuses` |
| `GET /api/v1/dashboard` | `read-statuses` |
| `GET /api/v1/statistics/overview`, `/statistics/history` | `read-statistics` |
| `GET /api/v1/trains/station/autocomplete/{query}`, `/nearby`, `/history` | `write-statuses` |
| `GET /api/v1/station/{id}/departures` | `write-statuses` |
| `GET /api/v1/trains/trip` | `write-statuses` |
| `POST /api/v1/trains/checkin` | `write-statuses` |

## 🩺 Fehlersuche

- **Check-in-Karte meldet „Zugriff abgelehnt“** → Token ohne `write-statuses`; neuen Token anlegen und über *Neu konfigurieren* eintragen.
- **Karte „Custom element doesn't exist“** → Home Assistant nach dem Update neu starten und die Seite neu laden (Browser-Cache).
- **Monat/Jahr leer** → Attribut `api_keys` am Sensor „Check-ins diesen Monat“ zeigt, welche Felder die API liefert.
- **Debug-Logging:**

```yaml
logger:
  logs:
    custom_components.traewelling: debug
```

## 📝 Changelog

- **1.2.0** – 🎫 Check-in-Karte mit Stationssuche, Standort, Live-Abfahrten und Ausstiegswahl · 🛠️ Services `search_stations`, `get_departures`, `get_trip`, `checkin` · 👤 Freunde verlinken auf ihr Profil · 🔑 Token über „Neu konfigurieren“ austauschbar
- **1.1.1** – 🐛 Monat/Jahr-Statistik über `/statistics/overview`
- **1.1.0** – 👥 Sensor „Freunde unterwegs“, Dashboard-Vorlage
- **1.0.0** – 🎉 Erste Version: aktive Fahrt und Statistiken
