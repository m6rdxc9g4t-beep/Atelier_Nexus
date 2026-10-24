"""Moteur d'analyse statistique d'Atelier Nexus (boîte à outils `analyse`).

Calculs déterministes en Python pur (aucune dépendance numérique) : profil d'un jeu,
distributions (asymétrie, aplatissement, normalité), corrélations, relations entre deux
variables, valeurs aberrantes, nettoyage, agrégations et graphiques pour le panneau Artefacts.

- `special`  : fonctions spéciales (bêta et gamma incomplètes) → valeurs p ;
- `stats`    : statistiques descriptives et tests ;
- `frame`    : jeu de travail en colonnes typées, inférence des types (formats français) ;
- `loaders`  : chargement depuis Atelier Viz, Atelier Tab ou un fichier joint ;
- `cleaning` : opérations de nettoyage, sans jamais modifier la source ;
- `store`    : jeux de travail d'une conversation, en mémoire ;
- `charts`   : spécifications des graphiques (artefact `chart`).
"""
