"""Render a built project to MP4, plus a contact sheet.

    python -X utf8 templates/explainer/render.py build/jz5 --preview     # 540×960 quick look of the full version
    python -X utf8 templates/explainer/render.py build/jz5               # final full and clean versions
    python -X utf8 templates/explainer/render.py build/jz5/full          # one version only

Outputs go to build/<name>/out/: <name>.mp4 (full), <name>_clean.mp4, <name>.preview.mp4, and a .sheet.jpg next to
each (one frame per second, timestamped).

The full version is: shots (dimmed/blurred where the YAML says) + overlay.js drawn by Edge/Chromium through
Playwright + light vignette + grain + fade-out, with mix.wav. The clean version is the same shots without dim/blur,
no overlay, with voice_clean.wav. Both are 1080×1920, 30 fps, H.264 tagged BT.709 limited range, AAC 48 kHz stereo,
and have exactly the frame count build.py worked out.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FPS, H, HERE, W, load_yaml, tool  # noqa: E402
from template import prepare_shots  # noqa: E402

BLUR_SIGMA = 2.0          # gblur sigma per unit of the YAML's `blur`
GRAIN_STRENGTH = 3.6      # ffmpeg noise strength per unit of `grain` (5 ≈ luma std 1.4 levels, measured)


# ------------------------------------------------------------------ fonts

def font_faces():
    """[(file, CSS weight range)] for the family "HC": 思源黑体 / Noto Sans SC if installed, else 微软雅黑 Bold."""
    override = os.environ.get("HC_FONT")
    if override:
        return [(Path(override), "100 900")]
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
            HERE / "assets" / "fonts", Path.home() / ".fonts", Path("/usr/share/fonts")]

    def find(*names):
        for folder in dirs:
            for name in names:
                hits = list(folder.rglob(name)) if folder.is_dir() and folder.name != "Fonts" else (
                    [folder / name] if (folder / name).is_file() else [])
                if hits:
                    return hits[0]
        return None

    variable = find("SourceHanSansSC-VF.otf", "SourceHanSansSC-VF.ttf", "SourceHanSansCN-VF.otf", "NotoSansSC-VF.ttf",
                    "NotoSansCJKsc-VF.otf", "NotoSansSC[wght].ttf")
    if variable:
        return [(variable, "100 900")]
    bold = find("SourceHanSansSC-Bold.otf", "SourceHanSansCN-Bold.otf", "NotoSansCJKsc-Bold.otf", "NotoSansSC-Bold.ttf")
    heavy = find("SourceHanSansSC-Heavy.otf", "SourceHanSansCN-Heavy.otf", "NotoSansCJKsc-Black.otf", "NotoSansSC-Black.ttf")
    if bold:
        return [(bold, "100 800"), (heavy or bold, "900")]
    yahei = find("msyhbd.ttc")
    if yahei:
        return [(yahei, "100 900")]
    raise SystemExit("找不到中文粗黑体：装思源黑体，或设 HC_FONT 指向字体文件")


# ------------------------------------------------------------------ overlay

def overlay_page(project, project_dir: Path, scale, folder: Path):
    data = {k: project.get(k) for k in ("canvas", "corp", "caps", "cards", "end", "hook_end")}
    data["scale"] = scale
    logo = (project_dir / project["assets"]["logo"]).resolve()
    css = "".join(f'@font-face{{font-family:HC;src:url("{path.resolve().as_uri()}");font-weight:{weight};}}'
                  for path, weight in font_faces())
    script = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>{css}'
            f'html,body{{margin:0;background:transparent;overflow:hidden}}canvas{{display:block}}</style>'
            f'<canvas id="c"></canvas><img id="logo" src="{logo.as_uri()}" style="display:none">'
            f'<script>window.PROJECT={script};</script><script src="{(HERE / "overlay.js").as_uri()}"></script></html>')
    target = folder / "overlay.html"
    target.write_text(page, encoding="utf-8")
    return target


def launch(playwright):
    args = ["--allow-file-access-from-files", "--font-render-hinting=none"]
    errors = []
    for channel in (None, "msedge", "chrome"):
        try:
            return playwright.chromium.launch(args=args, **({"channel": channel} if channel else {}))
        except Exception as error:  # noqa: BLE001 - try the next browser
            errors.append(str(error).splitlines()[0])
    raise SystemExit("打不开浏览器（Playwright Chromium / Edge / Chrome 都不行）：\n" + "\n".join(errors))


class Overlay:
    """Frames of the overlay in order, as raw RGBA; one screenshot per distinct frame key."""

    def __init__(self, project, project_dir, scale, folder, log):
        from playwright.sync_api import sync_playwright
        self.width, self.height = round(W * scale), round(H * scale)
        self._pw = sync_playwright().start()
        self.browser = launch(self._pw)
        self.page = self.browser.new_page(viewport={"width": self.width, "height": self.height}, device_scale_factor=1)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(overlay_page(project, project_dir, scale, folder).as_uri(), timeout=60000)
        self.page.evaluate("window.__ready")
        self._check("载入叠加层")
        self.keys = self.page.evaluate("n => window.__keys(n)", project["frames"])
        self._check("计算叠加层")
        self.pngs, self.shots = {}, 0
        log(f"  叠加层：{len(self.keys)} 帧里有 {len(set(self.keys))} 种画面")

    def _check(self, what):
        if self.errors:
            raise RuntimeError(f"{what}出错：{self.errors[0]}")

    def frames(self):
        last_key, raw = None, None
        for f, key in enumerate(self.keys):
            if key != last_key:
                if key not in self.pngs:
                    self.page.evaluate("f => window.__draw(f)", f)
                    self._check(f"第 {f} 帧叠加层")
                    self.pngs[key] = self.page.screenshot(omit_background=True, type="png")
                    self.shots += 1
                raw = Image.open(io.BytesIO(self.pngs[key])).convert("RGBA").tobytes()
                last_key = key
            yield raw

    def close(self):
        self.browser.close()
        self._pw.stop()


# ------------------------------------------------------------------ video

def vignette_png(path: Path, w, h, strength):
    if path.is_file():
        return path
    y, x = np.mgrid[0:h, 0:w]
    r = np.hypot((x + .5) / w * 2 - 1, (y + .5) / h * 2 - 1) / np.sqrt(2)
    a = np.clip((r - .4) / .6, 0, 1)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 3] = np.round(a * a * (3 - 2 * a) * min(.9, strength * 3) * 255)
    Image.fromarray(rgba, "RGBA").save(path)
    return path


def filter_graph(project, scale, full, overlay_input, vignette_input):
    shots, look = project["shots"], project["look"]
    chain = [f"[0:v]setpts=N/({FPS}*TB)"]
    if scale != 1:
        chain.append(f"scale={round(W * scale)}:{round(H * scale)}:flags=area")
    if full:
        for shot in shots:
            a, b = shot["f0"], shot["f0"] + shot["frames"] - 1
            if shot.get("blur"):
                chain.append(f"gblur=sigma={shot['blur'] * BLUR_SIGMA * scale:.2f}:enable='between(n,{a},{b})'")
            if shot.get("dim"):
                k = 1 - float(shot["dim"])
                chain.append(f"lutyuv=y='16+(val-16)*{k:.3f}':u='128+(val-128)*{k:.3f}':v='128+(val-128)*{k:.3f}'"
                             f":enable='between(n,{a},{b})'")
    chain.append("format=yuv444p")
    graph = [",".join(chain) + "[bg]"]
    to_yuv = "format=rgba,scale=out_color_matrix=bt709:out_range=tv,format=yuva444p"
    last = "bg"
    if overlay_input is not None:
        graph.append(f"[{overlay_input}:v]{to_yuv}[ov]")
        graph.append(f"[{last}][ov]overlay=format=yuv444[withov]")
        last = "withov"
    tail = []
    if vignette_input is not None:
        graph.append(f"[{vignette_input}:v]{to_yuv}[vg]")
        graph.append(f"[{last}][vg]overlay=format=yuv444:shortest=1[look]")
        last = "look"
    if look.get("grain") and scale == 1:
        tail.append(f"noise=c0s={max(1, round(look['grain'] * GRAIN_STRENGTH))}:c0f=t+u")
    if look.get("fade_out"):
        tail.append(f"fade=t=out:st={project['frames'] / FPS - look['fade_out']:.4f}:d={look['fade_out']}")
    # The graph's frames carry no primaries/transfer; stamp all four so the encoder writes complete BT.709 tags.
    tail += ["format=yuv420p", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"]
    graph.append(f"[{last}]" + ",".join(tail) + "[v]")
    return ";".join(graph)


def render(project_dir, preview=False, sheet=True, log=print):
    project_dir = Path(project_dir).resolve()
    project = load_yaml(project_dir / "project.yaml")
    full = project["version"] == "full"
    name, frames = project["name"], project["frames"]
    out_dir = project_dir.parent / "out"
    out_dir.mkdir(exist_ok=True)
    stem = name + ("" if full else "_clean") + (".preview" if preview else "")
    out = out_dir / f"{stem}.mp4"
    scale = .5 if preview else 1
    w, h = round(W * scale), round(H * scale)
    started = time.perf_counter()
    log(f"渲染 {stem}（{frames} 帧，{frames / FPS:.2f} 秒）")
    clips = prepare_shots(project, project_dir, log)

    with tempfile.TemporaryDirectory(prefix=".render-", dir=out_dir) as folder:
        folder = Path(folder)
        listing = folder / "shots.txt"
        listing.write_text("".join(f"file '{clip.as_posix()}'\n" for _, clip in clips), encoding="utf-8")
        args = [tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing]
        overlay_input = vignette_input = None
        n = 1
        if full:
            args += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-framerate", str(FPS), "-i", "-"]
            overlay_input, n = n, n + 1
        if project["look"].get("vignette"):
            png = vignette_png(folder / "vignette.png", w, h, float(project["look"]["vignette"]))
            args += ["-loop", "1", "-framerate", str(FPS), "-i", png]
            vignette_input, n = n, n + 1
        args += ["-i", (project_dir / project["audio"]).resolve()]
        audio_input = n
        args += ["-filter_complex", filter_graph(project, scale, full, overlay_input, vignette_input),
                 "-map", "[v]", "-map", f"{audio_input}:a", "-frames:v", str(frames),
                 "-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", "24" if preview else "17",
                 "-profile:v", "high", "-pix_fmt", "yuv420p",
                 "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out]
        errors = open(folder / "ffmpeg.log", "w+b")
        overlay = Overlay(project, project_dir, scale, folder, log) if full else None
        proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE if full else subprocess.DEVNULL,
                                stderr=errors)
        try:
            if overlay:
                for raw in overlay.frames():
                    proc.stdin.write(raw)
                proc.stdin.close()
            code = proc.wait()
        except (BrokenPipeError, OSError):
            code = proc.wait()
        finally:
            if overlay:
                overlay.close()
            if proc.poll() is None:
                proc.kill()
        errors.seek(0)
        message = errors.read().decode(errors="replace")
        errors.close()
        if code:
            raise RuntimeError(f"ffmpeg 失败：\n{message[-3000:]}")
    log(f"  完成 {out}（{time.perf_counter() - started:.0f} 秒"
        + (f"，叠加层截图 {overlay.shots} 张" if overlay else "") + "）")
    if sheet:
        log(f"  联系表 {contact_sheet(out, out.with_suffix('.sheet.jpg'))}")
    return out


# ------------------------------------------------------------------ contact sheet

def contact_sheet(video: Path, target: Path, every=1.0, cols=10, thumb=216):
    """One frame every `every` seconds, tiled with its time, to check cards, captions and footage at a glance."""
    result = subprocess.run([tool("ffmpeg"), "-v", "error", "-ss", f"{every / 2:.3f}", "-i", str(video), "-vf",
                             f"fps=1/{every},scale={thumb}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1000:])
    th = round(thumb * H / W / 2) * 2
    size = thumb * th * 3
    count = len(result.stdout) // size
    rows = -(-count // cols)
    sheet = Image.new("RGB", (cols * (thumb + 4) + 4, rows * (th + 4) + 4), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    faces = font_faces()
    try:
        label = ImageFont.truetype(str(faces[0][0]), 22)
    except OSError:
        label = ImageFont.load_default()
    for i in range(count):
        frame = Image.frombytes("RGB", (thumb, th), result.stdout[i * size:(i + 1) * size])
        x, y = 4 + (i % cols) * (thumb + 4), 4 + (i // cols) * (th + 4)
        sheet.paste(frame, (x, y))
        text = f"{every / 2 + i * every:.1f}s"
        draw.rectangle((x, y, x + 74, y + 28), fill=(0, 0, 0))
        draw.text((x + 6, y + 2), text, fill=(255, 255, 255), font=label)
    sheet.save(target, quality=88)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="渲染讲解片工程")
    parser.add_argument("project", help="build/<名字>（两个版本）或 build/<名字>/full、build/<名字>/clean")
    parser.add_argument("--preview", action="store_true", help="540×960 快速预览（只出完整版，除非指定 clean）")
    parser.add_argument("--no-sheet", action="store_true", help="不出联系表")
    args = parser.parse_args(argv)
    target = Path(args.project)
    if (target / "project.yaml").is_file():
        folders = [target]
    elif (target / "full" / "project.yaml").is_file():
        folders = [target / "full"] if args.preview else [target / "full", target / "clean"]
    else:
        raise SystemExit(f"{target} 里没有 project.yaml，先跑 build.py")
    for folder in folders:
        render(folder, preview=args.preview, sheet=not args.no_sheet)


if __name__ == "__main__":
    main()
