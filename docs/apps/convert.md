# Atelier Convert dans les workflows

Atelier Convert (relevés bancaires PDF, CSV, Excel, OFX, QIF → tables typées) est un **nœud** de la
suite (contrat `atelier-node/1`, [`noeuds.md`](noeuds.md)), comme Viz, Projets, Tab, Wiki et
Formulaire : ses actions sont des étapes de workflow v2, ses événements lancent des déclencheurs, il
figure sur la carte de la suite.

Pour les **agents**, le connecteur de Convert est dans l'extension Agent_DatAnalyst (Data Analyst,
outils `convert_*`) : même adresse, même variable.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `CONVERT_BASE_URL` | `http://127.0.0.1:8010/api` | API d'Atelier Convert (app de bureau ou `uvicorn main:app --port 8010`) ; vide = nœud absent. Réglable dans la roue dentée → Applications Atelier |

Adresse de bouclage seulement (garde du client de nœud) ; aucun proxy.

## Actions (manifeste `GET /api/atelier/manifest`, lu dans le dépôt de Convert)

| Étape | Type | Route | Ce qu'elle fait |
|---|---|---|---|
| `node:convert/conversions.list` | lecture | GET /api/conversions | Historique : fichier, ce qui a été reconnu, lignes, envois vers Tab |
| `node:convert/conversions.table` | lecture | GET /api/atelier/conversions/{conversion_id}/table | Lignes d'une conversion (`atelier-table/1`, par pages de 5 000 au plus) |
| `node:convert/tab.projects` | lecture | GET /api/tab | Projets d'Atelier Tab où envoyer une conversion |
| `node:convert/conversions.send_to_tab` | écriture | POST /api/atelier/conversions/{conversion_id}/send-to-tab | Crée une **nouvelle** table dans un projet de Tab |
| `node:convert/conversions.convert_file` | écriture | POST /api/atelier/conversions | Convertit un fichier transmis en base64 |
| `node:convert/conversions.delete` | suppression | DELETE /api/conversions/{conversion_id} | Supprime une conversion de l'historique (les tables de Tab restent) |

Comme pour toute application : en `APPROVAL_MODE=every_step` (défaut) chaque étape attend
« Autoriser » ; une écriture ou une suppression attend **toujours** la validation de son entrée
résolue, puis part avec une clé d'idempotence `nexus:<exécution>:<étape>` (rejouer une étape validée
ne crée pas de deuxième table).

## Événements (déclencheurs)

| Type | `subject.kind` | `data` |
|---|---|---|
| `convert.conversion.created` | `conversion` | `name`, `format`, `rows`, `columns`, `statement` (relevé reconnu), `ocr`, `origin` |
| `convert.conversion.updated` | `conversion` | `rows`, `columns`, `reason` (`options`, `columns`, `cells`, `ai`, `rename`) |
| `convert.conversion.sent_to_tab` | `conversion` | `table_id`, `table_name`, `project_id`, `rows` |
| `convert.conversion.deleted` | `conversion` | — |

Les événements ne contiennent jamais une ligne, un chemin ni le texte d'un fichier (règle de Convert).

## Exemple : un nouveau relevé part dans Atelier Tab

1. Workflow v2 : une étape `node:convert/conversions.send_to_tab`, entrée
   `{"conversion_id": "{{params.conversion}}", "project_id": "proj_…", "table_name": "Relevé {{params.nom}}"}`.
2. Déclencheur « événement » sur Convert, type `convert.conversion.created`, filtre
   `data.statement = true`, paramètres `{"conversion": "{{event.subject.id}}", "nom": "{{event.subject.label}}"}`.
3. Chaque relevé converti lance une exécution qui **attend** « Autoriser » dans la boîte « À valider »
   avec la table qui sera créée ; rien n'est écrit sans vous.

Le projet de Tab se choisit avec `node:convert/tab.projects` (ou dans Tab : identifiant `proj_…`).

## Confidentialité

Un relevé bancaire est une donnée financière. Un workflow n'appelle aucun modèle : les lignes lues
restent sur la machine (base de Nexus, exécution du workflow). Mais une étape suivante peut les
recopier ailleurs : envoyées dans **Atelier Viz**, elles deviennent lisibles par le Data Analyst, qui
peut tourner sur Claude. Pour un relevé, préférer Atelier Tab ou Atelier Trésorerie, et l'analyse par
l'agent Trésorier (100 % local). Chaque écriture montre son entrée résolue avant validation : la
relire en conséquence.

## Vérifier

```bash
cd backend && pytest tests/test_convert_node.py
```

Double fidèle : `tests/fake_convert.py`, avec le manifeste produit par le code d'Atelier Convert
(`build_manifest()`), enregistré dans `tests/fixtures/convert/manifest.json`. Le régénérer après une
évolution du nœud de Convert :

```bash
cd ../Atelier_Convert/backend && python -c "import json; from app.services.atelier.manifest import build_manifest; print(json.dumps(build_manifest().model_dump(mode='json', by_alias=True), ensure_ascii=False, indent=1))" > ../../Atelier_Nexus/backend/tests/fixtures/convert/manifest.json
```
