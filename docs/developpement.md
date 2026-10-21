# Développer Atelier Nexus avec Claude Code

Le dossier `.claude/` du dépôt équipe Claude Code pour travailler sur Nexus : des sous-agents
spécialisés, des procédures réutilisables (skills) et des garde-fous automatiques (hooks).
Il ne change rien à l'application elle-même : les agents **de** Nexus (`BaseAgent`) sont décrits
dans [`agents.md`](agents.md).

```
.claude/
├── settings.json              # hooks + règles de refus, partagés par le dépôt
├── agents/
│   ├── relecteur-nexus.md     # relecture contre CLAUDE.md (lecture seule)
│   ├── testeur-nexus.md       # vérifications de la CI (lecture seule)
│   └── batisseur-connecteur.md
├── skills/
│   ├── nouvel-agent/SKILL.md
│   ├── nouveau-connecteur/SKILL.md
│   └── verifier/SKILL.md
└── hooks/                     # Python, bibliothèque standard uniquement
    ├── garde_git.py
    ├── garde_fichiers.py
    └── formater_python.py
```

Réglages personnels (non versionnés) : `.claude/settings.local.json`.

## 1. Sous-agents

| Sous-agent | Modèle | Outils | Quand |
|---|---|---|---|
| `relecteur-nexus` | sonnet | Read, Grep, Glob, Bash | Avant un commit ou une PR : vérifie moteurs (`LLMRouter`), verrou local, validations, schémas Pydantic, design system, artefacts, migrations, docs, tests. Rend un verdict, ne modifie rien. |
| `testeur-nexus` | haiku | Bash, Read, Grep, Glob | Lance ruff, mypy, pytest, eslint, tsc, Vitest (et le build si demandé) ; ne renvoie que les échecs. |
| `batisseur-connecteur` | sonnet | Read, Write, Edit, Grep, Glob, Bash | Brancher une nouvelle application de la suite, en suivant le skill `nouveau-connecteur` (préchargé). |

Appel : « Utilise relecteur-nexus sur ma branche », ou `@relecteur-nexus`.
Les deux premiers n'ont pas d'outil d'écriture : un test le vérifie.

## 2. Skills

| Skill | Rôle |
|---|---|
| `/nouvel-agent` | Cadrer, écrire, tester, évaluer et documenter un agent expert. Rappelle qu'un agent personnalisé (interface) ou un workflow suffit souvent. |
| `/nouveau-connecteur` | Les 12 fichiers à toucher pour une application, dans l'ordre, et les règles des outils (validation, données sensibles, artefacts). |
| `/verifier` | Les commandes de la CI en local, et ce qu'on ne fait pas pour faire passer un test. |

## 3. Hooks (garde-fous déterministes)

| Hook | Événement | Effet |
|---|---|---|
| `garde_git.py` | avant Bash | Refuse : commit ou push depuis `main` / `master`, push vers `main` (y compris `HEAD:main`, `-C`, refspec `+…`), push forcé (`--force-with-lease` reste permis sur une branche de travail), suppression de branche distante ou de `main`. |
| `garde_fichiers.py` | avant Edit / Write | Refuse d'écrire : `.env` et `.env.*` (sauf `.env.example`), `cuisine-session.json`, le design system copié de la suite (`frontend/src/styles/atelier-ds/`, `frontend/src/styles/brand/`). Refuse de **modifier** une migration publiée ou une fixture enregistrée (en créer une nouvelle reste possible). |
| `formater_python.py` | après Edit / Write | `ruff format` et tri des imports sur le fichier Python modifié du backend (ruff de `backend/.venv` si présent). Ne bloque jamais. |

Un hook qui refuse sort avec le code 2 : l'action n'a pas lieu et Claude reçoit le motif.
`settings.json` ajoute des règles `permissions.deny` (push vers `main`, push forcé, lecture des
`.env`) : elles se contournent en reformulant la commande, d'où les hooks.

Les hooks sont testés par `backend/tests/test_dev_tooling.py` (dépôt git temporaire), avec la
forme des sous-agents et des skills.

## 4. Routine conseillée

1. Branche `feat/…` ou `fix/…`.
2. Pour un agent ou un connecteur : `/nouvel-agent` ou `/nouveau-connecteur`.
3. `testeur-nexus` jusqu'au vert, puis `relecteur-nexus`.
4. Une erreur de Claude corrigée pendant le travail devient une ligne de `CLAUDE.md` §6.
5. PR ; fusion seulement quand la CI est verte.

## 5. MCP

Aucun serveur MCP n'est déclaré pour le dépôt. Nexus parle aux applications de la suite par ses
propres connecteurs (`backend/app/tools/`), testés et soumis aux validations. Un serveur MCP
distant (Supabase, Vercel…) ne doit jamais recevoir de données de Trésorerie, de Savoir ou du
budget de Cuisine.
