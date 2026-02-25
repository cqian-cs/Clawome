"""v2 AgentState — extends v1 with execution chain and supervision fields.

Key additions over v1:
  - current_dom: DOM snapshot passed between perceive/plan/execute/sense
  - sense_signal: routing signal from sense_result (new_context/dom_changed/no_change/done)
  - last_supervisor_step: tracks when supervision last ran
  - before_tab_ids, before_url, api_status, api_msg: execute→sense bridge fields

Keeps full v1 compatibility — all v1 fields are preserved so reused nodes
(init_subtask, page_doctor, evaluate, review_final) work unchanged.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from models.task import Task
from models.browser import Browser
from models.memory import TaskMemory

# Reuse v1 LLMUsage — a single class shared by both versions.
# This avoids Pydantic validation errors when v1 nodes (main_planner,
# evaluate, review_final, etc.) return v1 LLMUsage instances into the
# v2 state graph.
from models.schemas import LLMUsage


class AgentState(BaseModel):
    """v2 AgentState — superset of v1 with execution chain + supervision fields."""

    # ── Core (shared with v1) ──────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    task: Task = Field(default_factory=Task)
    browser: Browser = Field(default_factory=Browser)
    memory: TaskMemory = Field(default_factory=TaskMemory)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    error: str = ""
    start_time: float = 0.0

    # ── Execution chain (v1 compatible) ────────────────────────
    current_action: dict = Field(default_factory=dict)
    action_count: int = 0
    global_step_count: int = 0

    # ── v2 execution chain additions ───────────────────────────
    current_dom: str = ""                    # DOM passed between perceive/plan/execute/sense
    sense_signal: str = "new_context"        # Sense routing: new_context/dom_changed/no_change/done

    # ── Supervision ────────────────────────────────────────────
    last_supervisor_step: int = 0

    # ── Page doctor (v1 compatible) ────────────────────────────
    page_doctor_count: int = 0
    last_doctor_url: str = ""

    # ── Review (v1 compatible) ─────────────────────────────────
    final_result: str = ""
    task_satisfied: bool = False
    review_count: int = 0
    replan_reason: str = ""
    replan_missing: list[str] = Field(default_factory=list)

    # ── Bridge fields (execute→sense, transient) ───────────────
    before_tab_ids: list[int] = Field(default_factory=list)  # Snapshot before action
    before_url: str = ""
    api_status: str = "ok"
    api_msg: str = ""
