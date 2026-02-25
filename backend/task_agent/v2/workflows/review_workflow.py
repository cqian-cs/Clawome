"""Review Workflow — final acceptance and replanning sub-graph.

Structure:
  final_check → satisfied?  → summary → END
                not_satisfied → replan → (returns to main for re-execution)

Reuses v1 review nodes unchanged.
"""

from langgraph.graph import StateGraph, END

from v2.models.schemas import AgentState

# Reuse v1 review nodes
from nodes.review_final import final_check_node, replan_node, summary_node

from utils.workflow_trace import traced


def final_router(state: AgentState) -> str:
    """Route after final_check."""
    if state.task_satisfied:
        return "satisfied"
    return "not_satisfied"


def build_review_workflow():
    """Build the review sub-graph."""
    g = StateGraph(AgentState)

    g.add_node("final_check", traced("final_check", "review", final_check_node))
    g.add_node("replan", traced("replan", "review", replan_node))
    g.add_node("summary", traced("summary", "review", summary_node))

    g.set_entry_point("final_check")

    g.add_conditional_edges("final_check", final_router, {
        "satisfied": "summary",
        "not_satisfied": "replan",
    })

    # Summary → end
    g.add_edge("summary", END)

    # Replan → end (main workflow will route back to execution)
    g.add_edge("replan", END)

    return g.compile()
