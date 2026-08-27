# Prism — Artifact Capture (spec)

**Roadmap item.** Production-Readiness **C2** · Priority **P0**.
**Layer.** Engine (`prism_terminal/core/automation.py`), read into the GUI's
existing `ARTIFACTS_DIR` + `artifacts_panel`.
**Status.** Mitigation shipped; real capture — detection pending live DOM.

---

## 1. The problem (live-seen 27-08-2026)
A task ran Consensus → Claude → ChatGPT. Claude answered by putting the real
work in a **DOCX artifact pane** beside the chat; the chat itself held only a
preamble — *"I'll build you a real document…"*. Three failures cascaded from one
cause:

1. **Premature settle.** `_capture` reads only the chat reply selector. The chat
   text (the preamble) stopped growing, so `_smart_wait` thought Claude was
   *done*.
2. **Broken handoff.** Claude's real output was never captured, so nothing
   useful was forwarded — ChatGPT effectively restarted the task.
3. **Lost deliverable.** The document never entered the pipeline or the
   Artifacts panel.

**Root cause:** Prism cannot *see* an artifact / document / canvas pane. Modern
chat LLMs increasingly move long or structured answers there, so the browser
path silently loses a stage's best work. This is BUGS.md #3.

## 2. Principles
- **The chat is not the whole page.** A stage's answer may live in a side pane;
  capture must consider the page, not just the reply selector.
- **Prefer text, fall back to the file.** If the pane's text is readable, use it
  as the response (so settle + handoff work). If it is a real file (DOCX/PDF),
  download it to `ARTIFACTS_DIR` and hand forward a text extraction + a link.
- **Never worse than today.** If detection finds nothing, behaviour is exactly
  the current chat-only capture. No regression.
- **Selectors are borrowed markup.** Site DOM changes often; detection must be
  defensive and server-overridable (same posture as `response_selector`).

## 3. The fix, in layers
**Layer A — mitigation (SHIPPED).** Prose (non-machine-shaped) stage prompts now
carry: *"write your COMPLETE answer in this chat; do not use a document /
canvas / artifact — only the chat is read."* Stops the bleeding for compliant
models. Not sufficient alone: a model may still use an artifact, and the user
may *want* the artifact.

**Layer B — presence detection.** After `_smart_wait` settles, decide whether an
artifact pane exists. Robust signals, cheapest first:
- The chat reply is short and preamble-shaped (*"I'll … document / canvas …"*)
  **and** the page has a much larger text region outside the conversation
  column.
- A known artifact container is present (Claude: the artifact/preview pane;
  ChatGPT: the canvas pane). Selectors live in `agent_cfg` (server-overridable),
  **derived from live DOM inspection — not guessed.**

**Layer C — extraction.**
- *Text artifact* (doc/markdown/code shown as text): read the pane's text;
  use it as the stage response. Solves settle + handoff at once.
- *File artifact* (a real DOCX/PDF with a download control): click download →
  save into `ARTIFACTS_DIR` → extract text (existing `core.files`) for the
  handoff → record the file so `artifacts_panel` shows it.

**Layer D — integration.** Feed the extracted text into `stage_responses`
exactly where chat text goes today (before `all_responses[stage] = …`), and
`all_links[stage]` / an artifact record for the panel. Everything downstream is
unchanged.

## 4. Failure semantics
| Condition | Behaviour |
|---|---|
| No pane detected | Current chat-only capture. No change. |
| Pane detected, text unreadable | Try download; if that fails, keep chat text + warn. |
| Download blocked/sandboxed | Keep the pane text; link the tab. |
| Selector drift | Falls back to the short-reply + big-region heuristic, then to chat-only. |

## 5. The honest limitation
Layer B/C need the **real DOM of Claude's artifact pane and ChatGPT's canvas**.
Those selectors must be *read from the live page*, not guessed — guessing is the
most likely reason an earlier attempt "didn't work." Two ways to get them:
1. **Inspect live** (in-app browser against claude.ai with the user signed in) —
   read the artifact pane's structure, pin the selectors, ship them
   server-overridable.
2. **Heuristic-first** (no selectors): capture the largest text region outside
   the conversation column when the reply is preamble-shaped. Less precise, but
   site-agnostic and a safe first cut to test on a real run.

## 6. Rollout
- **P0 now:** Layer A (done) + Layer B/C heuristic-first, tested on one real run.
- **P1:** pin Claude/ChatGPT selectors from live DOM; add file-download path +
  `artifacts_panel` record; server-overridable selectors.
