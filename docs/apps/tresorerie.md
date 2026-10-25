# Connecteur Atelier Trésorerie

Atelier Trésorerie tient les comptes, opérations, catégories, budgets, objectifs d'épargne et placements d'un foyer ou
d'une petite structure. API Flask + SQLite, sans authentification, sous `/api`. Nexus la lit **en lecture seule**.

Code : `backend/app/tools/tresorerie.py`, schémas `backend/app/schemas/tresorerie.py`. Contrat lu dans
`atelier_tresorerie` (`api.py`, `services/`) puis vérifié contre l'application lancée sur six mois fictifs
(`flask --app app seed-demo`).

## Configuration et lancement

| Variable | Défaut | Rôle |
|---|---|---|
| `TRESORERIE_BASE_URL` | `http://127.0.0.1:5050/api` | Vide = connecteur désactivé |

Lancement : l'app Mac Atelier Trésorerie, ou `python app.py` dans son dossier (`http://127.0.0.1:5050`). Trésorerie
n'écoute que sur `127.0.0.1` : un backend Nexus en Docker ne la joint pas.

Messages donnés au modèle (qui les relaie tels quels, sans inventer de commande) :

- application arrêtée : « Atelier Trésorerie injoignable sur … : lancez-le (app Mac Atelier Trésorerie, ou
  `python app.py` dans son dossier ; port 5050 par défaut), puis réessayez. » ;
- **autre service sur le port** : Atelier Savoir écoute lui aussi sur 5050 par défaut. Sur un 404 d'une route qui
  existe toujours chez Trésorerie, le client vérifie une fois l'identité (`GET /api/ping` doit renvoyer
  `app = atelier-tresorerie`) et remplace le « Ressource introuvable » par « Le service sur … ne répond pas comme
  Atelier Trésorerie : Atelier Savoir occupe peut-être le port 5050 (lancez Savoir avec ATELIER_PORT=5051)… ».
  Si Trésorerie répond bien, le 404 d'origine est rendu tel quel.

## Convention de signe

La même dans tous les outils :

- le **montant d'une opération** est signé : négatif = dépense, positif = revenu (colonne « montant € ») ;
- un **total de dépenses** est écrit en valeur positive, toujours avec le mot « dépenses » (tableau de bord,
  historique, budgets, hors budget, totaux par catégorie) ;
- une **évolution** est dite en clair : « en hausse de 7.5 % », « en baisse de 5.3 % », « stable ». Pour les
  dépenses, Trésorerie compare les montants dépensés : « en baisse » = on a moins dépensé que le mois précédent à date.
- les virements internes (opération liée à une autre, ou catégorie de type `transfert`) ne sont ni des revenus ni des
  dépenses ; le « net » d'une liste d'opérations, lui, les comprend.

## Outils (tous `sensitive` : modèle local imposé, lecture seule)

| Outil | Rôle |
|---|---|
| `tresorerie_dashboard` | Patrimoine net, revenus, dépenses, taux d'épargne du mois comparés au mois précédent à date, historique, dépenses par catégorie du mois |
| `tresorerie_accounts` | Comptes et leur identifiant, soldes, placements |
| `tresorerie_categories` | Catégories (depense, revenu, transfert) et leur identifiant |
| `tresorerie_transactions` | Opérations filtrées (compte, catégorie ou sans catégorie, mois **ou** période, type, statut, texte), totaux sur tout le filtre |
| `tresorerie_category_totals` | Totaux par catégorie sur un mois ou une période (trimestre, année), toutes les pages lues, éventuellement mois par mois |
| `tresorerie_budgets` | Budgets d'un mois : dépensé, reste ou dépassement, alerte, dépenses hors budget |
| `tresorerie_goals` | Objectifs d'épargne, progression, effort mensuel |
| `tresorerie_holdings` | Placements, plus-values (négatif = moins-value), poids |

Schémas pensés pour les petits modèles : chaque champ porte une description (« identifiant donné par
tresorerie_accounts »…). `type` accepte aussi le français (`depense`, `dépenses`, `revenu`, `transfert`,
`virement` → `expense`, `income`, `transfer`), sans tenir compte des majuscules ni des accents ; `month` et
`start` / `end` sont exclusifs (message clair sinon). Un champ envoyé vide (`"month": ""`, fréquent chez les petits
modèles qui remplissent tous les champs) compte comme non renseigné, au lieu d'être refusé.

### `tresorerie_transactions`

`limit` (1 à 200) opérations renvoyées, 50 montrées au modèle ; les totaux revenus / dépenses / net portent toujours
sur **tout** le filtre (calculés par Trésorerie). L'artefact « Opérations » n'est publié que si la réponse ne montre
pas tout (plus de 50 lignes, ou Trésorerie a plus d'opérations que la page renvoyée), avec un titre tiré du filtre :
« Opérations — 2026-07, dépenses, non catégorisées (100 sur 183) ».

### `tresorerie_category_totals`

Paramètres : `month` ou `start` / `end` (sans période : tout l'historique), `type` (`expense` par défaut, ou
`income`), `account_id`, `by_month` (une colonne par mois, 12 au plus ; avec `start` / `end`, un mois sans
opération garde sa colonne, à 0).

- Parcourt **toutes les pages** de `GET /transactions` (200 par page, 50 pages au plus), sans jamais compter deux
  fois une opération : arrêt dès qu'une page n'apporte rien de neuf.
- Regroupe par catégorie (« Sans catégorie » compris, signalé : à catégoriser pour un récapitulatif juste), montants en
  valeur positive, part du total, tri du plus gros au plus petit.
- **Contrôle** : la somme est comparée au total calculé par Trésorerie sur le même filtre. En cas d'écart
  (trop d'opérations, pagination incohérente), la réponse dit de présenter les totaux comme partiels, et le titre de
  l'artefact et de la table finit par « (partiel) ». Sans opération sur le filtre : « Aucune opération », sans tableau.
- Sorties : tableau pour le modèle, artefact `data_preview` « Dépenses par catégorie — du … au … », et table
  `atelier-table/1` (`ToolOutput.data` : `categorie`, mois éventuels, `operations`, `total`, `part`) pour les
  workflows v2.

## Confidentialité

Règle d'Atelier Trésorerie : « aucune donnée financière ne doit quitter la machine ». La boîte `tresorerie` est
`sensitive` : l'agent qui l'utilise est verrouillé sur Ollama, sans repli vers Claude, et un orchestrateur qui tourne
sur Claude ne peut pas le solliciter ([`agents.md`](../agents.md) §3).

## Agents

**Finance** (`finance`) et **Comptable** (`comptable`), catégorie Finance, 100 % locaux : `core`, `tresorerie`
(et `cuisine_budget` pour Finance).
