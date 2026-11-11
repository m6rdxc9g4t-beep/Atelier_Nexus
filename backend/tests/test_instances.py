"""Plusieurs processus Nexus sur une même base SQLite (deuxième ouverture de l'app de bureau) :
le nettoyage de démarrage ne ferme jamais une exécution qu'un autre processus mène.

Aucun réseau ; un seul vrai sous-processus (Python, bibliothèque standard) pour vérifier que le
système libère le témoin d'un processus tué.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.instances import SUFFIX, InstanceGuard, instances_dir
from app.db.models import Base
from app.db.workflows import WorkflowRepository
from app.schemas.workflows import WorkflowCreate, WorkflowStep
from app.schemas.workflows_v2 import StepRun, WorkflowRun
from main import close_interrupted_runs

BACKEND = Path(__file__).resolve().parents[1]


def witnesses(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.lock"))


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path / f"nexus.db{SUFFIX}"


@pytest.fixture
def guards(directory: Path) -> Iterator[list[InstanceGuard]]:
    """Témoins de trois « processus » sur la même base, relâchés en fin de test."""
    made = [InstanceGuard(directory) for _ in range(3)]
    yield made
    for guard in made:
        guard.release()


# ─── Témoins ──────────────────────────────────────────────────────


def test_only_a_file_database_has_a_guard(tmp_path: Path) -> None:
    db = tmp_path / "nexus.db"
    assert instances_dir(f"sqlite+aiosqlite:///{db}") == db.with_name("nexus.db.instances")
    for url in (
        "postgresql+asyncpg://atelier:secret@localhost:5432/atelier_nexus",
        "sqlite+aiosqlite://",
        "sqlite+aiosqlite:///:memory:",
        "n'importe quoi",
    ):
        assert instances_dir(url) is None
        guard = InstanceGuard.for_database(url)
        assert guard.acquire()  # comme avant : un seul serveur sur cette base
        guard.release()
    assert not list(tmp_path.iterdir())  # rien n'est écrit sans base sur disque


def test_second_process_sees_the_first(directory: Path, guards: list[InstanceGuard]) -> None:
    first, second, third = guards
    assert first.acquire()  # seul : le nettoyage de démarrage est sûr
    assert not second.acquire()  # deuxième ouverture : le premier sert encore
    assert not first.acquire()  # redemandé plus tard : il n'est plus seul
    assert len(witnesses(directory)) == 2

    first.release()  # la première fenêtre est fermée, la seconde sert toujours
    assert len(witnesses(directory)) == 1
    assert not third.acquire()
    second.release()
    third.release()
    assert witnesses(directory) == []
    assert first.acquire()  # plus personne : seul de nouveau


def test_witness_left_by_a_stopped_process_is_removed(
    directory: Path, guards: list[InstanceGuard]
) -> None:
    """Arrêt brutal : le fichier reste, mais plus aucun verrou ne le tient."""
    directory.mkdir()
    stale = directory / "4242-deadbeef0000.lock"
    stale.write_bytes(b"")
    assert guards[0].acquire()
    assert not stale.exists()
    assert len(witnesses(directory)) == 1


def test_unusable_directory_never_reports_alone(tmp_path: Path) -> None:
    """Témoin impossible à poser : dans le doute, pas seul (rien n'est clos)."""
    blocker = tmp_path / "nexus.db.instances"
    blocker.write_text("pas un dossier", encoding="utf-8")
    guard = InstanceGuard(blocker)
    assert not guard.acquire()
    guard.release()  # sans effet
    assert blocker.read_text(encoding="utf-8") == "pas un dossier"


_HOLD = """
import sys
from pathlib import Path
from app.db.instances import InstanceGuard

guard = InstanceGuard(Path(sys.argv[1]))
print("seul" if guard.acquire() else "accompagne", flush=True)
sys.stdin.read()  # sert jusqu'à être tué
"""


def test_killed_process_no_longer_counts(directory: Path, guards: list[InstanceGuard]) -> None:
    """Un vrai second processus : vivant, il empêche le nettoyage ; tué (sans rien relâcher
    lui-même), le système libère son verrou et son témoin est retiré au démarrage suivant."""
    process = subprocess.Popen(  # noqa: S603 — interpréteur des tests, script fixe
        [sys.executable, "-c", _HOLD, str(directory)],
        cwd=BACKEND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "seul"
        assert not guards[0].acquire()
        guards[0].release()
        process.kill()
        process.wait(timeout=30)
        assert len(witnesses(directory)) == 1  # le témoin du processus tué est resté
        assert guards[1].acquire()
        assert len(witnesses(directory)) == 1  # … remplacé par le nôtre
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


# ─── Nettoyage de démarrage ───────────────────────────────────────


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[list[WorkflowRepository]]:
    """Deux processus : deux moteurs sur le même fichier SQLite."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'nexus.db'}"
    engines = [create_async_engine(url) for _ in range(2)]
    async with engines[0].begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield [WorkflowRepository(async_sessionmaker(e, expire_on_commit=False)) for e in engines]
    for engine in engines:
        await engine.dispose()


async def test_second_startup_leaves_the_first_process_runs_alone(
    repos: list[WorkflowRepository], tmp_path: Path
) -> None:
    """Fenêtre A exécute une étape longue ; l'app est rouverte (fenêtre B, même `nexus.db`).
    Le démarrage de B marquait l'exécution de A « interrompue » et comptait un échec, puis la
    fin de l'étape de A comptait une seconde fois."""
    first, second = repos
    url = f"sqlite+aiosqlite:///{tmp_path / 'nexus.db'}"
    guard_a, guard_b = InstanceGuard.for_database(url), InstanceGuard.for_database(url)
    try:
        assert await close_interrupted_runs(first, guard_a) == 0  # A démarre, seul

        workflow = await first.create(
            WorkflowCreate(
                agent="data_analyst",
                title="Conversion longue",
                steps=[WorkflowStep(tool="data_via_list_datasets", input={})],
            )
        )
        now = datetime.now(UTC)
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            status="awaiting_approval",
            message="",
            params={},
            steps=[
                StepRun(id="convertir", uses="convert.convert_file", label="Convertir"),
                StepRun(id="publier", uses="wiki.pages.create", label="Publier"),
            ],
            artifacts=[],
            pending=[],
            created_at=now,
            updated_at=now,
        )
        await first.save_run(run, {})
        assert await first.claim_run(run.id)  # validée : A la mène
        started = run.model_copy(deep=True)
        started.status = "running"
        started.steps[0].started_at = now  # étape entamée, pas finie
        await first.save_run(started, {})

        # B démarre pendant l'étape : rien n'est touché
        assert await close_interrupted_runs(second, guard_b) is None
        stored = await second.get_run(run.id)
        assert stored is not None
        assert stored[0].status == "running" and stored[0].message == ""
        assert [(s.status, s.error_code) for s in stored[0].steps] == [
            ("pending", None),
            ("pending", None),
        ]
        kept = await second.get(workflow.id)
        assert kept is not None and kept.run_count == 0 and kept.last_status is None

        # A termine son étape et compte l'exécution : une seule fois
        await first.record_run(workflow.id, "completed")
        counted = await second.get(workflow.id)
        assert counted is not None
        assert counted.run_count == 1 and counted.last_status == "completed"
    finally:
        guard_a.release()
        guard_b.release()


async def test_interrupted_run_is_closed_once_no_process_is_left(
    repos: list[WorkflowRepository], tmp_path: Path
) -> None:
    """A s'arrête en pleine étape alors que B sert encore : l'exécution reste « en cours »
    tant que B vit (jamais de clôture pendant le service), puis le premier démarrage seul la
    clôt."""
    first, second = repos
    url = f"sqlite+aiosqlite:///{tmp_path / 'nexus.db'}"
    guard_a, guard_b, guard_c = (InstanceGuard.for_database(url) for _ in range(3))
    try:
        assert guard_a.acquire()
        now = datetime.now(UTC)
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            workflow_id=str(uuid.uuid4()),
            status="running",
            message="",
            params={},
            steps=[
                StepRun(
                    id="convertir", uses="convert.convert_file", label="Convertir", started_at=now
                )
            ],
            artifacts=[],
            pending=[],
            created_at=now,
            updated_at=now,
        )
        await first.save_run(run, {})
        assert await close_interrupted_runs(second, guard_b) is None  # B démarre

        guard_a.release()  # A quitté pendant l'étape
        assert await close_interrupted_runs(first, guard_c) is None  # C démarre, B sert encore
        still = await first.get_run(run.id)
        assert still is not None and still[0].status == "running"

        guard_b.release()
        guard_c.release()
        assert await close_interrupted_runs(first, guard_c) == 1  # redémarrage, seul
        closed = await first.get_run(run.id)
        assert closed is not None and closed[0].status == "failed"
        assert closed[0].steps[0].error_code == "INTERRUPTED"
    finally:
        for guard in (guard_a, guard_b, guard_c):
            guard.release()
