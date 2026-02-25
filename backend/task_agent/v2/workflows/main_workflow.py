"""v2 Main Workflow — three-layer orchestrator.

Structure:
  browser_reset → main_planner → exec_subtask → evaluate → [next|done|all_done]
                                      ↑                        |       |
                                      └── next ────────────────┘       |
                                                                  done (confident)
                                                                       ↓
                                                                   summary → END
                                                               all_done (uncertain)
                                                                       ↓
                                                             review (final_check → replan|summary)
                                                                       |
                                                                  ┌────┴────┐
                                                               done      replan
                                                                ↓           ↓
                                                               END     exec_subtask

When evaluate is confident (provides conclusion), it skips final_check and goes
directly to summary. When uncertain, it falls through to the review sub-graph.
"""

from langgraph.graph import StateGraph, END

from v2.models.schemas import AgentState

# Reuse v1 setup nodes
from nodes.setup_browser_reset import browser_reset_node
from nodes.plan_main_planner import main_planner_node

# Reuse v1 evaluate and summary nodes
from nodes.review_evaluate import evaluate_node
from nodes.review_final import summary_node

# v2 sub-graphs
from v2.workflows.execution_workflow import build_execution_workflow
from v2.workflows.review_workflow import build_review_workflow

from agent_config import settings
from utils.workflow_trace import traced


REVIEW_THRESHOLD = 3  # ≥3 completed subtasks → full review; ≤2 → trust evaluate


def subtask_router(state: AgentState) -> str:
    """Route after evaluate: next / done (skip review) / all_done (full review)."""
    task = state.task

    # Still have pending subtasks → continue
    if task.status not in ("completed", "failed"):
        has_pending = any(st.status == "pending" for st in task.subtasks)
        if has_pending:
            return "next"

    # Task finished — decide: skip review or full review?
    completed_count = sum(1 for st in task.subtasks if st.status == "completed")

    if completed_count < REVIEW_THRESHOLD and state.task_satisfied and state.final_result:
        # Simple task (≤2 subtasks) + evaluate gave conclusion → skip review
        return "done"

    # Complex task (≥3 subtasks) or no conclusion → full review
    return "all_done"


def review_router(state: AgentState) -> str:
    """Route after review: satisfied → end / not satisfied → re-execute."""
    if state.task_satisfied:
        return "done"
    # Replan added new subtasks → re-enter execution
    return "replan"


def build_main_workflow():
    """Build the complete v2 workflow."""
    g = StateGraph(AgentState)

    # ── Layer 1: Setup ──────────────────────────────────────
    g.add_node("browser_reset", traced("browser_reset", "main", browser_reset_node))
    g.add_node("main_planner", traced("main_planner", "main", main_planner_node))

    # ── Layer 2: Execution (sub-graph) ──────────────────────
    g.add_node("exec_subtask", build_execution_workflow())

    # ── Evaluate (between execution cycles) ─────────────────
    g.add_node("evaluate", traced("evaluate", "main", evaluate_node))

    # ── Summary (fast path: evaluate confident → skip review) ─
    g.add_node("summary", traced("summary", "main", summary_node))

    # ── Layer 3: Review (sub-graph, only when evaluate uncertain) ─
    g.add_node("review", build_review_workflow())

    # ── Edges ───────────────────────────────────────────────
    g.set_entry_point("browser_reset")
    g.add_edge("browser_reset", "main_planner")
    g.add_edge("main_planner", "exec_subtask")

    # After execution → evaluate
    g.add_edge("exec_subtask", "evaluate")

    # Evaluate → routing
    g.add_conditional_edges("evaluate", subtask_router, {
        "next": "exec_subtask",
        "done": "summary",       # confident — skip review
        "all_done": "review",    # uncertain — full review
    })

    # Summary → end
    g.add_edge("summary", END)

    # Review → routing
    g.add_conditional_edges("review", review_router, {
        "done": END,
        "replan": "exec_subtask",
    })

    return g.compile()
