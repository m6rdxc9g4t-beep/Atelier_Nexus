# Connecteur Atelier Projets

Atelier Projets (Fastify + Prisma, dépôt `Atelier_Projets`) tient la hiérarchie Projet › Phase › Epic › Story ›
élément (FEATURE, TASK, BUG), les temps passés, le journal d'avancement et les jalons. Nexus lit son API et y écrit
**avec validation** de l'utilisateur.

Code : `backend/app/tools/projets.py` (client `ProjetsClient` et outils), schémas `backend/app/schemas/projets.py`
(champs en camelCase, comme sur le fil ; corps d'écriture stricts). Contrat lu dans
`Atelier_Projets/backend/src/routes/` et `src/schemas/` (`hierarchy.ts`, `work-items.ts`). Tests :
`tests/test_connectors.py` (réponses réelles rejouées par `httpx.MockTransport`), `tests/test_tool_data.py`.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `PROJETS_BASE_URL` | `http://127.0.0.1:3000/api` | Vide = connecteur désactivé (boîtes `projets_read`, `projets_write`, `tab_projets`) |
| `PROJETS_IMPORT_TOKEN` | vide | `ATELIER_IMPORT_TOKEN` d'Atelier Projets, si l'import depuis Tab est protégé ([tab.md](tab.md)) |
| `TIMEZONE` | `Europe/Paris` | Fuseau du « jour courant » : retards (`overdue`) et jalons dépassés |

Projets n'écoute que sur `127.0.0.1` : un backend Nexus en Docker ne le joint pas.

## Outils

| Outil | Boîte | Rôle |
|---|---|---|
| `projets_list_projects` | `projets_read` | Projets : identifiant, budget, dates, dépôt GitHub |
| `projets_dashboard` | `projets_read` | Budget consommé, avancement pondéré, tendance, répartition par statut |
| `projets_structure` | `projets_read` | Phases › epics (`id`) › stories (`story_id`), avancement et temps |
| `projets_list_work_items` | `projets_read` | Éléments filtrés : statuts, types, story, texte, **`over_budget`** (passé > estimé, d'après l'écart calculé par Projets) et **`overdue`** (échéance passée, élément ni Résolu, ni Terminé, ni Rejeté), filtres cumulés. Liste coupée à 50 lignes pour le modèle, qui est invité à affiner |
| `projets_work_item` | `projets_read` | Détail : chemin, description, journal, temps, commits, PR, dépendances |
| `projets_timesheet` | `projets_read` | Feuille de temps et totaux |
| `projets_milestones` | `projets_read` | Jalons : atteint, en retard ou à venir (jour courant dans `TIMEZONE`) |
| `projets_create_story` | `projets_write` | `POST /epics/{id}/stories` : une story (titre, description, dates) où ranger ensuite ses éléments |
| `projets_create_work_item` | `projets_write` | `POST /stories/{id}/work-items` : une FEATURE, TASK ou BUG |
| `projets_update_work_item` | `projets_write` | `PATCH /work-items/{id}` : titre, description (remplacée en entier), statut, avancement, priorité, estimation, échéance ; seuls les champs donnés partent |
| `projets_add_time_entry` | `projets_write` | Saisie de temps |
| `projets_add_log_entry` | `projets_write` | Entrée horodatée du journal d'avancement ; `hours` n'est qu'une mention d'en-tête, pas une saisie de temps |

## Résumés de validation

Chaque écriture montre exactement ce qui sera envoyé :

- `projets_update_work_item` : « Modifier l'élément #12345 : statut « Terminée », avancement 100 % (imposé par
  « Terminée », au lieu de 40 %) ». `RESOLVED` et `CLOSED` imposent 100 % : Nexus corrige l'avancement fourni (Projets,
  lui, garderait un `progress` donné) et le résumé l'annonce ; sans avancement fourni, « avancement 100 % (fixé par
  Atelier Projets pour ce statut) ». Une description remplacée est annoncée avec sa longueur et son début (« description
  effacée » si elle est vide).
- `projets_add_log_entry` : « Ajouter au journal de #12345 (2 h mentionnées) : « … » ».
- `projets_add_time_entry` : jour (« aujourd'hui » = jour de Projets) et commentaire.
- `projets_create_work_item` et `projets_create_story` : type, titre, parent, estimation, priorité, dates.
- Import d'une table Tab sans projet cible : « le projet du même nom, créé s'il n'existe pas ».

## Date du jour

Retards et jalons se jugent sur le jour de l'utilisateur, calculé une seule fois pour tous les outils par
`app/tools/clock.py` (`local_today`, fuseau `TIMEZONE`), ni en UTC ni sur l'horloge de la machine (un conteneur
tourne souvent en UTC). Le même utilitaire sert à `tab_check_table` et à `current_datetime` (boîte `core`), dont le
fuseau par défaut est aussi `TIMEZONE` : l'agent lit la même date que celle des contrôles. Testé autour de minuit
(heure d'été et d'hiver).
