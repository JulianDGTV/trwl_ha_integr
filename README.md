# Träwelling für Home Assistant

Custom Integration, die deine aktive Fahrt und deine Reisestatistiken von
[traewelling.de](https://traewelling.de) in Home Assistant bringt.

## Installation

1. Ordner `custom_components/traewelling` nach `<config>/custom_components/traewelling` kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Träwelling**.

Für HACS: Repository als „Custom Repository“ (Kategorie *Integration*) hinzufügen.

## Access Token

Auf traewelling.de unter **Einstellungen → API / Anwendungen** einen persönlichen
Access Token anlegen. Benötigte Scopes:

- `read-statuses` – für die aktive Fahrt
- `read-statistics` – für die Statistik-Endpunkte

Fehlt `read-statistics`, läuft die Integration trotzdem; die Statistik-Sensoren
bleiben dann nur leer (es gibt eine Warnung im Log).

## Entitäten

**Aktive Fahrt** (Abfrage standardmäßig alle 60 s)

| Entität | Beschreibung |
|---|---|
| `binary_sensor.traewelling_check_in_aktiv` | An, sobald eine Fahrt läuft **oder** in Kürze startet – der Sensor für die Lovelace-Karte |
| `binary_sensor.traewelling_unterwegs` | An, nur solange die Fahrt tatsächlich läuft. Alle Fahrtdetails liegen als Attribute an |
| `sensor.traewelling_fahrtstatus` | `unterwegs` / `bevorstehend` / `keine` |
| `sensor.traewelling_abfahrt_in` | Minuten bis zur Abfahrt |
| `sensor.traewelling_nachste_geplante_fahrt` | Zeitstempel des nächsten Check-ins, die nächsten fünf als Attribut |
| `sensor.traewelling_aktuelle_fahrt` | Linienname, z. B. „RE 5“ |
| `sensor.traewelling_start` / `..._ziel` | Start- und Zielhaltestelle |
| `sensor.traewelling_abfahrt` / `..._ankunft` | Zeitstempel (Echtzeit, sonst Plan) |
| `sensor.traewelling_verspatung_abfahrt` / `..._ankunft` | Minuten |
| `sensor.traewelling_restfahrzeit` | Minuten bis Ankunft (nur während der Fahrt) |
| `sensor.traewelling_fahrtfortschritt` | 0–100 % |
| `sensor.traewelling_distanz_aktuelle_fahrt` | km |
| `sensor.traewelling_punkte_aktuelle_fahrt` | Punkte |

**Statistik** (Abfrage standardmäßig alle 30 min – die API cacht serverseitig 1–6 h)

| Entität | Quelle |
|---|---|
| `sensor.traewelling_punkte_gesamt` | Profil |
| `sensor.traewelling_distanz_gesamt` | Profil (km) |
| `sensor.traewelling_reisezeit_gesamt` | Profil (h) |
| `sensor.traewelling_check_ins_gesamt` | `/statistics/overview`, mit längster/kürzester Fahrt als Attribut |
| `sensor.traewelling_aktive_reisetage` | `/statistics/overview` |
| `sensor.traewelling_distanz_je_fahrt` | `/statistics/overview` (Mittelwert) |
| `sensor.traewelling_haufigste_station` / `..._linie` / `..._strecke` | `/statistics/favorites`; Top 10 als Attribut `top10`, dazu `count` und `distance_km` des Spitzenreiters |
| `sensor.traewelling_check_ins_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |
| `sensor.traewelling_distanz_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |

Alle Fahrt-Sensoren zeigen die laufende Fahrt an. Läuft gerade keine, springen
sie auf den nächsten bereits eingecheckten Trip, sofern dieser innerhalb des
Vorschaufensters (Standard: 60 Minuten) startet. Eine laufende Fahrt hat dabei
immer Vorrang: erst wenn sie zu Ende ist, rückt die Anschlussfahrt nach.

Intervalle, Vorschaufenster und der Startzeitpunkt der Statistik lassen sich
über **Konfigurieren** an der Integration anpassen. `0` Minuten schaltet die
Vorschau ganz ab.

## Verwendete Endpunkte

- `GET /api/v1/auth/user`
- `GET /api/v1/user/statuses/active` (404 = gerade keine Fahrt)
- `GET /api/v1/dashboard/future` für geplante Fahrten, mit Fallback auf
  `GET /api/v1/status?user_id=&from=&to=` bzw. `GET /api/v1/user/{username}/statuses`;
  fremde Check-ins aus dem Feed werden über die Nutzer-ID herausgefiltert
- `GET /api/v1/statistics/overview?from=&until=`
- `GET /api/v1/statistics/history`
- `GET /api/v1/statistics/favorites?from=&until=`

Die Feldnamen der Statistik-Endpunkte stammen aus den OpenAPI-Annotationen in
`app/Http/Controllers/API/v1/StatisticsController.php` (PR #4799, Release
2026.06.19) plus der Umbenennung vom 2026-06-21:

- `overview` → `data.summary` mit `total_checkins`, `active_days`,
  `total_distance_km`, `mean_distance_km`, `longest_checkin_by_distance`,
  `shortest_checkin_by_distance`, `longest_checkin_by_duration`,
  `shortest_checkin_by_duration`
- `history` → `data.yearly` / `monthly` / `weekly`, je Eintrag `period`,
  `period_type`, `checkin_count`, `distance_km`
- `favorites` → `data.stations` (`name`, `count`), `data.lines` (`linename`,
  `number`, `count`, `distance_km`) und `data.routes` (`origin`, `destination`,
  `count`, `distance_km`; ohne eigenes Namensfeld – der Sensor setzt
  „Start → Ziel“ selbst zusammen). Verifiziert gegen die Live-API am 2026-09-23.

Zwei Fallstricke: der Zeitraum-Parameter heißt `until`, nicht `to` (ohne
Parameter liefert die API nur die letzten vier Wochen), und `total_distance_km`
bzw. `distance_km` sind bereits Kilometer, während `distance` im Status in
Metern kommt.

Träwelling lehnt Anfragen ohne aussagekräftigen User-Agent mit HTTP 403 ab. Die
Integration schickt `home-assistant-traewelling/…`; beim Testen mit curl also
`-A "dein-name/1.0"` nicht vergessen.

Debug-Logging, falls doch etwas leer bleibt:

```yaml
logger:
  logs:
    custom_components.traewelling: debug
```

## Dashboard-Beispiel

```yaml
type: conditional
conditions:
  - entity: binary_sensor.traewelling_check_in_aktiv
    state: "on"
card:
  type: entities
  title: Fahrt
  entities:
    - entity: sensor.traewelling_fahrtstatus
    - entity: sensor.traewelling_aktuelle_fahrt
    - entity: sensor.traewelling_start
    - entity: sensor.traewelling_ziel
    - entity: sensor.traewelling_abfahrt_in
    - entity: sensor.traewelling_ankunft
    - entity: sensor.traewelling_verspatung_ankunft
    - type: attribute
      entity: binary_sensor.traewelling_check_in_aktiv
      attribute: origin_platform
      name: Gleis ab
    - type: divider
    - type: weblink
      url: /config/integrations/integration/traewelling
      name: Alle Sensordaten
      icon: mdi:database-search
```

Die `weblink`-Zeile führt auf die Integrationsseite; von dort ist es ein Klick
auf das Gerät „Träwelling", wo alle Entitäten mit ihren Rohwerten und Attributen
liegen. Wer direkt auf der Geräteseite landen will, öffnet sie einmal von Hand,
kopiert die ID aus der Adresszeile und trägt sie fest ein:

```yaml
    - type: weblink
      url: /config/devices/device/a1b2c3d4e5f6...
      name: Träwelling-Gerät
      icon: mdi:database-search
```

Als eigenständige Kachel neben der Fahrtkarte geht auch:

```yaml
type: button
name: Träwelling-Sensoren
icon: mdi:database-search
tap_action:
  action: navigate
  navigation_path: /config/integrations/integration/traewelling
```

## Automatisierungs-Beispiel

```yaml
automation:
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
