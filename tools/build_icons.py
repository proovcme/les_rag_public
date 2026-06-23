"""Generate app icons from installers/icon/les.svg.

Produces installers/macos/app/LES.icns and installers/windows/app/LES.ico, which
the bundle/installer builders pick up automatically.

Two rasterizers, tried in order:

1. ``cairosvg`` — full SVG fidelity (survives any future redesign of les.svg).
   Needs the ``cairosvg`` package (+ a libcairo system lib).
2. a tiny built-in Pillow renderer — no extra system deps, understands only the
   handful of primitives our icon uses (rounded rect, polygon, circle). It is a
   pragmatic fallback so icons build on a stock machine that only has Pillow
   (already in the runtime env). If you ever make les.svg fancier than these
   primitives, install cairosvg instead of extending this.

.icns assembly needs macOS ``iconutil``; the .ico is written directly by Pillow.
When no rasterizer is available the script prints exactly what to install and
exits non-zero rather than shipping a broken icon.

    # full fidelity
    uv run --with cairosvg --with pillow python tools/build_icons.py
    # fallback (Pillow only — already in the runtime env)
    uv run --with pillow python tools/build_icons.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "installers" / "icon" / "les.svg"
ICNS = ROOT / "installers" / "macos" / "app" / "LES.icns"
ICO = ROOT / "installers" / "windows" / "app" / "LES.ico"

ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 32, 48, 64, 128, 256)

INSTALL_HINT = (
    "[icons] no rasterizer available. Install one of:\n"
    "        uv run --with pillow python tools/build_icons.py                 # built-in fallback\n"
    "        uv run --with cairosvg --with pillow python tools/build_icons.py  # full SVG fidelity"
)


# ── rasterizers ─────────────────────────────────────────────────────────────
def _render_cairosvg(svg: Path, size: int, out: Path) -> None:
    import cairosvg

    cairosvg.svg2png(url=str(svg), write_to=str(out), output_width=size, output_height=size)


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _render_pillow(svg: Path, size: int, out: Path) -> None:
    """Render the (deliberately simple) les.svg with Pillow only.

    Supports just the primitives our icon uses: rounded background rects, filled
    polygons and a circle. Coordinates live in the SVG viewBox and are scaled to
    the requested pixel size. Drawn at 4× then downsampled for clean edges.
    """
    from PIL import Image, ImageDraw

    text = svg.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([\d.\s-]+)"', text)
    parts = [float(x) for x in (vb.group(1).split() if vb else ["0", "0", "1024", "1024"])]
    vw, vh = (parts[2], parts[3]) if len(parts) >= 4 else (1024.0, 1024.0)

    ss = 4  # supersample factor for anti-aliasing
    canvas = size * ss
    sx, sy = canvas / vw, canvas / vh
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded background rects with a solid hex fill (gradient/opacity overlays
    # have no plain fill="#rrggbb" and are skipped — fine for an app icon).
    for m in re.finditer(
        r'<rect[^>]*\bx="([\d.]+)"[^>]*\by="([\d.]+)"[^>]*\bwidth="([\d.]+)"[^>]*'
        r'\bheight="([\d.]+)"(?:[^>]*\brx="([\d.]+)")?[^>]*\bfill="(#[0-9a-fA-F]{6})"',
        text,
    ):
        x, y = float(m.group(1)) * sx, float(m.group(2)) * sy
        w, h = float(m.group(3)) * sx, float(m.group(4)) * sy
        rx = float(m.group(5) or 0) * sx
        fill = _hex(m.group(6))
        if rx > 0:
            draw.rounded_rectangle([x, y, x + w, y + h], radius=rx, fill=fill)
        else:
            draw.rectangle([x, y, x + w, y + h], fill=fill)

    # Polygons (spruce tiers).
    for m in re.finditer(r'<polygon[^>]*\bpoints="([\d.,\s]+)"[^>]*\bfill="(#[0-9a-fA-F]{6})"', text):
        nums = [float(v) for v in re.split(r"[,\s]+", m.group(1).strip()) if v]
        coords = [(nums[i] * sx, nums[i + 1] * sy) for i in range(0, len(nums) - 1, 2)]
        if len(coords) >= 3:
            draw.polygon(coords, fill=_hex(m.group(2)))

    # Circle (snow highlight).
    for m in re.finditer(
        r'<circle[^>]*\bcx="([\d.]+)"[^>]*\bcy="([\d.]+)"[^>]*\br="([\d.]+)"[^>]*\bfill="(#[0-9a-fA-F]{6})"',
        text,
    ):
        cx, cy, r = float(m.group(1)) * sx, float(m.group(2)) * sy, float(m.group(3)) * sx
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_hex(m.group(4)))

    img = img.resize((size, size), Image.LANCZOS)
    img.save(out)


def pick_renderer():
    """Return (render_fn, label) or (None, None) when nothing is available."""
    try:
        import cairosvg  # noqa: F401

        return _render_cairosvg, "cairosvg"
    except Exception:
        pass
    try:
        from PIL import Image  # noqa: F401

        return _render_pillow, "pillow"
    except Exception:
        return None, None


# ── outputs ─────────────────────────────────────────────────────────────────
def build_icns(render) -> bool:
    if sys.platform != "darwin" or shutil.which("iconutil") is None:
        print("[icons] skip .icns — needs macOS + iconutil")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "LES.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES:
            render(SVG, size, iconset / f"icon_{size}x{size}.png")
            if size <= 512:  # @2x retina variants
                render(SVG, size * 2, iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    print(f"[icons] wrote {ICNS}")
    return True


def build_ico(render) -> bool:
    try:
        from PIL import Image
    except Exception:
        print("[icons] skip .ico — needs Pillow")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "base.png"
        render(SVG, 256, png)
        img = Image.open(png)
        img.save(ICO, sizes=[(s, s) for s in ICO_SIZES])
    print(f"[icons] wrote {ICO}")
    return True


def main() -> int:
    if not SVG.exists():
        print(f"[icons] missing source {SVG}", file=sys.stderr)
        return 1
    render, label = pick_renderer()
    if render is None:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    print(f"[icons] rasterizer: {label}")
    ok_icns = build_icns(render)
    ok_ico = build_ico(render)
    return 0 if (ok_icns or ok_ico) else 1


if __name__ == "__main__":
    raise SystemExit(main())
