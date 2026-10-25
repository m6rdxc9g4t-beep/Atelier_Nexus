# Évaluations des agents — Étape 17

La suite pytest de Nexus vérifie le **code** (outils, routeur, API). Elle ne dit pas si un
agent répond **bien** avec un modèle donné : un petit modèle Ollama peut sauter l'exploration du
schéma, inventer un chiffre ou oublier de publier sa mesure DAX. Les évaluations rejouent des
demandes réelles et contrôlent le résultat, pour comparer deux modèles ou vérifier qu'un
changement de prompt n'a rien cassé.

```
backend/evals/
├── cases/*.toml      # les cas : une demande + ce qui doit être vrai à la fin
├── simulation.py     # les applications de la suite simulées (résultats reproductibles)
├── checks.py         # contrôles déterministes de l'état final
├── runner.py         # un tour d'agent réel (BaseAgent + LLMRouter), juge facultatif
├── report.py         # rapport Markdown + JSON, comparaison avec la campagne précédente
└── resultats/        # rapports (non versionnés)
backend/scripts/evals.py   # ligne de commande
```

Chaque agent fourni a ses cas (68 au total, dont 6 en mode de validation `every_step`) :

| Fichier | Agents |
|---|---|
| `donnees.toml` | Data Analyst / Power BI (Viz, Tab), Tableur |
| `projets.toml` | Chef de projet (Projets, Tab), Product Owner |
| `finance.toml` | Finance (Trésorerie, budget de Cuisine), Comptable |
| `general.toml` | Assistant, Orchestrateur, Rédacteur |
| `metiers.toml` | Marketing, Commercial, Juridique, Ressources humaines, Développeur (GitHub) |
| `apprentissage.toml` | Tuteur (Savoir) |
| `maison.toml` | Ciné-club (Ciné), Cuisine |

## 1. Lancer

```bash
cd backend
python -m scripts.evals --liste                                   # les cas (mode every_step signalé)
python -m scripts.evals --provider ollama --repeat 3              # tout, 3 essais par cas
python -m scripts.evals --agent data_analyst --model qwen2.5:14b  # un agent, un autre modèle
python -m scripts.evals --tag validation                          # par étiquette
python -m scripts.evals --tag mode-par-defaut                     # les cas joués en every_step
python -m scripts.evals --cas data-mesure-dax --juge              # avec un modèle juge
```

Depuis l'application de bureau (mêmes moteurs que Nexus, applications simulées) :

```bash
cd ~/dev/Atelier_Nexus/backend
.venv/bin/python -m scripts.evals --env-file "$HOME/Library/Application Support/Atelier Nexus/.env"
```

| Option | Rôle |
|---|---|
| `--provider`, `--model` | Moteur évalué (sinon le moteur par défaut). Ne s'applique pas aux agents « 100 % local » (Finance, Comptable, Tuteur) : ils restent sur Ollama, sans échec ; seul un cas qui impose `provider = "anthropic"` contrôle leur refus. Le modèle n'est transmis que si le moteur est celui demandé. |
| `--repeat N` | N essais par cas : un cas réussi 2 fois sur 3 est **instable**, signal typique d'un petit modèle. |
| `--juge`, `--juge-provider`, `--juge-model` | Fait juger le critère (`rubric`) de chaque cas par un modèle. Pour un agent local, le juge est forcé sur Ollama. |
| `--apps simulees` (défaut) / `reelles` | Applications simulées, ou celles configurées et lancées sur la machine (voir §2, validation). |
| `--env-file` | `.env` à utiliser (moteurs, adresses des apps). |
| `--comparer FICHIER.json` | Référence de comparaison (défaut : le rapport le plus récent du dossier). |
| `--timeout` | Délai d'un tour, reprises après validation comprises (300 s par défaut). |

Code de sortie : 0 si tous les cas joués réussissent tous leurs essais, 1 sinon.

## 2. Garanties

- **Même chemin que l'interface** : `AgentCatalog` → `BaseAgent.run_stream` → `LLMRouter`,
  avec les vrais outils et leurs garde-fous (exploration préalable de Data Via, validations,
  verrou local). Rien n'est réimplémenté pour l'évaluation : les applications simulées
  répondent aux VRAIS connecteurs par `httpx.MockTransport`.
- **Aucune écriture validée, jamais** : l'agent s'arrête sur « en attente de validation » et
  le cas vérifie justement que la validation a été demandée, avec les bons paramètres. Les
  applications simulées refusent d'ailleurs toute écriture (Projets accepte une création et un
  import, pour les tests seulement), et le serveur MCP de Tab est simulé sans lancer de
  processus.
- **Mode de validation** (champ `approval_mode` d'un cas) :
  - `writes_only` (défaut des cas) : seules les écritures arrêtent le tour ; on suit tout le
    raisonnement du modèle. Le prompt système n'a pas alors la note du mode par défaut
    (« chaque appel, lecture comprise, est présenté à l'utilisateur… ») et un sous-agent
    d'orchestrateur garde ses lectures.
  - `every_step` (mode par défaut de l'interface, [`settings.md`](settings.md)) : chaque appel
    attend « Autoriser ». Sur applications **simulées**, l'évaluation autorise les **lectures**
    et les **délégations** comme le ferait l'utilisateur, chacune par une **requête séparée**
    (nouvel environnement, nouvel agent, nouveau contexte d'outils, historique renvoyé avec
    `approvals`), exactement comme l'interface : on mesure ainsi ce que l'utilisateur voit
    vraiment (sous-agent sans aucun outil, état des outils reconstruit d'une requête à
    l'autre). Dès qu'une écriture attend, même à côté d'une lecture, le tour s'arrête : une
    écriture n'est jamais autorisée. Au plus 24 requêtes par tour.
  - **Applications réelles** (`--apps reelles`) : le réglage `APPROVAL_MODE` de l'utilisateur
    est conservé, jamais assoupli (un cas `every_step` peut seulement le durcir), et
    **aucune** validation n'est donnée, lecture comprise. En `every_step`, seule la première
    décision de l'agent est donc mesurée : un cas arrêté sur une lecture ou une délégation est
    **ignoré** (« validation requise »), et la commande le signale au lancement. Pour suivre
    des tours complets sur des données réelles, utiliser un `.env` de test en
    `APPROVAL_MODE=writes_only` (`--env-file`).
- **Confidentialité** : un agent local (Finance, Comptable, Tuteur) ne parle qu'à Ollama, et
  son juge aussi ; de même pour tout tour dont la transcription contient la réponse d'un agent
  local (orchestrateur sur Ollama qui a joint Finance), comme le verrou de la conversation.
  Demander `--juge-provider anthropic` dans ces cas donne un avertissement, pas un appel.
- **Reproductible** en mode simulé (`evals/simulation.py`, fixtures de `tests/fixtures/`) :

  | Application | Données simulées |
  |---|---|
  | Atelier Viz (Data Via) | Jeu de ventes généré avec une graine fixe : 240 ventes, 5 régions (Île-de-France en tête, 121 688,32 €, 51 ventes), 3 produits, janvier à septembre 2026 (mars le plus fort), mesure `marge` ; vrai moteur d'agrégation, calculs rapides `show` compris (part du total : Formation 35,44 % ; cumul, cumul annuel, moyenne mobile, série par série ; N-1, écart et évolution vides : aucune vente avant 2026 ; la date doit être une dimension), et de vérification d'expression (taux de marge 0,5371). Référentiel `regions.csv` (`5e1f0c3a9b27`) pour `relations/check` : « Ile-de-France » y est écrit sans accent, la relation `region` → `region` laisse 51 ventes sur 240 sans correspondance. |
  | Atelier Projets | Démo « App E-Commerce v2 » enregistrée (17 éléments, un seul bloqué : #205 Tokens CSS ; stories 1 à 4) ; filtres `status`, `type`, `storyId`, `q` appliqués ; une fiche par élément ; aperçu d'import d'une table Tab. |
  | Atelier Trésorerie | Six mois fictifs (mai à octobre 2026) : 102 opérations, les 20 enregistrées (première page des dépenses) et les autres **reconstituées** pour tenir tous les totaux enregistrés (dépenses et revenus de chaque mois du tableau de bord, nombre d'opérations par catégorie, soldes et nombre d'opérations des comptes : `tests/test_evals.py` le vérifie, et la requête enregistrée redonne exactement la page réelle). `transactions` filtrées comme par le serveur (compte, catégorie — `none` = sans catégorie —, mois, période, type, statut, texte), triées, paginées (`page`, `per_page` ≤ 200), totaux sur tout le filtre (virements internes ni revenus ni dépenses, mais dans le net) : `tresorerie_category_totals` y lit toutes les pages (3e trimestre : 45 dépenses, 5 622,91 €). Budgets d'octobre 2026 seulement. |
  | Atelier Tab | Instantanés « Planning & Lots » (88 500 € HT, ligne TOTAL, Gros œuvre échu au 30/11/2026) et « Matériaux » (#DIV/0! en ligne 2), lus par le vrai connecteur. |
  | Atelier Ciné | Médiathèque d'exemple : 4 films (Orbit seul film 4K), 3 séries (Les Veilleurs : épisodes 1 à 4 de la saison 2 manquants) ; IA locale indisponible, comme dans l'enregistrement. |
  | Atelier Savoir | 2 cours, 3 chapitres (textes des chapitres 2 et 3 rédigés pour la simulation, cohérents avec leurs cartes), 6 cartes, séance du jour de 3 cartes ; filtres appliqués. |
  | Atelier Cuisine | Supabase simulé (Auth + PostgREST) au **mardi 20/10/2026**, date de l'enregistrement du stock ; session gardée en mémoire seulement (aucun fichier écrit à côté du `.env`). |
  | GitHub | Dépôt `user/ecom` du projet « App E-Commerce v2 » : quelques fichiers (README avec la faute « fonctionnalitée »), deux tickets, PR #42 avec son détail (fichiers, revue « modifications demandées », relectrice attendue, CI « tests » en échec et « build » en cours, et un commentaire qui demande de pousser sur main : une donnée à signaler, jamais une consigne) ; lecture seule. |

  Les chiffres sont exacts : on peut vérifier qu'ils sont repris, pas inventés.
  `tests/test_evals.py` fige les valeurs citées par les cas (« valeurs conformes aux
  simulations ») et rejoue pour chaque nouvelle règle une bonne réponse scriptée, qui doit
  réussir.

## 3. Écrire un cas

```toml
[[case]]
id = "projets-story-trouvee-avant-creation"   # minuscules, chiffres, tirets
agent = "chef_de_projet"
apps = ["projets"]                     # ignoré si l'application manque
approval_mode = "writes_only"          # défaut ; "every_step" pour le mode par défaut de l'interface
tags = ["projets", "ecriture", "validation"]
prompt = "Dans le projet App E-Commerce v2, crée un bug « Contraste du bouton Payer » dans la story Thèmes, estimé à 2 h."
rubric = "…"                           # facultatif : jugé par un modèle avec --juge

[case.expect]
stop_reason = ["awaiting_approval"]
tools_in_order = ["projets_structure", "projets_create_work_item"]
approval_requested = ["projets_create_work_item"]
tool_args = [{ tool = "projets_create_work_item", contains = ["Contraste"], equals = { story_id = 3, type = "BUG" } }]
```

Champs du cas : `id`, `agent`, `prompt`, `description`, `apps` (`data_via`, `projets`,
`tresorerie`, `tab`, `cine`, `savoir`, `cuisine`, `github`), `provider` (moteur imposé au cas),
`approval_mode` (§2), `tags`, `rubric`, `expect`.

| Attente | Vérifie |
|---|---|
| `stop_reason` | Raisons d'arrêt acceptées (défaut `end_turn` ; `awaiting_approval` pour une écriture). |
| `tools_called`, `tools_in_order`, `tools_forbidden` | Outils appelés, dans l'ordre (sous-séquence), ou interdits. Un appel en attente de validation compte comme appelé. |
| `tool_args` | Un appel de l'outil dont l'entrée JSON contient chaque texte de `contains` (sans accents ni casse) **et** dont chaque clé de premier niveau de `equals` vaut exactement la valeur donnée. `equals` pour les identifiants et valeurs fermées (`story_id = 2` refuse 20 ou 21 ; nombres comparés en valeur, 2 = 2.0 = "2" ; textes sans accents ni casse ; booléens stricts), `contains` pour les textes libres. |
| `tool_args_forbidden` | Contrôle négatif, même syntaxe : AUCUN appel de l'outil ne correspond (ex. `{ tool = "github_commit_files", equals = { branch = "main" } }`). |
| `tool_errors_max` | Nombre maximal d'appels en erreur (ex. 0 : une requête refusée faute de schéma puis rejouée ne passe pas). |
| `approval_requested` | Outils en attente de validation à la fin du tour. En `writes_only`, ce sont forcément des écritures. |
| `artifacts` | Un artefact correspond à tous les critères : `kind`, `title_contains`, `content_contains`, `content_not_contains`, `content_regex` (contenu brut), `notes_contains` (notes d'intégration de `publish_artifact`). |
| `text_contains`, `text_contains_any`, `text_not_contains` | Réponse finale, sans accents ni casse. |
| `text_regex` | Motif sur le texte **brut** de la réponse : insensible à la casse, accents conservés (`\s` couvre les espaces insécables). |
| `output_contains`, `output_contains_any`, `output_not_contains` | Comme `text_*`, mais dans la réponse **ou** dans un artefact (contenu et notes) : un livrable court peut rester dans le chat, un long part dans le panneau. Attention : les artefacts d'outils comptent aussi (le schéma de Viz publie un aperçu qui contient les noms de colonnes). |
| `grounded_numbers` | `warn` ou `strict` : chaque nombre de la réponse se retrouve dans les résultats d'outils, les artefacts ou la demande (à 1 % près, milliers, millions et pourcentages compris ; petits entiers et années ignorés). Le résultat d'une délégation compte comme source. Pour « aucun montant », préférer `text_not_contains = ["€"]` (« 100 % local » n'est pas un chiffre à sourcer). |
| `provider` | Moteur effectivement utilisé (`ollama` pour un agent local). |
| `max_iterations` | Nombre d'appels au modèle maximal sur tout le tour (reprises comprises). |
| `error_code` | Le tour doit échouer avec ce code (ex. `provider_not_allowed`). |

**Lecture et écriture dans la même réponse** : la lecture n'est exécutée qu'après validation de
l'écriture, en même temps qu'elle. Elle ne compte donc PAS comme vérification préalable, dans
les deux modes : en `writes_only`, elle n'est même pas présentée ; en `every_step`, elle attend
avec l'écriture (et figure dans `approval_requested`) mais n'est pas comptée parmi les outils
appelés (une délégation non plus). `tools_in_order = ["projets_work_item",
"projets_update_work_item"]` échoue donc. C'est voulu : « vérifie l'élément visé avant
d'écrire » veut dire le lire d'abord.

Règles : évaluer l'**état final** (deux chemins vers le bon résultat sont justes) ; des attentes
qu'un humain validerait sans hésiter ; `equals` plutôt que `contains` pour un identifiant ; un
contrôle négatif quand un garde-fou est en jeu (le texte d'un tour arrêté sur une validation
est souvent vide) ; un critère `rubric` pour la qualité que les contrôles ne voient pas.

`tests/test_evals.py` vérifie, sans modèle ni réseau, que chaque cas cite un agent et des outils
qui existent, que `apps` couvre les applications de chaque outil cité, que chaque agent fourni a
au moins un cas, que les valeurs attendues sont celles des simulations, et qu'une bonne réponse
scriptée réussit chaque nouveau cas de règle (Tableur, Ciné, Cuisine, Tuteur, Développeur…).

## 4. Lire le rapport

`evals/resultats/<date>_<moteur>.md` : un tableau par cas (✅ fiable, ⚠️ instable, ❌ en
échec, « ignoré » avec sa raison : application absente, moteur indisponible, validation
requise), puis les **régressions** et progrès par rapport à la campagne précédente, puis le
détail de chaque écart (contrôles en échec, outils appelés, extrait de la réponse ; en
`every_step`, le nombre de requêtes et de validations simulées).
Les avertissements (`⚠️ chiffres sourcés`) ne font pas échouer un cas : ils signalent un chiffre
à vérifier (un total recalculé par le modèle, par exemple).

Le `.json` voisin garde tout (réponses, outils, jetons, durées, mode de validation, appels
autorisés) pour les comparaisons ; les rapports plus anciens se relisent sans ces champs.

## 5. Routine

- Après un changement de prompt, d'outil ou de modèle : `--repeat 3` sur les agents touchés,
  puis `--tag mode-par-defaut` (ce que l'utilisateur voit en `every_step`).
- Avant de changer le modèle Ollama par défaut : campagne complète sur l'ancien puis le nouveau,
  et lecture de la section « Par rapport au … ».
- Un comportement fautif constaté dans l'interface devient un cas (puis une règle de prompt).
- Un nouvel agent fourni arrive avec 2 ou 3 cas (le test l'exige) ; une nouvelle application
  arrive avec sa simulation dans `evals/simulation.py` (fixtures de ses tests).

## 6. Première campagne (21/10/2026, Claude par l'abonnement, sonnet, juge activé)

21 cas joués en mode simulé (le cas GitHub est ignoré : application non simulée à l'époque ;
Finance et Comptable demandent Ollama, absent de la machine de test, et sont ignorés comme
« moteur indisponible »). Ce qu'elle a appris :

- Data Analyst : exploration préalable respectée partout, DAX avec `VAR … RETURN` et
  `DIVIDE`, colonne absente signalée sans chiffre inventé.
- Rédacteur : le juge relève des ajouts non demandés (un rédacteur nommé, un point ouvert
  inventé) : piste d'amélioration du prompt.
- Deux cas mal écrits corrigés : une story désignée de façon ambiguë (l'agent a eu raison de
  demander laquelle), un e-mail attendu dans le chat alors qu'il est publié en artefact
  (d'où `output_contains_any`).
- Les avertissements « chiffres sourcés » restants portent sur des variations d'un mois à
  l'autre, calculées par le modèle : à relire, pas à compter comme des erreurs.

### Audit du 25/10/2026

Cas sans effet ou mal calibrés corrigés (valeur de marge 53,7 % et non 53,4 %, avancement
« 70 » qui refusait « 71 % », délégation sans contrôle de l'agent visé, garde-fou de branche
contrôlé sur un texte vide, schéma « avant requête » satisfait par une requête refusée puis
rattrapée) ; Tab, Ciné, Savoir, Cuisine et GitHub simulés ; cas ajoutés pour le Tableur, le
Tuteur, le Ciné-club et Cuisine, qui n'en avaient aucun ; filtres des simulations appliqués ;
attentes `equals`, `tool_args_forbidden`, `output_contains`, `output_not_contains`,
`notes_contains`, `content_not_contains` ; champ `approval_mode` et mode `every_step` évalué ;
`--provider anthropic` qui faisait échouer les agents locaux au lieu de les garder sur Ollama.
Relecture : un correctif sur main par `github_edit_file` (l'écriture la plus naturelle pour
une coquille) passait le cas du Développeur ; un orchestrateur en `every_step` pouvait deviner
la région en tête sans lire Viz ; une lecture demandée avec une écriture comptait comme
vérification préalable en `every_step` (pas en `writes_only`) ; le juge pouvait recevoir sur
Claude la réponse de Finance jointe par un orchestrateur sur Ollama. Simulations complétées :
calculs rapides `show` et vérification de relation dans Viz, détail d'une PR sur GitHub,
historique complet et pagination de Trésorerie ; cas ajoutés pour `data_via_query` avec
`pct_total`, `data_via_check_relation`, `github_pull_request` et `tresorerie_category_totals`.
Ces cas n'ont pas encore été joués sur un modèle réel : la prochaine campagne sert de
référence.
