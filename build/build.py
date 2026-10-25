#!/usr/bin/env python3
"""
Profile README builder for github.com/koetsuji, built on Vercel's Geist
design system (colors, type scale, materials, grid).

    pip install fonttools brotli uharfbuzz
    python3 build/build.py

Writes <piece>-light.svg and <piece>-dark.svg into assets/. Every string is
shaped with HarfBuzz against the real Geist font files, so positions are
computed rather than guessed, then the fonts are subset to the glyphs each
SVG uses and embedded (GitHub's image proxy blocks external font requests).

Edit CONTENT and the project data below, then run the script again.
"""
from __future__ import annotations

import base64
import colorsys
import io
import math
import pathlib
import re
from collections import defaultdict
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools import subset as ftsubset
from fontTools.ttLib import TTFont
import logging

logging.getLogger("fontTools").setLevel(logging.ERROR)

HERE = pathlib.Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
OUT_DIR = HERE.parent / "assets"

# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------

CONTENT = {
    "headline": ["systems", "networks", "security"],
    "intro": "Hybrid infrastructure, identity, automation and small tools.",
    # The request path in the hero: a request crosses each layer in order.
    "path": [
        ("Identity", "IAM, Active Directory"),
        ("Network", "Routing, NAT, VPN"),
        ("Systems", "Windows, Linux, VMs"),
        ("Security", "Hardening, monitoring"),
    ],
    "section": "Selected work",
    "motto": "build quietly. document properly.",
    "status": "All systems normal",
}

BATTERY = {
    "title": "Windows Battery Report",
    "desc": [
        "Turns the built-in Windows battery report",
        "into a dashboard you can actually read.",
    ],
    "command": "powercfg /batteryreport",
    "language": "PowerShell",
    # Figures from the project's own dashboard screenshot.
    "health": 95.4,
    "rows": [("Design", "84,000 mWh"), ("Full charge", "80,110 mWh"), ("Cycles", "57")],
}

PALO = {
    "title": "Palo Rules Game",
    "desc": [
        "A browser game for practicing DNAT and SNAT.",
        "Read the ticket, build the rule, watch the packet.",
    ],
    "language": "React",
    # Level 1 and level 2 of the game.
    "snat": {"inside": "trust", "outside": "untrust", "before": "10.1.1.55", "after": "203.0.113.1"},
    "dnat": {"inside": "dmz", "outside": "untrust", "before": "203.0.113.1", "after": "192.168.50.5"},
}

WEATHER = {
    "title": "Weather App",
    "desc": [
        "A small, quiet interface for checking the",
        "weather, with city search and geolocation.",
    ],
    "language": "JavaScript",
    # The app's own screenshot.
    "temp": "20°",
    "condition": "Clear sky",
    "place": "Paris, FR",
    "stats": [("Humidity", "41%"), ("Wind", "13 km/h"), ("Feels like", "19°")],
}

# --------------------------------------------------------------------------
# Geist tokens (vercel.com/geist/colors; values from the geist-colors package)
# --------------------------------------------------------------------------


def _hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _over(fg: int, alpha: float, bg: str) -> str:
    """Flatten a gray-alpha token onto a solid background."""
    bg = bg.lstrip("#")
    ch = [round(alpha * fg + (1 - alpha) * int(bg[i : i + 2], 16)) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*ch)


GEIST = {
    "light": {
        "bg100": "#ffffff",
        "bg200": "#fafafa",
        "gray": [95, 92, 90, 92, 79, 66, 56, 49, 40, 9],
        "alpha_fg": 0,
        "alpha": [0.05, 0.08, 0.10, 0.08, 0.21, 0.34, 0.44, 0.51, 0.61, 0.91],
        "blue700": (212, 100, 48),
        "blue700_p3": "oklch(57.61% 0.2508 258.23)",
        "blue900": (211, 100, 42),
        "blue900_p3": "oklch(53.18% 0.2399 256.99)",
    },
    "dark": {
        "bg100": "#0a0a0a",
        "bg200": "#000000",
        "gray": [10, 12, 16, 18, 27, 53, 56, 49, 63, 93],
        "alpha_fg": 255,
        "alpha": [0.06, 0.09, 0.13, 0.14, 0.24, 0.51, 0.54, 0.47, 0.61, 0.92],
        "blue700": (212, 100, 48),
        "blue700_p3": "oklch(57.61% 0.2321 258.23)",
        "blue900": (210, 100, 66),
        "blue900_p3": "oklch(71.7% 0.1648 250.79)",
    },
}


def theme(mode: str) -> dict[str, str]:
    g = GEIST[mode]
    t: dict[str, str] = {"bg100": g["bg100"], "bg200": g["bg200"]}
    for i, light in enumerate(g["gray"], 1):
        t[f"gray{i * 100}"] = _hsl(0, 0, light)
    for i, a in enumerate(g["alpha"], 1):
        t[f"alpha{i * 100}"] = _over(g["alpha_fg"], a, g["bg100"])
        t[f"alpha{i * 100}b"] = _over(g["alpha_fg"], a, g["bg200"])
    t["blue700"] = _hsl(*g["blue700"])
    t["blue900"] = _hsl(*g["blue900"])
    t.update(
        surface=t["bg100"],
        surface2=t["bg200"],
        ink=t["gray1000"],
        ink2=t["gray900"],
        ink3=t["gray700"],
        rule=t["alpha400"],
        rule2=t["alpha400b"],
        cross=t["alpha600"],
        guide=t["alpha200"],
        track=t["alpha300b"],
        node=t["alpha500b"],
        signal=t["blue700"],
        signal_p3=g["blue700_p3"],
        signal_text=t["blue900"],
        signal_text_p3=g["blue900_p3"],
    )
    return t


# --------------------------------------------------------------------------
# Fonts: HarfBuzz measurement + per-SVG woff2 subsets
# --------------------------------------------------------------------------


class Face:
    def __init__(self, filename: str, family: str, weight: int):
        self.path = FONT_DIR / filename
        self.family = family
        self.weight = weight
        tt = TTFont(self.path)
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        self._hb = hb.Font(hb.Face(buf.getvalue()))
        self.upm = tt["head"].unitsPerEm
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]
        os2 = tt["OS/2"]
        self.cap = os2.sCapHeight / self.upm
        self.xh = os2.sxHeight / self.upm

    def width(self, text: str, size: float, tracking: float = 0.0, tnum: bool = False) -> float:
        """Advance width as Chrome lays it out (tracking after every glyph)."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        feats = {"kern": True, "liga": tracking == 0}
        if tnum:
            feats["tnum"] = True
        hb.shape(self._hb, buf, feats)
        adv = sum(p.x_advance for p in buf.glyph_positions)
        return adv * size / self.upm + tracking * len(text)

    def positions(self, text: str, size: float, tracking: float = 0.0, tnum: bool = False):
        """Per-character x offsets (kerning and tracking applied) and the total advance."""
        buf = hb.Buffer()
        buf.add_codepoints([ord(ch) for ch in text])
        buf.guess_segment_properties()
        feats = {"kern": True, "liga": False}
        if tnum:
            feats["tnum"] = True
        hb.shape(self._hb, buf, feats)
        adv = defaultdict(float)
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            adv[info.cluster] += pos.x_advance * size / self.upm
        xs, cur = [], 0.0
        for i in range(len(text)):
            xs.append(cur)
            cur += adv[i] + tracking
        return xs, cur

    def lsb(self, char: str, size: float) -> float:
        _, lsb = self.hmtx[self.cmap[ord(char)]]
        return lsb * size / self.upm


FACES = {
    "sans400": Face("Geist-Regular.woff2", "GeistSVG", 400),
    "sans500": Face("Geist-Medium.woff2", "GeistSVG", 500),
    "sans600": Face("Geist-SemiBold.woff2", "GeistSVG", 600),
    "mono400": Face("GeistMono-Regular.woff2", "GeistMonoSVG", 400),
}

# Geist type roles: (face, size px, letter-spacing px)
ROLES = {
    "display": ("sans600", 64, -3.84),  # heading-64
    "num": ("sans600", 48, -2.88),  # heading-48
    "h32": ("sans600", 32, -1.28),  # heading-32
    "h24": ("sans600", 24, -0.96),  # heading-24
    "h20": ("sans600", 20, -0.40),  # heading-20
    "l16": ("sans500", 16, 0.0),  # label-16 strong
    "l14": ("sans500", 14, 0.0),  # label-14 strong
    "l13": ("sans400", 13, 0.0),  # label-13
    "c16": ("sans400", 16, 0.0),  # copy-16
    "c14": ("sans400", 14, 0.0),  # copy-14
    "m12": ("mono400", 12, 0.0),  # label-12-mono
}

_SUBSET_CACHE: dict[tuple[str, str], str] = {}


def woff2_b64(face_key: str, chars: set[str]) -> str:
    text = "".join(sorted(chars))
    key = (face_key, text)
    if key in _SUBSET_CACHE:
        return _SUBSET_CACHE[key]
    face = FACES[face_key]
    opts = ftsubset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.hinting = True
    opts.notdef_outline = True
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6]
    opts.name_languages = [0x409]
    font = TTFont(face.path, recalcTimestamp=False)
    sub = ftsubset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    out = base64.b64encode(buf.getvalue()).decode("ascii")
    _SUBSET_CACHE[key] = out
    return out


# --------------------------------------------------------------------------
# SVG document
# --------------------------------------------------------------------------

BASE_CSS = """
text{white-space:pre;font-kerning:normal;text-rendering:geometricPrecision}
.t1{fill:${ink}}.t2{fill:${ink2}}.t3{fill:${ink3}}.sg{fill:${signal}}
.tn{font-variant-numeric:tabular-nums}
.surface{fill:${surface}}.surface2{fill:${surface2}}
.rule{stroke:${rule};stroke-width:1;fill:none}
.rule2{stroke:${rule2};stroke-width:1;fill:none}
.cross{stroke:${cross};stroke-width:1;fill:none}
.guide{stroke:${guide};stroke-width:1;fill:none;stroke-dasharray:2 4}
@supports (color:oklch(0% 0 0)){@media (color-gamut:p3){.sg{fill:${signal_p3}}.sgs{stroke:${signal_p3}}}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def f(v: float) -> str:
    """Compact number formatting for SVG attributes."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


class Doc:
    def __init__(self, name: str, width: float, height: float, title: str):
        self.name = name
        self.w = width
        self.h = height
        self.title = title
        self.body: list[str] = []
        self.defs: list[str] = []
        self.css: list[str] = []
        self.chars: dict[str, set[str]] = defaultdict(set)

    # -- primitives ---------------------------------------------------------
    def add(self, markup: str) -> None:
        self.body.append(markup)

    def line(self, x1, y1, x2, y2, cls="rule", extra="") -> None:
        self.add(f'<path class="{cls}" d="M{f(x1)} {f(y1)}L{f(x2)} {f(y2)}"{extra}/>')

    def cross(self, x, y, arm=6.5) -> None:
        self.add(
            f'<path class="cross" d="M{f(x - arm)} {f(y)}H{f(x + arm)}M{f(x)} {f(y - arm)}V{f(y + arm)}"/>'
        )

    def width(self, text: str, role: str, tnum: bool = False) -> float:
        face_key, size, tracking = ROLES[role]
        return FACES[face_key].width(text, size, tracking, tnum)

    def ink_width(self, text: str, role: str, tnum: bool = False) -> float:
        """Width without the trailing letter-spacing Chrome adds after the last glyph."""
        _, _, tracking = ROLES[role]
        return self.width(text, role, tnum) - tracking

    def cap(self, role: str) -> float:
        face_key, size, _ = ROLES[role]
        return FACES[face_key].cap * size

    def text(self, x, y, runs, role, cls=None, anchor="start", tnum=False, attrs="") -> float:
        """Place text. runs: str or [(text, class)]. Returns the start x used."""
        face_key, size, tracking = ROLES[role]
        if isinstance(runs, str):
            runs = [(runs, None)]
        total = sum(FACES[face_key].width(t, size, tracking, tnum) for t, _ in runs) - tracking
        if anchor == "end":
            x = x - total
        elif anchor == "middle":
            x = x - total / 2
        for t, _ in runs:
            self.chars[face_key].update(t)
        classes = " ".join(c for c in (role, cls, "tn" if tnum else None) if c)
        if tracking:
            face = FACES[face_key]
            cur = x
            spans = []
            for t, c in runs:
                xs, adv = face.positions(t, size, tracking, tnum)
                xl = " ".join(f(cur + v) for v in xs)
                cl = f' class="{c}"' if c else ""
                spans.append(f'<tspan{cl} x="{xl}">{escape(t)}</tspan>')
                cur += adv
            self.add(f'<text class="{classes}" y="{f(y)}"{attrs}>{"".join(spans)}</text>')
            return x
        inner = "".join(
            f'<tspan class="{c}">{escape(t)}</tspan>' if c else escape(t) for t, c in runs
        )
        self.add(f'<text class="{classes}" x="{f(x)}" y="{f(y)}"{attrs}>{inner}</text>')
        return x

    # -- output -------------------------------------------------------------
    def svg(self, mode: str) -> str:
        t = theme(mode)
        fonts = []
        for face_key, chars in sorted(self.chars.items()):
            face = FACES[face_key]
            fonts.append(
                "@font-face{font-family:%s;font-weight:%d;font-style:normal;"
                "src:url(data:font/woff2;base64,%s) format('woff2')}"
                % (face.family, face.weight, woff2_b64(face_key, chars))
            )
        roles = []
        for role, (face_key, size, tracking) in ROLES.items():
            face = FACES[face_key]
            fallback = (
                "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
                if "Mono" in face.family
                else "ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif"
            )
            roles.append(
                f".{role}{{font-family:{face.family},{fallback};font-weight:{face.weight};font-size:{size}px}}"
            )
        css = "\n".join(fonts) + BASE_CSS + "\n".join(roles) + "\n" + "\n".join(self.css)
        sub = lambda s: re.sub(r"\$\{(\w+)\}", lambda m: t[m.group(1)], s)
        defs = f"<defs>{sub(''.join(self.defs))}</defs>" if self.defs else ""
        body = sub("\n".join(self.body))
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{f(self.w)}" height="{f(self.h)}" '
            f'viewBox="0 0 {f(self.w)} {f(self.h)}" role="img" aria-labelledby="title">\n'
            f'<title id="title">{escape(self.title)}</title>\n'
            f"<style>\n{sub(css)}\n</style>\n{defs}\n{body}\n</svg>\n"
        )


def keyframes(name: str, stops: list[tuple[float, str]]) -> str:
    """Build @keyframes from (percent, declarations) pairs, merging equal stops."""
    parts = []
    for pct, decl in stops:
        pct = max(0.0, min(100.0, pct))
        parts.append(f"{f(pct)}%{{{decl}}}")
    return f"@keyframes {name}{{{''.join(parts)}}}"


# --------------------------------------------------------------------------
# Layout constants
# --------------------------------------------------------------------------

W = 880  # full-width viewBox; the README shows it at ~846px on desktop
L, R = 10, 870  # outer edges of every block (room for grid crosses)
PAD = 32  # inner padding of the hero and every card
RADIUS = 12  # Geist material-medium
HALF = W / 2
GUTTER = 22  # gap between the two half cards (matches GitHub's paragraph gap)


def rounded_rect(x, y, w, h, r, cls, extra="") -> str:
    return f'<rect class="{cls}" x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(r)}"{extra}/>'


# --------------------------------------------------------------------------
# Hero
# --------------------------------------------------------------------------


def cap(role: str) -> float:
    face_key, size, _ = ROLES[role]
    return FACES[face_key].cap * size


HERO_GUIDES = True  # faint dashed column guides above the request line


def build_hero() -> Doc:
    c = CONTENT
    T = 10
    x = L + PAD
    disp_bl = T + PAD + 8 + cap("display")
    intro_bl = disp_bl + 30 + cap("c16")
    D = round(intro_bl + 40)  # the grid line the request travels along
    row_h = 104
    B = D + row_h
    H = B + 10
    d = Doc("hero", W, H, f"{' / '.join(c['headline'])}. {c['intro']}")

    d.defs.append(
        f'<clipPath id="frame"><rect x="{L}" y="{T}" width="{R - L}" height="{B - T}"/></clipPath>'
        '<linearGradient id="trail" x1="0" x2="1" y1="0" y2="0">'
        '<stop offset="0" stop-color="${signal}" stop-opacity="0"/>'
        '<stop offset="1" stop-color="${signal}" stop-opacity=".7"/></linearGradient>'
    )

    # Grid: frame, the request line, and the four cells below it.
    cell_w = (R - L) / 4
    d.add(rounded_rect(L, T, R - L, B - T, 0, "surface"))
    if HERO_GUIDES:
        for i in range(1, 4):
            gx = L + i * cell_w + 0.5
            d.line(gx, T + 1, gx, D, "guide")
    d.add(rounded_rect(L + 0.5, T + 0.5, R - L - 1, B - T - 1, 0, "rule"))
    d.line(L, D + 0.5, R, D + 0.5)
    for i in range(1, 4):
        gx = L + i * cell_w + 0.5
        d.line(gx, D + 0.5, gx, B)
    for px, py in ((L + 0.5, T + 0.5), (R - 0.5, T + 0.5), (L + 0.5, B - 0.5), (R - 0.5, B - 0.5)):
        d.cross(px, py)

    # Type.
    # Headline: words and slashes placed individually so the slashes sit
    # 0.12em from each word, which keeps heading-64 inside the padding.
    face_key, size, tracking = ROLES["display"]
    face = FACES[face_key]
    gap = 0.12 * size
    cur = x - face.lsb(c["headline"][0][0], size)
    spans = []
    for i, word in enumerate(c["headline"]):
        if i:
            cur += gap
            spans.append(f'<tspan class="t3" x="{f(cur)}">/</tspan>')
            cur += face.width("/", size, tracking) + gap
        xs, adv = face.positions(word, size, tracking)
        spans.append(f'<tspan x="{" ".join(f(cur + v) for v in xs)}">{escape(word)}</tspan>')
        cur += adv
        d.chars[face_key].update(word + "/")
    assert cur - tracking <= R - PAD + 0.5, f"headline overflows by {cur - tracking - (R - PAD):.1f}"
    d.add(f'<text class="display t1" y="{f(disp_bl)}">{"".join(spans)}</text>')
    d.text(x, intro_bl, c["intro"], "c16", cls="t2")

    # Request path cells.
    node_x = []
    for i, (label, detail) in enumerate(c["path"]):
        tx = L + i * cell_w + PAD
        d.text(tx, D + 48, label, "l14", cls="t1")
        d.text(tx, D + 70, detail, "l13", cls="t2")
        node_x.append(tx + 4)

    # Motion. One packet crosses the grid line. On the first pass each layer
    # comes online (hollow -> filled); later passes are only acknowledged.
    cycle, delay, travel = 8.0, 1.0, 2.6
    p_end = travel / cycle * 100
    dist = R - L
    d.css.append(
        keyframes(
            "pk",
            [
                (0, "transform:translateX(0);opacity:0"),
                (1.2, "opacity:1"),
                (p_end - 1.6, "opacity:1"),
                (p_end, f"transform:translateX({f(dist)}px);opacity:0"),
                (100, f"transform:translateX({f(dist)}px);opacity:0"),
            ],
        )
    )
    d.css.append(f".pk{{opacity:0;animation:pk {cycle}s linear {delay}s infinite}}")
    d.css.append(
        ".node{fill:${ink};stroke:${ink};stroke-width:1.5}"
        ".flash{fill:${signal};opacity:0}"
        ".ring{fill:none;stroke:${signal};stroke-width:1;opacity:0;transform-box:fill-box;transform-origin:center}"
        "@keyframes boot{from{fill:${surface}}to{fill:${ink}}}"
    )
    for i, nx in enumerate(node_x):
        t_hit = travel * (nx - L) / dist  # seconds after each cycle starts
        a = t_hit / cycle * 100
        d.css.append(
            keyframes(
                f"f{i}",
                [(0, "opacity:0"), (a - 0.2, "opacity:0"), (a + 0.5, "opacity:1"),
                 (a + 8, "opacity:1"), (a + 15, "opacity:0"), (100, "opacity:0")],
            )
        )
        d.css.append(
            keyframes(
                f"r{i}",
                [
                    (0, "opacity:0;transform:scale(1)"),
                    (a - 0.1, "opacity:0;transform:scale(1)"),
                    (a + 0.4, "opacity:.6;transform:scale(1)"),
                    (a + 11, "opacity:0;transform:scale(3.2)"),
                    (100, "opacity:0;transform:scale(3.2)"),
                ],
            )
        )
        d.css.append(
            f".b{i}{{animation:boot .3s ease-out {f(delay + t_hit)}s both}}"
            f".f{i}{{animation:f{i} {cycle}s linear {delay}s infinite}}"
            f".r{i}{{animation:r{i} {cycle}s cubic-bezier(.16,1,.3,1) {delay}s infinite}}"
        )
        cy = f(D + 0.5)
        d.add(f'<circle class="ring r{i}" cx="{f(nx)}" cy="{cy}" r="4"/>')
        d.add(f'<circle class="node b{i}" cx="{f(nx)}" cy="{cy}" r="4"/>')
        d.add(f'<circle class="flash f{i}" cx="{f(nx)}" cy="{cy}" r="4.75"/>')

    d.add(
        f'<g clip-path="url(#frame)"><g class="pk">'
        f'<rect x="{f(L - 44)}" y="{f(D - 0.25)}" width="44" height="1.5" fill="url(#trail)"/>'
        f'<circle class="sg" cx="{f(L)}" cy="{f(D + 0.5)}" r="3"/></g></g>'
    )
    return d


# --------------------------------------------------------------------------
# Featured card: Windows Battery Report (with the section heading above it)
# --------------------------------------------------------------------------


def build_battery() -> Doc:
    p = BATTERY
    label_bl = 26
    top = 44
    h = 232
    B = top + h
    H = B + 1
    split = 452  # left column | figure cell
    d = Doc(
        "work-battery",
        W,
        H,
        f"{CONTENT['section']}. {p['title']}: {' '.join(p['desc'])}",
    )
    d.text(L, label_bl, CONTENT["section"], "h20", cls="t1")

    card = (L + 0.5, top + 0.5, R - L - 1, h - 1)
    d.defs.append(
        f'<clipPath id="card"><rect x="{f(card[0])}" y="{f(card[1])}" width="{f(card[2])}" '
        f'height="{f(card[3])}" rx="{RADIUS}"/></clipPath>'
    )
    d.add(rounded_rect(*card, RADIUS, "surface"))
    d.add(
        f'<g clip-path="url(#card)"><rect class="surface2" x="{split}" y="{top}" '
        f'width="{R - split}" height="{h}"/></g>'
    )
    d.line(split + 0.5, top, split + 0.5, B)
    d.add(rounded_rect(*card, RADIUS, "rule"))

    # Left column.
    x = L + PAD
    title_bl = top + PAD + d.cap("h32")
    d.text(x - FACES["sans600"].lsb(p["title"][0], 32), title_bl, p["title"], "h32", cls="t1")
    y = title_bl + 34
    for line in p["desc"]:
        assert d.width(line, "c16") <= split - L - 2 * PAD, f"battery: line too long: {line!r}"
        d.text(x, y, line, "c16", cls="t2")
        y += 24
    cmd_bl = y + 18
    d.text(x, cmd_bl, [("> ", "t3"), (p["command"], "t1")], "m12")
    foot_bl = B - PAD
    d.text(x, foot_bl, "View repository", "l14", cls="t1")
    d.text(split - PAD, foot_bl, p["language"], "l13", cls="t2", anchor="end")

    # Figure: gauge + table, centred in the cell.
    r, sw = 50, 6
    gauge_w = 2 * r + sw
    gap = 36
    label_w = max(d.width(k, "l13") for k, _ in p["rows"])
    value_w = max(d.width(v, "l13", tnum=True) for _, v in p["rows"])
    table_w = label_w + 28 + value_w
    total = gauge_w + gap + table_w
    fx0 = split + (R - split - total) / 2
    cy = top + h / 2
    gcx = fx0 + gauge_w / 2
    circ = 2 * math.pi * r
    offset = circ * (1 - p["health"] / 100)
    d.add(
        f'<circle cx="{f(gcx)}" cy="{f(cy)}" r="{r}" fill="none" stroke="${{track}}" stroke-width="{sw}"/>'
    )
    d.add(
        f'<circle class="arc sgs" cx="{f(gcx)}" cy="{f(cy)}" r="{r}" fill="none" stroke="${{signal}}" '
        f'stroke-width="{sw}" stroke-linecap="round" stroke-dasharray="{f(circ)}" '
        f'stroke-dashoffset="{f(offset)}" transform="rotate(-90 {f(gcx)} {f(cy)})"/>'
    )
    d.css.append(keyframes("fill", [(0, f"stroke-dashoffset:{f(circ)}"), (100, f"stroke-dashoffset:{f(offset)}")]))
    d.css.append(".arc{animation:fill 1.8s cubic-bezier(.16,1,.3,1) .5s both}")
    d.text(gcx, cy + 4, f"{p['health']}%", "h24", cls="t1", anchor="middle", tnum=True)
    d.text(gcx, cy + 24, "Health", "l13", cls="t2", anchor="middle")

    tx = fx0 + gauge_w + gap
    row_h = 32
    rows = p["rows"]
    t0 = cy - row_h * len(rows) / 2
    for i, (k, v) in enumerate(rows):
        ry = t0 + i * row_h
        bl = ry + row_h / 2 + d.cap("l13") / 2
        d.text(tx, bl, k, "l13", cls="t2")
        d.text(tx + table_w, bl, v, "l13", cls="t1", anchor="end", tnum=True)
        if i:
            d.line(tx, ry + 0.5, tx + table_w, ry + 0.5, "rule2")
    return d


# --------------------------------------------------------------------------
# Half cards
# --------------------------------------------------------------------------


def half_card(name: str, side: str, project: dict, title: str) -> tuple[Doc, float, float, float, float]:
    h = 300
    x0 = L if side == "left" else GUTTER / 2
    x1 = HALF - GUTTER / 2 if side == "left" else HALF - (W - R)
    d = Doc(name, HALF, h, title)
    card = (x0 + 0.5, 0.5, x1 - x0 - 1, h - 1)
    d.card = card
    d.defs.append(
        f'<clipPath id="card"><rect x="{f(card[0])}" y="{f(card[1])}" width="{f(card[2])}" '
        f'height="{f(card[3])}" rx="{RADIUS}"/></clipPath>'
    )
    d.add(rounded_rect(*card, RADIUS, "surface"))

    x = x0 + PAD
    title_bl = PAD + d.cap("h24")
    d.text(x - FACES["sans600"].lsb(project["title"][0], 24), title_bl, project["title"], "h24", cls="t1")
    y = title_bl + 30
    for line in project["desc"]:
        assert d.width(line, "c14") <= (x1 - x0) - 2 * PAD, f"{name}: line too long: {line!r}"
        d.text(x, y, line, "c14", cls="t2")
        y += 20
    band_top = y + 8
    band_h = 112
    band_bot = band_top + band_h
    d.add(
        f'<g clip-path="url(#card)"><rect class="surface2" x="{f(x0)}" y="{f(band_top)}" '
        f'width="{f(x1 - x0)}" height="{f(band_h)}"/></g>'
    )
    d.line(x0, band_top + 0.5, x1, band_top + 0.5)
    d.line(x0, band_bot - 0.5, x1, band_bot - 0.5)
    foot_bl = h - PAD
    d.text(x, foot_bl, "View repository", "l14", cls="t1")
    d.text(x1 - PAD, foot_bl, project["language"], "l13", cls="t2", anchor="end")
    return d, x, x1 - PAD, band_top, band_h


def build_palo() -> Doc:
    p = PALO
    d, xa, xb, bt, bh = half_card(
        "work-palo",
        "left",
        p,
        f"{p['title']}: {' '.join(p['desc'])}",
    )
    zone_bl = bt + 32
    wire_y = bt + 52.5
    addr_bl = bt + 84
    mid = (xa + xb) / 2

    # Static wire with a policy gate in the middle.
    d.line(xa, wire_y, xb, wire_y)
    d.line(mid, wire_y - 9, mid, wire_y + 9, "gate")
    d.css.append(".gate{stroke:${ink3};stroke-width:1.5}")
    d.add(f'<circle cx="{f(xa + 3)}" cy="{f(wire_y)}" r="3" fill="${{node}}"/>')
    d.add(f'<circle cx="{f(xb - 3)}" cy="{f(wire_y)}" r="3" fill="${{node}}"/>')
    d.text(xb, zone_bl, p["snat"]["outside"], "m12", cls="t2", anchor="end")

    # Two scenes share the wire: SNAT outbound, then DNAT inbound.
    C, delay = 12.0, 1.0
    sec = lambda s: s / C * 100

    def scene(key, kind, field, direction, start):
        s = p[key]
        inside_x = xa
        g_in = f"in-{key}"
        g_after = f"after-{key}"
        visible_base = 1 if key == "snat" else 0
        # zone + scene label + the address before translation
        before_x, before_anchor = (xa, "start") if direction > 0 else (xb, "end")
        after_x, after_anchor = (xb, "end") if direction > 0 else (xa, "start")
        d.add(f'<g class="{g_in}">')
        d.text(inside_x, zone_bl, s["inside"], "m12", cls="t2")
        d.text(mid, zone_bl, kind, "m12", cls=f"t3 lab-{key}", anchor="middle")
        d.text(before_x, addr_bl, [(f"{field} ", "t2"), (s["before"], "t1")], "m12", anchor=before_anchor)
        d.add("</g>")
        d.add(f'<g class="{g_after}">')
        d.text(after_x, addr_bl, [(f"{field} ", "t2"), (s["after"], f"v-{key}")], "m12", anchor=after_anchor)
        d.add("</g>")

        t_in = start
        t_go = start + 0.6
        t_cross = t_go + 1.0
        t_arrive = t_go + 2.0
        t_out = start + 5.4
        t_gone = start + 6.0
        fade = lambda: [
            (0, "opacity:0"),
            (sec(t_in), "opacity:0"),
            (sec(t_in + 0.4), "opacity:1"),
            (sec(t_out), "opacity:1"),
            (sec(t_gone), "opacity:0"),
            (100, "opacity:0"),
        ]
        d.css.append(keyframes(f"k-{g_in}", fade()))
        d.css.append(
            keyframes(
                f"k-{g_after}",
                [
                    (0, "opacity:0"),
                    (sec(t_cross), "opacity:0"),
                    (sec(t_cross + 0.3), "opacity:1"),
                    (sec(t_out), "opacity:1"),
                    (sec(t_gone), "opacity:0"),
                    (100, "opacity:0"),
                ],
            )
        )
        d.css.append(
            keyframes(
                f"k-v-{key}",
                [
                    (0, "fill:${signal_text}"),
                    (sec(t_cross + 1.4), "fill:${signal_text}"),
                    (sec(t_cross + 2.4), "fill:${ink}"),
                    (100, "fill:${ink}"),
                ],
            )
        )
        d.css.append(
            keyframes(
                f"k-lab-{key}",
                [
                    (0, "fill:${ink3}"),
                    (sec(t_cross - 0.05), "fill:${ink3}"),
                    (sec(t_cross + 0.1), "fill:${signal_text}"),
                    (sec(t_cross + 1.4), "fill:${signal_text}"),
                    (sec(t_cross + 2.2), "fill:${ink3}"),
                    (100, "fill:${ink3}"),
                ],
            )
        )
        d.css.append(
            f".{g_in},.{g_after}{{opacity:{visible_base}}}"
            f".{g_in}{{animation:k-{g_in} {C}s linear {delay}s infinite both}}"
            f".{g_after}{{animation:k-{g_after} {C}s linear {delay}s infinite both}}"
            f".v-{key}{{fill:${{ink}};animation:k-v-{key} {C}s linear {delay}s infinite both}}"
            f".lab-{key}{{animation:k-lab-{key} {C}s linear {delay}s infinite both}}"
        )

        # packet
        span = (xb - 3) - (xa + 3)
        x_from = xa + 3 if direction > 0 else xb - 3
        dx = span * direction
        d.css.append(
            keyframes(
                f"k-pk-{key}",
                [
                    (0, "transform:translateX(0);opacity:0"),
                    (sec(t_go), "transform:translateX(0);opacity:0"),
                    (sec(t_go + 0.15), "opacity:1"),
                    (sec(t_arrive - 0.15), "opacity:1"),
                    (sec(t_arrive), f"transform:translateX({f(dx)}px);opacity:0"),
                    (100, f"transform:translateX({f(dx)}px);opacity:0"),
                ],
            )
        )
        d.css.append(f".pk-{key}{{opacity:0;animation:k-pk-{key} {C}s cubic-bezier(.45,0,.55,1) {delay}s infinite both}}")
        d.add(f'<circle class="sg pk-{key}" cx="{f(x_from)}" cy="{f(wire_y)}" r="3.5"/>')

    scene("snat", "SNAT", "src", +1, 0.0)
    scene("dnat", "DNAT", "dst", -1, 6.0)
    d.add(rounded_rect(*d.card, RADIUS, "rule"))
    return d


def build_weather() -> Doc:
    p = WEATHER
    d, xa, xb, bt, bh = half_card(
        "work-weather",
        "right",
        p,
        f"{p['title']}: {' '.join(p['desc'])}",
    )
    temp_bl = bt + 20 + d.cap("num")
    tx = d.text(xa - FACES["sans600"].lsb("2", 48), temp_bl, p["temp"], "num", cls="t1", tnum=True)
    temp_w = d.ink_width(p["temp"], "num", tnum=True)
    cx = tx + temp_w + 16
    d.text(cx, temp_bl - 18, p["condition"], "l14", cls="t1")
    d.text(cx, temp_bl, p["place"], "l13", cls="t2")

    # Sun: Geist-weight line icon.
    sx, sy, sr = xb - 14, bt + 20 + d.cap("num") / 2, 6
    rays = []
    for k in range(8):
        a = k * math.pi / 4
        r1, r2 = sr + 4, sr + 7.5
        rays.append(
            f"M{f(sx + r1 * math.cos(a))} {f(sy + r1 * math.sin(a))}L{f(sx + r2 * math.cos(a))} {f(sy + r2 * math.sin(a))}"
        )
    d.add(
        f'<g fill="none" stroke="${{ink}}" stroke-width="1.5" stroke-linecap="round">'
        f'<circle cx="{f(sx)}" cy="{f(sy)}" r="{sr}"/><path d="{"".join(rays)}"/></g>'
    )

    # Stats row.
    stats_bl = bt + bh - 22
    col = (xb - xa) / len(p["stats"])
    for i, (k, v) in enumerate(p["stats"]):
        sx0 = xa + i * col
        lx = d.text(sx0, stats_bl, k, "l13", cls="t2")
        d.text(lx + d.width(k, "l13") + 6, stats_bl, v, "l13", cls="t1", tnum=True)
    d.add(rounded_rect(*d.card, RADIUS, "rule"))
    return d


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------


def build_footer() -> Doc:
    c = CONTENT
    H = 44
    bl = 26
    d = Doc("footer", W, H, f"{c['motto']} {c['status']}.")
    d.text(L, bl, c["motto"], "l14", cls="t1")
    sx = d.text(R, bl, c["status"], "l13", cls="t2", anchor="end")
    d.add(f'<circle class="sg" cx="{f(sx - 12)}" cy="{f(bl - d.cap("l13") / 2)}" r="3.5"/>')
    return d


# --------------------------------------------------------------------------


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    docs = [build_hero(), build_battery(), build_palo(), build_weather(), build_footer()]
    for doc in docs:
        for mode in ("light", "dark"):
            path = OUT_DIR / f"{doc.name}-{mode}.svg"
            path.write_text(doc.svg(mode), encoding="utf-8")
            print(f"{path.relative_to(HERE.parent)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
