"""Shot preprocessing: cut each shot out of its footage as a 1080×1920, 30 fps clip with an exact frame count.

Landscape footage is cropped to 9:16 around clip.x (0–1, default 0.5); portrait footage is scaled to fit. Frame rates
(24/25/30/60/100) become 30 fps. Dimming and blur are not baked in here: render.py adds them only to the full
version, so both versions share these clips. Clips are cached in build/_shots by source file, start, length and crop.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import FPS, H, REPO, W, run, tool

CACHE = REPO / "build" / "_shots"
VERSION = 1          # bump when the preprocessing below changes, so old cached clips are not reused


def shot_key(source: Path, start, frames, x):
    stat = source.stat()
    text = json.dumps([VERSION, str(source.resolve()), stat.st_size, int(stat.st_mtime), round(start, 3), frames, round(x, 4)])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def cut(source: Path, start, frames, x, out: Path):
    vf = (f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H}:x='(iw-ow)*{x:.4f}':y='(ih-oh)/2',setsar=1,format=yuv420p,"
          # A source that runs out repeats its last frame (build.py warns about it beforehand).
          f"tpad=stop_mode=clone:stop={frames},trim=end_frame={frames},setpts=N/({FPS}*TB)")
    partial = out.with_suffix(".part.mp4")
    run([tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", source, "-t", f"{frames / FPS + 1:.3f}",
         "-an", "-vf", vf, "-frames:v", frames, "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-bf", "0",
         "-g", FPS, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
         partial])
    partial.replace(out)


def prepare_shots(project, project_dir: Path, log=print, workers=3):
    """Cached clip per shot, in order: [(shot, clip path)]."""
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs = []
    for shot in project["shots"]:
        source = (project_dir / shot["clip"]["path"]).resolve()
        if not source.is_file():
            raise SystemExit(f"镜头 {shot['id']} 缺素材：{source}")
        key = shot_key(source, shot["clip"]["in"], shot["frames"], shot["clip"]["x"])
        jobs.append((shot, source, CACHE / f"{key}.mp4"))
    todo = [job for job in jobs if not job[2].is_file()]
    if todo:
        log(f"  预处理 {len(todo)} 个镜头（共 {len(jobs)} 个，其余用缓存）")
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(lambda j: cut(j[1], j[0]["clip"]["in"], j[0]["frames"], j[0]["clip"]["x"], j[2]), todo))
    return [(shot, clip) for shot, _, clip in jobs]
