---
name: verifier
description: Lance toutes les vérifications de la CI d'Atelier Nexus en local (backend ruff, mypy, pytest ; frontend eslint, tsc, Vitest, build) et résume ce qui échoue. À utiliser avant un commit, une pull request, ou quand on demande si tout passe.
---

# Vérifier Atelier Nexus comme la CI

Délègue au sous-agent `testeur-nexus` s'il est disponible : il garde les journaux hors de la
conversation et ne renvoie que les échecs. Sinon, lance toi-même :

```bash
# Backend (depuis backend/ ; .venv/bin/ devant chaque commande si le venv existe)
ruff check . && ruff format --check . && mypy . && pytest -q

# Frontend (depuis frontend/ ; npm ci si node_modules manque)
npm run lint && npm run typecheck && npm test
npm run build                                   # si l'interface a changé
NEXUS_EXPORT=1 NEXT_PUBLIC_API_URL='' npm run build && test -f out/index.html   # app de bureau
```

Règles :
- Ne marque rien comme terminé tant qu'une vérification échoue.
- Un test qui échoue se corrige dans le code, pas dans le test, sauf si le comportement
  attendu a vraiment changé (et alors on le dit).
- Ne retouche jamais une fixture enregistrée (`backend/tests/fixtures/`) ni une migration
  publiée pour faire passer un test : le hook `garde_fichiers` le refusera.
- La CI ne tourne pas sur `main` : chaque PR doit être verte avant fusion.
