#!/usr/bin/env python3
"""
Generates animated terminal-style profile SVGs:
  assets/generated/contributions.svg  (animated contribution heatmap)
  assets/generated/whoami.svg         (ASCII portrait + animated stats dashboard)

Env vars:
  GH_TOKEN      GitHub token (Actions provides secrets.GITHUB_TOKEN)
  GH_USER       GitHub username
  HANDLE        name shown in the terminal prompts (default: naveen)
  DISPLAY_NAME  name printed after `whoami` (default: Naveen K)
  PORTRAIT_INVERT  "1" / "0" to force-invert the ASCII portrait (default: auto)

Local test:  python scripts/generate_profile.py --mock [--static]
"""
import argparse, datetime as dt, html, json, math, os, random, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "generated"
W = 830
T = 14  # animation loop length in seconds
FONT = 'ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace'
LEVELS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]

# ----------------------------------------------------------------- data ----
QUERY = """query($login:String!){user(login:$login){contributionsCollection{
contributionCalendar{totalContributions weeks{contributionDays{date contributionCount weekday}}}}}}"""


def fetch(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-readme-generator"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors") or not data["data"]["user"]:
        raise SystemExit(f"GitHub API error: {data.get('errors')}")
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return [[(d["date"], d["contributionCount"], d["weekday"]) for d in w["contributionDays"]]
            for w in cal["weeks"]]


def mock_weeks():
    rnd = random.Random(7)
    end = dt.date.today()
    start = end - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday
    weeks, cur, d = [], [], start
    while d <= end:
        busy = (d.month in (8, 9, 10, 2, 3)) and rnd.random() > 0.35
        n = rnd.randint(1, 9) if busy else (rnd.randint(0, 2) if rnd.random() > 0.8 else 0)
        cur.append((d.isoformat(), n, (d.weekday() + 1) % 7))
        if len(cur) == 7:
            weeks.append(cur); cur = []
        d += dt.timedelta(days=1)
    if cur:
        weeks.append(cur)
    return weeks


def compute_stats(weeks):
    days = [(dt.date.fromisoformat(d), c) for w in weeks for d, c, _ in w]
    days.sort()
    total = sum(c for _, c in days)
    active = sum(1 for _, c in days if c > 0)
    best = max(days, key=lambda x: x[1])
    # longest streak
    longest, cur_len, cur_start, l_range = 0, 0, None, None
    for d, c in days:
        if c > 0:
            if cur_len == 0:
                cur_start = d
            cur_len += 1
            if cur_len > longest:
                longest, l_range = cur_len, (cur_start, d)
        else:
            cur_len = 0
    # current streak (today may still be empty)
    seq = days[:]
    if seq and seq[-1][1] == 0:
        seq = seq[:-1]
    cs, c_range = 0, None
    for d, c in reversed(seq):
        if c > 0:
            cs += 1
            c_range = (d, c_range[1] if c_range else d)
        else:
            break
    months = {}
    for d, c in days:
        months[(d.year, d.month)] = months.get((d.year, d.month), 0) + c
    mkeys = sorted(months)
    return dict(days=days, total=total, active=active, n_days=len(days), best=best,
                longest=longest, l_range=l_range, current=cs, c_range=c_range,
                months=[(k, months[k]) for k in mkeys])


def fmt_d(d):
    return f"{d.strftime('%b')} {d.day}"


def fmt_range(r):
    return f"{fmt_d(r[0])} - {fmt_d(r[1])}" if r else "-"


# ------------------------------------------------------------ animation ----
class Anim:
    """Collects @keyframes (deduplicated) and returns CSS class names."""
    def __init__(self, static=False):
        self.static, self.rules, self.css = static, {}, []

    def _get(self, key, body):
        if key not in self.rules:
            name = f"k{len(self.rules)}"
            self.rules[key] = name
            self.css.append(f"@keyframes {name}{{{body}}}.{name}{{animation-name:{name}}}")
        return self.rules[key]

    def cls(self, kind, s, dur=1.2, final=True, e=None):
        if self.static:
            return ""
        s = round(min(s, 85), 2)
        if kind == "fade":
            body = (f"0%,{s}%{{opacity:0}}{round(s+dur,2)}%,90%{{opacity:1}}94%,100%{{opacity:0}}")
            return "a " + self._get((kind, s, dur), body)
        if kind == "grow":
            body = (f"0%,{s}%{{opacity:0;transform:scaleY(0)}}"
                    f"{round(s+dur,2)}%,90%{{opacity:1;transform:scaleY(1)}}"
                    f"94%{{opacity:0;transform:scaleY(1)}}100%{{opacity:0;transform:scaleY(0)}}")
            return "a g " + self._get((kind, s, dur), body)
        if kind == "step":  # discrete visibility window [s, e]; last one stays until reset
            if final:
                body = (f"0%,{round(s-.01,2)}%{{opacity:0}}{s}%,90%{{opacity:1}}94%,100%{{opacity:0}}")
            else:
                body = (f"0%,{round(s-.01,2)}%{{opacity:0}}{s}%,{e}%{{opacity:1}}"
                        f"{round(e+.01,2)}%,100%{{opacity:0}}")
            return "a " + self._get((kind, s, e, final), body)
        raise ValueError(kind)

    def style(self):
        if self.static:
            return ""
        base = (f".a{{animation-duration:{T}s;animation-iteration-count:infinite;"
                f"animation-timing-function:linear;animation-fill-mode:both}}"
                ".g{transform-box:fill-box;transform-origin:50% 100%;"
                "animation-timing-function:cubic-bezier(.2,.8,.2,1)}"
                "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}"
                ".cur{animation:blink 1s steps(1) infinite}"
                "@media (prefers-reduced-motion:reduce){.a,.cur{animation:none!important}}")
        return base + "".join(self.css)


def level_of(c, mx):
    if c <= 0:
        return 0
    q = max(mx / 4, 1)
    return min(4, math.ceil(c / q))


def e(s):
    return html.escape(str(s), quote=True)


# --------------------------------------------------- contributions.svg ----
def build_contributions(weeks, st, anim, handle):
    cell, gap = 11, 3
    pitch = cell + gap
    x0, y0 = 58, 38
    mx = max(c for _, c, _ in [x for w in weeks for x in w])
    parts = []
    last_label_col, last_month = -10, None
    for ci, w in enumerate(weeks):
        d0 = dt.date.fromisoformat(w[0][0])
        if d0.month != last_month and ci - last_label_col >= 3:
            parts.append(f'<text x="{x0+ci*pitch}" y="26" class="mut">{d0.strftime("%b")}</text>')
            last_label_col, last_month = ci, d0.month
        elif d0.month != last_month:
            last_month = d0.month
        for date, cnt, wd in w:
            diag = ci + wd * 2
            c = anim.cls("fade", 3 + diag * 0.26, 1.0)
            parts.append(f'<rect x="{x0+ci*pitch}" y="{y0+wd*pitch}" width="{cell}" height="{cell}" '
                         f'rx="2" fill="{LEVELS[level_of(cnt, mx)]}" class="{c}"/>')
    for r, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(f'<text x="24" y="{y0+r*pitch+9}" class="mut">{lab}</text>')
    cap = anim.cls("fade", 24, 2)
    parts.append(f'<text x="{x0}" y="{y0+7*pitch+26}" class="cap {cap}">{st["total"]:,} contributions in the last year</text>')
    h = y0 + 7 * pitch + 40
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
            f'role="img" aria-label="{st["total"]} contributions in the last year">'
            f'<style>text{{font-family:{FONT}}}.mut{{font-size:10px;fill:#8b949e}}'
            f'.cap{{font-size:13px;font-weight:700;fill:#e6edf3}}{anim.style()}</style>'
            + "".join(parts) + "</svg>")


# ---------------------------------------------------------- ASCII art ----
RAMP = " .,:;i1tfLCG08@"


def find_portrait(user):
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = ROOT / "assets" / f"portrait.{ext}"
        if p.exists():
            return p
    try:  # fall back to the GitHub avatar
        tmp = ROOT / "assets" / "_avatar.png"
        urllib.request.urlretrieve(f"https://github.com/{user}.png?size=500", tmp)
        return tmp
    except Exception:
        return None


def ascii_lines(path, max_cols, max_rows, cw, ch):
    from PIL import Image, ImageOps, ImageFilter, ImageStat
    im = Image.open(path)
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255)); bg.alpha_composite(im.convert("RGBA")); im = bg
    im = im.convert("L")
    w, h = im.size
    cols = max_cols
    rows = int(cols * h / w * (cw / ch))
    if rows > max_rows:
        rows = max_rows
        cols = int(rows * w / h * (ch / cw))
    from PIL import ImageChops
    big = im.resize((cols * 4, rows * 4), Image.LANCZOS)
    small = im.resize((cols * 2, rows * 2), Image.LANCZOS)
    inv = os.environ.get("PORTRAIT_INVERT", "auto")
    light_bg = ImageStat.Stat(small).mean[0] > 120
    edges = ImageOps.autocontrast(big.filter(ImageFilter.GaussianBlur(1.2)).filter(ImageFilter.FIND_EDGES), cutoff=1)
    edges = edges.resize((cols * 2, rows * 2), Image.LANCZOS)
    if inv == "1" or (inv == "auto" and light_bg):
        # light background: separate the subject (dark pixels), drop the background,
        # and equalise contrast inside the subject so features survive.
        blur = small.filter(ImageFilter.GaussianBlur(1.5))
        hist = blur.histogram()
        tot, sum_all = sum(hist), sum(i * h for i, h in enumerate(hist))
        wb = sb = 0; best, thr = -1, 128
        for i in range(256):
            wb += hist[i]
            if wb == 0 or wb == tot:
                continue
            sb += i * hist[i]
            m1, m2 = sb / wb, (sum_all - sb) / (tot - wb)
            v = wb * (tot - wb) * (m1 - m2) ** 2
            if v > best:
                best, thr = v, i
        thr = max(thr, 165)  # keep mid-tone skin; only drop the bright background
        mask = blur.point(lambda p: 255 if p < thr else 0).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(3))
        tone = ImageOps.autocontrast(ImageOps.invert(small), cutoff=2)
        tone = tone.point(lambda p: int(255 * max(0.0, (p - 120) / 135) ** 0.9))  # hair stays dense, skin goes light
        tone = ImageChops.multiply(tone, mask)
        edges = ImageChops.multiply(edges, mask.filter(ImageFilter.MaxFilter(3)))
        im = Image.blend(tone, edges, 0.62)
    else:
        tone = ImageOps.autocontrast(small, cutoff=3)
        im = Image.blend(tone, edges, 0.45)
    im = ImageOps.autocontrast(im, cutoff=1).resize((cols, rows), Image.LANCZOS)
    px = im.load()
    out = []
    for y in range(rows):
        row = ""
        for x in range(cols):
            v = max(0.0, (px[x, y] / 255 - 0.12) / 0.88) ** 1.6
            row += RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))]
        out.append(row)
    return out, cols


# ------------------------------------------------------- whoami.svg ----
def card(x, y, w, h, label, big_steps, unit, sub, anim, t0, green=False):
    """A stat card; the big number counts up in discrete steps."""
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="#161b22" stroke="#30363d"/>',
         f'<text x="{x+12}" y="{y+17}" class="lab">$ {e(label)}</text>']
    n = len(big_steps)
    sl = 2.0
    for i, v in enumerate(big_steps):
        final = i == n - 1
        if anim.static and not final:
            continue
        s = round(t0 + i * sl, 2)
        c = anim.cls("step", s, e=round(s + sl, 2), final=final)
        fill = "#3fb950" if green else "#e6edf3"
        o.append(f'<text x="{x+12}" y="{y+46}" class="{c}"><tspan class="big" fill="{fill}">{e(v)}</tspan>'
                 + (f'<tspan class="unit" dx="7">{e(unit)}</tspan>' if unit else "") + '</text>')
    o.append(f'<text x="{x+12}" y="{y+h-9}" class="sub">{e(sub)}</text>')
    return "".join(o)


def steps_for(v, fmt=lambda n: f"{n:,}"):
    fr = [0.15, 0.4, 0.65, 0.85, 1.0]
    out = []
    for f in fr:
        n = int(round(v * f))
        out.append(fmt(n))
    out[-1] = fmt(v)
    return out


def build_whoami(st, anim, handle, name, portrait):
    H = 458
    px, pw = 12, 399          # left window
    rx_, rw = 419, 399        # right window
    parts = [f'<rect x="0.5" y="0.5" width="{W-1}" height="{H+11}" rx="4" fill="#0d1117" stroke="#30363d"/>']
    for x, title in ((px, f"{handle}@github: ~ -l ./portrait.sh"), (rx_, f"{handle}@github: ~ -l ./stats.sh")):
        w = pw
        parts.append(f'<rect x="{x}" y="12" width="{w}" height="{H-12}" rx="6" fill="#0d1117" stroke="#30363d"/>')
        parts.append(f'<line x1="{x}" y1="36" x2="{x+w}" y2="36" stroke="#21262d"/>')
        for i, col in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
            parts.append(f'<circle cx="{x+14+i*12}" cy="24" r="3.2" fill="{col}"/>')
        parts.append(f'<text x="{x+w/2}" y="27" text-anchor="middle" class="ttl">{e(title)}</text>')

    # ---- left: ASCII portrait
    cw, ch = 3.1, 5.9
    area_x, area_y, area_w, area_h = px + 12, 44, pw - 24, 376
    if portrait:
        lines, cols = ascii_lines(portrait, int(area_w / cw), int(area_h / ch), cw, ch)
        ox = area_x + (area_w - cols * cw) / 2
        oy = area_y + (area_h - len(lines) * ch) / 2
        n = len(lines)
        for i, ln in enumerate(lines):
            s = ln.rstrip()
            lead = len(s) - len(s.lstrip())
            body = s.lstrip()
            if not body:
                continue
            c = anim.cls("fade", 8 + (i / n) * 32, 0.9)
            parts.append(f'<text x="{ox+lead*cw:.2f}" y="{oy+(i+1)*ch:.2f}" font-size="{ch*0.95:.2f}" '
                         f'textLength="{len(body)*cw:.2f}" lengthAdjust="spacing" xml:space="preserve" '
                         f'fill="#c9d1d9" class="asc {c}">{e(body)}</text>')
    parts.append(f'<line x1="{px}" y1="426" x2="{px+pw}" y2="426" stroke="#21262d"/>')
    prompt = f"{handle}@github:~$ whoami  {name}"
    parts.append(f'<text x="{px+12}" y="445" class="prm">{e(handle)}@github:~$ <tspan fill="#e6edf3">whoami</tspan>'
                 f'  <tspan fill="#e6edf3" font-weight="700">{e(name)}</tspan></text>')
    parts.append(f'<rect x="{px+12+len(prompt)*5.45+3:.1f}" y="436" width="5" height="10" fill="#3fb950" class="{"cur" if not anim.static else ""}"/>')

    # ---- right: stats
    cx1, cx2 = rx_ + 12, rx_ + 12 + 183 + 9
    cwid, chh = 183, 66
    ys = (44, 118, 192)
    avg = st["total"] / max(st["active"], 1)
    pct = round(st["active"] / max(st["n_days"], 1) * 100)
    bd, bc = st["best"]
    parts.append(card(cx1, ys[0], cwid, chh, "current streak", steps_for(st["current"]), "days",
                      fmt_range(st["c_range"]), anim, 16, green=True))
    parts.append(card(cx2, ys[0], cwid, chh, "longest streak", steps_for(st["longest"]), "days",
                      fmt_range(st["l_range"]), anim, 17))
    parts.append(card(cx1, ys[1], cwid, chh, "contributions", steps_for(st["total"]), "",
                      "in the last year", anim, 18))
    parts.append(card(cx2, ys[1], cwid, chh, "active days", steps_for(st["active"]), f"/ {st['n_days']}",
                      f"{pct}% of the year", anim, 19))
    parts.append(card(cx1, ys[2], cwid, chh, "best day", steps_for(bc), "", fmt_d(bd), anim, 20))
    parts.append(card(cx2, ys[2], cwid, chh, "avg / active day", steps_for(round(avg, 1), lambda n: f"{n:.1f}"),
                      "", "contributions", anim, 21))

    # ---- monthly bars
    cy, chh2 = 266, 180
    parts.append(f'<rect x="{cx1}" y="{cy}" width="{cx2+cwid-cx1}" height="{chh2}" rx="5" fill="#161b22" stroke="#30363d"/>')
    parts.append(f'<text x="{cx1+12}" y="{cy+17}" class="lab">$ contributions / month</text>')
    months = st["months"]
    mx = max(v for _, v in months) or 1
    inner_x, inner_w = cx1 + 16, (cx2 + cwid - cx1) - 32
    pitch = inner_w / len(months)
    bw = pitch * 0.68
    base = cy + chh2 - 24
    maxh = chh2 - 24 - 50
    for i, ((yr, mo), v) in enumerate(months):
        hh = max(3, v / mx * maxh)
        bx = inner_x + i * pitch + (pitch - bw) / 2
        c = anim.cls("grow", 30 + i * 1.1, 3.0)
        top = v == mx
        parts.append(f'<rect x="{bx:.1f}" y="{base-hh:.1f}" width="{bw:.1f}" height="{hh:.1f}" rx="2" '
                     f'fill="{"#39d353" if top else "#2ea043"}" class="{c}"/>')
        if top:
            c2 = anim.cls("fade", 38, 1.5)
            parts.append(f'<text x="{bx+bw/2:.1f}" y="{base-hh-6:.1f}" text-anchor="middle" class="pk {c2}">{v:,}</text>')
        parts.append(f'<text x="{bx+bw/2:.1f}" y="{base+14}" text-anchor="middle" class="mon">{dt.date(yr,mo,1).strftime("%b")[0]}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H+12}" viewBox="0 0 {W} {H+12}" '
            f'role="img" aria-label="ASCII portrait and GitHub stats">'
            f'<style>text{{font-family:{FONT}}}.ttl{{font-size:9px;fill:#6e7681}}.lab{{font-size:9.5px;fill:#8b949e}}'
            f'.big{{font-size:26px;font-weight:700}}.unit{{font-size:11px;fill:#8b949e}}.sub{{font-size:9px;fill:#6e7681}}'
            f'.prm{{font-size:9px;fill:#8b949e}}.mon{{font-size:9px;fill:#6e7681}}.pk{{font-size:10px;font-weight:700;fill:#e6edf3}}'
            f'{anim.style()}</style>' + "".join(parts) + "</svg>")


# ----------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use fake data (no token needed)")
    ap.add_argument("--static", action="store_true", help="no animation (for previews)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    user = os.environ.get("GH_USER", "")
    handle = os.environ.get("HANDLE", "naveen")
    name = os.environ.get("DISPLAY_NAME", "Naveen K")
    if a.mock:
        weeks = mock_weeks()
    else:
        token = os.environ.get("GH_TOKEN")
        if not (token and user):
            raise SystemExit("Set GH_TOKEN and GH_USER (or use --mock).")
        weeks = fetch(user, token)
    st = compute_stats(weeks)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "contributions.svg").write_text(build_contributions(weeks, st, Anim(a.static), handle), encoding="utf-8")
    portrait = find_portrait(user)
    (out / "whoami.svg").write_text(build_whoami(st, Anim(a.static), handle, name, portrait), encoding="utf-8")
    tmp = ROOT / "assets" / "_avatar.png"
    if tmp.exists():
        tmp.unlink()
    print(f"OK: {st['total']} contributions, streak {st['current']}d, wrote SVGs to {out}")


if __name__ == "__main__":
    main()
