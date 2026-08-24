"""Companion backend entrypoint — FastAPI app serving REST + WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .autonomy import MODES, AutonomyMode, resolve_mode
from .episodic import EpisodeStore
from .events import EventBus
from .executor import ApprovalStore, PlanExecutor
from .hive_client import HiveApiError, HiveClient
from .llm import ChatClient
from .planner import Plan, Planner
from .policy import ReinforcementPolicy
from .proactive import ProactiveEngine, SuggestionStore
from .settings import load_settings
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
        self.registry = ToolRegistry(self.client)
        self.llm: ChatClient | None = ChatClient(self.settings.llm_base_url, self.settings.llm_fast_model)
        self.planner = Planner(self.registry, self.llm, self.policy)
        self.executor = PlanExecutor(
            self.registry,
            self.episodes,
            self.policy,
            self.bus,
            self.approvals,
            approval_timeout_s=self.settings.approval_timeout_s,
        )
        self.proactive = ProactiveEngine(
            self.client,
            self.suggestions,
            self.policy,
            self.bus,
            interval_s=self.settings.proactive_interval_s,
        )
        self.plans: dict[str, Plan] = {}
        self.session_id = uuid.uuid4().hex[:12]

    async def startup(self) -> None:
        if self.llm is not None and not await self.llm.available():
            logger.warning("LLM unreachable at %s — planner falls back to heuristics", self.settings.llm_base_url)
            self.llm = None
            self.planner.llm = None
        self.proactive.start()

    async def shutdown(self) -> None:
        await self.proactive.stop()
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
    ) -> Plan:
        resolved = resolve_mode(mode)
        goal_episode = self.episodes.append("goal", goal_text, session_id=self.session_id)
        goal_id = goal_episode["id"]
        if plan is None:
            memory_context = self.episodes.context_for_prompt(goal_text)
            plan = await self.planner.build(goal_text, memory_context=memory_context)
            plan.goal_id = goal_id
        self.plans[plan.id] = plan
        self._persist_plan(plan)

        async def pump() -> None:
            try:
                async for _event in self.executor.run_plan(plan, goal_id, self.session_id, resolved):
                    pass  # executor already publishes to the bus
                self._persist_plan_final(plan)
            except Exception:
                logger.exception("plan %s crashed", plan.id)

        asyncio.create_task(pump())
        return plan

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


app = FastAPI(title="Hive Research Companion", version="0.1.0", lifespan=lifespan)
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
    }


@app.get("/api/tools")
async def get_tools() -> list[dict[str, Any]]:
    return state.registry.specs()


@app.post("/api/goals")
async def create_goal(req: GoalRequest) -> dict[str, Any]:
    plan = await state.launch_plan(req.goal.strip(), req.mode)
    return plan.to_dict()


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

_dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


if _dist_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = _dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist_dir / "index.html")


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
