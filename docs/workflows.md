# Workflows rejouables — Étape 18

« L'agent explore, le workflow industrialise. » La première fois, un agent trouve le chemin :
il lit le schéma d'un jeu Data Via, lance la bonne agrégation, publie la mesure DAX. Ce chemin
est ensuite enregistré tel quel et relancé **sans modèle** : mêmes outils, même ordre, résultat
immédiat, aucun jeton, rien qui quitte la machine.

## 1. Dans l'interface

1. Sous la dernière réponse d'un agent qui a utilisé des outils avec succès :
   **Enregistrer en workflow**.
2. La fenêtre propose les étapes du tour (les appels réussis, dans l'ordre). On peut retirer
   une étape, modifier ses paramètres (JSON) et remplacer une valeur par `{{nom}}` pour la
   demander à chaque lancement (`"dataset_id": "{{jeu}}"`). Libellé et valeur par défaut de
   chaque paramètre se règlent en dessous.
3. Bouton **Workflows** dans l'en-tête de la conversation : liste des workflows de l'agent,
   **Lancer** (avec les paramètres), modifier, supprimer.
4. Les livrables (aperçus Data Via, DAX, Markdown…) arrivent dans le panneau Artefacts, comme
   ceux de l'agent. Le détail de chaque étape (✓ réussie, ✗ en erreur, refusée, non exécutée)
   s'affiche dans la fenêtre.

Ce qui n'est jamais capturé : un appel en erreur ou refusé, un appel resté en attente de
validation, `delegate_to_agent` (il fait appel à un modèle) et `current_datetime` (rien à en
faire sans modèle). La fenêtre indique ce qui a été écarté et pourquoi.

## 2. Garde-fous

- **Porte de contrôle avant de commencer** : chaque étape est vérifiée (outil disponible pour
  l'agent, paramètres valides pour cet outil). Un problème → rien n'est exécuté.
- **Arrêt à la première erreur ou au premier refus** : les étapes suivantes sont marquées
  « non exécutées » (elles dépendent souvent de la précédente : un commit après la création
  d'une branche). Un refus donne le statut `stopped`.
- **Écritures validées à chaque lancement** : une étape `requires_approval` (créer une tâche
  dans Projets, modifier Tab…) n'est jamais exécutée sans « Autoriser », exactement comme dans
  le chat ; le workflow s'arrête d'abord sur `awaiting_approval` sans rien exécuter.
- **Une validation vaut pour l'action montrée, et elle seule** : chaque action en attente
  porte un jeton calculé à partir du workflow (identifiant et version), du numéro d'étape, de
  l'outil et des valeurs finales. D'autres valeurs de paramètres, une étape déplacée ou un
  workflow modifié entre-temps donnent un autre jeton : la validation est redemandée.
- **Jamais d'outil qui appelle un modèle** : `delegate_to_agent` est refusé à
  l'enregistrement comme au lancement.
- **Contexte partagé** entre les étapes : l'exploration préalable de Data Via (schéma avant
  requête) reste satisfaite, comme pendant le tour d'origine.
- **Aucun modèle** : un workflow d'un agent « 100 % local » (Finance, Tuteur…) ne fait que des
  appels aux applications locales.

## 3. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/workflows?agent=` | Liste (les plus récemment modifiés ou lancés d'abord) |
| POST | `/api/workflows/capture` | `{agent, messages}` → `WorkflowDraft` (étapes, écartés, étapes d'écriture). Rien n'est enregistré. 422 si aucun appel réutilisable. |
| POST | `/api/workflows` | `{agent, title, description, steps, params, source_conversation_id}` → 201 |
| GET / PUT / DELETE | `/api/workflows/{id}` | Lecture, modification (titre, description, étapes, paramètres), suppression |
| POST | `/api/workflows/{id}/run` | `{params, approvals}` → `WorkflowRunResult` |

Étape : `{"tool": "data_via_query", "input": {…}, "label": ""}` (30 au plus).
Paramètre : `{"name": "jeu", "label": "Jeu de données", "default": "ventes_2026"}` (10 au plus,
nom `^[a-z][a-z0-9_]{0,39}$`). Un `{{nom}}` cité dans une étape doit être déclaré (422 sinon).
Les paramètres sont substitués comme **texte** ; c'est l'outil qui convertit (« 20 » pour un
champ entier devient 20), et un identifiant « 007 » reste « 007 ».

Outils inconnus de l'agent refusés à l'enregistrement (422) ; un outil dont l'application n'est
pas configurée est accepté et signalé au lancement.

Résultat d'exécution :

```json
{
  "status": "completed | failed | stopped | awaiting_approval",
  "message": "2 étape(s) exécutée(s), 1 livrable(s).",
  "steps": [{"index": 1, "tool": "…", "label": "", "input": {…}, "status": "ok | error | refused | skipped", "content": "…"}],
  "artifacts": [{"kind": "data_preview", "title": "…", "content": "…", "language": null, "metadata": {}}],
  "pending": [{"index": 2, "tool": "projets_create_work_item", "summary": "Créer la TASK « … »", "token": "9f2c…"}]
}
```

`approvals` : jeton reçu dans `pending` → `true` / `false`. Un workflow dont l'agent a été
supprimé répond 409 au lancement.

Base : table `workflows` (migration `0005_workflows`), avec compteur de lancements et dernier
statut. Code : `app/workflows.py` (capture et exécution), `app/schemas/workflows.py`,
`app/db/workflows.py`, `app/api/workflows.py` ; interface dans `frontend/src/features/workflows/`.

## 4. Quand préférer un workflow à un agent

| Situation | Choix |
|---|---|
| Même question chaque semaine sur les mêmes données | Workflow (paramètre : la période) |
| Données inconnues, question nouvelle | Agent |
| Le résultat doit être identique d'une fois sur l'autre | Workflow |
| Il faut interpréter les chiffres, rédiger | Agent, éventuellement après un workflow qui prépare les données |
