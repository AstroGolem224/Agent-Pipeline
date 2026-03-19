# 🤖 Agent Pipeline — Clay Machine Games

> Eine Multi-Agent-Infrastruktur für autonome Task-Verarbeitung.  
> Agenten kommunizieren über das PM Tool als gemeinsame Aufgabenbasis.

---

## Überblick

Die Agent Pipeline verbindet PRISM, Kimi, Forge und zukünftige Agenten über ein **PM-Tool-zentriertes Task-System**. Statt direkter API-Kommunikation (fehleranfällig) nutzen alle Agenten das PM Tool als **gemeinsamen Nachrichtenbus** — strukturiert, persistent, nachvollziehbar.

```mermaid
graph TB
    subgraph Human["👤 Druid"]
        D[Matthias]
    end

    subgraph PMTool["📋 PM Tool (Shared Bus)"]
        direction LR
        COL_IN[📥 Inbox-Spalte<br/>neue Tasks]
        COL_WIP[⚙️ In Progress<br/>wird bearbeitet]
        COL_REVIEW[🔍 Review<br/>Ergebnis wartet]
        COL_DONE[✅ Done<br/>abgeschlossen]
        COL_IN --> COL_WIP --> COL_REVIEW --> COL_DONE
    end

    subgraph Agents["🤖 Agenten"]
        PRISM[🔮 PRISM<br/>Orchestrator]
        KIMI[🌙 Kimi K2.5<br/>Research / Analyse]
        FORGE[⚒️ Forge<br/>Code / Build]
    end

    D -->|Task erstellen| COL_IN
    PRISM -->|Task erstellen| COL_IN
    PRISM -->|Cron: pollt alle 2min| COL_IN
    PRISM -->|zuweisen| KIMI
    PRISM -->|zuweisen| FORGE
    KIMI -->|Ergebnis| COL_REVIEW
    FORGE -->|Ergebnis| COL_REVIEW
    PRISM -->|validiert + merged| COL_DONE
    PRISM -->|Telegram| D
```

---

## Kernprinzipien

| Prinzip | Beschreibung |
|---|---|
| **PM Tool als Bus** | Kein direkter Agent-zu-Agent-API-Call — alles läuft über Tasks |
| **Cron-getrieben** | PRISM pollt alle 2min die Inbox-Spalte auf neue Tasks |
| **Async by default** | Agenten arbeiten unabhängig, PRISM koordiniert |
| **Druid bleibt informiert** | Telegram-Notification bei Task-Start und -Abschluss |
| **Nachvollziehbar** | Jeder Schritt ist im PM Tool sichtbar |

---

## Architektur-Detail

### Task-Lifecycle

```mermaid
sequenceDiagram
    actor Druid
    participant PM as PM Tool
    participant PRISM as 🔮 PRISM
    participant Agent as 🤖 Spezialist-Agent

    Druid->>PM: Task anlegen (Inbox, agent: Kimi/Forge)
    Note over PM: Task liegt in Inbox-Spalte

    loop Cron alle 2 Minuten
        PRISM->>PM: GET /api/projects/{id}/tasks (Inbox-Spalte)
        PM-->>PRISM: Liste neuer Tasks
    end

    PRISM->>PM: Task → In Progress verschieben
    PRISM->>Agent: Task-Payload via Dispatch / direkter Aufruf
    PRISM->>Druid: 📱 Telegram: "Task gestartet: [Titel]"

    Agent->>Agent: Aufgabe ausführen
    Agent->>PM: Ergebnis als Kommentar + Task → Review
    PRISM->>PM: Cron erkennt Review-Task
    PRISM->>PRISM: Ergebnis validieren
    PRISM->>PM: Task → Done
    PRISM->>Druid: 📱 Telegram: "Task erledigt: [Titel] ✅"
```

### Task-Struktur

Jeder Task im PM Tool folgt diesem Schema:

```yaml
title: "[AgentTag] Kurze Beschreibung"
description: |
  ## Aufgabe
  Konkrete Beschreibung was zu tun ist.

  ## Kontext
  Relevante Hintergrundinformationen.

  ## Erwartetes Ergebnis
  Was soll der Agent liefern?

  ## Output-Format
  Code / Markdown / JSON / etc.

priority: low | medium | high | critical
labels:
  - agent:kimi      # Ziel-Agent
  - type:research   # Task-Typ
  - project:mmc     # Projekt-Kontext
```

### Agent-Rollen

```mermaid
graph LR
    subgraph PRISM["🔮 PRISM — Orchestrator"]
        P1[Cron Polling]
        P2[Task Routing]
        P3[Result Validation]
        P4[Druid Notification]
    end

    subgraph KIMI["🌙 Kimi K2.5 — Research"]
        K1[Marktanalyse]
        K2[Technische Recherche]
        K3[Dokumentation]
        K4[Ideation / Brainstorm]
    end

    subgraph FORGE["⚒️ Forge — Engineering"]
        F1[Code schreiben]
        F2[Refactoring]
        F3[Build & Deploy]
        F4[Bug Fixing]
    end

    P2 -->|research/analyse Tasks| KIMI
    P2 -->|code/build Tasks| FORGE
    KIMI -->|Ergebnis| P3
    FORGE -->|Ergebnis| P3
```

---

## Routing-Logik

PRISM entscheidet anhand von Labels und Titel-Prefix welcher Agent einen Task bekommt:

```mermaid
flowchart TD
    START([Neuer Task in Inbox]) --> CHECK{Label vorhanden?}

    CHECK -->|agent:kimi| KIMI[→ Kimi K2.5]
    CHECK -->|agent:forge| FORGE[→ Forge]
    CHECK -->|agent:prism| SELF[→ PRISM selbst]
    CHECK -->|kein Label| INFER{Titel-Analyse}

    INFER -->|research / analyse / docs| KIMI
    INFER -->|code / build / fix / deploy| FORGE
    INFER -->|unklar| DRUID[❓ Druid fragen]

    KIMI --> WORK[Aufgabe ausführen]
    FORGE --> WORK
    SELF --> WORK
    WORK --> RESULT[Ergebnis in PM Tool]
```

---

## Projektstruktur (dieses Repo)

```
Agent-Pipeline/
├── README.md               # Diese Datei — Architektur-Überblick
├── docs/
│   ├── ARCHITECTURE.md     # Detaillierte Technische Architektur
│   ├── ROUTING.md          # Routing-Regeln & Agent-Capabilities
│   └── TASK_SCHEMA.md      # Task-Format-Spezifikation
├── scripts/
│   ├── poller.py           # PRISM Cron-Poller (PM Tool → Agent Dispatch)
│   ├── dispatcher.py       # Task an richtigen Agent weiterleiten
│   └── notifier.py         # Telegram-Benachrichtigungen
├── agents/
│   ├── kimi.py             # Kimi K2.5 Interface (NVIDIA NIM)
│   └── forge.py            # Forge Interface
└── config/
    └── config.yml          # PM Tool IDs, API Keys, Routing-Regeln
```

---

## Implementierungs-Roadmap

```mermaid
gantt
    title Agent Pipeline — Aufbau-Plan
    dateFormat  YYYY-MM-DD
    section Phase 1 — Grundgerüst
    PM Tool Inbox-Spalte einrichten     :done,    p1a, 2026-03-19, 1d
    poller.py — Cron-Polling            :active,  p1b, 2026-03-19, 2d
    dispatcher.py — Routing-Logik      :         p1c, after p1b, 2d
    section Phase 2 — Agenten
    Kimi Interface (NVIDIA NIM)         :         p2a, after p1c, 3d
    Forge Interface                     :         p2b, after p1c, 3d
    Telegram Notifier                   :         p2c, after p1c, 2d
    section Phase 3 — Produktion
    End-to-End Test mit echtem Task     :         p3a, after p2a, 2d
    Error Handling + Retry-Logik        :         p3b, after p3a, 2d
    Monitoring + Logs                   :         p3c, after p3b, 2d
```

---

## Nächste Schritte

1. **PM Tool**: Inbox-Spalte im richtigen Projekt anlegen (oder dediziertes "Agent-Tasks" Projekt)
2. **`scripts/poller.py`** schreiben — fragt alle 2min die Inbox-Spalte ab
3. **Labels definieren** — `agent:kimi`, `agent:forge`, `type:research`, etc.
4. **Kimi Interface** — NVIDIA NIM API (bereits in TOOLS.md konfiguriert)
5. **Telegram Notifier** — PRISM postet Start/Ende an Druid

---

*Architektur-Dokument erstellt von PRISM 🔮 — 19.03.2026*
