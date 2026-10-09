"""Draws docs/flow-light.svg and docs/flow-dark.svg (the README diagram). Run: python docs/make_flow.py docs

The numbers shown (route counts, miss rate) are typed in below; update them when the results change.
"""
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
W, H = 1000, 560
FONT = "-apple-system, 'Segoe UI', Inter, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SFMono-Regular', Consolas, monospace"

THEMES = {
    "light": dict(bg="#FAF9F7", surface="#FFFFFF", raised="#F3F1ED", border="#D9D4CC", text="#1C1A17",
                  muted="#6A645C", faint="#9C958B", accent="#0E6E66", accent_soft="#E3F1EF", on_accent="#FFFFFF",
                  danger="#A8322D", line="#8E877D"),
    "dark": dict(bg="#0D1117", surface="#161B22", raised="#1C222B", border="#30363D", text="#E6E3DE",
                 muted="#9EA7B0", faint="#6E7781", accent="#4FB3A8", accent_soft="#13302D", on_accent="#0D1117",
                 danger="#E5736B", line="#6E7781"),
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(t):
    o = []
    add = o.append

    def text(x, y, s, size=12, weight=400, fill=t["text"], anchor="start", family=FONT, ls=None):
        extra = f' letter-spacing="{ls}"' if ls else ""
        add(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>')

    def box(x, y, w, h, fill=t["surface"], stroke=t["border"], dash=None, r=8):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1"{d}/>')

    def node(x, y, w, h, tag, title, sub, fill=t["surface"], stroke=t["border"], fg=t["text"], subfg=t["muted"], dash=None):
        box(x, y, w, h, fill, stroke, dash)
        text(x + 14, y + 20, tag, 10, 600, subfg, ls="0.08em")
        text(x + 14, y + 39, title, 14, 600, fg)
        for i, line in enumerate(sub):
            text(x + 14, y + 57 + i * 15, line, 11.5, 400, subfg)

    def arrow(points, color=t["line"], dash=None, head=True):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        pts = " ".join(f"{x},{y}" for x, y in points)
        marker = ' marker-end="url(#head)"' if head else ""
        add(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.25"{d}{marker}/>')

    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
        f'aria-labelledby="t d">')
    add('<title id="t">How the harness checks an answer</title>')
    add('<desc id="d">Test cases go to the bot under test; answers pass rule checks and two AI judges; '
        'a versioned routing policy sends each answer to auto-pass, human review or auto-fail. Blind human '
        'labels measure judge agreement and backtest the router; a judge audit rewords answers to count '
        'verdict flips. Every step logs append-only files, which are loaded into BigQuery and built by dbt into '
        'a scorecard with alerts, orchestrated by Dagster.</desc>')
    add(f'<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{t["line"]}"/></marker>'
        f'<marker id="headA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{t["accent"]}"/></marker></defs>')
    add(f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>')

    # Title
    text(32, 42, "Every answer is checked three ways; a versioned policy decides who reads it", 17, 650)
    text(32, 63, "Rules catch exact facts, two judges score the rest, and the judges themselves are measured against blind human labels.",
         12, 400, t["muted"])

    # ---- Main row ------------------------------------------------------------------------------
    y, h = 104, 84
    node(32, y, 138, h, "TEST SET", "73 cases", ["Australian leaflets", "50 dev · 23 locked"])
    node(194, y, 150, h, "L0  GENERATE", "Bot answers", ["Claude Haiku 4.5", "prompt v1 vs v2"])
    node(368, y, 150, h, "L1  RULES", "Rule checks", ["promptfoo", "exact facts, e.g. 5-day rule"])
    node(542, y, 158, h, "L2  JUDGES", "Two AI judges", ["gpt-6-luna + grok", "4 metrics, scored twice"])
    # Router: the signature node
    rx, rw = 724, 112
    node(rx, y, rw, h, "L4  ROUTER", "Policy", ["routing_v2.yaml", "first rule wins"],
         fill=t["accent"], stroke=t["accent"], fg=t["on_accent"], subfg=t["on_accent"])
    mid = y + h / 2
    for x1, x2 in [(170, 194), (344, 368), (518, 542), (700, rx)]:
        arrow([(x1, mid), (x2 - 2, mid)])

    # Outcomes: three stacked boxes, centred on the main row
    ox, ow, oh, gap = 864, 112, 36, 6
    top = mid - (3 * oh + 2 * gap) / 2
    outcomes = [("auto-pass", "33 / 88 answers"), ("human review", "55 / 88 answers"), ("auto-fail", "0 / 88 answers")]
    for i, (label, n) in enumerate(outcomes):
        oy = top + i * (oh + gap)
        review = label == "human review"
        box(ox, oy, ow, oh, t["accent_soft"] if review else t["surface"], t["accent"] if review else t["border"])
        text(ox + 10, oy + 15, label, 12, 600)
        text(ox + 10, oy + 29, n, 10.5, 400, t["muted"])
        cy = oy + oh / 2
        color = t["accent"] if review else t["line"]
        add(f'<polyline points="{rx + rw},{mid} {rx + rw + 12},{mid} {rx + rw + 12},{cy} {ox - 2},{cy}" fill="none" '
            f'stroke="{color}" stroke-width="1.25" marker-end="url(#{"headA" if review else "head"})"/>')
    text(ox, top + 3 * oh + 2 * gap + 16, "incl. 10% random audit", 10.5, 400, t["muted"])

    # ---- Measuring the judges ------------------------------------------------------------------
    my = 248
    text(368, my - 10, "MEASURING THE JUDGES", 10, 600, t["faint"], ls="0.08em")
    node(368, my, 200, 76, "L3  HUMAN LABELS", "Blind hand labels", ["42 high/critical answers", "agreement: Cohen's kappa"])
    node(592, my, 196, 76, "L5  JUDGE AUDIT", "Reworded answers", ["4 rewrites per critical answer",
                                                                    "flips vs same-text noise"], dash="4 3")
    # agreement: L3 -> judges
    arrow([(556, my), (556, y + h + 2)])
    text(564, my - 14, "agreement", 10.5, 400, t["muted"])
    # audit: L5 -> judges
    arrow([(676, my), (676, y + h + 2)], dash="4 3")
    text(684, my - 14, "re-judge", 10.5, 400, t["muted"])
    # backtest: L3 -> router, routed under the audit box
    arrow([(468, my + 76), (468, my + 90), (800, my + 90), (800, y + h + 2)], color=t["accent"], dash="2 3")
    text(808, my + 4, "backtest:", 10.5, 600, t["accent"])
    text(808, my + 18, "did a labelled hard", 10.5, 400, t["accent"])
    text(808, my + 32, "fail get auto-passed?", 10.5, 400, t["accent"])

    # ---- Scorecard band ------------------------------------------------------------------------
    by = 380
    box(24, by - 26, W - 48, 160, t["raised"], t["border"], r=10)
    text(40, by - 6, "L6  SCORECARD  ·  orchestrated by Dagster: refresh_scorecard (free) · full_eval (paid, weekly schedule off by default)",
         10, 600, t["muted"], ls="0.04em")
    bh = 74
    steps = [
        (40, 184, "LOGS", "runs/*.jsonl", ["append-only, one ID per run", "A$5 cost cap per run"]),
        (248, 164, "LOAD", "BigQuery raw", ["juniper_eval_raw", "australia-southeast1"]),
        (436, 176, "DBT", "Views → scorecard", ["staging views, mart tables", "data tests every build"]),
    ]
    for sx, sw, tag, title, sub in steps:
        node(sx, by + 8, sw, bh, tag, title, sub)
    for x1, x2 in [(224, 248), (412, 436), (612, 636)]:
        arrow([(x1, by + 8 + bh / 2), (x2 - 2, by + 8 + bh / 2)])
    hx, hw = 636, 340
    box(hx, by + 8, hw, bh, t["surface"], t["accent"])
    text(hx + 14, by + 26, "HEADLINES, ALWAYS SIDE BY SIDE", 10, 600, t["accent"], ls="0.08em")
    text(hx + 14, by + 46, "Severe miss rate", 13, 600)
    text(hx + 14, by + 61, "0 of 4 hard fails missed", 11.5, 400, t["muted"])
    text(hx + 14, by + 75, "95% range 0–49%", 11.5, 400, t["muted"])
    add(f'<line x1="{hx + 182}" y1="{by + 36}" x2="{hx + 182}" y2="{by + 74}" stroke="{t["border"]}" stroke-width="1"/>')
    text(hx + 196, by + 46, "Review load", 13, 600)
    text(hx + 196, by + 61, "55 of 88 answers", 11.5, 400, t["muted"])
    text(hx + 196, by + 75, "62.5% of the dev set", 11.5, 400, t["muted"])
    text(hx, by + 102, "Alert: a hard fail auto-passed fails the build", 11, 600, t["danger"])
    text(hx, by + 117, "No single overall safety percentage, anywhere.", 11, 400, t["muted"])

    # logs come from every step
    add(f'<line x1="269" y1="{y + h}" x2="269" y2="{by - 26}" stroke="{t["line"]}" stroke-width="1" stroke-dasharray="2 3"/>')
    text(277, by - 36, "every step logs its output", 10.5, 400, t["muted"])

    add("</svg>")
    return "\n".join(o)


for name, theme in THEMES.items():
    (OUT / f"flow-{name}.svg").write_text(build(theme), encoding="utf-8")
print("written")
