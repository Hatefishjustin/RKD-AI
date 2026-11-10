"""A quick diagnostic sketch of a spatial-plan draft.

This is NOT a deliverable drawing: it exists so the studio conversation has
something visible. Output is a plain SVG string stored with the artifact.
"""
from __future__ import annotations

from typing import Any

ROLE_TINT = {
    "arrival": "#e9dcc9", "gallery": "#dde5ea", "island": "#e6cfae",
    "scene": "#e4e8dc", "meeting": "#e8e2ec", "service": "#dfe3e6",
    "circulation": "#f2efe9", "support": "#ececec",
}
INK = "#2b3742"
GREY = "#7c8894"


def render(plan: dict, site: dict, title: str = "") -> str:
    W = float(site["width_mm"])
    H = float(site["height_mm"])
    pad = 900
    vb_w, vb_h = W + pad * 2, H + pad * 2
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} {-pad} {vb_w} {vb_h}" '
        f'width="100%" font-family="Microsoft YaHei, PingFang SC, sans-serif">',
        f'<rect x="{-pad}" y="{-pad}" width="{vb_w}" height="{vb_h}" fill="#ffffff"/>',
    ]

    def X(x: float) -> float:
        return x

    def Y(y: float) -> float:
        return H - y

    # site
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fbfaf8" stroke="{INK}" stroke-width="120"/>')

    for z in plan.get("zones") or []:
        poly = z.get("polygon") or []
        if len(poly) < 3:
            continue
        pts = " ".join(f"{X(p[0]):.0f},{Y(p[1]):.0f}" for p in poly)
        tint = ROLE_TINT.get(z.get("role", ""), "#eeeeee")
        out.append(f'<polygon points="{pts}" fill="{tint}" fill-opacity="0.75" stroke="#b9c2ca" stroke-width="30"/>')
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        out.append(f'<text x="{X(cx):.0f}" y="{Y(cy):.0f}" font-size="430" fill="{INK}" '
                   f'text-anchor="middle" font-weight="700">{_esc(z.get("name", ""))}</text>')
        if z.get("area_sqm"):
            out.append(f'<text x="{X(cx):.0f}" y="{Y(cy) + 470:.0f}" font-size="300" fill="{GREY}" '
                       f'text-anchor="middle">{float(z["area_sqm"]):.1f} ㎡</text>')

    for p in plan.get("platforms") or []:
        poly = p.get("polygon") or []
        if len(poly) < 3:
            continue
        pts = " ".join(f"{X(q[0]):.0f},{Y(q[1]):.0f}" for q in poly)
        out.append(f'<polygon points="{pts}" fill="#c9a077" fill-opacity="0.85" stroke="#8a6a45" stroke-width="40"/>')

    for c in plan.get("circulation") or []:
        path = c.get("path") or []
        if len(path) < 2:
            continue
        d = " ".join(("M" if i == 0 else "L") + f"{X(p[0]):.0f} {Y(p[1]):.0f}" for i, p in enumerate(path))
        out.append(f'<path d="{d}" fill="none" stroke="#b07b4a" stroke-width="{max(60.0, float(c.get("width_mm", 1500)) / 6)}" '
                   f'stroke-opacity="0.35" stroke-linecap="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="#8a5a2f" stroke-width="22" stroke-dasharray="150 110"/>')

    for f in plan.get("furniture") or []:
        w = float(f.get("w_mm") or 600)
        d = float(f.get("d_mm") or 600)
        x = float(f.get("x") or 0)
        y = float(f.get("y") or 0)
        rot = float(f.get("rot") or 0)
        out.append(f'<g transform="translate({X(x):.0f} {Y(y):.0f}) rotate({-rot:.0f})">'
                   f'<rect x="{-w/2:.0f}" y="{-d/2:.0f}" width="{w:.0f}" height="{d:.0f}" rx="40" '
                   f'fill="#ffffff" fill-opacity="0.85" stroke="#7c8894" stroke-width="30"/></g>')

    # north arrow + scale bar
    out.append(f'<g transform="translate({W - 900:.0f} {H - 1500:.0f})" stroke="{INK}" fill="{INK}">'
               f'<path d="M0 900 L0 0 L-220 320 L0 210 L220 320 Z" fill="{INK}" stroke="none"/>'
               f'<text x="0" y="1250" font-size="330" text-anchor="middle" stroke="none">N</text></g>')
    out.append(f'<g transform="translate(300 {H - 500:.0f})">'
               f'<rect x="0" y="0" width="2000" height="70" fill="{INK}"/>'
               f'<text x="0" y="330" font-size="280" fill="{GREY}">0</text>'
               f'<text x="2000" y="330" font-size="280" fill="{GREY}" text-anchor="middle">2 m</text></g>')

    if title:
        out.append(f'<text x="0" y="{-pad + 520:.0f}" font-size="520" fill="{INK}" font-weight="700">{_esc(title)}</text>')
    out.append(f'<text x="{W:.0f}" y="{H + 760:.0f}" font-size="300" fill="{GREY}" text-anchor="end">'
               f'草案缩略图 · 仅用于讨论，不是成果图纸</text>')
    out.append("</svg>")
    return "".join(out)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
