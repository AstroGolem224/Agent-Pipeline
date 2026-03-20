#!/usr/bin/env python3
"""Agent Worker — polls PM Tool Queue, delegates coding tasks to cheap LLMs (Mistral/Kimi),
posts results back to Review column. PRISM reviews and merges.

Runs via cron every 5 minutes.
"""
import json, os, sys, urllib.request, urllib.parse, time, traceback
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from openai import OpenAI as _OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# ─── Config ───
PM_BASE = "http://100.115.61.30:8000/api"
PROJECT_ID = "c719a8f5-86e8-4620-99d3-05f2c2ee4f37"
COL_QUEUE = "40149a13-a223-466b-b4e3-9b1ede45db8e"
COL_WIP = "724ce286-8fec-4150-9897-8f042b566fa4"
COL_REVIEW = "4fa54724-4c0e-42a5-a15b-cd8942a3389b"
COL_DONE = "b4b10fd6-6eae-4239-a951-72926000c921"

# LLM backends (cheapest first)
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "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")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

NEMOTRON_KEY = "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"

MODELS = {
    "mistral": {
        "url": NVIDIA_URL,
        "key": NVIDIA_KEY,
        "model": "mistralai/mistral-large-3-675b-instruct-2512",
        "max_tokens": 8192,
        "backend": "requests",
    },
    "kimi": {
        "url": NVIDIA_URL,
        "key": NVIDIA_KEY,
        "model": "moonshotai/kimi-k2.5",
        "max_tokens": 8192,
        "backend": "requests",
    },
    "nemotron": {
        "url": "https://integrate.api.nvidia.com/v1",
        "key": NEMOTRON_KEY,
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "max_tokens": 16384,
        "backend": "openai",
        "thinking": True,
    },
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "agent_worker_state.json")
LOG_FILE = "/tmp/agent-worker.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def api(method, path, data=None):
    url = f"{PM_BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def move_task(task_id, column_id, position=0):
    return api("PATCH", f"/tasks/{task_id}/move", {"column_id": column_id, "position": position})

def add_result(task_id, content):
    """Append result to task description via PUT."""
    task = api("GET", f"/tasks/{task_id}")
    old_desc = task.get("description", "") or ""
    new_desc = old_desc + "\n\n---\n\n" + content if old_desc else content
    return api("PUT", f"/tasks/{task_id}", {"title": task["title"], "description": new_desc, "priority": task["priority"]})

def call_llm(model_key, system_prompt, user_prompt):
    """Call an NVIDIA NIM model. Returns (response_text, thinking_text_or_None)."""
    cfg = MODELS[model_key]
    backend = cfg.get("backend", "requests")

    # ── Nemotron: OpenAI client, streaming + thinking ──
    if backend == "openai":
        if not HAS_OPENAI:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        client = _OpenAI(base_url=cfg["url"], api_key=cfg["key"])
        stream = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=1,
            top_p=0.95,
            max_tokens=cfg["max_tokens"],
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": cfg["max_tokens"],
            },
            stream=True,
        )
        thinking_parts, answer_parts = [], []
        for chunk in stream:
            if not chunk.choices:
                continue
            reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
            if reasoning:
                thinking_parts.append(reasoning)
            if chunk.choices[0].delta.content:
                answer_parts.append(chunk.choices[0].delta.content)
        return "".join(answer_parts), "".join(thinking_parts) or None

    # ── Mistral / Kimi: requests ──
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": cfg["max_tokens"],
        "temperature": 0.15,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if HAS_REQUESTS:
        resp = _requests.post(cfg["url"], headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"], None
    else:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(cfg["url"], data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"], None

def pick_model(task_title, task_desc):
    """Pick the right model based on task type.
    
    Tier 1 — Nemotron (thinking): Debugging, Architektur, komplexe Logik
    Tier 2 — Kimi: Research, Analyse, Zusammenfassungen  
    Tier 3 — Mistral: Coding, Scripts, Standard-Implementierung (default)
    """
    text = (task_title + " " + (task_desc or "")).lower()
    nemotron_kw = ["debug", "architektur", "architecture", "warum", "fehler", "error",
                   "refactor", "optimier", "performance", "design pattern", "komplex",
                   "analyse.*code", "code.*review", "security", "race condition"]
    kimi_kw = ["research", "analyse", "recherche", "zusammenfass", "dokumentation",
               "erkläre", "erklaer", "vergleich", "überblick"]
    if any(kw in text for kw in nemotron_kw):
        return "nemotron"
    if any(kw in text for kw in kimi_kw):
        return "kimi"
    return "mistral"

SYSTEM_PROMPT = """Du bist ein Senior Software Engineer bei Clay Machine Games.
Du bekommst Coding-Tasks und lieferst vollständige, produktionsreife Lösungen.

Regeln:
- Schreibe vollständigen Code (keine Platzhalter, keine TODOs)
- Nutze die Sprache die im Task angegeben ist (GDScript, Python, TypeScript, etc.)
- Erkläre kurz deine Lösung (max 3 Sätze)
- Wenn der Task unklar ist, beschreibe was fehlt
- Format: Erst kurze Erklärung, dann Code in ```-Blöcken
- Antworte auf Deutsch"""

def process_task(task):
    """Process a single task from the Queue."""
    task_id = task["id"]
    title = task["title"]
    desc = task.get("description", "") or ""
    
    log(f"Processing: {title} [{task_id[:8]}]")
    
    # Move to In Progress
    move_task(task_id, COL_WIP)
    
    # Pick model
    model = pick_model(title, desc)
    log(f"  Model: {model}")
    
    # Build prompt
    user_prompt = f"## Task: {title}\n\n{desc}" if desc else f"## Task: {title}"
    
    try:
        result, thinking = call_llm(model, SYSTEM_PROMPT, user_prompt)
        log(f"  Response: {len(result)} chars" + (f" | Thinking: {len(thinking)} chars" if thinking else ""))

        # Build result block
        model_emoji = {"mistral": "⚡", "kimi": "🌙", "nemotron": "🧠"}.get(model, "🤖")
        comment = f"**{model_emoji} {model.upper()} Ergebnis:**\n\n{result}"
        if thinking:
            # Add collapsed thinking block
            thinking_short = thinking[:3000] + "..." if len(thinking) > 3000 else thinking
            comment += f"\n\n---\n**💭 Thinking ({len(thinking)} chars):**\n\n```\n{thinking_short}\n```"
        if len(comment) > 10000:
            comment = comment[:9900] + f"\n\n... (gekürzt, {len(result)} Zeichen total)"
        add_result(task_id, comment)
        
        # Move to Review
        move_task(task_id, COL_REVIEW)
        log(f"  → Review ✅")
        
    except Exception as e:
        log(f"  ERROR: {e}")
        traceback.print_exc()
        add_result(task_id, f"**❌ Fehler ({model}):** {e}")
        # Move back to Queue for retry
        move_task(task_id, COL_QUEUE)

def main():
    log("=== Agent Worker Run ===")
    
    # Get all tasks in Queue column
    try:
        all_tasks = api("GET", f"/projects/{PROJECT_ID}/tasks")
        tasks = [t for t in all_tasks if t.get("column_id") == COL_QUEUE]
    except Exception as e:
        log(f"Failed to fetch queue: {e}")
        return
    
    if not tasks:
        log("Queue leer.")
        return
    
    log(f"{len(tasks)} Tasks in Queue")
    
    # Process one task per run (avoid timeout)
    task = tasks[0]
    process_task(task)
    
    log("=== Done ===")

if __name__ == "__main__":
    main()
