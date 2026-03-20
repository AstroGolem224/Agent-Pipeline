#!/usr/bin/env python3
"""Dispatch a coding task to the Agent Pipeline Queue.
Usage: python3 agent_dispatch.py "Task Title" "Optional description"
"""
import json, sys, urllib.request

PM_BASE = "http://100.115.61.30:8000/api"
PROJECT_ID = "c719a8f5-86e8-4620-99d3-05f2c2ee4f37"
COL_QUEUE = "40149a13-a223-466b-b4e3-9b1ede45db8e"

def dispatch(title, description="", priority="medium"):
    payload = {
        "project_id": PROJECT_ID,
        "column_id": COL_QUEUE,
        "title": title,
        "description": description,
        "priority": priority,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{PM_BASE}/tasks", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        task = json.loads(r.read())
    print(f"✅ Dispatched: {title} [{task['id'][:8]}]")
    return task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agent_dispatch.py 'Title' ['Description'] ['Priority']")
        sys.exit(1)
    title = sys.argv[1]
    desc = sys.argv[2] if len(sys.argv) > 2 else ""
    prio = sys.argv[3] if len(sys.argv) > 3 else "medium"
    dispatch(title, desc, prio)
