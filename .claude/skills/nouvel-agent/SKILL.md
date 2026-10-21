---
name: nouvel-agent
description: Ajoute un agent expert (codé) à Atelier Nexus — classe, icône, boîtes à outils, exemples, tests, cas d'évaluation et documentation. À utiliser quand on demande un nouvel agent fourni avec l'application (pas un agent créé depuis l'interface).
---

# Ajouter un agent expert à Atelier Nexus

Un agent expert est une classe Python. Un agent **personnalisé** se crée depuis l'interface
(« Créer un agent ») et ne demande aucun code : propose-le d'abord si l'utilisateur veut
seulement un prompt et des boîtes existantes.

## 1. Cadrer (avant d'écrire)

Réponds à ces questions, avec l'utilisateur si besoin :
- **Rôle** en une phrase, et 3 exemples de demandes réelles (ce seront les `starters`).
- **Boîtes à outils** nécessaires : liste dans `backend/app/tools/toolsets.py`
  (`core` toujours en tête). Une boîte qui manque → skill `nouveau-connecteur` d'abord.
- **Confidentialité** : s'il touche Trésorerie, Savoir ou le budget de Cuisine, il est
  automatiquement local (boîte `sensitive`). Sinon, `privacy = "local_only"` seulement si
  l'utilisateur le demande.
- **Workflow ou agent ?** Si les étapes sont toujours les mêmes, un workflow rejouable suffit
  (enregistré depuis une conversation réussie) : ne crée pas d'agent pour ça.

## 2. Écrire la classe

Dans le module de sa catégorie (`backend/app/agents/experts/` : `general`, `data`, `projects`,
`dev`, `finance`, `learning`, `home`, `business`) ou un nouveau module importé dans
`experts/__init__.py` (l'ordre des imports = l'ordre d'affichage).

```python
@register_agent
class VeilleAgent(BaseAgent):
    name = "veille"                       # ^[a-z][a-z0-9_]{2,40}$, unique
    display_name = "Veille"
    description = "Suit l'actualité d'un secteur et en tire des actions."   # une phrase
    icon = "lightbulb"
    category = "Métiers"
    toolsets = ("core",)
    starters = (
        "Résume l'actualité de la semaine dans mon secteur.",
        "…",
        "…",
    )
    max_iterations = 8                    # 12 pour un agent qui explore beaucoup
    system_prompt = prompt("""
Tu es …
Méthode : 1. … 2. … 3. …
""")
```

- `prompt()` (de `experts/common.py`) ajoute les règles communes : ne les répète pas.
- Le prompt dit **dans quel ordre** utiliser les outils et **quand s'arrêter**. Il nomme les
  outils par leur nom exact (`data_via_describe_dataset`…).
- Icône : une valeur de `ICONS` et du `Literal` `Icon` dans `backend/app/schemas/agents.py`.
  Nouvelle icône → l'ajouter aux deux, et à `BY_ICON` dans
  `frontend/src/features/chat-agent/agentMeta.ts` (icône Lucide).

## 3. Tester

- `backend/tests/test_framework.py` : ajoute le nom dans
  `test_catalog_lists_the_experts_with_categories`.
- Un test de comportement avec `ScriptedProvider` (`tests/fakes.py`) si l'agent a une règle
  propre (verrou local, outil obligatoire avant un autre…).
- Agent local : vérifie qu'il refuse Claude (`ProviderNotAllowedError`), sur le modèle de
  `test_finance_experts_are_local_only`.

## 4. Évaluer

Ajoute 2 ou 3 cas réels dans `backend/evals/cases/` (fichier de la catégorie) : les demandes des
`starters`, avec ce qui doit être vrai à la fin (outils appelés, artefact produit, validation
demandée, aucune donnée inventée). Lance-les sur le moteur visé :
`python -m scripts.evals --agent <name> --provider ollama --repeat 3`.
(Si `backend/evals/` n'existe pas encore sur ta branche, saute cette étape et signale-le.)

## 5. Documenter et vérifier

- `docs/agents.md` §1 : une ligne dans le tableau des agents fournis.
- Libellés lisibles des nouveaux outils éventuels : `TOOL_LABELS` dans
  `frontend/src/features/chat-agent/ToolCall.tsx`.
- Lance le skill `verifier` (ou le sous-agent `testeur-nexus`), puis `relecteur-nexus`.
