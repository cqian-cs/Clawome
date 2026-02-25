"""Execution Workflow — perceive → plan → act → sense loop with flow check.

Structure:
  init_subtask → perceive → step_planner → execute_action → sense_result → flow_check
                   ↑                                             |              |
                   |── perceive ← (no signals, continue loop) ──┘              |
                   |── page_doctor ← (sense or flow triggers) ─────────────────┘
                   |
                   END ← (subtask done OR flow anomaly needs agent_decision)

page_doctor is NOT in the default path — only entered when sense_result
or flow_check explicitly routes to it (obstacle detected, high error rate).
"""

from langgraph.graph import StateGraph, END

from v3.models.schemas import AgentState
from utils.workflow_trace import traced
from agent_config import settings

# Executor nodes
from v3.nodes.executor.init_subtask import init_subtask_node
from v3.nodes.executor.page_doctor import page_doctor_node
from v3.nodes.executor.perceive import perceive_node
from v3.nodes.executor.execute_action import execute_action_node
from v3.nodes.executor.sense_result import sense_result_node

# Agent node (step planning is a decision)
from v3.agent.step_planner import step_planner_node

# Flow signal detection (rules only, from agent_decision module)
from v3.agent.agent_decision import detect_flow_signals

import asyncio
import run_context


# ── Flow check node (rules only, zero LLM) ──────────────────────


async def flow_check_node(state: AgentState) -> dict:
    """Run flow anomaly detection rules. Store signals for routing."""
    if run_context.is_cancelled():
        raise asyncio.CancelledError("Task cancelled by user")

    global_step = state.global_step_count
    interval = settings.agent.supervisor_interval

    # Gate: only check every N steps
    if global_step > 0 and global_step < state.last_supervisor_step + interval:
        return {"flow_signals": []}

    signals = detect_flow_signals(state)
    if signals:
        print(f"  [flow_check] Signals ({len(signals)}):")
        for s in signals:
            print(f"    - {s}")

    return {"flow_signals": signals, "last_supervisor_step": global_step}


# ── Routers ──────────────────────────────────────────────────────


def sense_router(state: AgentState) -> str:
    """Route after sense_result: done → exit, page_doctor, or flow_check."""
    signal = state.sense_signal
    if signal == "done":
        return "done"
    if signal == "page_doctor":
        return "page_doctor"
    return "flow_check"


def flow_check_router(state: AgentState) -> str:
    """Route after flow_check: no signals → continue, high_error → page_doctor, serious → exit."""
    signals = state.flow_signals

    if not signals:
        return "continue"

    # High error rate → page_doctor (stay in loop)
    if any("high_error_rate" in s for s in signals):
        return "page_doctor"

    # Serious anomalies → exit to agent_decision for intervention
    _SERIOUS = ("stuck", "approaching_limit", "repeated_failure")
    if any(kw in s for s in signals for kw in _SERIOUS):
        return "exit"

    # Mild signals (e.g., loop_detected alone) → stay in execution loop
    return "continue"


# ── Workflow builder ─────────────────────────────────────────────


def build_execution_workflow():
    """Build the execution sub-graph: PPAS loop + flow check."""
    g = StateGraph(AgentState)

    # ── Nodes ──────────────────────────────────────────────
    g.add_node("init_subtask", traced("init_subtask", "execution", init_subtask_node))
    g.add_node("perceive", traced("perceive", "execution", perceive_node))
    g.add_node("step_planner", traced("step_planner", "execution", step_planner_node))
    g.add_node("execute_action", traced("execute_action", "execution", execute_action_node))
    g.add_node("sense_result", traced("sense_result", "execution", sense_result_node))
    g.add_node("flow_check", traced("flow_check", "execution", flow_check_node))
    g.add_node("page_doctor", traced("page_doctor", "execution", page_doctor_node))

    # ── Edges ──────────────────────────────────────────────
    g.set_entry_point("init_subtask")
    g.add_edge("init_subtask", "perceive")          # direct to perceive, skip page_doctor
    g.add_edge("perceive", "step_planner")
    g.add_edge("step_planner", "execute_action")
    g.add_edge("execute_action", "sense_result")

    g.add_conditional_edges("sense_result", sense_router, {
        "done": END,
        "page_doctor": "page_doctor",
        "flow_check": "flow_check",
    })

    g.add_conditional_edges("flow_check", flow_check_router, {
        "continue": "perceive",
        "page_doctor": "page_doctor",
        "exit": END,
    })

    # page_doctor always returns to perceive (re-read the cleaned page)
    g.add_edge("page_doctor", "perceive")

    return g.compile()
