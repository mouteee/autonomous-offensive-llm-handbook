#!/usr/bin/env python3
"""Generate the course chapter figures from the committed course artifacts.

Every figure is derived from a named JSON under data/course/ and nothing else,
so a plot is exactly as reproducible as its data: regenerate the artifacts with
the lesson commands, run this script, and the bytes match the committed SVGs.
A sync test in tests/test_course_artifacts.py re-derives all three.

The visual parameters follow the repository's dark diagram style with a
validated categorical palette: series colors are assigned to controllers in a
fixed order and reused identically across figures, identity is carried by a
legend plus direct labels rather than color alone, and all text wears ink
colors, never a series color. Stdlib only.
"""

import json
import pathlib
from xml.sax.saxutils import escape


ROOT = pathlib.Path(__file__).resolve().parents[1]
COURSE = ROOT / "data" / "course"
OUT = ROOT / "docs" / "assets" / "course"

SURFACE = "#1a1a19"
INK = "#ffffff"
INK_SOFT = "#c3c2b7"
INK_MUTED = "#898781"
GRID = "#2c2c2a"
BASELINE = "#383835"

# Categorical slots (dark-surface steps), assigned by entity and never cycled:
# the same controller wears the same hue in every figure of the course.
SERIES = {
    "priority": "#3987e5",
    "legacy": "#d95926",
    "linucb": "#199e70",
    # The scripted-lesson families reuse the first two slots in their own
    # figures; controllers and families never appear in the same chart, and
    # each figure's pair keeps its own fixed assignment.
    "fam-a": "#3987e5",
    "fam-b": "#d95926",
    "fam-inject": "#3987e5",
    "fam-recon": "#d95926",
    # The mushroom-body pair takes the fourth slot; the frozen/plastic twins
    # share their base controller's hue, and identity is always the label.
    "mb": "#c98500",
    "mb-plastic": "#c98500",
}


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


class Svg:
    def __init__(self, width, height, title, desc):
        self.width, self.height = width, height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-labelledby="t d">',
            f"<title id=\"t\">{escape(title)}</title>"
            f"<desc id=\"d\">{escape(desc)}</desc>",
            f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{SURFACE}"/>',
        ]

    def line(self, x1, y1, x2, y2, stroke, width=1, dash=None, cap="butt"):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" '
            f'stroke="{stroke}" stroke-width="{width}" stroke-linecap="{cap}"{d}/>')

    def polyline(self, points, stroke, width=2, dash=None):
        text = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in points)
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<polyline points="{text}" fill="none" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"{d}/>')

    def circle(self, x, y, r, fill, stroke=None, stroke_width=2):
        ring = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
        self.parts.append(
            f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{r}" fill="{fill}"{ring}/>')

    def text(self, x, y, content, *, size=12, fill=INK_SOFT, anchor="start",
             weight="normal", family="system-ui, -apple-system, 'Segoe UI', sans-serif"):
        self.parts.append(
            f'<text x="{fmt(x)}" y="{fmt(y)}" font-family="{family}" '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{escape(str(content))}</text>')

    def render(self):
        return "\n".join(self.parts + ["</svg>"]) + "\n"


def nice_ticks(top, count=4):
    import math
    raw = top / count
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 2.5, 5, 10):
        if raw <= step * magnitude:
            unit = step * magnitude
            break
    ticks = []
    value = 0.0
    while value <= top + 1e-9:
        ticks.append(round(value, 6))
        value += unit
    return ticks


def comparison_figure(data):
    world = data["world"]
    steps = data["steps"]
    series_names = sorted(data["controllers"])  # fixed alphabetical: legacy, linucb, priority
    order = [n for n in ("priority", "legacy", "linucb") if n in series_names]
    top = max(data["best_fixed_family_reward"],
              *(data["controllers"][n]["total_reward"] for n in order))

    width, height = 900, 540
    left, right, head, foot = 64, 210, 116, 56
    plot_w, plot_h = width - left - right, height - head - foot

    def sx(step):
        return left + plot_w * step / max(steps - 1, 1)

    def sy(value):
        return head + plot_h * (1 - value / top)

    svg = Svg(width, height,
              f"Cumulative reward on the {world} world",
              "Line chart of cumulative reward per step for the priority, "
              "legacy and linucb controllers, with the best fixed family in "
              "hindsight as a dashed reference line. The exact values are in "
              f"data/course/compare-{world}.json.")
    svg.text(left, 40, f"Cumulative reward: {world}", size=20, fill=INK, weight="650")
    svg.text(left, 64, "same candidates, same feedback, one seed",
             size=13, fill=INK_SOFT)

    for tick in nice_ticks(top):
        y = sy(tick)
        svg.line(left, y, left + plot_w, y, GRID)
        svg.text(left - 10, y + 4, fmt(tick), size=11, fill=INK_MUTED, anchor="end")
    svg.line(left, head + plot_h, left + plot_w, head + plot_h, BASELINE, 1.5)
    for tick in range(0, steps + 1, 30):
        svg.text(sx(min(tick, steps - 1)), head + plot_h + 22, str(tick),
                 size=11, fill=INK_MUTED, anchor="middle")
    svg.text(left + plot_w / 2, height - 16, "step", size=12,
             fill=INK_MUTED, anchor="middle")

    if data.get("drift_at") is not None:
        x = sx(data["drift_at"])
        svg.line(x, head, x, head + plot_h, INK_MUTED, 1, dash="4 4")
        svg.text(x + 6, head + 14, "reward means change", size=11, fill=INK_MUTED)

    labels = []
    for name in order:
        trace = data["controllers"][name]["trace"]
        points = [(sx(row["step"]), sy(row["cumulative_reward"])) for row in trace]
        svg.polyline(points, SERIES[name], width=2)
        total = data["controllers"][name]["total_reward"]
        labels.append([f"{name} {fmt(total)}", points[-1][1], SERIES[name], False])

    # The hindsight reference is drawn after the series so its dashes stay
    # visible where a controller's line coincides with it exactly.
    best = [(sx(i), sy(v)) for i, v in enumerate(data["best_fixed_cumulative"])]
    svg.polyline(best, INK_MUTED, width=2, dash="6 5")
    labels.append([f"best fixed ({data['best_fixed_family']}) "
                   f"{fmt(data['best_fixed_family_reward'])}",
                   best[-1][1], INK_MUTED, True])

    # Direct labels at the line ends, nudged apart when totals nearly tie.
    labels.sort(key=lambda item: item[1])
    for i, (text, y, color, dashed) in enumerate(labels):
        for _, prev_y, _, _ in labels[:i]:
            if abs(prev_y - y) < 17:
                y = prev_y + 17
        labels[i][1] = y
        if dashed:
            svg.line(left + plot_w + 4, y, left + plot_w + 16, y, color, 2, dash="4 3")
        else:
            svg.circle(left + plot_w + 10, y, 4, color)
        svg.text(left + plot_w + 22, y + 4, text, size=12,
                 fill=INK_MUTED if dashed else INK_SOFT)

    # Legend row under the subtitle: identity is legend plus direct label,
    # never color alone.
    lx = left
    for name in order:
        svg.line(lx, 84, lx + 18, 84, SERIES[name], 3, cap="round")
        svg.text(lx + 24, 88, name, size=12, fill=INK_SOFT)
        lx += 24 + 8 * len(name) + 28
    svg.line(lx, 84, lx + 18, 84, INK_MUTED, 2, dash="4 3")
    svg.text(lx + 24, 88, "best fixed family in hindsight", size=12, fill=INK_SOFT)
    return svg.render()


def linucb_scores_figure(data):
    rows = data["steps"]
    families = ("fam-a", "fam-b")
    top = max(cell["score"] for row in rows for cell in row["by_family"].values())
    top = max(top, 1.0) * 1.15

    width, height = 900, 480
    left, right, head, foot = 64, 190, 96, 96
    plot_w, plot_h = width - left - right, height - head - foot

    def sx(step):
        return left + plot_w * step / (len(rows) - 1)

    def sy(value):
        return head + plot_h * (1 - value / top)

    svg = Svg(width, height,
              "LinUCB family scores over the scripted lesson",
              "Line chart of the linucb score for two families across eight "
              "scripted steps; the signal feature flips mid-run and the chosen "
              "family per step is marked under the axis. Exact numbers are in "
              "data/course/linucb-trace.json.")
    svg.text(left, 40, "Why a family wins: score = predicted + bonus",
             size=20, fill=INK, weight="650")
    svg.text(left, 64, f"scripted trace, alpha {fmt(data['alpha'])}, zero noise; "
                       "filled dot = that step paid reward 1, open dot = 0",
             size=13, fill=INK_SOFT)

    for tick in (0.0, 0.5, 1.0, 1.5):
        if tick > top:
            continue
        y = sy(tick)
        svg.line(left, y, left + plot_w, y, GRID)
        svg.text(left - 10, y + 4, fmt(tick), size=11, fill=INK_MUTED, anchor="end")
    svg.line(left, head + plot_h, left + plot_w, head + plot_h, BASELINE, 1.5)

    flip = next(i for i, row in enumerate(rows) if row["x"][1] == 1.0)
    x = (sx(flip - 1) + sx(flip)) / 2
    svg.line(x, head, x, head + plot_h + 40, INK_MUTED, 1, dash="4 4")
    svg.text(x + 6, head + 14, "signal flips to 1", size=11, fill=INK_MUTED)

    for family in families:
        points = [(sx(i), sy(row["by_family"][family]["score"]))
                  for i, row in enumerate(rows)]
        svg.polyline(points, SERIES[family], width=2)
        end_y = points[-1][1]
        svg.circle(left + plot_w + 8, end_y, 4, SERIES[family])
        svg.text(left + plot_w + 18, end_y + 4, family, size=12, fill=INK_SOFT)

    for i, row in enumerate(rows):
        svg.text(sx(i), head + plot_h + 22, str(row["step"]), size=11,
                 fill=INK_MUTED, anchor="middle")
        chosen = row["chosen_family"]
        y = head + plot_h + 40
        if row["reward"] == 1.0:
            svg.circle(sx(i), y, 5, SERIES[chosen], stroke=SURFACE)
        else:
            svg.circle(sx(i), y, 5, SURFACE, stroke=SERIES[chosen])
    svg.text(left - 10, head + plot_h + 44, "chosen", size=11,
             fill=INK_MUTED, anchor="end")
    svg.text(left + plot_w / 2, height - 20, "step", size=12,
             fill=INK_MUTED, anchor="middle")

    lx = width - right + 4
    svg.text(lx, 40, "families", size=11, fill=INK_MUTED)
    for i, family in enumerate(families):
        y = 58 + i * 18
        svg.line(lx, y - 4, lx + 18, y - 4, SERIES[family], 3, cap="round")
        svg.text(lx + 26, y, family, size=12, fill=INK_SOFT)
    return svg.render()


def linucb_decomposition_figure(data):
    """The lesson 11 score taken apart: per step and family, a stacked bar of
    the learned prediction (solid) under the uncertainty bonus (pale), so the
    takeover reads as what it is -- a family winning on standing uncertainty
    while its prediction is still zero."""
    rows = data["steps"]
    families = ("fam-a", "fam-b")
    for row in rows:
        for cell in row["by_family"].values():
            if abs(cell["predicted"] + cell["bonus"] - cell["score"]) > 1e-6:
                raise ValueError("trace score is not predicted + bonus")
            if cell["predicted"] < 0:
                raise ValueError("negative prediction; this stacking assumes "
                                 "non-negative predicted values")
    top = max(cell["score"] for row in rows
              for cell in row["by_family"].values()) * 1.15

    width, height = 900, 500
    left, right, head, foot = 64, 190, 96, 110
    plot_w, plot_h = width - left - right, height - head - foot
    bar_w, pair_gap = 22, 8
    group_w = plot_w / len(rows)

    def gx(step):
        return left + group_w * (step + 0.5)

    def sy(value):
        return head + plot_h * (1 - value / top)

    svg = Svg(width, height,
              "LinUCB scores decomposed into prediction and bonus",
              "Stacked bar chart over the same eight scripted steps as the "
              "score line chart: for each step and family, the solid base is "
              "the learned prediction and the pale cap is the uncertainty "
              "bonus; their sum is the score. Exact numbers are in "
              "data/course/linucb-trace.json.")
    svg.text(left, 40, "The same trace taken apart: solid = predicted, "
                       "pale = bonus", size=20, fill=INK, weight="650")
    svg.text(left, 64, "reward grows the solid part and shrinks the pale cap; "
                       "a context flip refills the caps", size=13,
             fill=INK_SOFT)

    for tick in (0.0, 0.5, 1.0, 1.5):
        if tick > top:
            continue
        y = sy(tick)
        svg.line(left, y, left + plot_w, y, GRID)
        svg.text(left - 10, y + 4, fmt(tick), size=11, fill=INK_MUTED,
                 anchor="end")
    svg.line(left, sy(0), left + plot_w, sy(0), BASELINE, 1.5)

    flip = next(i for i, row in enumerate(rows) if row["x"][1] == 1.0)
    fx = left + group_w * flip
    svg.line(fx, head, fx, head + plot_h + 40, INK_MUTED, 1, dash="4 4")
    svg.text(fx + 6, head + 14, "signal flips to 1", size=11, fill=INK_MUTED)

    for i, row in enumerate(rows):
        for j, family in enumerate(families):
            cell = row["by_family"][family]
            x = gx(i) + (j - 1) * bar_w + (j - 0.5) * pair_gap
            hue = SERIES[family]
            base_h = sy(0) - sy(cell["predicted"])
            if base_h > 0.2:
                svg.parts.append(
                    f'<rect x="{fmt(x)}" y="{fmt(sy(cell["predicted"]))}" '
                    f'width="{bar_w}" height="{fmt(base_h)}" fill="{hue}"/>')
            cap_h = sy(cell["predicted"]) - sy(cell["score"])
            if cap_h > 0.2:
                svg.parts.append(
                    f'<rect x="{fmt(x)}" y="{fmt(sy(cell["score"]))}" '
                    f'width="{bar_w}" height="{fmt(cap_h)}" fill="{hue}" '
                    f'fill-opacity="0.3" stroke="{hue}" stroke-width="1"/>')

    all_bonus = rows[0]["by_family"][families[0]]
    svg.text(gx(0), sy(all_bonus["score"]) - 10, "all bonus", size=11,
             fill=INK_SOFT, anchor="middle")
    takeover = next(i for i, row in enumerate(rows)
                    if row["chosen_family"] == "fam-b")
    tk = rows[takeover]["by_family"]["fam-b"]
    svg.text(gx(takeover), sy(tk["score"]) - 24, "wins on bonus", size=11,
             fill=INK_SOFT, anchor="middle")
    svg.text(gx(takeover), sy(tk["score"]) - 10,
             f"alone (predicted {fmt(tk['predicted'])})", size=11,
             fill=INK_SOFT, anchor="middle")

    marker_y = head + plot_h + 40
    for i, row in enumerate(rows):
        svg.text(gx(i), head + plot_h + 22, str(row["step"]), size=11,
                 fill=INK_MUTED, anchor="middle")
        chosen = row["chosen_family"]
        if row["reward"] == 1.0:
            svg.circle(gx(i), marker_y, 5, SERIES[chosen], stroke=SURFACE)
        else:
            svg.circle(gx(i), marker_y, 5, SURFACE, stroke=SERIES[chosen])
    svg.text(left - 10, marker_y + 4, "chosen", size=11, fill=INK_MUTED,
             anchor="end")
    svg.text(left + plot_w / 2, height - 20, "step", size=12,
             fill=INK_MUTED, anchor="middle")

    lx = width - right + 4
    svg.text(lx, 40, "families", size=11, fill=INK_MUTED)
    for i, family in enumerate(families):
        y = 58 + i * 18
        svg.line(lx, y - 4, lx + 18, y - 4, SERIES[family], 3, cap="round")
        svg.text(lx + 26, y, family, size=12, fill=INK_SOFT)
    ky = 58 + len(families) * 18 + 14
    svg.text(lx, ky, "per bar", size=11, fill=INK_MUTED)
    svg.parts.append(
        f'<rect x="{lx}" y="{ky + 8}" width="14" height="12" '
        f'fill="{INK_MUTED}"/>')
    svg.text(lx + 22, ky + 18, "predicted", size=12, fill=INK_SOFT)
    svg.parts.append(
        f'<rect x="{lx}" y="{ky + 28}" width="14" height="12" '
        f'fill="{INK_MUTED}" fill-opacity="0.3" stroke="{INK_MUTED}" '
        f'stroke-width="1"/>')
    svg.text(lx + 22, ky + 38, "bonus", size=12, fill=INK_SOFT)
    svg.text(lx, ky + 60, "score = sum", size=12, fill=INK_SOFT)
    return svg.render()


def run_sequence_figure(_data=None):
    """The lesson 1 run-sequence diagram, generated from the harness's own
    stage list so the picture cannot drift from the code."""
    import sys
    sys.path.insert(0, str(ROOT))
    from harness.runtime import STAGES

    owners = {
        "observe": ("strict_gate", "gate record with its inputs"),
        "plan": ("plan", "frozen ranked plan, with reasons"),
        "execute": ("execute / skip", "evidence records and outcomes"),
        "review": ("propose_finding, verify_raise", "governed findings"),
        "report": ("finish / abort", "terminal report, human review required"),
    }
    accent = "#52c78d"
    box_w, box_h, gap = 148, 64, 22
    width = 64 * 2 + box_w * len(STAGES) + gap * (len(STAGES) - 1)
    height = 300
    svg = Svg(width, height,
              "The run sequence and who owns each decision",
              "Five stages in order: observe, plan, execute, review, report. "
              "Each stage names the host function that owns its decision and "
              "the artifact it leaves behind. Model proposals enter only at "
              "the execute stage, through validation.")
    svg.text(64, 44, "One run, five stages, one owner per decision",
             size=20, fill=INK, weight="650")
    svg.text(64, 68, "every stage is host code; a model may propose, and only "
                     "the execute stage's checks admit", size=13, fill=INK_SOFT)
    top = 100
    for i, stage in enumerate(STAGES):
        x = 64 + i * (box_w + gap)
        svg.parts.append(
            f'<rect x="{x}" y="{top}" width="{box_w}" height="{box_h}" rx="8" '
            f'fill="none" stroke="{accent}" stroke-width="1.5"/>')
        svg.text(x + box_w / 2, top + 27, stage, size=15, fill=INK,
                 anchor="middle", weight="650")
        owner, artifact = owners[stage]
        svg.text(x + box_w / 2, top + 47, owner, size=11, fill=INK_SOFT,
                 anchor="middle")
        if i:
            svg.line(x - gap + 2, top + box_h / 2, x - 2, top + box_h / 2,
                     accent, 1.5)
            svg.parts.append(
                f'<path d="M {fmt(x - 7)} {fmt(top + box_h / 2 - 4)} '
                f'L {fmt(x - 2)} {fmt(top + box_h / 2)} '
                f'L {fmt(x - 7)} {fmt(top + box_h / 2 + 4)}" '
                f'fill="none" stroke="{accent}" stroke-width="1.5"/>')
        svg.line(x + box_w / 2, top + box_h, x + box_w / 2, top + box_h + 18,
                 BASELINE, 1)
        svg.text(x + box_w / 2, top + box_h + 34, "leaves behind:", size=10,
                 fill=INK_MUTED, anchor="middle")
        words = artifact.split()
        lines = [" ".join(words[:3]), " ".join(words[3:])]
        for j, line in enumerate(l for l in lines if l):
            svg.text(x + box_w / 2, top + box_h + 50 + j * 14, line, size=11,
                     fill=INK_SOFT, anchor="middle")
    svg.text(64, height - 24, "advancement is positional: a stage opens only "
             "when the previous one is complete, and prompt text cannot move it",
             size=12, fill=INK_MUTED)
    return svg.render()


def stage_mapping_figure(_data=None):
    """The lesson 3 mapping diagram, generated from the stage module's own
    tables so the picture cannot drift from the code."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.run.stages import HARNESS_MAPPING, OPERATIONAL_STAGES
    from harness.runtime import STAGES

    accent = "#52c78d"
    width, height = 960, 330
    top_y, bottom_y, box_h = 96, 226, 46
    op_w, op_gap = 118, 10
    op_left = (width - (op_w * len(OPERATIONAL_STAGES)
                        + op_gap * (len(OPERATIONAL_STAGES) - 1))) / 2
    h_w, h_gap = 150, 22
    h_left = (width - (h_w * len(STAGES) + h_gap * (len(STAGES) - 1))) / 2

    svg = Svg(width, height,
              "Operational stages mapped onto the teaching harness stages",
              "Seven operational stages on top -- discovery, detection, "
              "crawling, mining, scanning, active testing, reporting -- each "
              "connected to the teaching harness stage or stages it "
              "corresponds to: observe, plan, execute, review, report.")
    svg.text(64, 40, "Two resolutions of the same run", size=20, fill=INK,
             weight="650")
    svg.text(64, 64, "the operational vocabulary above, the teaching harness "
                     "below; every arrow is a row of the mapping table in "
                     "core/run/stages.py", size=13, fill=INK_SOFT)

    op_centers = {}
    for i, stage in enumerate(OPERATIONAL_STAGES):
        x = op_left + i * (op_w + op_gap)
        op_centers[stage] = x + op_w / 2
        svg.parts.append(
            f'<rect x="{fmt(x)}" y="{top_y}" width="{op_w}" height="{box_h}" '
            f'rx="8" fill="none" stroke="{accent}" stroke-width="1.5"/>')
        svg.text(x + op_w / 2, top_y + 28, stage.replace("_", " "), size=12,
                 fill=INK, anchor="middle", weight="650")
    h_centers = {}
    for i, stage in enumerate(STAGES):
        x = h_left + i * (h_w + h_gap)
        h_centers[stage] = x + h_w / 2
        svg.parts.append(
            f'<rect x="{fmt(x)}" y="{bottom_y}" width="{h_w}" height="{box_h}" '
            f'rx="8" fill="none" stroke="{INK_MUTED}" stroke-width="1.5"/>')
        svg.text(x + h_w / 2, bottom_y + 28, stage, size=13, fill=INK,
                 anchor="middle", weight="650")
    for op, targets in HARNESS_MAPPING.items():
        for target in targets:
            svg.line(op_centers[op], top_y + box_h,
                     h_centers[target], bottom_y, BASELINE, 1.2)
    svg.text(64, height - 24, "advancement is positional in both vocabularies; "
             "the mapping is data the tests hold, not prose", size=12,
             fill=INK_MUTED)
    return svg.render()


def write_boundary_figure(_data=None):
    """The lesson 2 one-door diagram, generated from the recorder's own
    handler methods so the admitted-kind list cannot drift from the code."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.run.recorder import Recorder

    kinds = sorted(name[len("_record_"):] for name in dir(Recorder)
                   if name.startswith("_record_"))
    accent = "#52c78d"
    width, height = 900, 150 + 34 * len(kinds)
    svg = Svg(width, height,
              "One write boundary: every state change through one door",
              "Each record kind the recorder admits -- " + ", ".join(kinds) +
              " -- enters through the single record call, where validation "
              "either appends the record or appends a refusal with its "
              "reason. Both land in the same ordered ledger.")
    svg.text(64, 40, "One door, one ledger", size=20, fill=INK, weight="650")
    svg.text(64, 64, "admitted records and refusals are rows in the same "
                     "ordered event ledger; a refusal is evidence, not an "
                     "exception", size=13, fill=INK_SOFT)
    door_x, door_w = 380, 190
    ledger_x, ledger_w = 660, 176
    top = 100
    door_y = top + (34 * len(kinds)) / 2 - 30
    for i, kind in enumerate(kinds):
        y = top + i * 34
        svg.parts.append(
            f'<rect x="64" y="{fmt(y)}" width="200" height="26" rx="6" '
            f'fill="none" stroke="{INK_MUTED}" stroke-width="1.2"/>')
        svg.text(164, y + 17, kind, size=12, fill=INK, anchor="middle")
        svg.line(264, y + 13, door_x - 6, door_y + 30, BASELINE, 1)
    svg.parts.append(
        f'<rect x="{door_x}" y="{fmt(door_y)}" width="{door_w}" height="60" '
        f'rx="8" fill="none" stroke="{accent}" stroke-width="1.8"/>')
    svg.text(door_x + door_w / 2, door_y + 26, "record(kind, payload)",
             size=13, fill=INK, anchor="middle", weight="650")
    svg.text(door_x + door_w / 2, door_y + 45, "run binding, policy, shape",
             size=11, fill=INK_SOFT, anchor="middle")
    svg.parts.append(
        f'<rect x="{ledger_x}" y="{fmt(door_y - 24)}" width="{ledger_w}" '
        f'height="108" rx="8" fill="none" stroke="{accent}" stroke-width="1.5"/>')
    svg.text(ledger_x + ledger_w / 2, door_y + 4, "ordered event ledger",
             size=13, fill=INK, anchor="middle", weight="650")
    svg.text(ledger_x + ledger_w / 2, door_y + 26, "admitted rows", size=11,
             fill=INK_SOFT, anchor="middle")
    svg.text(ledger_x + ledger_w / 2, door_y + 44, "refusal rows, with reasons",
             size=11, fill=INK_SOFT, anchor="middle")
    svg.line(door_x + door_w, door_y + 18, ledger_x - 6, door_y + 6, accent, 1.5)
    svg.line(door_x + door_w, door_y + 42, ledger_x - 6, door_y + 54, accent, 1.5)
    svg.text((door_x + door_w + ledger_x) / 2, door_y + 2, "admit", size=10,
             fill=INK_MUTED, anchor="middle")
    svg.text((door_x + door_w + ledger_x) / 2, door_y + 66, "refuse + reason",
             size=10, fill=INK_MUTED, anchor="middle")
    return svg.render()


def mb_activation_figure(data):
    """The lesson 12 activation trace: two families' post-inhibition activation
    per step, exploration steps marked, the winner and its outcome underneath."""
    rows = data["steps"]
    families = ("fam-inject", "fam-recon")
    values = [row["by_family"][f]["activation"] for row in rows for f in families]
    top, bottom = max(values) * 1.15, min(min(values) * 1.15, -0.05)

    width, height = 940, 500
    left, right, head, foot = 64, 170, 96, 110
    plot_w, plot_h = width - left - right, height - head - foot

    def sx(step):
        return left + plot_w * step / (len(rows) - 1)

    def sy(value):
        return head + plot_h * (top - value) / (top - bottom)

    svg = Svg(width, height,
              "Mushroom-body activation per family over the scripted episode",
              "Line chart of post-inhibition activation for two families "
              "across the scripted steps; exploration steps are marked, and "
              "the winner row underneath shows which family was chosen and "
              "whether its outcome paid. Exact values are in "
              "data/course/mb-trace.json.")
    svg.text(left, 40, "Why a family loses attention", size=20, fill=INK,
             weight="650")
    svg.text(left, 64, "post-inhibition activation; filled dot = the chosen "
                       "step paid", size=13, fill=INK_SOFT)

    for tick in (-0.5, 0.0, 0.5, 1.0):
        if tick > top or tick < bottom:
            continue
        y = sy(tick)
        svg.line(left, y, left + plot_w, y,
                 BASELINE if tick == 0.0 else GRID, 1.2 if tick == 0.0 else 1)
        svg.text(left - 10, y + 4, fmt(tick), size=11, fill=INK_MUTED, anchor="end")

    ends = []
    for family in families:
        points = [(sx(i), sy(row["by_family"][family]["activation"]))
                  for i, row in enumerate(rows)]
        svg.polyline(points, SERIES[family], width=2)
        ends.append([family, points[-1][1]])
    ends.sort(key=lambda e: e[1])
    for i, (family, y) in enumerate(ends):
        for _, prev in ends[:i]:
            if abs(prev - y) < 16:
                y = prev + 16
        ends[i][1] = y
        svg.circle(left + plot_w + 8, y, 4, SERIES[family])
        svg.text(left + plot_w + 18, y + 4, family, size=12, fill=INK_SOFT)

    marker_y = head + plot_h + 46
    for i, row in enumerate(rows):
        if i % 2 == 0:
            svg.text(sx(i), head + plot_h + 24, str(row["step"]), size=11,
                     fill=INK_MUTED, anchor="middle")
        if row["exploration"]:
            svg.line(sx(i), head, sx(i), head + plot_h, INK_MUTED, 1, dash="3 4")
        paid = row["outcome_status"] == "verified_evidence"
        color = SERIES[row["winner"]]
        if paid:
            svg.circle(sx(i), marker_y, 5, color, stroke=SURFACE)
        else:
            svg.circle(sx(i), marker_y, 5, SURFACE, stroke=color)
    svg.text(left - 10, marker_y + 4, "chosen", size=11, fill=INK_MUTED,
             anchor="end")
    svg.text(left + plot_w / 2, height - 20,
             "step (dashed verticals are exploration draws)", size=12,
             fill=INK_MUTED, anchor="middle")

    lx = width - right + 4
    svg.text(lx, 40, "families", size=11, fill=INK_MUTED)
    for i, family in enumerate(families):
        y = 58 + i * 18
        svg.line(lx, y - 4, lx + 18, y - 4, SERIES[family], 3, cap="round")
        svg.text(lx + 26, y, family, size=12, fill=INK_SOFT)
    return svg.render()


def mb_signal_breakdown_figure(data):
    """The lesson 12 activation equation drawn with the trace's own numbers:
    at four telling steps, fam-inject's five weighted terms stacked signed
    around zero, the before-inhibition sum marked, and the post-inhibition
    activation dotted below it.

    The term weights are retyped from core/controller/mb.py's constants; the
    consistency check below re-derives every drawn sum from the trace and
    fails the build if the retype and the recorded values ever disagree.
    """
    rows = data["steps"]
    family, rival = "fam-inject", "fam-recon"
    # (label, weighted value from a by_family cell); weights retyped from
    # PRIOR_WEIGHT, NOVELTY_WEIGHT, HABITUATION_WEIGHT, COST_WEIGHT.
    def terms(cell):
        return (("prior", 1.0 * cell["prior"]),
                ("novelty", 0.5 * cell["novelty"]),
                ("readout", cell["w_dot"]),
                ("habituation", -1.0 * cell["habituation"]),
                ("cost", -0.1 * cell["cost"]))

    for row in rows:
        cell = row["by_family"][family]
        if abs(sum(v for _, v in terms(cell))
               - cell["activation_before_inhibition"]) > 1e-6:
            raise ValueError("retyped term weights no longer reproduce the "
                             "trace's before-inhibition activation")

    picks = (
        (0, "fresh: novelty pays,", "wins, then errors"),
        (1, "after the first error", "suppressed"),
        (5, "after the exploration", "re-touch: peak penalty"),
        (17, "rested since: decay", "closes the gap"),
    )
    top, bottom = 1.25, -0.85

    width, height = 940, 540
    left, right, head, foot = 64, 236, 96, 130
    plot_w, plot_h = width - left - right, height - head - foot
    bar_w = 56

    def cx(i):
        return left + plot_w * (i + 0.5) / len(picks)

    def sy(value):
        return head + plot_h * (top - value) / (top - bottom)

    svg = Svg(width, height,
              "Mushroom-body activation term by term at four steps",
              "Signed stacked bars for the injection family at four selected "
              "steps of the scripted episode: prior, novelty and the learned "
              "readout stack upward, habituation and cost stack downward, a "
              "horizontal marker shows their sum before lateral inhibition "
              "and a dot shows the activation after it. Exact values are in "
              "data/course/mb-trace.json.")
    svg.text(left, 40, "One family's activation, term by term", size=20,
             fill=INK, weight="650")
    svg.text(left, 64, f"{family} through the episode; credits stack up, "
                       "penalties stack down, the dot is what competition "
                       "leaves", size=13, fill=INK_SOFT)

    for tick in (-0.5, 0.0, 0.5, 1.0):
        y = sy(tick)
        svg.line(left, y, left + plot_w, y,
                 BASELINE if tick == 0.0 else GRID, 1.5 if tick == 0.0 else 1)
        svg.text(left - 10, y + 4, fmt(tick), size=11, fill=INK_MUTED,
                 anchor="end")

    hue = SERIES[family]
    fills = {"prior": (hue, 1.0, None), "novelty": (hue, 0.55, None),
             "readout": (hue, 0.3, None),
             "habituation": (None, 0, (hue, "5 3")),
             "cost": (None, 0, (INK_MUTED, "2 3"))}

    for col, (step, cap1, cap2) in enumerate(picks):
        row = rows[step]
        cell = row["by_family"][family]
        x = cx(col) - bar_w / 2
        up = down = 0.0
        for name, value in terms(cell):
            if abs(value) * plot_h / (top - bottom) < 0.4:
                continue
            if value >= 0:
                y0, y1 = sy(up + value), sy(up)
                up += value
            else:
                y0, y1 = sy(down), sy(down + value)
                down += value
            fill, opacity, stroke = fills[name]
            if fill:
                extra = (f' fill-opacity="{opacity}"'
                         if opacity < 1.0 else "")
                svg.parts.append(
                    f'<rect x="{fmt(x)}" y="{fmt(y0)}" width="{bar_w}" '
                    f'height="{fmt(y1 - y0)}" fill="{fill}"{extra}/>')
            else:
                color, dash = stroke
                svg.parts.append(
                    f'<rect x="{fmt(x)}" y="{fmt(y0)}" width="{bar_w}" '
                    f'height="{fmt(y1 - y0)}" fill="none" stroke="{color}" '
                    f'stroke-width="1.5" stroke-dasharray="{dash}"/>')
            if col == 0 or name == "habituation":
                mid = (y0 + y1) / 2
                svg.text(x + bar_w + 8, mid + 4,
                         f"{name} {fmt(abs(value))}", size=11, fill=INK_SOFT)

        before = cell["activation_before_inhibition"]
        after = cell["activation"]
        svg.line(x - 6, sy(before), x + bar_w + 6, sy(before), INK, 2.5)
        svg.line(cx(col), sy(before), cx(col), sy(after), INK_MUTED, 1,
                 dash="2 3")
        svg.circle(cx(col), sy(after), 5, INK, stroke=SURFACE)
        if col == 0:
            svg.text(x - 12, sy(before) + 4, f"sum {fmt(before)}", size=11,
                     fill=INK, anchor="end")
            svg.text(x - 12, sy(after) + 4, f"after inhibition {fmt(after)}",
                     size=11, fill=INK_SOFT, anchor="end")
        else:
            svg.text(cx(col) + bar_w / 2 + 8, sy(after) + 4, fmt(after),
                     size=11, fill=INK_SOFT)

        base_y = head + plot_h + 28
        svg.text(cx(col), base_y, f"step {row['step']}", size=12,
                 fill=INK_MUTED, anchor="middle", weight="650")
        svg.text(cx(col), base_y + 18, cap1, size=11, fill=INK_MUTED,
                 anchor="middle")
        svg.text(cx(col), base_y + 33, cap2, size=11, fill=INK_MUTED,
                 anchor="middle")

    lx = width - right + 12
    svg.text(lx, 40, "terms (weight)", size=11, fill=INK_MUTED)
    legend = (("prior (x1)", fills["prior"]),
              ("novelty (x0.5)", fills["novelty"]),
              ("learned readout", fills["readout"]),
              ("habituation (x1)", fills["habituation"]),
              ("cost (x0.1)", fills["cost"]))
    for i, (label, (fill, opacity, stroke)) in enumerate(legend):
        y = 58 + i * 22
        if fill:
            extra = f' fill-opacity="{opacity}"' if opacity < 1.0 else ""
            svg.parts.append(
                f'<rect x="{lx}" y="{y - 10}" width="14" height="12" '
                f'fill="{fill}"{extra}/>')
        else:
            color, dash = stroke
            svg.parts.append(
                f'<rect x="{lx}" y="{y - 10}" width="14" height="12" '
                f'fill="none" stroke="{color}" stroke-width="1.5" '
                f'stroke-dasharray="{dash}"/>')
        svg.text(lx + 22, y, label, size=12, fill=INK_SOFT)
    ny = 58 + len(legend) * 22 + 12
    svg.line(lx, ny - 4, lx + 14, ny - 4, INK, 2.5)
    svg.text(lx + 22, ny, "sum before inhibition", size=12, fill=INK_SOFT)
    svg.circle(lx + 7, ny + 18, 5, INK, stroke=SURFACE)
    svg.text(lx + 22, ny + 22, "activation after it", size=12, fill=INK_SOFT)
    svg.text(left + plot_w / 2, height - 24,
             f"competition from {rival} sets the drop from bar to dot",
             size=12, fill=INK_MUTED, anchor="middle")
    return svg.render()


def plasticity_ledger_figure(data):
    """The lesson 13 update ledger: learned readout per family on top, the
    per-observe weight change underneath, clipping marked, phases labeled."""
    ledger = data["ledger"]
    families = ("fam-a", "fam-b")
    n = len(ledger)
    width, height = 940, 560
    left, right = 64, 170
    top_head, panel_h, panel_gap = 128, 160, 66
    plot_w = width - left - right

    def sx(i):
        return left + plot_w * (i + 0.5) / n

    svg = Svg(width, height,
              "The plasticity update ledger",
              "Two panels over the same observes: the learned readout per "
              "family on top, and the total absolute weight change per observe "
              "underneath, with clipping events marked and the reward, delayed, "
              "stale and saturate phases labeled. Exact values are in "
              "data/course/plasticity-trace.json.")
    svg.text(left, 40, "Which past choice received credit, and how much",
             size=20, fill=INK, weight="650")
    svg.text(left, 64, "top: learned w_dot per family; bottom: total absolute "
                       "weight change per observe, ring = clipped at the bound",
             size=13, fill=INK_SOFT)

    w_vals = [row["learned_w_dot"][f] for row in ledger for f in families]
    w_top, w_bottom = max(max(w_vals) * 1.2, 0.1), min(min(w_vals) * 1.2, -0.02)

    def wy(value):
        return top_head + panel_h * (w_top - value) / (w_top - w_bottom)

    for tick in (0.0, 0.5, 1.0):
        if tick > w_top:
            continue
        svg.line(left, wy(tick), left + plot_w, wy(tick),
                 BASELINE if tick == 0.0 else GRID, 1)
        svg.text(left - 10, wy(tick) + 4, fmt(tick), size=11, fill=INK_MUTED,
                 anchor="end")
    w_ends = []
    for family in families:
        points = [(sx(i), wy(row["learned_w_dot"][family]))
                  for i, row in enumerate(ledger)]
        svg.polyline(points, SERIES[family], width=2)
        w_ends.append([family, points[-1][1]])
    w_ends.sort(key=lambda e: e[1])
    for i, (family, y) in enumerate(w_ends):
        for _, prev in w_ends[:i]:
            if abs(prev - y) < 16:
                y = prev + 16
        w_ends[i][1] = y
        svg.circle(left + plot_w + 8, y, 4, SERIES[family])
        svg.text(left + plot_w + 18, y + 4, family, size=12, fill=INK_SOFT)
    svg.text(left - 46, top_head - 12, "learned w_dot", size=11, fill=INK_MUTED)

    bar_head = top_head + panel_h + panel_gap
    d_vals = [row["total_abs_delta"] for row in ledger]
    d_top = max(max(d_vals), 1e-6) * 1.2

    def dy(value):
        return bar_head + panel_h * (1 - value / d_top)

    svg.line(left, bar_head + panel_h, left + plot_w, bar_head + panel_h,
             BASELINE, 1.2)
    svg.text(left - 10, dy(d_top / 1.2) + 4, fmt(d_top / 1.2), size=11,
             fill=INK_MUTED, anchor="end")
    bar_w = max(4.0, plot_w / n - 8)
    for i, row in enumerate(ledger):
        x = sx(i) - bar_w / 2
        y = dy(row["total_abs_delta"])
        h = bar_head + panel_h - y
        if h > 0.5:
            svg.parts.append(
                f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(bar_w)}" '
                f'height="{fmt(h)}" rx="2" fill="{SERIES[row["decision_family"]]}"/>')
        if row["clipped"]:
            svg.circle(sx(i), y - 9, 4, SURFACE, stroke=INK)
        svg.text(sx(i), bar_head + panel_h + 18, str(i), size=10,
                 fill=INK_MUTED, anchor="middle")
    svg.text(left - 46, bar_head - 12, "total |dW| per observe", size=11,
             fill=INK_MUTED)

    # Phase bands along the top of the first panel.
    spans = []
    for i, row in enumerate(ledger):
        if spans and spans[-1][0] == row["phase"]:
            spans[-1][2] = i
        else:
            spans.append([row["phase"], i, i])
    for phase, start, end in spans:
        x0, x1 = sx(start) - 8, sx(end) + 8
        svg.line(x0, top_head - 26, x1, top_head - 26, INK_MUTED, 1)
        svg.text((x0 + x1) / 2, top_head - 32, phase, size=10, fill=INK_MUTED,
                 anchor="middle")
    svg.text(left + plot_w / 2, height - 16, "observe (bar color = the family "
             "whose decision earned the credit)", size=12, fill=INK_MUTED,
             anchor="middle")
    return svg.render()


def retrieval_pipeline_figure(_data=None):
    """The lesson 6 mechanism diagram, weights read from the search module."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.memory.search import KEYWORD_WEIGHT, VECTOR_WEIGHT

    accent = "#52c78d"
    width, height = 960, 380
    svg = Svg(width, height,
              "The hybrid retrieval pipeline",
              "A query is sanitized, runs through a keyword lane and an "
              "optional vector lane, each normalized separately, then a "
              "weighted merge produces ranked results carrying their component "
              "scores. When no embedder is configured the merge weights fall "
              "back to keyword-only.")
    svg.text(64, 40, "Where a memory's rank comes from", size=20, fill=INK,
             weight="650")
    svg.text(64, 64, "each result carries its component scores, so the merge "
                     "is inspectable instead of implied", size=13, fill=INK_SOFT)

    def box(x, y, w, h, title, sub, stroke):
        svg.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
            f'fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        svg.text(x + w / 2, y + 24, title, size=13, fill=INK, anchor="middle",
                 weight="650")
        if sub:
            svg.text(x + w / 2, y + 42, sub, size=11, fill=INK_SOFT,
                     anchor="middle")

    box(64, 150, 130, 56, "query", "scope filters", INK_MUTED)
    box(234, 150, 150, 56, "sanitize", "strip, not escape", INK_MUTED)
    box(434, 96, 210, 56, "keyword lane", "FTS5 bm25, negate, min-max", accent)
    box(434, 204, 210, 56, "vector lane", "embed, cosine, min-max", accent)
    box(694, 150, 200, 56, "weighted merge",
        f"vector {fmt(VECTOR_WEIGHT)} + keyword {fmt(KEYWORD_WEIGHT)}", accent)
    svg.line(194, 178, 228, 178, BASELINE, 1.5)
    svg.line(384, 168, 428, 130, BASELINE, 1.5)
    svg.line(384, 188, 428, 226, BASELINE, 1.5)
    svg.line(644, 124, 688, 168, BASELINE, 1.5)
    svg.line(644, 232, 688, 188, BASELINE, 1.5)
    svg.text(794, 236, "ranked results, with", size=11, fill=INK_SOFT,
             anchor="middle")
    svg.text(794, 252, "keyword, vector and final scores", size=11,
             fill=INK_SOFT, anchor="middle")
    svg.line(544, 264, 544, 306, INK_MUTED, 1, dash="4 4")
    svg.text(548, 300, "no embedder, or it raised: weights fall back to "
                       "keyword-only, flagged in the trace",
             size=11, fill=INK_MUTED)
    svg.text(64, height - 20, "retrieval is advisory: nothing on this path "
             "can authorize a tool or widen scope", size=12, fill=INK_MUTED)
    return svg.render()


def context_assembly_figure(_data=None):
    """The lesson 7 mechanism diagram, tier fractions read from the module."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.memory.context import TIER_FRACTIONS

    accent = "#52c78d"
    tiers = sorted(TIER_FRACTIONS)
    width, height = 960, 350
    svg = Svg(width, height,
              "From blocks to context, with the omissions on the record",
              "Blocks grouped by tier fill per-tier budgets by priority, the "
              "unused budget pools into an overflow pass, and the assembler "
              "returns the context plus an omissions record naming every "
              "dropped block and why.")
    svg.text(64, 40, "Budgets first, then overflow, and drops are recorded",
             size=20, fill=INK, weight="650")
    svg.text(64, 64, "blocks are kept or dropped whole; the omissions record "
                     "is a deliverable, not debugging", size=13, fill=INK_SOFT)
    x = 64
    for tier in tiers:
        share = TIER_FRACTIONS[tier]
        w = 700 * share
        svg.parts.append(
            f'<rect x="{fmt(x)}" y="110" width="{fmt(w - 8)}" height="56" rx="8" '
            f'fill="none" stroke="{accent}" stroke-width="1.5"/>')
        svg.text(x + (w - 8) / 2, 134, tier, size=12, fill=INK, anchor="middle",
                 weight="650")
        svg.text(x + (w - 8) / 2, 152, f"{fmt(share * 100)}% of budget",
                 size=11, fill=INK_SOFT, anchor="middle")
        x += w
    svg.text(64, 196, "1. per tier: sort by priority, keep whole blocks that "
                      "fit; a too-big block is skipped, a later smaller one "
                      "may still fit", size=12, fill=INK_SOFT)
    svg.text(64, 218, "2. unused tier budget pools; remaining blocks admitted "
                      "across tiers by priority until the pool is spent",
             size=12, fill=INK_SOFT)
    svg.text(64, 240, "3. expiry applies at assembly: an expired block never "
                      "enters, and its omission says so", size=12, fill=INK_SOFT)
    box_y = 268
    svg.parts.append(
        f'<rect x="64" y="{box_y}" width="330" height="52" rx="8" fill="none" '
        f'stroke="{accent}" stroke-width="1.8"/>')
    svg.text(229, box_y + 22, "assembled context", size=13, fill=INK,
             anchor="middle", weight="650")
    svg.text(229, box_y + 40, "provenance headers kept; token sizes are "
                              "estimates", size=10, fill=INK_SOFT, anchor="middle")
    svg.parts.append(
        f'<rect x="434" y="{box_y}" width="330" height="52" rx="8" fill="none" '
        f'stroke="{INK_MUTED}" stroke-width="1.5"/>')
    svg.text(599, box_y + 22, "omissions record", size=13, fill=INK,
             anchor="middle", weight="650")
    svg.text(599, box_y + 40, "every dropped block, with its reason",
             size=10, fill=INK_SOFT, anchor="middle")
    return svg.render()


# The course arc, grouped for the front page. Lesson numbers are listed
# explicitly so the figure regenerates red against the course if a lesson is
# added or renumbered without touching this table.
# Core route on the top row, the optional advanced route beneath it; the
# census check keeps this map honest against the actual lesson files.
BUILD_PATH_GROUPS = (
    ("Run and bound", "lessons 1, 2 and 3",
     "a reproduced run, one write boundary"),
    ("Propose and dispatch", "lessons 4 and 5",
     "hypotheses in, six outcome statuses out"),
    ("Remember, prove, finish", "lessons 6, 7, 8 and 9",
     "retrieval, verified findings, a gated finish"),
    ("Assemble", "lesson 16",
     "your provider, the same permissions"),
)
ADVANCED_GROUP = ("Compare controllers", "lessons 10 to 15",
                  "optional advanced route; one contract, honest baselines")


def build_path_figure(_data=None):
    """The front-page course map: the core route and the optional branch."""
    import re as _re
    course = sorted((ROOT / "handbook" / "course").glob("*.md"))
    numbers = {int(_re.match(r"(\d+)", p.name).group(1)) for p in course}
    listed = set()
    for _, lessons, _ in BUILD_PATH_GROUPS + (ADVANCED_GROUP,):
        found = [int(n) for n in _re.findall(r"\d+", lessons)]
        if "to" in lessons:
            listed.update(range(found[0], found[1] + 1))
        else:
            listed.update(found)
    if listed != numbers:
        raise ValueError(f"BUILD_PATH_GROUPS is out of step with the course: "
                         f"{sorted(listed ^ numbers)}")

    accent = "#52c78d"
    # Sized for the site's real content column (about 690px of measure): the
    # stylesheet renders images at column width, so an intrinsic width near
    # the column keeps every label at its stated size instead of shrinking
    # with the image.
    box_w, box_h, gap, left = 162, 96, 12, 24
    width = left * 2 + box_w * len(BUILD_PATH_GROUPS) + gap * (len(BUILD_PATH_GROUPS) - 1)
    height = 430
    svg = Svg(width, height,
              "The course map: the core route and the optional advanced route",
              "Top row, the core build route in order: run and bound (lessons "
              "one to three), propose and dispatch (four and five, with a "
              "marked detour into lesson ten's contract), remember, prove and "
              "finish (six to nine), and assemble (sixteen). Beneath it, the "
              "optional advanced route: compare controllers (lessons ten to "
              "fifteen), branching from the detour and reconnecting to "
              "assembly through the configuration's controller key.")
    svg.text(left, 42, "The course map", size=24, fill=INK, weight="650")
    svg.text(left, 68, "core route on top; the controller track is optional",
             size=15, fill=INK_SOFT)
    top = 96
    for i, (title, lessons, outcome) in enumerate(BUILD_PATH_GROUPS):
        x = left + i * (box_w + gap)
        svg.parts.append(
            f'<rect x="{x}" y="{top}" width="{box_w}" height="{box_h}" rx="8" '
            f'fill="none" stroke="{accent}" stroke-width="1.5"/>')
        svg.text(x + box_w / 2, top + 28, title, size=14, fill=INK,
                 anchor="middle", weight="650")
        svg.text(x + box_w / 2, top + 50, lessons, size=13, fill=INK_SOFT,
                 anchor="middle")
        words = outcome.split()
        half = (len(words) + 1) // 2
        svg.text(x + box_w / 2, top + 70, " ".join(words[:half]), size=12,
                 fill=INK_MUTED, anchor="middle")
        svg.text(x + box_w / 2, top + 87, " ".join(words[half:]), size=12,
                 fill=INK_MUTED, anchor="middle")
        if i:
            svg.line(x - gap + 2, top + box_h / 2, x - 2, top + box_h / 2,
                     accent, 1.5)
            svg.parts.append(
                f'<path d="M {fmt(x - 7)} {fmt(top + box_h / 2 - 4)} '
                f'L {fmt(x - 2)} {fmt(top + box_h / 2)} '
                f'L {fmt(x - 7)} {fmt(top + box_h / 2 + 4)}" '
                f'fill="none" stroke="{accent}" stroke-width="1.5"/>')

    # The advanced branch: down from propose-and-dispatch, back up to assemble.
    adv_y = top + box_h + 64
    adv_x = left + 1 * (box_w + gap)
    adv_w = box_w * 2 + gap
    title, lessons, outcome = ADVANCED_GROUP
    svg.parts.append(
        f'<rect x="{adv_x}" y="{adv_y}" width="{adv_w}" height="{box_h}" rx="8" '
        f'fill="none" stroke="{INK_MUTED}" stroke-width="1.5" '
        f'stroke-dasharray="5 4"/>')
    svg.text(adv_x + adv_w / 2, adv_y + 28, title, size=14, fill=INK,
             anchor="middle", weight="650")
    svg.text(adv_x + adv_w / 2, adv_y + 52, lessons, size=13, fill=INK_SOFT,
             anchor="middle")
    svg.text(adv_x + adv_w / 2, adv_y + 76, outcome, size=12, fill=INK_MUTED,
             anchor="middle")
    branch_x = left + 1 * (box_w + gap) + box_w / 2
    svg.line(branch_x, top + box_h + 2, branch_x, adv_y - 2, INK_MUTED, 1.2,
             dash="4 4")
    svg.text(branch_x + 10, top + box_h + 34, "detour: lesson 10,",
             size=13, fill=INK_SOFT)
    svg.text(branch_x + 10, top + box_h + 52, "then return", size=13,
             fill=INK_SOFT)
    rejoin_x = left + 3 * (box_w + gap) + box_w / 2
    svg.line(adv_x + adv_w + 2, adv_y + box_h / 2, rejoin_x,
             adv_y + box_h / 2, INK_MUTED, 1.2, dash="4 4")
    svg.line(rejoin_x, adv_y + box_h / 2, rejoin_x, top + box_h + 2,
             INK_MUTED, 1.2, dash="4 4")
    svg.text(rejoin_x - 12, top + box_h + 34, "reconnects through", size=13,
             fill=INK_SOFT, anchor="end")
    svg.text(rejoin_x - 12, top + box_h + 52, "the controller key", size=13,
             fill=INK_SOFT, anchor="end")
    svg.text(left, height - 22, "every lesson: a run command, a committed "
             "artifact, a failure exercise, a completion check",
             size=13, fill=INK_SOFT)
    return svg.render()


def verification_sequence_figure(_data=None):
    """The lesson 8 verdict-path diagram, drawn from the verify module's own
    closed vocabulary so the picture cannot drift from the code."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.run.verify import VERDICTS

    accent = "#52c78d"
    width, height = 720, 470
    svg = Svg(width, height,
              "From a capture to a reviewed finding",
              "The verification sequence: a capture-bound finding is governed "
              "by the deterministic policy, packed with exactly its own "
              "capture for the verifier, and the verifier's reply is validated "
              "in host code against the closed verdict vocabulary -- " +
              ", ".join(VERDICTS) + " -- with unknown verdicts refused. Human "
              "acceptance stays a separate recorded decision.")
    svg.text(40, 36, "The verdict path, with the host holding every gate",
             size=19, fill=INK, weight="650")
    svg.text(40, 58, "a quote must occur in the cited capture; a raise needs "
                     "contained proof", size=13, fill=INK_SOFT)

    def box(x, y, w, h, title, sub, stroke):
        svg.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
            f'fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        svg.text(x + w / 2, y + 24, title, size=14, fill=INK, anchor="middle",
                 weight="650")
        if sub:
            svg.text(x + w / 2, y + 43, sub, size=12, fill=INK_SOFT,
                     anchor="middle")

    def arrow(x1, y1, x2, y2):
        svg.line(x1, y1, x2, y2, INK_MUTED, 1.5)

    row1 = 84
    box(40, row1, 180, 58, "capture", "content-addressed", INK_MUTED)
    box(262, row1, 180, 58, "finding", "verbatim quote required", INK_MUTED)
    box(484, row1, 196, 58, "govern", "grade, then ceiling", accent)
    arrow(220, row1 + 29, 258, row1 + 29)
    arrow(442, row1 + 29, 480, row1 + 29)

    row2 = 186
    box(40, row2, 300, 58, "verifier packet",
        "one finding, its own capture, nothing else", accent)
    box(380, row2, 300, 58, "host validates the reply",
        "closed vocabulary; unknown is refused", accent)
    arrow(582, row1 + 58 + 2, 582, row2 - 2)
    svg.line(582, row1 + 58 + 22, 190, row1 + 58 + 22, INK_MUTED, 1.5)
    arrow(190, row1 + 58 + 22, 190, row2 - 2)
    arrow(340, row2 + 29, 376, row2 + 29)

    verdicts_y = 296
    labels = {
        "accept": "severity holds",
        "reject": "kept visible, with evidence",
        "needs_review": "unverified high caps",
        "adjust_severity": "down freely; up needs proof",
    }
    positions = [(40, verdicts_y), (380, verdicts_y),
                 (40, verdicts_y + 74), (380, verdicts_y + 74)]
    hub_x, hub_y = 530, row2 + 58
    for verdict, (bx, by) in zip(VERDICTS, positions):
        box(bx, by, 300, 58, verdict, labels[verdict], INK_MUTED)
        arrow(hub_x, hub_y + 2, bx + 150, by - 2)
    svg.text(40, height - 16, "human acceptance is a separate recorded "
             "decision; nothing on this path flips a finding to accepted",
             size=13, fill=INK_MUTED)
    return svg.render()


def candidate_feedback_figure(_data=None):
    """The lesson 10 loop: how an action becomes a learning signal, drawn from
    the contract's own vocabularies."""
    import sys
    sys.path.insert(0, str(ROOT))
    from core.controller.contract import OUTCOME_STATUSES
    from core.controller.feedback import WEIGHTS, WEIGHTS_VERSION

    accent = "#52c78d"
    width, height = 960, 430
    svg = Svg(width, height,
              "The candidate-to-feedback loop",
              "The host offers eligible candidates; the controller answers "
              "with a decision; the policy door re-checks before anything "
              "runs; the outcome carries one of the fixed statuses -- " +
              ", ".join(OUTCOME_STATUSES) + " -- and the shared feedback "
              "signal, scalarized under the versioned weights, returns to the "
              "decision that earned it.")
    svg.text(64, 40, "How an action becomes a learning signal", size=20,
             fill=INK, weight="650")
    svg.text(64, 64, "selection is advice; the door is the door; credit is "
                     "keyed by decision and controller", size=13, fill=INK_SOFT)

    def box(x, y, w, h, title, sub, stroke):
        svg.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
            f'fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        svg.text(x + w / 2, y + 24, title, size=13, fill=INK, anchor="middle",
                 weight="650")
        if sub:
            svg.text(x + w / 2, y + 42, sub, size=10, fill=INK_SOFT,
                     anchor="middle")

    top_y, bottom_y = 100, 240
    box(64, top_y, 190, 56, "eligible candidates", "host-built, with reasons",
        INK_MUTED)
    box(294, top_y, 180, 56, "controller.select", "decision, scores visible",
        accent)
    box(514, top_y, 170, 56, "the policy door", "re-checked per action",
        accent)
    box(724, top_y, 170, 56, "execute", "capture or error", INK_MUTED)
    for x1, x2 in ((254, 288), (474, 508), (684, 718)):
        svg.line(x1, top_y + 28, x2, top_y + 28, BASELINE, 1.5)
    svg.line(809, top_y + 56, 809, bottom_y - 4, BASELINE, 1.5)
    box(639, bottom_y, 255, 62, "outcome",
        "status from the fixed vocabulary", INK_MUTED)
    box(294, bottom_y, 305, 62, "shared feedback signal",
        "components scalarized under " + WEIGHTS_VERSION, accent)
    svg.line(635, bottom_y + 31, 603, bottom_y + 31, BASELINE, 1.5)
    box(64, bottom_y, 190, 62, "controller.observe",
        "decision-keyed; once", accent)
    svg.line(290, bottom_y + 31, 258, bottom_y + 31, BASELINE, 1.5)
    svg.line(159, bottom_y, 159, top_y + 60, BASELINE, 1.5, dash="4 3")
    svg.text(64, 350, "components: " + ", ".join(sorted(WEIGHTS[WEIGHTS_VERSION])),
             size=11, fill=INK_MUTED)
    svg.text(64, 372, "statuses: " + ", ".join(OUTCOME_STATUSES), size=11,
             fill=INK_MUTED)
    svg.text(64, height - 16, "a shadow decision, an unexecuted decision, a "
             "mis-addressed outcome and a replay all earn nothing", size=12,
             fill=INK_MUTED)
    return svg.render()


def graph_topology_figure(data):
    """The lesson 14 toy topology, drawn from the committed fixture, with the
    learning site labeled where it lives."""
    import math
    n = data["nodes"] if isinstance(data["nodes"], int) else len(data["nodes"])
    edges = data["edges"]
    accent = "#52c78d"
    width, height = 940, 520
    cx, cy, radius = 300, 280, 180
    svg = Svg(width, height,
              "The toy topology and its learning site",
              f"The committed toy graph: {n} nodes on a circle with its "
              f"{len(edges)} directed weighted edges drawn between them. The "
              "plastic site is the association edges; the per-family readout "
              "over the active set never learns. The shuffled and random "
              "control arms rewire these edges while preserving the counts.")
    svg.text(64, 40, "An authored toy graph, and where learning lives",
             size=20, fill=INK, weight="650")
    svg.text(64, 64, "drawn from data/course/graph-toy.json; the originating "
                     "experiments froze a measured connectome this repository "
                     "does not ship", size=13, fill=INK_SOFT)

    def pos(i):
        angle = 2 * math.pi * i / n - math.pi / 2
        return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    max_w = max(e[2] for e in edges)
    for pre, post, w in edges:
        x1, y1 = pos(pre)
        x2, y2 = pos(post)
        opacity = 0.15 + 0.45 * (w / max_w)
        svg.parts.append(
            f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" '
            f'stroke="{accent}" stroke-width="1" stroke-opacity="{opacity:.2f}"/>')
    for i in range(n):
        x, y = pos(i)
        svg.circle(x, y, 4, SURFACE, stroke=INK_MUTED, stroke_width=1.2)
    lx = 580
    svg.text(lx, 150, "the plastic site", size=14, fill=INK, weight="650")
    svg.text(lx, 172, "association edges, keyed (pre, post):", size=12,
             fill=INK_SOFT)
    svg.text(lx, 190, "hop weight = w_norm + learned", size=12, fill=INK_SOFT)
    svg.text(lx, 208, "deposits land on the co-activation", size=12,
             fill=INK_SOFT)
    svg.text(lx, 226, "keys of each non-shadow selection", size=12,
             fill=INK_SOFT)
    svg.text(lx, 268, "what never learns", size=14, fill=INK, weight="650")
    svg.text(lx, 290, "the per-family readout over the", size=12, fill=INK_SOFT)
    svg.text(lx, 308, "active set: fixed seeded noise,", size=12, fill=INK_SOFT)
    svg.text(lx, 326, "the design invariant separating", size=12, fill=INK_SOFT)
    svg.text(lx, 344, "this arm from lesson 13's", size=12, fill=INK_SOFT)
    svg.text(lx, 386, "the controls", size=14, fill=INK, weight="650")
    svg.text(lx, 408, "shuffled: degrees kept, wiring destroyed", size=12,
             fill=INK_SOFT)
    svg.text(lx, 426, "random: counts kept, everything redrawn", size=12,
             fill=INK_SOFT)
    svg.text(lx, 444, "no-hop: step-zero set only, no edge keys", size=12,
             fill=INK_SOFT)
    svg.text(lx, 462, "frozen: no deposit, no update", size=12, fill=INK_SOFT)
    svg.text(64, height - 16, "edge opacity follows raw weight; a toy "
             "mechanism figure, not evidence about any topology", size=12,
             fill=INK_MUTED)
    return svg.render()


def research_summary_figure(data):
    """The lesson 15 comparison figure: per-world panels of total reward per
    condition, drawn from the committed summary."""
    rows = [r for r in data["rows"] if r["status"] == "analyzed"]
    worlds = sorted({r["condition"].split("--")[1] for r in rows})
    conditions = []
    for r in rows:
        name = r["condition"].split("--")[0]
        if name not in conditions:
            conditions.append(name)
    lo = min(min(r["total_reward"] for r in rows), 0.0)
    hi = max(max(r["total_reward"] for r in rows), 0.0)

    panel_w, panel_h, gap_x, gap_y = 380, 130, 60, 46
    left, head = 130, 110
    width = left + panel_w * 2 + gap_x + 40
    height = head + panel_h * 2 + gap_y + 116
    svg = Svg(width, height,
              "Total reward per condition, by world",
              "Four panels, one per synthetic world, each showing every "
              "manifest condition's total reward as a labeled bar from the "
              "committed research summary. The exact values are in "
              "data/course/research-summary.json.")
    svg.text(64, 40, "The frozen manifest's summary, drawn", size=20,
             fill=INK, weight="650")
    svg.text(64, 64, "one seed and short episodes on purpose: the figure "
                     "shows the protocol's output shape, not statistical "
                     "power", size=13, fill=INK_SOFT)

    def bar_color(name):
        return SERIES.get(name.replace("-frozen", ""), INK_MUTED)

    for w_index, world in enumerate(worlds):
        px = left + (w_index % 2) * (panel_w + gap_x)
        py = head + (w_index // 2) * (panel_h + gap_y)

        def sx(value):
            return px + panel_w * (value - lo) / (hi - lo)

        svg.text(px, py - 8, world, size=13, fill=INK, weight="650")
        svg.line(sx(0), py, sx(0), py + panel_h - 18, INK_MUTED, 1.2)
        axis_y = py + panel_h - 12
        for tick in (lo, 0.0, hi):
            svg.line(sx(tick), axis_y - 4, sx(tick), axis_y, INK_MUTED, 1)
            svg.text(sx(tick), axis_y + 14, fmt(round(tick, 1)), size=13,
                     fill=INK_SOFT, anchor="middle")
        bar_h = (panel_h - 24) / len(conditions)
        for c_index, name in enumerate(conditions):
            row = next(r for r in rows
                       if r["condition"] == f"{name}--{world}--seed7")
            y = py + c_index * bar_h
            x0, x1 = sorted((sx(0), sx(row["total_reward"])))
            svg.parts.append(
                f'<rect x="{fmt(x0)}" y="{fmt(y)}" width="{fmt(max(x1 - x0, 0.5))}" '
                f'height="{fmt(bar_h - 3)}" rx="2" fill="{bar_color(name)}"/>')
            svg.text(px - 8, y + bar_h / 2 + 4, name, size=13,
                     fill=INK_SOFT, anchor="end")
    svg.text(64, height - 62, "axis: total synthetic reward under this toy "
             "world's scoring rule -- larger is more reward; the marked zero "
             "line separates net-positive from net-negative", size=13,
             fill=INK_SOFT)
    svg.text(64, height - 40, "bar color follows the base controller (frozen "
             "twins share their hue and are named); identity is the row "
             "label, never color alone", size=12, fill=INK_MUTED)
    svg.text(64, height - 18, "read one row before citing one: scope every "
             "statement to its measured world and replicate unit", size=12,
             fill=INK_MUTED)
    return svg.render()


def _flow_box(svg, x, y, w, h, title, sub, stroke, title_size=14, sub_size=12):
    svg.parts.append(
        f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
        f'rx="8" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
    svg.text(x + w / 2, y + 23, title, size=title_size, fill=INK,
             anchor="middle", weight="650")
    if sub:
        svg.text(x + w / 2, y + 42, sub, size=sub_size, fill=INK_SOFT,
                 anchor="middle")


def _arrow(svg, x1, y1, x2, y2, stroke=None, dash=None, label=None,
           label_dy=-6):
    stroke = stroke or INK_MUTED
    svg.line(x1, y1, x2, y2, stroke, 1.5, dash=dash)
    if x2 > x1 and y1 == y2:
        svg.parts.append(
            f'<path d="M {fmt(x2 - 6)} {fmt(y2 - 4)} L {fmt(x2)} {fmt(y2)} '
            f'L {fmt(x2 - 6)} {fmt(y2 + 4)}" fill="none" stroke="{stroke}" '
            f'stroke-width="1.5"/>')
    elif y2 > y1 and x1 == x2:
        svg.parts.append(
            f'<path d="M {fmt(x2 - 4)} {fmt(y2 - 6)} L {fmt(x2)} {fmt(y2)} '
            f'L {fmt(x2 + 4)} {fmt(y2 - 6)}" fill="none" stroke="{stroke}" '
            f'stroke-width="1.5"/>')
    if label:
        svg.text((x1 + x2) / 2, min(y1, y2) + label_dy, label, size=12,
                 fill=INK_MUTED, anchor="middle")


def proposal_sequence_figure(_data=None):
    """Lesson 4: where a model client plugs in, and when repair stops."""
    accent = "#52c78d"
    width, height = 720, 470
    svg = Svg(width, height,
              "One proposal round, from context to admission",
              "The host builds the proposal context and hands it to the "
              "provider callable -- the one place a model client plugs in. "
              "The reply passes strict parsing and the hypothesis schema; a "
              "malformed reply earns one bounded repair attempt carrying the "
              "validation error back, while a well-formed proposal goes to "
              "the policy, whose refusal is terminal. Every call is admitted "
              "against the host's stops and charged to the shared model-call "
              "budget.")
    svg.text(40, 36, "One proposal round", size=19, fill=INK, weight="650")
    svg.text(40, 58, "your model client is the provider callable; everything "
                     "around it is the host's", size=13, fill=INK_SOFT)
    _flow_box(svg, 40, 84, 300, 58, "proposal context",
              "instruction, observations, evidence", INK_MUTED)
    _flow_box(svg, 380, 84, 300, 58, "provider(context)",
              "your client plugs in here", accent)
    _arrow(svg, 340, 113, 376, 113)
    svg.text(358, 76, "admitted + charged", size=12, fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 380, 186, 300, 58, "strict parse",
              "one JSON object, byte cap, no extras", INK_MUTED)
    _arrow(svg, 530, 142, 530, 182, label=None)
    _flow_box(svg, 40, 186, 300, 58, "hypothesis schema",
              "kind, surface, evidence, action", INK_MUTED)
    svg.line(380, 215, 348, 215, INK_MUTED, 1.5)
    svg.parts.append('<path d="M 350 211 L 344 215 L 350 219" fill="none" '
                     f'stroke="{INK_MUTED}" stroke-width="1.5"/>')
    _flow_box(svg, 40, 288, 300, 58, "policy", "terminal either way", accent)
    _arrow(svg, 190, 244, 190, 284)
    _flow_box(svg, 380, 288, 300, 58, "admitted plan row",
              "same door as everything else", INK_MUTED)
    _arrow(svg, 340, 317, 376, 317, label="allowed")
    # The repair loop: malformed only, bounded, re-admitted per call.
    svg.line(620, 244, 620, 264, INK_MUTED, 1.2, dash="4 4")
    svg.line(620, 264, 700, 264, INK_MUTED, 1.2, dash="4 4")
    svg.line(700, 264, 700, 113, INK_MUTED, 1.2, dash="4 4")
    svg.line(700, 113, 684, 113, INK_MUTED, 1.2, dash="4 4")
    svg.text(696, 258, "repair:", size=12, fill=INK_MUTED, anchor="end")
    svg.text(696, 274, "malformed only,", size=12, fill=INK_MUTED,
             anchor="end")
    svg.text(696, 290, "bounded,", size=12, fill=INK_MUTED, anchor="end")
    svg.text(696, 306, "re-admitted", size=12, fill=INK_MUTED, anchor="end")
    svg.text(40, 384, "repair stops at the attempt bound, the model-call "
             "budget, cancellation,", size=13, fill=INK_SOFT)
    svg.text(40, 404, "closure or the wall deadline -- whichever comes "
             "first; a policy refusal is terminal", size=13, fill=INK_SOFT)
    svg.text(40, 424, "because rephrasing a forbidden action does not "
             "permit it", size=13, fill=INK_SOFT)
    svg.text(40, height - 16, "a call already running may finish late; no "
             "further call starts after the run's stops", size=12,
             fill=INK_MUTED)
    return svg.render()


def dispatch_door_figure(_data=None):
    """Lesson 5: eligible candidate to permitted callback to recorded outcome."""
    accent = "#52c78d"
    width, height = 720, 400
    svg = Svg(width, height,
              "From an eligible candidate to a recorded outcome",
              "Selection is advice: whoever chose the candidate, dispatch "
              "re-asks the policy, the recorded gate and stage, and the "
              "budgets at the door before the adapter runs. A permitted "
              "callback becomes a content-addressed capture and one terminal "
              "outcome; every refusal and skip is recorded with its reason; "
              "feedback returns to the controller only for executed work.")
    svg.text(40, 36, "The dispatch door", size=19, fill=INK, weight="650")
    svg.text(40, 58, "eligibility, order and permission are three separate "
                     "decisions", size=13, fill=INK_SOFT)
    _flow_box(svg, 40, 84, 190, 58, "candidates", "eligible, with reasons",
              INK_MUTED)
    _flow_box(svg, 270, 84, 180, 58, "controller", "advice, not permission",
              INK_MUTED)
    _flow_box(svg, 490, 84, 190, 58, "the door",
              "policy, gate, stage, budget", accent)
    _arrow(svg, 230, 113, 266, 113)
    _arrow(svg, 450, 113, 486, 113, label="chosen")
    _flow_box(svg, 490, 196, 190, 58, "adapter runs", "fixture callback",
              INK_MUTED)
    _arrow(svg, 585, 142, 585, 192, label=None)
    svg.text(602, 172, "admitted", size=12, fill=INK_MUTED)
    _flow_box(svg, 270, 196, 180, 58, "capture + outcome",
              "one terminal status", INK_MUTED)
    svg.line(490, 225, 458, 225, INK_MUTED, 1.5)
    svg.parts.append('<path d="M 460 221 L 454 225 L 460 229" fill="none" '
                     f'stroke="{INK_MUTED}" stroke-width="1.5"/>')
    _flow_box(svg, 40, 196, 190, 58, "feedback",
              "executed work only", INK_MUTED)
    svg.line(270, 225, 238, 225, INK_MUTED, 1.5)
    svg.parts.append('<path d="M 240 221 L 234 225 L 240 229" fill="none" '
                     f'stroke="{INK_MUTED}" stroke-width="1.5"/>')
    svg.text(40, 300, "a refusal leaves the door as a recorded reason -- "
             "unknown tool, foreign origin, stop gate,", size=13,
             fill=INK_SOFT)
    svg.text(40, 320, "wrong stage, spent budget, settled or unresolved "
             "identity -- and the adapter never runs for it;", size=13,
             fill=INK_SOFT)
    svg.text(40, 340, "six outcome words, and none of them blur", size=13,
             fill=INK_SOFT)
    svg.text(40, height - 16, "clean means executed and captured; a security "
             "conclusion is a later, human decision", size=12, fill=INK_MUTED)
    return svg.render()


def lifecycle_states_figure(_data=None):
    """Lesson 9: running, interrupted, unresolved, reconciled, closed."""
    accent = "#52c78d"
    warn = "#d95926"
    width, height = 720, 470
    svg = Svg(width, height,
              "The lifecycle's states and the one-way closure",
              "A running plan can stop on budgets, gate, cancellation or no "
              "progress, with the remainder recorded as skips. An "
              "interruption checkpoints; resume folds the ledger back and an "
              "action without a recorded outcome comes back unresolved. "
              "Reconciliation settles it only on evidence; re-dispatch needs "
              "a declared idempotent tool; an action still unresolved is "
              "named in the gated finish's coverage rather than blocking it. "
              "Finish closes the run; abort closes it early from the running "
              "side; a closed run refuses every later effect, and there is "
              "no reopen.")
    svg.text(40, 36, "Stop, recover, finish", size=19, fill=INK, weight="650")
    svg.text(40, 58, "when work may resume, and when a possible side effect "
                     "must never repeat", size=13, fill=INK_SOFT)
    _flow_box(svg, 40, 88, 180, 58, "running",
              "admitted per attempt", accent)
    _flow_box(svg, 270, 88, 180, 58, "checkpointed",
              "the ledger, folded", INK_MUTED)
    _flow_box(svg, 500, 88, 180, 58, "resumed",
              "same write boundary", INK_MUTED)
    _arrow(svg, 220, 117, 266, 117)
    svg.text(243, 82, "interrupt", size=12, fill=INK_MUTED, anchor="middle")
    _arrow(svg, 450, 117, 496, 117)
    svg.text(473, 82, "fold back", size=12, fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 500, 196, 180, 58, "unresolved",
              "maybe it ran; prove it", warn)
    _arrow(svg, 590, 146, 590, 192)
    _flow_box(svg, 270, 196, 180, 58, "reconciled",
              "capture found: settled", INK_MUTED)
    svg.line(500, 225, 458, 225, INK_MUTED, 1.5)
    svg.parts.append('<path d="M 460 221 L 454 225 L 460 229" fill="none" '
                     f'stroke="{INK_MUTED}" stroke-width="1.5"/>')
    svg.text(360, 274, "no capture: stays unresolved;", size=12,
             fill=INK_MUTED, anchor="middle")
    svg.text(360, 290, "re-dispatch only if declared idempotent", size=12,
             fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 40, 196, 180, 58, "stopped remainder",
              "skips, reasons recorded", INK_MUTED)
    _arrow(svg, 130, 146, 130, 192)
    svg.text(146, 172, "budget / gate / cancel", size=12, fill=INK_MUTED)
    _flow_box(svg, 40, 330, 300, 58, "finished",
              "gated on complete accounting", accent)
    _flow_box(svg, 380, 330, 300, 58, "aborted",
              "the early close, reason kept", warn)
    _arrow(svg, 130, 254, 130, 326)
    # An action still unresolved does not block the gate: it is named in the
    # finished report's coverage.
    svg.line(590, 254, 590, 276, INK_MUTED, 1.5, dash="4 4")
    svg.line(590, 276, 190, 276, INK_MUTED, 1.5, dash="4 4")
    _arrow(svg, 190, 276, 190, 326, dash="4 4")
    svg.text(390, 312, "still unresolved: named in the finish's coverage",
             size=12, fill=INK_MUTED, anchor="middle")
    # Abort is the operator's early close from the running side.
    svg.line(60, 146, 60, 306, INK_MUTED, 1.2, dash="6 4")
    svg.line(60, 306, 430, 306, INK_MUTED, 1.2, dash="6 4")
    _arrow(svg, 430, 306, 430, 326, dash="6 4")
    svg.text(72, 302, "abort: the operator ends it early", size=12,
             fill=INK_MUTED)
    svg.text(40, height - 40, "finished and aborted are both closed: later "
             "effects are refused at the write boundary,", size=12,
             fill=INK_MUTED)
    svg.text(40, height - 20, "closure survives resume, and continuing "
             "means a new run", size=12, fill=INK_MUTED)
    return svg.render()


def assembled_app_figure(_data=None):
    """Lesson 16: the actual connected application, one record's journey."""
    accent = "#52c78d"
    width, height = 720, 620
    svg = Svg(width, height,
              "The assembled application, as wired",
              "One configured run: observations gate the world; the memory "
              "store's search assembles budgeted context with omissions "
              "recorded; the observation-phase proposal and the plan execute "
              "through the dispatch door; capture summaries feed the "
              "evidence-phase proposal; verification spends the same "
              "model-call meter; surviving findings return to the store as "
              "tactics; finish closes the run; the review decision is a "
              "separate artifact beside it.")
    svg.text(40, 36, "The assembled application", size=19, fill=INK,
             weight="650")
    svg.text(40, 58, "follow the shared banner finding through every "
                     "connected part", size=13, fill=INK_SOFT)
    _flow_box(svg, 40, 84, 200, 56, "observe + gate",
              "full / passive / stop", accent)
    _flow_box(svg, 280, 84, 200, 56, "plan", "candidates + coverage",
              INK_MUTED)
    _flow_box(svg, 520, 84, 160, 56, "memory store",
              "search, budget, trace", INK_MUTED)
    _arrow(svg, 240, 112, 276, 112)
    _flow_box(svg, 40, 188, 200, 56, "propose: observation",
              "advisory context attached", INK_MUTED)
    _arrow(svg, 600, 140, 600, 160)
    svg.line(600, 160, 140, 160, INK_MUTED, 1.2, dash="4 4")
    svg.line(140, 160, 140, 184, INK_MUTED, 1.2, dash="4 4")
    svg.text(370, 154, "assembled context, omissions recorded", size=12,
             fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 280, 188, 200, 56, "the door",
              "policy, gate, stage, budgets", accent)
    _arrow(svg, 240, 216, 276, 216)
    _flow_box(svg, 520, 188, 160, 56, "captures",
              "content-addressed", INK_MUTED)
    _arrow(svg, 480, 216, 516, 216)
    _flow_box(svg, 40, 292, 200, 56, "propose: evidence",
              "sees the new captures", accent)
    svg.line(600, 244, 600, 264, INK_MUTED, 1.2, dash="4 4")
    svg.line(600, 264, 140, 264, INK_MUTED, 1.2, dash="4 4")
    svg.line(140, 264, 140, 288, INK_MUTED, 1.2, dash="4 4")
    svg.text(370, 258, "capture summaries: the loop", size=12,
             fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 280, 292, 200, 56, "the door, again",
              "admitted follow-up runs", INK_MUTED)
    _arrow(svg, 240, 320, 276, 320)
    _flow_box(svg, 520, 292, 160, 56, "verify",
              "shared model meter", INK_MUTED)
    _arrow(svg, 480, 320, 516, 320)
    _flow_box(svg, 40, 396, 200, 56, "remember",
              "tactics back to the store", INK_MUTED)
    svg.line(600, 348, 600, 368, INK_MUTED, 1.2, dash="4 4")
    svg.line(600, 368, 140, 368, INK_MUTED, 1.2, dash="4 4")
    svg.line(140, 368, 140, 392, INK_MUTED, 1.2, dash="4 4")
    svg.text(370, 362, "surviving findings; refuted writes decline", size=12,
             fill=INK_MUTED, anchor="middle")
    _flow_box(svg, 280, 396, 200, 56, "finish",
              "gated, then closed", accent)
    _arrow(svg, 240, 424, 276, 424)
    _flow_box(svg, 520, 396, 160, 56, "review artifact",
              "beside the closed run", accent)
    _arrow(svg, 480, 424, 516, 424, label=None)
    svg.text(40, 496, "call sites, in run() order: _start, _observe, _plan,",
             size=12, fill=INK_SOFT)
    svg.text(40, 514, "_proposal_pass (retrieval assembles inside it), "
             "_execute, _proposal_pass(evidence),", size=12, fill=INK_SOFT)
    svg.text(40, 532, "_execute_rows, _review, _remember, finish -- the "
             "store itself opens lazily, at first use", size=12,
             fill=INK_SOFT)
    svg.text(40, 556, "one shared model-call meter spans proposals, repairs "
             "and verifier calls; one write boundary", size=12, fill=INK_SOFT)
    svg.text(40, 574, "records everything, refusals included", size=12,
             fill=INK_SOFT)
    svg.text(40, height - 16, "the review decision never reopens the run; "
             "examples/app_agent.py is this diagram, executable", size=12,
             fill=INK_MUTED)
    return svg.render()


def sparse_encoding_inset(_data=None):
    """Lesson 12: state to projection to sparse code to family score."""
    accent = "#52c78d"
    width, height = 720, 316
    svg = Svg(width, height,
              "How the sparse controller computes one family score",
              "The state vector passes a fixed random sign projection; only "
              "the top strictly-positive expansion units stay active (the "
              "sparse code); the family readout averages its fixed weights "
              "over exactly those active units, and the family signal adds "
              "prior, novelty, habituation and cost around it.")
    svg.text(40, 36, "State to sparse code to family score", size=19,
             fill=INK, weight="650")
    _flow_box(svg, 40, 70, 140, 56, "state x", "d numbers", INK_MUTED)
    _flow_box(svg, 220, 70, 180, 56, "sign projection",
              "fixed, seeded, sparse", INK_MUTED)
    _flow_box(svg, 440, 70, 130, 56, "top-k units", "the sparse code", accent)
    _flow_box(svg, 40, 176, 250, 56, "family readout",
              "mean fixed weight over active", INK_MUTED)
    _flow_box(svg, 330, 176, 350, 56, "activation",
              "prior + novelty + w_dot - habituation - cost", accent)
    _arrow(svg, 180, 98, 216, 98)
    _arrow(svg, 400, 98, 436, 98)
    svg.line(505, 126, 505, 146, INK_MUTED, 1.5)
    svg.line(505, 146, 165, 146, INK_MUTED, 1.5)
    _arrow(svg, 165, 146, 165, 172)
    _arrow(svg, 290, 204, 326, 204)
    dots = [(452, 98), (466, 98), (480, 98), (494, 98), (508, 98)]
    for i, (dx, dy) in enumerate(dots):
        svg.circle(dx, dy + 22, 3.4, accent if i in (0, 2, 4) else GRID)
    svg.text(524, 124, "active", size=12, fill=INK_MUTED)
    svg.text(40, 256, "habituation keys on (surface class, family, "
             "signature):", size=13, fill=INK_SOFT)
    svg.text(40, 274, "a family erroring on one surface shape is suppressed "
             "there, nowhere else", size=13, fill=INK_SOFT)
    svg.text(40, height - 16, "no learned weights anywhere on this page; "
             "the next lesson adds the one learning site", size=12,
             fill=INK_MUTED)
    return svg.render()


def delayed_credit_inset(_data=None):
    """Lesson 13: two decisions, one late reward, the traces still alive."""
    accent = "#52c78d"
    warn = "#d95926"
    width, height = 720, 336
    svg = Svg(width, height,
              "Delayed credit over decaying traces",
              "Selection A lays traces for family A; selection B decays them "
              "and lays its own; when A's reward finally arrives, the update "
              "applies to every trace still alive -- A's, now smaller, and "
              "B's, fresh. Shared traces are the mechanism and the "
              "interference, both on purpose and both visible in the "
              "ledger.")
    svg.text(40, 36, "Two selections, one late reward", size=19, fill=INK,
             weight="650")
    timeline_y = 96
    svg.line(60, timeline_y, 660, timeline_y, INK_MUTED, 1.5)
    for x, label in ((120, "select A"), (330, "select B"),
                     (560, "reward for A arrives")):
        svg.circle(x, timeline_y, 5, accent if "reward" not in label else warn)
        svg.text(x, timeline_y - 14, label, size=13, fill=INK,
                 anchor="middle")
    svg.text(120, timeline_y + 24, "traces(A) = 1.0", size=12,
             fill=INK_SOFT, anchor="middle")
    svg.text(330, timeline_y + 24, "traces(A) decay to 0.8;", size=12,
             fill=INK_SOFT, anchor="middle")
    svg.text(330, timeline_y + 40, "traces(B) = 1.0", size=12,
             fill=INK_SOFT, anchor="middle")
    svg.text(560, timeline_y + 24, "update touches A at 0.8", size=12,
             fill=INK_SOFT, anchor="middle")
    svg.text(560, timeline_y + 40, "and B at 1.0", size=12, fill=INK_SOFT,
             anchor="middle")
    svg.text(40, 196, "w <- clip(w + eta * modulation * eligibility):",
             size=13, fill=INK_SOFT)
    svg.text(40, 216, "the late reward still finds A's smaller trace, and "
             "also credits B's --", size=13, fill=INK_SOFT)
    svg.text(40, 236, "the intentional interference lesson 13 measures "
             "instead of hiding", size=13, fill=INK_SOFT)
    svg.text(40, 272, "shadow selections lay no trace and tick no clock; "
             "an unexecuted selection leaves only a decaying trace", size=12,
             fill=INK_MUTED)
    svg.text(40, height - 16, "numbers here are the lesson's toy "
             "constants, not measurements", size=12, fill=INK_MUTED)
    return svg.render()


def graph_hop_inset(_data=None):
    """Lesson 14: one propagation hop over a handful of nodes."""
    accent = "#52c78d"
    warn = "#d95926"
    width, height = 720, 348
    svg = Svg(width, height,
              "One graph hop, six nodes",
              "Two input nodes start active; one hop propagates activation "
              "along weighted association edges; the top-k most activated "
              "nodes form the active set the fixed readout scores. The "
              "edges that joined active nodes are the eligible ones -- the "
              "only place this arm's learning applies.")
    svg.text(40, 36, "One hop, then top-k", size=19, fill=INK, weight="650")
    svg.text(40, 58, "the full topology figure is the evidence view; this "
                     "is the mechanism", size=13, fill=INK_SOFT)
    nodes = {"a": (140, 130), "b": (140, 230), "c": (320, 100),
             "d": (320, 180), "e": (320, 260), "f": (500, 180)}
    edges = [("a", "c", "0.9"), ("a", "d", "0.4"), ("b", "d", "0.7"),
             ("b", "e", "0.2"), ("d", "f", "0.6"), ("c", "f", "0.3")]
    for src, dst, w in edges:
        (x1, y1), (x2, y2) = nodes[src], nodes[dst]
        eligible = src in ("a", "b") and dst in ("c", "d")
        svg.line(x1, y1, x2, y2, accent if eligible else INK_MUTED,
                 2 if eligible else 1.2)
        svg.text((x1 + x2) / 2, (y1 + y2) / 2 - 6, w, size=12,
                 fill=INK_SOFT, anchor="middle")
    active = {"a", "b", "c", "d"}
    for name, (x, y) in nodes.items():
        svg.circle(x, y, 15, SURFACE, stroke=accent if name in active
                   else INK_MUTED, stroke_width=2)
        svg.text(x, y + 4, name, size=13, fill=INK, anchor="middle",
                 weight="650")
    svg.text(140, 275, "inputs: a, b active", size=12, fill=INK_SOFT,
             anchor="middle")
    svg.text(320, 296, "after the hop: c and d join (top-k), e misses",
             size=12, fill=INK_SOFT, anchor="middle")
    svg.text(560, 150, "readout scores the", size=12, fill=INK_MUTED)
    svg.text(560, 166, "active set; edges", size=12, fill=INK_MUTED)
    svg.text(560, 182, "a-c, a-d, b-d are", size=12, fill=INK_MUTED)
    svg.text(560, 198, "eligible to learn", size=12, fill=INK_MUTED)
    svg.text(40, height - 34, "toy weights for the walkthrough; this arm "
             "learns association edges under a fixed", size=12, fill=INK_MUTED)
    svg.text(40, height - 16, "readout -- a different family from readout "
             "plasticity", size=12, fill=INK_MUTED)
    return svg.render()


FIGURES = {
    "compare-steady-families.svg": (
        "compare-steady-families.json", comparison_figure),
    "compare-drifting-signal.svg": (
        "compare-drifting-signal.json", comparison_figure),
    "linucb-lesson-scores.svg": (
        "linucb-trace.json", linucb_scores_figure),
    "linucb-lesson-decomposition.svg": (
        "linucb-trace.json", linucb_decomposition_figure),
    "verification-sequence.svg": (None, verification_sequence_figure),
    "candidate-to-feedback.svg": (None, candidate_feedback_figure),
    "graph-topology.svg": ("graph-toy.json", graph_topology_figure),
    "research-summary.svg": ("research-summary.json", research_summary_figure),
    "run-sequence.svg": (None, run_sequence_figure),
    "build-path.svg": (None, build_path_figure),
    "stage-mapping.svg": (None, stage_mapping_figure),
    "write-boundary.svg": (None, write_boundary_figure),
    "mb-lesson-activation.svg": ("mb-trace.json", mb_activation_figure),
    "mb-lesson-signal-breakdown.svg": (
        "mb-trace.json", mb_signal_breakdown_figure),
    "plasticity-lesson-ledger.svg": (
        "plasticity-trace.json", plasticity_ledger_figure),
    "retrieval-pipeline.svg": (None, retrieval_pipeline_figure),
    "context-assembly.svg": (None, context_assembly_figure),
    "proposal-sequence.svg": (None, proposal_sequence_figure),
    "dispatch-door.svg": (None, dispatch_door_figure),
    "lifecycle-states.svg": (None, lifecycle_states_figure),
    "assembled-app.svg": (None, assembled_app_figure),
    "sparse-encoding.svg": (None, sparse_encoding_inset),
    "delayed-credit.svg": (None, delayed_credit_inset),
    "graph-hop.svg": (None, graph_hop_inset),
}


def render_all():
    out = {}
    for name, (source, figure) in FIGURES.items():
        data = None
        if source is not None:
            data = json.loads((COURSE / source).read_text(encoding="utf-8"))
        out[name] = figure(data)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in render_all().items():
        (OUT / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"docs/assets/course/{name}")


if __name__ == "__main__":
    main()
