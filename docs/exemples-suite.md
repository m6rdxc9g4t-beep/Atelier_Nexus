# Exemples de la suite

Neuf histoires fictives (studio de design, chantier, e-commerce, freelance, patrimoine, marketing, courtage,
librairie, immobilier) traversent toute la suite Atelier avec les mêmes chiffres : Convert → Tab → Viz →
Trésorerie → **Nexus** → Projets → Wiki. Chaque application a un panneau « Exemples de la suite » qui charge sa
part de l'histoire ; l'histoire choisie est mémorisée sur l'appareil (`localStorage["atelier:exemple"]`).

Les fichiers (`exemples-suite/`, format `atelier-exemples/1`) sont générés par
`Atelier_Deploy/exemples/generer.py` et copiés tels quels dans chaque dépôt : **ne pas les modifier à la main**.
Dossier lu : `EXEMPLES_DIR`, sinon `exemples-suite/` du dépôt.

## Dans Nexus

Studio des workflows › **Modèles de la suite** › panneau « Exemples de la suite » : choisir une histoire, puis
**Charger l'exemple**.

- Les modèles de la bibliothèque cités par l'histoire sont copiés en workflows (titre « … · <histoire> »), avec
  leurs paramètres préremplis. **Rien n'est lancé** ; à l'exécution, chaque étape attend « Autoriser » comme
  toujours (`APPROVAL_MODE`).
- Paramètres résolus dans les applications quand elles répondent : id du jeu Viz (clé
  `exemple:<histoire>:operations`), n° du projet et de la story Projets. Chargez donc l'exemple dans Viz et dans
  Projets **avant** Nexus ; sinon la réponse dit ce qui manque et le paramètre reste à renseigner.
- Déclencheur sur `viz.alert.triggered`, filtré sur le nom de l'alerte de l'histoire (2 lancements par heure au
  plus). Il n'est actif que si la story Projets est connue.
- Si `TAB_MCP_COMMAND` est défini, le projet de l'histoire est aussi chargé dans les fichiers de Tab (outil MCP
  `load_suite_example`, qui crée les données d'un dossier vide) : c'est là que les workflows lisent et écrivent.
- Recharger recrée les workflows de l'histoire ; **Retirer** les supprime (déclencheurs compris, historique des
  exécutions conservé) et retire le projet des fichiers de Tab.

Un workflow d'exemple se reconnaît à la marque `[exemple:<histoire>]` en fin de description. Modifier la
description (ou retirer la marque) le rend à l'utilisateur : il n'est plus jamais remplacé ni retiré.

## API

| Méthode | Chemin | Réponse |
|---|---|---|
| GET | `/api/exemples-suite` | `{histoires: [{id, titre, sous_titre, secteur, resume, parcours: [{app, titre, texte}], workflows: [{id, title}]}]}` |
| POST | `/api/exemples-suite/{histoire}` | `{histoire, workflows, trigger_id, jeu, story, tab, notes}` ; 404 si l'histoire est inconnue |
| DELETE | `/api/exemples-suite/{histoire}` | `{histoire, retires}` ; 404 si l'histoire est inconnue |

Une application arrêtée ne fait jamais échouer `POST` : `notes` le dit en clair. Un modèle refusé par le
manifeste d'une application (version différente) n'est pas créé, et `notes` dit pourquoi.

Code : `backend/app/examples.py` (logique pure : fichiers, résolution, corps des workflows et du déclencheur),
`backend/app/api/examples.py` (routes), `frontend/src/features/workflows/SuiteExamples.tsx` (panneau).
