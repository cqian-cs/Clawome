"""stop_browser node — close the browser at the end of a workflow run.

Called after summary to release browser resources (Playwright, Chromium).
Errors are silently ignored — the browser may already be closed.

LLM call: None.
"""

import asyncio

from browser.api import close_browser
from v3.models.schemas import AgentState
import run_context


async def stop_browser_node(state: AgentState) -> dict:
    """Close the browser and release resources."""
    if run_context.is_cancelled():
        raise asyncio.CancelledError("Task cancelled by user")

    try:
        await close_browser(save_session=False)
        print("  [stop_browser] Browser closed")
    except Exception:
        print("  [stop_browser] Browser already closed or not running")

    return {}
