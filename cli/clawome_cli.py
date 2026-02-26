#!/usr/bin/env python3
"""Clawome CLI — command-line client for the Clawome Task Agent.

Usage:
    clawome start                                # Start server + guided setup
    clawome "Go to Hacker News and find top 3 AI stories"
    clawome status
    clawome stop
    clawome "complex task" --max-steps 30
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:5001"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Providers ────────────────────────────────────────────────────────

PROVIDERS = [
    ("dashscope",  "DashScope (Qwen)",  "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.5-plus"),
    ("openai",     "OpenAI",            "https://api.openai.com/v1",                          "gpt-4o"),
    ("anthropic",  "Anthropic",         None,                                                  "claude-sonnet-4-20250514"),
    ("google",     "Google",            None,                                                  "gemini-2.0-flash"),
    ("deepseek",   "DeepSeek",          None,                                                  "deepseek-chat"),
    ("moonshot",   "Moonshot",          None,                                                  "moonshot-v1-8k"),
    ("zhipu",      "Zhipu",             None,                                                  "glm-4"),
    ("mistral",    "Mistral",           None,                                                  "mistral-large-latest"),
    ("groq",       "Groq",              None,                                                  "llama-3.1-70b"),
    ("xai",        "xAI",               None,                                                  "grok-2"),
]

# ── HTTP helpers ─────────────────────────────────────────────────────

def _request(base_url, method, path, body=None):
    """Send an HTTP request and return parsed JSON."""
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"status": "error", "message": f"HTTP {e.code}"}
    except urllib.error.URLError:
        return None  # Connection failed


def _post(base_url, path, body=None):
    return _request(base_url, "POST", path, body)


def _get(base_url, path):
    return _request(base_url, "GET", path)


def _is_server_running(base_url):
    """Check if the backend server is reachable."""
    return _get(base_url, "/api/browser/url") is not None


def _exit_no_server(base_url):
    """Print error and exit if server is unreachable."""
    print(f"Error: Cannot connect to {base_url}")
    print("Run 'clawome start' to start the server first.")
    sys.exit(1)


# ── Display helpers ──────────────────────────────────────────────────

def _print_status(data, prev_subtasks):
    """Print incremental status updates. Returns current subtask list."""
    subtasks = data.get("subtasks", [])

    for st in subtasks:
        step = st.get("step", "?")
        goal = st.get("goal", st.get("description", ""))
        status = st.get("status", "")
        key = (step, goal)

        prev = prev_subtasks.get(key)
        if prev == status:
            continue
        prev_subtasks[key] = status

        if status == "completed":
            result = st.get("result", "")
            print(f"  [Step {step}] {goal} ... done")
            if result:
                for line in result.strip().split("\n")[:3]:
                    print(f"    {line}")
        elif status == "running":
            print(f"  [Step {step}] {goal} ... running")

    return prev_subtasks


def _format_usage(usage):
    """Format LLM usage stats."""
    if not usage:
        return ""
    calls = usage.get("calls", 0)
    tokens = usage.get("total_tokens", 0)
    parts = []
    if calls:
        parts.append(f"{calls} LLM calls")
    if tokens:
        parts.append(f"{tokens:,} tokens")
    return ", ".join(parts)


# ── Interactive setup ────────────────────────────────────────────────

def _prompt_choice(prompt, options, default=None):
    """Prompt user to pick from a numbered list."""
    print(f"\n{prompt}")
    for i, (_, label, *_rest) in enumerate(options, 1):
        marker = " *" if default and options[i - 1][0] == default else ""
        print(f"  [{i}] {label}{marker}")

    while True:
        raw = input("\n  > ").strip()
        if not raw and default:
            for i, opt in enumerate(options):
                if opt[0] == default:
                    return opt
            return options[0]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print(f"  Please enter 1-{len(options)}")


def _prompt_input(prompt, default="", secret=False):
    """Prompt for text input with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass
            val = getpass.getpass(f"  {prompt}{suffix}: ")
        else:
            val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default


def _save_env(env_path, values):
    """Write config values to .env file, preserving other lines."""
    existing = {}
    other_lines = []

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    existing[key] = line
                else:
                    other_lines.append(line)

    # Update with new values
    existing.update({k: f"{k}={v}\n" for k, v in values.items()})

    with open(env_path, "w") as f:
        for line in other_lines:
            f.write(line)
        for line in existing.values():
            f.write(line)


def cmd_setup(env_path):
    """Interactive LLM configuration wizard. Returns True if configured."""
    print("\n  LLM Configuration")
    print("  " + "-" * 40)

    # Pick provider
    provider_id, provider_name, default_base, default_model = _prompt_choice(
        "  Select LLM provider:", PROVIDERS
    )

    # API Key
    api_key = _prompt_input("API Key", secret=True)
    if not api_key:
        print("  API Key is required for Task Agent.")
        return False

    # API Base (only if needed)
    api_base = ""
    if default_base:
        api_base = _prompt_input("API Base URL", default=default_base)

    # Model
    model = _prompt_input("Model name", default=default_model)

    # Save
    values = {
        "LLM_PROVIDER": provider_id,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": model,
    }
    if api_base:
        values["LLM_API_BASE"] = api_base

    _save_env(env_path, values)
    print(f"\n  Configuration saved to {env_path}")
    return True


# ── Commands ─────────────────────────────────────────────────────────

def cmd_start(base_url):
    """Start the backend server with optional guided setup."""
    # Check if already running
    if _is_server_running(base_url):
        print(f"Server is already running at {base_url}")
        return

    env_path = os.path.join(PROJECT_ROOT, ".env")
    has_config = os.path.exists(env_path)

    print("\n  Welcome to Clawome!")
    print("  " + "=" * 40)

    # Check if LLM is configured
    needs_setup = True
    if has_config:
        with open(env_path) as f:
            content = f.read()
        if "LLM_API_KEY=" in content:
            # Check if key is actually set (not empty)
            for line in content.splitlines():
                if line.startswith("LLM_API_KEY=") and line.split("=", 1)[1].strip():
                    needs_setup = False
                    break

    if needs_setup:
        print("\n  LLM is not configured yet. Task Agent requires an LLM API key.")
        choice = _prompt_input("Configure now? [Y/n]", default="Y")
        if choice.lower() in ("y", "yes", ""):
            cmd_setup(env_path)
        else:
            print("  Skipped. You can configure later in Dashboard > Settings.")
    else:
        print("\n  LLM configuration found.")
        choice = _prompt_input("Reconfigure? [y/N]", default="N")
        if choice.lower() in ("y", "yes"):
            cmd_setup(env_path)

    # Install Playwright chromium if needed
    backend_dir = os.path.join(PROJECT_ROOT, "backend")
    try:
        print("\n  Checking Playwright browser...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=120,
        )
        print("  Playwright chromium ready.")
    except Exception:
        print("  Warning: Could not install Playwright chromium.")
        print("  Run manually: python -m playwright install chromium")

    # Start backend server
    print("\n  Starting server...")
    process = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=backend_dir,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    # Wait for server to be ready
    print("  Waiting for server...", end="", flush=True)
    for _ in range(30):
        time.sleep(1)
        print(".", end="", flush=True)
        if _is_server_running(base_url):
            print(" ready!")
            port = base_url.rsplit(":", 1)[-1]
            print(f"\n  Server:    {base_url}")
            print(f"  Dashboard: {base_url}")
            print(f"\n  Now you can run:")
            print(f'    clawome "your task here"')
            print(f"    clawome status")
            print(f"    clawome stop")
            print(f"\n  Press Ctrl+C to stop the server.")

            # Keep running until Ctrl+C
            def _on_interrupt(sig, frame):
                print("\n\n  Shutting down server...")
                process.terminate()
                process.wait(timeout=5)
                print("  Server stopped.")
                sys.exit(0)

            signal.signal(signal.SIGINT, _on_interrupt)
            process.wait()
            return

    print(" timeout!")
    print("  Server failed to start. Check backend/app.py for errors.")
    process.terminate()
    sys.exit(1)


def cmd_run(base_url, task, max_steps=None):
    """Submit a task and poll until completion."""
    if not _is_server_running(base_url):
        _exit_no_server(base_url)

    body = {"task": task}
    if max_steps:
        body["max_steps"] = max_steps

    result = _post(base_url, "/api/agent/start", body)

    if result.get("error_code") == "task_running":
        print(f"A task is already running (id: {result.get('task_id')})")
        print("Use 'clawome status' to check progress or 'clawome stop' to cancel.")
        sys.exit(1)

    if result.get("status") == "error":
        print(f"Error: {result.get('message', 'Unknown error')}")
        sys.exit(1)

    task_id = result.get("task_id", "?")
    print(f"Task started (id: {task_id})\n")

    # Auto-cancel on Ctrl+C
    def _on_interrupt(sig, frame):
        print("\n\nCancelling task...")
        _post(base_url, "/api/agent/stop")
        print("Task cancelled.")
        sys.exit(130)

    signal.signal(signal.SIGINT, _on_interrupt)

    # Poll loop
    prev_subtasks = {}
    while True:
        time.sleep(2)
        data = _get(base_url, "/api/agent/status")
        if data is None:
            print("\nLost connection to server.")
            sys.exit(1)

        status = data.get("status", "idle")
        prev_subtasks = _print_status(data, prev_subtasks)

        if status == "completed":
            elapsed = data.get("elapsed_seconds", 0)
            usage_str = _format_usage(data.get("llm_usage"))
            summary = f"Task completed ({elapsed}s"
            if usage_str:
                summary += f", {usage_str}"
            summary += ")"
            print(f"\n{summary}\n")

            final = data.get("final_result", "")
            if final:
                print(final)
            break

        elif status == "failed":
            print(f"\nTask failed: {data.get('error', 'Unknown error')}")
            sys.exit(1)

        elif status == "cancelled":
            print("\nTask cancelled.")
            break

        elif status == "idle":
            print("No task running.")
            break


def cmd_status(base_url):
    """Show current task status."""
    if not _is_server_running(base_url):
        _exit_no_server(base_url)

    data = _get(base_url, "/api/agent/status")
    status = data.get("status", "idle")

    if status == "idle":
        print("No task running.")
        return

    task_desc = data.get("task", "")
    elapsed = data.get("elapsed_seconds", 0)
    print(f"Task: {task_desc}")
    print(f"Status: {status} ({elapsed}s elapsed)")

    subtasks = data.get("subtasks", [])
    if subtasks:
        print()
        for st in subtasks:
            step = st.get("step", "?")
            goal = st.get("goal", st.get("description", ""))
            s = st.get("status", "")
            mark = {"completed": "+", "running": ">", "pending": " "}.get(s, " ")
            print(f"  [{mark}] Step {step}: {goal}")

    if status == "completed":
        final = data.get("final_result", "")
        if final:
            print(f"\nResult:\n{final}")

    usage_str = _format_usage(data.get("llm_usage"))
    if usage_str:
        print(f"\nLLM usage: {usage_str}")


def cmd_stop(base_url):
    """Cancel the running task."""
    if not _is_server_running(base_url):
        _exit_no_server(base_url)

    result = _post(base_url, "/api/agent/stop")
    status = result.get("status", "")
    if status == "cancelled":
        print("Task cancelled.")
    elif status == "no_task_running":
        print("No task running.")
    else:
        print(f"Response: {result}")


# ── Entry point ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="clawome",
        description="Clawome CLI — run web tasks from the terminal",
        epilog="Examples:\n"
               "  clawome start                     Start server with guided setup\n"
               '  clawome "find AI news on HN"      Submit a task\n'
               "  clawome status                    Check progress\n"
               "  clawome stop                      Cancel task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL,
        help=f"Backend server URL (default: {DEFAULT_URL})",
    )

    sub = parser.add_subparsers(dest="command")

    # clawome start
    sub.add_parser("start", help="Start server with guided setup")

    # clawome setup
    sub.add_parser("setup", help="Configure LLM settings")

    # clawome run "task"
    run_p = sub.add_parser("run", help="Submit a new task")
    run_p.add_argument("task", help="Task description in natural language")
    run_p.add_argument("--max-steps", type=int, help="Override step limit (default: 15)")

    # clawome status
    sub.add_parser("status", help="Show current task status")

    # clawome stop
    sub.add_parser("stop", help="Cancel running task")

    # Allow bare `clawome "task"` without the `run` subcommand
    args, remaining = parser.parse_known_args()

    if args.command == "start":
        cmd_start(args.url)
    elif args.command == "setup":
        env_path = os.path.join(PROJECT_ROOT, ".env")
        cmd_setup(env_path)
    elif args.command == "run":
        cmd_run(args.url, args.task, args.max_steps)
    elif args.command == "status":
        cmd_status(args.url)
    elif args.command == "stop":
        cmd_stop(args.url)
    elif args.command is None:
        if remaining:
            # Treat first positional arg as task description
            task = " ".join(remaining)
            max_steps = None
            if "--max-steps" in remaining:
                idx = remaining.index("--max-steps")
                if idx + 1 < len(remaining):
                    try:
                        max_steps = int(remaining[idx + 1])
                    except ValueError:
                        pass
                    task = " ".join(r for i, r in enumerate(remaining)
                                   if i != idx and i != idx + 1)
            cmd_run(args.url, task, max_steps)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
