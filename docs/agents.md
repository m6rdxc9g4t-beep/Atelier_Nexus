# Plateforme multi-agents (étapes 5, 7 et 8)

Atelier Nexus réunit des **agents experts** (codés), des **agents personnalisés** (créés depuis l'interface)
et un **orchestrateur** qui confie des sous-tâches aux autres. Tous partagent la même boucle (`BaseAgent`),
le même routeur LLM (Claude ou Ollama) et des **boîtes à outils** branchées sur les applications Atelier.

## 1. Agents fournis

| Catégorie | Agent (`name`) | Boîtes à outils | Particularités |
|---|---|---|---|
| Général | Assistant Atelier (`assistant`) | core | Oriente vers le bon spécialiste |
| Général | Orchestrateur (`orchestrateur`) | core, delegation, equipe | Découpe, délègue, assemble ; 12 étapes |
| Communication | Rédacteur (`redacteur`) | core, wiki, wiki_write, equipe, equipe_write | Courriels, comptes rendus, documentation ; pages du Wiki |
| Communication | Marketing (`marketing`) | core, data_via | Plans de campagne, contenus ; s'appuie sur Viz |
| Équipe | Direction (`direction`) | core, equipe, equipe_write, equipe_rapports, projets_read, projets_write, wiki, formulaire | Comité, priorités, arbitrages ; inscrit les décisions validées et les comptes rendus → [`equipe.md`](equipe.md) |
| Équipe | Enquêtes (`enquetes`) | core, formulaire, formulaire_write, formulaire_reponses, equipe | **100 % local** ; crée et ouvre les formulaires, lit les réponses ; lit la mémoire sans y écrire |
| Données | Data Analyst (`data_analyst`) | core, analyse, data_via, tab, formulaire, equipe, equipe_write (+ boîtes d'Agent_DatAnalyst si l'extension est chargée) | Récupère, nettoie, analyse (distributions, asymétrie, corrélations, tests, atypiques) et visualise ; Power BI : exploration préalable, DAX `VAR … RETURN`, modèle en étoile → [`analyse.md`](analyse.md) |
| Données | Tableur (`tableur`) | core, tab, tab_write, tab_projets | Totaux calculés par l'outil, erreurs de formule, échéances dépassées ; modifie les tables (validation) |
| Données | Ingénieur de données (`ingenieur_donnees`) | core, data_via, tab | Inventaire des sources, qualité chiffrée, transformations Power Query typées ; ni modèle ni DAX |
| Données | Modélisateur BI (`modelisateur_bi`) | core, data_via | Grain, faits et dimensions, table Date, relations ; cardinalités vérifiées par requête |
| Données | Contrôleur qualité données (`controleur_donnees`) | core, data_via | Recalcule chaque chiffre annoncé, tableau des écarts, verdict |
| Gestion de projet | Chef de projet (`chef_de_projet`) | core, projets_read, projets_write, tab, tab_projets, equipe, equipe_write, equipe_rapports, wiki | Points d'avancement calculés, saisie de temps, statuts, plannings Tab |
| Gestion de projet | Product Owner (`product_owner`) | core, projets_read, projets_write, equipe, equipe_write, wiki, wiki_write | User stories, critères d'acceptation, estimations |
| Développement | Développeur (`developpeur`) | core, github_read, github_write, projets_read, equipe, equipe_write, wiki | Branches `feat/…`, commits `#ID`, PR brouillons |
| Développement | Architecte logiciel (`architecte`) | core, github_read, projets_read | Conception avant le code : fichiers, contrats, risques, plan de tests ; lecture seule |
| Développement | Testeur (`testeur`) | core, github_read, github_write | Tests sur la branche de travail (jamais `main`), cas limites, doublures |
| Développement | Relecteur de code (`relecteur_code`) | core, github_read | Verdict et remarques classées sur une branche ou une PR ; lecture seule |
| Finance | Finance (`finance`) | core, tresorerie, cuisine_budget, equipe | **100 % local** ; budget courses d'Atelier Cuisine |
| Finance | Comptable (`comptable`) | core, tresorerie | **100 % local**, PCG / TVA, ne modifie rien |
| Métiers | Commercial (`commercial`) | core, data_via | Propositions, objections, relances |
| Métiers | Juridique (`juridique`) | core | Droit français ; renvoie vers un avocat |
| Métiers | Ressources humaines (`rh`) | core | Fiches de poste, entretiens, intégration |

Boîte **partagée** (`shared`) : elle écrit là où lisent les agents sur Claude ; elle est retirée de tout
agent verrouillé sur le modèle local (déclaré, ou par une boîte ou un outil sensible), signalée
« indisponible » avec la raison. Les données locales (finances, réponses individuelles) ne peuvent donc
pas y être recopiées.

Ces agents s'enchaînent dans les **chaînes Data et Dev** ([`chaines.md`](chaines.md)).

Chaque expert est une classe de `backend/app/agents/experts/` (identité, boîtes, exemples, consignes) ;
`common.py` ajoute les règles communes (français, artefacts, pas de chiffre inventé, validation) ;
`team_rules.py` celles de l'équipe (mémoire partagée dans le Wiki, jamais de donnée personnelle ni financière) → [`equipe.md`](equipe.md).

Ciné-club, Cuisine et Tuteur ont été retirés (octobre 2026) : les boîtes `cine`, `cine_write`, `savoir_read`,
`savoir_write` et `cuisine` restent disponibles pour les agents personnalisés et les workflows, et Finance
garde `cuisine_budget`. Les conversations passées avec ces agents restent consultables dans l'historique ;
un workflow ou un déclencheur enregistré sur l'un d'eux répond « agent introuvable » (404) au lancement :
le recréer sur un agent personnalisé qui a les mêmes boîtes.

## 2. Boîtes à outils

| `id` | Outils | Écriture | Sensible |
|---|---|---|---|
| `core` | `current_datetime`, `publish_artifact` | — | — |
| `analyse` | `analyse_charger`, `_jeux`, `_profil`, `_distribution`, `_correlations`, `_relation`, `_aberrants`, `_nettoyer` (copie), `_agreger`, `_graphique`, `_exporter` ([`analyse.md`](analyse.md)) | — (calculs dans Nexus) | — |
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
| `wiki` | `wiki_spaces`, `_search`, `_pages`, `_read_page` ([`apps/wiki.md`](apps/wiki.md)) | — | — |
| `wiki_write` | `wiki_create_page`, `_append_page`, `_replace_page`, `_create_space` | ✅ validation, **partagée** | — |
| `formulaire` | `formulaire_forms`, `_form`, `_summary` (agrégats, sans texte libre, masqués sous 3 réponses) ([`apps/formulaire.md`](apps/formulaire.md)) | — | — |
| `formulaire_write` | `formulaire_create_form`, `_set_status`, `_set_access` | ✅ validation | — |
| `formulaire_reponses` | `formulaire_responses` (réponses une par une, plus récentes d'abord) | — | ✅ local imposé |
| `equipe` | `equipe_memoire` (espace « Équipe Atelier » du Wiki) | — | — |
| `equipe_write` | `equipe_noter`, `_decision`, `_compte_rendu` | ✅ validation, **partagée** | — |
| `equipe_rapports` | `equipe_point_avancement` (Projets), `_synthese_formulaires` (Formulaire, agrégats) | — | — |
| `delegation` | `delegate_to_agent` | — | — |

Une boîte **non configurée** (adresse ou jeton absent) est écartée sans casser l'agent : elle apparaît dans
`unavailable_toolsets`, l'interface l'indique et le prompt de l'agent le précise pour qu'il l'explique.

## 3. Garde-fous

**Validation humaine.** Réglage `APPROVAL_MODE` ([`settings.md`](settings.md)) : en `every_step` (**défaut**, choix de
l'utilisateur), **aucun** appel d'outil n'est exécuté directement, lectures comprises ; en `writes_only`, seulement les
outils `requires_approval`. Un appel à valider suit toujours le même chemin :
1. le modèle demande l'appel → l'agent émet `approval_required` (`calls` : id, nom, paramètres, résumé lisible,
   `kind` = `read` | `write` | `delegation`) puis `done` avec `stop_reason = "awaiting_approval"` ;
2. l'interface affiche une carte par appel (badge « Lecture », « Écriture » ou « Délégation », résumé,
   « Autoriser / Refuser ») ; plusieurs appels d'un même tour se décident un par un, puis partent ensemble.
   Jamais de « tout autoriser » ;
3. le client renvoie l'historique (terminé par le message assistant contenant les appels) avec
   `approvals: {"<id>": true|false}` ; l'agent exécute les appels autorisés, répond « refusé » pour les autres
   et poursuit. Un appel sans décision provoque une nouvelle demande (pour lui seul), et rien n'est exécuté tant
   qu'il en manque une. Rien n'est stocké côté serveur. Les identifiants `call_…` générés par le hub pour Ollama
   font l'aller-retour à l'identique.

Résumé d'une lecture : `BaseTool.approval_summary()` par défaut = nom lisible (`app/tools/labels.py`, mêmes
libellés que l'interface) + paramètres principaux (« Data Via · requête : dataset_id = « ventes », limit = 50 ») ;
un outil d'écriture le surcharge (« Créer la TASK … »). En `every_step`, le prompt système prévient le modèle que
chaque appel est validé.

**Revue de chaque résultat (« Pas à pas »).** Interrupteur dans l'en-tête de la conversation, **activé par défaut**
(choix de l'utilisateur, retenu dans le navigateur). Il complète la validation des actions, sans la remplacer :
1. le client envoie `review_results: true` ; après chaque exécution d'outil, l'agent émet
   `review_required` (`call_ids`) puis `done` avec `stop_reason = "awaiting_review"` **avant** que le modèle ne lise
   le résultat. La conversation enregistrée se termine alors par les résultats ;
2. l'interface déplie le résultat et propose **Continuer**, **Corriger** ou **Arrêter** ;
3. *Continuer* : le client renvoie l'historique (`review: "continue"`), le modèle lit le résultat. *Corriger* : la
   consigne est jointe aux résultats (« Consigne de l'utilisateur après ce résultat : … ») puis le tour continue.
   *Arrêter* : `review: "stop"`, le tour se termine **sans appel au modèle** (`stop_reason = "stopped_by_user"`).

Un appel refusé ne provoque pas de pause (le modèle propose une alternative). Désactivé, l'agent enchaîne ses
étapes ; les actions restent validées selon `APPROVAL_MODE`. Les évaluations et les workflows n'utilisent pas ce mode
(un workflow s'arrête déjà avant chaque étape, résultat précédent affiché).

**Confidentialité (« 100 % local »).** Un agent est verrouillé sur Ollama s'il le déclare (`privacy = "local_only"`)
ou s'il utilise une boîte sensible (`tresorerie`, `savoir_*`, `cuisine_budget`). Demander Claude → 403 `provider_not_allowed` ; pas de repli
vers Claude si Ollama tombe. L'orchestrateur ne peut déléguer à un agent local que s'il tourne lui-même sur Ollama,
sinon la réponse partirait chez Claude.

**Délégation.** `delegate_to_agent` attend la validation (résumé : agent + consigne). Un seul niveau, jamais de
délégation en chaîne. En `every_step`, le sous-agent n'a **aucun** outil : même ses lectures devraient être validées,
et une validation ne peut pas être présentée depuis l'intérieur d'un appel d'outil. Il répond à partir de la consigne
seule ; le résumé de la carte (« il répondra sans outil, à partir de cette consigne seulement »), la description de
l'outil donnée à l'orchestrateur et le prompt du sous-agent le disent. En `writes_only`, le sous-agent garde ses
lectures (ni écriture ni délégation) et ses artefacts remontent dans le panneau.

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
| `WIKI_BASE_URL` | `http://127.0.0.1:3200/api` | Atelier Wiki ([`apps/wiki.md`](apps/wiki.md)) |
| `FORMULAIRE_BASE_URL` | `http://127.0.0.1:3300/api` | Atelier Formulaire ([`apps/formulaire.md`](apps/formulaire.md)) |
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
Nouvel outil de lecture : son libellé dans `app/tools/labels.py` (`TOOL_LABELS`) et dans `ToolCall.tsx` ; le résumé
par défaut suffit, sauf paramètres peu parlants.
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

Un tour réussi peut devenir un **workflow** relancé sans modèle (« Enregistrer en workflow ») → [`workflows.md`](workflows.md).

Vérifié le 2026-10-20 contre Atelier Projets (démo « App E-Commerce v2 »), Atelier Trésorerie (6 mois fictifs)
et Atelier Viz (données d'exemple), dans Chromium : validation autorisée (élément réellement créé dans Projets)
et refusée, création d'un agent personnalisé verrouillé en local, agent Finance sur Ollama, thèmes clair et sombre.
