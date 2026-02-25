"""Master Supervisor — synthesize Flow + Info signals into a decision.

Like a director hearing from both the project manager (Flow) and
the research assistant (Info), then making the final call.

Decision matrix:
  Flow normal + Info insufficient  → continue
  Flow normal + Info sufficient    → wrap_up (early finish)
  Flow loop   + Info insufficient  → redirect (change approach)
  Flow loop   + Info sufficient    → force_done
  Flow stuck  + any               → force_done
  Flow limit  + Info partial      → wrap_up
  Flow errors + any               → page_doctor
  Flow normal + Info unreliable   → redirect (verify from better source)

LLM call: Only when signals exist. Zero cost when both rule layers clear.
"""

import json
import time

from langchain_core.messages import SystemMessage, HumanMessage

from llm import get_llm
from v2.models.schemas import AgentState
from agent_config import settings
from utils import extract_json, tlog
from shared.result_helpers import collect_partial_result


MASTER_SYSTEM = """\
You are a task execution supervisor. You receive anomaly signals from two monitoring channels and must decide how to intervene.

[Overall Task]
{task}

[Current Subtask]
Step {current_step}: {current_goal} (executed {action_count}/{max_steps} steps)

[Completed Subtasks]
{completed_summary}

[Key Findings Collected]
{findings}

[Flow Supervisor Signals (process anomalies)]
{flow_signals}

[Info Checker Signals (information quality)]
{info_signals}

Analyze the signals and return a JSON decision:

{{"action": "continue", "reason": "brief explanation"}}
— No intervention needed, execution is progressing normally.

{{"action": "force_done", "reason": "problem description", "conclusion": "conclusion based on available information"}}
— Current subtask should be force-completed (target info doesn't exist or was already obtained).

{{"action": "wrap_up", "reason": "information is sufficient", "conclusion": "complete final conclusion"}}
— Collected information is sufficient; skip remaining work, enter evaluation.

{{"action": "redirect", "reason": "current approach is ineffective", "suggestion": "try a different search query or website"}}
— Current approach has problems; provide a new direction.

{{"action": "page_doctor", "reason": "page obstacles detected"}}
— High error rate suggests page issues; trigger page repair.

Rules:
- Return JSON only
- If the same URL has been visited 3+ times without new findings, the page likely doesn't have what we need → force_done
- If 2+ subtasks failed for similar goals, the information likely doesn't exist → force_done
- If collected findings already answer the user's question → wrap_up
- Prefer noting "information not found on official sources" rather than letting execution spin indefinitely
- If no obvious anomaly is present, return continue

[Response Language]
You MUST respond in {language}."""


def master_decide_rule(flow_signals: list[str], info_signals: list[str]) -> str | None:
    """Fast-path rule-based decision. Returns action string or None (needs LLM).

    Zero LLM cost when no signals from either channel.
    """
    has_flow = bool(flow_signals)
    has_info = bool(info_signals)

    # No signals at all → continue (zero cost)
    if not has_flow and not has_info:
        return "continue"

    # Info sufficient + no flow issues → wrap_up (no LLM needed)
    if not has_flow and any("info_sufficient" in s for s in info_signals):
        return "wrap_up"

    # Both have signals → need LLM to synthesize
    return None


async def master_diagnose(
    state: AgentState,
    flow_signals: list[str],
    info_signals: list[str],
) -> dict:
    """LLM diagnosis when rule layer can't decide. Returns decision dict."""
    task = state.task
    memory = state.memory
    subtask = task.get_current_subtask()

    findings = "(none)"
    if memory.findings:
        findings = "\n".join(f"  - {f}" for f in memory.findings)

    flow_text = "\n".join(f"  - {s}" for s in flow_signals) if flow_signals else "(none)"
    info_text = "\n".join(f"  - {s}" for s in info_signals) if info_signals else "(none)"

    prompt = MASTER_SYSTEM.format(
        task=task.description,
        current_step=subtask.step if subtask else "?",
        current_goal=subtask.goal if subtask else "(none)",
        action_count=state.action_count,
        max_steps=settings.agent.max_steps,
        completed_summary=task.get_completed_summary(),
        findings=findings,
        flow_signals=flow_text,
        info_signals=info_text,
        language=task.language or "English",
    )

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="Analyze the signals and decide whether intervention is needed."),
    ]

    llm = get_llm()
    task.start_llm_step("master_supervisor")
    tlog("[master] LLM call start")
    t0 = time.time()
    response = await llm.ainvoke(messages)
    d = int((time.time() - t0) * 1000)
    state.llm_usage.add(response, node="master_supervisor", messages=messages, duration_ms=d)
    task.complete_llm_step(d, summary="Supervising execution…")
    tlog(f"[master] LLM ({d}ms): {response.content[:200]}")

    try:
        data = extract_json(response.content)
    except (json.JSONDecodeError, TypeError):
        print("  [master] JSON parse failed, defaulting to continue")
        return {"action": "continue", "reason": "LLM parse failed"}

    return data
