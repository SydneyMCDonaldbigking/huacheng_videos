"""Build one episode: the episode YAML plus its voice files -> timeline, captions, SRT, audio and two projects.

    python -X utf8 templates/explainer/build.py episodes/jz5.yaml [--out build/jz5] [--footage footage] [--music music]

Writes into the output folder (default build/<YAML name>):
    timing.json          every line's [start, end] in seconds, plus lead, end card, total and frame count
    subs.srt             one cue per caption screen, on the voice's timing, text from `cap`
    voice.wav            the lines placed on the timeline (48 kHz mono, as recorded)
    mix.wav              voice + ducked music, -15 LUFS, true peak about -1.5 dBTP (the full version's audio)
    voice_clean.wav      the voice alone at the same gain (the clean version's audio)
    music_stem.wav       the ducked music alone at the same gain (delivered separately)
    full/project.yaml    everything render.py needs for the full version (anchors already in seconds)
    clean/project.yaml   the same timeline with only the shots and the voice

Change the episode YAML, not these files.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FPS, HERE, RATE, REPO, Anchors, dump_yaml, frame_of, load_yaml, probe, run, tool  # noqa: E402

LOOK = {"vignette": 0.1, "grain": 1.4, "fade_out": 0.6}
CORP = {"name": "画城环保", "tagline": "产业治废 · 美画城市", "company": "成都画城环保科技有限公司", "site": "huacheng.city"}
TARGET_LUFS, LIMIT_DB = -15.0, -2.0      # the limiter's sample ceiling keeps the true peak near -1.5 dBTP

# ------------------------------------------------------------------ captions

PUNCT = "，、。？；：！,.?!;:…"
TAIL = "，、。；：,.;:"                    # dropped at the end of a screen; ？ and ！ stay
MAX_W = 14                                # about 14 Chinese characters per screen
# A point or comma between digits (1.406, 14,060) is part of the number: hidden from the splitter as these.
NUMBER_MARKS = {".": "", ",": ""}
SOFT_BREAK = "的了和与并及后在是把被就都也还而或"   # a long clause without punctuation prefers to break after these


def latin(ch):
    return ch.isascii() or ch in ""


def width(text):
    """Screen width in Chinese characters: Latin letters and digits count about half."""
    return sum(0.3 if c == " " else (0.55 if latin(c) else 1) for c in text)


def shown(text):
    text = text.strip().rstrip(TAIL).strip()
    for mark, stand_in in NUMBER_MARKS.items():
        text = text.replace(stand_in, mark)
    return text


def split_long(clause, keys):
    """A clause wider than one screen, cut into near-equal pieces, never inside a key word or a Latin/number run."""
    body = clause
    pieces = math.ceil(width(shown(body)) / MAX_W)
    if pieces <= 1:
        return [clause]
    banned = set()
    for key in keys:
        key = re.sub(r"(?<=\d)[.,](?=\d)", lambda m: NUMBER_MARKS[m.group(0)], key)
        for match in re.finditer(re.escape(key), body):
            banned.update(range(match.start() + 1, match.end()))
    for i in range(1, len(body)):
        if latin(body[i - 1]) and latin(body[i]) and (body[i - 1] + body[i]).strip():
            banned.add(i)
    cuts, last = [], 0
    for n in range(1, pieces):
        ideal = round(len(body) * n / pieces)
        options = [p for p in range(last + 1, len(body)) if p not in banned]
        if not options:
            break
        cut = min(options, key=lambda p: abs(p - ideal) - (1.6 if body[p - 1] in SOFT_BREAK else 0))
        cuts.append(cut)
        last = cut
    edges = [0, *cuts, len(body)]
    return [body[a:b] for a, b in zip(edges, edges[1:]) if body[a:b]]


def caption_screens(cap, keys):
    """Split a line's caption at punctuation into screens of at most about 14 characters, merging short clauses
    so that the screens come out as few and as even as possible."""
    cap = cap.replace("\\n", "").replace("\n", "")
    cap = re.sub(r"(?<=\d)[.,](?=\d)", lambda m: NUMBER_MARKS[m.group(0)], cap)
    clauses = re.findall(rf"[^{PUNCT}]+[{PUNCT}]*|[{PUNCT}]+", cap)
    parts = [piece for clause in clauses for piece in split_long(clause, keys)]
    n = len(parts)
    best = [0.0] + [math.inf] * n
    back = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            w = width(shown("".join(parts[i:j])))
            if w > MAX_W and j - i > 1:
                break
            cost = best[i] + 1000 + max(0.0, MAX_W - w) ** 2
            if cost < best[j]:
                best[j], back[j] = cost, i
    groups, j = [], n
    while j > 0:
        groups.append("".join(parts[back[j]:j]))
        j = back[j]
    groups.reverse()
    screens = []
    for raw in groups:
        text = shown(raw)
        if not text:
            continue
        # Time follows the spoken characters; a comma or full stop inside the screen adds a short breath.
        weight = sum(1 for c in text if c not in PUNCT) + 0.5 * sum(1 for c in raw if c in PUNCT)
        screens.append({"text": text, "weight": max(weight, 1.0), "keys": [k for k in keys if k and k in text]})
    return screens


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ------------------------------------------------------------------ audio

def decode(path, channels, start=0.0, duration=None):
    args = [tool("ffmpeg"), "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.4f}"]
    args += ["-vn", "-f", "f32le", "-ac", str(channels), "-ar", str(RATE), "-"]
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"读不了 {path}：{result.stderr.decode(errors='replace')[-800:]}")
    data = np.frombuffer(result.stdout, np.float32)
    return data.reshape(-1, channels) if channels > 1 else data


def write_audio(path, data, codec="pcm_s24le", filters=None):
    channels = 1 if data.ndim == 1 else data.shape[1]
    args = [tool("ffmpeg"), "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", str(channels), "-i", "-"]
    if filters:
        args += ["-af", filters]
    args += ["-c:a", codec, str(path)]
    result = subprocess.run(args, input=np.ascontiguousarray(data, np.float32).tobytes(), capture_output=True)
    if result.returncode:
        raise RuntimeError(f"写不了 {path}：{result.stderr.decode(errors='replace')[-800:]}")


def measure(path):
    """(integrated LUFS, true peak dBTP) from ffmpeg's EBU R128 scanner."""
    err = run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    summary = err[err.rfind("Summary:"):]
    loud = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary).group(1))
    peak = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    return loud, float(peak.group(1)) if peak else None


def limited(data, gain_db, path):
    ceiling = 10 ** (LIMIT_DB / 20)
    write_audio(path, data * 10 ** (gain_db / 20),
                filters=f"alimiter=limit={ceiling:.4f}:attack=5:release=80:level=false:latency=true")
    return measure(path)


def smooth_step(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def duck_curve(samples, first_start, last_end, open_db, duck_db, end_start):
    """Music gain in dB: open before the first line, ducked under the voice, back up for the end card."""
    t = np.arange(samples) / RATE
    down = smooth_step((t - (first_start - 0.5)) / 0.5)          # 0.5 s ramp that lands as the voice starts
    up = smooth_step((t - last_end) / max(0.3, min(0.8, end_start - last_end + 0.3)))
    duck = down * (1 - up)
    return open_db + (duck_db - open_db) * duck


def fade(data, total_s, fade_out, fade_in=0.0):
    t = np.arange(len(data)) / RATE
    gain = np.clip((total_s - t) / fade_out, 0, 1) if fade_out else np.ones(len(data))
    if fade_in:
        gain = gain * np.clip(t / fade_in, 0, 1)
    return data * (gain[:, None] if data.ndim > 1 else gain)


# ------------------------------------------------------------------ cards

def is_anchor(value):
    return (isinstance(value, (int, float, str)) and not isinstance(value, bool)) or (
        isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], (int, float))
        and not isinstance(value[1], bool))


def resolve_times(node, anchors):
    """Every `at` inside a card becomes seconds; compare's `at` may be a list of anchors."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "at":
                out[key] = anchors(value) if is_anchor(value) else [anchors(v) for v in value]
            else:
                out[key] = resolve_times(value, anchors)
        return out
    if isinstance(node, list):
        return [resolve_times(v, anchors) for v in node]
    return node


def rel(path, base):
    """Paths in project.yaml are written relative to the project folder."""
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        import os
        return Path(os.path.relpath(Path(path).resolve(), base.resolve())).as_posix()


def build(yaml_path, out=None, footage=None, music_dir=None, log=print):
    yaml_path = Path(yaml_path).resolve()
    ep = load_yaml(yaml_path)
    base = yaml_path.parent
    name = yaml_path.stem
    out = Path(out or REPO / "build" / name).resolve()
    out.mkdir(parents=True, exist_ok=True)
    warnings = []

    def where(value, default):
        path = Path(value or default)
        return path if path.is_absolute() else (base / path if value else REPO / path)

    audio_dir = where(ep.get("audio_dir"), "voice")
    footage_dir = Path(footage).resolve() if footage else where(ep.get("footage"), "footage")
    music_folder = Path(music_dir).resolve() if music_dir else where(ep.get("music_dir"), "music")
    lead, end_card = float(ep.get("lead", 2.4)), float(ep.get("end_card", 5.0))
    look = {**LOOK, **(ep.get("look") or {})}

    # Voice: the timeline is the recordings plus the pauses; nothing is stretched.
    lines, timing, clips, t = ep["lines"], {}, {}, lead
    for line in lines:
        ident = str(line["id"])
        wav = audio_dir / f"{ident}.wav"
        if not wav.is_file():
            raise SystemExit(f"缺配音：{wav}")
        info = next(s for s in probe(wav)["streams"] if s["codec_type"] == "audio")
        if int(info["sample_rate"]) != RATE or int(info.get("channels", 1)) != 1:
            warnings.append(f"{ident}.wav 是 {info['sample_rate']} Hz、{info.get('channels')} 声道，已按 48 kHz 单声道读入")
        clips[ident] = decode(wav, 1)
        duration = len(clips[ident]) / RATE
        timing[ident] = (round(t, 4), round(t + duration, 4))
        t += duration + float(line.get("pause", 0.4))
    end_start = t
    frames = frame_of(end_start + end_card)
    total = frames / FPS
    samples = frames * (RATE // FPS)
    if not 45 <= total <= 60:
        warnings.append(f"成片 {total:.1f} 秒，不在 45～60 秒之内")
    anchors = Anchors(timing)

    voice = np.zeros(samples, np.float32)
    for ident, clip in clips.items():
        at = int(round(timing[ident][0] * RATE))
        voice[at:at + len(clip)] += clip[:max(0, samples - at)]
    peak = float(np.abs(voice).max())
    if peak >= 0.999:
        warnings.append("配音里有削波（峰值到顶）")

    # Music under the voice.
    stereo_voice = np.repeat(voice[:, None], 2, axis=1)
    music = np.zeros((samples, 2), np.float32)
    spec = ep.get("music") or None
    if spec:
        path = Path(spec["file"])
        path = path if path.is_absolute() else (music_folder / path if not (base / path).is_file() else base / path)
        if not path.is_file():
            raise SystemExit(f"缺配乐：{path}")
        raw = decode(path, 2, float(spec.get("start", 0)), total)
        if len(raw) < samples - RATE // 20:
            warnings.append(f"配乐从 {spec.get('start', 0)} 秒起只有 {len(raw) / RATE:.1f} 秒，不够 {total:.1f} 秒，后面是静音")
        music[:min(samples, len(raw))] = raw[:samples]
        first, last = timing[str(lines[0]["id"])][0], timing[str(lines[-1]["id"])][1]
        curve = duck_curve(samples, first, last, float(spec.get("open_db", -9)), float(spec.get("duck_db", -20)), end_start)
        music = fade(music * (10 ** (curve / 20))[:, None], total, 0, fade_in=0.25)

    mix = fade(stereo_voice + music, total, look["fade_out"])
    loud, _ = measure_array(mix, out / "mix_raw.wav")
    gain = TARGET_LUFS - loud
    for _ in range(3):           # the limiter takes a little loudness away; correct and run again
        loud, true_peak = limited(mix, gain, out / "mix.wav")
        if abs(loud - TARGET_LUFS) <= 0.2:
            break
        gain += TARGET_LUFS - loud
    (out / "mix_raw.wav").unlink(missing_ok=True)
    clean_loud, clean_peak = limited(fade(stereo_voice, total, look["fade_out"]), gain, out / "voice_clean.wav")
    stem = fade(music, total, look["fade_out"]) * 10 ** (gain / 20)
    if np.abs(stem).max() >= 0.999:
        warnings.append("配乐分轨有削波")
    if spec:
        write_audio(out / "music_stem.wav", stem)
    write_audio(out / "voice.wav", voice, codec="pcm_s16le")

    # Captions and SRT.
    caps, cues = [], []
    starts = [timing[str(line["id"])][0] for line in lines] + [end_start]
    for n, line in enumerate(lines):
        ident = str(line["id"])
        start, stop = timing[ident]
        screens = caption_screens(str(line["cap"]), [str(k) for k in line.get("keys") or []])
        total_weight = sum(s["weight"] for s in screens)
        at = start
        for k, screen in enumerate(screens):
            until = stop if k == len(screens) - 1 else at + (stop - start) * screen["weight"] / total_weight
            cues.append((at, until, screen["text"]))
            # On screen the last caption of a line stays through the pause, so captions don't blink off.
            shown_until = starts[n + 1] if k == len(screens) - 1 else until
            caps.append({"t0": round(at, 4), "t1": round(shown_until, 4), "text": screen["text"], "keys": screen["keys"],
                         "line": ident})
            at = until
    (out / "subs.srt").write_text("".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n"
                                          for i, (a, b, text) in enumerate(cues, 1)), encoding="utf-8")

    # Cards.
    cards = []
    for card in ep.get("cards") or []:
        card = dict(card)
        kind = card.get("kind")
        card["from"] = anchors(card.get("from", 0))
        card["to"] = anchors(card["to"], end=True) if "to" in card else total
        card = resolve_times(card, anchors)
        if card["to"] <= card["from"]:
            raise SystemExit(f"{kind} 卡片的 to 早于 from：{card['from']:.2f} → {card['to']:.2f}")
        if kind == "note":
            card["y"] = card.get("y", 1262)
        cards.append(card)
    main = sorted((c for c in cards if c.get("kind") != "note"), key=lambda c: c["from"])
    for a, b in zip(main, main[1:]):
        if b["from"] < a["to"] - 1e-6:
            warnings.append(f"卡片重叠：{a['kind']}（{a['from']:.2f}–{a['to']:.2f}）和 {b['kind']}（{b['from']:.2f}–{b['to']:.2f}）")
    for note in (c for c in cards if c.get("kind") == "note"):
        for hook in (c for c in cards if c.get("kind") == "hook"):
            if note["from"] < hook["to"]:
                warnings.append(f"note 从 {note['from']:.2f} 秒开始，和片头标题卡（到 {hook['to']:.2f} 秒）同时出现")

    # Shots.
    shots, raw_shots = [], ep.get("shots") or []
    if not raw_shots:
        raise SystemExit("shots 是空的")
    starts_s = [anchors(s["at"]) for s in raw_shots]
    if starts_s[0] > 1e-6:
        raise SystemExit("第一个镜头要从 0 开始")
    if any(b <= a for a, b in zip(starts_s, starts_s[1:])):
        raise SystemExit("镜头的 at 要按时间先后排")
    ends = starts_s[1:] + [end_start]
    end_spec = ep.get("end")
    if not end_spec:
        raise SystemExit("缺 end：片尾品牌卡下面的背景镜头")
    entries = [(f"s{i + 1:02d}", s, a, b) for i, (s, a, b) in enumerate(zip(raw_shots, starts_s, ends))]
    entries.append(("end", end_spec, end_start, total))
    for ident, spec_, a, b in entries:
        clip = dict(spec_.get("clip") or {})
        if "px" in clip:
            source = footage_dir / f"{clip['px']}.mp4"
        elif "file" in clip:
            source = Path(clip["file"])
            source = source if source.is_absolute() else base / source
        else:
            raise SystemExit(f"镜头 {ident} 没有 clip.px 或 clip.file")
        f0, f1 = frame_of(a), frame_of(b)
        if f1 <= f0:
            raise SystemExit(f"镜头 {ident} 短于一帧")
        length = (f1 - f0) / FPS
        if ident != "end" and not 2.4 <= length <= 8.0:      # 2.4: a first shot that only covers the lead
            warnings.append(f"镜头 {ident}（{clip.get('px', clip.get('file'))}）长 {length:.1f} 秒，建议 2.5～8 秒")
        if source.is_file():
            have = float(probe(source)["format"].get("duration", 0))
            if float(clip.get("in", 0)) + length > have + 0.01:
                warnings.append(f"镜头 {ident}：素材 {source.name} 只有 {have:.1f} 秒，从 {clip.get('in', 0)} 秒起不够 {length:.1f} 秒")
        else:
            warnings.append(f"镜头 {ident}：还没有素材文件 {source}")
        shots.append({"id": ident, "t0": round(a, 4), "f0": f0, "frames": f1 - f0,
                      "clip": {"path": str(source), "in": float(clip.get("in", 0)), "x": float(clip.get("x", 0.5)),
                               **({"px": clip["px"]} if "px" in clip else {})},
                      "dim": float(spec_.get("dim", 0.55 if ident == "end" else 0)),
                      "blur": float(spec_.get("blur", 3 if ident == "end" else 0))})

    corp = {**CORP, **(ep.get("corp") or {}), "series": ep.get("series", "")}
    logo = Path(ep["logo"]) if ep.get("logo") else HERE / "assets" / "logo_icon.png"
    logo = logo if logo.is_absolute() else base / logo
    hook_end = max((c["to"] for c in cards if c.get("kind") == "hook"), default=0.0)
    common = {"template": "explainer", "name": name, "title": ep.get("title", ""), "ep": ep.get("ep"),
              "series": ep.get("series", ""), "music": Path(spec["file"]).name if spec else None,
              "canvas": {"w": 1080, "h": 1920, "fps": FPS}, "frames": frames, "duration": round(total, 4), "look": look}
    for version in ("full", "clean"):
        folder = out / version
        folder.mkdir(exist_ok=True)
        project = {**common, "version": version,
                   "audio": rel(out / ("mix.wav" if version == "full" else "voice_clean.wav"), folder),
                   "shots": [{**s, "clip": {**s["clip"], "path": rel(s["clip"]["path"], folder)},
                              **({"dim": 0, "blur": 0} if version == "clean" else {})} for s in shots]}
        if version == "full":
            project.update(assets={"logo": rel(logo, folder)}, corp=corp, hook_end=round(hook_end, 4),
                           end={"t0": round(end_start, 4), "t1": round(total, 4), "next": ep.get("next") or ""},
                           caps=caps, cards=cards)
        dump_yaml(project, folder / "project.yaml")

    report = {"lines": {k: list(v) for k, v in timing.items()}, "lead": lead,
              "end_card": [round(end_start, 4), round(total, 4)], "duration": round(total, 4), "frames": frames,
              "audio": {"gain_db": round(gain, 2), "mix_lufs": loud, "mix_true_peak": true_peak,
                        "clean_lufs": clean_loud, "clean_true_peak": clean_peak, "voice_peak": round(peak, 4)},
              "warnings": warnings}
    (out / "timing.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{name}：{total:.2f} 秒，{frames} 帧，{len(lines)} 句，{len(caps)} 屏字幕，{len(cards)} 张卡片，{len(shots)} 个镜头")
    log(f"  完整版音频 {loud:.1f} LUFS，真峰值 {true_peak} dBTP；输出在 {out}")
    for warning in warnings:
        log(f"  注意：{warning}")
    return out, report


def measure_array(data, path):
    write_audio(path, data, codec="pcm_f32le")
    return measure(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="构建一集讲解片的工程")
    parser.add_argument("episode", help="分集 YAML")
    parser.add_argument("--out", help="输出文件夹，默认 build/<YAML 文件名>")
    parser.add_argument("--footage", help="素材文件夹（<Pexels 编号>.mp4），默认 YAML 的 footage 或仓库的 footage/")
    parser.add_argument("--music", help="配乐文件夹，默认 YAML 的 music_dir 或仓库的 music/")
    args = parser.parse_args(argv)
    build(args.episode, args.out, args.footage, args.music)


if __name__ == "__main__":
    main()
