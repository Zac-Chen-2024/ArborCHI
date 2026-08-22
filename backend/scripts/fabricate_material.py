"""Fabricate a complete exhibit set by replicating a real one, entity for entity.

Takes exhibit group C of the source filing -- award-committee certificates, an
industry association's own pages, and three news reports -- and produces a
parallel set in which every name, organisation, award, publication, brand, date
and figure has been replaced with an invented one. The result is a filing that
has never existed, about a person who has never existed, with the same shape as
one that does.

## Why replicate rather than invent from nothing

The interface has to be learned on material that behaves like the real thing:
citations that resolve, pages that scroll, passages that sit where a bbox says
they sit, documents of several genres. Prose invented from scratch tends to be
uniform -- every page the same register, the same length, the same density --
and an interface learned on it does not prepare anyone for a scan of a seal, a
news page with a navigation strip across the top, or a bilingual association
profile.

So the layout is not imitated, it is **reused**: every page keeps the original's
block rectangles, and the substituted text is drawn back into those same boxes.
The bboxes therefore remain exactly valid, and a bundle built from this set can
point at a passage with the same coordinates the real one uses.

## What is and is not preserved

Preserved: page count, block layout and bboxes, block kinds, the genre of each
document, roughly the length of every passage.

Replaced: the petitioner, every other named person, the association, the award,
the committee, every company, every publication, both universities, both
ministries, the seal number, and every date and headline figure.

Nothing carried over identifies anyone. That is the point: the practice phase
must teach the interface without teaching the case, and material derived from a
living person's filing cannot do that safely no matter how the names are
handled.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

SRC = Path(r"F:/Python-Project/Arbor_CHI_2027/data/Dehuan Liu/OCR/ocr_results_l")
OUT = Path(r"F:/Python-Project/Arbor_CHI_2027/TRY")

# Exhibit C-10 of the source is a private email and is not replicated.
#
# g5 and d8 are not in group C. They are here because the criterion's evidence
# cites them: a book the petitioner edited and a paper he co-wrote. A set that
# leaves them out is not a replica of the filing, it is a replica of one folder
# of it.
EXHIBITS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "g5", "d8"]

PAGE_WIDTH = 1400

FONTS = {
    "regular": r"C:/Windows/Fonts/times.ttf",
    "bold": r"C:/Windows/Fonts/timesbd.ttf",
    "italic": r"C:/Windows/Fonts/timesi.ttf",
    "sans": r"C:/Windows/Fonts/arial.ttf",
    "sans_bold": r"C:/Windows/Fonts/arialbd.ttf",
}

# Applied in order, longest first, so no replacement eats a prefix of another.
# Ordering matters more than it looks: "China Advertising Association of
# Commerce" must be replaced before "China", or the long name is left holding a
# substituted fragment.
SUBSTITUTIONS: list[tuple[str, str]] = [
    # -- the book (G-5) and the paper (D-8) --------------------------------
    #
    # Publications, their catalogue entries, and the people credited in them.
    # A book's colophon identifies a person as precisely as a name does: an
    # ISBN, a CIP number and a press address between them name exactly one
    # book, and that book has one editor-in-chief.
    ("Market Research and Applications", "Market Study and Practice"),
    ("Market Research and Application", "Market Study and Practice"),
    ("Market Survey Textbook", "Market Study: A Textbook"),
    ("Modern Market Research", "Contemporary Market Study"),
    ("National Market Research Association", "National Market Study Association"),
    ("Center for Market and Media Research", "Centre for Market and Media Study"),
    ("21st Century Journalism and Communication Series",
     "Twenty-First Century Communication Studies Series"),
    ("978- 7- 301- 10091- 2", "978- 7- 902- 41773- 6"),
    ("978-7-301-10091-2", "978-7-902-41773-6"),
    ("F. 1302", "F. 4417"),
    ("F.713.5", "F.740.2"),
    ("(2005) No. 131218", "(2005) No. 274905"),
    ("No. 205 Chengfu Road, Haidian District, Beijing 100871",
     "No. 88 Yunqi Road, Xihu District, Hangzhou 310013"),
    ("http://www.pup.cn", "http://www.nhup.cn"),
    ("ss@pup.pku.edu.cn", "ss@nhup.nanhu.edu.cn"),
    ("fd@pup.pku.edu.cn", "fd@nhup.nanhu.edu.cn"),
    ("010- 62752024", "010- 84913077"),
    ("62752015", "84910211"),
    ("62750672", "84910348"),
    ("62765016", "84910592"),
    ("62754962", "84910736"),
    ("Xinhua Bookstore", "Cloudgate Bookshops"),
    ("World Knowledge Printing House", "Riverbend Printing House"),
    ("Spring Studio", "Nine Rivers Studio"),
    ("Zhou, Lijin", "Han, Ruoxi"),
    ("Lijing Zhou", "Ruoxi Han"),
    ("Zhou Jing", "Cao Meilin"),
    ("Jing Zhou", "Meilin Cao"),
    ("Ren, Jing", "Tang, Yuan"),
    ("Jing Ren", "Yuan Tang"),
    ("Siluo Chen", "Yanting Qiu"),
    # ISMAS is the paper's own proposed model, so it names its authors as
    # surely as the byline does. AIDMA and AISAS are other people's published
    # frameworks and stay: a fabricated paper may cite the literature.
    ("ISMAS", "IRMAP"),
    # Real firms and real people the text makes claims about. A fabricated
    # document that says what a named living person wrote is worse than one
    # that names nobody.
    ("Nao Bai Jin", "Golden Rest"),
    ("Yuzhu Shi", "Zhenhai Mu"),
    ("Qin Chi", "Yunhe"),
    ("Procter & Gamble", "Halcyon Household"),
    ("E·S·Lewis", "R·T·Alder"),
    ("E. S. Lewis", "R. T. Alder"),

    # -- the award ---------------------------------------------------------
    ("Tiger Roar Award Ended Successfully", "Blue Lantern Award Ended Successfully"),
    ("Tiger Roar Awards Organizing Committee", "Blue Lantern Awards Organizing Committee"),
    ("Tiger Roar Awards", "Blue Lantern Awards"),
    ("Tiger Roar Award", "Blue Lantern Award"),
    ("TIGER ROAR", "BLUE LANTERN"),
    ("Tiger Roar", "Blue Lantern"),

    # -- the association and its committee ---------------------------------
    ("China Advertising Association of Foreign Economy and Trade",
     "China Digital Commerce Association of Foreign Trade"),
    ("China Advertising Association of Foreign Trade",
     "China Digital Commerce Association of Trade"),
    ("China Advertising Association of Commerce", "China Digital Commerce Association"),
    ("Advertising Association of Commerce", "Digital Commerce Association"),
    ("Digital Marketing Committee of China", "Smart Retail Committee of China"),
    ("Digital Marketing Committee", "Smart Retail Committee"),
    ("China Digital Marketing Conference", "China Smart Retail Conference"),
    ("China Digital Marketing Commendation Conference",
     "China Smart Retail Commendation Conference"),
    ("digital marketing", "smart retail"),
    ("Digital Marketing", "Smart Retail"),
    ("CAAFET", "CDCFET"),
    ("CAAFT", "CDCFT"),
    ("CAAC", "CDCA"),
    ("DMCC", "SRCC"),

    # -- people -------------------------------------------------------------
    ("Dehuan Liu", "Ruiheng Fang"),
    ("Liu Dehuan", "Fang Ruiheng"),
    ("LIU Dehuan", "FANG Ruiheng"),
    ("Liu, Dehuan", "Fang, Ruiheng"),
    ("Xubin Chen", "Zhiyuan Tan"),
    ("Chen Xubin", "Tan Zhiyuan"),
    ("Xiaodong Zheng", "Meilin Guo"),
    ("Zheng Xiaodong", "Guo Meilin"),
    ("Jun Yao", "Hao Qin"),
    ("Xisha Li", "Yanshu Wei"),
    ("Liping Sun", "Jianwen Xu"),
    # The OCR drops the space in one place; the variant has to go too.
    ("LipingSun", "JianwenXu"),
    ("Professor Sun", "Professor Xu"),
    ("Sun Liping", "Xu Jianwen"),
    ("Libin Liu", "Chenyu Bai"),
    ("Xiaoli Zhang", "Hongru Mei"),
    ("Xiaoguang Yang", "Tianlin Shao"),
    ("Yuhong", "Yuchen Lai"),
    ("Zhiming Guo", "Nanshu Fu"),
    ("Fei Gao", "Bingwen Yu"),
    ("Jingying Tan", "Ruoxi Cen"),
    ("Li Li", "Wei Deng"),

    # -- companies and brands ----------------------------------------------
    ("ZEISS Vision", "LUMEN Optics"),
    ("ZEISS Group", "LUMEN Group"),
    ("ZEISS", "LUMEN"),
    ("iG Esports Club", "RX Esports Club"),
    ("NetEase Media Group", "Kanyu Media Group"),
    ("NetEase", "Kanyu"),
    ("Leo Digital Network", "Lanxin Digital Network"),
    ("LeEco Holdings", "Yunqi Holdings"),
    ("Letv", "Yunqi"),
    ("Baidu", "Beiyuan"),
    ("Google", "Northsky"),
    ("Tencent", "Haitu"),
    ("Alibaba", "Qiantang"),
    ("Acxiom", "Datamere"),
    ("Criteo", "Adverra"),
    ("Trend Watch", "Trendscope"),
    ("Bolun", "Cangyu"),
    ("Balloon", "Cangyu"),
    ("Sina", "Weiyu"),

    # -- publications --------------------------------------------------------
    ("PR Newswire", "Newswire Asia"),
    ("CHINADAILY.COM.CN", "CNBUSINESSREVIEW.COM"),
    ("China Daily", "CN Business Review"),
    ("Global TMT", "Global Digital Brief"),
    ("Cision Ltd", "Vantle Ltd"),
    ("Cision", "Vantle"),
    ("Eastday", "Eastport"),
    ("Sohu", "Qingzhou"),

    # -- institutions --------------------------------------------------------
    ("Tsinghua University", "Jinling University"),
    ("Peking University", "Nanhu University"),
    ("Ministry of Commerce", "Ministry of Trade"),
    ("Ministry of Civil Affairs", "Ministry of Public Affairs"),
    ("Peking Opera", "Kunqu Opera"),

    # -- figures, in the phrases that carry them ----------------------------
    ("92 final review judges", "76 final review judges"),
    ("92 judges for final review", "76 judges for final review"),
    ("92 judges", "76 judges"),
    ("416 shortlisted companies", "388 shortlisted companies"),
    ("over 1,000 selected case works", "over 900 selected case works"),
    ("650+ public jury", "540+ public jury"),
    ("90+ final judging panel", "70+ final judging panel"),
    ("10+ executive members", "8+ executive members"),
    ("over 4,000 case works", "over 3,200 case works"),
    ("more than 4,000", "more than 3,200"),
    ("800 participating companies", "640 participating companies"),
    ("20 largest", "16 largest"),
    ("1100000195568", "1100000287431"),

    # -- dates ---------------------------------------------------------------
    ("December 21, 2021", "November 16, 2023"),
    ("11th Council", "9th Council"),
    ("13th", "9th"),
    ("held for 13 sessions", "held for 9 sessions"),
    ("Apr. 14 to Apr. 16, 2022", "Sep. 6 to Sep. 8, 2023"),
    ("Apr. 21, 2022", "Sep. 13, 2023"),
    ("Aug. 23, 2022", "Sep. 15, 2023"),
    ("Aug. 19, 2022", "Sep. 12, 2023"),
    ("August 19th", "September 12th"),
    ("Aug. 14, 2015", "Jun. 25, 2017"),
    ("Aug. 19", "Sep. 12"),
    ("Apr.19,2016", "Jul.30,2018"),
    ("Apr. 2022", "Oct. 2023"),
    ("Jan. 2016", "Mar. 2018"),
    ("January 21st", "March 18th"),
    ("January 21", "March 18"),
    ("in 1981", "in 1984"),
    ("Founded in 1981", "Founded in 1984"),
    ("September 2005", "September 2007"),
    ("In Sep. 2005", "In Sep. 2007"),
    ("2022", "2023"),
    ("2021", "2023"),
    ("2019", "2021"),
    ("2016", "2018"),
    ("2015", "2017"),
]


# Everyone else the source happens to name: council members, committee
# delegates, a company officer, one foreign judge. They are bystanders in
# someone else's filing and consented to appear in a study's practice material
# exactly as much as the petitioner did -- which is not at all. Mapped
# mechanically rather than by hand so none is forgotten, and the resulting
# pairs are written into substitutions.json so the set can be audited.
TAIL_PEOPLE = [
    "Bei Hong", "Bofan Wu", "Cui Yuhong", "Ding Junjie", "Du Li", "Gao Jun",
    "Han Yibing", "Hu Jiping", "Huang Xiaochuan", "Jian Xiong", "Jianyun Hang",
    "Jingwen Zhong", "Jun Yuan", "Junhui Zhang", "Keren Zhou", "Li Xiannian",
    "Li Xisha", "Liu Yang", "Ma Xiaobo", "Mingchao Xiao", "Qu Weihai",
    "Shengnan Ren", "Shuai Yuan", "Tomaz Mok", "Tong Su", "Tu Yafang",
    "Wang Jianchao", "Wang Qimin", "Wang Xin", "Wei Guo", "Wenquan Zhao",
    "Xiao Dai", "Xiaoke Li", "Xue Sun", "Yang Liu", "Yi Shi", "Yi Shu",
    "Yiding Shao", "Yonghua Lei", "Yougui Jiang", "Yu Kong", "Zander Hattingh",
    "Zeng Yi", "Zhao Yan", "Zheng Luo",
]

_GIVEN = ["Anwen", "Boyan", "Chunlin", "Duoyu", "Enhe", "Fanyu", "Guanru",
          "Haocheng", "Jinbo", "Kaiwen", "Lianshu", "Mingxu", "Nianzu",
          "Peiyao", "Qixuan", "Rongzhi", "Shuyan", "Tianhe", "Wanru", "Yuqian"]
_FAMILY = ["An", "Cao", "Dai", "Fei", "Gong", "He", "Jiang", "Kong", "Lu",
           "Mou", "Ning", "Pei", "Qiao", "Rong", "Shen", "Tian", "Wan",
           "Xue", "Yin", "Zhu"]


def _pseudonyms() -> list:
    pool = [f"{g} {f}" for f in _FAMILY for g in _GIVEN]
    if len(TAIL_PEOPLE) > len(pool):
        raise SystemExit("not enough invented names for the people in this set")
    pairs = []
    for i, real in enumerate(sorted(set(TAIL_PEOPLE))):
        invented = pool[i]
        pairs.append((real, invented))
        # The source writes some names both ways round; both have to go.
        parts = real.split()
        if len(parts) == 2:
            pairs.append((f"{parts[1]} {parts[0]}", " ".join(reversed(invented.split()))))
    return pairs


# Organisations named only once or twice, alongside the people above.
TAIL_ORGS = [
    ("Bochuang Guanbang", "Hexing Yuanlu"),
    ("Zhimeng Consulting", "Qingnuo Consulting"),
    ("Limei Technology", "Ruikan Technology"),
    ("Sina Weibo", "Weiyu Feed"),
    ("Bloomberg", "Marketrail"),
]


CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]+")

_SUP = re.compile(r"<sup>(.*?)</sup>", re.I)
_TAG = re.compile(r"</?[a-z][^>]*>", re.I)
_HEAD = re.compile(r"^\s*#{1,6}\s*")
# The corpus writes ordinals three ways: 13<sup>th</sup>, \(13^{th}\) and
# \(13^{\text{th}}\). The braces are required here rather than optional --
# leaving them optional let \w* swallow the "t" of "th" and produce "13h",
# which then matched no substitution and left the real edition number on the
# page in a set whose point is that nothing real is left on any page.
_TEX_SUP = re.compile(r"\\\(\s*(\d+)\s*\^\s*\{\s*(?:\\\w+\s*)?\{?\s*(\w+)\s*\}?\s*\}\s*\\\)")
# The same ordinal also occurs without the \( \) wrapper: "13^{th}Blue Lantern".
_TEX_SUP_BARE = re.compile(r"(\d+)\s*\^\s*\{\s*(?:\\\w+\s*)?\{?\s*(\w+?)\s*\}?\s*\}")


def clean_markup(text: str) -> str:
    """Strip the OCR's markup before anything else touches the text.

    Not cosmetic. The source writes ordinals as `13<sup>th</sup>`, so a
    substitution for "13th" matches nothing and the real edition number survives
    into a set whose entire point is that nothing does. The tags were also being
    drawn onto the page as literal characters, which no document has ever done.
    """
    text = _TEX_SUP.sub(r"\1\2", text)
    text = _TEX_SUP_BARE.sub(r"\1\2", text)
    text = text.replace("\\(", "").replace("\\)", "")
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    text = _SUP.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = _HEAD.sub("", text)
    return text.replace("**", "")


ALL_SUBSTITUTIONS = SUBSTITUTIONS + TAIL_ORGS + _pseudonyms()
# Longest first: a short name that is a prefix of a longer one must not be
# replaced before it ("Li Li" inside "Li Xiannian").
ALL_SUBSTITUTIONS.sort(key=lambda pair: -len(pair[0]))

# Matched without regard to case, because the source does not keep to one.
# The same organisation appears as "China Advertising Association of Commerce"
# in a heading, "CHINADAILY.COM.CN" in a masthead and "Market research and
# application" in a running head, and a case-sensitive pass replaced the first
# and left the other two. Four real names survived that way in the earlier set,
# and neither the substitution nor the audit noticed, because both were
# comparing exactly.
#
# The replacement follows the case it found: an all-capitals match gets an
# all-capitals replacement, everything else gets the name as written.
_COMPILED = [(re.compile(re.escape(old), re.I), new) for old, new in ALL_SUBSTITUTIONS]


def substitute(text: str) -> str:
    """Apply the map, then drop any Chinese that came through with it.

    The source is a bilingual filing and its Chinese halves name the same
    entities. Translating each one is not the job here, and leaving them would
    put the real organisations back into a set whose whole purpose is that they
    are absent -- so the Chinese runs are removed rather than replaced.
    """
    out = clean_markup(text)
    for pattern, new in _COMPILED:
        out = pattern.sub(lambda m, n=new: n.upper() if m.group(0).isupper() else n, out)
    out = CJK.sub(" ", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def load_font(kind: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(FONTS[kind], size)


def fit_text(draw, text: str, box_w: int, box_h: int, kind: str) -> tuple:
    """Largest size at which the wrapped text still fits the original block.

    The rectangle came from the real document, so this is what keeps the
    replica's layout honest: a passage that filled its box there fills it here.
    """
    from PIL import ImageFont  # noqa: F401

    lo, hi, best = 7, 44, None
    while lo <= hi:
        size = (lo + hi) // 2
        font = load_font(kind, size)
        avg = max(1, draw.textlength("n", font=font))
        wrapped = textwrap.wrap(text, width=max(4, int(box_w / avg)))
        line_h = size * 1.28
        if wrapped and len(wrapped) * line_h <= box_h and all(
            draw.textlength(line, font=font) <= box_w for line in wrapped
        ):
            best = (font, wrapped, line_h)
            lo = size + 1
        else:
            hi = size - 1
    if best:
        return best
    font = load_font(kind, 8)
    avg = max(1, draw.textlength("n", font=font))
    wrapped = textwrap.wrap(text, width=max(4, int(box_w / avg))) or [text[:40]]
    return font, wrapped[: max(1, int(box_h / 10))], 10


def render_page(page: dict, width: int) -> "object":
    from PIL import Image, ImageDraw

    height = round(width * 1.3029)  # the corpus renders at this ratio
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    for block in page.get("text_blocks") or []:
        bb = block.get("bbox_list") or []
        if len(bb) != 4:
            continue
        x1, y1, x2, y2 = (bb[0] / 1000 * width, bb[1] / 1000 * height,
                          bb[2] / 1000 * width, bb[3] / 1000 * height)
        bw, bh = max(4, x2 - x1), max(4, y2 - y1)
        kind = block.get("block_type")

        if kind == "image":
            # A photograph cannot be fabricated honestly, so its place on the
            # page is kept and marked as what it is.
            draw.rectangle([x1, y1, x2, y2], fill="#eef1f5", outline="#d7dde5")
            label = load_font("sans", max(9, min(16, int(bh / 6))))
            draw.text((x1 + bw / 2, y1 + bh / 2), "[ photograph ]", font=label,
                      fill="#9aa6b4", anchor="mm")
            continue

        text = substitute(block.get("text_content") or "")
        if not text:
            continue

        style = {"title": "bold", "sub_title": "bold",
                 "table_caption": "italic", "image_caption": "italic"}.get(kind, "regular")
        font, lines, line_h = fit_text(draw, text, bw, bh, style)
        centre = kind in ("title", "sub_title")
        y = y1
        for line in lines:
            x = x1 + (bw - draw.textlength(line, font=font)) / 2 if centre else x1
            draw.text((x, y), line, font=font, fill="#111820")
            y += line_h

    return img



def audit(out: Path) -> list:
    """Every original name must be gone. Loudly, because the whole value of the
    set is that nothing in it belongs to anyone."""
    text = []
    for path in (out / "OCR").rglob("page_*.json"):
        page = json.loads(path.read_text(encoding="utf-8"))
        text.append(page.get("markdown_text") or "")
        for block in page.get("text_blocks") or []:
            text.append(block.get("text_content") or "")
    # Folded, for the same reason the substitution is: an original that comes
    # back in a different case is just as much of a leak, and an audit that
    # cannot see it is worse than no audit, because it says the set is clean.
    blob = " ".join(text).lower()
    originals = [a for a, _ in ALL_SUBSTITUTIONS] + [
        "Dehuan", "Liping", "Xubin", "Xiaodong", "ZEISS", "Tiger Roar",
        "NetEase", "Baidu", "Google", "Tencent", "Sohu", "China Daily",
        "PR Newswire", "Tsinghua", "Peking Univ", "CAAC", "DMCC",
        # From the book and the paper. Fragments rather than whole names,
        # because a colophon identifies a book by its numbers as surely as by
        # its title -- an ISBN or a press e-mail domain surviving is the same
        # leak as a name surviving.
        "ISMAS", "Siluo", "Yuzhu", "Nao Bai", "Qin Chi", "Procter",
        "pup.cn", "pku.edu", "Chengfu", "Xinhua Book", "10091", "131218",
        "62752015", "62750672", "62765016", "62754962", "F.713.5",
    ]
    return sorted({o for o in originals if o.lower() in blob})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out = Path(args.out)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow is required: pip install pillow") from None

    (out / "OCR").mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(parents=True, exist_ok=True)

    total_pages = 0
    for ex in EXHIBITS:
        src_dir = SRC / ex
        pages = sorted(src_dir.glob("page_*.json"),
                       key=lambda p: int(re.search(r"(\d+)", p.name).group(1)))
        if not pages:
            raise SystemExit(f"no OCR for {ex}")

        display = f"{ex[0].upper()}-{ex[1:]}"
        ocr_dir = out / "OCR" / ex
        img_dir = out / "pages" / display
        ocr_dir.mkdir(parents=True, exist_ok=True)
        img_dir.mkdir(parents=True, exist_ok=True)

        for path in pages:
            page = json.loads(path.read_text(encoding="utf-8"))

            # Substituted OCR, same schema and same boxes, so the existing
            # bundle builder can read this set unchanged.
            for block in page.get("text_blocks") or []:
                block["text_content"] = substitute(block.get("text_content") or "")
            page["markdown_text"] = substitute(page.get("markdown_text") or "")
            page.pop("raw_output", None)
            (ocr_dir / path.name).write_text(
                json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

            img = render_page(page, PAGE_WIDTH)
            img.save(img_dir / f"{page['page_number']}.jpg", "JPEG",
                     quality=82, optimize=True)
            total_pages += 1

        print(f"  {display}: {len(pages)} pages")

    (out / "substitutions.json").write_text(
        json.dumps({
            "_comment": (
                "Every replacement applied, in order. Kept so the fabricated set "
                "can be audited against the original: anyone can check that no "
                "name, organisation, publication or figure survived."
            ),
            "source": "data/Dehuan Liu, exhibit group C (C-10 excluded: private email)",
            "replacements": [{"from": a, "to": b} for a, b in ALL_SUBSTITUTIONS],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # The whole value of this set is that nothing in it belongs to anyone, so
    # a survivor is a failure of the run, not a warning at the end of it.
    leaks = audit(out)
    if leaks:
        raise SystemExit(
            "these names from the original survived the substitution:\n  "
            + "\n  ".join(leaks))

    print(f"\n{total_pages} pages across {len(EXHIBITS)} exhibits -> {out}")
    print(f"{len(ALL_SUBSTITUTIONS)} replacements applied; the audit finds "
          f"nothing left from the original")
    return 0


if __name__ == "__main__":
    sys.exit(main())
