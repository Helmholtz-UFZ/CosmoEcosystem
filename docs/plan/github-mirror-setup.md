# GitHub-Mirror: Ziel, Umfang, Verifikation (C2)

**Betrifft:** alle drei Repos · **Kanonischer Ort:** dieses Repo, weil die Entscheidung
repo-übergreifend ist und nur **eine** Quelle haben darf.
**Erstellt:** 2026-08-18

---

## 1. Ziel steht fest

Die Suite ist Teil der **UFZ-Organisation** auf GitHub:
`https://github.com/Helmholtz-UFZ` — Team `cosmo-suite` unter MET (Umbenennung in
`cosmo-ecosystem` offen, siehe §6).

| GitLab (Arbeitsort) | GitHub (Publikation) |
|---|---|
| `…/wg7/cosmo-ecosystem` (vormals `cosmo-suite`) | `github.com/Helmholtz-UFZ/**CosmoEcosystem**` (vormals `CosmoSuite`) |
| `…/wg7/cosmopolitan` | `github.com/Helmholtz-UFZ/Cosmopolitan` |
| `…/wg7/cosmonaut` | `github.com/Helmholtz-UFZ/Cosmonaut` |

> ⚠️ **Der Framework-Repo-Name weicht ab.** Das Python-Paket heißt `cosmo-ecosystem`
> (Import `cosmo_ecosystem`), das GitHub-Repo `CosmoEcosystem`. Der Pin lautet deshalb
> `"cosmo-ecosystem @ git+https://github.com/Helmholtz-UFZ/CosmoEcosystem@v0.9.0"` —
> Paketname links, Reponame in der URL. Das funktioniert (`uv` liest den Namen aus der
> geholten `pyproject.toml`), sieht aber nach einem Tippfehler aus. **Nicht „korrigieren".**
> PascalCase auf GitHub wie bei `Cosmonaut` und `Cosmopolitan`.
>
> **Umbenannt (2026-10-20): `CosmoSuite` → `CosmoEcosystem`, ab v0.9.0.** Nach
> Abstimmung mit dem WTT (03.09.2026) ersetzt „Cosmo Ecosystem" den Namen „Cosmo
> Suite" in Manuskript, Repos und Zenodo; das eingereichte SoftwareX-Manuskript nennt
> das Framework so. Abgelöst ist damit die Entscheidung vom 2026-08-19
> („`CosmoSuite` bleibt"). Cosmonaut und Cosmopolitan behalten ihre Namen.
>
> Die beiden Folgen, die vor der Umbenennung hier notiert waren, gelten weiter:
>
> - **Der permanente Anker ist die Zenodo-DOI, nicht die GitHub-URL.** Genau deshalb
>   gehört in C2 die DOI als „permanent link" und die GitHub-URL als Repository. Eine DOI
>   übersteht eine Umbenennung, eine URL nur per Redirect.
> - **Eine Umbenennung bricht den Pin nicht sofort — und das ist das Tückische.** GitHub
>   hält Redirects auch für git-Operationen, der Pin funktioniert also weiter, bis jemand
>   ein neues Repo unter dem alten Namen anlegt. Der Bruch kommt still und spät. Wird
>   umbenannt, ist derselbe Tag die Gelegenheit, in beiden Apps neu zu pinnen
>   (`pyproject.toml` + `uv lock` + ein CI-Lauf).

Damit ist auch die C2-Anforderung „permanent" besser gedeckt als mit einem persönlichen
Repo: die URL hängt an der Institution, nicht an einer Person, und übersteht
Maintainer-Wechsel ohne Umzug.

**Kostenfrage erledigt:** GitHub-Actions-Minuten und Packages-Storage sind für
**öffentliche** Repos unbegrenzt; die 2000-Minuten-/500-MB-Grenzen gelten für private.
Und keines der drei Repos hat ein `.github/workflows/` — die CI bleibt vollständig auf
GitLab, auf GitHub läuft nichts.

---

## 2. Umfang: `main` + Tags, keine Feature-Branches

**Tags sind zwingend, nicht optional** — an drei Stellen:

1. Der Dependency-Pin nennt einen Tag (`@v0.9.0`). Ohne gespiegelte Tags schlägt
   `git+https://github.com/Helmholtz-UFZ/CosmoEcosystem@v0.9.0` fehl, und damit ist der
   Zweck der ganzen Umstellung verfehlt.
2. C1 der Metadaten-Tabelle nennt Versionen — ein Reviewer will den Stand auschecken,
   den das Paper beschreibt.
3. **Zenodo archiviert GitHub-*Releases*, und Releases setzen auf Tags auf.** Ohne Tags
   kein DOI, also kein „permanent link" für C2.

**Feature-Branches nicht spiegeln.** In GitLab *„Mirror only protected branches"*
aktivieren und `main` protected halten. Begründung: `universalization` trägt die bewusst
verworfene Arbeit, `egress-test` war ein Wegwerf-Branch, `cosmo-suite-integration` ist
abgeschlossene Historie. Zwölf halbfertige Branches lesen sich als unfertiges Projekt —
und jeder nicht gespiegelte Branch ist eine Fläche weniger, die niemand auf Interna
geprüft hat.

---

## 3. Zwei Dinge, die der Mirror **nicht** von allein tut

**Ein gespiegelter Tag erzeugt keinen Release.** Zenodo hängt am Release, nicht am Tag.
Nach dem ersten Sync in der GitHub-UI (oder per API) einen Release auf `v0.4.0` bzw. dem
App-Tag anlegen — sonst archiviert Zenodo nichts und C2 bleibt ohne DOI.

**Der Push-Mirror überschreibt — und löscht auch.** Er drückt den GitLab-Stand über den
GitHub-Stand. Niemals direkt auf GitHub committen oder mergen: das ist beim nächsten Sync
weg. GitHub ist Leseseite, GitLab die Wahrheit. Issues und Discussions sind davon nicht
betroffen — nur Git-Inhalte.

**Gemessen am 2026-08-18:** Der Mirror synchronisiert **Löschungen mit**. Ein
versehentlich gepushter Tag wurde in GitLab entfernt und war danach auch auf GitHub weg,
ohne Zutun. Eine Tag-Korrektur macht man also in GitLab, GitHub folgt nach. (Eine frühere
Fassung dieses Dokuments behauptete das Gegenteil — das war eine Annahme, keine Messung.)

---

## 4. Verifikation nach dem ersten Sync

```bash
# 1. Kamen die Tags mit? Das ist der Punkt, der den Pin bricht.
git ls-remote --tags https://github.com/Helmholtz-UFZ/CosmoEcosystem | grep v0.9.0

# 2. Kamen NUR die gewollten Branches mit?
git ls-remote --heads https://github.com/Helmholtz-UFZ/CosmoEcosystem

# 3. Der Ernstfall: löst der Pin für einen Außenstehenden auf?
uv pip install --system --dry-run \
  "cosmo-ecosystem @ git+https://github.com/Helmholtz-UFZ/CosmoEcosystem@v0.9.0"
```

Punkt 1 ist der wichtigste: ob *„only protected branches"* die Tags mitnimmt, ist der
Doku nicht sicher zu entnehmen. Zwei Sekunden Prüfung, und ohne sie bricht der Pin.

---

## 5. Bekanntes, das mit der Historie öffentlich wird

**Commit-Autorschaft:** In `cosmo-ecosystem` (damals `cosmo-suite`) sind 12 Commits als
`LFT-W47 <louis.trinkle@gmail.com>` attribuiert — eine private Adresse, die mit der
Historie öffentlich wird. Nicht kritisch, aber vor dem Mirror bewusst entscheiden:
hinnehmen, oder für künftige Commits `git config user.email` auf die UFZ-Adresse setzen.
Nachträglich ändern hieße Historie umschreiben — dafür ist es zu geringfügig.

**Dienstkonto + Relay in `env_prod`: bewusst drin gelassen.** Beide Apps tragen
`EMAIL_USERNAME="soncosmo"` und `EMAIL_SERVER="smtp.ufz.de"` in der getrackten
`env_prod`. **Entscheidung Louis (2026-08-19): unkritisch, bleibt.** Begründung: ein
Kontoname ohne Passwort ist kein Zugang, und in `env_prod` steht keine
`EMAIL_PASSWORD`-Zeile. Hier vermerkt, damit die Frage nicht bei jedem Durchgang neu
gestellt wird.

**Keine Secrets.** In allen Repos geprüft: die getrackten env-Dateien enthalten
Platzhalter oder leere Werte, kein Passwort in `env_prod`. Deshalb voller
Historien-Mirror, kein Rewrite. Der einzige offene Einzelfall ist in cosmonauts
Plan als Gate festgehalten.

---

## 6. Status

| Schritt | Stand |
|---|---|
| Org + Team | ✅ `Helmholtz-UFZ`, Team `cosmo-suite` unter MET · ⬜ Team → `cosmo-ecosystem` |
| Egress GitLab-Runner → github.com | ✅ beide Runner-Pools inkl. dind-Imagebuild |
| Lizenz/Copyright symmetrisch | ✅ cosmo-ecosystem, ✅ cosmopolitan, ⬜ cosmonaut |
| Repos auf GitHub anlegen | ✅ public, leer, Team = Admin |
| Push-Mirror je Repo | ✅ per SSH-Deploy-Key, Tags kommen mit |
| Pin auf GitHub-URL (beide Apps) | ⬜ Phase B |
| Release-Tags mit Zitations-Metadaten | ✅ `v0.4.1` / `0.2.4` / `0.3.5` |
| Release + Zenodo-DOI | ✅ Framework: Concept-DOI `10.5281/zenodo.21996475`, Apps: siehe deren `CITATION.cff` |
| Rename → Cosmo Ecosystem | ⬜ Framework v0.9.0 · ⬜ GitLab-Pfad · ⬜ GitHub-Repo + Mirror-URL · ⬜ beide Apps neu gepinnt |
