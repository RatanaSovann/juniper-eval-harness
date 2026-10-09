"""Draw the two README diagrams as light and dark SVG files.

Run:  python docs/make_readme_diagrams.py
Writes docs/harness-flow-{light,dark}.svg and docs/production-fit-{light,dark}.svg
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

# fill, stroke, title, subtitle
THEMES = {
    "light": {
        "purple": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7"),
        "coral": ("#FAECE7", "#993C1D", "#712B13", "#993C1D"),
        "gray": ("#F1EFE8", "#5F5E5A", "#2C2C2A", "#5F5E5A"),
        "line": "#888780", "muted": "#5F5E5A", "dash": "#888780",
    },
    "dark": {
        "purple": ("#3C3489", "#AFA9EC", "#EEEDFE", "#CECBF6"),
        "coral": ("#712B13", "#F0997B", "#FAECE7", "#F5C4B3"),
        "gray": ("#444441", "#B4B2A9", "#F1EFE8", "#D3D1C7"),
        "line": "#B4B2A9", "muted": "#B4B2A9", "dash": "#B4B2A9",
    },
}


class Svg:
    def __init__(self, w, h, title, desc, t):
        self.t, self.parts = t, []
        self.head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" font-family="{FONT}"><title>{title}</title><desc>{desc}</desc>'
            f'<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
            f'orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="{t["line"]}" '
            f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>'
        )

    def box(self, x, y, w, h, ramp, title, sub):
        f, s, tc, sc = self.t[ramp]
        cx = x + w / 2
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{f}" stroke="{s}" stroke-width="0.75"/>'
            f'<text x="{cx}" y="{y + h / 2 - 4}" text-anchor="middle" font-size="14" font-weight="600" fill="{tc}">{title}</text>'
            f'<text x="{cx}" y="{y + h / 2 + 14}" text-anchor="middle" font-size="12" fill="{sc}">{sub}</text>'
        )

    def diamond(self, cx, cy, hw, hh, label):
        f, s, tc, _ = self.t["gray"]
        pts = f"{cx - hw},{cy} {cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh}"
        self.parts.append(
            f'<polygon points="{pts}" fill="{f}" stroke="{s}" stroke-width="0.75"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="12" fill="{tc}">{label}</text>'
        )

    def arrow(self, d):
        self.parts.append(f'<path d="{d}" fill="none" stroke="{self.t["line"]}" stroke-width="1.5" marker-end="url(#a)"/>')

    def dashed(self, d):
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{self.t["dash"]}" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#a)"/>'
        )

    def frame(self, x, y, w, h, label):
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="none" stroke="{self.t["line"]}" '
            f'stroke-width="0.75" stroke-dasharray="4 4"/>'
            f'<text x="{x + 12}" y="{y + 18}" font-size="12" fill="{self.t["muted"]}">{label}</text>'
        )

    def text(self, x, y, s, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="12" fill="{self.t["muted"]}">{s}</text>')

    def legend(self, y, items):
        x = items[0][0]
        for x, kind, label in items:
            if kind == "dash":
                self.parts.append(f'<line x1="{x}" y1="{y - 5}" x2="{x + 32}" y2="{y - 5}" stroke="{self.t["dash"]}" stroke-width="1.5" stroke-dasharray="5 4"/>')
                self.text(x + 42, y, label)
            else:
                f, s, _, _ = self.t[kind]
                self.parts.append(f'<rect x="{x}" y="{y - 12}" width="14" height="14" rx="3" fill="{f}" stroke="{s}" stroke-width="0.75"/>')
                self.text(x + 22, y, label)

    def save(self, path):
        path.write_text(self.head + "".join(self.parts) + "</svg>\n", encoding="utf-8")


def harness_flow(t):
    s = Svg(680, 820, "How the harness works",
            "73 test cases go to the bot, then rule checks and two AI judges. Blind labels and a judge audit "
            "measure the judges and backtest the router. The router sends each answer to auto-pass, human review "
            "or auto-fail. The scorecard shows the severe miss rate beside review load; an alert fails the build "
            "if a hard fail is auto-passed.", t)
    s.box(150, 40, 260, 56, "gray", "Test set", "73 cases: 50 dev, 23 locked")
    s.arrow("M280 96 V118")
    s.box(150, 120, 260, 56, "purple", "L0 Bot answers", "Claude Haiku 4.5, v1 vs v2")
    s.arrow("M280 176 V198")
    s.box(150, 200, 260, 56, "purple", "L1 Rule checks", "promptfoo, exact facts")
    s.arrow("M280 256 V278")
    s.box(150, 280, 260, 56, "purple", "L2 Two judges", "gpt-6-luna + Grok, twice")
    s.arrow("M280 336 V358")
    s.box(150, 360, 260, 56, "purple", "L4 Router", "routing_v2.yaml")
    s.frame(440, 200, 200, 146, "Measuring the judges")
    s.box(452, 228, 176, 50, "coral", "L3 Blind labels", "Blind, kappa")
    s.box(452, 286, 176, 50, "purple", "L5 Judge audit", "4 rewrites per answer")
    s.arrow("M440 308 H412")
    s.dashed("M540 346 V388 H412")
    s.text(548, 372, "backtest")
    s.arrow("M180 416 V432 H115 V446")
    s.arrow("M285 416 V446")
    s.arrow("M380 416 V432 H455 V446")
    s.box(40, 448, 150, 56, "gray", "Auto-pass", "Both judges clean")
    s.box(210, 448, 150, 56, "coral", "Human review", "Flagged + 10% audit")
    s.box(380, 448, 150, 56, "gray", "Auto-fail", "Not used yet")
    for x in (115, 285, 455):
        s.arrow(f"M{x} 504 V526")
    s.box(40, 528, 490, 56, "purple", "L6 Scorecard, BigQuery + dbt", "Severe miss rate beside review load")
    s.arrow("M285 584 V606")
    s.diamond(285, 648, 90, 40, "Hard fail auto-passed?")
    s.arrow("M375 648 H418")
    s.text(382, 640, "yes")
    s.box(420, 620, 200, 56, "coral", "dbt build fails", "Alert, nothing ships")
    s.arrow("M285 688 V710")
    s.text(293, 704, "no")
    s.box(135, 712, 300, 56, "gray", "Scorecard published", "Dagster runs the pipeline")
    s.legend(802, [(40, "purple", "Automated"), (160, "coral", "Human or alert"), (300, "gray", "Data or outcome")])
    return s


def production_fit(t):
    s = Svg(680, 700, "Where the harness fits in production",
            "Patients chat with an AI assistant and chats are logged to a data warehouse. The harness takes a "
            "daily sample, runs rules and two judges, and a router sends cases to a scorecard with alerts and to "
            "clinician review. Labelled cases feed a kappa check back to the judges, and a regression set that "
            "gates model updates before they reach patients.", t)
    s.frame(60, 30, 590, 170, "A typical live clinic setup")
    s.box(100, 60, 300, 52, "gray", "Patients chat with an AI assistant", "Any vendor's bot")
    s.arrow("M250 112 V134")
    s.box(100, 136, 300, 52, "gray", "Chat logs", "Data warehouse, e.g. BigQuery")
    s.arrow("M250 188 V240")
    s.frame(60, 212, 590, 246, "The harness plugs in here")
    s.box(100, 242, 300, 52, "purple", "Daily sample", "Risky, unsure, plus random")
    s.arrow("M250 294 V316")
    s.box(100, 318, 300, 52, "purple", "Rules + two judges", "L1 and L2")
    s.arrow("M250 370 V392")
    s.box(100, 394, 300, 52, "purple", "Router", "Versioned routing policy")
    s.arrow("M400 420 H448")
    s.box(450, 394, 180, 52, "purple", "Scorecard + alerts", "dbt, Dagster")
    s.arrow("M250 446 V498")
    s.frame(60, 470, 590, 170, "People and feedback")
    s.box(100, 500, 300, 52, "coral", "Clinician review", "Ranked by severity")
    s.arrow("M250 552 V574")
    s.box(100, 576, 300, 52, "coral", "Labelled cases", "Verdict plus reason")
    s.arrow("M400 602 H448")
    s.box(450, 576, 180, 52, "gray", "Regression set", "Failures become tests")
    s.arrow("M540 576 V554")
    s.box(450, 500, 180, 52, "purple", "Release gate", "Before model updates")
    s.dashed("M630 526 H662 V86 H402")
    s.dashed("M100 602 H80 V344 H98")
    s.legend(676, [(60, "purple", "The harness"), (180, "coral", "People"), (270, "gray", "Live systems / data"), (440, "dash", "Feedback loop")])
    return s


if __name__ == "__main__":
    for name, t in THEMES.items():
        harness_flow(t).save(OUT / f"harness-flow-{name}.svg")
        production_fit(t).save(OUT / f"production-fit-{name}.svg")
    print("Wrote 4 SVGs to", OUT)
