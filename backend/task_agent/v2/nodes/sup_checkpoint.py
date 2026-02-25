"""Supervision Checkpoint — orchestrates the supervision layer.

Inserted between sense_result and perceive in the execution loop.
Runs both Flow Supervisor and Info Checker rule layers, then delegates
to Master Supervisor when signals are present.

Flow:
  1. Check if supervision is due (every N steps)
  2. Run Flow Supervisor rules → flow_signals
  3. Run Info Checker rules → info_signals
  4. Master fast-path: if no signals → continue (zero LLM cost)
  5. Master LLM: if signals present → synthesize and decide
  6. Execute intervention based on Master decision

Most cycles: zero LLM cost (both rule layers clear → Master returns "continue").
"""

import asyncio

from v2.models.schemas import AgentState
from agent_config import settings
from shared.result_helpers import collect_partial_result
import run_context

from v2.nodes.sup_flow_supervisor import detect_flow_signals
from v2.nodes.sup_info_checker import detect_info_signals
from v2.nodes.sup_master import master_decide_rule, master_diagnose


async def supervision_checkpoint_node(state: AgentState) -> dict:
    """Run the dual-channel supervision check."""
    if run_context.is_cancelled():
        raise asyncio.CancelledError("Task cancelled by user")

    task = state.task
    memory = state.memory
    global_step = state.global_step_count
    interval = settings.agent.supervisor_interval

    # ── Gate: only run every N steps ──────────────────────────
    if global_step > 0 and global_step < state.last_supervisor_step + interval:
        # Not due yet — pass through
        return {}

    print(f"\n  [supervision] Checkpoint at step {global_step}")

    # ── 1. Flow Supervisor rules ──────────────────────────────
    flow_signals = detect_flow_signals(state)
    if flow_signals:
        print(f"  [supervision] Flow signals ({len(flow_signals)}):")
        for s in flow_signals:
            print(f"    - {s}")

    # ── 2. Info Checker rules ─────────────────────────────────
    info_signals = detect_info_signals(state)
    if info_signals:
        print(f"  [supervision] Info signals ({len(info_signals)}):")
        for s in info_signals:
            print(f"    - {s}")

    # ── 3. Master decision ────────────────────────────────────
    # Fast-path: rule-based
    rule_decision = master_decide_rule(flow_signals, info_signals)

    if rule_decision == "continue":
        print("  [supervision] No anomalies → continue")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="periodic check",
            assessment="no anomaly patterns",
            action="continue",
        )
        task.save()
        return {"last_supervisor_step": global_step}

    if rule_decision == "wrap_up":
        # Info sufficient, no flow issues → wrap up early
        partial = collect_partial_result(memory, state.browser)
        conclusion = partial or "; ".join(memory.findings[-3:]) if memory.findings else ""
        subtask = task.get_current_subtask()
        if subtask:
            task.complete_subtask(subtask.step, result=conclusion)
        print(f"  [supervision] Info sufficient → wrap_up")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="; ".join(info_signals[:3]),
            assessment="Information sufficient for task completion",
            action="wrap_up",
            details=f"Conclusion: {conclusion[:100]}",
        )
        task.save()
        return {
            "task": task,
            "memory": memory,
            "current_action": {"action": "done", "result": conclusion, "_source": "supervisor"},
            "last_supervisor_step": global_step,
            "sense_signal": "done",
        }

    # ── Need LLM diagnosis ────────────────────────────────────
    triggers = flow_signals + info_signals
    print(f"  [supervision] Signals detected, calling Master LLM...")

    data = await master_diagnose(state, flow_signals, info_signals)
    action = data.get("action", "continue")
    reason = data.get("reason", "")
    conclusion = data.get("conclusion", "")
    suggestion = data.get("suggestion", "")

    subtask = task.get_current_subtask()

    # ── 4. Execute intervention ───────────────────────────────
    if action == "force_done" and subtask:
        partial = collect_partial_result(memory, state.browser)
        result = conclusion or partial or reason
        task.complete_subtask(subtask.step, result=result)
        print(f"  [supervision] Force-completed subtask {subtask.step}: {reason}")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="; ".join(triggers[:3]),
            assessment=reason,
            action="force_done",
            details=f"Subtask {subtask.step} force-completed: {result[:100]}",
        )
        task.save()
        return {
            "task": task,
            "memory": memory,
            "llm_usage": state.llm_usage,
            "current_action": {"action": "done", "result": result, "_source": "supervisor"},
            "last_supervisor_step": global_step,
            "sense_signal": "done",
        }

    if action == "wrap_up":
        if subtask:
            partial = collect_partial_result(memory, state.browser)
            result = conclusion or partial or reason
            task.complete_subtask(subtask.step, result=result)
        task.replan_remaining([])
        print(f"  [supervision] Wrapping up: {reason}")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="; ".join(triggers[:3]),
            assessment=reason,
            action="wrap_up",
            details=f"Wrapped up: {conclusion[:100]}",
        )
        task.save()
        return {
            "task": task,
            "memory": memory,
            "llm_usage": state.llm_usage,
            "current_action": {"action": "done", "result": conclusion, "_source": "supervisor"},
            "last_supervisor_step": global_step,
            "sense_signal": "done",
        }

    if action == "redirect":
        print(f"  [supervision] Redirect: {reason} — suggestion: {suggestion}")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="; ".join(triggers[:3]),
            assessment=reason,
            action="redirect",
            details=suggestion,
        )
        task.save()
        # Continue execution but the next perceive will see the redirect log
        return {
            "last_supervisor_step": global_step,
            "llm_usage": state.llm_usage,
        }

    if action == "page_doctor":
        print(f"  [supervision] Triggering page_doctor: {reason}")
        task.add_supervisor_log(
            global_step=global_step,
            trigger="; ".join(triggers[:3]),
            assessment=reason,
            action="page_doctor",
        )
        task.save()
        return {
            "last_supervisor_step": global_step,
            "llm_usage": state.llm_usage,
            "sense_signal": "page_doctor",
        }

    # Default: continue
    print(f"  [supervision] Continuing: {reason}")
    task.add_supervisor_log(
        global_step=global_step,
        trigger="; ".join(triggers[:3]),
        assessment=reason,
        action="continue",
    )
    task.save()
    return {
        "last_supervisor_step": global_step,
        "llm_usage": state.llm_usage,
    }
