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
(choix de l'utilisateur). La synthèse (`formulaire_summary`) ne garde que des agrégats — effectifs par
choix, minimum, moyenne, maximum, distribution d'une échelle — et retire les derniers textes libres que
renvoie Formulaire : elle peut être lue par un agent sur Claude et recopiée dans le Wiki.

## Création d'un formulaire

Questions : `short_text`, `long_text`, `email`, `number`, `date`, `single`, `multiple`, `dropdown`,
`scale`, `yes_no`, `section` (`domain/questions.ts`). Nexus attribue les identifiants `q1`, `q2`… Un
formulaire créé est **en préparation** : il n'accepte des réponses qu'une fois ouvert
(`formulaire_set_status`). Un accès `public` ouvre le lien à toute personne qui l'a : la carte de
validation le dit en capitales.

## Vérifier

```bash
cd backend && pytest tests/test_wiki_formulaire.py
cd Atelier_Formulaire && npm run build && npm start   # port 3300
```
