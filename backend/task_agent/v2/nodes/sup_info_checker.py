"""Info Checker — information quality and completeness monitoring.

Like a research assistant doing notes and fact-checking.
Consumes findings, page summaries, and extraction results — not the raw DOM.

Two modes:
  1. Light mode (rule layer, zero LLM cost): every cycle
     - Count findings
     - Track data sources
     - Flag potential completeness
  2. Deep mode (with LLM): every N steps or when Master requests
     - Analyze finding consistency
     - Score information sufficiency
     - List missing items

This is a NEW v2 capability — v1 had no independent info quality monitoring.
"""

from v2.models.schemas import AgentState


def detect_info_signals(state: AgentState) -> list[str]:
    """Light-mode rule check. Returns info quality signals.

    Zero LLM cost. Called by sup_checkpoint every cycle.
    """
    signals = []
    memory = state.memory
    task = state.task

    findings_count = len(memory.findings)

    # 1. Information sufficiency heuristic
    min_findings = 2
    if findings_count >= min_findings:
        # Check if findings cover key aspects of the task
        signals.append(f"info_partial: {findings_count} findings collected")

        # If we have 3+ findings from different sources, likely sufficient
        source_urls = set()
        for page in memory.pages.values():
            if page.key_info or page.summary:
                source_urls.add(page.url)
        if len(source_urls) >= 2 and findings_count >= 3:
            signals.append("info_sufficient: 3+ findings from 2+ sources")

    # 2. No findings yet — flag if we've executed many steps
    if findings_count == 0 and state.action_count >= 5:
        signals.append("info_empty: 0 findings after 5+ steps")

    # 3. Source reliability check
    _UNRELIABLE_DOMAINS = (
        "gaosan.com", "chusan.com", "youtuwang.com",
        "daxueshengbibei.com", "liuxue86.com",
    )
    unreliable_sources = []
    reliable_sources = []
    for page in memory.pages.values():
        if any(d in page.url for d in _UNRELIABLE_DOMAINS):
            unreliable_sources.append(page.url)
        elif page.summary or page.key_info:  # Has actual content
            reliable_sources.append(page.url)

    if unreliable_sources and not reliable_sources:
        signals.append(
            f"info_unreliable: all {len(unreliable_sources)} sources are from unreliable sites"
        )

    # 4. Potential data conflict (simple heuristic)
    # Check if findings contain contradictory patterns (numbers that differ)
    if findings_count >= 2:
        # Simple: flag if two findings mention different numbers for similar topics
        # This is a best-effort heuristic; deep mode uses LLM for real analysis
        pass

    # 5. Completed subtask has vague/empty results
    for st in task.subtasks:
        if st.status == "completed" and st.result:
            result_lower = st.result.lower()
            if any(kw in result_lower for kw in ("unable to", "could not", "failed to", "blocked")):
                signals.append(f"info_failed_subtask: step {st.step} result indicates failure")
                break

    return signals
