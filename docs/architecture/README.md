# Prism — Architecture Documentation

**Audience:** the product manager and maintainer, and anyone joining the team.
**Purpose:** understand the whole system without reading 74,000 lines of code.

This set is the *technical* reference. It says what the system is, what data it
holds, where that data comes from and goes, and what every module is
responsible for. It deliberately does **not** re-argue product decisions —
those live in the documents listed under "Where the reasoning lives" below, and
this set links out to them rather than restating them.

**Last updated:** 2026-08-26 · against commit `20292f4`, app version `1.3.0`.

---

## Read in this order

| # | Document | Answers |
|---|---|---|
| 1 | [System overview](01-system-overview.md) | What is Prism, what are the layers, what runs on which thread, what happens at startup |
| 2 | [Data model](02-data-model.md) | Every file on disk, every field in it, every in-memory record, and how they relate |
| 3 | [Data flow](03-data-flow.md) | Every pipeline, stage by stage: input → process → output → destination |
| 4 | [API reference](04-api-reference.md) | Internal module surface, and every external service Prism talks to |
| 5 | [Licensing & authorisation](05-licensing.md) | The gate on every launch and every add-on |
| 6 | [Add-on subsystems](06-addons.md) | Email automation, BOQ, Gerber, Reel/Studio, Email blast |
| 7 | [Operations](07-operations.md) | Build, CI, release, tests, configuration, environment, failure modes |
| 8 | [System state & roadmap map](08-state-and-roadmap.md) | What is built, what is half-built, what is deliberately not built |

---

## The thirty-second version

Prism is a **native PySide6/Qt desktop application** — no browser, no local
server, no backend of its own. It takes a task in plain language, works out
which AI tools it needs, and drives those tools **in the user's own Chrome,
signed in as them**. On top of that sits a shelf of add-ons for small Indian
manufacturers: read the inbox and keep an inquiry register, take quantities off
a CAD drawing, measure a PCB job, send email from the user's own account, make
a short video.

Three properties shape every decision in the codebase:

1. **The customer's data stays on the customer's machine.** There is no Prism
   server that receives customer content. The only outbound calls are to Groq
   (small text snippets, and only when local rules cannot settle a question),
   the licence server (never content), and the user's own mail servers.
2. **Prism has no AI engine of its own.** `core_bridge.py` imports the
   `prism_terminal` submodule's `core/` package. The CLI and the GUI run
   *identical* routing, automation, voice and file-finding code, and share one
   `~/.prism/config.json`.
3. **Automation stops where money moves.** Two human confirmations per order —
   before a price goes to a customer, and before a purchase order is accepted.
   Everything else runs unattended.

---

## Where the reasoning lives

This set answers *what* and *how*. These answer *why*, and they are the record
of decisions already argued through. Do not duplicate them; link to them.

| Document | Holds |
|---|---|
| `README.md` (repo root) | The product tour, the layout, the known limitations |
| `CHANGES.md` | The full development log, round by round |
| `docs/EMAIL_WORKFLOW.md` | The per-inquiry lifecycle as a business process |
| `docs/EMAIL_WORKFLOW_RUNTIME.md` | Which brain does which job; the human stop points |
| `docs/EMAIL_AUTOMATION.md` | Office scale: several mailboxes, one register |
| `docs/AFTER_THE_MERGE.md` | Decided work, blocked only on merging |
| `docs/DEFERRED.md` | Work deliberately not built yet, each with its trigger |
| `docs/FUTURE_INDUSTRY_TARGETS.md` | Which industries next, and the hard rules per industry |
| `docs/GERBER_FIXES.md` | The Gerber reader's verification history |
| `LICENSING.md` | The licence design and the trade it makes |
| `BUILD.md` / `SHIPPING.md` / `RUNNING.md` | Building, issuing keys, running |
| `KNOWN_ISSUES.md` | Live defects |

---

## Word copies

Everything here is also generated as Word documents in
[`word/`](word/) — nine individual files plus
`Prism-Architecture-Complete.docx`, which carries all nine behind a contents
page. They are for people who will never open a repository.

**The Markdown is the master.** The `.docx` files are output: they are
regenerated, not edited. If you edit one by hand, the next build overwrites it.

```bash
python docs/architecture/build_docx.py
```

Real Word heading styles (so the navigation pane and the contents field both
work), native tables, and every diagram rendered to an image — wide ones on
their own landscape page. Diagrams need `node`; the build fetches
`@mermaid-js/mermaid-cli` through `npx` on demand and caches the results. With
no `node` on the machine, diagrams fall back to their source text in a
captioned box rather than failing the build.

Word's contents page opens empty by design: right-click it and choose **Update
Field → Update entire table** to fill in the page numbers.

---

## Maintaining this set

- **Each document names the files it describes**, so a change to the code has
  an obvious document to update.
- **Field tables come from the source, not from memory.** When a schema
  changes, update the table in [02-data-model.md](02-data-model.md) in the same
  commit.
- **When a fact here contradicts the code, the code wins** — fix the document
  and say so in the commit message.
- **Do not move product reasoning in here.** If a decision needs arguing, it
  belongs in `docs/DEFERRED.md` or `docs/AFTER_THE_MERGE.md`.
