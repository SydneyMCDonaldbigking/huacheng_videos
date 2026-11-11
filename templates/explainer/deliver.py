"""Copy checked episodes into the delivery folder that docs/06 describes, and write 素材来源.md.

    python -X utf8 templates/explainer/deliver.py --to "D:/成片_建筑垃圾资源化" build/jz1 build/jz2 ... \
        [--sources 素材清单.txt]

Each episode gets NN_<title>/ with NN_完整版.mp4, NN_无字幕版.mp4, NN_字幕.srt and NN_配乐（已避让）.wav. NN is the
YAML's `ep` (else the order given), the folder name is its `title` with punctuation turned into underscores. An
episode whose out/check.json is missing or failed is refused unless --force.

素材来源.md lists every Pexels clip and every music file per episode. With --sources (the footage list in the format
docs/05 gives: 编号|宽x高|时长|帧率|作者|标题|…), the author and title are filled in; otherwise they are left as
「待填」. 发布文案.md is written by hand.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_yaml  # noqa: E402

FILES = [("{name}.mp4", "{nn}_完整版.mp4"), ("{name}_clean.mp4", "{nn}_无字幕版.mp4")]


def safe(title):
    return re.sub(r"_+", "_", re.sub(r"[，。？！、：；·“”‘’\"'/\\:*?<>|\s,.!?;()（）]", "_", title)).strip("_")


def read_sources(path):
    rows = {}
    if path:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("|")
            if len(parts) >= 6 and parts[0].strip().isdigit():
                rows[parts[0].strip()] = {"author": parts[4].strip(), "title": parts[5].strip()}
    return rows


def deliver(target, builds, sources=None, force=False, log=print):
    target = Path(target)
    known = read_sources(sources)
    footage, music = {}, {}
    for n, build in enumerate(builds, 1):
        build = Path(build).resolve()
        project = load_yaml(build / "full" / "project.yaml")
        name = project["name"]
        report = build / "out" / "check.json"
        ok = report.is_file() and json.loads(report.read_text(encoding="utf-8")).get("ok")
        if not ok and not force:
            raise SystemExit(f"{name}：检查没通过或没跑过（{report}），先跑 check.py；确实要交付加 --force")
        nn = f"{int(project.get('ep') or n):02d}"
        title = project.get("title") or name
        folder = target / f"{nn}_{safe(title)}"
        folder.mkdir(parents=True, exist_ok=True)
        for src, dst in FILES:
            shutil.copy2(build / "out" / src.format(name=name), folder / dst.format(nn=nn))
        shutil.copy2(build / "subs.srt", folder / f"{nn}_字幕.srt")
        if (build / "music_stem.wav").is_file():
            shutil.copy2(build / "music_stem.wav", folder / f"{nn}_配乐（已避让）.wav")
        for shot in project["shots"]:
            if "px" in shot["clip"]:
                footage.setdefault(str(shot["clip"]["px"]), []).append(nn)
        if project.get("music"):
            music.setdefault(project["music"], []).append(nn)
        log(f"{nn} {title} → {folder}")

    lines = ["# 素材来源", "",
             "- 视频素材来自 Pexels，Pexels License，可免费商用，不要求署名。",
             "- 配乐来自 Pixabay，Pixabay Content License，所选曲目没有 Content ID，也不是 AI 生成。", "",
             "## 配乐", "", "| Pixabay 编号 | 曲目 | 用在 |", "|---|---|---|"]
    for file, eps in music.items():
        number, _, rest = Path(file).stem.partition("_")      # Pixabay files are named <number>_<title>
        if not number.isdigit():
            number, rest = "待填", Path(file).stem
        lines.append(f"| {number} | {rest or file} | {', '.join(sorted(set(eps)))} |")
    lines += ["", "## 视频素材", "", "| Pexels 编号 | 作者 | 标题 | 用在 |", "|---|---|---|---|"]
    for px, eps in footage.items():
        row = known.get(px, {})
        lines.append(f"| [{px}](https://www.pexels.com/video/{px}/) | {row.get('author', '待填')} | "
                     f"{row.get('title', '待填')} | {', '.join(sorted(set(eps)))} |")
    (target / "素材来源.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    missing = [px for px in footage if px not in known]
    log(f"素材来源.md：{len(footage)} 段素材，{len(music)} 首配乐" + (f"，{len(missing)} 段的作者和标题待填" if missing else ""))
    if not (target / "发布文案.md").is_file():
        log("还没有 发布文案.md：按 docs/06 的格式手写")


def main(argv=None):
    parser = argparse.ArgumentParser(description="整理交付文件夹")
    parser.add_argument("builds", nargs="+", help="build/<名字>，按集的顺序")
    parser.add_argument("--to", required=True, help="交付文件夹，比如 D:/成片_建筑垃圾资源化")
    parser.add_argument("--sources", help="素材清单（docs/05 的格式），用来填作者和标题")
    parser.add_argument("--force", action="store_true", help="检查没通过也照样复制")
    args = parser.parse_args(argv)
    deliver(args.to, args.builds, args.sources, args.force)


if __name__ == "__main__":
    main()
