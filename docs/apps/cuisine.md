# Connecteur Atelier Cuisine

Atelier Cuisine est l'app de cuisine du foyer : stock du frigo et des placards avec les dates, semainier des
repas, liste de courses, tickets de caisse et budget. Contrairement aux autres apps de la suite, c'est une
**app en ligne** : interface sur Vercel (PWA iPhone, app Mac Tauri `fr.ateliercuisine.app`), données dans
**Supabase** (Postgres + Row Level Security par `user_id`).

Code : `backend/app/tools/cuisine.py`, schémas `backend/app/schemas/cuisine.py`, tests
`backend/tests/test_cuisine.py` (Supabase simulé par `httpx.MockTransport`). Contrat lu dans le dépôt
`Atelier_Cuisine` (`backend/supabase/migrations/`, `frontend/src/lib/supabase.ts`, `budget.ts`, `dates.ts`) puis
vérifié sur le schéma déployé (2026-10-20).

**Lecture seule** dans ce lot : aucun outil d'écriture.

## Accès : API REST de Supabase + session du foyer

Nexus lit l'API REST du projet (PostgREST, `/rest/v1/<table>`) exactement comme l'app :

| En-tête | Valeur |
|---|---|
| `apikey` | Clé **publique** du projet (`sb_publishable_…` ou ancienne clé JWT `anon`) |
| `Authorization` | `Bearer <jeton d'accès>` de la session du foyer (Supabase Auth) |

La session s'ouvre par `POST /auth/v1/token` : `grant_type=password` (e-mail + mot de passe du foyer) ou
`grant_type=refresh_token`. Les règles RLS font le reste : **seules les lignes du compte connecté** sont lisibles.

- Une clé `service_role` (JWT de rôle autre que `anon`) ou `sb_secret_…` est **refusée** (elle contournerait RLS),
  dans les Réglages comme au démarrage du connecteur (boîte « non configurée », avec la raison).
- Adresse en HTTPS (HTTP seulement pour un Supabase local de développement), sans chemin.
- Supabase **fait tourner** les jetons de rafraîchissement : un jeton ne sert qu'une fois. La session en cours
  (jeton d'accès, jeton de rafraîchissement, expiration, identifiant du compte) est gardée en mémoire et dans
  `cuisine-session.json` **à côté du `.env`** (droits 600, ignoré par git). Jamais le mot de passe ni l'e-mail
  (la clé du fichier est une empreinte). Un jeton d'accès expiré ou révoqué (401) est renouvelé une fois.
- Si la session est perdue : avec un mot de passe, reconnexion automatique ; avec un jeton seul, message clair
  (« Session Atelier Cuisine expirée ou révoquée… ») : collez un nouveau jeton ou le mot de passe.
- Machine hors ligne : erreur d'outil « Atelier Cuisine injoignable… app en ligne, vérifiez la connexion
  Internet », l'agent reste utilisable.

Nexus n'a pas de mode « hors ligne » global : comme Claude, Cuisine n'est utilisé **que s'il est configuré**.
Sans réglage, les boîtes sont écartées (`unavailable_toolsets`) et rien ne part vers Supabase.

## Configuration (Réglages → « Atelier Cuisine », ou `.env`)

| Variable | Rôle |
|---|---|
| `CUISINE_SUPABASE_URL` | Adresse du projet : Supabase → Project Settings → API → Project URL (`https://<projet>.supabase.co`) |
| `CUISINE_SUPABASE_ANON_KEY` | Clé publique (publishable / anon), la même que celle de l'app |
| `CUISINE_EMAIL` | E-mail du compte du foyer |
| `CUISINE_PASSWORD` | Mot de passe du foyer (secret : jamais renvoyé par l'API des réglages) |
| `CUISINE_REFRESH_TOKEN` | À la place du mot de passe : jeton de rafraîchissement d'une session (renouvelé ensuite) |
| `CUISINE_SESSION_FILE` | Facultatif, hors interface : emplacement de la session (défaut : `cuisine-session.json` à côté du `.env`) |

Rien n'est en dur ni dans le dépôt : tout vide = connecteur désactivé. Il faut l'adresse, la clé publique et
(e-mail + mot de passe) **ou** un jeton de rafraîchissement.

## Outils

| Boîte | Outil | Rôle |
|---|---|---|
| `cuisine` | `cuisine_stock` | Stock par emplacement (frigo, congélateur, placard, corbeille, maison) ; **« À finir en premier »** : périmés et dates à `urgent_days` jours (3 par défaut), restes mis en boîte d'abord à date égale ; produits presque finis ; inventaire (quantité ou niveau, rayon, échéance) |
| `cuisine` | `cuisine_meal_plan` | Semainier (semaine en cours par défaut, ou `start` + `days` ≤ 31) : repas par créneau, type (recette, assemblage rapide, extérieur), prévu / cuisiné, jours sans repas |
| `cuisine` | `cuisine_shopping_list` | Liste de courses rangée selon les rayons du foyer, origine (repas prévu, à racheter, ticket, manuel) ; articles cochés sur demande |
| `cuisine_budget` | `cuisine_budget` | **`sensitive`** : dépenses du mois (`month` AAAA-MM) Alimentaire / Maison & hygiène / Sorties, plafonds (mensuels sur le mois, hebdomadaires sur la semaine en cours), panier moyen, coût par repas cuisiné, tickets du mois |

Règles reprises d'Atelier Cuisine (`frontend/src/lib/budget.ts`) : Alimentaire = sous-total des rayons 1 à 9 des
tickets, Maison = rayons 10 et 11, Sorties = coût des repas extérieurs ; jour **local** d'un ticket ; libellés
d'échéance de `dates.ts`.

Données minimales : chaque lecture demande ses colonnes (`select=`). Les outils non sensibles ne lisent **aucun
prix** (ni `purchase_price`, ni `unit_price` / `total_price`, ni `external_cost`) ; l'outil Budget ne lit jamais le
texte brut d'un ticket (`raw_text`).

## Confidentialité et agents

- L'agent Cuisine a été retiré. La boîte `cuisine` (stock, repas, courses : pas de données financières) reste
  disponible pour les agents personnalisés et les workflows.
- **Finance** (`finance`, 100 % local) : `core`, `tresorerie`, `cuisine_budget`. Budget et tickets sont des données
  financières : boîte `sensitive`, modèle local imposé, sans repli vers Claude. Le prompt rappelle de ne pas
  additionner ces montants à ceux de Trésorerie (mêmes achats souvent déjà débités par carte).

## Menu « Suite Atelier » et état

- Menu Suite : tuile `data-atelier-app="cuisine"` (#E056E2), icône `CookingPot`, « Stock, repas, courses et budget du
  foyer », adresse `https://atelier-cuisine-iota.vercel.app` (`NEXT_PUBLIC_ATELIER_CUISINE_URL`). App en ligne :
  **jamais sondée**, affichée « en ligne ». Dans l'application de bureau, le clic ouvre l'app Mac
  `fr.ateliercuisine.app` si elle est installée (`SUITE_ONLINE_BUNDLES`), sinon le navigateur.
- `GET /api/apps/status` : si le connecteur est configuré, lit le stock dans Supabase (jamais l'adresse Vercel) :
  « N produit(s) en stock, M à finir en premier (en ligne) ».
