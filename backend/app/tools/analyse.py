"""Boîte à outils `analyse` : statistiques sur des jeux chargés depuis Viz, Tab ou un fichier.

Les jeux de travail vivent en mémoire du backend, rangés par conversation (`app/analysis/store.py`) :
un appel validé dans une nouvelle requête (`APPROVAL_MODE=every_step`) retrouve le jeu chargé
par l'appel précédent. Aucun outil n'écrit dans une application : le nettoyage produit une copie
en mémoire, la source n'est jamais modifiée.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analysis import analyses, loaders
from app.analysis.analyses import AggName, ChartKind, MeasureSpec, Period
from app.analysis.cleaning import CleaningError, Comparator, Operation, OpName, apply
from app.analysis.frame import TYPE_LABELS, ColumnError, Frame
from app.analysis.loaders import LoadError
from app.analysis.store import (
    FRAMES,
    NAME,
    FrameNotFoundError,
    FrameScopeError,
    FrameStore,
    frame_name,
    scope_of,
)
from app.tools.base import BaseTool, ToolContext, ToolInput, ToolOutput
from app.tools.data_via import DataViaError
from app.tools.environment import ToolEnvironment
from app.tools.formatting import markdown_table
from app.tools.http import AppError

FRAME_NAME = NAME.pattern
_NAME_FIELD = Field(
    pattern=FRAME_NAME, description="Nom du jeu de travail (donné par analyse_charger)."
)


class _AnalyseTool[InputT: ToolInput](BaseTool[InputT]):
    expected_errors: ClassVar[tuple[type[Exception], ...]] = (
        AppError, DataViaError, LoadError, ColumnError, CleaningError, FrameNotFoundError, FrameScopeError,
    )  # fmt: skip

    def __init__(self, env: ToolEnvironment, store: FrameStore | None = None) -> None:
        self.env = env
        self.store = store or FRAMES

    def scope(self, ctx: ToolContext) -> str:
        return scope_of(ctx.conversation_id, ctx.extras)

    def frame(self, ctx: ToolContext, name: str) -> Frame:
        return self.store.get(self.scope(ctx), name)

    def output(self, result: analyses.Result) -> ToolOutput:
        return ToolOutput(content=result.content, artifacts=result.artifacts)


# ─── Charger ──────────────────────────────────────────────────────


class LoadInput(ToolInput):
    source: Literal["viz", "tab", "fichier"] = Field(
        description="viz = jeu Atelier Viz ; tab = table Atelier Tab ; fichier = fichier joint (CSV, .xlsx, JSON)."
    )
    reference: str = Field(
        min_length=1,
        max_length=200,
        description="Identifiant du jeu Viz (data_via_list_datasets), de la table Tab (tab_list_tables) ou nom du fichier joint.",
    )
    nom: str | None = Field(
        default=None,
        pattern=FRAME_NAME,
        description="Nom court du jeu de travail (défaut : tiré de la source).",
    )
    feuille: str | None = Field(
        default=None, max_length=100, description="Feuille d'un classeur Excel."
    )
    max_lignes: int = Field(
        default=50_000, ge=10, le=200_000, description="Lignes chargées au plus."
    )


class LoadTool(_AnalyseTool[LoadInput]):
    name = "analyse_charger"
    description = (
        "Charge un jeu de données pour l'analyser : jeu Atelier Viz, table Atelier Tab ou fichier "
        "joint (CSV, Excel .xlsx, JSON). Lit toutes les lignes (jusqu'à max_lignes), type les "
        "colonnes (nombres au format français compris) et donne le schéma. À appeler avant tout "
        "autre outil analyse_*."
    )
    input_model = LoadInput

    def approval_summary(self, params: LoadInput) -> str:
        where = {
            "viz": "le jeu Atelier Viz",
            "tab": "la table Atelier Tab",
            "fichier": "le fichier",
        }
        return (
            f"Charger {where[params.source]} « {params.reference} » pour l'analyser (lecture seule)"
        )

    async def run(self, params: LoadInput, ctx: ToolContext) -> ToolOutput:
        scope = self.scope(ctx)  # refuse avant tout chargement hors conversation
        name = params.nom or frame_name(params.reference)
        if params.source == "viz":
            frame = await loaders.from_viz(
                self.env.data_via(), params.reference, name, params.max_lignes
            )
        elif params.source == "tab":
            frame = await loaders.from_tab(
                self.env.tab(), params.reference, name, params.max_lignes
            )
        else:
            frame = await loaders.from_file(
                self.env.conversation_files(),
                params.reference,
                name,
                params.max_lignes,
                params.feuille,
            )
        if not params.nom and params.source in ("viz", "tab") and frame_name(frame.label) != "jeu":
            frame.name = frame_name(frame.label)  # nom lisible plutôt que l'identifiant
        evicted = self.store.put(scope, frame)
        schema = ", ".join(f"{c.name} ({TYPE_LABELS[c.type]})" for c in frame.columns[:60])
        lines = [
            f"Jeu de travail « {frame.name} » chargé : {frame.rows} ligne(s), {len(frame.columns)} colonne(s).",
            f"Source : {frame.origin}.",
            f"Colonnes : {schema}{' …' if len(frame.columns) > 60 else ''}.",
        ]
        lines += [f"- {n}" for n in frame.notes]
        if evicted:
            lines.append(f"Jeux retirés de la mémoire (limite atteinte) : {', '.join(evicted)}.")
        lines.append(
            "Étape suivante conseillée : `analyse_profil` (qualité, types, distributions)."
        )
        return ToolOutput(content="\n".join(lines))


# ─── Lister ───────────────────────────────────────────────────────


class NoInput(ToolInput):
    pass


class ListFramesTool(_AnalyseTool[NoInput]):
    name = "analyse_jeux"
    description = (
        "Jeux de travail chargés dans cette conversation (nom, taille, origine, nettoyages)."
    )
    input_model = NoInput

    async def run(self, params: NoInput, ctx: ToolContext) -> ToolOutput:
        frames = self.store.list(self.scope(ctx))
        if not frames:
            return ToolOutput(content="Aucun jeu chargé : utilise `analyse_charger`.")
        rows = [[f.name, f.rows, len(f.columns), f.origin, len(f.recipe)] for f in frames]
        return ToolOutput(
            content=markdown_table(["Nom", "Lignes", "Colonnes", "Origine", "Nettoyages"], rows)
        )


# ─── Profil, distribution, corrélations, relation, aberrants ──────


class FrameInput(ToolInput):
    nom: str = _NAME_FIELD


class ProfileTool(_AnalyseTool[FrameInput]):
    name = "analyse_profil"
    description = (
        "Profil complet d'un jeu : par colonne type, remplissage, valeurs distinctes, moyenne, "
        "médiane, écart-type, quartiles, asymétrie, aplatissement ; points de qualité (doublons, "
        "lignes de total, nombres ou dates écrits en texte, variantes d'écriture, valeurs atypiques)."
    )
    input_model = FrameInput

    async def run(self, params: FrameInput, ctx: ToolContext) -> ToolOutput:
        return self.output(analyses.profile(self.frame(ctx, params.nom)))


class DistributionInput(ToolInput):
    nom: str = _NAME_FIELD
    colonne: str = Field(min_length=1, description="Colonne étudiée (nombre, date ou catégorie).")
    par: str | None = Field(
        default=None, description="Catégorie de regroupement (comparaison entre groupes)."
    )


class DistributionTool(_AnalyseTool[DistributionInput]):
    name = "analyse_distribution"
    description = (
        "Distribution d'une colonne. Nombre : quantiles, asymétrie (skewness) et aplatissement "
        "(kurtosis) avec leur lecture, test de normalité, valeurs atypiques, transformation "
        "suggérée, histogramme. Catégorie : effectifs et parts. Avec `par` : boîtes à moustaches "
        "par groupe et tests de comparaison (t de Welch / Mann-Whitney, ANOVA / Kruskal-Wallis)."
    )
    input_model = DistributionInput

    async def run(self, params: DistributionInput, ctx: ToolContext) -> ToolOutput:
        frame = self.frame(ctx, params.nom)
        return self.output(analyses.distribution(frame, params.colonne, params.par))


class CorrelationsInput(ToolInput):
    nom: str = _NAME_FIELD
    colonnes: list[str] | None = Field(
        default=None,
        max_length=30,
        description="Colonnes numériques (défaut : toutes les colonnes de nombres).",
    )
    methode: Literal["pearson", "spearman", "les_deux"] = Field(
        default="les_deux",
        description="pearson = linéaire ; spearman = monotone, robuste aux valeurs extrêmes ; les_deux = comparer.",
    )
    cible: str | None = Field(
        default=None, description="Ne calculer que les corrélations avec cette colonne."
    )


class CorrelationsTool(_AnalyseTool[CorrelationsInput]):
    name = "analyse_correlations"
    description = (
        "Matrice de corrélation (Pearson et/ou Spearman) entre colonnes numériques : paires les plus "
        "liées, force, valeurs p corrigées des comparaisons multiples (Holm), alertes de "
        "non-linéarité ; carte de chaleur dans le panneau Artefacts."
    )
    input_model = CorrelationsInput

    async def run(self, params: CorrelationsInput, ctx: ToolContext) -> ToolOutput:
        frame = self.frame(ctx, params.nom)
        return self.output(
            analyses.correlations(frame, params.colonnes, params.methode, params.cible)
        )


class RelationInput(ToolInput):
    nom: str = _NAME_FIELD
    x: str = Field(min_length=1, description="Première colonne (variable explicative, ou date).")
    y: str = Field(min_length=1, description="Seconde colonne (variable étudiée).")


class RelationTool(_AnalyseTool[RelationInput]):
    name = "analyse_relation"
    description = (
        "Relation entre deux colonnes, test adapté aux types : deux nombres → Pearson, Spearman, "
        "droite de régression et nuage de points ; nombre et catégorie → comparaison des groupes ; "
        "deux catégories → tableau croisé, khi², V de Cramér ; date et nombre → évolution et tendance."
    )
    input_model = RelationInput

    async def run(self, params: RelationInput, ctx: ToolContext) -> ToolOutput:
        return self.output(analyses.relation(self.frame(ctx, params.nom), params.x, params.y))


class OutliersInput(ToolInput):
    nom: str = _NAME_FIELD
    colonnes: list[str] | None = Field(
        default=None, max_length=30, description="Défaut : toutes les colonnes de nombres."
    )
    methode: Literal["iqr", "mad"] = Field(
        default="iqr",
        description="iqr = moustaches de Tukey ; mad = score z robuste (médiane, MAD).",
    )


class OutliersTool(_AnalyseTool[OutliersInput]):
    name = "analyse_aberrants"
    description = (
        "Valeurs atypiques des colonnes numériques (règle de Tukey ou score z robuste) : nombre, "
        "bornes, valeurs les plus extrêmes ; lignes concernées dans le panneau Artefacts."
    )
    input_model = OutliersInput

    async def run(self, params: OutliersInput, ctx: ToolContext) -> ToolOutput:
        frame = self.frame(ctx, params.nom)
        return self.output(analyses.outliers(frame, params.colonnes, params.methode))


# ─── Nettoyer ─────────────────────────────────────────────────────


class OperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: OpName = Field(
        description=(
            "supprimer_doublons (colonne = clé, facultative) · supprimer_lignes_vides · "
            "supprimer_totaux · nettoyer_texte (espaces, « N/A ») · casse (valeur : titre, "
            "majuscules, minuscules) · convertir (valeur : nombre, date, booleen, texte) · remplir "
            "(valeur : mediane, moyenne, mode, zero, precedente ou valeur fixe) · supprimer_manquants · "
            "plafonner (valeur : iqr, p1-p99, p5-p95) · supprimer_aberrants (valeur : iqr, mad) · "
            "log (nouvelle_colonne facultative) · filtrer (comparateur + valeur) · supprimer_colonne · "
            "renommer (valeur = nouveau nom)."
        )
    )
    colonne: str | None = Field(default=None, description="Colonne visée (selon l'opération).")
    valeur: str | None = Field(default=None, description="Paramètre de l'opération (voir op).")
    comparateur: Comparator | None = Field(
        default=None,
        description="Pour filtrer : =, !=, >, >=, <, <=, contient, ne_contient_pas, vide, non_vide.",
    )
    nouvelle_colonne: str | None = Field(
        default=None, description="Pour log : nom de la colonne créée."
    )


class CleanInput(ToolInput):
    nom: str = _NAME_FIELD
    operations: list[OperationInput] = Field(
        min_length=1, max_length=30, description="Opérations, appliquées dans l'ordre."
    )
    nouveau_nom: str | None = Field(
        default=None,
        pattern=FRAME_NAME,
        description="Nom du jeu nettoyé (défaut : <nom>_propre). La source reste intacte.",
    )


class CleanTool(_AnalyseTool[CleanInput]):
    name = "analyse_nettoyer"
    description = (
        "Nettoie une COPIE d'un jeu de travail (la source n'est jamais modifiée) : doublons, lignes "
        "vides ou de total, espaces et casse, conversions de type, valeurs manquantes, valeurs "
        "aberrantes (plafonnement ou suppression), logarithme, filtres, colonnes. Rend le bilan "
        "avant / après et la recette rejouable."
    )
    input_model = CleanInput

    def approval_summary(self, params: CleanInput) -> str:
        ops = ", ".join(
            o.op + (f" ({o.colonne})" if o.colonne else "") for o in params.operations[:6]
        )
        more = f" (+{len(params.operations) - 6})" if len(params.operations) > 6 else ""
        target = params.nouveau_nom or f"{params.nom}_propre"
        return (
            f"Nettoyer une copie de « {params.nom} » → « {target} » : {ops}{more} (source intacte)"
        )

    async def run(self, params: CleanInput, ctx: ToolContext) -> ToolOutput:
        source = self.frame(ctx, params.nom)
        target = _clean_target(params.nom, params.nouveau_nom)
        frame = source.copy(target)
        before_rows, before_missing = frame.rows, _missing(frame)
        effects = apply(frame, [Operation(**o.model_dump()) for o in params.operations])
        evicted = self.store.put(self.scope(ctx), frame)
        lines = [
            f"Jeu « {frame.name} » créé à partir de « {source.name} » (source intacte) :",
            *[f"{i}. {e}" for i, e in enumerate(effects, start=1)],
            f"Avant : {before_rows} ligne(s), {before_missing} cellule(s) vide(s). "
            f"Après : {frame.rows} ligne(s), {len(frame.columns)} colonne(s), {_missing(frame)} cellule(s) vide(s).",
        ]
        if before_rows and frame.rows < 0.9 * before_rows:
            lines.append(
                f"Attention : {before_rows - frame.rows} ligne(s) retirée(s) "
                f"({100 * (before_rows - frame.rows) / before_rows:.0f} %) — vérifier que c'est voulu."
            )
        if evicted:
            lines.append(f"Jeux retirés de la mémoire (limite atteinte) : {', '.join(evicted)}.")
        lines.append(
            "Analyse ensuite le jeu nettoyé par son nom ; `analyse_exporter` pour le télécharger."
        )
        return ToolOutput(content="\n".join(lines))


def _clean_target(source: str, wanted: str | None) -> str:
    """Nom du jeu nettoyé : jamais celui de la source (elle reste intacte)."""
    if wanted is not None:
        if wanted == source:
            raise CleaningError("`nouveau_nom` doit différer de `nom` : la source reste intacte.")
        return wanted
    base = source[:-7] if source.endswith("_propre") else source
    candidate = f"{base[:33]}_propre"
    return candidate if candidate != source else f"{base[:32]}_propre2"


def _missing(frame: Frame) -> int:
    return sum(1 for c in frame.columns for v in c.values if v is None)


# ─── Agréger, graphique, exporter ─────────────────────────────────


class MeasureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fonction: AggName = Field(
        description="nombre, somme, moyenne, mediane, ecart_type, min, max, distinct, p25, p75."
    )
    colonne: str | None = Field(
        default=None, description="Colonne mesurée (sans colonne : nombre de lignes)."
    )


class AggregateInput(ToolInput):
    nom: str = _NAME_FIELD
    par: list[str] = Field(
        default_factory=list, max_length=3, description="Colonnes de regroupement (vide = total)."
    )
    mesures: list[MeasureInput] = Field(
        min_length=1, max_length=10, description="Mesures calculées par groupe."
    )
    periode: Period | None = Field(
        default=None,
        description="Pour une colonne date de `par` : annee, trimestre, mois, semaine, jour.",
    )
    tri: str | None = Field(default=None, description="Clé de tri, ex. « somme(montant) ».")
    decroissant: bool = Field(default=True, description="Tri décroissant (défaut) ou croissant.")
    limite: int = Field(default=500, ge=1, le=5000, description="Nombre maximal de groupes rendus.")


class AggregateTool(_AnalyseTool[AggregateInput]):
    name = "analyse_agreger"
    description = (
        "Regroupe un jeu de travail (y compris nettoyé) et calcule des mesures par groupe : nombre, "
        "somme, moyenne, médiane, écart-type, min, max, distinct, quartiles ; dates par période."
    )
    input_model = AggregateInput

    async def run(self, params: AggregateInput, ctx: ToolContext) -> ToolOutput:
        frame = self.frame(ctx, params.nom)
        measures = [MeasureSpec(m.fonction, m.colonne) for m in params.mesures]
        return self.output(
            analyses.aggregate(
                frame,
                params.par,
                measures,
                params.periode,
                params.tri,
                params.decroissant,
                params.limite,
            )
        )


class ChartInput(ToolInput):
    nom: str = _NAME_FIELD
    type: ChartKind = Field(description="histogramme, boite, nuage, barres ou courbe.")
    x: str | None = Field(default=None, description="Axe horizontal (catégorie, date ou nombre).")
    y: str | None = Field(default=None, description="Valeur mesurée (nombre).")
    agregation: AggName | None = Field(
        default=None,
        description="Barres / courbe : somme (défaut avec y), nombre (défaut sans y), moyenne…",
    )
    groupe: str | None = Field(
        default=None, description="Catégorie : une série ou une couleur par modalité."
    )
    periode: Period | None = Field(
        default=None, description="Courbe sur une date : annee, trimestre, mois, semaine, jour."
    )
    titre: str | None = Field(
        default=None, max_length=120, description="Titre qui dit ce que montre le graphique."
    )


class ChartTool(_AnalyseTool[ChartInput]):
    name = "analyse_graphique"
    description = (
        "Publie un graphique dans le panneau Artefacts à partir d'un jeu de travail : histogramme, "
        "boîte à moustaches (par groupe), nuage de points (avec droite de tendance), barres ou courbe "
        "(valeur agrégée par catégorie ou par période, une série par groupe)."
    )
    input_model = ChartInput

    async def run(self, params: ChartInput, ctx: ToolContext) -> ToolOutput:
        frame = self.frame(ctx, params.nom)
        return self.output(
            analyses.chart(
                frame,
                params.type,
                params.x,
                params.y,
                params.agregation,
                params.groupe,
                params.periode,
                params.titre,
            )  # fmt: skip
        )


class ExportInput(ToolInput):
    nom: str = _NAME_FIELD
    max_lignes: int = Field(default=10_000, ge=1, le=50_000, description="Lignes publiées au plus.")


class ExportTool(_AnalyseTool[ExportInput]):
    name = "analyse_exporter"
    description = (
        "Publie un jeu de travail (par exemple nettoyé) dans le panneau Artefacts, téléchargeable "
        "en CSV par l'utilisateur, avec sa recette de nettoyage."
    )
    input_model = ExportInput

    async def run(self, params: ExportInput, ctx: ToolContext) -> ToolOutput:
        return self.output(analyses.export(self.frame(ctx, params.nom), params.max_lignes))


def analyse_tools(env: ToolEnvironment, store: FrameStore | None = None) -> list[BaseTool[Any]]:
    return [
        LoadTool(env, store),
        ListFramesTool(env, store),
        ProfileTool(env, store),
        DistributionTool(env, store),
        CorrelationsTool(env, store),
        RelationTool(env, store),
        OutliersTool(env, store),
        CleanTool(env, store),
        AggregateTool(env, store),
        ChartTool(env, store),
        ExportTool(env, store),
    ]
