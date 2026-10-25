# Connecteur Data Via — Étape 3

**Data Via** désigne l'API REST d'**Atelier Viz**, l'outil de BI locale de la suite Atelier (dépôt `Atelier_Viz`).
Atelier Nexus s'y connecte en **lecture seule** pour que les agents explorent les jeux de données, lancent des
agrégations (calculs rapides de Viz compris : part du total, N-1, cumuls), lisent des lignes brutes, vérifient des
mesures et les clés d'un modèle en étoile, sans jamais écrire de SQL.

- Code : `backend/app/tools/data_via.py` (point d'entrée unique, règle de `CLAUDE.md`)
- Schémas : `backend/app/schemas/data_via.py` (miroir de `Atelier_Viz/backend/app/schemas/{dataset,query}.py`)
- Contrat de référence côté Viz : `Atelier_Viz/backend/app/api/routes/{datasets,query,health}.py`

## 1. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `DATA_VIA_BASE_URL` | `http://127.0.0.1:8000/api` | API d'Atelier Viz (port fixé par `docs/SUITE.md`) |
| `DATA_VIA_API_KEY` | vide | Envoyé en `Authorization: Bearer` si défini (Viz n'en exige pas aujourd'hui) |
| `DATA_VIA_TIMEOUT` | `30` | Délai par appel, en secondes |

En Docker, le compose remplace l'adresse par `http://host.docker.internal:8000/api` : Atelier Viz tourne sur la
machine hôte. Vider `DATA_VIA_BASE_URL` désactive le connecteur (statut « non configuré »).

> **Viz « injoignable » alors qu'il tourne.** Une adresse locale est jointe sans le proxy du système
> (`app/core/net.py`, voir [docs/desktop.md](../desktop.md#proxy-du-système-et-apps-locales)). Si Viz n'a pas pu prendre
> le port 8000 (déjà occupé), son app de bureau en choisit un autre : reporter son adresse dans `DATA_VIA_BASE_URL`.

> **Ports.** La suite réserve 8000 (Atelier Viz) et 3000 (API d'Atelier Projets). Atelier Nexus utilise donc
> **8100** (API) et **3100** (interface) ; son Ollama conteneurisé est publié sur **11435** pour laisser 11434 à un Ollama natif.

## 2. Endpoints d'Atelier Viz utilisés

| Méthode | Chemin (Viz) | Usage dans Nexus |
|---|---|---|
| GET | `/api/health` | Statut |
| GET | `/api/datasets` | Liste des jeux |
| GET | `/api/datasets/{id}` | Profil : colonnes typées, statistiques, échantillon, modèle (mesures calculées, relations) |
| GET | `/api/datasets/{id}/rows?offset&limit` | Aperçu paginé (≤ 1000 lignes ; l'outil d'agent en demande ≤ 50) |
| POST | `/api/query` | Agrégation (dimensions, mesures, calculs rapides `show`, filtres, tri) — SQL généré côté Viz |
| POST | `/api/datasets/{id}/model/check` | Vérification d'une expression, **sans enregistrement** |
| POST | `/api/datasets/{id}/relations/check` | Correspondance des clés d'une relation fait → dimension, **sans enregistrement** |

Non utilisés volontairement (écriture) : import, `PUT …/model`, `…/refresh`, `DELETE`. Ils seront ajoutés, avec
confirmation explicite de l'utilisateur, quand un agent devra modifier un modèle.

## 3. Langage de requête (rappel)

```json
{
  "dataset_id": "85c8f5c3a4c2",
  "dimensions": [{"field": "date", "bin": "month"}, {"field": "region"}],
  "measures":   [{"field": "chiffre_affaires", "agg": "sum"}, {"agg": "count"}, {"field": "marge", "agg": "calc"},
                 {"field": "chiffre_affaires", "agg": "sum", "show": {"kind": "yoy_pct", "date": "date"}}],
  "filters":    [{"field": "produit", "op": "in", "values": ["Logiciel", "Support"]}],
  "sort":       [{"key": "sum(chiffre_affaires)", "desc": true}],
  "limit": 500
}
```

- `agg` : `sum`, `avg`, `min`, `max`, `count`, `count_distinct`, `median`, `calc` (mesure calculée du modèle).
- `bin` (dates) : `year`, `quarter`, `month`, `week`, `day`.
- `op` : `in`, `not_in`, `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `between` (2 valeurs), `contains`, `is_null`, `not_null`.
- `show` (calcul rapide, comme les mesures rapides de Power BI, calculé par Viz) : `ytd` cumul annuel, `running`
  cumul, `prev_year` N-1, `yoy_diff` écart et `yoy_pct` évolution vs N-1, `moving_avg` moyenne mobile sur `window`
  périodes (2 à 60, défaut 3), `pct_total` part du total. `date` (colonne date de référence) est obligatoire sauf
  pour `pct_total`. `yoy_pct` et `pct_total` sont en **points de %** (12,5 = 12,5 %) ; l'outil le rappelle au modèle.
- Clés des colonnes du résultat : dimension `champ` ou `champ|période`, mesure `agg(champ)` (`count(*)` sans champ),
  suffixée du calcul rapide comme dans Viz : `sum(ca)@pct_total`, `sum(ca)@ytd`, `sum(ca)@moving_avg6`. Le tri
  (`sort`) utilise ces clés.

Expressions (mesures et colonnes calculées), proches du DAX, en anglais ou en français :
`SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNT_DISTINCT`, `MEDIAN`, `DIVIDE`, `COALESCE`, `ROUND`, `ABS`, `IF`/`SI`,
`YEAR`, `MONTH`, `CONCAT`… Noms avec espaces entre crochets : `[chiffre d'affaires]`.

## 4. Outils d'agent

Déclaration dans un agent : boîte `data_via` (`toolsets = ("core", "data_via")`, voir [docs/agents.md](../agents.md) §2).

| Outil | Rôle | Artefact |
|---|---|---|
| `data_via_list_datasets` | Jeux disponibles (id, nom, lignes, colonnes) | — |
| `data_via_describe_dataset` | Schéma compact pour le modèle : types, stats, valeurs fréquentes, mesures, relations (modèle en étoile) et colonnes liées, 5 lignes | `data_preview` « Schéma — … » |
| `data_via_query` | Agrégation, calculs rapides `show` compris ; le modèle reçoit ≤ 50 lignes en tableau Markdown | `data_preview` « Requête — … » (résultat complet + requête) |
| `data_via_rows` | Lignes brutes dans l'ordre du jeu (`offset`, `limit` ≤ 50, colonnes choisies) : exemples, contrôle de qualité. Un classement ou un total passe par `data_via_query` | — |
| `data_via_check_expression` | Valide une mesure / colonne calculée, renvoie type et aperçu | — |
| `data_via_check_relation` | Vérifie une clé fait → dimension : lignes trouvées (et %), lignes sans correspondance (exemples), clés en double côté dimension ; verdict « clé valide » ou « à corriger en amont » | — |

Garde-fous :
- **Exploration préalable obligatoire** (CLAUDE.md §3.1) : `data_via_query`, `data_via_rows` et
  `data_via_check_expression` refusent un jeu dont le schéma n'a pas été consulté par `data_via_describe_dataset`
  plus tôt dans la conversation (état porté par `ToolContext.state`, reconstruit d'une requête à l'autre par le
  crochet `restore` de l'outil de schéma). `data_via_check_relation` contrôle la colonne du fait sur place si le
  schéma est connu, sinon laisse Viz la vérifier.
- **Validation locale** avant tout appel : champs inconnus (avec suggestion « Vouliez-vous dire… »), `bin` sur une
  colonne non date, `sum`/`avg` sur du texte, mesure calculée inconnue, colonne `show.date` inconnue ou non date,
  colonne demandée deux fois, tri sur une clé absente. Rien ne part vers Viz.
- **Identifiants** de jeu limités à `[A-Za-z0-9_-]` : impossible de sortir du chemin `/datasets/{id}`.
- Viz arrêté, 404, 422 : l'outil renvoie un message clair au modèle (pas d'exception, pas de trace d'erreur).
- Réponses de Viz validées par Pydantic ; un **champ ajouté** côté Viz est ignoré, un **champ manquant ou mal typé**
  donne une erreur « non conforme au contrat ».

## 5. Endpoints Atelier Nexus (`/api/data-via`)

Relais lecture seule pour le futur Dashboard Data Via du frontend.

| Méthode | Chemin | Réponse |
|---|---|---|
| GET | `/api/data-via/status` | `{configured, available, base_url, version, datasets, error}` — ne renvoie jamais d'erreur HTTP |
| GET | `/api/data-via/datasets` | `DatasetSummary[]` |
| GET | `/api/data-via/datasets/{id}` | `DatasetProfile` |
| GET | `/api/data-via/datasets/{id}/rows?offset=0&limit=100` | `DatasetRows` |
| POST | `/api/data-via/query` | `QueryResponse` (corps validé par Nexus avant envoi) |

Erreurs (format commun `{"error": {"code", "message", "provider": "data_via"}}`) :

| HTTP | `code` | Cause |
|---|---|---|
| 503 | `data_via_not_configured` | `DATA_VIA_BASE_URL` vide |
| 503 | `data_via_unavailable` | Atelier Viz arrêté, délai dépassé, 5xx |
| 404 | `data_via_not_found` | Jeu inconnu |
| 422 | `data_via_request_error` | Requête refusée par Viz (message de Viz relayé) ou réponse non conforme |

## 6. Vérifier sur sa machine

```bash
# 1. Atelier Viz (dépôt Atelier_Viz) — puis « Charger les données d'exemple » dans l'app
cd Atelier_Viz/backend && uvicorn main:app            # http://127.0.0.1:8000

# 2. Essai de bout en bout du connecteur (parcours d'un agent)
cd atelier-nexus/backend && python -m scripts.smoke_data_via

# 3. Via l'API de Nexus
uvicorn main:app --port 8100
curl localhost:8100/api/data-via/status
```

Résultat obtenu le 2026-10-20 contre Atelier Viz 0.1.0 et ses données d'exemple : liste, schéma de
`ventes_2026.csv` (8 colonnes), agrégation par région et par mois, vérification de
`DIVIDE(SUM(quantite), COUNT(*))`, refus local de `regiox` avec suggestion `region`.
