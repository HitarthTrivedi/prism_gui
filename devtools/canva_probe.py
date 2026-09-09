"""Does ChatGPT still hand a generated image to the Canva app the way
core/automation._make_editable expects? A Playwright probe on a COPY of
Prism's own Chrome profile, so it never fights a running Prism for the
profile lock and never spends anything Prism did not already sign in to.

    python3 devtools/canva_probe.py check
        read-only: opens chatgpt.com, types "@", screenshots the app picker
        (Canva listed = the app is connected) and the "+" menu.
    python3 devtools/canva_probe.py run
        spends ONE image generation and ONE Canva turn: sends the same
        first prompt Prism sends (agents._CANVA_SUFFIX), waits for the
        picture, then the follow-up, and reports the CANVA LINK it got.
    python3 devtools/canva_probe.py followup <chat url>
        the second half only, on a chat that already holds a picture.

Screenshots and the profile copy land in devtools/canva_probe_out/. What
the 2026-09-09 run found is written up in CHANGES.md (Round 18): the
hand-off works; Prism skipped it because an image-only reply captures no
text. Never packaged -- devtools/ is excluded by packaging/prism.spec.
"""
import json, os, re, shutil, sys, time

SRC_PROFILE = os.path.join(os.path.expanduser("~"), ".prism", "chrome_profile")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "canva_probe_out")
PROFILE = os.path.join(OUT, "profile")
COMPOSER = "#prompt-textarea"
SEND = "button[data-testid='send-button']"
ASSISTANT = "[data-message-author-role='assistant']"

POPUP_JS = """
() => {
  const sel = '[role=option], [role=menuitem], [role=listbox] *, [cmdk-item], [data-radix-popper-content-wrapper] *';
  const seen = new Set(); const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const t = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
    const r = el.getBoundingClientRect();
    if (!t || t.length > 80 || r.width < 5 || r.height < 5 || seen.has(t)) continue;
    seen.add(t); out.push({role: el.getAttribute('role') || el.tagName.toLowerCase(), text: t});
  }
  return out.slice(0, 60);
}
"""
TURNS_JS = """
() => {
  const out = {authorRole: document.querySelectorAll('[data-message-author-role]').length,
               turns: []};
  const turns = document.querySelectorAll("article, [data-testid^='conversation-turn']");
  for (const t of Array.from(turns).slice(-4)) {
    const attrs = {}; for (const a of t.attributes) attrs[a.name] = a.value.slice(0, 80);
    const inner = t.querySelector('[data-message-author-role], [data-message-id], [class*=markdown]');
    const iattrs = {}; if (inner) for (const a of inner.attributes) iattrs[a.name] = a.value.slice(0, 80);
    out.turns.push({tag: t.tagName, attrs, inner: iattrs, text: (t.innerText || '').slice(0, 160),
                    imgs: t.querySelectorAll('img').length});
  }
  return out;
}
"""
LAST_JS = """
() => {
  let msgs = document.querySelectorAll("[data-message-author-role='assistant']");
  if (!msgs.length) msgs = document.querySelectorAll("article, [data-testid^='conversation-turn']");
  const m = msgs[msgs.length - 1]; if (!m) return null;
  const links = Array.from(m.querySelectorAll('a[href]')).map(a => a.href);
  const imgs = Array.from(m.querySelectorAll('img')).map(i => i.src).filter(s => !s.startsWith('data:') || s.length > 5000);
  return {text: (m.innerText || '').slice(0, 3000), links, imgs: imgs.length,
          busy: !!document.querySelector("button[data-testid='stop-button']")};
}
"""

def fresh_profile():
    shutil.rmtree(PROFILE, ignore_errors=True)
    shutil.copytree(SRC_PROFILE, PROFILE, ignore=shutil.ignore_patterns(
        "Singleton*", "*.lock", "Cache", "Cache*", "Code Cache", "GPUCache",
        "ShaderCache", "GrShaderCache", "DawnCache", "Service Worker", "*.log",
        "BrowserMetrics*", "Crashpad", "RunningChromeVersion"), ignore_dangling_symlinks=True)

def shot(page, label):
    page.screenshot(path=os.path.join(OUT, f"{label}.png"))
    print(f"   [shot] {label}.png  {page.url[:80]}")

def wait_reply(page, timeout, need_image=False):
    """Until the stop button is gone and (optionally) an image is in the last bubble."""
    t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        page.wait_for_timeout(3000)
        last = page.evaluate(LAST_JS)
        if last and not last["busy"] and (last["imgs"] or not need_image) and last["text"].strip():
            return last
    return last

def main():
    from playwright.sync_api import sync_playwright
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if not os.path.isdir(SRC_PROFILE):
        print(f"no Prism profile at {SRC_PROFILE} -- run Prism and sign in to ChatGPT once first")
        return 1
    os.makedirs(OUT, exist_ok=True)
    fresh_profile()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=False,
            args=["--profile-directory=Default", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
            ignore_default_args=["--enable-automation", "--use-mock-keychain"])
        page = ctx.new_page()
        for extra in ctx.pages:
            if extra is not page: extra.close()
        chat = sys.argv[2] if mode == "followup" and len(sys.argv) > 2 else "https://chatgpt.com/"
        page.goto(chat, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        shot(page, "home")
        if mode == "followup":
            print("turns:", json.dumps(page.evaluate(TURNS_JS), ensure_ascii=False)[:2500])
            last = page.evaluate(LAST_JS)
            print("last turn imgs:", (last or {}).get("imgs"))
            if not last or not last["imgs"]:
                print("!! the chat has no image to hand over"); ctx.close(); return 2
        if not page.query_selector(COMPOSER):
            print("!! no composer — login wall?"); ctx.close(); return 1
        print("composer found:", COMPOSER)

        # 1. what does '@' offer?
        page.click(COMPOSER); page.keyboard.type("@")
        page.wait_for_timeout(2500)
        popup = page.evaluate(POPUP_JS)
        shot(page, "at_picker")
        print("@ picker items:", json.dumps(popup, ensure_ascii=False)[:1500])
        canva_items = [i for i in popup if "canva" in i["text"].lower()]
        print("Canva in the @ picker:", bool(canva_items), canva_items[:3])
        page.keyboard.press("Escape"); page.keyboard.press("Control+A"); page.keyboard.press("Backspace")

        # 2. the '+' menu (apps & connectors live here too)
        plus = page.query_selector("button[data-testid='composer-plus-btn'], button[aria-label*='Add' i], button[aria-label*='Attach' i]")
        if plus:
            plus.click(); page.wait_for_timeout(2000)
            menu = page.evaluate(POPUP_JS); shot(page, "plus_menu")
            print("+ menu items:", json.dumps(menu, ensure_ascii=False)[:1200])
            page.keyboard.press("Escape")
        if mode == "check":
            ctx.close(); return 0

        # 3. spend one generation: the same first prompt Prism sends
        suffix = ("DELIVERY FORMAT — generate the image yourself, directly, at the highest "
                  "quality you can. Do NOT route this through Canva or any other design "
                  "tool yet, even if one is connected: a template-built layout is not what "
                  "is being asked for. Return the generated image in your reply. I will ask "
                  "you to make it editable in a follow-up message once I have seen it.")
        prompt = ("Make an Instagram post image, square 1080x1080, for a tea brand: a steaming "
                  "cup of masala chai on a wooden table at sunrise, warm colours, with the "
                  "headline text 'Morning Ritual' at the top. " + suffix)
        if mode == "run":
            page.click(COMPOSER); page.keyboard.type(prompt); page.wait_for_timeout(800)
            page.click(SEND); print("sent the image prompt…")
            last = wait_reply(page, 300, need_image=True)
            shot(page, "image_reply")
            print("turns:", json.dumps(page.evaluate(TURNS_JS), ensure_ascii=False)[:1500])
            print("image reply:", json.dumps({k: (v if k != 'text' else v[:300]) for k, v in (last or {}).items()}, ensure_ascii=False))
            if not last or not last["imgs"]:
                print("!! no image came back — stopping before the Canva turn"); ctx.close(); return 2

        # 4. the follow-up, addressed to the app through the picker, not as plain text
        follow = ("can you make this design editable — import the image above into a "
                  "new Canva design in my account, at the same size, keeping the artwork as "
                  "the background so I can edit the text and layout on top of it. "
                  "Then reply with the Canva design URL on its own line, prefixed exactly "
                  "with 'CANVA LINK: '. If the Canva app is not connected to this account, "
                  "reply with only 'CANVA LINK: none'.")
        page.click(COMPOSER); page.keyboard.type("@Canva"); page.wait_for_timeout(2500)
        popup = page.evaluate(POPUP_JS); shot(page, "at_canva")
        print("@Canva picker:", json.dumps(popup, ensure_ascii=False)[:600])
        picked = False
        try:
            item = page.get_by_text("Create, review, edit designs", exact=False).first
            item.wait_for(timeout=4000); item.click(); picked = True
        except Exception as e:
            print("picker click failed:", str(e)[:120])
            try:
                page.get_by_text("Canva", exact=True).first.click(timeout=3000); picked = True
            except Exception as e2:
                print("fallback click failed:", str(e2)[:120])
        print("picked Canva from the picker:", picked)
        page.wait_for_timeout(1000)
        page.keyboard.type(" " + follow); page.wait_for_timeout(800)
        shot(page, "followup_typed")
        page.click(SEND); print("sent the Canva follow-up…")
        last = wait_reply(page, 240)
        shot(page, "canva_reply")
        text = (last or {}).get("text", "")
        links = (last or {}).get("links", [])
        m = re.search(r"canva link:\s*(\S+)", text, re.I)
        print("CANVA reply text:", text[:1200].replace("\n", " | "))
        print("links in reply:", links[:10])
        print("CANVA LINK line:", m.group(1) if m else None)
        print("canva.com link present:", any("canva.com" in l for l in links) or "canva.com" in text)
        print("chat url:", page.url)
        ctx.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
