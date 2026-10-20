# Lokale Port-Zuteilung über die drei Repos

**Betrifft:** `cosmo-ecosystem/examples/csv_profiler`, `cosmopolitan`, `ufz-cosmonaut`
**Erstellt:** 2026-08-11 · **Kanonischer Ort:** dieses Repo (die Zuteilung ist
repo-übergreifend und darf nur **eine** Quelle haben)

> **Nachtrag 2026-09-16:** MinIO ist durch RustFS ersetzt. Der Dienst heißt jetzt in allen
> drei Repos `object-storage`, die Host-Port-Variablen `OBJECT_STORAGE_HOST_PORT` /
> `OBJECT_STORAGE_CONSOLE_HOST_PORT` (vorher `MINIO_HOST_PORT` bzw. in cosmonaut
> `OBJECT_STORAGE_PORT`). §0–§2 geben den damals gemessenen Stand wieder. Siehe
> [`object_storage.md`](../conventions/object_storage.md).
>
> **Nachtrag 2026-09-17:** §3 ist jetzt in allen drei Repos umgesetzt — auch
> cosmopolitan (Flask, Postgres, Redis, Tileserver) und cosmonaut (Postgres, Redis)
> lesen `${…_HOST_PORT:-<Default>}`. Nachgewiesen per `docker compose config`: für jede
> env-Datei dieselben aufgelösten Mappings wie vorher. In cosmonaut (`network_mode:
> host`) müssen `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` gleich `POSTGRES_PORT` /
> `REDIS_PORT` sein.

---

## 0. Problem

Alle drei Stacks veröffentlichen dieselben Ports auf dem Host. Konkret gemessen:

| Kollision | betroffen |
|---|---|
| Dash **8080** | alle drei |
| Postgres **5432**, Redis **6379**, MinIO **9000/9001** | cosmopolitan ↔ csv_profiler |
| Tileserver **8001** | cosmopolitan ↔ cosmonaut |

Folge: **keine zwei Suiten gleichzeitig, in keiner Kombination.** Das hat bisher jeden
Agenten zwei abgebrochene Läufe gekostet. Eine Kollision sieht dabei **nicht** wie ein
Failure aus, sondern wie Setup-ERRORs bzw. wie e2e-Tests ohne Server — also wie ein
inhaltlicher Fehler an ganz anderer Stelle.

**Reines Entwickler-/Test-Problem.** In CI läuft jeder Stack in eigenen Containern, in
Produktion auf Kubernetes — dort kollidiert nichts.

**Harte Randbedingung:** Was live geht, wird **nicht** angefasst. `env_prod`,
`env_ci`, `env_dev_prod*`, `env_dev_stage_priv` und alle k8s-Manifeste bleiben, wie sie
sind.

---

## 1. Warum env-Dateien allein nicht reichen

Etwa die Hälfte der `ports:`-Mappings sind **feste Literale**, die die Variablen
ignorieren. Gemessener Stand:

| Repo | interpoliert ✓ | hartcodiert ✗ |
|---|---|---|
| cosmonaut | `${POSTGRES_PORT}:5432`, `${REDIS_PORT}:6379`, `${OBJECT_STORAGE_PORT}:9000`, `${OBJECT_STORAGE_CONSOLE_PORT}:9001` | `8001:80` (tileserver) |
| cosmopolitan | `${FLASK_PORT}:${FLASK_PORT}`, `${POSTGRES_PORT}:${POSTGRES_PORT}` | `6379:6379`, `9000:9000`, `9001:9001`, `8001:80` |
| csv_profiler | `${FLASK_PORT}:${FLASK_PORT}`, `${POSTGRES_PORT}:${POSTGRES_PORT}` | `6379:6379`, `9000:9000`, `9001:9001` |

Ändert man nur die env-Dateien, entsteht eine **Teillösung**: der Flask-Port wandert,
Redis und MinIO kollidieren weiter — und der Fehler sieht nach etwas anderem aus. Genau
die Sorte halbe Reparatur, die teurer ist als keine.

---

## 2. Der Fallstrick, der die naive Variante bricht

cosmopolitan und csv_profiler mappen **auf beiden Seiten dieselbe Variable**:

```yaml
postgres: ports: ["${POSTGRES_PORT}:${POSTGRES_PORT}"]
```

`POSTGRES_PORT=5434` würde also verlangen, dass der Container *intern* auf 5434 lauscht —
das tut das Postgres-Image nicht von selbst. Und die App verbindet sich im Compose-Netz
über `POSTGRES_HOST_NAME:POSTGRES_PORT`, bekäme also ebenfalls den falschen Port.

cosmonaut macht es richtig: `${POSTGRES_PORT}:5432` — Host variabel, Container fest.

**Konsequenz: die vorhandenen Variablen nicht überladen.** `POSTGRES_PORT`,
`REDIS_PORT`, `OBJECT_STORAGE_PORT` beschreiben, *wohin die App sich verbindet*. Was auf
dem Laptop veröffentlicht wird, ist eine andere Frage und braucht eigene Variablen.

---

## 3. Lösung: Host-Port-Variablen mit Default

Jedes host-veröffentlichte Mapping bekommt eine eigene Variable, deren **Default der
heutige Wert ist**:

```yaml
webserver:  ports: ["${FLASK_HOST_PORT:-8080}:${FLASK_PORT}"]
postgres:   ports: ["${POSTGRES_HOST_PORT:-5432}:5432"]
redis:      ports: ["${REDIS_HOST_PORT:-6379}:6379"]
object-storage: ports: ["${OBJECT_STORAGE_HOST_PORT:-9000}:9000",
                        "${OBJECT_STORAGE_CONSOLE_HOST_PORT:-9001}:9001"]
tileserver: ports: ["${TILESERVER_HOST_PORT:-8001}:80"]
```

Der `:-default`-Teil ist der Kern: **solange keine Datei die Variable setzt, ist das
Verhalten bitidentisch zu heute.** Prod, CI und k8s sehen null Änderung, ohne dass dort
eine Zeile angefasst wird. Die internen Ports bleiben fest — die App verbindet sich
weiter über `postgres:5432`, unabhängig davon, was auf dem Host liegt.

`FLASK_PORT` behält seine Doppelrolle (Container-Port **und** der Port, an den der
Dash-Testserver bindet). Deshalb steht rechts `${FLASK_PORT}` und links die neue
Host-Variable: im Container-Betrieb kann man beide gleich setzen, beim `pytest`-Lauf
außerhalb von Docker zählt nur `FLASK_PORT`.

---

## 4. Zuteilung

| | Flask | Postgres | Redis | Object Storage | Console | Tileserver |
|---|---|---|---|---|---|---|
| **cosmopolitan** | 8080 | 5432 | 6379 | 9000 | 9001 | 8001 |
| **cosmonaut** | 8081 | 5433 | 6380 | 9010 | 9011 | 8011 |
| **csv_profiler** | 8082 | 5434 | 6381 | 9020 | 9021 | — |

**cosmopolitan behält die heutigen Werte.** Dort muss deshalb *keine* env-Datei
angefasst werden — nur die vier Literale parametrisiert. Das hält den Diff dort minimal
und die Referenz stabil.

**cosmonaut hat in `env_test_local` bereits 5433 / 6380 / 9010 / 9011** — dort fehlen nur
`FLASK_PORT`/`FLASK_HOST_PORT=8081` und `TILESERVER_HOST_PORT=8011`.

---

## 5. Welche Dateien angefasst werden

**Nur lokale Entwicklungs- und Testdateien:**

| Repo | anfassen | **nicht** anfassen |
|---|---|---|
| cosmopolitan | `docker-compose.yml` (4 Literale), `env_test_local`, `env_dev_mock` | `env_prod`, `env_dev_prod`, `env_dev_prod_priv`, `env_dev_stage_priv`, `env_test`, `docker-compose.prod.yml`, k8s |
| cosmonaut | `docker-compose.yml` (1 Literal), `env_test_local`, `env_dev_mock` | `env_prod`, `env_dev_prod`, `env_dev_prod_priv`, `env_test`, k8s |
| csv_profiler | `docker-compose.yml` (3 Literale), die Datei, die `run_pytest.sh` lokal kopiert | `env_ci` |

**`env_test` vs. `env_test_local` zuerst klären:** In beiden Apps existieren beide. Vor
dem Editieren nachsehen, welche `run_pytest.sh` lokal kopiert und welche CI verwendet —
nur die lokale anfassen. In cosmonaut ist `env_test_local` erkennbar die lokale (sie
trägt schon die abweichenden Service-Ports).

---

## 6. Was das billig macht

**Kein einziger Test und kein Skript hat einen hartcodierten Port.** Verifiziert über
`test/`, `run_pytest.sh` und `dev_up.sh` in allen drei Repos: null Treffer. (Die
`8080`-Treffer in cosmonauts `test/fixtures/` sind OSM-Node-IDs und Koordinaten, keine
Ports.) Die Suiten lesen den Port aus der Config.

Aufwand daher **~1 Stunde pro Repo**, ein eigenständiger Commit, ohne Bezug zur
Framework-Arbeit.

---

## 7. Reihenfolge und Verifikation

Pro Repo, unabhängig voneinander — die drei können parallel laufen:

1. Literale in `docker-compose.yml` auf `${…_HOST_PORT:-<heutiger Wert>}` umstellen.
2. `docker compose config` — zeigt die aufgelösten Mappings; **ohne gesetzte Variablen
   muss die Ausgabe identisch zu vorher sein.** Das ist der Beweis für „prod unberührt".
3. Die lokalen env-Dateien auf den Block aus §4 setzen.
4. `./run_pytest.sh` — grün, und in der Ausgabe den neuen Port sehen.
5. Stack hochfahren, App im Browser auf dem neuen Port öffnen.

**Der eigentliche Abnahmetest, und der geht nur zu zweit:** zwei Suiten **gleichzeitig**
starten. Vorher unmöglich, nachher der Normalfall. Wenn das nicht läuft, ist die Änderung
nicht fertig.

---

## 8. Danach festhalten

Die Zuteilungstabelle aus §4 gehört zusätzlich in die
`docs/conventions/framework_integration.md` beider Apps (kurz, mit Verweis hierher als
kanonische Quelle) — sonst erfindet der nächste Agent eine eigene Zuteilung und die
Kollision kommt zurück, nur schwerer zu finden.

Ebenfalls dorthin, weil es zwei Läufe gekostet hat: **eine Portkollision sieht wie
Setup-ERRORs oder wie serverlose e2e-Tests aus, nicht wie ein Failure.** Wer das nicht
weiß, sucht den Fehler im Code.
