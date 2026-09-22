# Träwelling für Home Assistant

Custom Integration, die deine aktive Fahrt, die laufenden Fahrten deiner
Freunde und deine Reisestatistiken von [traewelling.de](https://traewelling.de)
in Home Assistant bringt.

**Neu in 1.1.0:** Sensor „Freunde unterwegs“ mit allen gerade laufenden Fahrten
der Accounts, denen du folgst – plus fertige Dashboard-Ansicht mit
Fortschrittsbalken (siehe unten).

## Installation

1. Ordner `custom_components/traewelling` nach `<config>/custom_components/traewelling` kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Träwelling**.

Für HACS: Repository als „Custom Repository“ (Kategorie *Integration*) hinzufügen.

## Access Token

Auf traewelling.de unter **Einstellungen → API / Anwendungen** einen persönlichen
Access Token anlegen. Benötigte Scopes:

- `read-statuses` – für die aktive Fahrt und die Fahrten deiner Freunde
- `read-statistics` – für die Statistik-Endpunkte

Fehlt `read-statistics`, läuft die Integration trotzdem; die Statistik-Sensoren
bleiben dann nur leer (es gibt eine Warnung im Log).

## Entitäten

**Aktive Fahrt** (Abfrage standardmäßig alle 60 s)

| Entität | Beschreibung |
|---|---|
| `binary_sensor.traewelling_unterwegs` | An, solange ein Check-in aktiv ist. Alle Fahrtdetails liegen als Attribute an |
| `sensor.traewelling_aktuelle_fahrt` | Linienname, z. B. „RE 5“ |
| `sensor.traewelling_start` / `..._ziel` | Start- und Zielhaltestelle |
| `sensor.traewelling_abfahrt` / `..._ankunft` | Zeitstempel (Echtzeit, sonst Plan) |
| `sensor.traewelling_verspatung_abfahrt` / `..._ankunft` | Minuten |
| `sensor.traewelling_restfahrzeit` | Minuten bis Ankunft |
| `sensor.traewelling_fahrtfortschritt` | 0–100 % |
| `sensor.traewelling_distanz_aktuelle_fahrt` | km |
| `sensor.traewelling_punkte_aktuelle_fahrt` | Punkte |

> Hinweis: Die tatsächlichen Entity-IDs enthalten je nach HA-Version den
> Gerätenamen, z. B. `sensor.trawelling_deinname_punkte_gesamt`. Die
> Dashboard-Vorlage unten findet die Entitäten automatisch.

**Freunde unterwegs** (Abfrage zusammen mit der aktiven Fahrt)

| Entität | Beschreibung |
|---|---|
| `sensor.traewelling_freunde_unterwegs` | Anzahl der Freunde, die gerade fahren |

„Freunde“ sind alle Accounts, denen du auf Träwelling folgst (Quelle:
`/dashboard`, also inkl. privater Profile, die dich zugelassen haben). Pro
Person wird nur die aktuell laufende Fahrt berücksichtigt. Das Attribut
`trips` ist eine Liste, nach Ankunft sortiert, mit diesen Feldern pro Fahrt:

| Feld | Inhalt |
|---|---|
| `name`, `username`, `avatar` | Anzeigename, Benutzername, Profilbild |
| `line`, `category` | Linie (z. B. „ICE 598“) und Verkehrsmittel |
| `origin`, `destination` | Start- und Zielhaltestelle |
| `departure`, `arrival` | Abfahrt/Ankunft (Echtzeit, sonst Plan, ISO-8601) |
| `departure_planned`, `arrival_planned` | Planzeiten |
| `delay_arrival` | Verspätung bei Ankunft in Minuten |
| `progress`, `minutes_left` | Fortschritt in % und Restzeit (Stand letzte Abfrage) |
| `distance_km`, `body`, `url` | Distanz, Status-Text, Link zum Status |

Zusätzlich enthält das Attribut `names` nur die Namen – praktisch für
Benachrichtigungen.

**Statistik** (Abfrage standardmäßig alle 30 min – die API cacht serverseitig 1–6 h)

| Entität | Quelle |
|---|---|
| `sensor.traewelling_punkte_gesamt` | Profil |
| `sensor.traewelling_distanz_gesamt` | Profil (km) |
| `sensor.traewelling_reisezeit_gesamt` | Profil (h) |
| `sensor.traewelling_check_ins_gesamt` | `/statistics/overview`, mit längster/kürzester Fahrt als Attribut |
| `sensor.traewelling_aktive_reisetage` | `/statistics/overview` |
| `sensor.traewelling_check_ins_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |
| `sensor.traewelling_distanz_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |

Intervalle und der Startzeitpunkt der Statistik lassen sich über
**Konfigurieren** an der Integration anpassen.

## Verwendete Endpunkte

- `GET /api/v1/auth/user`
- `GET /api/v1/user/statuses/active` (404 = gerade keine Fahrt)
- `GET /api/v1/dashboard?page=1..2` (Status der Accounts, denen du folgst)
- `GET /api/v1/statistics/overview?from=&to=`
- `GET /api/v1/statistics/history`

Feldnamen werden defensiv gelesen (mehrere Kandidaten pro Wert), weil Träwelling
Felder gelegentlich umbenennt – siehe `API_CHANGELOG.md` im Projekt-Repo.
Bleibt ein Statistik-Sensor leer, hilft ein Blick in die Rohdaten:

```bash
curl -H "Authorization: Bearer DEIN_TOKEN" \
     "https://traewelling.de/api/v1/statistics/overview?from=2019-01-01&to=2026-12-31" | jq
```

Die passenden Keys lassen sich dann in `helpers.py` / `sensor.py` ergänzen.
Debug-Logging:

```yaml
logger:
  logs:
    custom_components.traewelling: debug
```

## Dashboard

Fertige Ansicht mit drei Bereichen: **Meine Fahrt**, **Freunde unterwegs**
(je Freund Name, Linie, Start → Ziel, Abfahrt → Ankunft, Fortschrittsbalken
und Restzeit) und **Statistik** (Monat / Jahr / gesamt). Kommt ohne
Zusatzkarten aus und findet die Träwelling-Entitäten automatisch.

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
      - type: markdown
        grid_options:
          columns: full
        content: |-
          {% set e = integration_entities('traewelling') %}
          {% set b = e | select('match', 'binary_sensor\.') | first | default(none) %}
          {% if b and is_state(b, 'on') %}
          {% set dep = as_datetime(state_attr(b, 'departure_real') or state_attr(b, 'departure_planned')) %}
          {% set arr = as_datetime(state_attr(b, 'arrival_real') or state_attr(b, 'arrival_planned')) %}
          {% set p = ((now() - dep).total_seconds() / ((arr - dep).total_seconds() or 1) * 100) | round(0) | int %}
          {% set p = [0, [100, p] | min] | max %}
          {% set n = (p / 5) | round(0) | int %}
          {% set left = [0, ((arr - now()).total_seconds() / 60) | int] | max %}

          ### 🚆 {{ state_attr(b, 'line') or 'Fahrt' }}

          **{{ state_attr(b, 'origin') }}** → **{{ state_attr(b, 'destination') }}**

          🕐 {{ as_local(dep).strftime('%H:%M') }} → {{ as_local(arr).strftime('%H:%M') }}{% if state_attr(b, 'destination_platform') %} · Gleis {{ state_attr(b, 'destination_platform') }}{% endif %}

          `{{ '█' * n }}{{ '░' * (20 - n) }}` **{{ p }} %** · noch {{ left }} min
          {% else %}
          🏠 Gerade nicht unterwegs.
          {% endif %}

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

          ### 👤 {{ t.name }}{% if t.line %} · {{ t.line }}{% endif %}

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

## Automatisierungs-Beispiele

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

## Changelog

- **1.1.0** – Neuer Sensor „Freunde unterwegs“ (laufende Fahrten gefolgter
  Accounts via `/dashboard`), Dashboard-Vorlage mit Fortschrittsbalken.
- **1.0.0** – Erste Version: aktive Fahrt und Statistiken.
