# Analyse statistique — agent Data Analyst (étape 25)

Un seul agent pour les données : **Data Analyst** (`data_analyst`, catégorie Données). Il récupère
les données (Atelier Viz, Atelier Tab, fichiers joints), les nettoie, mesure leurs distributions,
leurs liens et leurs valeurs atypiques, publie les graphiques et garde son expertise Power BI / DAX.
Les statistiques sont calculées par la boîte **`analyse`**, jamais « de tête » par le modèle.

## 1. Outils de la boîte `analyse`

| Outil | Rôle | Artefacts |
|---|---|---|
| `analyse_charger` | Charge un jeu Viz (`source=viz`, toutes les lignes par pages de 1 000), une table Tab (`tab`, lignes de total exclues) ou un fichier joint (`fichier` : CSV, TSV, `.xlsx`, JSON). Colonnes typées. | — |
| `analyse_jeux` | Jeux de travail chargés dans la conversation. | — |
| `analyse_profil` | Par colonne : type, remplissage, distinctes, moyenne, écart-type, quartiles, asymétrie, aplatissement. Points de qualité : doublons, lignes de total, nombres ou dates écrits en texte, variantes d'écriture, colonnes constantes ou identifiants, valeurs atypiques. | `data_preview` (profil, aperçu) |
| `analyse_distribution` | Nombre : centre, dispersion, quantiles, asymétrie G1, aplatissement G2 et leur lecture, normalité, atypiques, transformation conseillée. Catégorie : effectifs et parts. Avec `par` : comparaison de groupes. | `chart` (histogramme, barres ou boîtes) |
| `analyse_correlations` | Pearson et / ou Spearman entre colonnes numériques (30 au plus), valeurs p corrigées de Holm, alerte quand Pearson et Spearman divergent (non-linéarité, valeurs extrêmes). `cible` : seulement les liens avec une colonne. | `chart` (carte de chaleur), `data_preview` |
| `analyse_relation` | Deux colonnes, test adapté : nombre × nombre (Pearson, Spearman, droite, R², nuage) ; nombre × catégorie (t de Welch et Mann-Whitney, ou ANOVA et Kruskal-Wallis, tailles d'effet) ; catégorie × catégorie (khi², V de Cramér, tableau croisé) ; date × nombre (évolution par période, tendance). | `chart`, `data_preview` |
| `analyse_aberrants` | Règle de Tukey (1,5 et 3 × EIQ) ou score z robuste (médiane, MAD, seuil 3,5) ; lignes concernées. | `data_preview`, `chart` (une colonne) |
| `analyse_nettoyer` | Opérations sur une **copie** (la source reste intacte) : `supprimer_doublons`, `supprimer_lignes_vides`, `supprimer_totaux`, `nettoyer_texte`, `casse`, `convertir`, `remplir`, `supprimer_manquants`, `plafonner`, `supprimer_aberrants`, `log`, `filtrer`, `supprimer_colonne`, `renommer`. Bilan avant / après, recette rejouable. | — |
| `analyse_agreger` | Regroupement (3 colonnes au plus, dates par période) et mesures : nombre, somme, moyenne, médiane, écart-type, min, max, distinct, quartiles. | `data_preview` |
| `analyse_graphique` | Histogramme, boîte à moustaches, nuage de points (tendance), barres ou courbe (une série par groupe). | `chart` |
| `analyse_exporter` | Jeu de travail (nettoyé) téléchargeable en CSV, avec sa recette. | `data_preview` |

Aucun outil n'écrit dans une application : la boîte n'a pas d'outil `requires_approval`. En
`APPROVAL_MODE=every_step`, chaque appel est tout de même présenté à l'utilisateur.

## 2. Méthodes (vérifiées contre SciPy et pandas)

Calculs en Python pur (`backend/app/analysis/`), sans dépendance numérique : l'app de bureau et
l'installation Windows ne grossissent pas. `tests/test_analyse.py` compare chaque statistique aux
valeurs de SciPy 1.16 / pandas 2.3.

| Mesure | Convention |
|---|---|
| Écart-type, variance | échantillon (ddof = 1) |
| Quantiles | interpolation linéaire (type 7, défaut de pandas) |
| Asymétrie, aplatissement | G1 et G2 corrigés du biais (`Series.skew()`, `Series.kurt()`, excès : 0 pour une loi normale) |
| Normalité | K² de D'Agostino-Pearson (`scipy.stats.normaltest`), à partir de 20 valeurs |
| Corrélations | Pearson ; Spearman = Pearson sur les rangs moyens ; p par la loi t (n − 2 ddl) ; Holm |
| Groupes | t de Welch, U de Mann-Whitney (approximation normale, ex aequo, continuité), ANOVA (η²), Kruskal-Wallis (ε², ex aequo) |
| Catégories | khi² sans correction de Yates, V de Cramér, part d'effectifs attendus < 5 |
| Histogramme | classes de Freedman-Diaconis (Sturges si EIQ nul), une classe par valeur pour des entiers peu nombreux |

Lecture donnée au modèle : |G1| < 0,5 quasi symétrique, < 1 modérée, sinon forte ; |r| < 0,1
négligeable, < 0,3 faible, < 0,5 modérée, < 0,7 forte, sinon très forte ; seuils d'effet usuels
(d de Cohen 0,2 / 0,5 / 0,8 ; η² et ε² 0,01 / 0,06 / 0,14).

## 3. Fichiers : formats français

- Nombres : « 1 234,56 », « 1.234,56 € », « 12,5 % » (gardé à 12,5), « (1 000,00) » (négatif
  comptable), puis formats anglais (« 1,234.56 ») ; « 1.234 » seul est lu 1,234.
- Dates : `AAAA-MM-JJ` (avec heure), `JJ/MM/AAAA`, `JJ-MM-AA`, `JJ.MM.AAAA`, cellules date d'Excel.
- Oui / non : oui, non, vrai, faux, true, false, x ; une colonne 0 / 1 reste numérique.
- Vides : cellule vide, N/A, NA, -, —, null, #N/A, #DIV/0!…
- Une colonne prend un type si au moins 95 % de ses valeurs s'y lisent ; les autres sont mises à
  vide et signalées au chargement (« 3 valeur(s) illisible(s) mise(s) à vide »).
- Lignes de titre au-dessus de l'en-tête ignorées ; lignes « Total », « Sous-total »,
  « Total général » exclues (elles fausseraient tous les calculs).
- PDF, `.xls`, OFX, QIF : à convertir d'abord (Atelier Convert par l'extension Agent_DatAnalyst,
  ou export CSV / `.xlsx`).

## 4. Jeux de travail en mémoire

En `every_step`, chaque appel validé arrive dans une nouvelle requête : l'état de tour
(`ToolContext.state`) est perdu. Les jeux chargés vivent donc dans le processus du backend
(`app/analysis/store.py`), rangés par `conversation_id` : 8 jeux au plus par conversation,
32 conversations, oubli après 6 h sans usage, 3 millions de cellules au plus par jeu. Une
conversation ne voit jamais les jeux d'une autre. Rien n'est écrit sur disque : après un
redémarrage de Nexus, l'outil le dit et l'agent recharge la source.

## 5. Graphiques (artefact `chart`)

Format `atelier-chart/1` (`backend/app/analysis/charts.py`), dessiné en SVG par
`frontend/src/features/artifacts/charts/` avec les jetons du design system : `histogram`
(repères moyenne et médiane), `box`, `scatter` (2 000 points au plus, échantillon régulier ;
droite de tendance), `bar`, `line`, `heatmap` (corrélations : négatif en couleur secondaire, positif en couleur signature).
La spécification ne contient que des nombres déjà calculés. Le bouton Télécharger exporte les
données du graphique en CSV. `publish_artifact` n'accepte pas `chart` : le modèle n'écrit jamais
de graphique à la main.

## 6. Extensions

Une extension complète l'agent par `extend_agent` (`docs/extensions.md`) : Agent_DatAnalyst lui
ajoute Convert, les écritures Viz (import, rapports), Tab et le plan Projets, avec leurs recettes.

## 7. Vérifier

```bash
cd backend && pytest tests/test_analyse.py     # statistiques vs SciPy, chargements, nettoyage, every_step
cd frontend && npx vitest run src/features/artifacts
cd backend && python -m scripts.evals --tag analyse   # cas data-correlations, data-asymetrie, data-comparaison-regions
```
