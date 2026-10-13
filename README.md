# APIZIT Flask Logs API

Une API publique de référence pour tester les journaux d'APIZIT : un appel génère
des logs synthétiques, faciles à retrouver par marqueur et identifiant d'appel.
Elle reprend la structure de `apizit-flask-light-api`, sans service externe ni
dépendance au code APIZIT. Elle est destinée aux tests, pas à un usage de production.

## Premier test dans APIZIT

1. Importe ce dépôt GitHub dans ton espace TEST, puis lance l'API avec `/health`
   comme route de santé. Sélectionne le commit exact de `main` pour un test reproductible.
2. Appelle `GET /logs/sample` sur l'URL de ton API : cela produit **25 logs**,
   cinq de chaque niveau `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
3. Ouvre les journaux de l'API dans APIZIT et recherche le `request_id` retourné.
   Tu peux aussi rechercher un marqueur comme `pagination-01`.

Exemple PowerShell après le lancement :

```powershell
$base = "https://URL-DE-TON-API"
$headers = @{ "x-api-key" = "TA-CLE-D-APPEL" }
Invoke-RestMethod -Uri "$base/logs/sample?marker=sample-01" -Headers $headers

$body = @{
    count = 1000
    level = "mixed"
    format = "json"
    marker = "pagination-01"
    message_chars = 128
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/logs/burst" -Headers $headers `
    -ContentType "application/json" -Body $body
```

Ce second appel produit **1 000 logs**, plus les deux logs de début et fin d'appel.
Pour tester uniquement les avertissements, remplace `level` par `WARNING`.
Pour tester le texte brut, remplace `format` par `text`.
Garde ta clé d'appel privée et ne la mets pas dans le dépôt.

## Scénarios de logs

| Méthode | Route | Résultat |
| --- | --- | --- |
| `GET` | `/logs/sample?marker=sample-01` | 25 événements, tous les niveaux |
| `POST` | `/logs/burst` | 1 à 1 000 événements, volume et niveau configurables |
| `GET` | `/logs/exception?marker=failure-01` | Une trace Python synthétique et HTTP **500 volontaire** |
| `GET` | `/logs/multiline?format=text` | Multiligne, accents, emoji et écritures non latines |
| `POST` | `/logs/timeline` | Événements espacés dans le temps, jusqu'à 5 secondes d'attente cumulée |

Les routes GET acceptent `marker` et `format=json|text`.

Options JSON de `/logs/burst` :

| Option | Valeur par défaut | Valeurs acceptées |
| --- | --- | --- |
| `count` | `100` | Entier de 1 à 1 000 |
| `level` | `mixed` | `mixed`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `format` | `json` | `json`, `text` |
| `marker` | `logs-test` | 1 à 64 caractères ASCII : lettres, chiffres, `.`, `_`, `-`; commence par lettre/chiffre |
| `message_chars` | `0` | 0 à 512 caractères synthétiques supplémentaires par événement |

Options JSON de `/logs/timeline` : `count` (1–50, défaut 10), `interval_ms`
(0–5 000, défaut 100), `marker`, `format`. Le produit `(count - 1) * interval_ms`
doit rester inférieur ou égal à 5 000 ms. Exemple :

```json
{"count": 10, "interval_ms": 250, "marker": "timeline-01", "format": "json"}
```

La réponse donne `generated_logs`, `level_counts`, `marker` et `request_id`.
`generated_logs` compte les événements du scénario, hors début/fin de requête.
L'en-tête `X-Log-Request-Id` est présent sur chaque réponse. Les numéros `sequence`
vont de 1 au nombre d'événements; les logs de début/fin portent 0.

Les logs JSON occupent une ligne physique par événement; les retours à la ligne
d'une trace ou d'un message sont échappés dans `message`. Le format texte les
écrit sur plusieurs lignes, pour tester l'affichage réel des traces.
Chaque message contient aussi le marqueur et l'identifiant, car un lecteur de
logs peut afficher uniquement le champ JSON `message`.

APIZIT regroupe actuellement `DEBUG`/`INFO` dans le filtre Info,
`WARNING` dans Warning, et `ERROR`/`CRITICAL` dans Error. Un log Error synthétique
ne signifie pas forcément un appel HTTP en échec : `/logs/burst` répond 200.
Seule `/logs/exception` provoque volontairement un 500; `/health` reste saine ensuite.

## Routes de référence conservées

| Méthode | Route | Résultat |
| --- | --- | --- |
| `GET` | `/health` | `200 {"status":"ok"}`, immédiat |
| `GET` | `/info` | Framework, profil `logs` et limites du générateur |
| `POST` | `/echo` | `{"message":"hello","count":2}` retourné sous `received` |
| `GET` | `/items/7?include_details=true` | Paramètres de chemin et de requête |
| `GET` | `/slow` | Attend exactement **80 secondes**, puis répond 200 |

`/slow` conserve la sonde de durée de la référence légère. Ne l'utilise jamais
comme route de santé. Cette API de logs possède son propre contrat de dix routes;
elle ne modifie pas la matrice Light/Heavy existante.

## Lancer localement

Python 3.12 est requis.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -X utf8 -m flask --app app run
```

L'API est disponible à `http://127.0.0.1:5000` sans clé d'appel locale.

```powershell
Invoke-RestMethod "http://127.0.0.1:5000/logs/sample?marker=local-01"
Invoke-RestMethod -Method Post "http://127.0.0.1:5000/logs/burst" `
    -ContentType "application/json" -Body '{"count":1000,"marker":"local-burst"}'
```

Les événements sont écrits immédiatement sur stdout avec vidage du flux.
Un logger indépendant conserve DEBUG et évite les doublons des handlers du runtime.
L'API n'écrit aucun fichier, ne lance aucune tâche de fond et ne fait aucun appel externe.
Les logs ne contiennent ni corps de requête, ni paramètres de requête bruts,
ni en-têtes d'authentification. Les marqueurs sont validés pour empêcher les
retours à la ligne injectés. Utilise uniquement des marqueurs de test.

Chaque corps de requête est limité à 8 Kio. Un burst maximal produit moins de
1 Mio de sortie; cette borne concerne un appel, pas plusieurs appels simultanés.
Les coûts de logs et d'appels de l'API hébergée restent ceux de ton environnement.
Commence par `/logs/sample`, puis augmente le volume au besoin.
La disponibilité et le délai d'apparition dans APIZIT doivent être observés après
lancement : la publication du dépôt seule ne prouve pas une qualification hébergée.

## Vérifier

```powershell
ruff check .
ruff format --check .
pytest -q
python -c "from app import app; assert app is not None"
```

La CI vérifie le contrat des routes, les niveaux et volumes réellement écrits,
les limites, les traces, l'Unicode, la corrélation entre appels concurrents et
l'absence de données de requête dans les logs. Les tests remplacent les attentes
de `/slow` et `/logs/timeline`; ils ne dorment pas 80 secondes.
