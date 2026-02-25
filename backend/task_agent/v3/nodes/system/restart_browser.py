"""restart_browser node — close and restart the browser for a clean state.

Flow: close_browser() → open_browser() → close extra tabs → ready

LLM call: None.
"""

import asyncio
import time

from browser.api import close_browser, open_browser, get_tabs, close_tab
from v3.models.schemas import AgentState
from agent_config import settings
import run_context


async def restart_browser_node(state: AgentState) -> dict:
    """Close old browser → reopen blank page → clear leftover tabs → ready."""
    if run_context.is_cancelled():
        raise asyncio.CancelledError("Task cancelled by user")

    br = state.browser

    # 1. Close without saving session (so next open won't restore old tabs)
    try:
        await close_browser(save_session=False)
    except Exception:
        pass

    # 2. Clear model state (tabs, logs)
    br.reset()

    # 3. Open blank page (passing a URL skips session restore in BrowserManager).
    #    Use about:blank for instant load; step_planner will navigate to the target.
    start_url = "about:blank"
    last_err = None
    for attempt in range(3):
        try:
            await open_browser(start_url)
            last_err = None
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(1)

    if last_err is not None:
        raise last_err

    # 4. Clean up leftover tabs from previous runs.
    try:
        tabs = await get_tabs()
        if len(tabs) > 1:
            keep_id = tabs[0]["tab_id"]
            for t in reversed(tabs):
                if t["tab_id"] != keep_id:
                    try:
                        await close_tab(t["tab_id"])
                    except Exception:
                        pass
            print(f"  [restart_browser] Closed {len(tabs) - 1} leftover tab(s)")
    except Exception:
        pass

    print("  [restart_browser] Browser ready")
    return {"browser": br, "start_time": time.time()}
