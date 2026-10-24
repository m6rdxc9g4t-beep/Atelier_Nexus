# Connecteur Atelier Formulaire

Atelier Formulaire (dépôt `Atelier_Formulaire`) : sondages, inscriptions, retours ; réponses rangées par
question. Nexus s'y branche par son nœud **`atelier-node/1`** (garde-fous de `docs/apps/noeuds.md`) et par
trois routes de l'interface pour créer et ouvrir un formulaire.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `FORMULAIRE_BASE_URL` | `http://127.0.0.1:3300/api` | API de Formulaire ; vide = désactivé |

## Routes utilisées (lues dans le dépôt)

| Action / route | Outil | Boîte |
|---|---|---|
| `forms.list` — GET /api/atelier/forms | `formulaire_forms` | `formulaire` |
| `forms.get` — GET /api/atelier/forms/{form_id} | `formulaire_form` | `formulaire` |
| GET /api/forms/{id}/summary (`routes/forms.ts`) | `formulaire_summary` (agrégats seulement) | `formulaire` |
| POST /api/forms — {title, description, questions} | `formulaire_create_form` ✅ validation | `formulaire_write` |
| POST /api/forms/{id}/status — {status} | `formulaire_set_status` ✅ validation | `formulaire_write` |
| POST /api/forms/{id}/access — {access} | `formulaire_set_access` ✅ validation | `formulaire_write` |
| `responses.list` — GET /api/atelier/forms/{form_id}/responses | `formulaire_responses` | `formulaire_reponses` **sensible** |

`responses.submit` (envoyer une réponse à la place d'une personne) n'est volontairement pas exposé aux agents.

## Confidentialité

Les réponses individuelles (nom du répondant, e-mails, textes libres) sont des **données personnelles** :
la boîte `formulaire_reponses` est `sensitive`, l'agent qui l'utilise tourne uniquement sur le modèle local
(choix de l'utilisateur). Le seul agent fourni qui l'a, Enquêtes, n'a **aucune écriture** vers ce que
lisent les agents sur Claude : le cœur retire les boîtes `shared` (mémoire d'équipe, Wiki) de tout agent
verrouillé sur le modèle local, fourni, étendu ou créé dans l'interface.

`formulaire_responses` lit les réponses **les plus récentes d'abord**. Formulaire les rend de la plus
ancienne à la plus récente, par pages de 5 000 au plus : Nexus avance de page en page (`since_id`,
100 000 réponses au plus) et garde la fin. Chaque réponse est montrée en entier (jusqu'à 2 000 caractères
par réponse libre) dans un budget de 40 000 caractères : on montre moins de réponses plutôt que d'en
couper une, et `avant_id` désigne exactement la suivante à lire.

La synthèse (`formulaire_summary`, `equipe_synthese_formulaires`) ne garde que des agrégats — effectifs
par choix, minimum, moyenne, maximum, distribution d'une échelle — et retire les derniers textes libres
que renvoie Formulaire. Une question n'est montrée que par son nombre de réponses en dessous de
**3 réponses** pour un choix, **5** pour un nombre ou une échelle (moyenne, minimum, maximum et
distribution permettent de reconstituer chaque valeur d'un petit groupe). Elle peut alors être lue par
un agent sur Claude et notée dans le Wiki. Limite connue : le rituel du vendredi note chaque semaine un
agrégat **cumulé** ; la différence entre deux semaines peut isoler une réponse arrivée seule entre les
deux. Pour un formulaire très sensible, ne pas installer ce rituel ou le désactiver.

**À savoir.** Formulaire publie aussi ses réponses comme jeu de données pour Atelier Viz
(`/api/exports/datasets/form-N`, colonne `repondant` comprise). Brancher ce jeu dans Viz le rend lisible
par le Data Analyst, qui tourne sur Claude : ne le faire que pour des formulaires anonymes. De même,
l'action `responses.list` reste disponible aux workflows v2 ([`noeuds.md`](noeuds.md)).

## Création d'un formulaire

Questions : `short_text`, `long_text`, `email`, `number`, `date`, `single`, `multiple`, `dropdown`,
`scale`, `yes_no`, `section` (`domain/questions.ts`). Nexus attribue les identifiants `q1`, `q2`… Un
formulaire créé est **en préparation** : il n'accepte des réponses qu'une fois ouvert
(`formulaire_set_status`). Un accès `public` ouvre le lien à toute personne qui l'a : la carte de
validation le dit en capitales. `POST /api/forms` n'accepte pas de clé d'idempotence : une
création validée deux fois crée deux formulaires (le second se supprime dans Formulaire).

## Vérifier

```bash
cd backend && pytest tests/test_wiki_formulaire.py
cd Atelier_Formulaire && npm run build && npm start   # port 3300
```
