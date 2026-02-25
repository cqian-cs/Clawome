"""evaluate node — Rolling evaluator and planner.

After each subtask completes, the LLM decides: is the overall task done (→ final_check),
or what single next subtask should be executed? This implements a "walk one step, then look"
model instead of pre-planning all subtasks upfront.
"""

import json
import time

from langchain_core.messages import SystemMessage, HumanMessage

from llm import get_llm
from models.schemas import AgentState
from models.task import SubTask
from utils import extract_json, tlog


MAX_SUBTASKS = 10  # Guard against infinite loops

EVALUATE_SYSTEM = """\
You are a rolling task evaluator and planner. After each subtask finishes (completed or failed), you assess progress and decide: is the task done, or what single next step should be taken?

[Overall Task]
{task}

[Subtask Results (✓ = completed, ✗ = failed)]
{completed_summary}

[Collected Key Findings]
{findings_summary}

[Pages Visited]
{pages_summary}

[Historical Evaluation Records]
{evaluations_summary}

[Subtasks Completed So Far: {completed_count}]

Decide and return JSON:

If the collected information is sufficient to fully answer/complete the user's task:
{{"assessment": "Brief reason why the task is done", "next_action": "finish", "conclusion": "A comprehensive answer to the user's question, incorporating all key findings with specific data, numbers, and source URLs"}}

If more work is needed, plan exactly ONE next subtask:
{{"assessment": "Brief reason why more work is needed", "next_action": "continue", "next_subtask": {{"step": {next_step}, "goal": "Goal-oriented description of the next step"}}}}

Rules:
- Only return JSON, do not add explanations
- Assessment should be concise, one sentence
- When returning "finish", you MUST include a high-quality "conclusion" field:
  - The conclusion MUST be written in the SAME language as the user's original requirements
  - Include concrete, verifiable details: quantitative data, specific names, dates, source URLs
  - Incorporate ALL key findings from the completed subtasks and memory
  - Do NOT write vague, generic summaries — every claim should be backed by specific data
- When deciding "finish" vs "continue", focus on whether the completed subtasks + key findings already cover what the user asked for
- When planning the next subtask, base it on ACTUAL results so far — do not assume what pages look like or what information is available
- The next subtask should be goal-oriented (WHAT to accomplish), not prescriptive about HOW to navigate
- Do not plan redundant steps for information already obtained
- If {completed_count} subtasks have already been completed and the task is not done, consider whether the approach needs to change

Critical — result quality check before finishing:
- If a subtask result contains NO concrete data from actual web pages (no specific numbers, names, dates, URLs, etc.), it is NOT a valid result — the executor likely failed or fabricated an answer from general knowledge
- If the result mentions being "blocked", "unable to access", "CAPTCHA", anti-bot detection, or similar access failures, the subtask FAILED — do NOT treat it as done
- If the result is vague or based on "common knowledge" / "general understanding" rather than actual browsed content, plan a next step with a DIFFERENT approach (e.g., try a different search engine like Baidu or Bing, try a different website, rephrase the query)
- Only return "finish" when the findings contain REAL data obtained from actual web browsing

Critical — browser-only constraint:
- You are controlling a browser automation agent. It can ONLY perform web browsing actions: navigate pages, click elements, type text, read content.
- NEVER plan subtasks that require actions OUTSIDE the browser, such as: making phone calls, sending emails, downloading and opening files, installing software, or any physical-world actions.
- If a page shows contact info (phone, email), simply EXTRACT and REPORT it — do not plan a subtask to "call" or "email" them.
- Form filling is allowed, but NEVER submit forms (click submit/send buttons) unless the user's original task EXPLICITLY asks to submit something.

Critical — source reliability check:
- Review the [Pages Visited] list. Consider whether the information sources are reliable:
  - TRUSTWORTHY: government sites (.gov), education bureau sites (.edu), school official websites, major news outlets
  - UNRELIABLE: SEO content farms and aggregator sites (e.g., 高三网, 初三网, 有途网, 大学生必备网, etc.) — these often contain inaccurate, outdated, or fabricated rankings and data
- If all findings come ONLY from unreliable sources, plan a next step to verify from an authoritative source (e.g., visit the official education bureau website, school official websites, or government data portals)
- If findings include specific claims (rankings, scores, statistics) without citing an original source, plan a step to find the original data
- Information from a single unreliable source is NOT sufficient to finish — cross-verification or an authoritative source is needed

[Response Language]
You MUST respond in {language}."""




async def evaluate_node(state: AgentState) -> dict:
    """Rolling evaluator: assess the last subtask (completed or failed), then decide finish or plan the next single subtask."""
    task = state.task

    # The most recently done subtask (completed OR failed)
    done_subtasks = [st for st in task.subtasks if st.status in ("completed", "failed")]
    last_done = done_subtasks[-1] if done_subtasks else None
    if not last_done:
        return {"task": task}

    completed_count = sum(1 for st in done_subtasks if st.status == "completed")
    total_done = len(done_subtasks)

    # Guard: if we've hit the max subtask limit, go straight to final_check
    if total_done >= MAX_SUBTASKS:
        print(f"  [evaluate] Max subtask limit ({MAX_SUBTASKS}) reached, routing to final_check")
        task.add_evaluation(
            subtask_step=last_done.step,
            result=last_done.result,
            assessment=f"Max subtask limit ({MAX_SUBTASKS}) reached, proceeding to final check",
        )
        task.save()
        return {"task": task}

    # Build context for the LLM — show both completed and failed subtasks
    completed_summary = task.get_execution_summary()
    evaluations_summary = task.get_evaluations_summary(n=4)
    next_step = max(st.step for st in task.subtasks) + 1

    memory = state.memory
    findings_summary = "(none)"
    if memory.findings:
        findings_summary = "\n".join(f"  - {f}" for f in memory.findings)

    # Build visited pages summary so evaluate can judge source quality
    pages_summary = "(none)"
    if memory.pages:
        page_lines = []
        for page in memory.pages.values():
            line = f"  {page.title or '(no title)'} — {page.url} (visited {page.visited_count}x)"
            if page.summary:
                line += f"\n    Summary: {page.summary}"
            page_lines.append(line)
        pages_summary = "\n".join(page_lines)

    prompt = EVALUATE_SYSTEM.format(
        task=task.description,
        completed_summary=completed_summary,
        findings_summary=findings_summary,
        pages_summary=pages_summary,
        evaluations_summary=evaluations_summary,
        completed_count=completed_count,
        next_step=next_step,
        language=task.language or "English",
    )

    # Include browser logs for additional context
    browser_context = ""
    if state.browser.logs:
        browser_context = f"\n\n[Recent Browser Actions]\n{state.browser.get_logs_summary(n=3)}"

    # Compose the human message based on whether the last subtask completed or failed
    if last_done.status == "failed":
        human_msg = (
            f"Step {last_done.step} FAILED: \"{last_done.result}\". "
            f"The subtask did not succeed. Decide: should we retry with a different approach, "
            f"or is the overall task done based on what was collected so far?"
            f"{browser_context}"
        )
    else:
        human_msg = (
            f"Step {last_done.step} completed: \"{last_done.result}\". "
            f"Decide: is the overall task done, or what is the next step?"
            f"{browser_context}"
        )

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=human_msg),
    ]

    llm = get_llm()
    state.task.start_llm_step("evaluate", subtask_step=0)
    tlog("[evaluate] LLM call start")
    t0 = time.time()
    response = await llm.ainvoke(messages)
    d = int((time.time() - t0) * 1000)
    state.llm_usage.add(response, node="evaluate", messages=messages, duration_ms=d)
    state.task.complete_llm_step(d, summary="Evaluating progress…")
    tlog(f"[evaluate] LLM ({d}ms): {response.content[:200]}")

    try:
        data = extract_json(response.content)
    except (json.JSONDecodeError, TypeError):
        print("  [evaluate] JSON parsing failed, treating as finish")
        task.add_evaluation(
            subtask_step=last_done.step,
            result=last_done.result,
            assessment="Evaluation parsing failed, proceeding to final check",
        )
        task.save()
        return {"task": task, "llm_usage": state.llm_usage, "messages": [response]}

    assessment = data.get("assessment", "")
    next_action = data.get("next_action", "finish")

    if next_action == "continue" and data.get("next_subtask"):
        # Rolling plan: add the next single subtask
        ns = data["next_subtask"]
        new_subtask = SubTask(step=ns["step"], goal=ns["goal"])
        task.replan_remaining([new_subtask])
        # complete_subtask / fail_subtask may have set task.status to
        # "completed" or "failed". Override it — we're continuing.
        task.status = "running"
        changes = f"Planned next subtask: step {new_subtask.step} — {new_subtask.goal}"
        print(f"  [evaluate] {changes}")

        task.add_evaluation(
            subtask_step=last_done.step,
            result=last_done.result,
            assessment=assessment,
            plan_changed=True,
            changes=changes,
        )
        task.save()
        return {"task": task, "llm_usage": state.llm_usage, "messages": [response]}
    else:
        # Task is done — evaluate provides conclusion directly, skip final_check
        task.replan_remaining([])
        conclusion = data.get("conclusion", "")
        print(f"  [evaluate] Task done: {assessment}")

        task.add_evaluation(
            subtask_step=last_done.step,
            result=last_done.result,
            assessment=assessment,
        )
        task.save()

        if conclusion:
            # Evaluate is confident — set final_result + task_satisfied to skip review
            print(f"  [evaluate] Conclusion provided, skipping final_check")
            return {
                "task": task,
                "llm_usage": state.llm_usage,
                "final_result": conclusion,
                "task_satisfied": True,
                "messages": [response],
            }
        else:
            # No conclusion — fall through to final_check for review
            print(f"  [evaluate] No conclusion, routing to final_check")
            return {"task": task, "llm_usage": state.llm_usage, "messages": [response]}
