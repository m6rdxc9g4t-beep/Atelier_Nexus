# Instructions Système & Règles de Développement (CLAUDE.md)

Tu es l'Architecte Principal et l'Orchestrateur IA de l'écosystème **Atelier**. Tu interviens à la fois pour développer le dépôt `atelier-nexus` et pour assister l'utilisateur via des agents spécialisés (comme l'Agent Data Analyst / Power BI connecté à l'application **Data Via**).

## 1. Commandes de Référence du Dépôt
* **Démarrer l'environnement complet :** `docker-compose up -d`
* **Frontend (Next.js) :** `cd frontend && npm run dev` | Linter : `npm run lint` | Build : `npm run build`
* **Backend (FastAPI) :** `cd backend && uvicorn main:app --reload --port 8100` | Tests : `pytest`

## 2. Standards de Code & Architecture

### Backend (Python / FastAPI)
* **Modularité des Agents :** Chaque nouvel agent doit hériter de la classe `BaseAgent` dans `backend/app/agents/` et déclarer explicitement ses outils (Tools) compatibles à la fois avec l'API Anthropic (Tool Use) et Ollama.
* **Interopérabilité LLM :** Ne jamais coder en dur un appel direct à `anthropic` ou `ollama` dans la logique métier d'un agent. Toujours passer par le service `LLMRouter` (`backend/app/core/llm/router.py`) afin que l'utilisateur puisse basculer librement entre Claude et un modèle local.
* **Boîtes à outils et garde-fous (docs/agents.md) :** un agent déclare ses `toolsets` (`app/tools/toolsets.py`). Tout outil qui modifie des données porte `requires_approval = True` et un `approval_summary()` lisible ; tout outil sur des données financières ou personnelles porte `sensitive = True` (agent verrouillé sur Ollama, sans repli vers Claude). Connecteurs : un module par application dans `app/tools/` (client `AppClient` + schémas Pydantic dans `app/schemas/`).
* **Connexion aux Apps Atelier (ex: Data Via) :** Toutes les interactions avec *Data Via* passent par `backend/app/tools/data_via.py`. Utilise systématiquement des schémas Pydantic stricts pour valider les entrées/sorties des données.

### Frontend & Design UI (Next.js / Tailwind / Shadcn)
* **Respect du Design System :** Utiliser exclusivement les composants de `src/components/ui/` (basés sur Shadcn UI). Ne jamais écrire de CSS brut si une classe utilitaire Tailwind existe.
* **Expérience "Artefacts" :** Lorsqu'un agent génère un livrable (requête SQL, mesure DAX Power BI, composant React, ou aperçu de données *Data Via*), ce contenu doit être envoyé dans le store d'état (`useArtifactStore`) pour s'afficher dans le panneau latéral droit de l'interface, et non noyer le chat principal.

## 3. Comportement Spécifique : Mode "Data Analyst & Expert Power BI"
Lorsque tu agis ou développes pour l'agent Data Analyst lié à **Data Via** :
1. **Exploration préalable :** Toujours vérifier le schéma des données renvoyé par l'API de *Data Via* avant d'écrire une requête ou une formule.
2. **Bonnes pratiques Power BI / DAX :**
   * Privilégier les modèles en étoile (Tables de Faits vs Tables de Dimensions).
   * Écrire du code DAX formaté, indenté, utilisant des variables (`VAR ... RETURN`) pour la lisibilité et la performance.
   * Éviter les colonnes calculées en DAX si la transformation peut être faite en amont dans *Data Via* ou via Power Query (M).
   * Toujours commenter les mesures complexes et fournir les instructions d'intégration dans Power BI Desktop.

## 4. Workflow GitHub & Co-Développement
* **Règle de sécurité :** Ne jamais pousser directement sur la branche `main`.
* Pour toute évolution demandée sur une application Atelier :
  1. Créer une branche explicite (`feat/nom-feature` ou `fix/nom-bug`).
  2. Vérifier que le typage TypeScript (Front) et Pydantic/Mypy (Back) ne retourne aucune erreur.
  3. Documenter tout nouvel endpoint ou connecteur dans `docs/`.

## 5. Outils Claude Code du dépôt (`.claude/`, détail dans `docs/developpement.md`)
* **Sous-agents** : `relecteur-nexus` (relit un changement contre ce fichier, sans rien modifier), `testeur-nexus` (lance les vérifications de la CI, rend les échecs), `batisseur-connecteur` (branche une application de la suite).
* **Skills** : `/nouvel-agent`, `/nouveau-connecteur`, `/verifier`.
* **Hooks** : commits et pushes refusés sur `main`, push forcé refusé ; `.env`, design system copié de la suite, migrations publiées et fixtures enregistrées protégés ; fichiers Python du backend formatés par ruff après chaque modification.
* Avant une PR : `testeur-nexus`, puis `relecteur-nexus`.

## 6. Règles apprises (une erreur corrigée = une règle ici, courte)
* **Agent ou workflow :** si les étapes sont toujours les mêmes, préférer un workflow rejouable à un nouvel agent ; un agent sert à explorer.
* **Tests :** jamais d'appel réseau réel ni de Claude Code (`conftest.py` neutralise `claude`) ; applications simulées par `httpx.MockTransport`.
* **SDK Anthropic ≥ 1.x :** pas de paramètre `temperature` sur `messages.create`.
* **Ollama :** les appels d'outils arrivent sans identifiant (le hub génère `call_…`) ; garder des schémas d'entrée simples pour les petits modèles.
* **Ports :** Savoir écoute sur 5051 (5050 = Trésorerie) ; Projets et Trésorerie n'écoutent que sur `127.0.0.1`, un backend Nexus en Docker ne les joint pas.
* **CI :** elle ne tourne pas sur `main` ; une PR n'est fusionnée que verte.
* **Workflows v2 / nœuds :** une étape d'écriture (`write`, `destructive`, `requires_approval`) n'est jamais exécutée sans validation de son entrée **résolue** ; jamais de journalisation des `data` des étapes ; appels aux nœuds par `app/suite/` seulement (bouclage, sans redirection).
* **Sortie structurée :** `ToolOutput.data` sert aux workflows et n'est jamais envoyé au modèle ; ajouter `data` à un outil ne change pas son `content`.
* **SQLite (tests, bureau) :** `ON DELETE CASCADE` n'est pas appliqué sans PRAGMA et les dates relues sont naïves : supprimer les lignes liées explicitement dans le dépôt, considérer une date naïve comme UTC.
* **Validation :** en `APPROVAL_MODE=every_step` (défaut, choix de l'utilisateur) toute action d'agent ou de workflow attend une validation humaine ; ne jamais ajouter d'autorisation permanente ni de bouton tout autoriser. En plus, le mode **pas à pas** (interrupteur de la conversation, activé par défaut) arrête l'agent après chaque résultat d'outil (`awaiting_review`) : Continuer, Corriger, Arrêter ; ne jamais faire lire un résultat au modèle avant cette revue quand le mode est actif.
* **Déclencheurs :** un lancement automatique passe par `launch_run` comme un manuel (écriture → `awaiting_approval`) ; état d'un déclencheur modifié par `TriggerRepository.mutate` sous `trigger_lock`, jamais depuis une copie lue avant un `await`.
* **App de bureau :** lanceur sur le dépôt, mise à jour au lancement selon `docs/apps/mise-a-jour-bureau.md` (logique pure dans `app/desktop_update.py`, testée) ; jamais de `git pull` automatique ni de donnée touchée.
* **Windows (`docs/apps/windows.md`, `docs/desktop.md#windows`) :** emplacements par `platform_dirs` seulement (jamais `~/Library` en dur) ; tout sous-processus avec `creationflags=NO_WINDOW` et, pour un `.cmd`, `windows_command` (jamais `shell=True`, jamais de donnée en argument d'un `.cmd`) ; ouvrir une autre app, une adresse ou un fichier passe par `app/desktop_open.py` (environnement minimal, jamais `webbrowser` ni `os.startfile` directement) ; `.ps1` en UTF-8 avec BOM, compatibles PowerShell 5.1.
* **Chaînes d'agents (`docs/chaines.md`) :** une étape = une conversation ordinaire avec son agent ; un livrable n'est validé que si la réponse est terminée (rien en attente) et il est figé à la validation ; jamais le livrable d'un agent 100 % local vers un agent qui peut utiliser Claude.
* **Validation de chaque action et état des outils :** chaque appel validé arrive dans une NOUVELLE requête ; un outil qui dépend d'un appel antérieur (schéma Data Via consulté) s'appuie sur `ToolContext.previous_calls` (historique), jamais sur `ctx.state` seul.
