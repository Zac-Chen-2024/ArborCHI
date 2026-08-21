"""Assemble the bilingual walkthrough page from the captured figures.

Reads `docs/figures/flow/steps.json` and the web-sized JPEGs beside it, and
writes a single self-contained HTML file with every screenshot inlined as a
data URI (an Artifact's CSP admits no external image host).

The captions live here; the *results* under each screenshot come from
steps.json, which capture_flow.py recorded from the live page and the live
event log. That split is the point: the prose is mine, the numbers are the
session's.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIG = ROOT / "docs" / "figures" / "flow"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "walkthrough.html"

# zh / en caption per step, keyed by the capture's own step name.
CAPTIONS = {
    "join": (
        "被试拿到一条一次性链接。按 Start 之前什么都不会开始——按下的瞬间落 "
        "<code>session_start</code>,时间从这里算。",
        "The participant gets a single-use link. Nothing starts until Start is "
        "pressed; that press stamps <code>session_start</code> and the clock "
        "begins there.",
    ),
    "setup": (
        "准备段:签署同意书、主试讲背景。屏幕上只有一张等待卡——工作区不渲染,"
        "服务端这一段发的也是**练习**材料包,所以就算前端出错也拿不到正式案件。",
        "Setup: consent and briefing. A waiting card only — the workspace does "
        "not render, and the server serves the <strong>practice</strong> bundle "
        "in this phase, so a client that misbehaved still could not fetch the "
        "real case.",
    ),
    "tutorial": (
        "讲解段:主试介绍界面。同样是等待卡。教界面的地方在下一段,用的是别的案子。",
        "Tutorial: the moderator explains the interface. Same waiting card. The "
        "interface gets taught in the next phase, on a different case.",
    ),
    "practice-gates": (
        "练习段:换成**另一个法条**(Original Contributions)、**另一个申请人**。"
        "界面可以学,案件学不到。两道关卡未过之前,主试推不动阶段——服务端会 409 "
        "并说明还差哪个。",
        "Practice: a <strong>different criterion</strong> (Original "
        "Contributions) and a <strong>different petitioner</strong>. The "
        "interface can be learned without learning the case. Until both gates "
        "are cleared the server refuses to advance, and says which is missing.",
    ),
    "practice-done": (
        "两道关卡都过了——选中一张证据卡、打开一次放大镜。横幅换成「等主试推进」。"
        "关卡是服务端记的,不是前端自己判定的。",
        "Both gates cleared — an evidence card selected, the magnifier opened "
        "once. The banner switches to waiting for the researcher. The gates are "
        "recorded server-side, not judged by the client.",
    ),
    "organization": (
        "组织段开始,真实案件出现:11 份 exhibit、18 张证据卡、机器提出的 3 主论点 / "
        "10 分论点。**倒计时是全场唯一一次出现钟**——15 分钟硬时限。被试在这里接受、"
        "改名、换父节点、拆分、合并、删除、重新挂证据。",
        "Organization begins and the real case appears: 11 exhibits, 18 evidence "
        "cards, and the machine's proposed 3 arguments / 10 sub-arguments. "
        "<strong>This is the only clock in the whole session</strong> — a hard "
        "15 minutes. Here the participant accepts, renames, re-parents, splits, "
        "merges, removes and re-assigns.",
    ),
    "linkage": (
        "点一张证据卡,四处同时动:左栏翻到被引页并画框、面包屑更新、对应分论点卡高亮、"
        "下方「这条证据讲的是谁」列出主谓宾三元组和他在本案其他出现处。"
        "这就是条件 C 与 B 的**唯一**差别——同样的文档,只是有没有人替你指。",
        "Selecting an evidence card moves four things at once: the page turns "
        "and the passage is boxed, the breadcrumb updates, the matching "
        "sub-argument card highlights, and the relations panel lists what the "
        "excerpt asserts plus where else he is named. This is the <em>only</em> "
        "difference between conditions C and B — same document, only the "
        "pointing differs.",
    ),
    "magnifier": (
        "放大镜 300%:真实文书页面(北京大学出版社/虎啸奖聘书等,由源 PDF 渲染),"
        "蓝框精确落在被引段落上。框按百分比定位,100/200/300% 每一档都对得准。"
        "**刻意不显示相邻候选框**——那等于界面替被试做判断,而判断正是被测的东西。",
        "The magnifier at 300%: the real document page, rendered from the source "
        "PDF, with the cited passage boxed. The box is positioned in "
        "percentages, so it holds at 100%, 200% and 300%. It <strong>deliberately "
        "shows no neighbouring candidate boxes</strong> — that would be the "
        "interface making the judgement the participant is being measured on.",
    ),
    "node-menu": (
        "分论点的操作菜单:重命名 / 拆成两条 / 与上一条合并 / 移到别的主论点下 / "
        "提升为主论点 / 删除。每一次操作都会记下节点**操作前后的完整快照**,"
        "不是差量——差量要靠重放才能读懂,而重放正是丢了一条事件就会断的东西。",
        "The sub-argument menu: rename, split in two, merge with the one above, "
        "move under another argument, promote, remove. Every operation logs the "
        "node's <strong>full state on both sides</strong> of it, not a delta — a "
        "delta is only readable by replaying everything before it, and replay is "
        "exactly what breaks when one event goes missing.",
    ),
    "edited": (
        "改名并接受两个分论点之后:计数器随之变化,卡片出现「Renamed」标。"
        "树的状态即刻存到服务端——早先它只活在浏览器内存里,刷一次页面整段工作就没了,"
        "而信照样生成,没有任何提示。",
        "After a rename and two accepts: the counters follow and the card gains a "
        "\"Renamed\" tag. The tree is saved to the server as it changes — it used "
        "to live only in browser memory, and a single refresh erased the whole "
        "phase while the letter still generated as if nothing had happened.",
    ),
    "softlock": (
        "时间到:软锁盖住整个工作区,10 秒宽限。经命中测试确认,遮罩后面的按钮、"
        "证据卡、菜单**没有一个够得到**。同时落 <code>phase_softlock</code>。"
        "(此图为把截止时刻前移生成,不是等了 15 分钟。)",
        "Time up: a soft lock covers the workspace after a 10-second grace "
        "period. Verified by hit test — not one button, card or menu behind it is "
        "reachable. A <code>phase_softlock</code> event is written. (Captured by "
        "moving the deadline, not by waiting fifteen minutes.)",
    ),
    "generation": (
        "生成段:信按被试整理好的树装配而成,10 段、逐句带真实引证。"
        "被试没动过的节点用预生成的**冻结**文本,动过的节点由 gpt-5.6-luna **现场**写。"
        "两者在页面上**无法区分**——属性、class、计算样式完全一致。此处无钟。",
        "Generation: the letter is assembled from the tree the participant "
        "organised — ten paragraphs, every sentence carrying a real citation. "
        "Untouched nodes take pre-generated <strong>frozen</strong> text; changed "
        "nodes are written <strong>live</strong> by gpt-5.6-luna. The two are "
        "<strong>indistinguishable</strong> on screen: same attributes, same "
        "classes, same computed styles. No clock here.",
    ),
    "stale": (
        "生成之后又改了结构,琥珀色横幅立刻提示「N 个段落不同步」并给出重新生成的入口。"
        "这条判据原先只认「没有段落的节点」,而改名和换父节点都留着段落——"
        "于是重构完全不提示,被试拿着一封和自己结构对不上的信继续核验。",
        "Restructuring after generation raises an amber banner — <em>N paragraphs "
        "out of sync</em> — with a way to regenerate. The check used to look only "
        "for nodes with no paragraph, and renaming and re-parenting both leave "
        "the paragraph in place, so the banner never appeared and the participant "
        "went on verifying a letter that no longer matched their structure.",
    ),
    "verification": (
        "核验段,被测的主任务:逐句对照它引用的原文,改掉站不住的地方。"
        "信里埋了 6 条错误、跨 5 类,其中 3 类只有打开 exhibit 逐字读才能发现。"
        "**没有倒计时,也没有软锁**——什么时候说「我核完了」本身就是数据。",
        "Verification, the measured task: check each sentence against the exhibit "
        "it cites and fix what does not hold up. Six errors are planted across "
        "five kinds; three of those kinds are findable only by opening the "
        "exhibit and reading it. <strong>No countdown and no lock</strong> — when "
        "they declare themselves finished is itself the data.",
    ),
    "cite-click": (
        "点信里的引证,直接跳到被引页并打开放大镜——不必先猜是哪份 exhibit、"
        "再翻到第几页。「有没有去查原文、查了多久」是因变量,所以查证这条路必须短。",
        "Clicking a citation in the letter jumps straight to the cited page and "
        "opens the magnifier — no guessing which exhibit, no paging to find it. "
        "Whether they checked the source and for how long is a dependent "
        "variable, so the path to checking has to be short.",
    ),
    "editing": (
        "双击进入编辑,整封信是一个文本域。改动按**句**记录血缘:一句拆成两句,"
        "日志里旧 id 会指向两个新 id。句 id 与快照、拷问段用的是同一套——"
        "早先编辑器自己造号,于是「被试改的是哪条植入句」根本答不出来。",
        "Double-click to edit; the whole letter is one field. Edits are tracked "
        "per <strong>sentence</strong>: split one in two and the log maps the old "
        "id onto both new ones. Those ids are the same ones the snapshot and the "
        "probe use — the editor used to mint its own, which left <em>which "
        "planted sentence did they correct</em> unanswerable.",
    ),
    "submit-confirm": (
        "提交前二次确认。提交是不可逆的:之后服务端拒收任何日志写入,核验段就此结束。"
        "而这个按钮就挨着 Help,原先单击一次就交了。",
        "Submitting asks first. It cannot be undone — the server refuses further "
        "log writes afterwards and the measured phase is over — and the button "
        "sits right next to Help. It used to go on one click.",
    ),
    "confidence": (
        "信心段:工作区被**整个替换**而不是覆盖,防止被试边答边回看初稿。"
        "两问——「我确信每一句都有证据支撑」7 点量表,以及「你认为还有几句有引证问题」。",
        "Confidence: the workspace is <strong>replaced</strong> rather than "
        "overlaid, so the draft cannot be re-read while answering. Two questions "
        "— a 7-point scale on whether every sentence is supported, and an "
        "estimate of how many still have citation problems.",
    ),
    "probe": (
        "拷问段:从被试**自己的终稿**里抽句,逐句问「引证是否支持这句话」。"
        "14 句取自 20 句的池,存活的植入句全部必抽,其余按分论点分层填补,"
        "植入占比封顶 60%——超过这个数,被试就开始答「这是不是又是个坑」了。",
        "The probe: sentences drawn from the participant's <strong>own final "
        "text</strong>, asked one at a time — <em>does the cited evidence support "
        "this?</em> Fourteen items from a pool of twenty; every surviving planted "
        "sentence is mandatory, the rest fill stratified by sub-argument, and "
        "planted items are capped at 60% — above that people start answering "
        "\"is this another trick one\" instead.",
    ),
    "probe-source": (
        "按「看原文」展开被引原文。给的是**摘录**而不是整页——如果原文一直摊在眼前,"
        "「有没有去查」就不再有答案。是否展开、展开了多久,都进日志。"
        "(这个按钮此前在真实材料下**根本不出现**:引证解析器不认 <code>C-1</code> "
        "这种带连字符的编号。)",
        "\"View source\" reveals the cited passage — the <strong>excerpt</strong>, "
        "not the whole page: if the evidence were permanently on screen, "
        "\"did they check?\" would have no answer. Whether they opened it and for "
        "how long both go into the log. (On real material this button "
        "<strong>did not appear at all</strong>: the citation parser did not "
        "accept hyphenated ids like <code>C-1</code>.)",
    ),
    "done": (
        "收场:被试看到结束页;主试那边跑一份 integrity 报告——日志连续性、心跳覆盖、"
        "快照存在与哈希、阶段配对、关卡、顺序、来源一致性、事件量对队列基线。"
        "判定 valid / review / invalid。",
        "Done: the participant sees a closing screen. On the moderator's side an "
        "integrity report runs — log continuity, heartbeat coverage, snapshot "
        "presence and hashes, phase pairing, gates, order, provenance, event "
        "volume against the cohort — returning valid, review or invalid.",
    ),
}


def data_uri(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def result_line(step: dict) -> list:
    """The facts the capture recorded on that screen, as label/value pairs."""
    o = step["observed"]
    out = []
    if o.get("clock_on_screen"):
        out.append(("clock", o["clock_on_screen"]))
    elif step["file"][3:-4] in ("verification", "generation", "cite-click", "editing",
                                "submit-confirm", "stale"):
        out.append(("clock", "none"))
    if o.get("criterion"):
        crit = o["criterion"].split("8 C.F.R")[0].strip()
        out.append(("criterion", crit))
    if o.get("letter_sentences"):
        out.append(("paragraphs", str(o["letter_sentences"])))
    if o.get("bbox_drawn"):
        out.append(("bbox drawn", str(o["bbox_drawn"])))
    if o.get("softlock") and step["file"][3:-4] == "softlock":
        out.append(("soft lock", "covering the workspace"))
    if o.get("titles_truncated"):
        out.append(("titles truncated", str(o["titles_truncated"])))
    return out


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    data = json.loads((FIG / "steps.json").read_text(encoding="utf-8"))
    steps = data["steps"]

    seen: set = set()
    blocks = []
    for s in steps:
        name = s["file"][3:-4]
        zh, en = CAPTIONS.get(name, (s["zh"], s["en"]))
        img = data_uri(FIG / "web" / (s["file"][:-4] + ".jpg"))
        new_events = sorted(set(s["log_events"]) - seen)
        seen = set(s["log_events"])

        results = "".join(
            f'<div class="r"><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>'
            for k, v in result_line(s)
        )
        if new_events:
            ev = " ".join(f"<span>{esc(e)}</span>" for e in new_events)
            results += f'<div class="r ev"><dt>events logged</dt><dd>{ev}</dd></div>'

        blocks.append(f"""
    <article class="step" id="step-{s['n']}">
      <div class="step-head">
        <span class="step-n">{s['n']:02d}</span>
        <span class="step-name">{esc(name)}</span>
      </div>
      <figure>
        <img src="{img}" alt="{esc(name)}" loading="lazy" width="1400">
      </figure>
      <div class="caption">
        <div class="zh"><p>{zh}</p></div>
        <div class="en"><p>{en}</p></div>
      </div>
      {f'<dl class="results">{results}</dl>' if results else ''}
    </article>""")

    integrity = steps[-1].get("integrity", {})
    html = TEMPLATE.replace("<!--STEPS-->", "\n".join(blocks))
    html = html.replace("<!--VERDICT-->", esc(str(integrity.get("verdict", "—"))))
    html = html.replace("<!--SESSION-->", esc(data["session_id"]))
    html = html.replace("<!--VIEWPORT-->",
                        f"{data['viewport']['width']}×{data['viewport']['height']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{len(steps)} steps -> {OUT}  ({OUT.stat().st_size / 1e6:.2f} MB)")
    return 0


TEMPLATE = (Path(__file__).parent / "walkthrough_template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    sys.exit(main())
