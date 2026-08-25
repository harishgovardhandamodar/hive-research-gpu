"""Companion backend entrypoint — FastAPI app serving REST + WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .autonomy import MODES, AutonomyMode, resolve_mode
from .artifacts import build_explorer, shape_artifacts
from .episodic import EpisodeStore
from .events import EventBus
from .executor import ApprovalStore, PlanExecutor
from .ingest_failures import IngestFailureStore, inner_add_status
from .hive_client import HiveApiError, HiveClient
from .llm import ChatClient
from .discover import join_note_paths, shape_pool_paper
from .jobsbar import collect as collect_statusbar
from .kg import KGCache, extract_arxiv_ids
from .deepideation import ConceptNetwork, DeepIdeationEngine, DeepRun
from .ideagent import IdeagentEngine, IdeaRun, persist_runs
from .backup import BackupLoop, create_snapshot, list_snapshots
from .cite import bibtex
from .schedules import GoalScheduler, ScheduleStore, WEEKDAYS
from .planner import Plan, Planner, Step
from .policy import ReinforcementPolicy
from .plan_templates import TemplateStore
from .proactive import ProactiveEngine, SuggestionStore
from .settings import load_settings
from .timeline import build_timeline
from .agents_catalog import AgentSelectionStore, CATEGORY_LABEL, CATALOG_BY_ID, catalog_dicts
from .tools import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("companion")


class CompanionApp:
    """Dependency container shared across requests."""

    def __init__(self) -> None:
        self.settings = load_settings()
        self.bus = EventBus()
        self.client = HiveClient(self.settings.hive_api_url, self.settings.hive_token)
        self.episodes = EpisodeStore(self.settings.data_dir)
        self.policy = ReinforcementPolicy(self.settings.data_dir)
        self.approvals = ApprovalStore(self.settings.data_dir)
        self.suggestions = SuggestionStore(self.settings.data_dir)
        self.ingest_failures = IngestFailureStore(self.settings.data_dir)
        self.llm: ChatClient | None = ChatClient(self.settings.llm_base_url, self.settings.llm_fast_model)
        self.registry = ToolRegistry(self.client, failures=self.ingest_failures, episodes=self.episodes, llm=self.llm)
        self.kg = KGCache(self.client)
        ideation_url = self.settings.ideation_base_url or self.settings.llm_base_url
        self.ideagent = IdeagentEngine(
            llm_fast=ChatClient(ideation_url, self.settings.llm_fast_model),
            llm_main=ChatClient(ideation_url, self.settings.llm_model),
            kg=self.kg,
            bus=self.bus,
            on_complete=lambda run: persist_runs(self.settings.data_dir, self.ideagent.history),
            on_iteration=lambda run: persist_runs(self.settings.data_dir, self.ideagent.history),
        )
        self._ideagent_llms: list[Any] = [self.ideagent.llm_fast, self.ideagent.llm_main]
        self.backups = BackupLoop(self.settings.data_dir)
        self.deep_network = ConceptNetwork(self.kg)
        ideation_url2 = self.settings.ideation_base_url or self.settings.llm_base_url
        self.deep_llms = [
            ChatClient(ideation_url2, self.settings.llm_fast_model),
            ChatClient(ideation_url2, self.settings.llm_model),
        ]
        self._ideagent_llms.extend(x for x in self.deep_llms if x is not None)
        self.deepideation = DeepIdeationEngine(
            llm_fast=self.deep_llms[0],
            llm_main=self.deep_llms[1],
            kg=self.kg,
            network=self.deep_network,
            bus=self.bus,
            on_complete=lambda run: self._persist_deep_runs(),
            search_fn=lambda q: self.client.paper_search(q),
            on_iteration=lambda run: self._persist_deep_runs(),
        )
        self.agents = AgentSelectionStore(self.settings.data_dir / "agent_selection.json")
        self.templates = TemplateStore(self.settings.data_dir)
        self.schedules = ScheduleStore(self.settings.data_dir)
        self.scheduler = GoalScheduler(
            self.schedules,
            launcher=lambda goal, mode: state.launch_plan(goal, mode),
        )
        self.planner = Planner(self.registry, self.llm, self.policy)
        self.executor = PlanExecutor(
            self.registry,
            self.episodes,
            self.policy,
            self.bus,
            self.approvals,
            approval_timeout_s=self.settings.approval_timeout_s,
            max_mutations=self.settings.plan_max_mutations,
            budget_s=self.settings.plan_budget_s,
            judge=self.llm,
        )
        self.proactive = ProactiveEngine(
            self.client,
            self.suggestions,
            self.policy,
            self.bus,
            interval_s=self.settings.proactive_interval_s,
            failures=self.ingest_failures,
            episodes=self.episodes,
        )
        self.plans: dict[str, Plan] = {}
        self.session_id = uuid.uuid4().hex[:12]

    def _persist_deep_runs(self) -> None:
        path = self.settings.data_dir / "deepideas.jsonl"
        lines = [json.dumps(r.to_dict(), default=str) for r in self.deepideation.history[-10:]]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines))
        import os
        os.replace(tmp, path)

    def _load_deep_history(self) -> None:
        path = self.settings.data_dir / "deepideas.jsonl"
        if not path.exists():
            return
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    run = DeepRun(raw.get("topic", ""), raw.get("iterations", 0), raw.get("depth", 2))
                    run.id = raw.get("id", run.id)
                    run.status = raw.get("status", "done")
                    run.started = raw.get("started", run.started)
                    run.finished = raw.get("finished")
                    run.error = raw.get("error")
                    run.ideas = raw.get("ideas", [])
                    run.events = [{"ts": raw.get("started", "")}] * int(raw.get("candidates_seen", 0))
                    self.deepideation.history.append(run)
                except Exception:
                    continue
        except OSError:
            pass

    def _load_idea_history(self) -> None:
        from .backup import load_runs

        path = self.settings.data_dir / "ideas.jsonl"
        self.ideagent.history = load_runs(path, IdeaRun.from_dict)

    def _load_deep_history(self) -> None:
        from .backup import load_runs

        path = self.settings.data_dir / "deepideas.jsonl"

        def deep_factory(d: dict[str, Any]) -> DeepRun:
            run = DeepRun(d.get("topic", ""), d.get("iterations", 0), d.get("depth", 2))
            run.id = d.get("id", run.id)
            run.status = d.get("status", "done")
            run.started = d.get("started", run.started)
            run.finished = d.get("finished")
            run.error = d.get("error")
            run.ideas = d.get("ideas", [])
            return run

        self.deepideation.history = load_runs(path, deep_factory)

    async def startup(self) -> None:
        self._load_idea_history()
        self._load_deep_history()
        try:
            await self.kg.get()  # warm concept-network substrate
            self.deep_network.refresh(force=True)
        except Exception:
            logger.warning("concept network warmup skipped")
        if self.llm is not None and not await self.llm.available():
            logger.warning("LLM unreachable at %s — planner falls back to heuristics", self.settings.llm_base_url)
            self.llm = None
            self.planner.llm = None
        self.proactive.start()
        self.scheduler.start()
        self.backups.start()

    async def shutdown(self) -> None:
        await self.proactive.stop()
        await self.scheduler.stop()
        await self.backups.stop()
        for llm in self._ideagent_llms:
            if llm is not None:
                await llm.aclose()
        await self.client.aclose()
        if self.llm is not None:
            await self.llm.aclose()

    # -- goal lifecycle ------------------------------------------------------

    def _persist_plan(self, plan: Plan) -> None:
        path = self.settings.data_dir / "plans.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(plan.to_dict()) + "\n")

    async def launch_plan(
        self,
        goal_text: str,
        mode: str,
        plan: Plan | None = None,
        success_criteria: str = "",
    ) -> Plan:
        resolved = resolve_mode(mode)
        goal_episode = self.episodes.append("goal", goal_text, session_id=self.session_id)
        goal_id = goal_episode["id"]
        if plan is None:
            memory_context = self.episodes.context_for_prompt(goal_text)
            # experience replay: surface the closest past workflow as a seed
            similar = self.episodes.retrieve(goal_text, limit=3, kinds=["observation"])
            replay = [e["summary"] for e in similar if "finished: status=done" in e.get("summary", "")]
            if replay:
                memory_context += "\nSimilar past workflow that succeeded:\n" + replay[0][:200]
            # agent-profile conditioning: enabled research agents bias the planner
            try:
                selected_ids = self.agents.get()
                if selected_ids:
                    profiles = [
                        f"- {a['name']}: {a.get('tagline', '')} (workflow: {' → '.join(a.get('workflow', [])[:4])})"
                        for a in catalog_dicts()
                        if a["id"] in selected_ids
                    ]
                    if profiles:
                        memory_context += "\nActive agent profiles to emulate:\n" + "\n".join(profiles[:5])
            except Exception:
                logger.debug("agent-profile context unavailable", exc_info=True)
            plan = await self.planner.build(goal_text, memory_context=memory_context)
            plan.goal_id = goal_id
            try:
                selected_ids = self.agents.get()
                if selected_ids:
                    profile = next((a for a in catalog_dicts() if a["id"] == selected_ids[0]), None)
                    if profile:
                        plan.created_by_agent = str(profile.get("name", ""))[:60]
            except Exception:
                pass
            if success_criteria:
                setattr(plan, "verdict_criteria", success_criteria)
        self.plans[plan.id] = plan
        self._persist_plan(plan)

        async def pump() -> None:
            try:
                async for event in self.executor.run_plan(plan, goal_id, self.session_id, resolved):
                    if event.get("type") == "step_finished":
                        if event.get("tool") == "library.add_paper":
                            self._record_ingest_outcome(plan, event)
                        # Reflexion-style verbal self-correction: on failure,
                        # produce a short diagnosis that future planner calls
                        # will retrieve through episodic memory.
                        if not event.get("ok") and self.llm is not None:
                            asyncio.create_task(self._reflect_on_failure(plan, event))
                self._persist_plan_final(plan)
                if plan.status == "done" and plan.planner in ("llm", "llm-tot"):
                    try:
                        agent = getattr(plan, "created_by_agent", "") or (self.agents.get() or [""])[0]
                        self.templates.save(
                            plan.goal,
                            [{"tool": st.tool, "args": st.args} for st in plan.steps],
                            plan.planner,
                            agent,
                        )
                    except Exception:
                        logger.debug("template save failed", exc_info=True)
            except Exception:
                logger.exception("plan %s crashed", plan.id)

    async def _reflect_on_failure(self, plan: Plan, event: dict[str, Any]) -> None:
        idx = event.get("step_index")
        step = plan.steps[idx] if isinstance(idx, int) and 0 <= idx < len(plan.steps) else None
        tool = (event.get("tool") or "step")[:60]
        error = ""
        result = event.get("result") or {}
        error = str(result.get("error") or (result.get("result") or {}).get("error") or "unknown error")[:200]
        try:
            content = await self.llm.chat(
                system=(
                    "A research-agent step just failed. In one or two sentences, diagnose the most "
                    "likely cause and state the concrete adjustment for the next attempt. "
                    "Plain text only, no preamble."
                ),
                user=f"Goal: {plan.goal}\nTool: {tool}\nArgs: {json.dumps(step.args)[:300] if step else '{}'}\nError: {error}",
                num_predict=160,
            )
            reflection = content.strip()[:400]
        except Exception as exc:
            logger.debug("reflection LLM call failed: %s", exc)
            return
        self.episodes.append(
            "reflection",
            f"{tool} failed ({error}); reflection: {reflection}",
            session_id=self.session_id,
            goal_id=plan.goal_id,
            plan_id=plan.id,
            tool=tool,
            status="reflected",
        )
        self.bus.publish("reflection", {"plan_id": plan.id, "arxiv_hint": "", "reflection": reflection})

        asyncio.create_task(pump())
        return plan

    def _record_ingest_outcome(self, plan: Plan, event: dict[str, Any]) -> None:
        """Keep the ingestion failure ledger in sync with add_paper steps."""
        idx = event.get("step_index")
        step = plan.steps[idx] if isinstance(idx, int) and 0 <= idx < len(plan.steps) else None
        arxiv_id = str((step.args or {}).get("arxiv_id", "")) if step else ""
        if not arxiv_id:
            return
        failed = not event.get("ok") or inner_add_status(event.get("result")) == "error"
        if failed:
            result = event.get("result") or {}
            error = str(result.get("error") or (result.get("result") or {}).get("error") or "ingestion failed")
            entry = self.ingest_failures.record_failure(arxiv_id, error=error)
            self.bus.publish(
                "ingest_failed",
                {"arxiv_id": arxiv_id, "attempts": entry["attempts"], "error": entry.get("error", ""), "plan_id": plan.id},
            )
        else:
            self.ingest_failures.record_success(arxiv_id)
            # fresh paper/concepts should show up in KG views immediately
            self.kg.invalidate()

    def _persist_plan_final(self, plan: Plan) -> None:
        path = self.settings.data_dir / "plans_final.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(plan.to_dict()) + "\n")


state = CompanionApp()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.startup()
    yield
    await state.shutdown()


app = FastAPI(title="Fox Companion", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- request models ------------------------------------------------------------


class GoalRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    mode: str = "tiered"
    success_criteria: str = Field(default="", max_length=500)


class ModeRequest(BaseModel):
    mode: str


class DecisionRequest(BaseModel):
    approved: bool
    note: str = ""


class SuggestionDecisionRequest(BaseModel):
    mode: str = "tiered"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    mode: str = "rag"
    conversation_id: str | None = None


# -- helpers -------------------------------------------------------------------


def _hive_error(exc: HiveApiError) -> HTTPException:
    if exc.status == 0:
        return HTTPException(502, f"hive server unreachable at {state.settings.hive_api_url}")
    return HTTPException(exc.status or 500, str(exc))


# -- routes --------------------------------------------------------------------


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    hive_ok = False
    hive_info: dict[str, Any] = {}
    try:
        hive_info = await state.client.stats()
        hive_ok = True
    except HiveApiError:
        pass
    return {
        "session_id": state.session_id,
        "hive_url": state.settings.hive_api_url,
        "hive_ok": hive_ok,
        "hive_stats": hive_info,
        "llm_available": state.llm is not None,
        "llm_model": state.settings.llm_fast_model if state.llm else None,
        "autonomy_modes": MODES,
        "proactive": state.proactive.last_cycle,
        "episodes": state.episodes.stats(),
        "policy": state.policy.snapshot(),
        "ws_clients": state.bus.subscriber_count,
        "approvals_pending": len(state.approvals.pending()),
        "suggestions_open": len(state.suggestions.open()),
        "ingest_failures": state.ingest_failures.count(),
        "plans_running": sum(1 for p in state.plans.values() if p.status == "running"),
    }


@app.get("/api/tools")
async def get_tools() -> list[dict[str, Any]]:
    return state.registry.specs()


@app.post("/api/goals")
async def create_goal(req: GoalRequest) -> dict[str, Any]:
    plan = await state.launch_plan(req.goal.strip(), req.mode, success_criteria=req.success_criteria.strip())
    return plan.to_dict()


class TemplateRunRequest(BaseModel):
    mode: str = "tiered"


@app.get("/api/plans/templates")
async def list_templates() -> list[dict[str, Any]]:
    return state.templates.items()


@app.post("/api/plans/templates/{template_id}/run")
async def run_template(template_id: str, req: TemplateRunRequest) -> dict[str, Any]:
    """Case-based reasoning: re-run a saved successful workflow."""
    tpl = state.templates.get(template_id)
    if not tpl:
        raise HTTPException(404, "template not found")
    from .planner import Step

    plan = Plan(
        id=uuid.uuid4().hex[:12],
        goal_id="",
        goal=tpl["goal"],
        steps=[
            Step(index=n, tool=st["tool"], args=st.get("args", {}), rationale=f"from template {tpl['id']}")
            for n, st in enumerate(tpl["steps"])
        ],
        planner="template",
    )
    launched = await state.launch_plan(tpl["goal"], req.mode, plan=plan)
    state.templates.save(tpl["goal"], tpl["steps"], tpl["planner"], tpl.get("agent", ""))
    return launched.to_dict()


@app.delete("/api/plans/templates/{template_id}")
async def delete_template(template_id: str) -> dict[str, Any]:
    if not state.templates.delete(template_id):
        raise HTTPException(404, "template not found")
    return {"deleted": template_id}


@app.get("/api/plans")
async def list_plans() -> list[dict[str, Any]]:
    return [p.to_dict() for p in state.plans.values()]


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: str) -> dict[str, Any]:
    plan = state.plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, "plan not found")
    return plan.to_dict()


@app.post("/api/plans/{plan_id}/mode")
async def switch_mode(plan_id: str, req: ModeRequest) -> dict[str, Any]:
    mode = resolve_mode(req.mode)
    if not state.executor.set_mode(plan_id, mode):
        raise HTTPException(404, "plan not active")
    return {"plan_id": plan_id, "mode": mode.value}


@app.get("/api/approvals")
async def pending_approvals() -> list[dict[str, Any]]:
    return state.approvals.pending()


@app.get("/api/approvals/history")
async def approval_history() -> list[dict[str, Any]]:
    return state.approvals.recent()


@app.post("/api/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, req: DecisionRequest) -> dict[str, Any]:
    item = state.approvals.resolve(approval_id, req.approved, req.note)
    if item is None:
        raise HTTPException(404, "approval not found or already decided")
    state.policy.observe(f"tool:{item['tool']}", success=req.approved)
    state.episodes.append(
        "feedback",
        f"{'approved' if req.approved else 'rejected'} {item['tool']}" + (f": {req.note}" if req.note else ""),
        session_id=state.session_id,
        approval_id=approval_id,
        status="ok",
    )
    return item


@app.get("/api/suggestions")
async def open_suggestions() -> list[dict[str, Any]]:
    return state.suggestions.open()


@app.get("/api/suggestions/history")
async def suggestion_history() -> list[dict[str, Any]]:
    return state.suggestions.recent()


@app.post("/api/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str) -> dict[str, Any]:
    item = state.suggestions.decide(suggestion_id, accepted=False)
    if item is None:
        raise HTTPException(404, "suggestion not open")
    state.policy.observe(f"suggestion:{item['kind']}", success=False)
    state.bus.publish("suggestion_resolved", {"id": suggestion_id, "status": "rejected"})
    return item


@app.post("/api/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str, req: SuggestionDecisionRequest) -> dict[str, Any]:
    from .planner import Step

    item = state.suggestions.decide(suggestion_id, accepted=True)
    if item is None:
        raise HTTPException(404, "suggestion not open")
    state.policy.observe(f"suggestion:{item['kind']}", success=True)
    plan = Plan(
        id=uuid.uuid4().hex[:12],
        goal_id="",
        goal=item["title"],
        steps=[
            Step(index=0, tool=item["tool"], args=item.get("args", {}), rationale=item.get("rationale", ""))
        ],
        planner="proactive",
    )
    launched = await state.launch_plan(item["title"], req.mode, plan=plan)
    state.bus.publish("suggestion_resolved", {"id": suggestion_id, "status": "accepted"})
    return launched.to_dict()


@app.get("/api/episodes")
async def list_episodes(query: str = "", limit: int = 50, kind: str = "") -> dict[str, Any]:
    if query:
        items = state.episodes.retrieve(query, limit=min(limit, 100))
    else:
        items = state.episodes.recent(limit=min(limit, 200), kind=kind or None)
    return {"items": items}


@app.get("/api/episodes/stats")
async def episode_stats() -> dict[str, Any]:
    return state.episodes.stats()


@app.get("/api/timeline")
async def agent_timeline(limit: int = 40) -> dict[str, Any]:
    return build_timeline(state.episodes, limit=min(limit, 100))


@app.get("/api/artifacts")
async def list_artifacts() -> dict[str, Any]:
    try:
        tree = await state.client.browse()
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    return shape_artifacts(tree.get("tree", []))


@app.get("/api/artifacts/content")
async def artifact_content(path: str = "") -> dict[str, Any]:
    if not path or ".." in path:
        raise HTTPException(400, "bad path")
    try:
        data = await state.client.read_file(path)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    return {"path": path, "content": data.get("content", "")}


@app.get("/api/explorer")
async def explorer_tree() -> dict[str, Any]:
    try:
        tree = await state.client.browse()
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    return build_explorer(tree.get("tree", []))


@app.get("/api/kg")
async def kg_full() -> dict[str, Any]:
    try:
        return await state.kg.slim()
    except HiveApiError as exc:
        raise _hive_error(exc) from exc


@app.get("/api/kg/search")
async def kg_search(q: str = "") -> dict[str, Any]:
    if len(q.strip()) < 2:
        raise HTTPException(400, "query too short")
    try:
        return await state.kg.search(q)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc


@app.get("/api/artifacts/related")
async def artifact_related(path: str = "") -> dict[str, Any]:
    """Related papers + keyword concepts for an artifact, via the KG."""
    if not path or ".." in path:
        raise HTTPException(400, "bad path")
    try:
        data = await state.client.read_file(path)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    ids = extract_arxiv_ids(data.get("content", ""))
    try:
        return await state.kg.related_subgraph(ids)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc


# -- discovery & retrieval -----------------------------------------------------


class ImportRequest(BaseModel):
    arxiv_id: str = Field(min_length=4, max_length=64)
    mode: str = "tiered"


class TopicRequest(BaseModel):
    action: str  # add | remove
    topic: str = Field(min_length=2, max_length=120)


class RateRequest(BaseModel):
    kind: str = "notes"
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


@app.get("/api/discover")
async def discover() -> dict[str, Any]:
    try:
        topics, papers = await asyncio.gather(state.client.pool_topics(), state.client.pool_papers())
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    shaped = sorted(
        (shape_pool_paper(p) for p in papers),
        key=lambda p: p.get("published", ""),
        reverse=True,
    )
    topic_list = topics.get("topics", []) if isinstance(topics, dict) else []
    topic_names = [t.get("name", str(t)) if isinstance(t, dict) else str(t) for t in topic_list]
    return {"topics": topic_names, "papers": shaped}


@app.post("/api/discover/import")
async def discover_import(req: ImportRequest) -> dict[str, Any]:
    """Import a pool paper through the governed plan pipeline."""
    plan = Plan(
        id=uuid.uuid4().hex[:12],
        goal_id="",
        goal=f"import pool paper {req.arxiv_id}",
        steps=[Step(index=0, tool="library.add_paper", args={"arxiv_id": req.arxiv_id}, rationale="selected from watch pool")],
        planner="discover",
    )
    launched = await state.launch_plan(f"import {req.arxiv_id} from watch pool", req.mode, plan=plan)
    return launched.to_dict()


@app.post("/api/discover/topics")
async def discover_topics(req: TopicRequest) -> dict[str, Any]:
    try:
        if req.action == "add":
            return await state.client.pool_topic_add(req.topic.strip())
        if req.action == "remove":
            return await state.client.pool_topic_remove(req.topic.strip())
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    raise HTTPException(400, "action must be add or remove")


@app.get("/api/ingest/failures")
async def ingest_failures() -> dict[str, Any]:
    items = state.ingest_failures.items()
    return {"count": len(items), "failures": items}


@app.delete("/api/ingest/failures/{arxiv_id}")
async def dismiss_ingest_failure(arxiv_id: str) -> dict[str, Any]:
    if not state.ingest_failures.dismiss(arxiv_id):
        raise HTTPException(404, "no failure recorded for this id")
    return {"dismissed": arxiv_id}


class RetryRequest(BaseModel):
    arxiv_ids: list[str] = Field(default_factory=list)
    mode: str = "tiered"


@app.post("/api/ingest/retry")
async def ingest_retry(req: RetryRequest) -> dict[str, Any]:
    """Relaunch ingestion for failed papers through the governed plan pipeline."""
    from .planner import Step

    ids = [i for i in req.arxiv_ids if i] or [
        f["arxiv_id"] for f in state.ingest_failures.items()
    ]
    if not ids:
        raise HTTPException(400, "no failed ingestions to retry")
    steps = [
        Step(index=n, tool="library.add_paper", args={"arxiv_id": aid}, rationale="retry after failure")
        for n, aid in enumerate(ids)
    ]
    plan = Plan(
        id=uuid.uuid4().hex[:12],
        goal_id="",
        goal=f"retry {len(ids)} failed ingestion{'s' if len(ids) > 1 else ''}",
        steps=steps,
        planner="retry",
    )
    launched = await state.launch_plan(plan.goal, req.mode, plan=plan)
    return launched.to_dict()


@app.get("/api/library/search")
async def library_search(q: str = "", limit: int = 12) -> dict[str, Any]:
    if len(q.strip()) < 2:
        raise HTTPException(400, "query too short")
    import asyncio as _asyncio

    try:
        hits, papers = await _asyncio.gather(
            state.client.paper_search(q.strip()),
            state.client.papers(),
        )
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    joined = join_note_paths(hits[:limit], papers)
    return {"items": joined}


@app.post("/api/rate")
async def rate_artifact(req: RateRequest) -> dict[str, Any]:
    try:
        result = await state.client.record_feedback(req.kind, req.rating, req.comment)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    state.episodes.append(
        "feedback",
        f"rated {req.kind} {req.rating}/5" + (f": {req.comment}" if req.comment else ""),
        session_id=state.session_id,
        status="ok",
    )
    return result


# -- ideagent (novel ideas) ----------------------------------------------------


class IdeaRunRequest(BaseModel):
    topic: str = Field(min_length=4, max_length=400)
    iterations: int = Field(default=8, ge=2, le=20)
    model: str = "fast"  # fast | main


@app.post("/api/ideas/run")
async def ideas_run(req: IdeaRunRequest) -> dict[str, Any]:
    try:
        run = await state.ideagent.run(req.topic.strip(), req.iterations, req.model)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    persist_runs(state.settings.data_dir, state.ideagent.history)
    return run.to_dict()


@app.get("/api/ideas/latest")
async def ideas_latest() -> dict[str, Any]:
    if not state.ideagent.history:
        return {"status": "idle"}
    return state.ideagent.history[-1].to_dict()


@app.get("/api/ideas/history")
async def ideas_history() -> list[dict[str, Any]]:
    """All runs, newest first — GUI groups these by their query/topic."""
    persist_runs(state.settings.data_dir, state.ideagent.history)
    return [r.to_dict() for r in reversed(state.ideagent.history)]


@app.get("/api/ideas/{run_id}")
async def ideas_get(run_id: str) -> dict[str, Any]:
    for r in reversed(state.ideagent.history):
        if r.id == run_id:
            return r.to_dict()
    raise HTTPException(404, "run not found")


# -- deep ideation ---------------------------------------------------------------


class DeepIdeaRunRequest(BaseModel):
    topic: str = Field(min_length=4, max_length=400)
    iterations: int = Field(default=5, ge=2, le=12)
    depth: int = Field(default=2, ge=0, le=3)
    model: str = "fast"


@app.post("/api/deepideas/run")
async def deepideas_run(req: DeepIdeaRunRequest) -> dict[str, Any]:
    try:
        run = await state.deepideation.run(req.topic.strip(), req.iterations, req.depth, req.model)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return run.to_dict()


@app.get("/api/deepideas/latest")
async def deepideas_latest() -> dict[str, Any]:
    if not state.deepideation.history:
        return {"status": "idle"}
    return state.deepideation.history[-1].to_dict()


@app.get("/api/deepideas/history")
async def deepideas_history() -> list[dict[str, Any]]:
    return [r.to_dict() for r in reversed(state.deepideation.history)]


# -- schedules -----------------------------------------------------------------


class ScheduleRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    mode: str = "tiered"
    cadence: str = "daily"  # daily | weekly
    weekday: int = Field(default=0, ge=0, le=6)


@app.get("/api/schedules")
async def list_schedules() -> list[dict[str, Any]]:
    return state.schedules.all()


@app.post("/api/schedules")
async def add_schedule(req: ScheduleRequest) -> dict[str, Any]:
    if req.cadence not in ("daily", "weekly"):
        raise HTTPException(400, "cadence must be daily or weekly")
    return state.schedules.add(req.goal.strip(), resolve_mode(req.mode).value, req.cadence, req.weekday)


@app.delete("/api/schedules/{sid}")
async def delete_schedule(sid: str) -> dict[str, Any]:
    if not state.schedules.remove(sid):
        raise HTTPException(404, "not found")
    return {"deleted": sid}


@app.post("/api/schedules/{sid}/toggle")
async def toggle_schedule(sid: str) -> dict[str, Any]:
    item = state.schedules.toggle(sid)
    if item is None:
        raise HTTPException(404, "not found")
    return item


@app.post("/api/schedules/run-due")
async def run_due_schedules() -> dict[str, Any]:
    fired = await state.scheduler.run_pending_now()
    return {"fired": fired}


# -- agent collection --------------------------------------------------------


@app.get("/api/agents")
async def list_agents(include_fork: bool = True) -> dict[str, Any]:
    selected = set(state.agents.get())
    items = []
    for d in catalog_dicts():
        row = dict(d)
        row["enabled"] = row["id"] in selected
        row["from_fork"] = False
        items.append(row)
    fork_extra: list[dict[str, Any]] = []
    if include_fork:
        try:
            from .agents_fork import load_cached as _load_fork

            cached = _load_fork(state.settings.data_dir)
            # map curated ids for dedup (arxiv id is canonical)
            curated_arxiv = {str(a.arxiv_id) for a in __import__("hive_companion.agents_catalog", fromlist=["CATALOG"]).CATALOG if a.arxiv_id}
            curated_ids = set(CATALOG_BY_ID)
            for f in cached:
                fid = str(f.get("id", ""))
                arxiv = f.get("arxiv_id")
                if fid in curated_ids or (arxiv and str(arxiv) in curated_arxiv):
                    continue
                # synthesize a full agent card from fork entry
                cat = f.get("category", "ideation")
                row = {
                    "id": fid,
                    "name": f.get("name", fid)[:40],
                    "category": cat,
                    "tagline": f.get("tagline", f.get("paper_title", ""))[:120],
                    "description": f.get("paper_title", ""),
                    "paper_title": f.get("paper_title", ""),
                    "paper_url": f.get("paper_url", ""),
                    "arxiv_id": arxiv,
                    "capabilities": [],
                    "workflow": ["read paper", "apply workflow"],
                    "icon": f.get("icon", "🤖"),
                    "color": f.get("color", "#8b96a8"),
                    "implemented": False,
                    "autonomy": "tiered",
                    "tags": ["from-fork"],
                    "enabled": fid in selected,
                    "from_fork": True,
                }
                fork_extra.append(row)
        except Exception:
            pass
    items.extend(fork_extra)
    return {
        "categories": CATEGORY_LABEL,
        "agents": items,
        "selected_ids": sorted(selected),
        "fork_extra": len(fork_extra),
    }


@app.get("/api/agents/selection")
async def get_agent_selection() -> dict[str, Any]:
    return {"selected_ids": state.agents.get()}


class AgentSelectionIn(BaseModel):
    selected_ids: list[str] = Field(default_factory=list)


@app.post("/api/agents/selection")
async def set_agent_selection(body: AgentSelectionIn) -> dict[str, Any]:
    # allow both curated and fork ids — validate against union
    allowed: set[str] = set(CATALOG_BY_ID)
    try:
        from .agents_fork import load_cached as _load_fork

        for f in _load_fork(state.settings.data_dir):
            fid = str(f.get("id", ""))
            if fid:
                allowed.add(fid)
    except Exception:
        pass
    valid = [str(x) for x in body.selected_ids if str(x) in allowed]
    # if fork cache empty and user tries to set fork ids, keep them anyway (relax)
    if not valid and body.selected_ids:
        # fallback: allow any non-empty slug (lets new fork agents be selected before cache loads)
        valid = [str(x).strip() for x in body.selected_ids if str(x).strip()]
        valid = valid[:20]
    saved = state.agents.set(valid)
    return {"selected_ids": saved}


@app.post("/api/agents/refresh")
async def refresh_agents_from_fork() -> dict[str, Any]:
    """Fetch your fork's ai-scientist.md, parse, cache, and return summary.

    Source: https://github.com/harishgovardhandamodar/ai-agent-papers
    """
    from .agents_fork import FORK_URL, fetch_and_cache, load_cached

    try:
        result = await fetch_and_cache(state.settings.data_dir, url=FORK_URL)
    except Exception as exc:
        # offline / fork unreachable: keep serving the last cached catalog
        cached = load_cached(state.settings.data_dir)
        if not cached:
            raise HTTPException(502, f"fork fetch failed and no cache exists: {exc}") from exc
        return {
            "fetched_at": 0,
            "count": len(cached),
            "agents": cached,
            "source": "cache",
            "warning": f"fetch failed, serving cached agents: {str(exc)[:200]}",
        }
    return {
        "source": result["source"],
        "count": result["count"],
        "fetched_at": result["fetched_at"],
        "cache_path": result["cache_path"],
    }


@app.get("/api/agents/fork")
async def get_fork_agents() -> dict[str, Any]:
    from .agents_fork import FORK_URL, load_cached

    agents = load_cached(state.settings.data_dir)
    return {"source": FORK_URL, "count": len(agents), "agents": agents}


@app.get("/api/weekdays")
async def weekdays() -> list[str]:
    return WEEKDAYS


# -- backups -------------------------------------------------------------------


@app.get("/api/backups")
async def backups_list() -> dict[str, Any]:
    return {
        "snapshots": list_snapshots(state.settings.data_dir),
        "last_snapshot": state.backups.last_snapshot,
        "last_error": state.backups.last_error,
    }


@app.post("/api/backups/run")
async def backups_run_now() -> dict[str, Any]:
    arc = create_snapshot(state.settings.data_dir)
    if arc is None:
        raise HTTPException(400, "no store files to snapshot")
    return {"snapshot": arc.name, "bytes": arc.stat().st_size}


# -- citations & comparison ----------------------------------------------------


@app.get("/api/cite")
async def cite_paper(
    arxiv_id: str = "",
    title: str = "",
    authors: str = "",
    published: str = "",
) -> dict[str, Any]:
    if len(arxiv_id) < 4:
        raise HTTPException(400, "arxiv_id required")
    # prefer library metadata when the paper is ingested
    try:
        papers = await state.client.papers()
        for p in papers:
            if str(p.get("id", "")).split("v")[0] == arxiv_id.split("v")[0]:
                title = p.get("title") or title
                authors = p.get("authors") or authors
                published = p.get("published") or published
                break
    except HiveApiError:
        pass
    return {"arxiv_id": arxiv_id, "bibtex": bibtex(arxiv_id, title, authors, published)}


@app.post("/api/similarity")
async def similarity_route(body: dict[str, Any]) -> Any:
    paper_ids = body.get("paper_ids") or []
    if not isinstance(paper_ids, list) or len(paper_ids) < 2:
        raise HTTPException(400, "provide at least two paper_ids")
    try:
        return await state.client.similarity([str(x) for x in paper_ids])
    except HiveApiError as exc:
        raise _hive_error(exc) from exc


@app.get("/api/statusbar")
async def status_bar() -> dict[str, Any]:
    plans_by_status: dict[str, int] = {}
    plan_progress: list[dict[str, Any]] = []
    for plan in state.plans.values():
        if plan.status in ("running", "ready"):
            plans_by_status["running"] = plans_by_status.get("running", 0) + 1
            total = len(plan.steps)
            done = sum(1 for s in plan.steps if s.state in ("done", "failed", "skipped"))
            cur = next((s for s in plan.steps if s.state in ("running", "awaiting_approval")), None)
            progress = (done / total) if total else 0
            plan_progress.append(
                {
                    "id": plan.id,
                    "goal": plan.goal[:80],
                    "status": plan.status,
                    "total": total,
                    "done": done,
                    "progress": round(progress, 3),
                    "current_tool": cur.tool if cur else (plan.steps[done].tool if done < total else ""),
                    "current_state": cur.state if cur else "pending",
                }
            )
    snapshot = await collect_statusbar(
        state.client,
        plans_by_status,
        approvals_pending=len(state.approvals.pending()),
        suggestions_open=len(state.suggestions.open()),
        fox_step_episodes=state.episodes.recent(kind="step", limit=300),
        ingest_failures=state.ingest_failures.count(),
    )
    snapshot["episodes"] = state.episodes.stats()["count"]
    snapshot["last_scan"] = state.proactive.last_cycle.get("at")
    snapshot["plan_progress"] = plan_progress
    snapshot["ingest_failures"] = state.ingest_failures.count()
    return snapshot


@app.get("/api/artifacts/raw")
async def artifact_raw(path: str = "") -> Response:
    """Binary passthrough so figures inside note markdown render in the GUI."""
    if not path or ".." in path:
        raise HTTPException(400, "bad path")
    try:
        blob, content_type = await state.client.get_raw(path)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    return Response(content=blob, media_type=content_type)


@app.get("/api/sessions/current/summary")
async def current_session() -> dict[str, Any]:
    return state.episodes.summarize_session(state.session_id)


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    recalled = state.episodes.retrieve(req.message, limit=4)
    try:
        payload = await state.client.fox_chat(req.message, mode=req.mode, conversation_id=req.conversation_id)
    except HiveApiError as exc:
        raise _hive_error(exc) from exc
    state.episodes.append(
        "conversation",
        f"Q: {req.message[:160]} A: {str(payload.get('answer', ''))[:160]}",
        session_id=state.session_id,
        fox_conversation=payload.get("conversation_id"),
        mode=req.mode,
        grounded=bool(payload.get("grounded")),
    )
    payload["memory_recalled"] = [
        {"kind": e["kind"], "ts": e["ts"], "summary": e["summary"]} for e in recalled
    ]
    return payload


@app.get("/api/policy")
async def policy_snapshot() -> dict[str, Any]:
    return state.policy.snapshot()


@app.post("/api/proactive/run")
async def run_proactive_now() -> dict[str, Any]:
    created = await state.proactive.run_cycle()
    return {"created": created, "cycle": state.proactive.last_cycle}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    qid, queue = state.bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        state.bus.unsubscribe(qid)


# -- static frontend (built React bundle) --------------------------------------


def _resolve_dist_dir() -> Path:
    """Repo checkout layout by default; containers override via env."""
    configured = os.environ.get("COMPANION_FRONTEND_DIST", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


_dist_dir = _resolve_dist_dir()

_NOT_BUILT_PAGE = """<!doctype html><html><head><title>Fox Companion — frontend not built</title></head>
<body style="font-family:system-ui;background:#0e1116;color:#d7dee9;padding:40px;line-height:1.6">
<h2>Fox Companion frontend not built yet</h2>
<p>The API is running fine — only the React UI is missing.</p>
<pre style="background:#1c2330;padding:14px;border-radius:8px">npm --prefix companion/frontend install
npm --prefix companion/frontend run build</pre>
<p>Then restart this process and reload. Meanwhile, the API is under
<code>/api/state</code>, <code>/api/goals</code>, <code>/api/suggestions</code>,
<code>/api/episodes</code> (docs: docs/companion.md).</p>
</body></html>"""


from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402 (top-level import ok)


class _NoCacheAssets(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        path = request.url.path
        # hashed assets are safe to cache; index.html must revalidate so a
        # stale page can't keep pointing at an old bundle after redeploy
        if path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif not path.startswith("/api/") and (path == "/" or "." not in path or path.endswith(".html")):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.add_middleware(_NoCacheAssets)

app.mount(
    "/assets",
    StaticFiles(directory=_dist_dir / "assets", check_dir=False),
    name="assets",
)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str) -> Any:
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(404, "not found")
    candidate = _dist_dir / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    index = _dist_dir / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(_NOT_BUILT_PAGE)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "hive_companion.main:app",
        host=state.settings.host,
        port=state.settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
