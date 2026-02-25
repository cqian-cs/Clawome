from __future__ import annotations

"""LLM usage tracking — shared by all workflow versions."""

import json

from pydantic import BaseModel
import run_context


class LLMUsage(BaseModel):
    """LLM call statistics."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, response, node: str = "", messages: list | None = None, duration_ms: int = 0) -> None:
        """Extract token usage from an LLM response, accumulate it, and write to the log file."""
        self.calls += 1
        usage = response.response_metadata.get("token_usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)
        self.input_tokens += inp
        self.output_tokens += out

        self._log_to_file(node, messages, response, inp, out, duration_ms)

    def _log_to_file(self, node: str, messages, response, inp: int, out: int, duration_ms: int = 0) -> None:
        """Append an LLM call record to the JSON log file."""
        log_path = run_context.get_log_path("llm_calls.json")

        # Build the record for this call
        record = {
            "call": self.calls,
            "node": node,
            "duration_ms": duration_ms,
            "tokens": {"input": inp, "output": out},
            "messages": [],
            "response": response.content,
        }

        if messages:
            for msg in messages:
                role = msg.__class__.__name__.replace("Message", "").lower()
                record["messages"].append({"role": role, "content": msg.content})

        # Create a new array on the first write; append on subsequent writes
        if self.calls == 1:
            calls_list = []
        else:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    calls_list = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                calls_list = []

        calls_list.append(record)

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(calls_list, f, ensure_ascii=False, indent=2)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> str:
        return (
            f"LLM Calls: {self.calls}\n"
            f"Input Tokens: {self.input_tokens}\n"
            f"Output Tokens: {self.output_tokens}\n"
            f"Total Tokens: {self.total_tokens}"
        )
