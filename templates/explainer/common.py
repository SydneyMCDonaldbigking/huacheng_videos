"""Shared helpers for the explainer template: tools, YAML, time anchors."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FPS = 30
W, H = 1080, 1920
RATE = 48000


def tool(name):
    """ffmpeg / ffprobe from PATH, else the conda env's Library/bin next to this Python."""
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path(sys.executable).parent / "Library" / "bin", Path(sys.executable).parent):
        candidate = folder / (name + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f"找不到 {name}：请在环境里装 ffmpeg（conda install -c conda-forge ffmpeg）")


def run(args, **kw):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", **kw)
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} 失败：\n{result.stderr[-3000:]}")
    return result


def probe(path):
    out = run([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path]).stdout
    return json.loads(out)


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))


def dump_yaml(data, path):
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")


def frame_of(seconds):
    return int(round(seconds * FPS))


class Anchors:
    """Turns the episode YAML's time anchors into seconds.

    0 or any number  -> that second
    ID               -> the line's start (as `to`: its end)
    [ID, f]          -> start + f × the line's duration
    "ID+1.2"         -> the line's end + 1.2 s ("ID-0.3" also works)
    """

    def __init__(self, timing):
        self.timing = timing          # id -> (start, end)

    def _line(self, ident):
        if ident not in self.timing:
            raise ValueError(f"时间锚点里的句子编号 {ident!r} 不存在")
        return self.timing[ident]

    def __call__(self, value, end=False):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            start, stop = self._line(str(value[0]))
            return start + float(value[1]) * (stop - start)
        if isinstance(value, str):
            match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s*([+-])\s*([0-9.]+)\s*", value)
            if match:
                _, stop = self._line(match.group(1))
                return stop + (1 if match.group(2) == "+" else -1) * float(match.group(3))
            start, stop = self._line(value.strip())
            return stop if end else start
        raise ValueError(f"看不懂的时间锚点：{value!r}")
