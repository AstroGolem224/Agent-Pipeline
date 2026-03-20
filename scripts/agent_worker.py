#!/usr/bin/env python3
"""Agent Worker — polls PM Tool Queue, delegates coding tasks to cheap LLMs (Mistral/Kimi),
posts results back to Review column. PRISM reviews and merges.

Runs via cron every 5 minutes.
"""
import json, os, sys, urllib.request, urllib.parse, time, traceback

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

MODELS = {
    "mistral": {
        "url": NVIDIA_URL,
        "key": NVIDIA_KEY,
        "model": "mistralai/mistral-large-3-675b-instruct-2512",
        "max_tokens": 8192,
    },
    "kimi": {
        "url": NVIDIA_URL,
        "key": NVIDIA_KEY,
        "model": "moonshotai/kimi-k2.5",
        "max_tokens": 8192,
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
    """Call an NVIDIA NIM model. Returns response text."""
    cfg = MODELS[model_key]
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": cfg["max_tokens"],
        "temperature": 0.3,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(cfg["url"], data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['key']}",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    return resp["choices"][0]["message"]["content"]

def pick_model(task_title, task_desc):
    """Pick the cheapest model for the task. Default: mistral."""
    text = (task_title + " " + (task_desc or "")).lower()
    # Kimi for research/analysis, Mistral for coding
    if any(kw in text for kw in ["research", "analyse", "recherche", "zusammenfass", "review"]):
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
        result = call_llm(model, SYSTEM_PROMPT, user_prompt)
        log(f"  Response: {len(result)} chars")
        
        # Post result as comment
        comment = f"**🤖 {model.upper()} Ergebnis:**\n\n{result}"
        # Truncate if too long for comment
        if len(comment) > 10000:
            comment = comment[:9900] + "\n\n... (gekürzt, {len(result)} Zeichen total)"
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
