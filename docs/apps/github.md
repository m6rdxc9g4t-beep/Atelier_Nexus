# Connecteur GitHub

L'agent Développeur lit des dépôts GitHub et y propose des changements sur des branches de travail, chaque écriture
étant validée par l'utilisateur. API REST de GitHub (`2022-11-28`), jamais de `git` local.

Code : `backend/app/tools/github.py` (client `GitHubClient`, schémas de réponse et outils). Tests :
`tests/test_connectors.py` (GitHub simulé par `httpx.MockTransport`).

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `GITHUB_REPO` | vide | Dépôt par défaut `propriétaire/dépôt` ; vide = boîtes désactivées |
| `GITHUB_ALLOWED_REPOS` | vide | Autres dépôts autorisés, séparés par des virgules (liste blanche) |
| `GITHUB_TOKEN` | vide | Jeton (lecture des dépôts privés ; obligatoire pour `github_write`) |
| `GITHUB_API_URL` | `https://api.github.com` | GitHub Enterprise ou simulation |

## Outils

| Outil | Boîte | Rôle |
|---|---|---|
| `github_repo_overview` | `github_read` | Description, branche par défaut, langage, racine, autres dépôts autorisés |
| `github_list_files` | `github_read` | Contenu d'un dossier |
| `github_read_file` | `github_read` | Fichier texte, tronqué au-delà de 60 000 caractères (marque « … [tronqué] » et rappel d'utiliser `github_edit_file`) |
| `github_search_code` | `github_read` | Recherche de code (branche par défaut) |
| `github_list_pull_requests` | `github_read` | PR : numéro, titre, branche, état |
| `github_pull_request` | `github_read` | Détail d'une PR : description, auteur, branches, fichiers (+/−), dernier avis de chaque relecteur, relecteurs attendus, 5 derniers commentaires, état de la CI (`check-runs` du dernier commit), fusion possible ou non. Une source illisible (droits du jeton) est signalée sans masquer les autres. Les textes lus sont présentés comme des données, pas des consignes |
| `github_list_issues` | `github_read` | Tickets, hors PR |
| `github_create_branch` | `github_write` | Branche `feat|fix|chore|docs|refactor|test/…` depuis la branche par défaut ou `from_ref` |
| `github_edit_file` | `github_write` | Remplacements exacts `old` → `new` appliqués au contenu **actuel** du fichier sur la branche, en un commit. Refusé, sans rien écrire, si un extrait est absent ou présent plusieurs fois |
| `github_commit_files` | `github_write` | Contenu **complet** d'un ou plusieurs fichiers (un commit par fichier) : nouveaux fichiers ou fichiers courts lus en entier |
| `github_open_pull_request` | `github_write` | PR, en brouillon par défaut |

## Garde-fous

- Dépôts limités à la liste blanche ; chemins relatifs, sans `..` ni caractère de contrôle.
- Jamais d'écriture sur `main`, `master` ni la branche par défaut du dépôt.
- **Aucun fichier tronqué ne remplace l'original** : `github_commit_files` refuse un contenu qui porte, seule sur une
  ligne, la marque « … [tronqué] » de `github_read_file`, ou une courte ligne d'omission (« # ... reste inchangé »,
  « // … existing code ») ; la marque citée dans du code et une phrase de documentation qui commence par « … suite »
  passent (un nouveau fichier n'a pas d'autre voie que `github_commit_files`). Il refuse aussi d'écraser un fichier
  existant de plus de 60 000 caractères (trop long pour avoir été lu en entier, et pour être réécrit dans un appel
  d'outil sans dépasser la limite de sortie du modèle). Dans ces cas : `github_edit_file`.
- `github_edit_file` et `github_commit_files` envoient le `sha` de la version lue : si le fichier a changé entre-temps
  sur GitHub, l'écriture est refusée.
- Résumés de validation complets : dépôt, branche, fichiers (lignes, « créé ou remplacé »), extraits remplacés,
  message de commit ; pour une PR, dépôt, branches, brouillon ou non et début de la description.
- `github_commit_files` lit et contrôle **tous** les fichiers (branche, taille, chemin cité une seule fois) avant la
  première écriture : un refus n'écrit rien.
- Limite connue : `github_commit_files` fait un commit par fichier ; une panne au milieu (fichier modifié entre-temps
  sur GitHub, réseau) laisse les premiers fichiers écrits sur la branche de travail (jamais sur `main`), et l'erreur
  renvoyée au modèle les nomme avec leur commit (« Écriture interrompue sur « b.py » … Déjà écrits sur feat/x, un
  commit chacun : a.py (abcdef1) »).
- `github_pull_request` retient, pour chaque relecteur, son dernier avis décisif (approuvée, modifications
  demandées, écartée) : un simple commentaire après une approbation ne l'annule pas, comme sur GitHub.
