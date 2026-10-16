"""Build the Cricket Care troubleshooting agent architecture from one layout model.

    python3 build.py                                  # architecture.html and architecture.drawio
    python3 build.py --slides icon-urls.json          # also slides-requests.json for the Slides API

Every element sits on a 1920 x 1080 grid. The same coordinates drive the HTML page, the draw.io file and
the Google Slides build (see slides.py), so the three never drift apart.
"""
import argparse
import base64
import html
import itertools
import json
import pathlib
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

HERE = pathlib.Path(__file__).resolve().parent
TITLE = "Cricket Care Troubleshooting Agent"

# ---- Palette (light). The HTML page also defines a dark variant. ---------------------------------
C = dict(stage="#ffffff", ink="#1f2430", muted="#5b6474", line="#d5dbe5", blue="#1a73e8", blue_soft="#e8f0fe",
         gcp_fill="#f8fafd", cricket_fill="#f3f7ef", cricket_line="#b9cfa3", pipe_fill="#f1f8f3",
         pipe_line="#a8d5b5", third_fill="#f6f6f7", planned="#9aa3b2", content="#188038", image="#e37400",
         tip="#8a93a3")

EDGE = {  # kind -> (color, dash for drawio, dash for Slides)
    "live": (C["blue"], None, "SOLID"),
    "content": (C["content"], "7 6", "DASH"),
    "planned": (C["planned"], "3 5", "DOT"),
    "image": (C["image"], "2 5", "DOT"),
}


# ---- Layout model ----------------------------------------------------------------------------------
@dataclass
class Frame:
    x: int; y: int; w: int; h: int; label: str = ""; icon: str = ""; kind: str = "gcp"


@dataclass
class Box:
    x: int; y: int; w: int; h: int; icon: str; title: str; sub: str = ""; kind: str = ""
    tags: list = field(default_factory=list)


@dataclass
class Edge:
    pts: list; kind: str = "live"; both: bool = False


@dataclass
class Label:
    x: int; y: int; text: str; kind: str = "small"   # x is the centre


FRAMES = [
    Frame(500, 150, 1090, 570, "Google Cloud", "cloud", "gcp"),
    Frame(520, 190, 500, 510, "", "", "ces"),
    Frame(1620, 150, 260, 570, "Cricket", "list", "cricket"),
    Frame(40, 770, 1840, 270, "Content pipeline · offline", "code", "pipeline"),
    Frame(340, 815, 1000, 185, "Pipeline job · Cloud Run · weekly via Cloud Scheduler", "cloud-run", "job"),
]

PANEL = dict(x=540, y=206, icon="contact-center-ai", title="Gemini Enterprise for CX", sub="CX Agent Studio app")

PY, PH = 845, 130
BOXES = [
    Box(40, 330, 180, 100, "person", "Customer"),
    Box(245, 320, 195, 120, "headset-grey", "Cricket IVR", "VAIL", "third"),
    Box(245, 490, 195, 120, "chat", "Chat UI", "Demo web app + relay", "third"),
    Box(540, 290, 460, 90, "agents", "Care Concierge", "Root agent"),
    Box(540, 440, 220, 100, "agents", "Billing", "Sub-agent", "planned"),
    Box(780, 440, 220, 100, "agents", "Tech Support", "Sub-agent", "focus"),
    Box(540, 590, 460, 80, "gemini", "Gemini Live", "Native-audio model", "model"),
    Box(1100, 200, 460, 210, "cloud-run", "MCP server", "Cloud Run · stateless", "",
        ["Tutorial tools · checkpoint", "Account and network tools", "SMS and ticket tools"]),
    Box(1100, 470, 220, 110, "vertex-ai", "Agent Search", "Data store"),
    Box(1340, 470, 220, 110, "databases", "Tutorial store", "Firestore"),
    Box(1640, 200, 220, 140, "integration-services", "Cricket APIs", "Account · Network · Tickets"),
    Box(1640, 380, 220, 100, "chat", "SMS API"),
    Box(80, PY, 220, PH, "list", "Cricket support site", "or Ozmo content feed"),
    Box(360, PY, 225, PH, "code", "Fetch", "Headless browser · text + images"),
    Box(605, PY, 225, PH, "code", "Extract", "Tutorial data · step graph"),
    Box(850, PY, 225, PH, "check", "Validate", "Schema · branches"),
    Box(1095, PY, 225, PH, "gemini", "Enrich", "Gemini · safety flags"),
    Box(1380, PY, 180, PH, "cloud-storage", "Cloud Storage", "Content + step images"),
]

EDGES = [
    Edge([(220, 350), (245, 350)], "live", True),
    Edge([(440, 350), (540, 350)], "live", True),
    Edge([(125, 430), (125, 550), (245, 550)], "live", True),
    Edge([(440, 550), (480, 550), (480, 368), (540, 368)], "live", True),
    Edge([(890, 380), (890, 440)], "live"),
    Edge([(650, 380), (650, 440)], "planned"),
    Edge([(1000, 465), (1050, 465), (1050, 300), (1100, 300)], "live"),
    Edge([(1000, 525), (1100, 525)], "live"),
    Edge([(1210, 410), (1210, 470)], "live"),
    Edge([(1450, 410), (1450, 470)], "live"),
    Edge([(1560, 270), (1640, 270)], "live"),
    Edge([(1560, 380), (1600, 380), (1600, 430), (1640, 430)], "live"),
    *[Edge([(a, PY + PH // 2), (b, PY + PH // 2)], "content")
      for a, b in [(300, 360), (585, 605), (830, 850), (1075, 1095), (1320, 1380)]],
    Edge([(1490, PY), (1490, 580)], "content"),
    Edge([(1420, PY), (1420, 795), (1230, 795), (1230, 580)], "content"),
    Edge([(1470, 975), (1470, 1018), (322, 1018), (322, 610)], "image"),
]

LABELS = [
    Label(490, 316, "Bidi-SAC", "pill"),
    Label(1075, 280, "MCP"),
    Label(1050, 548, "data store tool"),
    Label(1210, 432, "find"),
    Label(1450, 432, "walk · progress"),
    Label(1600, 248, "REST"),
    Label(1230, 650, "import"),
    Label(1490, 650, "upsert"),
    Label(900, 1006, "step images, served to the chat UI by the relay"),
]

LEGEND = [("live", "Live call"), ("content", "Content pipeline"), ("image", "Step images")]
LEGEND_X, LEGEND_Y = 1180, 58

# Geometry shared by the draw.io and Slides renderers (the HTML page lays boxes out with CSS to the same metrics).
PAD_X, PAD_Y, ICON, GAP = 18, 16, 36, 12
TAG_TOP, TAG_H, TAG_GAP = 66, 37, 10


def label_size(lb):
    if lb.kind == "pill":
        return len(lb.text) * 7.5 + 40, 28
    return len(lb.text) * 8.4 + 22, 22


def legend_items():
    x, out = LEGEND_X, []
    for kind, text in LEGEND:
        out.append((kind, text, x))
        x += 44 + 8 + len(text) * 8.1 + 28
    return out


def svg_data(name):
    return base64.b64encode((HERE / "icons" / "svg" / f"{name}.svg").read_bytes()).decode()


# ---- HTML -------------------------------------------------------------------------------------------
def to_html():
    def img(n):
        return f'<img src="data:image/svg+xml;base64,{svg_data(n)}" alt="">'

    parts = []
    for f in FRAMES:
        lab = f'<div class="frame-label">{img(f.icon) if f.icon else ""}{html.escape(f.label)}</div>' if f.label else ""
        parts.append(f'<div class="frame {f.kind}" style="left:{f.x}px;top:{f.y}px;width:{f.w}px;height:{f.h}px">{lab}</div>')
    frames = "".join(parts)

    paths = []
    for e in EDGES:
        d = "M" + " L".join(f"{x},{y}" for x, y in e.pts)
        start = ' marker-start="url(#arrow-start)"' if e.both else ""
        paths.append(f'<path d="{d}" class="{e.kind}" marker-end="url(#arrow)"{start}/>')
    tip = f'<path d="M0,0 L10,5 L0,10 z" fill="{C["tip"]}"/>'
    wires = ('<svg class="wires" viewBox="0 0 1920 1080" width="1920" height="1080" aria-hidden="true"><defs>'
             f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">{tip}</marker>'
             '<marker id="arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" '
             f'orient="auto-start-reverse">{tip}</marker></defs>' + "".join(paths) + "</svg>")

    boxes = [f'<div class="panel-head" style="left:{PANEL["x"]}px;top:{PANEL["y"]}px">{img(PANEL["icon"])}'
             f'<div><span class="title">{PANEL["title"]}</span><span class="sub">{PANEL["sub"]}</span></div></div>']
    for b in BOXES:
        sub = f'<span class="sub">{html.escape(b.sub)}</span>' if b.sub else ""
        tags = ('<div class="tags">' + "".join(f"<span>{html.escape(t)}</span>" for t in b.tags) + "</div>") if b.tags else ""
        boxes.append(f'<div class="box {b.kind}" style="left:{b.x}px;top:{b.y}px;width:{b.w}px;height:{b.h}px">'
                     f'<div class="head">{img(b.icon)}<div><span class="title">{html.escape(b.title)}</span>{sub}</div></div>'
                     f"{tags}</div>")
    labels = "".join(f'<div class="label {lb.kind}" style="left:{lb.x}px;top:{lb.y}px">{html.escape(lb.text)}</div>'
                     for lb in LABELS)
    legend = ('<div class="legend" style="left:%dpx;top:%dpx">' % (LEGEND_X, LEGEND_Y) + "".join(
        f'<span><svg width="44" height="10"><path d="M2,5 L42,5" class="{k}"/></svg>{t}</span>' for k, t in LEGEND) + "</div>")

    return f"""<title>Cricket Care Agent Architecture</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap">
<style>{CSS}</style>
<div class="wrap"><div class="fit"><div class="stage">
<h1>{TITLE}</h1>
{legend}
{frames}
{wires}
{''.join(boxes)}
{labels}
</div></div></div>
<script>{JS}</script>
"""


CSS = """
/* Layout: one 1920 x 1080 slide grid scaled to the viewport. Runtime across the top, offline content pipeline along the bottom. */
:root {
  --bg: #f4f6fa; --stage: #ffffff; --ink: #1f2430; --muted: #5b6474; --line: #d5dbe5;
  --blue: #1a73e8; --blue-soft: #e8f0fe; --gcp-fill: #f8fafd; --cricket-fill: #f3f7ef; --cricket-line: #b9cfa3;
  --pipe-fill: #f1f8f3; --pipe-line: #a8d5b5; --third-fill: #f6f6f7; --planned: #9aa3b2; --content: #188038;
  --image: #e37400;
  --font-display: "Google Sans", "Product Sans", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-body: Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f131a; --stage: #161b24; --ink: #e6e9ef; --muted: #a3acbb; --line: #2c3442;
  --blue: #8ab4f8; --blue-soft: #1d2a40; --gcp-fill: #1a2029; --cricket-fill: #19211a; --cricket-line: #3f5a35;
  --pipe-fill: #16211b; --pipe-line: #2f5a3d; --third-fill: #1d2129; --planned: #6b7484; --content: #81c995;
  --image: #fcad70; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f131a; --stage: #161b24; --ink: #e6e9ef; --muted: #a3acbb; --line: #2c3442;
  --blue: #8ab4f8; --blue-soft: #1d2a40; --gcp-fill: #1a2029; --cricket-fill: #19211a; --cricket-line: #3f5a35;
  --pipe-fill: #16211b; --pipe-line: #2f5a3d; --third-fill: #1d2129; --planned: #6b7484; --content: #81c995;
  --image: #fcad70; color-scheme: dark; }
body { background: var(--bg); color: var(--ink); font-family: var(--font-body); }
.wrap { padding-block: 24px; padding-inline: 16px; overflow-x: hidden; }
.fit { width: 100%; max-width: 1920px; margin: 0 auto; position: relative; }
.stage { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; transform-origin: 0 0;
  background: var(--stage); border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow: hidden; }
.stage > * { position: absolute; }
h1 { left: 40px; top: 44px; margin: 0; font: 500 40px/1.15 var(--font-display); letter-spacing: -0.01em; }
.frame { border: 1.5px solid var(--line); border-radius: 4px; background: var(--gcp-fill); box-sizing: border-box; }
.frame.cricket { background: var(--cricket-fill); border-color: var(--cricket-line); }
.frame.pipeline { background: var(--pipe-fill); border-color: var(--pipe-line); }
.frame.job { background: transparent; border: 1.5px dashed var(--pipe-line); }
.frame.ces { background: var(--blue-soft); border-color: transparent; }
.frame-label { position: absolute; left: 16px; top: -14px; padding: 2px 10px; background: var(--stage);
  font: 500 17px/1.4 var(--font-display); color: var(--muted); display: flex; align-items: center; gap: 8px; letter-spacing: .02em; }
.frame.job .frame-label { background: var(--pipe-fill); font-size: 15px; }
.frame-label img { width: 22px; height: 22px; }
.panel-head { display: flex; gap: 12px; align-items: center; }
.panel-head img { width: 40px; height: 40px; }
.panel-head .title { display: block; font: 500 21px/1.25 var(--font-display); }
.panel-head .sub { display: block; font: 400 15px/1.35 var(--font-body); color: var(--muted); }
.box { background: var(--stage); border: 1.5px solid var(--line); border-radius: 10px; padding: 16px 18px;
  box-sizing: border-box; display: flex; flex-direction: column; gap: 14px; }
.box.focus { border-color: var(--blue); border-width: 2px; }
.box.planned { border-style: dashed; border-color: var(--planned); }
.box.planned .title { color: var(--muted); }
.box.third { background: var(--third-fill); }
.box.model { justify-content: center; }
.head { display: flex; gap: 12px; align-items: flex-start; }
.head img { width: 36px; height: 36px; flex: none; }
.head .title { display: block; font: 500 19px/1.25 var(--font-display); }
.head .sub { display: block; font: 400 15px/1.35 var(--font-body); color: var(--muted); }
.tags { display: grid; gap: 10px; }
.tags span { font: 500 15.5px/1 var(--font-display); color: var(--blue); background: var(--blue-soft); padding: 11px 14px; border-radius: 8px; }
.wires { left: 0; top: 0; pointer-events: none; }
.wires > path { fill: none; stroke-width: 2.25; }
.wires .live, .legend .live { stroke: var(--blue); }
.wires .content, .legend .content { stroke: var(--content); stroke-dasharray: 7 6; }
.wires .planned, .legend .planned { stroke: var(--planned); stroke-dasharray: 3 5; }
.wires .image, .legend .image { stroke: var(--image); stroke-dasharray: 2 5; stroke-linecap: round; }
.legend path { fill: none; stroke-width: 2.25; }
.label { transform: translateX(-50%); white-space: nowrap; font: 400 14px/1.2 var(--font-body); color: var(--muted);
  background: var(--stage); padding: 2px 6px; border-radius: 4px; }
.label.pill { font: 500 14px/1 var(--font-display); color: var(--blue); border: 1.5px solid var(--blue); border-radius: 999px; padding: 5px 12px; }
.legend { display: flex; gap: 28px; font: 400 15px/1 var(--font-body); color: var(--muted); }
.legend span { display: flex; align-items: center; gap: 8px; }
"""

JS = """
(function () {
  var fit = document.querySelector('.fit'), stage = document.querySelector('.stage');
  function size() { var s = fit.clientWidth / 1920; stage.style.transform = 'scale(' + s + ')'; fit.style.height = (1080 * s) + 'px'; }
  window.addEventListener('resize', size); size();
})();
"""


# ---- Box metrics shared by draw.io and Slides ---------------------------------------------------------
def box_parts(b):
    """Icon square and text block for a box, in grid px."""
    if b.kind == "model":
        iy = b.y + (b.h - ICON) / 2
        ty = b.y + (b.h - 44) / 2
    else:
        iy, ty = b.y + PAD_Y, b.y + PAD_Y - 2
    icon = (b.x + PAD_X, iy, ICON)
    text = (b.x + PAD_X + ICON + GAP, ty, b.w - (PAD_X + ICON + GAP) - 4, 48)
    tags = [(b.x + PAD_X, b.y + TAG_TOP + i * (TAG_H + TAG_GAP), b.w - 2 * PAD_X, TAG_H, t) for i, t in enumerate(b.tags)]
    return icon, text, tags


def box_style(b):
    fill = C["third_fill"] if b.kind == "third" else C["stage"]
    stroke = {"focus": C["blue"], "planned": C["planned"]}.get(b.kind, C["line"])
    width = 2 if b.kind == "focus" else 1.5
    return fill, stroke, width, b.kind == "planned"


def frame_style(f):
    return {
        "gcp": (C["gcp_fill"], C["line"], False),
        "ces": (C["blue_soft"], None, False),
        "cricket": (C["cricket_fill"], C["cricket_line"], False),
        "pipeline": (C["pipe_fill"], C["pipe_line"], False),
        "job": (None, C["pipe_line"], True),
    }[f.kind]


def frame_label_box(f):
    size = 15 if f.kind == "job" else 17
    w = 10 + 22 + 8 + len(f.label) * size * 0.66 + 14
    return f.x + 16, f.y - 14, w, 28, size


# ---- draw.io --------------------------------------------------------------------------------------------
def to_drawio():
    ids = itertools.count(2)
    cells = []

    def cell(value, style, x, y, w, h):
        cells.append(f'<mxCell id="c{next(ids)}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/></mxCell>')

    def image(name, x, y, s):
        cell("", f"shape=image;aspect=fixed;imageAspect=1;image=data:image/svg+xml,{svg_data(name)};", x, y, s, s)

    font = "fontFamily=Google Sans,Roboto,Helvetica,Arial,sans-serif;"
    for f in FRAMES:
        fill, stroke, dashed = frame_style(f)
        cell("", f"rounded=0;html=1;fillColor={fill or 'none'};strokeColor={stroke or 'none'};strokeWidth=1.5;"
                 f"{'dashed=1;' if dashed else ''}", f.x, f.y, f.w, f.h)
        if f.label:
            x, y, w, h, size = frame_label_box(f)
            bg = C["pipe_fill"] if f.kind == "job" else C["stage"]
            cell("", f"rounded=0;fillColor={bg};strokeColor=none;", x, y, w, h)
            image(f.icon, x + 10, y + 3, 22)
            cell(f.label, f"text;html=1;{font}fontSize={size};fontColor={C['muted']};align=left;verticalAlign=middle;"
                          f"fontStyle=1;", x + 40, y, w - 40, h)

    image(PANEL["icon"], PANEL["x"], PANEL["y"] + 3, 40)
    cell(f'<b>{PANEL["title"]}</b><br><font style="font-size:15px" color="{C["muted"]}">{PANEL["sub"]}</font>',
         f"text;html=1;{font}fontSize=21;fontColor={C['ink']};align=left;verticalAlign=top;whiteSpace=wrap;",
         PANEL["x"] + 52, PANEL["y"], 400, 50)

    for b in BOXES:
        fill, stroke, width, dashed = box_style(b)
        cell("", f"rounded=1;arcSize=8;absoluteArcSize=0;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={width};"
                 f"{'dashed=1;' if dashed else ''}", b.x, b.y, b.w, b.h)
        (ix, iy, isz), (tx, ty, tw, th), tags = box_parts(b)
        image(b.icon, ix, iy, isz)
        tcol = C["muted"] if b.kind == "planned" else C["ink"]
        sub = f'<br><font style="font-size:15px" color="{C["muted"]}">{html.escape(b.sub)}</font>' if b.sub else ""
        cell(f"<b>{html.escape(b.title)}</b>{sub}",
             f"text;html=1;{font}fontSize=19;fontColor={tcol};align=left;verticalAlign=top;whiteSpace=wrap;spacing=0;",
             tx, ty, tw, th)
        for (x, y, w, h, t) in tags:
            cell(t, f"rounded=1;arcSize=20;html=1;{font}fontSize=15;fontStyle=1;fillColor={C['blue_soft']};strokeColor=none;"
                    f"fontColor={C['blue']};align=left;spacingLeft=14;", x, y, w, h)

    for e in EDGES:
        color, dash, _ = EDGE[e.kind]
        style = (f"edgeStyle=none;html=1;rounded=0;strokeColor={color};strokeWidth=2.25;endArrow=block;endFill=1;"
                 f"{'startArrow=block;startFill=1;' if e.both else 'startArrow=none;'}"
                 f"{'dashed=1;dashPattern=' + dash + ';' if dash else ''}")
        (sx, sy), (tx, ty) = e.pts[0], e.pts[-1]
        mids = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in e.pts[1:-1])
        arr = f'<Array as="points">{mids}</Array>' if mids else ""
        cells.append(f'<mxCell id="c{next(ids)}" style="{style}" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                     f'<mxPoint x="{sx}" y="{sy}" as="sourcePoint"/><mxPoint x="{tx}" y="{ty}" as="targetPoint"/>{arr}'
                     f"</mxGeometry></mxCell>")

    for lb in LABELS:
        w, h = label_size(lb)
        if lb.kind == "pill":
            cell(lb.text, f"rounded=1;arcSize=50;html=1;{font}fontSize=14;fontStyle=1;fontColor={C['blue']};"
                          f"fillColor={C['stage']};strokeColor={C['blue']};strokeWidth=1.5;", lb.x - w / 2, lb.y, w, h)
        else:
            cell(lb.text, f"text;html=1;{font}fontSize=14;fontColor={C['muted']};align=center;verticalAlign=middle;"
                          f"fillColor={C['stage']};", lb.x - w / 2, lb.y, w, h)

    cell(TITLE, f"text;html=1;{font}fontSize=40;fontColor={C['ink']};align=left;verticalAlign=top;", 40, 40, 900, 56)
    for kind, text, x in legend_items():
        color, dash, _ = EDGE[kind]
        cells.append(f'<mxCell id="c{next(ids)}" style="endArrow=none;html=1;strokeColor={color};strokeWidth=2.25;'
                     f'{"dashed=1;dashPattern=" + dash + ";" if dash else ""}" edge="1" parent="1">'
                     f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x}" y="{LEGEND_Y + 8}" as="sourcePoint"/>'
                     f'<mxPoint x="{x + 44}" y="{LEGEND_Y + 8}" as="targetPoint"/></mxGeometry></mxCell>')
        cell(text, f"text;html=1;{font}fontSize=15;fontColor={C['muted']};align=left;verticalAlign=middle;",
             x + 52, LEGEND_Y - 4, len(text) * 8.1 + 10, 24)

    return ('<mxfile host="app.diagrams.net"><diagram id="architecture" name="Architecture">'
            '<mxGraphModel dx="1920" dy="1080" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
            'fold="1" page="1" pageScale="1" pageWidth="1920" pageHeight="1080" background="#ffffff" math="0" shadow="0">'
            '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")


# ---- Google Slides batchUpdate -----------------------------------------------------------------------------
EMU = 9144000 / 1920
INSET = 7    # Slides keeps a 0.1 in text inset that the API cannot change; text boxes are grown by it
PT = 0.375 * 0.94   # 1 px on the 1920 grid in points, less ~6% because Google Sans sets wider in Slides


def rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def to_slides(icon_urls):
    R, ids = [], itertools.count(1)
    sid = "arch_slide"
    R.append({"createSlide": {"objectId": sid, "slideLayoutReference": {"predefinedLayout": "BLANK"}}})

    def oid(p="o"):
        return f"{p}{next(ids):04d}"

    def geom(x, y, w, h):
        return {"pageObjectId": sid, "size": {"width": {"magnitude": max(w, 1) * EMU, "unit": "EMU"},
                                              "height": {"magnitude": max(h, 1) * EMU, "unit": "EMU"}},
                "transform": {"scaleX": 1, "scaleY": 1, "translateX": x * EMU, "translateY": y * EMU, "unit": "EMU"}}

    def shape(x, y, w, h, fill=None, stroke=None, sw=1.5, dash=None, kind="RECTANGLE"):
        s = oid()
        R.append({"createShape": {"objectId": s, "shapeType": kind, "elementProperties": geom(x, y, w, h)}})
        props = {"shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": rgb(fill)}}} if fill else {"propertyState": "NOT_RENDERED"},
                 "outline": ({"outlineFill": {"solidFill": {"color": {"rgbColor": rgb(stroke)}}},
                              "weight": {"magnitude": sw * EMU, "unit": "EMU"}, "dashStyle": dash or "SOLID"}
                             if stroke else {"propertyState": "NOT_RENDERED"})}
        R.append({"updateShapeProperties": {"objectId": s, "shapeProperties": props, "fields": "shapeBackgroundFill,outline"}})
        return s

    def text(x, y, w, h, runs, align="START", valign="TOP", box=None):
        """runs: list of (text, size_px, color, bold). Lines are separate runs joined by newlines."""
        t = box or shape(x - INSET, y - INSET, w + 2 * INSET, h + 2 * INSET, kind="TEXT_BOX")
        full = "\n".join(r[0] for r in runs)
        R.append({"insertText": {"objectId": t, "text": full}})
        pos = 0
        for (s, size, color, bold) in runs:
            R.append({"updateTextStyle": {"objectId": t, "textRange": {"type": "FIXED_RANGE", "startIndex": pos, "endIndex": pos + len(s)},
                                          "fields": "foregroundColor,fontSize,bold,fontFamily",
                                          "style": {"foregroundColor": {"opaqueColor": {"rgbColor": rgb(color)}},
                                                    "fontSize": {"magnitude": round(size * PT, 1), "unit": "PT"},
                                                    "bold": bold, "fontFamily": "Google Sans"}}})
            pos += len(s) + 1
        R.append({"updateParagraphStyle": {"objectId": t, "textRange": {"type": "ALL"},
                                           "fields": "alignment,spaceAbove,spaceBelow,lineSpacing",
                                           "style": {"alignment": align, "spaceAbove": {"magnitude": 0, "unit": "PT"},
                                                     "spaceBelow": {"magnitude": 0, "unit": "PT"}, "lineSpacing": 100}}})
        R.append({"updateShapeProperties": {"objectId": t, "fields": "contentAlignment,autofit.autofitType",
                                            "shapeProperties": {"contentAlignment": valign, "autofit": {"autofitType": "NONE"}}}})
        return t

    def image(name, x, y, s):
        R.append({"createImage": {"url": icon_urls[name], "elementProperties": geom(x, y, s, s)}})

    def line(x1, y1, x2, y2, color, dash, start=False, end=False):
        l = oid("l")
        R.append({"createLine": {"objectId": l, "lineCategory": "STRAIGHT", "elementProperties": {
            **geom(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)),
            "transform": {"scaleX": 1 if x2 >= x1 else -1, "scaleY": 1 if y2 >= y1 else -1,
                          "translateX": x1 * EMU, "translateY": y1 * EMU, "unit": "EMU"}}}})
        R.append({"updateLineProperties": {"objectId": l, "fields": "lineFill,weight,dashStyle,startArrow,endArrow", "lineProperties": {
            "lineFill": {"solidFill": {"color": {"rgbColor": rgb(color)}}}, "weight": {"magnitude": 2.25 * EMU, "unit": "EMU"},
            "dashStyle": dash, "startArrow": "FILL_ARROW" if start else "NONE", "endArrow": "FILL_ARROW" if end else "NONE"}}})

    R.append({"updatePageProperties": {"objectId": sid, "fields": "pageBackgroundFill",
                                       "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": rgb(C["stage"])}}}}}})
    text(40, 40, 1000, 56, [(TITLE, 40, C["ink"], False)])

    for f in FRAMES:
        fill, stroke, dashed = frame_style(f)
        shape(f.x, f.y, f.w, f.h, fill, stroke, 1.5, "DASH" if dashed else None)
    for f in FRAMES:
        if f.label:
            x, y, w, h, size = frame_label_box(f)
            shape(x, y, w, h, C["pipe_fill"] if f.kind == "job" else C["stage"])
            image(f.icon, x + 10, y + 3, 22)
            text(x + 40, y, w - 40, h, [(f.label, size, C["muted"], True)], valign="MIDDLE")

    for e in EDGES:   # edges under boxes, as in the page
        color, _, dash = EDGE[e.kind]
        n = len(e.pts) - 1
        for i in range(n):
            (x1, y1), (x2, y2) = e.pts[i], e.pts[i + 1]
            line(x1, y1, x2, y2, color, dash, start=e.both and i == 0, end=i == n - 1)

    image(PANEL["icon"], PANEL["x"], PANEL["y"] + 3, 40)
    text(PANEL["x"] + 52, PANEL["y"], 420, 50, [(PANEL["title"], 21, C["ink"], True), (PANEL["sub"], 15, C["muted"], False)])

    for b in BOXES:
        fill, stroke, width, dashed = box_style(b)
        shape(b.x, b.y, b.w, b.h, fill, stroke, width, "DASH" if dashed else None, kind="ROUND_RECTANGLE")
        (ix, iy, isz), (tx, ty, tw, th), tags = box_parts(b)
        image(b.icon, ix, iy, isz)
        tcol = C["muted"] if b.kind == "planned" else C["ink"]
        runs = [(b.title, 19, tcol, True)] + ([(b.sub, 15, C["muted"], False)] if b.sub else [])
        text(tx, ty, tw, th, runs)
        for (x, y, w, h, t) in tags:
            shape(x, y, w, h, C["blue_soft"], kind="ROUND_RECTANGLE")
            text(x + 14, y, w - 28, h, [(t, 15.5, C["blue"], True)], valign="MIDDLE")

    for lb in LABELS:
        w, h = label_size(lb)
        if lb.kind == "pill":
            box = shape(lb.x - w / 2, lb.y, w, h, C["stage"], C["blue"], 1.5, kind="ROUND_RECTANGLE")
            text(0, 0, 0, 0, [(lb.text, 14, C["blue"], True)], align="CENTER", valign="MIDDLE", box=box)
        else:
            shape(lb.x - w / 2, lb.y, w, h, C["stage"])
            tw = max(w, 90)   # Slides crushes text in frames under ~70 px; the frame is wider than its background
            text(lb.x - tw / 2, lb.y, tw, h, [(lb.text, 14, C["muted"], False)], align="CENTER", valign="MIDDLE")

    for kind, label, x in legend_items():
        color, _, dash = EDGE[kind]
        line(x, LEGEND_Y + 8, x + 44, LEGEND_Y + 8, color, dash)
        text(x + 52, LEGEND_Y - 4, len(label) * 8.1 + 16, 24, [(label, 15, C["muted"], False)], valign="MIDDLE")
    return {"requests": R}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slides", metavar="ICON_URLS_JSON", help="also write slides-requests.json using these icon URLs")
    a = ap.parse_args()
    (HERE / "architecture.html").write_text(to_html())
    (HERE / "architecture.drawio").write_text(to_drawio())
    print("wrote architecture.html, architecture.drawio")
    if a.slides:
        urls = json.loads(pathlib.Path(a.slides).read_text())
        (HERE / "slides-requests.json").write_text(json.dumps(to_slides(urls)))
        print("wrote slides-requests.json")


if __name__ == "__main__":
    main()
