"""Moteur des déclencheurs : validation, état initial, passages de fond, lancements.

Un **passage** (`tick()`) fait, dans l'ordre :
1. **Horaires** échus : une seule exécution, même si plusieurs occurrences ont été manquées
   (Nexus fermé) ; les autres sont comptées `missed`. `next_fire_at` passe à l'occurrence suivante.
2. **Événements** : pour chaque application observée par au moins un déclencheur actif, lecture
   à partir du curseur de l'application (un seul, persisté), puis distribution aux déclencheurs
   (types, filtres, `{{event.…}}`). Premier démarrage : curseur = dernier `seq` connu, rien n'est
   rejoué. `gap` : le curseur repart du dernier `seq`, avertissement, rien relancé en masse. Un
   déclencheur ne voit que les événements postérieurs à sa création (`state.cursor`).
3. **Rafales** (`debounce_seconds`) arrivées à échéance : un lancement, le dernier événement gagne.

Chaque lancement passe par les mêmes garde-fous : une seule exécution en attente de validation par
déclencheur (`waiting`), au plus `max_runs_per_hour` (`throttled`), lancements séquentiels pour un
même déclencheur (verrou). Le moteur d'exécution est celui de `POST /api/workflows/{id}/run` : une
écriture s'arrête toujours sur `awaiting_approval`.

Une erreur sur un déclencheur est comptée (`counters.errors`, `last_error`) et n'arrête ni le
passage ni la boucle. Les `data` des événements ne sont jamais journalisées ni conservées : seuls
les paramètres déjà résolus et la référence de l'événement (sans `data`) sont gardés pendant une
rafale. Un seul processus Nexus est visé (verrous en mémoire, curseurs non partagés).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import weakref
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.agents import AgentCatalog, AgentNotFoundError
from app.core.config import Settings
from app.core.llm import LLMRouter
from app.db.triggers import AnyFields, StoredTrigger, TriggerRepository
from app.db.workflows import WorkflowRepository
from app.schemas.triggers import (
    CatalogEvent,
    CatalogEventApp,
    EventsCatalog,
    EventTrigger,
    EventTriggerFields,
    RunOrigin,
    SampleEvent,
    ScheduleTrigger,
    ScheduleTriggerFields,
    TriggerEventRef,
    TriggerState,
)
from app.schemas.workflows_v2 import WorkflowRun, WorkflowV2
from app.suite.apps import NODE_APPS, app_color, app_name
from app.suite.manifest import AtelierEvent, EventPage, ManifestError
from app.suite.nodes import NodeState, SuiteNodes
from app.tools.environment import ToolEnvironment
from app.tools.http import AppError
from app.triggers.matching import matches, mentions_event, render_params, template_problems
from app.triggers.schedule import catch_up, next_occurrence
from app.workflows import WorkflowError
from app.workflows_v2.launch import launch_run

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
MAX_PAGES = 4
#: Délai laissé à un passage en cours avant l'annulation à l'extinction
STOP_GRACE_SECONDS = 10.0
GAP_WARNING = (
    "Des événements ont été perdus (journal de l'application remis à zéro ou purgé) : le "
    "déclencheur repart des événements suivants, rien n'a été relancé."
)

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(UTC)


_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def trigger_lock(trigger_id: str) -> asyncio.Lock:
    """Verrou d'un déclencheur, partagé par l'API et la tâche de fond : un même déclencheur ne
    lance jamais deux exécutions en parallèle (un seul processus Nexus est visé)."""
    locks = _LOCKS.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(trigger_id, asyncio.Lock())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def event_ref(app: str, event: AtelierEvent | SampleEvent) -> TriggerEventRef:
    """Référence d'un événement conservée sur l'exécution : jamais ses `data`."""
    return TriggerEventRef.model_validate(
        {
            "app": app,
            "seq": event.seq,
            "type": event.type,
            "at": event.at,
            "subject": event.subject.model_dump(),
        }
    )


def app_problem(state: NodeState) -> str | None:
    """Message d'une application dont on ne peut pas lire les événements (None si elle répond)."""
    if state.status == "ok":
        return None
    name = app_name(state.app)
    if state.status == "not_configured":
        return f"{name} n'est pas configuré."
    if state.status == "no_contract":
        return f"{name} ne publie pas d'événements (version antérieure au contrat atelier-node/1)."
    return f"{name} injoignable."


@dataclass
class TriggerDeps:
    """Dépendances du moteur (fabriques : réglages et routeur rechargés à chaud)."""

    triggers: TriggerRepository
    workflows: WorkflowRepository
    make_env: Callable[[], ToolEnvironment]
    llm: Callable[[], LLMRouter]
    catalog: Callable[[], AgentCatalog]
    settings: Callable[[], Settings]


class TriggerService:
    def __init__(
        self,
        deps: TriggerDeps,
        *,
        clock: Clock = utc_now,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.deps = deps
        self.clock = clock
        self.sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._sleeping = False
        self._last_failure: str | None = None

    @property
    def triggers(self) -> TriggerRepository:
        return self.deps.triggers

    @property
    def workflows(self) -> WorkflowRepository:
        return self.deps.workflows

    def now(self) -> datetime:
        return _aware(self.clock()).astimezone(UTC)

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.deps.settings().timezone)

    def lock(self, trigger_id: str) -> asyncio.Lock:
        return trigger_lock(trigger_id)

    # ─── Validation et état initial ───────────────────────────────

    async def check(self, workflow: WorkflowV2, fields: AnyFields) -> tuple[list[str], str | None]:
        """(problèmes bloquants → 422, avertissement à garder dans `last_error`)."""
        problems: list[str] = []
        declared = {p.name for p in workflow.params}
        unknown = sorted(set(fields.params) - declared)
        if unknown:
            problems.append(
                f"Paramètre(s) inconnu(s) du workflow : {', '.join(unknown)}"
                + (f" (déclarés : {', '.join(sorted(declared))})." if declared else ".")
            )
        problems += template_problems(
            fields.params, allow_event=isinstance(fields, EventTriggerFields)
        )
        if mentions_event(fields.label):
            problems.append("Gabarit {{event.…}} hors des paramètres : retirez-le du libellé.")
        if not isinstance(fields, EventTriggerFields):
            return problems, None
        if any(mentions_event(f.value) for f in fields.filters):
            problems.append(
                "Gabarit {{event.…}} hors des paramètres : un filtre compare une valeur fixe."
            )
        env = self.deps.make_env()
        try:
            state = await env.suite().state(fields.app)
        finally:
            await env.aclose()
        problem = app_problem(state)
        if problem is not None or state.manifest is None:
            return problems, f"{problem or app_name(fields.app)} Types d'événements non vérifiés."
        known = {e.type for e in state.manifest.events}
        undeclared = [t for t in fields.types if t not in known]
        if undeclared:
            problems.append(
                f"Type(s) d'événement non déclaré(s) par {state.name} : {', '.join(undeclared)}"
                + (f" (déclarés : {', '.join(sorted(known))})." if known else ".")
            )
        return problems, None

    async def latest_seq(self, app: str) -> int | None:
        """Dernier `seq` connu de l'application (curseur de création d'un déclencheur) ; None si
        elle ne répond pas (le déclencheur partira alors du premier passage où elle répond)."""
        env = self.deps.make_env()
        try:
            return (await env.suite().events(app, limit=1)).next
        except (AppError, ManifestError, OSError, ValueError):
            return None
        finally:
            await env.aclose()

    async def initial_state(
        self,
        fields: AnyFields,
        note: str | None,
        previous: StoredTrigger | None = None,
    ) -> tuple[TriggerState, dict[str, Any]]:
        """État d'un déclencheur enregistré (création ou modification) : compteurs et
        historique conservés, `next_fire_at` recalculé, curseur repris au dernier événement si
        le déclencheur est nouveau, réactivé ou change d'application. La rafale en attente et
        l'avertissement sont oubliés."""
        state = previous.trigger.state.model_copy(deep=True) if previous else TriggerState()
        internal: dict[str, Any] = dict(previous.internal) if previous else {}
        internal.pop("pending", None)
        state.warning = None
        state.last_error = note
        internal["app_error"] = note is not None
        if isinstance(fields, ScheduleTriggerFields):
            state.cursor = None
            state.next_fire_at = (
                next_occurrence(fields.schedule, self.now(), self.tz()) if fields.enabled else None
            )
            return state, internal
        state.next_fire_at = None
        before = previous.trigger if previous else None
        fresh = (
            not isinstance(before, EventTrigger)
            or before.app != fields.app
            or (fields.enabled and not before.enabled)
            or state.cursor is None
        )
        if fresh:
            state.cursor = await self.latest_seq(fields.app)
            if state.cursor is None and fields.enabled and state.last_error is None:
                state.last_error = (
                    f"{app_name(fields.app)} injoignable : le déclencheur partira du premier "
                    "passage où l'application répond."
                )
                internal["app_error"] = True
        return state, internal

    # ─── Catalogue des événements ─────────────────────────────────

    async def events_catalog(self) -> EventsCatalog:
        env = self.deps.make_env()
        try:
            states = await env.suite().states(NODE_APPS)
        finally:
            await env.aclose()
        apps = []
        for state in states:
            events = []
            for spec in state.manifest.events if state.manifest else []:
                fields = [f"data.{name}" for name in spec.data_fields]
                events.append(
                    CatalogEvent(
                        type=spec.type,
                        label=spec.label or spec.type,
                        fields=[*fields, "subject.id", "subject.label"],
                    )
                )
            apps.append(
                CatalogEventApp(
                    app=state.app,
                    name=state.name,
                    color=app_color(state.app),
                    status=state.status,
                    events=events,
                )
            )
        return EventsCatalog(apps=apps)

    # ─── Lancement ────────────────────────────────────────────────

    async def _launch(
        self,
        workflow: WorkflowV2,
        params: dict[str, str],
        origin: RunOrigin,
        trigger_id: str,
        ref: TriggerEventRef | None,
    ) -> WorkflowRun:
        return await launch_run(
            workflow,
            params,
            llm=self.deps.llm(),
            catalog=self.deps.catalog(),
            make_env=self.deps.make_env,
            repo=self.workflows,
            trigger=origin,
            trigger_id=trigger_id,
            trigger_event=ref,
        )

    async def test(self, trigger_id: str, sample: SampleEvent | None) -> WorkflowRun | None:
        """Lance une fois maintenant (origine `test`), sans compter ni limiter : la validation
        des écritures, elle, s'applique comme toujours. None si le déclencheur n'existe plus.
        Lève `WorkflowError` ou `AgentNotFoundError`."""
        stored = await self.triggers.get(trigger_id)
        if stored is None:
            return None
        trigger = stored.trigger
        workflow = await self.workflows.get(trigger.workflow_id)
        if not isinstance(workflow, WorkflowV2):
            raise WorkflowError("Le workflow de ce déclencheur n'est plus un workflow v2.")
        event: dict[str, Any] | None = None
        ref: TriggerEventRef | None = None
        if sample is not None and isinstance(trigger, EventTrigger):
            event = sample.model_dump(mode="json")
            ref = event_ref(trigger.app, sample)
        async with self.lock(trigger_id):
            return await self._launch(
                workflow, render_params(trigger.params, event), "test", trigger_id, ref
            )

    async def _fire(
        self,
        trigger_id: str,
        params: dict[str, str],
        ref: TriggerEventRef | None,
        origin: RunOrigin,
    ) -> None:
        """Un déclenchement : contrôles de débit, lancement, état. Jamais d'exception sauf
        stockage indisponible (rattrapée par le passage)."""
        stored = await self.triggers.get(trigger_id)
        if stored is None:
            return
        trigger = stored.trigger
        if await self.workflows.has_waiting_run(trigger_id):

            def waiting(_: StoredTrigger, state: TriggerState, __: dict[str, Any]) -> None:
                state.counters.waiting += 1

            await self.triggers.mutate(trigger_id, waiting)
            return
        now = self.now()

        def reserve(fresh: StoredTrigger, state: TriggerState, internal: dict[str, Any]) -> bool:
            horizon = now - timedelta(hours=1)
            fired = [t for t in internal.get("fired", []) if datetime.fromisoformat(t) > horizon]
            if len(fired) >= fresh.trigger.max_runs_per_hour:
                internal["fired"] = fired
                state.counters.throttled += 1
                return False
            internal["fired"] = [*fired, now.isoformat()]
            return True

        if not await self.triggers.mutate(trigger_id, reserve):
            return
        workflow = await self.workflows.get(trigger.workflow_id)
        try:
            if not isinstance(workflow, WorkflowV2):
                raise WorkflowError("Workflow introuvable ou non v2.")
            run = await self._launch(workflow, params, origin, trigger_id, ref)
        except AgentNotFoundError:
            agent = workflow.agent if isinstance(workflow, WorkflowV2) else None
            await self._error(trigger_id, f"L'agent « {agent} » de ce workflow n'existe plus.")
            return
        except WorkflowError as exc:
            await self._error(trigger_id, f"Lancement impossible : {exc}")
            return

        def record(_: StoredTrigger, state: TriggerState, internal: dict[str, Any]) -> None:
            state.counters.fired += 1
            state.last_fired_at = now
            state.last_run_id = run.id
            state.last_run_status = run.status
            state.warning = None
            if not internal.get("app_error"):
                state.last_error = None
            if ref is not None and (state.cursor is None or ref.seq > state.cursor):
                state.cursor = ref.seq

        await self.triggers.mutate(trigger_id, record)
        logger.info(
            "Déclencheur %s (%s) : exécution %s, statut %s", trigger_id, origin, run.id, run.status
        )

    async def _error(self, trigger_id: str, message: str, *, app: bool = False) -> None:
        """Erreur sur un déclencheur (`last_error`, `counters.errors`). Application injoignable
        (`app`) : comptée une fois par panne, effacée dès qu'elle répond de nouveau."""

        def note(_: StoredTrigger, state: TriggerState, internal: dict[str, Any]) -> None:
            if not app or not internal.get("app_error"):
                state.counters.errors += 1
            state.last_error = message[:500]
            internal["app_error"] = app

        await self.triggers.mutate(trigger_id, note)

    # ─── Passage ──────────────────────────────────────────────────

    async def tick(self) -> None:
        """Un passage complet (horaires, événements, rafales). Les tests l'appellent sans
        attendre. Une erreur sur un déclencheur est comptée sur lui et le passage continue."""
        active = await self.triggers.list(enabled_only=True)
        for stored in active:
            if isinstance(stored.trigger, ScheduleTrigger):
                await self._guard(stored.id, self._schedule(stored))
        by_app: dict[str, list[StoredTrigger]] = {}
        for stored in active:
            if isinstance(stored.trigger, EventTrigger):
                by_app.setdefault(stored.trigger.app, []).append(stored)
        if by_app:
            env = self.deps.make_env()
            try:
                suite = env.suite()
                for app, group in by_app.items():
                    try:
                        await self._app_events(suite, app, group)
                    except Exception as exc:  # une application ne bloque pas les autres
                        logger.warning(
                            "Événements de %s : passage interrompu (%s)", app, type(exc).__name__
                        )
            finally:
                await env.aclose()
        for stored in await self.triggers.list(enabled_only=True):
            if isinstance(stored.trigger, EventTrigger) and stored.internal.get("pending"):
                await self._guard(stored.id, self._flush(stored))

    async def _guard(self, trigger_id: str, work: Awaitable[None]) -> None:
        """Exécute le travail d'un déclencheur sous son verrou ; une exception est comptée."""
        try:
            async with self.lock(trigger_id):
                await work
        except Exception as exc:  # jamais fatal pour le passage ni pour la boucle
            logger.warning(
                "Déclencheur %s : erreur pendant le passage (%s)", trigger_id, type(exc).__name__
            )
            with contextlib.suppress(Exception):
                await self._error(trigger_id, f"Erreur interne du déclencheur : {exc}")

    # ─── Horaires ─────────────────────────────────────────────────

    async def _schedule(self, stored: StoredTrigger) -> None:
        now = self.now()
        tz = self.tz()

        def claim(
            fresh: StoredTrigger, state: TriggerState, __: dict[str, Any]
        ) -> dict[str, str] | None:
            """Paramètres à lancer si une occurrence est échue (état relu, jamais une copie)."""
            trigger = fresh.trigger
            if not isinstance(trigger, ScheduleTrigger) or not trigger.enabled:
                return None
            due = state.next_fire_at
            if due is None:  # enregistrement sans prochaine occurrence : calculée, rien lancé
                state.next_fire_at = next_occurrence(trigger.schedule, now, tz)
                return None
            due = _aware(due)
            if due > now:
                return None
            count, upcoming = catch_up(trigger.schedule, due, now, tz)
            state.next_fire_at = upcoming
            state.counters.missed += max(0, count - 1)  # au plus une exécution rattrapée
            return dict(trigger.params) if count > 0 else None

        params = await self.triggers.mutate(stored.id, claim)
        if params is not None:
            await self._fire(stored.id, render_params(params, None), None, "schedule")

    # ─── Événements ───────────────────────────────────────────────

    async def _app_events(self, suite: SuiteNodes, app: str, group: list[StoredTrigger]) -> None:
        """Lit les événements d'UNE application à partir de son curseur et les distribue."""
        problem = app_problem(await suite.state(app))
        cursor = await self.triggers.get_cursor(app)
        # Rien d'utile avant le plus petit curseur des déclencheurs (seq de création compris)
        floors = [t.trigger.state.cursor for t in group if t.trigger.state.cursor is not None]
        since = cursor
        if floors:
            since = min(floors) if since is None else max(since, min(floors))
        page: EventPage | None = None
        if problem is None:
            try:
                if since is None:
                    # Premier démarrage : on part du dernier événement, rien n'est rejoué
                    latest = (await suite.events(app, limit=1)).next
                    await self.triggers.set_cursor(app, latest)
                    for stored in group:
                        await self._guard(stored.id, self._clear_app_error(stored.id))
                        await self._guard(stored.id, self._advance(stored.id, latest))
                    return
                page = await suite.events(app, since=since, limit=PAGE_SIZE)
            except (AppError, ManifestError, OSError, ValueError) as exc:
                problem = f"{app_name(app)} injoignable."
                logger.info("Événements de %s illisibles (%s)", app, type(exc).__name__)
        if problem is not None or page is None or since is None:
            for stored in group:
                await self._guard(stored.id, self._error(stored.id, problem or "", app=True))
            return
        for stored in group:
            await self._guard(stored.id, self._clear_app_error(stored.id))
        for _ in range(MAX_PAGES):
            if page.gap:
                await self._gap(suite, app, group)
                return
            events = sorted(page.events, key=lambda e: e.seq)
            reached = max(since, page.next)
            for stored in group:
                await self._guard(stored.id, self._dispatch(stored, events, reached))
            if cursor is None or reached != cursor:
                await self.triggers.set_cursor(app, reached)
                cursor = reached
            if len(page.events) < PAGE_SIZE or reached == since:
                return
            since = reached
            try:
                page = await suite.events(app, since=since, limit=PAGE_SIZE)
            except (AppError, ManifestError, OSError, ValueError):
                return  # le passage suivant reprend au curseur enregistré

    async def _gap(self, suite: SuiteNodes, app: str, group: list[StoredTrigger]) -> None:
        """Trou d'événements : le curseur repart du dernier `seq`, avertissement sur chaque
        déclencheur de l'application, rien n'est relancé."""
        try:
            latest = (await suite.events(app, limit=1)).next
        except (AppError, ManifestError, OSError, ValueError):
            return  # repris au passage suivant (le trou sera de nouveau signalé)
        await self.triggers.set_cursor(app, latest)
        logger.warning("Événements de %s perdus (gap) : curseur repris à %d", app, latest)
        for stored in group:

            def warn(_: StoredTrigger, state: TriggerState, __: dict[str, Any]) -> None:
                state.cursor = latest
                state.warning = GAP_WARNING

            await self._guard(stored.id, self._mutate(stored.id, warn))

    async def _mutate(
        self, trigger_id: str, fn: Callable[[StoredTrigger, TriggerState, dict[str, Any]], None]
    ) -> None:
        await self.triggers.mutate(trigger_id, fn)

    async def _advance(self, trigger_id: str, seq: int) -> None:
        def move(_: StoredTrigger, state: TriggerState, __: dict[str, Any]) -> None:
            if state.cursor is None or seq > state.cursor:
                state.cursor = seq

        await self.triggers.mutate(trigger_id, move)

    async def _clear_app_error(self, trigger_id: str) -> None:
        def clear(_: StoredTrigger, state: TriggerState, internal: dict[str, Any]) -> None:
            if internal.get("app_error"):
                state.last_error = None
                internal["app_error"] = False

        await self.triggers.mutate(trigger_id, clear)

    async def _dispatch(
        self, stored: StoredTrigger, events: Iterable[AtelierEvent], nxt: int
    ) -> None:
        """Distribue une page d'événements à UN déclencheur (sous son verrou)."""
        fresh = await self.triggers.get(stored.id)
        if (
            fresh is None
            or not isinstance(fresh.trigger, EventTrigger)
            or not fresh.trigger.enabled
        ):
            return
        trigger = fresh.trigger
        start = trigger.state.cursor
        if start is None:  # créé alors que l'application ne répondait pas : il part d'ici
            await self._advance(stored.id, nxt)
            return
        filtered = 0
        chosen: list[AtelierEvent] = []
        for event in events:
            if event.seq <= start or event.type not in trigger.types:
                continue
            if matches(trigger.filters, event.model_dump(mode="json")):
                chosen.append(event)
            else:
                filtered += 1
        if trigger.debounce_seconds > 0 and chosen:
            last = chosen[-1]
            pending = {
                "params": render_params(trigger.params, last.model_dump(mode="json")),
                "event": event_ref(trigger.app, last).model_dump(mode="json"),
                "due": (self.now() + timedelta(seconds=trigger.debounce_seconds)).isoformat(),
            }

            def hold(_: StoredTrigger, state: TriggerState, internal: dict[str, Any]) -> None:
                internal["pending"] = pending  # le dernier événement de la rafale gagne
                state.counters.filtered += filtered
                state.cursor = max(state.cursor or 0, nxt)

            await self.triggers.mutate(stored.id, hold)
            return
        for event in chosen:
            params = render_params(trigger.params, event.model_dump(mode="json"))
            await self._fire(stored.id, params, event_ref(trigger.app, event), "event")

        def done(_: StoredTrigger, state: TriggerState, __: dict[str, Any]) -> None:
            state.counters.filtered += filtered
            state.cursor = max(state.cursor or 0, nxt)

        await self.triggers.mutate(stored.id, done)

    async def _flush(self, stored: StoredTrigger) -> None:
        """Rafale arrivée à échéance : un seul lancement avec le dernier événement."""
        now = self.now()

        def take(_: StoredTrigger, __: TriggerState, internal: dict[str, Any]) -> Any:
            pending = internal.get("pending")
            if not isinstance(pending, dict):
                return None
            if _aware(datetime.fromisoformat(pending["due"])) > now:
                return None
            return internal.pop("pending")

        pending = await self.triggers.mutate(stored.id, take)
        if pending:
            ref = TriggerEventRef.model_validate(pending["event"])
            await self._fire(stored.id, dict(pending["params"]), ref, "event")

    # ─── Boucle de fond ───────────────────────────────────────────

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop(), name="nexus-triggers")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        """Arrêt propre : un passage en cours a `STOP_GRACE_SECONDS` pour finir, puis la tâche
        est annulée ; on attend sa fin dans tous les cas."""
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping = True
        if self._sleeping:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), STOP_GRACE_SECONDS)
        except TimeoutError:
            task.cancel()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # la boucle ne lève pas ; par prudence, l'extinction continue
            logger.warning("Arrêt des déclencheurs : %s", type(exc).__name__)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
                self._last_failure = None
            except Exception as exc:  # stockage indisponible… : journalisé, la boucle continue
                message = f"{type(exc).__name__} : {exc}"
                level = logging.DEBUG if message == self._last_failure else logging.WARNING
                logger.log(level, "Passage des déclencheurs en échec : %s", message)
                self._last_failure = message
            if self._stopping:
                break
            self._sleeping = True
            try:
                await self.sleep(self.deps.settings().triggers_poll_seconds)
            finally:
                self._sleeping = False
