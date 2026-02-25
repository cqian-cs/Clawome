"""Startup Workflow — browser initialization + task planning.

Structure:
  restart_browser → main_planner → END

Responsibilities:
  - Close old browser, open clean blank page
  - Break user task into initial subtask via LLM
"""

from langgraph.graph import StateGraph, END

from v3.models.schemas import AgentState
from utils.workflow_trace import traced

from v3.nodes.system.restart_browser import restart_browser_node
from v3.agent.main_planner import main_planner_node


# ── Workflow builder ──────────────────────────────────────────────


def build_startup_workflow():
    """Build the startup sub-graph: restart browser then plan first subtask."""
    g = StateGraph(AgentState)

    g.add_node("restart_browser", traced("restart_browser", "startup", restart_browser_node))
    g.add_node("main_planner", traced("main_planner", "startup", main_planner_node))

    g.set_entry_point("restart_browser")
    g.add_edge("restart_browser", "main_planner")
    g.add_edge("main_planner", END)

    return g.compile()
