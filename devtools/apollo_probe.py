"""Find out where Apollo puts its prompt boxes today.

Apollo re-skins its People page often and hashes its class names per deploy,
so when a run comes back with the prompt sitting in the wrong field, this is
the script to run before touching `core/agents.py`. It opens a COPY of Prism's
own Chrome profile (so the Apollo login it holds is reused and the real
profile is never locked or written), loads the People page, and prints every
visible input / textarea / contenteditable together with the buttons that
mention AI — once on the page as loaded, once after "Search with AI", and once
with the AI Assistant panel open. Screenshots and JSON dumps land beside this
file under `apollo_probe_out/`.

    python3 devtools/apollo_probe.py            # look, type nothing
    python3 devtools/apollo_probe.py type "Find CTOs at fintechs in Pune"

`type` puts the text into the AI search box and presses Enter. That spends one
of the account's assistant chats, so it is not the default.

Needs the Playwright Python package and a real Chrome. Two things it does that
are easy to get wrong elsewhere: it launches the `chrome` channel rather than
Playwright's bundled Chromium, and it strips Playwright's default
`--use-mock-keychain` — with that flag Chrome cannot read "Chrome Safe
Storage", every cookie value decrypts to garbage, and Apollo shows a login
wall even though the profile is signed in.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

SRC_PROFILE = os.path.join(os.path.expanduser("~"), ".prism", "chrome_profile")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apollo_probe_out")
PROFILE = os.path.join(OUT, "profile")

# The three fields that matter, attribute-based. Keep in step with the
# Apollo entry in core/agents.py.
AI_SEARCH = "input[role='combobox'][placeholder^='Example:']"
ASSISTANT = "textarea[placeholder='What can I help you do?']"
TOOLBAR = "input[data-element='finder-toolbar-search-input']"

DUMP_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll(
        'input, textarea, [contenteditable="true"], [role="textbox"]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 5 || r.height < 5) continue;
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value.slice(0, 140);
    out.push({tag: el.tagName.toLowerCase(), attrs,
              rect: [r.x, r.y, r.width, r.height].map(Math.round),
              value: (el.value || el.innerText || '').slice(0, 80)});
  }
  return out;
}
"""
BUTTONS_JS = """
() => Array.from(document.querySelectorAll('button, [role=button]'))
  .map(b => ({text: (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 60),
              id: b.id}))
  .filter(b => /AI|Assistant|Research|Search with/i.test(b.text))
"""


def fresh_profile() -> None:
    shutil.rmtree(PROFILE, ignore_errors=True)
    shutil.copytree(SRC_PROFILE, PROFILE, ignore=shutil.ignore_patterns(
        "Singleton*", "*.lock", "Cache", "Cache*", "Code Cache", "GPUCache",
        "ShaderCache", "GrShaderCache", "DawnCache", "Service Worker", "*.log",
        "BrowserMetrics*", "Crashpad"))


def dump(page, label: str) -> None:
    inputs = page.evaluate(DUMP_JS)
    buttons = page.evaluate(BUTTONS_JS)
    page.screenshot(path=os.path.join(OUT, f"{label}.png"))
    with open(os.path.join(OUT, f"{label}.json"), "w") as f:
        json.dump({"url": page.url, "inputs": inputs, "buttons": buttons}, f, indent=1)
    print(f"\n== {label}  ({page.url[:90]})")
    for i in inputs:
        print("  input ", json.dumps(i)[:300])
    for b in buttons:
        print("  button", json.dumps(b))


def main() -> int:
    from playwright.sync_api import sync_playwright

    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    prompt = sys.argv[2] if len(sys.argv) > 2 else ""
    if not os.path.isdir(SRC_PROFILE):
        print(f"no Prism profile at {SRC_PROFILE} — run Prism and sign in to "
              "Apollo once first")
        return 1
    os.makedirs(OUT, exist_ok=True)
    fresh_profile()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=False,
            args=["--profile-directory=Default",
                  "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
            ignore_default_args=["--enable-automation", "--use-mock-keychain"])
        page = ctx.new_page()
        for extra in ctx.pages:
            if extra is not page:
                extra.close()
        page.goto("https://app.apollo.io/#/people", wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        if not page.url.startswith("https://app.apollo.io") or "login" in page.url:
            dump(page, "login_wall")
            print("\nApollo is not signed in inside Prism's profile. Open Prism, "
                  "use its Login tabs, sign in to Apollo, then rerun.")
            ctx.close()
            return 1

        dump(page, "people_page")
        # "Research with AI" is a harmless menu. "Search with AI" is not
        # opened here: it starts an assistant chat and spends a chat.
        btn = page.get_by_role("button", name="Research with AI")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2500)
            dump(page, "research_with_ai")
            page.keyboard.press("Escape")
        page.get_by_role("button", name="AI Assistant").first.click()
        page.wait_for_timeout(3500)
        dump(page, "ai_assistant")
        page.keyboard.press("Escape")

        print("\nwhere things are right now:")
        for label, sel in (("AI search box", AI_SEARCH),
                           ("AI Assistant textarea", ASSISTANT),
                           ("toolbar keyword box", TOOLBAR)):
            n = page.locator(sel).count()
            print(f"  {label:24s} {sel:60s} -> {n} match(es)")

        if mode == "type" and prompt:
            box = page.locator(AI_SEARCH).first
            if not box.count():
                # The box only exists while no search is applied. "Reset
                # filters" clears one; "Search with AI" would NOT help — it
                # opens a chat about the current search and spends a chat.
                reset = page.get_by_role("button", name="Reset filters")
                if reset.count():
                    reset.first.click()
                else:
                    page.evaluate("() => { location.hash = '#/people' }")
                page.wait_for_timeout(4000)
                box = page.locator(AI_SEARCH).first
            box.click()
            box.fill(prompt)
            page.keyboard.press("Enter")
            for t in range(24):          # up to two minutes
                page.wait_for_timeout(5000)
                total = page.locator("text=/^Total/").first
                rows = page.locator("[role='row'], tr").count()
                print(f"  t={5 * (t + 1):3d}s rows={rows}")
                if rows > 1:
                    break
            dump(page, "after_prompt")
        ctx.close()
    print(f"\nscreenshots and dumps: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
