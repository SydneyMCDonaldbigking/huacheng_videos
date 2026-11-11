"""Mechanical checks of a rendered episode, as docs/06 lists them.

    python -X utf8 templates/explainer/check.py build/jz5

Checks out/<name>.mp4 and out/<name>_clean.mp4: frame counts (equal to each other and to the project), format
(1080×1920, 30 fps, H.264, BT.709 limited range, AAC 48 kHz stereo), loudness of the full version (about -15 LUFS,
true peak at most -1 dBTP), frozen pictures, length (45–60 s) and subs.srt. Writes out/check.json; exits 1 when a
hard check fails.

Freeze detection runs on a 1/8-size picture, so the grain (which changes every frame) does not hide a frozen shot.
A freeze in the full version that the clean version does not have is the dimmed, blurred shot under a card moving
too little: reported, not a failure. A freeze in both is footage that does not move: replace it or start it elsewhere.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import measure  # noqa: E402
from common import load_yaml, probe, run, tool  # noqa: E402


def frame_count(path):
    out = run([tool("ffprobe"), "-v", "error", "-count_packets", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path]).stdout
    return int(out.strip())


def freezes(path):
    err = run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-an", "-vf",
               "scale=iw/8:ih/8:flags=area,freezedetect=n=0.003:d=1.0", "-f", "null", "-"]).stderr
    starts = [float(v) for v in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(v) for v in re.findall(r"freeze_end: ([\d.]+)", err)]
    duration = float(probe(path)["format"]["duration"])
    return [(round(s, 2), round(ends[i] if i < len(ends) else duration, 2)) for i, s in enumerate(starts)]


def srt_cues(path):
    cues = []
    for block in Path(path).read_text(encoding="utf-8-sig").strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        a, b = lines[1].split(" --> ")
        to_s = lambda s: sum(float(x) * m for x, m in zip(s.replace(",", ".").split(":"), (3600, 60, 1)))  # noqa: E731
        cues.append((to_s(a), to_s(b), "\n".join(lines[2:])))
    return cues


def check(build_dir, log=print):
    build_dir = Path(build_dir).resolve()
    project = load_yaml(build_dir / "full" / "project.yaml")
    name, frames = project["name"], project["frames"]
    videos = {"full": build_dir / "out" / f"{name}.mp4", "clean": build_dir / "out" / f"{name}_clean.mp4"}
    results, failed = [], False

    def item(what, ok, detail, hard=True):
        nonlocal failed
        failed |= hard and not ok
        results.append({"check": what, "ok": ok, "detail": detail, "hard": hard})
        log(f"  {'✓' if ok else ('✗' if hard else '!')} {what}：{detail}")

    log(f"检查 {name}")
    found = {}
    for version, path in videos.items():
        if not path.is_file():
            item(f"{version} 文件", False, f"没有 {path.name}，先跑 render.py")
            continue
        info = probe(path)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
        count = frame_count(path)
        found[version] = path
        item(f"{version} 帧数", count == frames, f"{count}（工程 {frames}）")
        fmt_ok = (v["codec_name"], v["width"], v["height"], v["r_frame_rate"], v.get("pix_fmt")) == ("h264", 1080, 1920, "30/1", "yuv420p")
        item(f"{version} 画面规格", fmt_ok, f"{v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']} {v.get('pix_fmt')}")
        tags = tuple(v.get(k) for k in ("color_space", "color_range", "color_primaries", "color_transfer"))
        item(f"{version} 色彩标记", tags == ("bt709", "tv", "bt709", "bt709"), " / ".join(str(t) for t in tags))
        audio_ok = (a.get("codec_name"), a.get("sample_rate"), a.get("channels")) == ("aac", "48000", 2)
        item(f"{version} 音频规格", audio_ok, f"{a.get('codec_name')} {a.get('sample_rate')} Hz {a.get('channels')} 声道")
    if len(found) == 2:
        item("两个版本帧数一致", frame_count(found["full"]) == frame_count(found["clean"]), "完整版和无字幕版")
    if "full" in found:
        loud, peak = measure(found["full"])
        item("完整版响度", -16 <= loud <= -14, f"{loud:.1f} LUFS（目标 -15）")
        item("完整版真峰值", peak is not None and peak <= -1.0, f"{peak} dBTP（不高于 -1）")
    seconds = frames / project["canvas"]["fps"]
    item("时长", 45 <= seconds <= 60, f"{seconds:.1f} 秒（45～60）", hard=False)

    frozen = {version: freezes(path) for version, path in found.items()}
    for a, b in frozen.get("full", []):
        real = any(c < b and a < d for c, d in frozen.get("clean", []))
        if real:
            item("冻帧", False, f"完整版 {a}–{b} 秒，无字幕版同一段也不动：素材本身不动，换素材或换起点")
        else:
            item("冻帧", True, f"完整版 {a}–{b} 秒；无字幕版这段在动，是卡片下压暗模糊造成的，不算", hard=False)
    for a, b in frozen.get("clean", []):
        if not any(c < b and a < d for c, d in frozen.get("full", [])):
            item("冻帧", False, f"无字幕版 {a}–{b} 秒不动")
    if not any(frozen.values()):
        item("冻帧", True, "没有")

    srt = build_dir / "subs.srt"
    if srt.is_file():
        cues = srt_cues(srt)
        ordered = all(a < b for a, b, _ in cues) and all(p[1] <= q[0] + 1e-3 for p, q in zip(cues, cues[1:]))
        inside = all(b <= seconds + 1e-3 for _, b, _ in cues)
        item("字幕 SRT", bool(cues) and ordered and inside and all(t.strip() for *_, t in cues),
             f"{len(cues)} 条，时间{'有序' if ordered else '有重叠或倒序'}{'' if inside else '，有超出片长的'}")
    else:
        item("字幕 SRT", False, "没有 subs.srt")

    report = {"name": name, "ok": not failed, "frames": frames, "seconds": round(seconds, 3),
              "freezes": frozen, "checks": results}
    (build_dir / "out").mkdir(exist_ok=True)
    (build_dir / "out" / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log("通过" if not failed else "有没通过的项")
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(0 if check(sys.argv[1])["ok"] else 1)
