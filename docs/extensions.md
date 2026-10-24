# Extensions

Une extension est un paquet Python externe qui ajoute à Nexus des boîtes à outils et des agents,
sans modifier son code. Exemple : [Agent_DatAnalyst](https://github.com/m6rdxc9g4t-beep/Agent_DatAnalyst)
(Atelier Convert, écritures Viz, plan de travail Projets, saisies Trésorerie ; complète l'agent
Data Analyst et ajoute l'agent « Trésorier »).

## Activer une extension

1. La rendre importable, au choix :
   - **app de bureau** (son environnement Python est refait à partir des `requirements*.txt` du
     dépôt, un `pip install` y serait perdu) : `NEXUS_PLUGIN_PATHS=/chemin/absolu/vers/Agent_DatAnalyst/src`
     — valable pour une extension sans dépendance autre que celles de Nexus ;
   - **serveur de développement** : `pip install -e ../Agent_DatAnalyst` dans l'environnement du
     backend (ou le même `NEXUS_PLUGIN_PATHS`).
2. La nommer : `NEXUS_PLUGINS=atelier_datanalyst` (plusieurs : séparées par des virgules), dans
   `backend/.env` ou, pour l'app de bureau, `~/Library/Application Support/Atelier Nexus/.env`.
3. Relancer Nexus. Les agents de l'extension apparaissent après les agents fournis.

`NEXUS_PLUGIN_PATHS` n'accepte que des dossiers absolus existants, ajoutés **après** les chemins
de Nexus : une extension ne peut pas remplacer un module de Nexus ni de la bibliothèque standard.

Rien n'est découvert automatiquement : un paquet installé mais absent de `NEXUS_PLUGINS` n'est
jamais importé. Une extension introuvable ou qui échoue est journalisée
(`Extension « … » non chargée`) et écartée ; Nexus démarre avec ses agents fournis.

## Écrire une extension

Le module expose `register()`, appelé **une fois** par `app/plugins.py`, à la fin de l'import de
`app.agents` (après les agents fournis). Il y enregistre :

| Quoi | API de Nexus |
|---|---|
| Boîtes à outils | `app.tools.toolsets.register_toolset(Toolset(...))` |
| Agents | `@app.agents.registry.register_agent` sur une sous-classe de `BaseAgent` |
| Compléter un agent fourni | `app.agents.registry.extend_agent(nom, source=..., toolsets=..., instructions=..., starters=...)` |
| Libellés lisibles des outils | `app.tools.labels.TOOL_LABELS.update({...})` |
| Nom et couleur d'une nouvelle app | `app.suite.apps.APP_NAMES`, `APP_COLORS` |

Dans la fabrique d'une boîte (`build=lambda env: ...`), l'environnement d'exécution fournit :

- `env.client(nom, fabrique)` : client d'application créé à la demande, réutilisé pendant
  l'exécution et fermé à la fin (il expose `async aclose()`) ;
- `env.transport(app)` : transport simulé dans les tests (`None` en réel) ;
- `env.conversation_files()` : fichiers joints **cités par la conversation en cours**
  (`load(nom ou id)`, `list()`), vide hors conversation (workflows, déclencheurs) ;
- `env.settings` et les clients fournis (`env.data_via()`, `env.projets()`…).

Les règles des agents fournis s'appliquent à l'identique (`docs/agents.md`) : tout outil qui
modifie des données porte `requires_approval = True` et un `approval_summary()` concret ; tout
outil sur des données financières ou personnelles porte `sensitive = True`, et sa boîte
`sensitive=True` (agent verrouillé sur le modèle local). Une boîte ne peut pas réutiliser
l'identifiant d'une boîte existante : `register_toolset` lève une erreur et l'extension n'est
pas chargée.

## Compléter un agent fourni (`extend_agent`)

Plutôt que de créer un second agent qui fait presque la même chose, une extension peut ajouter à
un agent **fourni** ses boîtes, des consignes (ajoutées à la fin de son prompt) et des exemples :

```python
from app.agents.registry import extend_agent

extend_agent(
    "data_analyst",
    source="atelier_datanalyst",          # idempotent : un second appel avec la même source ne fait rien
    toolsets=("convert", "convert_write", "data_via_write", "projets_plan"),
    instructions="Faire circuler un fichier dans la suite : …",
    starters=("Voici mon fichier de ventes : fais-en un rapport Atelier Viz.",),
)
```

Refus (`ValueError` ou `KeyError`, rien n'est modifié, l'extension n'est pas chargée) : agent
inconnu, boîte inconnue (à enregistrer **avant** l'appel), boîte `sensitive` sur un agent qui n'est
pas déjà « 100 % local » — une extension ne peut pas faire basculer un agent sur le modèle local à
l'insu de l'utilisateur ; pour des données sensibles, enregistrer un agent séparé (ex. Trésorier).
Les agents personnalisés (créés depuis l'interface) ne peuvent pas être complétés ainsi.

