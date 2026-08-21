"""Walk a whole session in a real browser and photograph every step.

Produces `docs/figures/flow/NN-name.png` plus a `steps.json` recording, per
step, what was actually on screen -- counters, phase label, whether a clock was
present, which events reached the log. The screenshots are for reading; the
recorded result is what makes them checkable, because a picture of a UI cannot
say whether the event behind it was logged.

Scripted rather than taken by hand so the figures can be regenerated when the
interface changes. A screenshot in a paper that no longer matches the software
is worse than no screenshot.

    python scripts/capture_flow.py --material judging_v1

Needs both dev servers up and `playwright install chromium` done once.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API = "http://127.0.0.1:8000/api/study"
APP = "http://localhost:5174"
OUT = Path(__file__).resolve().parents[2] / "docs" / "figures" / "flow"

# The width the three-column layout is designed for. Below roughly 1280 the
# middle column squeezes and every sub-argument title truncates.
VIEWPORT = {"width": 1512, "height": 945}

STEPS: list = []


def api(method, path, token=None, body=None):
    req = urllib.request.Request(API + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=180) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def events(session_id: str) -> list:
    from app.core import study
    session = study.load_session(session_id)
    path = study.session_dir(
        session["workspace_id"], session_id, session["track"]) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def observe(page) -> dict:
    """What is on screen right now, in facts rather than pixels."""
    return page.evaluate("""() => {
      const txt = (el) => (el ? el.innerText.replace(/\\s+/g, ' ').trim() : null);
      const header = [...document.querySelectorAll('header *')].map(e => e.textContent.trim());
      const clock = header.find(t => /^\\d+:\\d{2}$/.test(t)) || null;
      const panels = [...document.querySelectorAll('.phead')];
      return {
        phase_label: header.find(t => /^(Setting|Walkthrough|Practice|Organise|Generat|Review)/.test(t)) || null,
        clock_on_screen: clock,
        case_label: header.find(t => /EB-1A/.test(t)) || null,
        criterion: header.find(t => /Judging|Contributions|Leading/.test(t)) || null,
        counters: txt(panels[1]),
        sub_arguments: [...document.querySelectorAll('.sub')].map(s => ({
          title: s.querySelector('p')?.textContent.trim(),
          state: s.getAttribute('data-state'),
        })),
        titles_truncated: [...document.querySelectorAll('.sub p')]
          .filter(p => p.scrollWidth > p.clientWidth + 1).length,
        page_images: document.querySelectorAll('img').length,
        bbox_drawn: document.querySelectorAll('.paper .absolute.border-2, #lbPage .absolute').length,
        letter_sentences: document.querySelectorAll('.para').length,
        softlock: !!document.querySelector('.fixed.inset-0'),
        body_head: document.body.innerText.replace(/\\s+/g, ' ').trim().slice(0, 140),
      };
    }""")


def shot(page, name: str, zh: str, en: str, session_id: str, extra: dict | None = None):
    OUT.mkdir(parents=True, exist_ok=True)
    n = len(STEPS) + 1
    filename = f"{n:02d}-{name}.png"
    page.screenshot(path=str(OUT / filename))
    seen = events(session_id)
    STEPS.append({
        "n": n,
        "file": filename,
        "zh": zh,
        "en": en,
        "observed": observe(page),
        "log_events": sorted({e["event"] for e in seen}),
        "log_count": len(seen),
        **(extra or {}),
    })
    print(f"  {n:02d}  {name:<26} {zh}")



def close_lightbox(page):
    """Escape alone is not reliable enough to build a run on: one capture got
    as far as the magnifier and then timed out clicking a card the still-open
    dialog was covering."""
    if page.locator("#lb").count():
        btn = page.locator("#lbCard button[aria-label]").last
        if btn.count():
            btn.click()
    page.keyboard.press("Escape")
    page.wait_for_selector("#lb", state="detached", timeout=10_000)
    page.wait_for_timeout(500)


def settle(page, ms: int = 900):
    page.wait_for_timeout(ms)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="judging_v1")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    from app.core import study, workspace

    mod = workspace.mint_token("capture", role="moderator")["token"]
    code, s = api("POST", "/sessions", mod, {
        "condition": "c", "participant_code": "FIGURES", "lang": "en",
        "track": "test", "material_id": args.material})
    if code != 200:
        raise SystemExit(f"could not create session: {code} {s}")
    tok, sid = s["join_token"], s["session_id"]
    print(f"session {sid} on {args.material}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        page.goto(f"{APP}/join?token={tok}", wait_until="networkidle")
        settle(page)

        shot(page, "join", "被试看到的第一屏,按 Start 开始",
             "The first screen. The task begins on Start.", sid)

        page.click("button:has-text('Start')")
        settle(page, 1500)
        shot(page, "setup", "准备段:只有等待卡,服务端此时发的是练习材料包",
             "Setup: a waiting card only. The server serves the practice bundle here.", sid)

        api("POST", "/advance", mod, {"session_id": sid, "to": "tutorial"})
        page.reload(wait_until="networkidle")
        settle(page)
        shot(page, "tutorial", "讲解段:同样只有等待卡,主试在讲界面",
             "Tutorial: the same waiting card while the moderator explains.", sid)

        api("POST", "/advance", mod, {"session_id": sid, "to": "practice"})
        page.reload(wait_until="networkidle")
        settle(page, 2500)
        shot(page, "practice-gates", "练习段:另一个法条、另一个申请人,两道关卡待过",
             "Practice: a different criterion and petitioner, two gates to clear.", sid)

        page.click(".chip")
        settle(page, 700)
        page.click(".chip .zoom")
        settle(page, 1400)
        close_lightbox(page)
        shot(page, "practice-done", "两道关卡都过了,横幅变成「等主试推进」",
             "Both gates cleared; the banner switches to waiting for the researcher.", sid)

        api("POST", "/advance", mod, {"session_id": sid, "to": "organization"})
        page.reload(wait_until="networkidle")
        settle(page, 3000)
        shot(page, "organization", "组织段:真实案件材料,倒计时是全场唯一可见的钟",
             "Organization: the real case. The only visible clock in the session.", sid)

        page.click(".chip")
        settle(page, 1400)
        shot(page, "linkage", "点一张证据卡:面包屑、左栏定位、卡片、关系面板同时联动",
             "Selecting evidence moves breadcrumb, page, card and relations together.", sid)

        page.click(".chip .zoom")
        settle(page, 1800)
        page.click("button:has-text('300%')")
        settle(page, 1200)
        shot(page, "magnifier", "放大镜 300%:真实文书页面,蓝框精确落在被引段落上",
             "Magnifier at 300%: the real page, the cited passage boxed.", sid)

        close_lightbox(page)

        subs = page.locator(".sub")
        menu = subs.nth(3).locator("button[aria-label='Sub-argument actions']:visible").first
        menu.click()
        settle(page, 700)
        shot(page, "node-menu", "分论点菜单:重命名 / 拆分 / 上并 / 移到… / 提升 / 删除",
             "The sub-argument menu: rename, split, merge, move, promote, remove.", sid)

        page.locator(".sub").nth(3).locator("button:has-text('Rename')").click()
        settle(page, 600)
        inp = page.locator(".sub input").first
        inp.fill("Budget and hiring authority")
        inp.press("Enter")
        settle(page, 1600)
        for i in (0, 1):
            page.locator(".sub").nth(i).locator("button:has-text('Accept')").click()
            settle(page, 400)
        settle(page, 1200)
        shot(page, "edited", "改名并接受两个分论点后:计数器随之变化,改动即刻存到服务端",
             "After a rename and two accepts: counters follow, and the tree is saved server-side.", sid)

        # Force the countdown to expire rather than waiting fifteen minutes.
        # The deadline is what softlock_due reads; writing any other key just
        # adds a field nothing looks at, which is how the first run produced a
        # "soft lock" screenshot with 14:35 still on the clock.
        def backdate(rec):
            grace = 10_000
            rec["phase_deadline_ms"] = study.now_ms() - grace - 2_000
            return rec
        study.update_session(sid, backdate)
        page.wait_for_timeout(4000)
        if not page.evaluate("() => !!document.querySelector('.fixed.inset-0')"):
            raise SystemExit("soft lock did not appear -- refusing to photograph it as if it had")
        shot(page, "softlock", "时间到:软锁盖住工作区,10 秒宽限,指针够不到任何控件",
             "Time up: a soft lock covers the workspace; nothing behind it is reachable.", sid)

        api("POST", "/advance", mod, {"session_id": sid, "to": "generation"})
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".para", timeout=180_000)
        settle(page, 1500)
        shot(page, "generation", "生成段:信按树装配而成,逐句带引证;此处无时钟",
             "Generation: the letter is assembled from the tree, every sentence cited. No clock.", sid)

        menu2 = page.locator(".sub").nth(2).locator(
            "button[aria-label='Sub-argument actions']:visible").first
        menu2.click()
        settle(page, 600)
        page.locator(".sub").nth(2).locator("button:has-text('Rename')").click()
        settle(page, 600)
        inp2 = page.locator(".sub input").first
        inp2.fill("Reporting line and span of control")
        inp2.press("Enter")
        settle(page, 1600)
        shot(page, "stale", "改完结构后:琥珀色横幅提示信与结构不同步",
             "After restructuring: an amber banner says the letter is out of sync.", sid)

        api("POST", "/advance", mod, {"session_id": sid, "to": "verification"})
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".para", timeout=180_000)
        settle(page, 1500)
        shot(page, "verification", "核验段:被试逐句对照原文;无倒计时、无软锁",
             "Verification: check each sentence against its exhibit. No countdown, no lock.", sid)

        page.locator(".cite").nth(3).click()
        page.wait_for_timeout(2200)
        if page.locator("#lb").count():
            raise SystemExit("a citation click opened the magnifier -- it must only locate")
        shot(page, "cite-click", "点信里的引证:左栏跳到被引页、画框、滚到居中。放大镜**不会**自己弹出",
             "Clicking a citation turns to the cited page, boxes the passage and "
             "centres it. The magnifier does <strong>not</strong> open by itself.", sid)

        page.hover(".bbox")
        settle(page, 700)
        shot(page, "bbox-hover", "鼠标移到框上:出现放大提示,光标变成 zoom-in",
             "Hovering the box offers the magnifier; the cursor becomes zoom-in.", sid)

        page.click(".bbox")
        settle(page, 1600)
        shot(page, "bbox-zoom", "点框才打开放大镜。点弹层以外任意位置即关闭",
             "Clicking the box opens the magnifier. Clicking anywhere outside it closes.", sid)

        close_lightbox(page)
        page.locator(".para p").first.dblclick()
        settle(page, 900)
        shot(page, "editing", "双击进入编辑:整封信是一个文本域,改动按句记录血缘",
             "Double-click to edit: the whole letter is one field; edits are tracked per sentence.", sid)

        page.keyboard.press("Escape")
        settle(page, 600)
        page.click("header button:has-text('Submit final')")
        settle(page, 900)
        shot(page, "submit-confirm", "提交前二次确认:提交不可逆",
             "Submitting asks first, because it cannot be undone.", sid)

        page.click(".fixed.inset-0 button:has-text('Submit final')")
        settle(page, 2500)

        api("POST", "/advance", mod, {"session_id": sid, "to": "confidence"})
        page.reload(wait_until="networkidle")
        settle(page, 2000)
        shot(page, "confidence", "信心段:工作区被整个替换,防止边答边回看初稿",
             "Confidence: the workspace is replaced so the draft cannot be re-read.", sid)

        page.click("button:has-text('5')")
        settle(page, 400)
        page.fill("input[type=number]", "3")
        settle(page, 400)
        page.click("button:has-text('Continue')")
        settle(page, 1500)

        api("POST", "/advance", mod, {"session_id": sid, "to": "probe"})
        page.reload(wait_until="networkidle")
        settle(page, 2500)
        shot(page, "probe", "拷问段:逐句提问「引证是否支持这句话」,附看原文按钮",
             "Probe: one sentence at a time, with a View source button.", sid)

        page.click("button:has-text('View source')")
        settle(page, 1800)
        shot(page, "probe-source", "拷问段查原文:是否查过、查了多久,都是因变量",
             "Checking the source during the probe. Whether and how long is a measure.", sid)

        code, probe = api("POST", "/probe/start", tok)
        for i in range(len(probe.get("items", []))):
            api("POST", "/probe/answer", tok, {
                "probe_index": i, "judgment": "supported" if i % 2 else "not_supported",
                "rt_ms": 1500 + i * 200, "source_opened": i % 3 == 0})

        api("POST", "/advance", mod, {"session_id": sid, "to": "done"})
        page.reload(wait_until="networkidle")
        settle(page, 1800)
        code, report = api("POST", f"/close/{sid}", mod, {})
        shot(page, "done", "收场:被试看到结束页,主试拿到 integrity 报告",
             "Done: the participant sees a closing screen; the moderator gets an integrity report.",
             sid, extra={"integrity": report})

        browser.close()

    (OUT / "steps.json").write_text(
        json.dumps({"session_id": sid, "material": args.material,
                    "viewport": VIEWPORT, "steps": STEPS},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total = sum((OUT / s["file"]).stat().st_size for s in STEPS)
    print(f"\n{len(STEPS)} steps, {total / 1e6:.1f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
