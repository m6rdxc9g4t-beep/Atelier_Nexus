"""Boîte `analyse` : statistiques (comparées à SciPy / pandas), typage des fichiers français,
chargement depuis Viz / Tab / fichier joint, nettoyage, magasin de jeux, outils et agent Data.

Valeurs de référence calculées avec SciPy 1.16 et pandas 2.3 sur les mêmes listes.
"""

from __future__ import annotations

import io
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.analysis import analyses, cleaning, stats
from app.analysis.cleaning import CleaningError, Operation
from app.analysis.frame import (
    ColumnError,
    frame_from_rows,
    infer_column,
    is_total_row,
    parse_date,
    parse_number,
)
from app.analysis.store import MAX_FRAMES, FrameNotFoundError, FrameStore, frame_name
from app.core.config import Settings
from app.schemas.attachments import AttachmentInfo
from app.tools.analyse import analyse_tools
from app.tools.base import ToolContext
from app.tools.environment import ToolEnvironment
from app.tools.files import ConversationFiles

FIX = Path(__file__).parent / "fixtures"

X = [2.1, 3.4, 1.9, 8.7, 4.4, 3.3, 2.8, 15.2, 3.9, 4.1, 2.2, 3.0, 5.6, 2.9, 3.1, 4.8, 2.5, 3.6,
     7.9, 3.2, 2.7, 4.0, 3.5, 6.1, 2.4]  # fmt: skip
Y = [1.0, 1.9, 0.8, 4.1, 2.5, 1.4, 1.2, 6.9, 2.2, 2.6, 0.9, 1.6, 2.4, 1.5, 1.3, 2.0, 1.1, 1.8,
     3.9, 1.7, 1.4, 2.1, 1.6, 2.9, 1.0]  # fmt: skip


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


# ═══ Statistiques ════════════════════════════════════════════════


def test_moments_match_pandas() -> None:
    assert close(stats.skewness(X), 2.741151981245986)
    assert close(stats.kurtosis(X), 8.928950691434094)
    s = sorted(X)
    assert stats.quantile(s, 0.25) == pytest.approx(2.8) and stats.quantile(
        s, 0.5
    ) == pytest.approx(3.4)


def test_normality_matches_scipy_normaltest() -> None:
    n = stats.normality_test(X)
    assert n is not None
    assert close(n.statistic, 33.31468743037948) and close(n.p_value, 5.831866064154147e-08, 1e-6)
    assert stats.normality_test(X[:10]) is None  # moins de 20 valeurs


def test_correlations_match_scipy() -> None:
    p = stats.pearson(X, Y)
    assert close(p.r, 0.9847499488583332) and close(p.p_value, 5.671880006966363e-19, 1e-6)
    s = stats.spearman(X, Y)
    assert close(s.r, 0.9647875380785685) and close(s.p_value, 7.77643630799794e-15, 1e-6)
    reg = stats.linear_regression(X, Y)
    assert reg is not None
    assert close(reg.slope, 0.4574856221535188) and close(reg.intercept, 0.10847170971709708)
    assert close(reg.r2, 0.9697324617764896)
    assert math.isnan(stats.pearson([1, 1, 1], [1, 2, 3]).r)  # variance nulle


def test_group_tests_match_scipy() -> None:
    a, b = X[:12], X[12:]
    t = stats.welch_t(a, b)
    assert t is not None and close(t.statistic, 0.47250985270084656)
    assert close(t.p_value, 0.6434848625957692, 1e-7)
    u = stats.mann_whitney(a, b)
    assert u is not None and u.statistic == 71.0 and close(u.p_value, 0.7236736098317631, 1e-9)
    f = stats.anova([X[:8], X[8:16], X[16:]])
    assert f is not None and close(f.statistic, 0.6405954871237362)
    assert close(f.p_value, 0.5365279637459753, 1e-7)
    h = stats.kruskal([X[:8], X[8:16], X[16:]])
    assert h is not None and close(h.statistic, 0.004615384615391349, 1e-6)
    assert close(h.p_value, 0.9976949683671313, 1e-9)


def test_contingency_matches_scipy() -> None:
    g1 = ["a", "a", "b", "b", "a", "c", "c", "a", "b", "c"] * 3
    g2 = ["x", "y", "x", "x", "y", "y", "x", "x", "y", "x"] * 3
    t = stats.contingency(g1, g2)
    assert close(t.chi2, 0.8333333333333331) and t.dof == 2
    assert close(t.p_value, 0.6592406302004439, 1e-9)


def test_holm_and_labels() -> None:
    assert stats.holm([0.01, 0.04, 0.03, 0.2]) == pytest.approx([0.04, 0.09, 0.09, 0.2])
    assert "forte à droite" in stats.skew_label(2.7)
    assert stats.skew_label(-0.2) == "quasi symétrique"
    assert stats.strength_label(-0.62) == "forte négative"
    d = stats.describe(X)
    assert d is not None
    hint = stats.transformation_hint(d, X)
    assert hint is not None and hint[0] == "log" and abs(hint[1]) < abs(d.skew)


def test_histogram_and_fences() -> None:
    bins = stats.histogram(X)
    assert sum(b.count for b in bins) == len(X) and 5 <= len(bins) <= 50
    notes = stats.histogram([1, 2, 2, 3, 3, 3, 5])  # entiers : une classe par valeur
    assert [(b.start, b.count) for b in notes] == [(0.5, 1), (1.5, 2), (2.5, 3), (3.5, 0), (4.5, 1)]
    f = stats.iqr_fences(X)
    assert f.high < 15.2 and f.low < 1.9
    assert max(abs(z) for z in stats.mad_scores(X)) > 3.5


# ═══ Typage des fichiers ═════════════════════════════════════════


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", 1234.56), ("1 234,5 €", 1234.5), ("12,5 %", 12.5), ("1.234,56", 1234.56),
        ("1,234.56", 1234.56), ("-3,2", -3.2), ("(1 000,00)", -1000.0), ("1,234,567", 1234567.0),
        ("2.5e3", 2500.0), ("42", 42.0), (7, 7.0), ("abc", None), ("12,3,4", None), (True, None),
    ],
)  # fmt: skip
def test_parse_number_french_first(raw: Any, expected: float | None) -> None:
    assert parse_number(raw) == expected


def test_parse_date_formats() -> None:
    assert parse_date("05/03/2026") == "2026-03-05"  # jour/mois
    assert parse_date("2026-03-05T14:30:00Z") == "2026-03-05T14:30:00"
    assert parse_date("31/02/2026") is None
    assert parse_date(datetime(2026, 1, 2)) == "2026-01-02"
    assert parse_date(date(2026, 1, 2)) == "2026-01-02"


def test_infer_column_threshold_and_booleans() -> None:
    numbers = infer_column(["1,5"] * 40 + ["n/c", "", None])
    assert numbers.type == "number" and numbers.invalid == 1 and numbers.values[-1] is None
    mixed = infer_column(["1", "deux", "3", "quatre"])
    assert mixed.type == "string"
    assert infer_column(["oui", "non", "Oui"]).type == "boolean"
    assert infer_column(["0", "1", "1"]).type == "number"  # 0/1 reste numérique
    assert infer_column(["N", "O", "N"]).type == "string"  # pas des booléens
    assert is_total_row(["Total général", None, 12]) and not is_total_row(["Totalement", 1])


# ═══ Fichiers joints ═════════════════════════════════════════════


class FakeAttachments:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def get(self, attachment_id: str) -> tuple[AttachmentInfo, bytes] | None:
        data = self.files.get(attachment_id)
        if data is None:
            return None
        info = AttachmentInfo(
            id=attachment_id, name=attachment_id, media_type="application/octet-stream",
            kind="document", size=len(data), meta={}, created_at=datetime.now(UTC),
        )  # fmt: skip
        return info, data


SALES_CSV = "\n".join(
    [
        "Export du 31/03/2026;;;;",
        "Date;Région;Produit;Quantité;Montant HT",
        "05/01/2026;Nord;Logiciel;3;1 200,50",
        "06/01/2026;nord ;Support;1;80",
        "07/01/2026;Sud;Logiciel;2;800",
        "07/01/2026;Sud;Logiciel;2;800",
        "15/02/2026;Est;Formation;10;4 500",
        "18/02/2026;Nord;Support;;95,5",
        "03/03/2026;N/A;Logiciel;4;1 650",
        "Total;;;22;9 126,00",
    ]
).encode("cp1252")


def tools_for(
    files: dict[str, bytes], store: FrameStore, **transports: httpx.MockTransport
) -> dict[str, Any]:
    settings = Settings(_env_file=None, data_via_base_url="http://viz.test/api")  # type: ignore[call-arg]
    env = ToolEnvironment(settings, transports=dict(transports))
    env.files = ConversationFiles(FakeAttachments(files), list(files))
    return {t.name: t for t in analyse_tools(env, store)}


async def call(tools: dict[str, Any], name: str, ctx: ToolContext, **kw: Any) -> Any:
    out = await tools[name].invoke(kw, ctx)
    for artifact in out.artifacts:  # tout artefact est du JSON strict (pas de NaN)
        json.loads(artifact.content)
    return out


async def test_csv_load_profile_clean_and_analyse_end_to_end() -> None:
    store = FrameStore()
    tools = tools_for({"ventes.csv": SALES_CSV}, store)
    ctx = ToolContext(conversation_id="conv-1")

    out = await call(tools, "analyse_charger", ctx, source="fichier", reference="ventes")
    assert not out.is_error, out.content
    frame = store.get("conv-1", "ventes")
    assert frame.rows == 7  # titre et ligne Total exclus
    assert [c.type for c in frame.columns] == ["date", "string", "string", "number", "number"]
    assert (
        frame.column("Montant HT").values[0] == 1200.5 and frame.column("Région").values[6] is None
    )
    assert "ligne(s) de titre" in out.content and "total" in out.content

    out = await call(tools, "analyse_profil", ctx, nom="ventes")
    assert "1 ligne(s) en double" in out.content and "variante(s) d'écriture" in out.content
    assert [a.kind for a in out.artifacts] == ["data_preview", "data_preview"]

    out = await call(
        tools, "analyse_nettoyer", ctx, nom="ventes",
        operations=[{"op": "supprimer_doublons"}, {"op": "casse", "colonne": "Région"},
                    {"op": "remplir", "colonne": "Quantité", "valeur": "mediane"}],
    )  # fmt: skip
    assert not out.is_error, out.content
    clean = store.get("conv-1", "ventes_propre")
    assert clean.rows == 6 and store.get("conv-1", "ventes").rows == 7  # source intacte
    assert set(v for v in clean.column("Région").values if v) == {"Nord", "Sud", "Est"}
    assert None not in clean.column("Quantité").values and len(clean.recipe) == 3

    out = await call(tools, "analyse_distribution", ctx, nom="ventes_propre", colonne="Montant HT")
    assert "asymétrie G1" in out.content and out.artifacts[0].kind == "chart"
    spec = json.loads(out.artifacts[0].content)
    assert spec["format"] == "atelier-chart/1" and spec["type"] == "histogram"
    assert sum(b["count"] for b in spec["bins"]) == 6

    out = await call(
        tools, "analyse_relation", ctx, nom="ventes_propre", x="Quantité", y="Montant HT"
    )
    assert (
        "Pearson r = " in out.content and json.loads(out.artifacts[0].content)["type"] == "scatter"
    )

    out = await call(tools, "analyse_correlations", ctx, nom="ventes_propre")
    assert "Holm" in out.content
    assert json.loads(out.artifacts[0].content)["type"] == "heatmap"

    out = await call(
        tools, "analyse_agreger", ctx, nom="ventes_propre", par=["Date"], periode="mois",
        mesures=[{"fonction": "somme", "colonne": "Montant HT"}, {"fonction": "nombre"}],
        tri="Date (mois)", decroissant=False,
    )  # fmt: skip
    assert "| 2026-01 | 2 080.5 | 3 |" in out.content

    out = await call(
        tools,
        "analyse_graphique",
        ctx,
        nom="ventes_propre",
        type="barres",
        x="Région",
        y="Montant HT",
    )
    assert json.loads(out.artifacts[0].content)["series"][0]["name"] == "somme(Montant HT)"

    out = await call(tools, "analyse_exporter", ctx, nom="ventes_propre")
    assert out.artifacts[0].metadata["recipe"][0] == {"op": "supprimer_doublons"}

    # Une autre conversation ne voit pas ces jeux
    out = await call(tools, "analyse_profil", ToolContext(conversation_id="conv-2"), nom="ventes")
    assert out.is_error and "introuvable" in out.content


async def test_excel_and_json_files() -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Résumé"
    ws.append(["rien"])
    data = wb.create_sheet("Mesures")
    data.append(["Capteur", "Valeur", "Relevé le"])
    for i in range(30):
        data.append([f"C{i % 3}", 10 + i * 0.5, datetime(2026, 1, 1 + i)])
    buffer = io.BytesIO()
    wb.save(buffer)
    payload = json.dumps([{"a": 1, "b": "x"}, {"a": 2.5, "b": "y", "c": [1, 2]}]).encode()
    store = FrameStore()
    tools = tools_for({"mesures.xlsx": buffer.getvalue(), "lignes.json": payload}, store)
    ctx = ToolContext(conversation_id="c")

    out = await call(
        tools, "analyse_charger", ctx, source="fichier", reference="mesures.xlsx", feuille="mesures"
    )
    assert not out.is_error, out.content
    frame = store.get("c", "mesures")
    assert [c.type for c in frame.columns] == ["string", "number", "date"] and frame.rows == 30
    out = await call(
        tools, "analyse_charger", ctx, source="fichier", reference="mesures.xlsx", feuille="Absente"
    )
    assert out.is_error and "Mesures" in out.content
    out = await call(tools, "analyse_charger", ctx, source="fichier", reference="lignes.json")
    assert store.get("c", "lignes").column("c").values == [None, "[1, 2]"]
    out = await call(tools, "analyse_charger", ctx, source="fichier", reference="inconnu.csv")
    assert out.is_error and "introuvable" in out.content


# ═══ Atelier Viz et Atelier Tab ══════════════════════════════════


def viz_transport(total: int) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    from tests.fake_data_via import PROFILE

    seen: list[httpx.Request] = []
    rows = [
        {"date": f"2026-01-{1 + i % 28:02d}", "region": ["Bretagne", "Occitanie"][i % 2],
         "chiffre_affaires": 100.0 + i, "cout": 50.0 + (i % 7)}
        for i in range(total)
    ]  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path.removeprefix("/api")
        if path == "/datasets/ds_ventes":
            return httpx.Response(200, json={**PROFILE, "rows": total})
        if path == "/datasets/ds_ventes/rows":
            offset = int(request.url.params["offset"])
            limit = int(request.url.params["limit"])
            assert limit <= 1000
            return httpx.Response(
                200,
                json={"columns": ["date", "region", "chiffre_affaires", "cout"],
                      "rows": rows[offset : offset + limit], "total": total, "offset": offset, "limit": limit},
            )  # fmt: skip
        return httpx.Response(404, json={"detail": "introuvable"})

    return httpx.MockTransport(handler), seen


async def test_viz_load_pages_rows_and_respects_limit() -> None:
    transport, seen = viz_transport(2500)
    store = FrameStore()
    tools = tools_for({}, store, data_via=transport)
    ctx = ToolContext(conversation_id="v")
    out = await call(tools, "analyse_charger", ctx, source="viz", reference="ds_ventes")
    assert not out.is_error, out.content
    frame = store.get("v", "ventes_2026")  # nom tiré du libellé du jeu
    assert frame.rows == 2500 and len([r for r in seen if r.url.path.endswith("/rows")]) == 3
    assert [c.type for c in frame.columns] == ["date", "string", "number", "number"]

    out = await call(
        tools,
        "analyse_charger",
        ctx,
        source="viz",
        reference="ds_ventes",
        nom="extrait",
        max_lignes=1200,
    )
    assert store.get("v", "extrait").rows == 1200 and "1200 ligne(s) sur 2500" in out.content

    out = await call(tools, "analyse_charger", ctx, source="viz", reference="ds_absent")
    assert out.is_error


async def test_tab_load_excludes_totals(tmp_path: Path) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "tbl_planning_lots.json").write_text(
        (FIX / "tab" / "tbl_planning_lots.json").read_text()
    )
    settings = Settings(_env_file=None, tab_exports_dir=str(folder))  # type: ignore[call-arg]
    store = FrameStore()
    tools = {t.name: t for t in analyse_tools(ToolEnvironment(settings), store)}
    ctx = ToolContext(conversation_id="t")
    out = await call(tools, "analyse_charger", ctx, source="tab", reference="tbl_planning_lots")
    assert not out.is_error, out.content
    frame = store.list("t")[0]
    assert frame.rows == 3 and "Coût HT" in frame.names() and "Lignes de total" in out.content
    assert frame.column("Coût HT").type == "number"


# ═══ Nettoyage et magasin ════════════════════════════════════════


def sample_frame() -> Any:
    return frame_from_rows(
        "jeu", "jeu", "test",
        ["ville", "montant", "date"],
        [["Paris", "10", "01/01/2026"], ["paris ", "20", "02/01/2026"], ["Lyon", "1 000", ""],
         ["Lyon", "15", "04/01/2026"], ["Lille", "12", "05/01/2026"], ["Lille", "11", "06/01/2026"]],
    )  # fmt: skip


def test_cleaning_operations() -> None:
    frame = sample_frame()
    effects = cleaning.apply(
        frame,
        [
            Operation("casse", "ville", "majuscules"),
            Operation("filtrer", "montant", "11", ">="),
            Operation("plafonner", "montant", "p5-p95"),
            Operation("log", "montant"),
            Operation("renommer", "ville", "Ville"),
        ],
    )
    assert len(effects) == 5 and frame.rows == 5
    assert set(frame.column("Ville").values) == {"PARIS", "LYON", "LILLE"}
    assert max(frame.column("montant").values) < 1000 and "log_montant" in frame.names()
    with pytest.raises(CleaningError, match="Opération 1"):
        cleaning.apply(sample_frame(), [Operation("convertir", "absente", "nombre")])
    f = sample_frame()
    cleaning.apply(f, [Operation("remplir", "date", "precedente")])
    assert f.column("date").values[2] == "2026-01-02"
    f.column("montant").values[0] = -1.0
    with pytest.raises(CleaningError, match="négatives"):
        cleaning.apply(f, [Operation("log", "montant")])


def test_store_isolation_eviction_and_names() -> None:
    clock = [0.0]
    store = FrameStore(clock=lambda: clock[0])
    for i in range(MAX_FRAMES + 2):
        f = sample_frame()
        f.name = f"j{i}"
        store.put("a", f)
    assert [f.name for f in store.list("a")][0] == "j2"
    with pytest.raises(FrameNotFoundError):
        store.get("b", "j5")
    clock[0] = 7 * 3600
    with pytest.raises(FrameNotFoundError):
        store.get("a", "j5")  # expiré
    assert frame_name("Ventes 2026.csv") == "ventes_2026" and frame_name("2026.xlsx") == "c_2026"


def test_column_errors_are_explained() -> None:
    frame = sample_frame()
    with pytest.raises(ColumnError, match="Vouliez-vous dire « montant »"):
        frame.column("montnt")
    with pytest.raises(ColumnError, match="numérique"):
        analyses.distribution(frame, "ville", by="montant")


# ═══ Agent Data et extensions ════════════════════════════════════


def test_data_agent_has_analysis_tools_and_can_be_extended() -> None:
    from app.agents.registry import _EXTENDED, extend_agent, get_agent_class
    from app.tools.toolsets import get_toolset
    from tests.fakes import ScriptedProvider, make_router

    cls = get_agent_class("data_analyst")
    agent = cls(
        make_router(ScriptedProvider("anthropic")), ToolEnvironment(Settings(_env_file=None))
    )  # type: ignore[call-arg]
    assert {"analyse_charger", "analyse_correlations", "analyse_nettoyer"} <= set(agent.tools)
    assert not agent.local_only and not get_toolset("analyse").writes

    before = (cls.toolsets, cls.system_prompt, cls.starters)
    try:
        with pytest.raises(ValueError, match="sensible"):
            extend_agent("data_analyst", source="test", toolsets=("tresorerie",))
        assert cls.toolsets == before[0]  # rien modifié
        with pytest.raises(KeyError):
            extend_agent("data_analyst", source="test", toolsets=("inconnue",))
        extend_agent(
            "data_analyst",
            source="test",
            toolsets=("projets_read",),
            instructions="Recette X.",
            starters=("Essai",),
        )
        extend_agent(
            "data_analyst", source="test", toolsets=("projets_read",), instructions="Recette X."
        )
        assert (
            cls.toolsets.count("projets_read") == 1 and cls.system_prompt.count("Recette X.") == 1
        )
        assert cls.starters[-1] == "Essai"
        with pytest.raises(ValueError, match="inconnu"):
            extend_agent("absent", source="test")
    finally:
        cls.toolsets, cls.system_prompt, cls.starters = before
        _EXTENDED.discard(("data_analyst", "test"))
