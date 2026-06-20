"""Generate app icons from installers/icon/les.svg.

Produces installers/macos/app/LES.icns and installers/windows/app/LES.ico, which
the bundle/installer builders pick up automatically. SVG rasterization needs
``cairosvg`` (+ ``Pillow`` for the .ico); .icns needs macOS ``iconutil``. When a
tool is missing the script says exactly what to install rather than shipping a
bad icon.

    uv run --with cairosvg --with pillow python tools/build_icons.py
"""

from __future__ import annotations

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


def _render_png(svg: Path, size: int, out: Path) -> None:
    import cairosvg

    cairosvg.svg2png(url=str(svg), write_to=str(out), output_width=size, output_height=size)


def build_icns() -> bool:
    if sys.platform != "darwin" or shutil.which("iconutil") is None:
        print("[icons] skip .icns — needs macOS + iconutil")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "LES.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES:
            _render_png(SVG, size, iconset / f"icon_{size}x{size}.png")
            if size <= 512:  # @2x retina variants
                _render_png(SVG, size * 2, iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    print(f"[icons] wrote {ICNS}")
    return True


def build_ico() -> bool:
    try:
        from PIL import Image
    except Exception:
        print("[icons] skip .ico — needs Pillow")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "base.png"
        _render_png(SVG, 256, png)
        img = Image.open(png)
        img.save(ICO, sizes=[(s, s) for s in ICO_SIZES])
    print(f"[icons] wrote {ICO}")
    return True


def main() -> int:
    if not SVG.exists():
        print(f"[icons] missing source {SVG}", file=sys.stderr)
        return 1
    try:
        import cairosvg  # noqa: F401
    except Exception:
        print("[icons] cairosvg not available — install it to rasterize:")
        print("        uv run --with cairosvg --with pillow python tools/build_icons.py")
        return 1
    ok_icns = build_icns()
    ok_ico = build_ico()
    return 0 if (ok_icns or ok_ico) else 1


if __name__ == "__main__":
    raise SystemExit(main())
