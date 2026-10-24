# Évaluations des agents — Étape 17

Les 217 tests de Nexus vérifient le **code** (outils, routeur, API). Ils ne disent pas si un
agent répond **bien** avec un modèle donné : un petit modèle Ollama peut sauter l'exploration du
schéma, inventer un chiffre ou oublier de publier sa mesure DAX. Les évaluations rejouent des
demandes réelles et contrôlent le résultat, pour comparer deux modèles ou vérifier qu'un
changement de prompt n'a rien cassé.

```
backend/evals/
├── cases/*.toml      # les cas : une demande + ce qui doit être vrai à la fin
├── simulation.py     # Data Via, Projets, Trésorerie simulés (résultats reproductibles)
├── checks.py         # contrôles déterministes de l'état final
├── runner.py         # un tour d'agent réel (BaseAgent + LLMRouter), juge facultatif
├── report.py         # rapport Markdown + JSON, comparaison avec la campagne précédente
└── resultats/        # rapports (non versionnés)
backend/scripts/evals.py   # ligne de commande
```

## 1. Lancer

```bash
cd backend
python -m scripts.evals --liste                                   # 22 cas
python -m scripts.evals --provider ollama --repeat 3              # tout, 3 essais par cas
python -m scripts.evals --agent data_analyst --model qwen2.5:14b  # un agent, un autre modèle
python -m scripts.evals --tag validation                          # par étiquette
python -m scripts.evals --cas data-mesure-dax --juge              # avec un modèle juge
```

Depuis l'application de bureau (mêmes moteurs et adresses que Nexus) :

```bash
cd ~/dev/Atelier_Nexus/backend
.venv/bin/python -m scripts.evals --env-file "$HOME/Library/Application Support/Atelier Nexus/.env"
```

| Option | Rôle |
|---|---|
| `--provider`, `--model` | Moteur évalué (sinon le moteur par défaut). Les agents « 100 % local » restent sur Ollama, quoi qu'on demande. |
| `--repeat N` | N essais par cas : un cas réussi 2 fois sur 3 est **instable**, signal typique d'un petit modèle. |
| `--juge`, `--juge-provider`, `--juge-model` | Fait juger le critère (`rubric`) de chaque cas par un modèle. Pour un agent local, le juge est forcé sur Ollama. |
| `--apps simulees` (défaut) / `reelles` | Applications simulées, ou celles configurées et lancées sur la machine. |
| `--env-file` | `.env` à utiliser (moteurs, adresses des apps). |
| `--comparer FICHIER.json` | Référence de comparaison (défaut : le rapport le plus récent du dossier). |
| `--timeout` | Délai d'un tour (300 s par défaut). |

Code de sortie : 0 si tous les cas joués réussissent tous leurs essais, 1 sinon.

## 2. Garanties

- **Même chemin que l'interface** : `AgentCatalog` → `BaseAgent.run_stream` → `LLMRouter`,
  avec les vrais outils et leurs garde-fous (exploration préalable de Data Via, validations,
  verrou local). Rien n'est réimplémenté pour l'évaluation.
- **Aucune écriture** : aucune validation n'est donnée ; l'agent s'arrête sur « en attente de
  validation » et le cas vérifie justement que la validation a été demandée. Les applications
  simulées tournent en `APPROVAL_MODE=writes_only` (`simulated_settings`) : les lectures simulées
  s'exécutent pour suivre tout le raisonnement du modèle ; l'interface, elle, valide chaque action
  par défaut ([`settings.md`](settings.md)).
- **Confidentialité** : un agent local (Finance, Comptable, Trésorier) ne parle qu'à Ollama, et
  son juge aussi. Demander `--juge-provider anthropic` pour lui donne un avertissement, pas un appel.
- **Reproductible** en mode simulé : jeu de ventes généré avec une graine fixe (240 ventes,
  5 régions, 3 produits, janvier à septembre 2026, mesure `marge`), réponses réelles
  enregistrées de Projets et Trésorerie. Les chiffres sont exacts : on peut vérifier qu'ils sont
  repris, pas inventés.

## 3. Écrire un cas

```toml
[[case]]
id = "data-schema-avant-requete"        # minuscules, chiffres, tirets
agent = "data_analyst"
apps = ["data_via"]                     # ignoré si l'application manque
tags = ["donnees", "regle-claude-md"]
prompt = "Quel est le chiffre d'affaires total par région ?"
rubric = "La réponse donne le CA de chaque région et nomme la région en tête (Île-de-France)."

[case.expect]
tools_in_order = ["data_via_describe_dataset", "data_via_query"]
tool_args = [{ tool = "data_via_query", contains = ["region", "chiffre_affaires"] }]
artifacts = [{ kind = "data_preview" }]
text_contains = ["Ile-de-France"]
grounded_numbers = "warn"
```

| Attente | Vérifie |
|---|---|
| `stop_reason` | Raisons d'arrêt acceptées (défaut `end_turn` ; `awaiting_approval` pour une écriture). |
| `tools_called`, `tools_in_order`, `tools_forbidden` | Outils appelés, dans l'ordre (sous-séquence), ou interdits. Un appel en attente de validation compte comme appelé. |
| `tool_args` | Un appel de l'outil dont l'entrée JSON contient ces textes. |
| `tool_errors_max` | Nombre maximal d'appels en erreur. |
| `approval_requested` | Outils en attente de validation à la fin du tour. |
| `artifacts` | Un artefact correspond : `kind`, `title_contains`, `content_contains`, `content_regex`. |
| `text_contains`, `text_contains_any`, `text_not_contains`, `text_regex` | Réponse finale, sans accents ni casse. |
| `output_contains_any` | Un de ces textes dans la réponse **ou** dans un artefact (un livrable court peut rester dans le chat). |
| `grounded_numbers` | `warn` ou `strict` : chaque nombre de la réponse se retrouve dans les résultats d'outils, les artefacts ou la demande (à 1 % près, milliers, millions et pourcentages compris ; petits entiers et années ignorés). |
| `provider` | Moteur effectivement utilisé (`ollama` pour un agent local). |
| `max_iterations` | Nombre d'étapes maximal. |
| `error_code` | Le tour doit échouer avec ce code (ex. `provider_not_allowed`). |

Règles : évaluer l'**état final** (deux chemins vers le bon résultat sont justes) ; des attentes
qu'un humain validerait sans hésiter ; un critère `rubric` pour la qualité que les contrôles ne
voient pas. Le test `tests/test_evals.py` vérifie que chaque cas cite un agent et des outils qui
existent.

## 4. Lire le rapport

`evals/resultats/<date>_<moteur>.md` : un tableau par cas (✅ fiable, ⚠️ instable, ❌ en
échec, « ignoré »), puis les **régressions** et progrès par rapport à la campagne précédente,
puis le détail de chaque écart (contrôles en échec, outils appelés, extrait de la réponse).
Les avertissements (`⚠️ chiffres sourcés`) ne font pas échouer un cas : ils signalent un chiffre
à vérifier (un total recalculé par le modèle, par exemple).

Le `.json` voisin garde tout (réponses, outils, jetons, durées) pour les comparaisons.

## 5. Routine

- Après un changement de prompt, d'outil ou de modèle : `--repeat 3` sur les agents touchés.
- Avant de changer le modèle Ollama par défaut : campagne complète sur l'ancien puis le nouveau,
  et lecture de la section « Par rapport au … ».
- Un comportement fautif constaté dans l'interface devient un cas (puis une règle de prompt).

## 6. Première campagne (21/10/2026, Claude par l'abonnement, sonnet, juge activé)

21 cas joués en mode simulé (le cas GitHub est ignoré : application non simulée ; Finance et
Comptable demandent Ollama, absent de la machine de test, et sont ignorés comme « moteur
indisponible »). Ce qu'elle a appris :

- Data Analyst : exploration préalable respectée partout, DAX avec `VAR … RETURN` et
  `DIVIDE`, colonne absente signalée sans chiffre inventé.
- Rédacteur : le juge relève des ajouts non demandés (un rédacteur nommé, un point ouvert
  inventé) : piste d'amélioration du prompt.
- Deux cas mal écrits corrigés : une story désignée de façon ambiguë (l'agent a eu raison de
  demander laquelle), un e-mail attendu dans le chat alors qu'il est publié en artefact
  (d'où `output_contains_any`).
- Les avertissements « chiffres sourcés » restants portent sur des variations d'un mois à
  l'autre, calculées par le modèle : à relire, pas à compter comme des erreurs.
