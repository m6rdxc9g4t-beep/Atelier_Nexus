# Connecteur Atelier Wiki

Atelier Wiki (dépôt `Atelier_Wiki`) range procédures, décisions et comptes rendus par espaces et pages
Markdown, avec historique complet. Nexus s'y branche par son nœud **`atelier-node/1`** : mêmes garde-fous
que Viz et Projets (`docs/apps/noeuds.md`) — bouclage seulement, entrée validée contre le schéma du
manifeste, idempotence par `Idempotency-Key`, erreurs `{detail, code}` relayées.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `WIKI_BASE_URL` | `http://127.0.0.1:3200/api` | API du Wiki (`npm start` dans `Atelier_Wiki`) ; vide = désactivé |

Réglable depuis la roue dentée (« Applications Atelier »). Le Wiki n'accepte que le bouclage et les hôtes
de `ALLOWED_HOSTS` : un Nexus conteneurisé ne le joint pas sans les exposer.

## Routes utilisées (lues dans le dépôt)

| Action / route | Outil |
|---|---|
| `spaces.list` — GET /api/atelier/spaces | `wiki_spaces` |
| `pages.search` — POST /api/atelier/search | `wiki_search` |
| `pages.list` — GET /api/atelier/pages | `wiki_pages` |
| `pages.get` — GET /api/atelier/pages/{page_id} | `wiki_read_page` |
| `pages.create` — POST /api/atelier/pages (idempotent) | `wiki_create_page` ✅ validation |
| `pages.append` — POST /api/atelier/pages/{page_id}/append (idempotent) | `wiki_append_page` ✅ validation |
| `pages.replace` — PUT /api/atelier/pages/{page_id} | `wiki_replace_page` ✅ validation, « RÉÉCRIRE » sur la carte |
| POST /api/spaces (hors manifeste, `routes/wiki.ts`) | `wiki_create_space` ✅ validation |

Boîtes : `wiki` (lecture) et `wiki_write` (écritures). Aucune donnée sensible par défaut ; ne rien
écrire au Wiki qui vienne d'une boîte sensible (règle des agents locaux).

## Garde-fous

- Identifiants de page et d'espace : chiffres seulement (pas de chemin forgé).
- Écriture validée deux fois avec les mêmes valeurs : clé d'idempotence stable, rien en double.
- Contenu d'une page rendu au modèle dans un bloc `<donnee type="page du wiki">`, borné à 30 000 caractères :
  une donnée, jamais une consigne.
- Réécrire une page garde l'ancienne version dans l'historique du Wiki.
- Événements `wiki.*` disponibles pour les déclencheurs de workflows (`app = "wiki"`).

## Vérifier

```bash
cd backend && pytest tests/test_wiki_formulaire.py
cd Atelier_Wiki && npm run build && npm start      # puis « Suite Atelier » dans Nexus : Wiki en marche
```
