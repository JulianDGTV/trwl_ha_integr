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
| `binary_sensor.traewelling_unterwegs` | An, solange ein Check-in aktiv ist. Alle Fahrtdetails liegen als Attribute an |
| `sensor.traewelling_aktuelle_fahrt` | Linienname, z. B. „RE 5“ |
| `sensor.traewelling_start` / `..._ziel` | Start- und Zielhaltestelle |
| `sensor.traewelling_abfahrt` / `..._ankunft` | Zeitstempel (Echtzeit, sonst Plan) |
| `sensor.traewelling_verspatung_abfahrt` / `..._ankunft` | Minuten |
| `sensor.traewelling_restfahrzeit` | Minuten bis Ankunft |
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
| `sensor.traewelling_check_ins_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |
| `sensor.traewelling_distanz_diesen_monat` / `..._dieses_jahr` | `/statistics/history` |

Intervalle und der Startzeitpunkt der Statistik lassen sich über
**Konfigurieren** an der Integration anpassen.

## Verwendete Endpunkte

- `GET /api/v1/auth/user`
- `GET /api/v1/user/statuses/active` (404 = gerade keine Fahrt)
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

## Dashboard-Beispiel

```yaml
type: conditional
conditions:
  - entity: binary_sensor.traewelling_unterwegs
    state: "on"
card:
  type: entities
  title: Aktuelle Fahrt
  entities:
    - entity: sensor.traewelling_aktuelle_fahrt
    - entity: sensor.traewelling_ziel
    - entity: sensor.traewelling_ankunft
    - entity: sensor.traewelling_verspatung_ankunft
    - type: attribute
      entity: binary_sensor.traewelling_unterwegs
      attribute: destination_platform
      name: Gleis
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
