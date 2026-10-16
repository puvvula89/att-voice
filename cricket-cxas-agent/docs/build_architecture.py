"""Build architecture.html, the architecture of the Cricket Care troubleshooting agent.

    python3 build_architecture.py            # writes architecture.html next to this file

Every box sits on a 1920 x 1080 grid so the same coordinates can be reused for a slide. Icons are read
from icons/ and embedded as data URIs, so the page is a single self-contained file.
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def icon(name: str) -> str:
    data = base64.b64encode((HERE / "icons" / f"{name}.svg").read_bytes()).decode()
    return f"data:image/svg+xml;base64,{data}"


def box(x, y, w, h, ic, title, sub="", extra="", cls=""):
    s = f'<span class="sub">{sub}</span>' if sub else ""
    return (f'<div class="box {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            f'<div class="head"><img src="{icon(ic)}" alt=""><div><span class="title">{title}</span>{s}'
            f"</div></div>{extra}</div>")


def frame(x, y, w, h, text, ic=None, cls=""):
    img = f'<img src="{icon(ic)}" alt="">' if ic else ""
    return (f'<div class="frame {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            f'<div class="frame-label">{img}{text}</div></div>')


def tags(*items):
    return '<div class="tags">' + "".join(f"<span>{t}</span>" for t in items) + "</div>"


def label(x, y, text, cls=""):
    return f'<div class="label {cls}" style="left:{x}px;top:{y}px">{text}</div>'


def path(points, cls="", both=False):
    d = "M" + " L".join(f"{x},{y}" for x, y in points)
    start = ' marker-start="url(#arrow-start)"' if both else ""
    return f'<path d="{d}" class="{cls}" marker-end="url(#arrow)"{start}/>'


F, B, A, L = [], [], [], []   # frames, boxes, arrows, arrow labels (paint order: F, A, B, L)

# ---- Runtime: the live call --------------------------------------------------------------------
F.append(frame(500, 150, 1090, 570, "Google Cloud", "cloud"))
F.append(frame(520, 190, 500, 510, "", cls="ces"))
F.append(frame(1620, 150, 260, 570, "Cricket", "list", "cricket"))

B.append(box(40, 330, 170, 100, "person", "Customer"))
B.append(box(245, 320, 185, 120, "headset-grey", "Cricket IVR", "VAIL", cls="third"))

B.append(f'<div class="panel-head" style="left:540px;top:206px">'
         f'<img src="{icon("contact-center-ai")}" alt="">'
         f'<div><span class="title">Gemini Enterprise for CX</span>'
         f'<span class="sub">CX Agent Studio app</span></div></div>')
B.append(box(540, 290, 460, 90, "agents", "Care Concierge", "Root agent"))
B.append(box(540, 440, 220, 100, "agents", "Billing", "Sub-agent · next", cls="planned"))
B.append(box(780, 440, 220, 100, "agents", "Tech Support", "Sub-agent", cls="focus"))
B.append(box(540, 590, 460, 80, "gemini", "Gemini Live", "Native-audio model", cls="model"))

B.append(box(1100, 200, 460, 210, "cloud-run", "MCP server", "Cloud Run · stateless",
             tags("Tutorial tools · checkpoint", "Account and network tools", "SMS and ticket tools")))
B.append(box(1100, 470, 220, 110, "vertex-ai", "Search", "Vertex AI Search"))
B.append(box(1340, 470, 220, 110, "databases", "Tutorial store", "Firestore"))

B.append(box(1640, 200, 220, 140, "integration-services", "Cricket APIs", "Account · Network · Tickets"))
B.append(box(1640, 380, 220, 100, "chat", "SMS API"))

A.append(path([(210, 380), (245, 380)], "live", both=True))
A.append(path([(430, 380), (540, 380)], "live", both=True))
A.append(path([(890, 380), (890, 440)], "live"))
A.append(path([(650, 380), (650, 440)], "planned"))
A.append(path([(1000, 465), (1050, 465), (1050, 300), (1100, 300)], "live"))
A.append(path([(1000, 525), (1100, 525)], "live"))
A.append(path([(1210, 410), (1210, 470)], "live"))
A.append(path([(1450, 410), (1450, 470)], "live"))
A.append(path([(1560, 270), (1640, 270)], "live"))
A.append(path([(1560, 380), (1600, 380), (1600, 430), (1640, 430)], "live"))

L.append(label(476, 346, "Bidi-SAC", "pill"))
L.append(label(1075, 280, "MCP", "small"))
L.append(label(1050, 548, "data store tool", "small"))
L.append(label(1210, 432, "find", "small"))
L.append(label(1450, 432, "walk", "small"))
L.append(label(1600, 248, "REST", "small"))

# ---- Content pipeline: offline, along the bottom -------------------------------------------------
F.append(frame(40, 770, 1840, 270, "Content pipeline · offline", "code", "pipeline"))
F.append(frame(340, 815, 1000, 185, "Pipeline job · Cloud Run · weekly via Cloud Scheduler", "cloud-run", "job"))
Y, H = 845, 130
B.append(box(80, Y, 220, H, "list", "Cricket support site", "or Ozmo content feed"))
B.append(box(360, Y, 225, H, "code", "Fetch", "Headless browser"))
B.append(box(605, Y, 225, H, "code", "Extract", "Tutorial data · step graph"))
B.append(box(850, Y, 225, H, "check", "Validate", "Schema · branches"))
B.append(box(1095, Y, 225, H, "gemini", "Enrich", "Gemini · safety flags"))
B.append(box(1380, Y, 180, H, "cloud-storage", "Cloud Storage", "Raw + normalized"))

for x1, x2 in [(300, 360), (585, 605), (830, 850), (1075, 1095), (1320, 1380)]:
    A.append(path([(x1, Y + H // 2), (x2, Y + H // 2)], "content"))
A.append(path([(1490, Y), (1490, 580)], "content"))
A.append(path([(1420, Y), (1420, 795), (1230, 795), (1230, 580)], "content"))

L.append(label(1230, 735, "import", "small"))
L.append(label(1490, 735, "upsert", "small"))

LEGEND = (
    '<div class="legend" style="left:1180px;top:58px">'
    '<span><svg width="44" height="10"><path d="M2,5 L42,5" class="live"/></svg>Live call</span>'
    '<span><svg width="44" height="10"><path d="M2,5 L42,5" class="content"/></svg>Content pipeline</span>'
    '<span><svg width="44" height="10"><path d="M2,5 L42,5" class="planned"/></svg>Next use case</span>'
    '</div>'
)

ARROWS_SVG = (
    '<svg class="wires" viewBox="0 0 1920 1080" width="1920" height="1080" aria-hidden="true">'
    '<defs>'
    '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#8a93a3"/></marker>'
    '<marker id="arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" '
    'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8a93a3"/></marker>'
    '</defs>' + "".join(A) + "</svg>"
)

CSS = """
/* Layout: one 1920 x 1080 slide grid scaled to the viewport. Runtime across the top, offline content pipeline along the bottom. */
:root {
  --bg: #f4f6fa;
  --stage: #ffffff;
  --ink: #1f2430;
  --muted: #5b6474;
  --line: #d5dbe5;
  --blue: #1a73e8;
  --blue-soft: #e8f0fe;
  --gcp-fill: #f8fafd;
  --cricket-fill: #f3f7ef;
  --cricket-line: #b9cfa3;
  --pipe-fill: #f1f8f3;
  --pipe-line: #a8d5b5;
  --third-fill: #f6f6f7;
  --planned: #9aa3b2;
  --content: #188038;
  --font-display: "Google Sans", "Product Sans", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-body: Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f131a; --stage: #161b24; --ink: #e6e9ef; --muted: #a3acbb; --line: #2c3442;
  --blue: #8ab4f8; --blue-soft: #1d2a40; --gcp-fill: #1a2029; --cricket-fill: #19211a; --cricket-line: #3f5a35;
  --pipe-fill: #16211b; --pipe-line: #2f5a3d; --third-fill: #1d2129; --planned: #6b7484; --content: #81c995;
  color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f131a; --stage: #161b24; --ink: #e6e9ef; --muted: #a3acbb; --line: #2c3442;
  --blue: #8ab4f8; --blue-soft: #1d2a40; --gcp-fill: #1a2029; --cricket-fill: #19211a; --cricket-line: #3f5a35;
  --pipe-fill: #16211b; --pipe-line: #2f5a3d; --third-fill: #1d2129; --planned: #6b7484; --content: #81c995;
  color-scheme: dark; }
body { background: var(--bg); color: var(--ink); font-family: var(--font-body); }
.wrap { padding-block: 24px; padding-inline: 16px; overflow-x: hidden; }
.fit { width: 100%; max-width: 1920px; margin: 0 auto; position: relative; }
.stage { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; transform-origin: 0 0;
  background: var(--stage); border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow: hidden; }
.stage > * { position: absolute; }
h1 { position: absolute; left: 40px; top: 44px; margin: 0; font: 500 40px/1.15 var(--font-display);
  letter-spacing: -0.01em; text-wrap: balance; }
.frame { border: 1.5px solid var(--line); border-radius: 4px; background: var(--gcp-fill); box-sizing: border-box; }
.frame.cricket { background: var(--cricket-fill); border-color: var(--cricket-line); }
.frame.pipeline { background: var(--pipe-fill); border-color: var(--pipe-line); }
.frame.job { background: transparent; border: 1.5px dashed var(--pipe-line); }
.frame.job .frame-label { background: var(--pipe-fill); font-size: 15px; }
.frame.ces { background: var(--blue-soft); border-color: transparent; }
.frame.ces .frame-label { display: none; }
.frame-label { position: absolute; left: 16px; top: -14px; padding: 2px 10px; background: var(--stage);
  font: 500 17px/1.4 var(--font-display); color: var(--muted); display: flex; align-items: center; gap: 8px;
  letter-spacing: .02em; }
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
.tags span { font: 500 15.5px/1 var(--font-display); color: var(--blue); background: var(--blue-soft);
  padding: 11px 14px; border-radius: 8px; }
.wires { left: 0; top: 0; pointer-events: none; }
.wires > path { fill: none; stroke-width: 2.25; }
.wires .live, .legend .live { stroke: var(--blue); }
.wires .content, .legend .content { stroke: var(--content); stroke-dasharray: 7 6; }
.wires .planned, .legend .planned { stroke: var(--planned); stroke-dasharray: 3 5; }
.legend path { fill: none; stroke-width: 2.25; }
.label { transform: translateX(-50%); white-space: nowrap; font: 400 14px/1.2 var(--font-body); color: var(--muted);
  background: var(--stage); padding: 2px 6px; border-radius: 4px; }
.label.pill { font: 500 14px/1 var(--font-display); color: var(--blue); border: 1.5px solid var(--blue);
  border-radius: 999px; padding: 5px 12px; }
.legend { display: flex; gap: 28px; font: 400 15px/1 var(--font-body); color: var(--muted); }
.legend span { display: flex; align-items: center; gap: 8px; }
"""

JS = """
(function () {
  var fit = document.querySelector('.fit'), stage = document.querySelector('.stage');
  function size() {
    var s = fit.clientWidth / 1920;
    stage.style.transform = 'scale(' + s + ')';
    fit.style.height = (1080 * s) + 'px';
  }
  window.addEventListener('resize', size);
  size();
})();
"""

HTML = f"""<title>Cricket Care Agent Architecture</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap">
<style>{CSS}</style>
<div class="wrap"><div class="fit"><div class="stage">
<h1>Cricket Care Troubleshooting Agent</h1>
{LEGEND}
{''.join(F)}
{ARROWS_SVG}
{''.join(B)}
{''.join(L)}
</div></div></div>
<script>{JS}</script>
"""

if __name__ == "__main__":
    out = HERE / "architecture.html"
    out.write_text(HTML)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
