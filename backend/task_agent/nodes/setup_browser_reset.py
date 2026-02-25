"""browser_reset node — Close and restart the browser to ensure each workflow starts from a clean state.

Flow: close_browser() -> open_browser() -> close extra tabs -> ready
"""

import asyncio
import time

from browser.api import close_browser, open_browser, get_tabs, close_tab
from models.schemas import AgentState


async def browser_reset_node(state: AgentState) -> dict:
    """Close old browser -> reopen a blank page -> clear leftover tabs -> ready."""
    br = state.browser

    # 1. Close (ignore errors: the browser may not have been started)
    try:
        await close_browser()
    except Exception:
        pass

    # 2. Clear model state (tabs, logs)
    br.reset()

    # 3. Open blank browser (no URL — plan_step will navigate to the target)
    last_err = None
    for attempt in range(3):
        try:
            await open_browser()
            last_err = None
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(1)

    if last_err is not None:
        raise last_err

    # 4. Clean up leftover tabs from previous runs.
    #    After close+open the server *should* start fresh, but some browser
    #    instances keep old pages alive.  Close every tab except the first one
    #    to guarantee a single blank page.
    try:
        tabs = await get_tabs()
        if len(tabs) > 1:
            # Keep the first tab, close the rest (iterate in reverse to avoid index shift)
            keep_id = tabs[0]["tab_id"]
            for t in reversed(tabs):
                if t["tab_id"] != keep_id:
                    try:
                        await close_tab(t["tab_id"])
                    except Exception:
                        pass
            print(f"  [browser_reset] Closed {len(tabs) - 1} leftover tab(s)")
    except Exception:
        pass

    print("  [browser_reset] Browser ready")
    return {"browser": br, "start_time": time.time()}
