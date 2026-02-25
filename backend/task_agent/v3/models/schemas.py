"""v3 AgentState — three-layer architecture (agent / workflows / nodes).

Extends v2 AgentState. Structurally identical for now — the v3 refactor
is about directory organisation (agent/workflows/nodes separation),
not schema changes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from models.task import Task
from models.browser import Browser
from models.memory import TaskMemory
from models.schemas import LLMUsage


class AgentState(BaseModel):
    """v3 AgentState — agent / workflows / nodes architecture."""

    # ── Core ─────────────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    task: Task = Field(default_factory=Task)
    browser: Browser = Field(default_factory=Browser)
    memory: TaskMemory = Field(default_factory=TaskMemory)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    error: str = ""
    start_time: float = 0.0

    # ── Execution chain ──────────────────────────────────────────
    current_action: dict = Field(default_factory=dict)
    action_count: int = 0
    global_step_count: int = 0

    # ── Execution detail ─────────────────────────────────────────
    current_dom: str = ""                    # DOM passed between perceive/plan/execute/sense
    sense_signal: str = "new_context"        # Sense routing: new_context/dom_changed/no_change/done

    # ── Supervision ──────────────────────────────────────────────
    last_supervisor_step: int = 0
    flow_signals: list[str] = Field(default_factory=list)   # flow anomaly detection signals

    # ── Page doctor ──────────────────────────────────────────────
    page_doctor_count: int = 0
    last_doctor_url: str = ""

    # ── Review ───────────────────────────────────────────────────
    final_result: str = ""
    task_satisfied: bool = False
    review_count: int = 0
    replan_reason: str = ""
    replan_missing: list[str] = Field(default_factory=list)

    # ── Bridge fields (execute→sense, transient) ─────────────────
    before_tab_ids: list[int] = Field(default_factory=list)
    before_url: str = ""
    api_status: str = "ok"
    api_msg: str = ""
