"""Workflows v2 : graphe d'étapes outils Nexus et actions des applications (docs/workflows.md §5).

- `templates` : gabarits `{{…}}` typés (paramètres, sorties des étapes ancêtres, exécution) ;
- `graph` : ordre topologique, cycles, ancêtres ;
- `catalog` : étapes disponibles (outils d'un agent ou de la suite, actions des manifestes) ;
- `validation` : erreurs par étape et par champ, codes stables ;
- `engine` : exécution pas à pas persistée, arrêt sur chaque écriture, reprise.
"""
