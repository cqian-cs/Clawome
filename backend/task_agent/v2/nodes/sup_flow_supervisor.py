"""Flow Supervisor — process-level anomaly detection.

Like a project manager watching the Gantt chart, not the code.
Consumes execution metadata (step counts, URLs, errors) — never reads DOM.

Two modes:
  1. Rule layer (zero LLM cost): detect patterns → return signals
  2. LLM diagnosis (only when rules trigger): synthesize signals → recommend action

Merges v1 supervisor_node + global_check + step_exec stuck detection.
"""

from v2.models.schemas import AgentState
from agent_config import settings


def detect_flow_signals(state: AgentState) -> list[str]:
    """Rule-based anomaly detection. Returns a list of signal strings.

    Zero LLM cost. Called by sup_checkpoint every cycle.
    """
    signals = []
    memory = state.memory
    task = state.task
    br = state.browser

    # 1. Loop detection: same URL visited 3+ times
    loop_threshold = 3
    for page in memory.pages.values():
        if page.visited_count >= loop_threshold:
            signals.append(
                f"loop_detected: URL visited {page.visited_count}x — {page.title or page.url}"
            )

    # 2. Stuck detection: consecutive identical actions
    stuck_threshold = 5
    if len(br.logs) >= stuck_threshold:
        recent = br.logs[-stuck_threshold:]
        click_nodes = [
            log.action.get("node_id")
            for log in recent
            if log.action.get("action") == "click" and log.action.get("node_id")
        ]
        if len(click_nodes) >= stuck_threshold and len(set(click_nodes)) == 1:
            signals.append(f"stuck: clicked same node [{click_nodes[0]}] {stuck_threshold}x")

        # Consecutive "page did not navigate"
        no_nav = sum(1 for log in recent if "page did not navigate" in log.response.lower())
        if no_nav >= stuck_threshold:
            signals.append(f"stuck: page did not navigate {no_nav} consecutive times")

    # 3. Approaching step limit
    max_steps = settings.agent.max_steps
    if state.action_count >= max_steps - 3:
        signals.append(
            f"approaching_limit: {state.action_count}/{max_steps} steps used"
        )

    # 4. Multiple subtask failures
    failed = [st for st in task.subtasks if st.status == "failed"]
    if len(failed) >= 2:
        goals = "; ".join(f.goal[:40] for f in failed)
        signals.append(f"repeated_failure: {len(failed)} subtasks failed — {goals}")

    # 5. High error rate in recent actions
    error_window = 5
    if len(br.logs) >= error_window:
        recent_logs = br.logs[-error_window:]
        error_count = sum(1 for log in recent_logs if log.status == "error")
        if error_count >= 3:
            signals.append(f"high_error_rate: {error_count}/{error_window} recent actions errored")

    # 6. no_change accumulation (from sense_result signals)
    # Check recent logs for signs of ineffective actions
    if len(br.logs) >= 3:
        recent3 = br.logs[-3:]
        no_effect = sum(1 for log in recent3 if "page did not navigate" in log.response.lower())
        if no_effect >= 3:
            signals.append("no_effect: 3+ consecutive actions had no visible effect")

    return signals
