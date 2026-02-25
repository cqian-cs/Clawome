"""sense_result node — Analyse what changed after action execution.

Three-level detection:
  1. Tab change? → auto-switch to new tab, signal new_context
  2. URL change? → signal new_context
  3. Neither? → DOM diff analysis
     - DOM changed → signal dom_changed (pass DOM to perceive)
     - DOM same    → signal no_change (action may not have taken effect)

Also handles:
  - Stuck detection → early termination (save tokens)
  - Max step exceeded → early termination
  - Browser log recording

LLM call: None (pure logic).
"""

import asyncio
import json

from browser import api as browser_api
from v2.models.schemas import AgentState
from agent_config import settings
import run_context

from shared.result_helpers import collect_partial_result

# Force-end subtask when consecutive no-progress steps reach this value
_MAX_STUCK_STEPS = 5


async def sense_result_node(state: AgentState) -> dict:
    """Analyse post-action changes, route the next step."""
    if run_context.is_cancelled():
        raise asyncio.CancelledError("Task cancelled by user")

    task = state.task
    br = state.browser
    memory = state.memory
    action = state.current_action
    step_num = state.action_count  # Already incremented by execute_action

    # If execute_action already handled "done", just pass through
    if action.get("action") == "done":
        return {
            "sense_signal": "done",
            "current_dom": "",
        }

    # Retrieve post-action state from execute_action's output
    new_dom = state.current_dom or ""
    before_tab_ids = set(state.before_tab_ids) if state.before_tab_ids else br.get_tab_ids()
    before_url = state.before_url or ""
    api_status = state.api_status or "ok"
    api_msg = state.api_msg or ""

    # ── 1. Update browser state with post-action DOM ──────────
    if new_dom:
        new_raw_tabs = await browser_api.get_tabs()
        br.update_tabs(new_raw_tabs, dom=new_dom)

    # ── 2. Tab change detection ───────────────────────────────
    tab_change = br.detect_tab_change(before_tab_ids)

    # Auto-switch to new tab when click opens one
    if tab_change.startswith("new_tab:") and action.get("action") == "click":
        new_tab_id = int(tab_change.split(":")[1].strip().split(",")[0])
        print(f"  [sense step {step_num}] Click opened new tab {new_tab_id}, auto-switching")
        try:
            await asyncio.sleep(0.5)
            switch_resp = await browser_api.switch_tab(new_tab_id)
            new_dom = switch_resp.get("dom", "")
            new_raw_tabs = await browser_api.get_tabs()
            br.update_tabs(new_raw_tabs, dom=new_dom)
        except Exception as e:
            print(f"  [sense step {step_num}] Auto-switch to tab {new_tab_id} failed: {e}")

    # ── 3. Log the action ─────────────────────────────────────
    # URL change detection annotation
    if action.get("action") in ("click", "goto") and api_status == "ok":
        if br.current_url == before_url:
            api_msg += " (page did not navigate)"

    br.add_log(action, response=api_msg, status=api_status, tab_change=tab_change)
    print(f"  [sense step {step_num}] {json.dumps(action, ensure_ascii=False)} -> {api_msg}")

    # ── 4. Determine sense signal ─────────────────────────────
    sense_signal = "new_context"  # default

    if tab_change:
        sense_signal = "new_context"
        print(f"  [sense step {step_num}] Tab changed: {tab_change} → new_context")
    elif br.current_url != before_url:
        sense_signal = "new_context"
        print(f"  [sense step {step_num}] URL changed → new_context")
    else:
        # URL + Tab same → check DOM diff
        old_dom = state.current_dom or ""
        if new_dom and new_dom != old_dom and len(new_dom) > 50:
            sense_signal = "dom_changed"
            print(f"  [sense step {step_num}] DOM changed ({len(old_dom)} → {len(new_dom)}) → dom_changed")
        else:
            sense_signal = "no_change"
            print(f"  [sense step {step_num}] No visible change → no_change")

    # ── 5. Stuck detection → early termination ────────────────
    subtask = task.get_current_subtask()
    post_stuck, post_stuck_reason = br.is_stuck(n=_MAX_STUCK_STEPS)
    if post_stuck:
        partial = collect_partial_result(memory, br)
        fail_msg = f"Action loop with no progress: {post_stuck_reason}"
        if partial:
            fail_msg += f"\nPartial results collected: {partial}"
        task.fail_subtask(subtask.step, result=fail_msg)
        task.save()
        print(f"  [sense step {step_num}] Subtask {subtask.step} stuck: {fail_msg}")

        return {
            "task": task,
            "browser": br,
            "memory": memory,
            "error": fail_msg,
            "current_action": action,
            "sense_signal": "done",
            "current_dom": new_dom,
        }

    # ── 6. Max steps exceeded ─────────────────────────────────
    max_actions = settings.agent.max_steps
    if state.action_count >= max_actions:
        partial = collect_partial_result(memory, br)
        fail_result = f"Exceeded maximum action steps ({max_actions})"
        if partial:
            fail_result += f"\nPartial results collected: {partial}"
        task.fail_subtask(subtask.step, result=fail_result)
        task.save()
        print(f"  [sense step {step_num}] Max steps exceeded")

        return {
            "task": task,
            "browser": br,
            "memory": memory,
            "error": f"subtask {subtask.step} exceeded maximum steps",
            "current_action": action,
            "sense_signal": "done",
            "current_dom": new_dom,
        }

    task.save()

    return {
        "browser": br,
        "memory": memory,
        "sense_signal": sense_signal,
        "current_dom": new_dom,
    }
