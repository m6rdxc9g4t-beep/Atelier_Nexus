"""Nœuds de la suite Atelier (contrat `atelier-node/1`, docs/apps/noeud-atelier.md).

Chaque application (Viz, Projets, Tab, Convert) publie un manifeste de ses actions, échange des
tables `atelier-table/1` et publie ses événements. Ce paquet lit les manifestes (avec un cache
court), exécute une action déclarée (HTTP ou MCP) sous les garde-fous de Nexus et lit les
événements. Il ne fait jamais appel à un modèle.
"""
