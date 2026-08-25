# Agentic Workflows — Fox Companion

A reference for every agentic capability in the Fox Companion: the core
execution loop, the research-pattern add-ons built on top of it, and how to
operate each one. Research lineage is noted per feature.

---

## 1. Core agent loop

```
goal ─▶ Planner (LLM + critic + best-of-N) ─▶ PlanExecutor ─▶ episodes / policy / bus
                 ▲                                    │
        episodic memory │ reflections │ agent profiles │ templates
                 └──────────────────────────────────────┘
```

- **Planner** (`planner.py`) turns a goal into a validated tool plan. LLM path
  first; a heuristic planner covers common goal shapes when no LLM is
  available. Steps are validated against the tool registry (unknown tools and
  missing args are dropped with a log line).
- **PlanExecutor** (`executor.py`) walks steps under an autonomy mode:
  - `approve` — every mutating step waits for explicit approval.
  - `tiered` — read-only steps run automatically; mutations wait.
  - `auto` — everything runs unattended once submitted.
- **Reinforcement policy** (`policy.py`) records every tool/suggestion outcome
  in a sliding window and converts it into planner hints and suggestion scores.

Every step, plan, goal, reflection and verdict becomes an **episodic memory**
record (`episodic.py`), which is what later planning rounds retrieve as
context. The store is bounded (compacted to 5 000 episodes) and cached in
memory for cheap status-bar polling.

## 2. Planning add-ons

| Feature | Pattern | What happens |
|---|---|---|
| Best-of-N planning | Tree-of-Thought (lite) | When the LLM plans, a second draft is generated; both are critic-scored 0–10 and the higher wins by ≥0.5 margin. Plans carry `planner: llm-tot`. |
| Plan critic | Self-Refine / LLM-as-critic | The drafted plan gets a pre-flight critique pass that drops redundant or off-goal steps before anything executes. Failures degrade silently to the drafted plan. |
| Agent-profile conditioning | Role-based agents (MetaGPT/CAMEL) | Enabled profiles from the Agents tab are injected into planning context ("Active agent profiles to emulate"), biasing tool choice toward that workflow. The originating profile is recorded on the plan (`created_by_agent`). |
| Experience replay | Case-based reasoning | The closest past *successful* workflow summary is retrieved into planning context as a seed ("Similar past workflow that succeeded"). |
| Bandit-grade hints | Multi-armed bandit | Planner hints quote measured evidence — e.g. `library.add_paper (92% over 12 runs)` — from the policy's per-tool success statistics instead of vague adjectives. |

## 3. Execution add-ons

| Feature | Pattern | What happens |
|---|---|---|
| Parallel read-only batches | Parallel tool use | Consecutive read-only steps run concurrently via `asyncio.gather` (batches of ≤3). Mutating steps always run alone. |
| Reflexion | Shinn et al., *Reflexion* (2023) | A failed step triggers an LLM diagnosis (likely cause + concrete next-attempt adjustment), stored as a `reflection` episode that future planners retrieve through episodic memory. |
| Mutation budget | Cost-aware agents | At most `COMPANION_PLAN_MAX_MUTATIONS` (default 6) mutating steps run per plan; excess mutations are skipped with a recorded reason. |
| Time budget | Cost-aware agents | Plans exceeding `COMPANION_PLAN_BUDGET_S` (default 1800 s) skip all remaining pending steps and mark the plan `budget_hit`. |
| Earned autonomy | Learned trust | Under `tiered`, a mutating tool with ≥90 % success over ≥5 runs auto-approves itself (never under `approve`). Logged as "earned autonomy". |
| Success-criteria verdicts | Self-evaluation / verifier | Goals accept optional `success_criteria`; after execution an LLM judge grades the step transcript against them and files a pass/fail `verdict` episode. |

## 4. Memory add-ons

| Feature | Pattern | What happens |
|---|---|---|
| Recency-weighted recall | Generative Agents | Retrieval multiplies keyword overlap by a 30-day half-life decay so recent experience dominates planner/chat context without erasing history. |
| `memory.reflect` tool | Generative Agents reflection | Distills the last ~200 episodes into ≤5 durable insight episodes about the researcher's interests and workflow patterns. Registered as a mutating tool, callable by plans or suggestions. |
| Consolidation nudge | same | The proactive engine suggests consolidation when 150+ episodes sit undistilled (deduped per 150-episode block). |

## 5. Ideation add-ons

| Feature | Pattern | What happens |
|---|---|---|
| Cross-run novelty dedup | Novelty search / QD | IDEAgent suppresses candidates whose titles are near-duplicates (token-Jaccard ≥ 0.72) of ideas archived by earlier runs; counted per run as `duplicates`. Within-run variety remains the job of QD archive cells. |
| Self-consistency judging | Wang et al., self-consistency | If a judge vote lands on all-defaults (5/5/5 — i.e. unusable output), one decisive re-vote is taken with an explicit anti-default instruction before settling. |
| Loud failures | — | Runs where every iteration fails end `failed` with the last error instead of silently reporting `done` with zero ideas. Deep Ideation behaves identically for explored pairs. |
| Adversarial debate | Du et al., multi-agent debate | Deep Ideation inserts a skeptic pass per idea: the strongest technical objection is generated, then the refinement critic must address it. Objections persist on the idea (`adversarial_objection`). |

## 6. Trust & verification add-ons

| Feature | Pattern | What happens |
|---|---|---|
| `verify.attribution` tool | RARR attribution | Extracts arxiv ids cited in any vault note and checks they exist in the library — flags hallucinated references (`checked / known / missing`). |
| Graph grounding | — | Ideation candidates are conditioned on knowledge-graph concepts; the KG cache refreshes on every successful ingestion so new material flows in immediately. |

## 7. Plan template library (plan-library pattern)

Successful LLM plans auto-save to `plan_templates.py` storage, upserted by
normalized goal shape (re-runs increment a use counter instead of duplicating).

- `GET /api/plans/templates` — list (most-used first)
- `POST /api/plans/templates/{id}/run` — re-execute a saved workflow under a chosen autonomy mode
- `DELETE /api/plans/templates/{id}` — retire one

The GoalComposer renders a "saved workflows" dropdown with use counts; loading
a template prefills the goal text.

## 8. Surfacing in the GUI

| Where | What you see |
|---|---|
| Status bar | hive/llm dots, papers/notes counts, ⏸ approvals · 💡 suggestions · ✖ failed-ingestion badges, scan-now with last-scan time |
| JobsBar | running plans w/ progress, fox survey jobs, failed-ingest chip |
| PlanCard | step states incl. ⏸ earned-auto and ⤼ budget-skips, args chips, keyboard-toggable header |
| Timeline | decision-node glyphs: ⚖ verdicts (✅ pass / ❌ fail), 🪞 reflections, 💡 insights, ⏸ skips |
| Discover | failed-ingestions strip (rerun / retry-all / dismiss), live pool updates, filter box |
| SuggestionsFeed | ingest_retry, memory_consolidation, pool_import, topic_drift, digest suggestions — accept launches governed plans |
| IDEAgent | dupes counter, explicit failure banners, markdown-free card grid |

## 9. Configuration

| Env var | Default | Controls |
|---|---|---|
| `COMPANION_PLAN_MAX_MUTATIONS` | 6 | mutating steps allowed per plan |
| `COMPANION_PLAN_BUDGET_S` | 1800 | wall-clock budget per plan |
| `COMPANION_APPROVAL_TIMEOUT` | 1800 s | how long an approval wait lasts before skipping |
| `COMPANION_PROACTIVE_INTERVAL` | 300 s | proactive signal scan cadence |

## 10. Tests

Agentic behaviour is covered by:

- `tests/test_agent.py` — executor basics, failure recording, approvals
- `tests/test_agentic.py` — parallel batching, mutation budgets, novelty dedup
- `tests/test_agentic2.py` — earned-autonomy trust thresholds, bandit hints,
  template store upsert/delete
- `tests/test_ingest_failures.py`, `tests/test_gaps.py`,
  `tests/test_round2.py`, `tests/test_round3.py` — supporting features
