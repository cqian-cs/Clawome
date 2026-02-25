"""Execution Workflow — dual-dimension execution sub-graph.

Structure:
  init_subtask → page_doctor → perceive → plan_step → execute_action → sense_result
                                  ↑                                         |
                                  |              supervision_checkpoint      |
                                  |                    |                     |
                                  +--------------------+---------------------+
                                  ↑                    |
                                  +--- page_doctor <---+ (if page_doctor signal)

Routes:
  sense_router:
    - done          → END (subtask complete or failed)
    - page_doctor   → page_doctor (from supervision)
    - *             → supervision (checkpoint before next cycle)

  supervision_router:
    - done          → END
    - page_doctor   → page_doctor
    - *             → perceive (continue loop)
"""

from langgraph.graph import StateGraph, END

from v2.models.schemas import AgentState

# Reuse v1 nodes for init_subtask and page_doctor
from nodes.exec_init_subtask import init_subtask_node
from nodes.exec_page_doctor import page_doctor_node

# v2 execution chain nodes
from v2.nodes.exec_perceive import perceive_node
from v2.nodes.exec_plan_step import plan_step_node
from v2.nodes.exec_execute_action import execute_action_node
from v2.nodes.exec_sense_result import sense_result_node

# v2 supervision
from v2.nodes.sup_checkpoint import supervision_checkpoint_node

from utils.workflow_trace import traced


def sense_router(state: AgentState) -> str:
    """Route after sense_result."""
    signal = state.sense_signal

    # Done: subtask completed or failed (from sense or supervision)
    if signal == "done":
        return "done"

    # Page doctor request (from supervision)
    if signal == "page_doctor":
        return "page_doctor"

    # Normal: proceed to supervision checkpoint
    return "supervision"


def supervision_router(state: AgentState) -> str:
    """Route after supervision checkpoint."""
    signal = state.sense_signal

    if signal == "done":
        return "done"

    if signal == "page_doctor":
        return "page_doctor"

    # Continue execution loop
    return "continue"


def build_execution_workflow():
    """Build the dual-dimension execution sub-graph."""
    g = StateGraph(AgentState)

    # ── Subtask initialization ──────────────────────────────
    g.add_node("init_subtask", traced("init_subtask", "execution", init_subtask_node))
    g.add_node("page_doctor", traced("page_doctor", "execution", page_doctor_node))

    # ── Execution chain (Perceive → Plan → Act → Sense) ────
    g.add_node("perceive", traced("perceive", "execution", perceive_node))
    g.add_node("plan_step", traced("plan_step", "execution", plan_step_node))
    g.add_node("execute_action", traced("execute_action", "execution", execute_action_node))
    g.add_node("sense_result", traced("sense_result", "execution", sense_result_node))

    # ── Supervision checkpoint ──────────────────────────────
    g.add_node("supervision", traced("supervision", "execution", supervision_checkpoint_node))

    # ── Edges ───────────────────────────────────────────────
    g.set_entry_point("init_subtask")
    g.add_edge("init_subtask", "page_doctor")
    g.add_edge("page_doctor", "perceive")

    # Execution chain: linear flow
    g.add_edge("perceive", "plan_step")
    g.add_edge("plan_step", "execute_action")
    g.add_edge("execute_action", "sense_result")

    # Sense → routing
    g.add_conditional_edges("sense_result", sense_router, {
        "done": END,
        "page_doctor": "page_doctor",
        "supervision": "supervision",
    })

    # Supervision → routing
    g.add_conditional_edges("supervision", supervision_router, {
        "done": END,
        "page_doctor": "page_doctor",
        "continue": "perceive",
    })

    return g.compile()
