# Historique des conversations (Étape 6)

Chaque échange avec un agent est enregistré en base, avec ses artefacts. On le retrouve d'une session à l'autre,
depuis le bouton **Historique** de l'en-tête de conversation.

## Ce qui est enregistré

| Table | Contenu |
|---|---|
| `conversations` | `id`, `agent`, `title`, `history` (messages au format neutre du routeur, JSON), `turn_meta` (moteur, modèle, jetons et motif d'arrêt de chaque tour), `pending` (actions en attente de validation), `created_at`, `updated_at` |
| `artifacts` | Livrables publiés pendant la conversation (`kind`, `title`, `content`, `language`, `meta`), `position` = nombre de messages au moment de la publication. Suppression en cascade avec la conversation. |

Migration : `backend/migrations/versions/0002_conversations.py`, appliquée au démarrage (`DB_AUTO_MIGRATE=true`).
SQLite (`DATABASE_URL=sqlite+aiosqlite:///./data/nexus.db`) et PostgreSQL sont tous deux pris en charge.

Les dates sont renvoyées en UTC explicite (`…Z`) : SQLite les stocke sans fuseau.

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/api/conversations?agent=&limit=` | Les plus récentes d'abord (50 par défaut, 200 au plus) : `id`, `agent`, `title`, dates, `message_count`, `artifact_count` |
| `POST` | `/api/conversations` | `{agent, title?}` → 201. 404 si l'agent n'existe pas. |
| `GET` | `/api/conversations/{id}` | Détail : `history`, `artifacts`, `turn_meta`, `pending_approvals` |
| `PATCH` | `/api/conversations/{id}` | `{title}` (1 à 120 caractères) |
| `DELETE` | `/api/conversations/{id}` | 204, artefacts compris |

Les routes `POST /api/agents/{nom}/run` et `/stream` acceptent `conversation_id` :

- l'historique envoyé et les nouveaux messages remplacent l'historique enregistré, les artefacts du tour sont ajoutés,
  le titre est tiré de la première question s'il est vide ;
- la conversation doit exister (404) et appartenir à cet agent (409) ;
- en streaming, un événement `saved` (`{conversation_id}`) ou `save_error` (`{message}`) suit `done`.

**Une base indisponible ne bloque jamais l'agent** : la réponse arrive normalement, seul l'enregistrement est sauté
(`save_error`), et l'interface affiche « Historique indisponible ».

## Interface

- La conversation est créée en base juste avant le premier envoi ; ensuite chaque tour l'enregistre.
- **Historique** : liste des conversations de l'agent, réouverture, renommage, suppression (avec confirmation).
- **Nouvelle conversation** : repart de zéro ; l'ancienne reste dans l'historique.
- Au premier passage sur un agent, sa dernière conversation est rouverte (mémorisée dans le navigateur, à titre de
  confort : si elle a été supprimée, on repart d'une conversation vide).
- Rouvrir une conversation remplace les artefacts de cet agent dans le panneau de droite par les siens.
- Une validation laissée en attente est restaurée telle quelle : on peut autoriser ou refuser plus tard.

Reconstruction de l'affichage : `fromStored()` dans `frontend/src/features/chat-agent/conversation.ts`
(testée dans `fromStored.test.ts`).

## Confidentialité

L'historique contient tout ce que les agents ont lu, y compris les données financières des agents verrouillés en local
(Finance, Comptable). La base reste sur la machine (SQLite) ou sur le PostgreSQL du docker-compose, lié à `127.0.0.1`.
Supprimer une conversation efface définitivement ses messages et ses artefacts.
