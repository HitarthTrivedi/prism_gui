"""
Prism Sales Automation (POC)
────────────────────────────
The first app on Prism's app-framework direction: source → store (lead
artifact) → qualify → reach. This package is the app's core logic, kept
independent of the Qt shell so it can run headless (see `run_poc`).

Modules:
  models   — Lead / Signal / Dimension / Dossier (the shapes)
  sheet    — ingest the client's own xlsx/csv (stdlib only)
  signals  — the "why-now" layer (Exa, BYO-key; degrades honestly)
  qualify  — qualification as an evidence-cited case file (Prism's Groq router)
  engine   — the orchestrator (sheet → signals → qualify)
  render   — dossier → console / Markdown
"""
