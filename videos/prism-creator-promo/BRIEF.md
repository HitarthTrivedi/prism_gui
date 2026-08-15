---
workflow: product-launch-video
flow: automation
storyboard: no
message: "Your last collab's transcript is the brief for your next one — one prompt, one pipeline"
destination: shorts
aspect: 1080x1920
language: en
audience: creators-and-influencers
length: 60s
angle: one-task-one-pipeline
narration: no
---

## Intent

A 9:16 promo for **Prism**, aimed at YouTubers / creators planning their next
collaboration video. It follows one real job end to end: drop the transcript of
the last collab into Prism, and Prism's Groq router splits it into the stages
that job actually needs — look things up, think it through, write it up, make
the images — then drives each stage in the creator's *own* signed-in Chrome,
passing every stage's output forward as context to the next.

Sell, don't tour: the video markets the product, but the demonstration *is* the
argument. Prism's honesty is the hook — it doesn't replace ChatGPT, Claude,
Perplexity or NotebookLM, it routes to them and drives your own browser.

Tone: precise, unhypey, spectral. Discovering a sharp tool, not being sold a
platform. Watched muted — the piece carries itself on type and motion.

## Assets

- ../../assets/prism-logo.svg — the teal faceted prism mark; closing sting.
- ../../../img_2.png — real app screenshot: the plan rows (Look things up /
  Perplexity, Think it through / ChatGPT, Write it up / Claude, Make the images
  / ChatGPT) plus "Files you mentioned → ATTACHED". The evidence beat. Landscape,
  so it is cropped into vertical inset panels, never shown whole.
- ../../../img_1.png — real app screenshot: the empty task card, "Describe what
  you want done", Speak / Add file / Add folder / Make a plan. The setup beat.

## Customizations

- No voice-over. Vertical creator content is watched muted; type and motion carry it.
- The spectrum is literal, not decorative: one white prompt refracts downward
  into exactly the coloured stage bands the job needs. Each stage owns a band.
- Screenshots are staged as lit inset panels against the near-black canvas —
  cropped to the region that matters, never a whole desktop window.
- Close on the logo as a sting.

## Notes

- Every claim must be real. 25 tools across 7 categories; Groq LLaMA 3.3-70B
  routing brain; no passwords stored, it reuses existing Chrome sessions;
  `/remote` sends tasks from a phone; `/attach` puts any file into the pipeline
  (the GUI calls it "Add file"). Use the GUI's own wording, since the
  screenshots are the GUI.
- Anti-references from PRODUCT.md: no SaaS-cream hero-metric template, no
  "one AI does everything" magic-box claim, no generic dark-terminal costume
  with no idea underneath.
- Accessibility: colour never carries meaning alone — every spectrum band is
  labelled.
