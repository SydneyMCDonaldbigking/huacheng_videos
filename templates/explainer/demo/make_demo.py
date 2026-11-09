"""Test material for the template, written to work/demo/ (not in git):

    python -X utf8 templates/explainer/demo/make_demo.py

- footage/<id>.mp4 for every Pexels id the demo episodes use: synthetic moving pictures in the sizes and frame rates
  real footage comes in (landscape 1080p at 25/30/60 fps, portrait, 4K at 24 fps), each labelled with its id and a
  running clock so the contact sheet shows which shot and which second is on screen;
- music/demo_pad.wav: a synthetic pad to test ducking;
- voice/<line id>.wav and voice/lines.json: the demo lines read by the Windows voice (Huihui), 48 kHz mono. On other
  systems, tone bursts of a plausible length instead.

The voice is only a stand-in for testing timing and captions. Finished videos never use a local TTS voice.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import REPO, load_yaml, run, tool  # noqa: E402
from render import font_faces  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = REPO / "work" / "demo"

# (size, fps, picture) by position, so the demo covers the formats real footage comes in.
LOOKS = [
    ("1920x1080", 25, "gradients=s={s}:r={r}:speed=0.02:c0=0x2a5d3a:c1=0x0e2a44:c2=0x6b7d2a:n=3"),
    ("1920x1080", 30, "mandelbrot=s={s}:r={r}:inner=convergence:maxiter=200"),
    ("1080x1920", 30, "gradients=s={s}:r={r}:speed=0.03:c0=0x3a4a2a:c1=0x1d3346:n=2:type=radial"),
    ("1920x1080", 60, "testsrc2=s={s}:r={r}"),
    ("3840x2160", 24, "gradients=s={s}:r={r}:speed=0.015:c0=0x55402a:c1=0x203a28:c2=0x2c3f52:n=3:type=circular"),
    ("1920x1080", 30, "life=s=480x270:r={r}:mold=10:ratio=0.2:life_color=0x8fd18f:death_color=0x1a2a1a,scale=size={s}:flags=neighbor"),
]


def footage_ids():
    ids = []
    for name in ("jz5.yaml", "cards.yaml"):
        episode = load_yaml(HERE / name)
        for shot in [*episode["shots"], episode["end"]]:
            px = shot["clip"]["px"]
            if px not in ids:
                ids.append(px)
    return ids


def make_footage(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    font = font_faces()[0][0].as_posix().replace(":", r"\:")
    for n, px in enumerate(footage_ids()):
        out = folder / f"{px}.mp4"
        if out.is_file():
            continue
        size, rate, picture = LOOKS[n % len(LOOKS)]
        width = int(size.split("x")[0])
        label = (f"drawtext=fontfile='{font}':text='px {px}  {size} {rate}fps':x=(w-tw)/2:y=h*0.42:fontsize={width // 24}"
                 f":fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=12,"
                 f"drawtext=fontfile='{font}':text='%{{pts\\:hms}}':x=(w-tw)/2:y=h*0.52:fontsize={width // 18}"
                 f":fontcolor=0x3CD764:box=1:boxcolor=black@0.5:boxborderw=12")
        run([tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", picture.format(s=size, r=rate), "-t", "30",
             "-vf", f"{label},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out])
        print(f"素材 {out.name}（{size}，{rate} fps）")


def make_music(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "demo_pad.wav"
    if not out.is_file():
        chord = "+".join(f"0.12*sin(2*PI*{f}*t)" for f in (110, 164.8, 220, 277.2, 329.6))
        run([tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
             f"aevalsrc=({chord})*(0.75+0.25*sin(2*PI*0.25*t)):s=48000:c=stereo:d=120", "-c:a", "pcm_s16le", out])
        print(f"配乐 {out.name}")


def make_voice(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    lines = load_yaml(HERE / "jz5.yaml")["lines"]
    (folder / "lines.json").write_text(json.dumps({l["id"]: l["cap"] for l in lines}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    todo = [{"path": str(folder / f"{l['id']}.wav"), "text": l["cap"]} for l in lines
            if not (folder / f"{l['id']}.wav").is_file()]
    if not todo:
        return
    if os.name == "nt":
        script = r"""
Add-Type -AssemblyName System.Speech
$lines = Get-Content -Raw -Encoding UTF8 $args[0] | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Huihui Desktop')
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($l in $lines) { $s.SetOutputToWaveFile($l.path, $fmt); $s.Speak($l.text) }
$s.SetOutputToNull()
"""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "say.ps1").write_text(script, encoding="utf-8-sig")
            (Path(tmp) / "lines.json").write_text(json.dumps(todo, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(Path(tmp) / "say.ps1"), str(Path(tmp) / "lines.json")], capture_output=True)
        if result.returncode == 0 and all(Path(l["path"]).is_file() for l in todo):
            print(f"配音（测试用 Huihui）{len(todo)} 句")
            return
        print("系统语音不可用，改用提示音代替配音")
    for line in todo:
        seconds = max(2.0, len(line["text"]) / 5)
        run([tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
             f"aevalsrc=0.3*sin(2*PI*180*t)*(0.5+0.5*sin(2*PI*4*t)):s=48000:c=mono:d={seconds:.2f}",
             "-c:a", "pcm_s16le", line["path"]])


def main():
    make_footage(OUT / "footage")
    make_music(OUT / "music")
    make_voice(OUT / "voice")
    print(f"测试素材在 {OUT}")


if __name__ == "__main__":
    main()
