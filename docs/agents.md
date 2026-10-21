# Plateforme multi-agents (étapes 5, 7 et 8)

Atelier Nexus réunit des **agents experts** (codés), des **agents personnalisés** (créés depuis l'interface)
et un **orchestrateur** qui confie des sous-tâches aux autres. Tous partagent la même boucle (`BaseAgent`),
le même routeur LLM (Claude ou Ollama) et des **boîtes à outils** branchées sur les applications Atelier.

## 1. Agents fournis

| Catégorie | Agent (`name`) | Boîtes à outils | Particularités |
|---|---|---|---|
| Général | Assistant Atelier (`assistant`) | core | Oriente vers le bon spécialiste |
| Général | Orchestrateur (`orchestrateur`) | core, delegation | Découpe, délègue, assemble ; 12 étapes |
| Communication | Rédacteur (`redacteur`) | core | Courriels, comptes rendus, documentation |
| Communication | Marketing (`marketing`) | core, data_via | Plans de campagne, contenus ; s'appuie sur Viz |
| Données | Data Analyst / Power BI (`data_analyst`) | core, data_via, tab | Exploration préalable obligatoire, DAX `VAR … RETURN`, modèle en étoile |
| Données | Tableur (`tableur`) | core, tab, tab_write, tab_projets | Totaux calculés par l'outil, erreurs de formule, échéances dépassées ; modifie les tables (validation) |
| Gestion de projet | Chef de projet (`chef_de_projet`) | core, projets_read, projets_write, tab, tab_projets | Points d'avancement, saisie de temps, statuts, plannings Tab |
| Gestion de projet | Product Owner (`product_owner`) | core, projets_read, projets_write | User stories, critères d'acceptation, estimations |
| Développement | Développeur (`developpeur`) | core, github_read, github_write, projets_read | Branches `feat/…`, commits `#ID`, PR brouillons |
| Finance | Finance (`finance`) | core, tresorerie, cuisine_budget | **100 % local** ; budget courses d'Atelier Cuisine |
| Finance | Comptable (`comptable`) | core, tresorerie | **100 % local**, PCG / TVA, ne modifie rien |
| Apprentissage | Tuteur (`tuteur`) | core, savoir_read, savoir_write | **100 % local** ; interrogation, cartes, notes enregistrées en une validation |
| Maison | Ciné-club (`cineclub`) | core, cine, cine_write | Recommandations dans la médiathèque, épisodes manquants, doublons |
| Maison | Cuisine (`cuisine`) | core, cuisine | Ce qui presse dans le stock, idées de repas, planning, liste de courses ; lecture seule |
| Métiers | Commercial (`commercial`) | core, data_via | Propositions, objections, relances |
| Métiers | Juridique (`juridique`) | core | Droit français ; renvoie vers un avocat |
| Métiers | Ressources humaines (`rh`) | core | Fiches de poste, entretiens, intégration |

Chaque expert est une classe de `backend/app/agents/experts/` (identité, boîtes, exemples, consignes) ;
`common.py` ajoute les règles communes (français, artefacts, pas de chiffre inventé, validation).

## 2. Boîtes à outils

| `id` | Outils | Écriture | Sensible |
|---|---|---|---|
| `core` | `current_datetime`, `publish_artifact` | — | — |
| `data_via` | `data_via_list_datasets`, `_describe_dataset`, `_query`, `_check_expression` | — | — |
| `projets_read` | `projets_list_projects`, `_dashboard`, `_structure`, `_list_work_items`, `_work_item`, `_timesheet`, `_milestones` | — | — |
| `projets_write` | `projets_create_work_item`, `_update_work_item`, `_add_time_entry`, `_add_log_entry` | ✅ validation | — |
| `tresorerie` | `tresorerie_dashboard`, `_accounts`, `_categories`, `_transactions`, `_budgets`, `_goals`, `_holdings` | — (lecture seule) | ✅ local imposé |
| `tab` | `tab_list_tables`, `_read_table`, `_aggregate`, `_check_table` | — (lecture des instantanés) | — |
| `tab_write` | `tab_set_cells`, `_add_rows`, `_delete_rows`, `_add_column`, `_create_table` (serveur MCP de Tab) | ✅ validation | — |
| `tab_projets` | `projets_preview_tab_import`, `projets_import_tab_table` (Tab → Projets) | ✅ validation (import) | — |
| `cine` | `cine_library`, `_title`, `_library_report`, `_ai_summary` | — | — |
| `cine_write` | `cine_scan` | ✅ validation | — |
| `savoir_read` | `savoir_overview`, `_course`, `_chapter`, `_flashcards`, `_due_cards` | — | ✅ local imposé |
| `savoir_write` | `savoir_create_course`, `_add_chapter`, `_add_flashcards`, `_record_reviews` | ✅ validation | ✅ local imposé |
| `cuisine` | `cuisine_stock`, `_meal_plan`, `_shopping_list` (Atelier Cuisine, app en ligne) | — (lecture seule) | — |
| `cuisine_budget` | `cuisine_budget` (dépenses du mois, plafonds, tickets) | — (lecture seule) | ✅ local imposé |
| `github_read` | `github_repo_overview`, `_list_files`, `_read_file`, `_search_code`, `_list_pull_requests`, `_list_issues` | — | — |
| `github_write` | `github_create_branch`, `_commit_files`, `_open_pull_request` | ✅ validation | — |
| `delegation` | `delegate_to_agent` | — | — |

Une boîte **non configurée** (adresse ou jeton absent) est écartée sans casser l'agent : elle apparaît dans
`unavailable_toolsets`, l'interface l'indique et le prompt de l'agent le précise pour qu'il l'explique.

## 3. Garde-fous

**Validation humaine.** Un outil `requires_approval` n'est jamais exécuté directement :
1. le modèle demande l'appel → l'agent émet `approval_required` (`calls` : id, nom, paramètres, résumé lisible)
   puis `done` avec `stop_reason = "awaiting_approval"` ;
2. l'interface affiche « Autoriser / Refuser » ;
3. le client renvoie l'historique (terminé par le message assistant contenant les appels) avec
   `approvals: {"<id>": true|false}` ; l'agent exécute les appels autorisés, répond « refusé » pour les autres
   et poursuit. Un appel sans décision provoque une nouvelle demande. Rien n'est stocké côté serveur.

**Confidentialité (« 100 % local »).** Un agent est verrouillé sur Ollama s'il le déclare (`privacy = "local_only"`)
ou s'il utilise une boîte sensible (`tresorerie`, `savoir_*`, `cuisine_budget`). Demander Claude → 403 `provider_not_allowed` ; pas de repli
vers Claude si Ollama tombe. L'orchestrateur ne peut déléguer à un agent local que s'il tourne lui-même sur Ollama,
sinon la réponse partirait chez Claude.

**Délégation.** Un seul niveau ; les sous-agents n'ont ni outils d'écriture ni délégation ; leurs artefacts
remontent dans le panneau.

**GitHub.** Liste blanche de dépôts (`GITHUB_REPO` + `GITHUB_ALLOWED_REPOS`), jamais d'écriture sur `main`, `master`
ou la branche par défaut, branches `feat|fix|chore|docs|refactor|test/…`, chemins sans `..`, PR en brouillon par défaut.

**Projets.** `RESOLVED` / `CLOSED` imposent 100 % : l'outil corrige l'avancement au lieu d'échouer.

## 4. Agents personnalisés

Créés depuis l'interface (« Créer un agent ») ou l'API, stockés dans la table `custom_agents`.

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/toolsets` | Options de l'éditeur : icônes, boîtes (configurée, sensible, écriture), noms réservés |
| GET | `/api/custom-agents` | Définitions |
| POST | `/api/custom-agents` | Création → fiche `AgentInfo` (201) ; 409 si nom réservé ou existant |
| GET / PUT / DELETE | `/api/custom-agents/{name}` | Lecture, modification (l'identifiant ne change pas), suppression |

Corps : `name` (`^[a-z][a-z0-9_]{2,40}$`), `display_name`, `description`, `system_prompt` (≥ 20 caractères),
`icon`, `category`, `toolsets` (`core` toujours ajouté en tête), `privacy`, `default_provider`, `starters` (≤ 6).
Les règles communes de Nexus sont ajoutées au prompt à l'exécution.

Base : PostgreSQL (`DATABASE_URL`), ou SQLite pour un usage local (`sqlite+aiosqlite:///./data/nexus.db`).
Migrations Alembic appliquées au démarrage (`DB_AUTO_MIGRATE=true`) ; sans base, les experts restent utilisables.
Manuellement : `cd backend && alembic upgrade head`.

## 5. Autres endpoints

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/agents` | Catalogue complet : `icon`, `category`, `starters`, `source`, `toolsets`, `local_only`, `tools[].requires_approval`, `unavailable_toolsets` |
| POST | `/api/agents/{name}/run` · `/stream` | Corps : `messages`, `provider`, `model`, `conversation_id`, **`approvals`** |
| GET | `/api/apps/status` | État de Viz, Projets, Trésorerie, Tab, Ciné, Savoir, Cuisine (Supabase), GitHub (3 s max chacun, ne lève jamais) |

Événements SSE : `text_delta`, `tool_call`, `tool_result`, `artifact`, **`approval_required`**, `done`, `error`.

## 6. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `PROJETS_BASE_URL` | `http://127.0.0.1:3000/api` | Atelier Projets |
| `TRESORERIE_BASE_URL` | `http://127.0.0.1:5050/api` | Atelier Trésorerie |
| `TAB_EXPORTS_DIR` | `~/Atelier_Tab/exports` | Instantanés d'Atelier Tab ([`apps/tab.md`](apps/tab.md)) |
| `PROJETS_IMPORT_TOKEN` | vide | Jeton `ATELIER_IMPORT_TOKEN` d'Atelier Projets, si l'import depuis Tab est protégé |
| `TAB_MCP_COMMAND`, `TAB_DATA_DIR` | vide | Écriture dans Atelier Tab par son serveur MCP ([`apps/tab.md`](apps/tab.md)) |
| `CINE_BASE_URL` | `http://127.0.0.1:4000/api` | Atelier Ciné ([`apps/cine.md`](apps/cine.md)) |
| `SAVOIR_BASE_URL` | `http://127.0.0.1:5051/api` | Atelier Savoir, lancé avec `ATELIER_PORT=5051` ([`apps/savoir.md`](apps/savoir.md)) |
| `CUISINE_SUPABASE_URL`, `CUISINE_SUPABASE_ANON_KEY`, `CUISINE_EMAIL`, `CUISINE_PASSWORD` / `CUISINE_REFRESH_TOKEN` | vide | Atelier Cuisine, app en ligne : projet Supabase, clé publique, compte du foyer ([`apps/cuisine.md`](apps/cuisine.md)) |
| `APPS_TIMEOUT` | `20` | Délai par appel (s) |
| `GITHUB_TOKEN` | vide | Jeton *fine-grained* : Contents + Pull requests (lecture/écriture), dépôts choisis |
| `GITHUB_REPO` / `GITHUB_ALLOWED_REPOS` | vide | Dépôt par défaut / autres dépôts autorisés |
| `DATABASE_URL`, `DB_AUTO_MIGRATE` | PostgreSQL, `true` | Agents personnalisés |

> **Docker.** Atelier Projets, Atelier Trésorerie et Atelier Savoir n'écoutent que sur `127.0.0.1` (et Projets vérifie l'en-tête
> `Host`) : un backend Nexus conteneurisé ne les joint pas. Pour ces connecteurs, lancez le backend Nexus sur la
> machine (`uvicorn main:app --port 8100`), ou exposez les applications (Projets : `HOST=0.0.0.0`,
> `ALLOWED_HOSTS=host.docker.internal`).

## 7. Ajouter un agent ou un outil

```python
# backend/app/agents/experts/mon_domaine.py  (puis l'importer dans experts/__init__.py)
@register_agent
class VeilleAgent(BaseAgent):
    name = "veille"
    display_name = "Veille"
    description = "Suit l'actualité d'un secteur et en tire des actions."
    icon = "lightbulb"            # liste dans app/schemas/agents.py (ICONS) et agentMeta.ts
    category = "Métiers"
    toolsets = ("core",)
    starters = ("Résume l'actualité de la semaine dans mon secteur.",)
    system_prompt = prompt("""Tu es analyste de veille…""")
```

Nouvel outil d'écriture : `requires_approval = True` et un `approval_summary()` lisible (« Créer la TASK … »).
Outil sur des données personnelles ou financières : `sensitive = True` (et `sensitive=True` sur sa boîte).
Toute nouvelle boîte se déclare dans `app/tools/toolsets.py` (`register_toolset`).

## 8. Vérifier

```bash
cd backend && pytest                     # 195 tests, dont réponses réelles de Projets, Trésorerie, Ciné, Savoir ; Supabase simulé pour Cuisine
python -m scripts.smoke_apps             # tous les outils contre les applications lancées
python -m scripts.smoke_apps --apps=tab,cine,savoir --write   # + écritures (DONNÉES DE TEST uniquement)
DATABASE_URL=sqlite+aiosqlite:///./data/demo.db python -m scripts.demo_server   # démo sans LLM
```

Qualité des réponses avec un vrai modèle (outils appelés, livrables, validations, chiffres sourcés) :
`python -m scripts.evals --provider ollama --repeat 3` → [`evaluations.md`](evaluations.md).

Vérifié le 2026-10-20 contre Atelier Projets (démo « App E-Commerce v2 »), Atelier Trésorerie (6 mois fictifs)
et Atelier Viz (données d'exemple), dans Chromium : validation autorisée (élément réellement créé dans Projets)
et refusée, création d'un agent personnalisé verrouillé en local, agent Finance sur Ollama, thèmes clair et sombre.
