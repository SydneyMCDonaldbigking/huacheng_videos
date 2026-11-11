# 讲解模板 `templates/explainer/`

2026-11-09 按 [docs/04](../../docs/04_模板说明.md) 重建。原来的模板和私有仓库里的渲染引擎都不用了：这里从分集 YAML 到四个交付文件，一条路走完。

## 一集怎么出

在仓库根目录运行（Windows 上一律加 `-X utf8`）：

```powershell
$py = "D:\anaconda\envs\huacheng\python.exe"
& $py -X utf8 templates/explainer/build.py episodes/jz5.yaml          # 时间轴、字幕、SRT、配音配乐、两个工程
& $py -X utf8 templates/explainer/render.py build/jz5 --preview       # 540×960 预览 + 联系表，改 YAML 重来
& $py -X utf8 templates/explainer/render.py build/jz5                 # 正式出完整版和无字幕版，各带联系表
& $py -X utf8 templates/explainer/check.py build/jz5                  # docs/06 的机械检查
& $py -X utf8 templates/explainer/deliver.py --to "D:/成片_<系列名>" build/jz1 build/jz2 ...
```

改片子只改分集 YAML，然后从 `build.py` 重来。镜头预处理有缓存（`build/_shots/`），重来时只有改过的镜头会重新裁。

## 文件

| 文件 | 做什么 |
|---|---|
| `build.py` | 读分集 YAML 和配音，算时间轴，拆字幕，写 `subs.srt`、`timing.json`、`voice.wav`，混出 `mix.wav`（−15 LUFS）、`voice_clean.wav`、`music_stem.wav`，生成 `full/project.yaml` 和 `clean/project.yaml` |
| `template.py` | 素材预处理：裁成 9:16（按 `clip.x`）、统一 30 fps、按帧数精确截取，缓存到 `build/_shots/` |
| `overlay.js` | 卡片、字幕、角标、片尾卡的画法和动画，在透明画布上画 |
| `render.py` | 用 Playwright 驱动 Edge/Chromium 逐帧画叠加层，ffmpeg 合成：压暗模糊、叠加层、暗角、颗粒、淡出、编码；出联系表 |
| `check.py` | 帧数、规格、色彩标记、响度、冻帧、时长、SRT，写 `out/check.json` |
| `deliver.py` | 复制成 docs/06 的交付文件夹，写 `素材来源.md` |
| `make_logo.py` | 从官网 logo 抠出透明底图标 `assets/logo_icon.png` |
| `common.py` | 共用：找 ffmpeg、读 YAML、时间锚点换算 |
| `demo/` | 测试用的两集 YAML 和生成测试素材的 `make_demo.py` |

产物都在 `build/<名字>/`，成片在 `build/<名字>/out/`。`build/`、`work/`、`footage/`、`music/` 都不进 git。

## 环境

```powershell
conda env create -p D:/anaconda/envs/huacheng -f templates/explainer/environment.yml
```

- Python 3.12、numpy、Pillow、PyYAML、ffmpeg（conda-forge），pip 装 Playwright。
- 浏览器：先找 Playwright 自带的 Chromium，没有就用本机的 Edge 或 Chrome，不用另外下载。
- 字体：按顺序找思源黑体（Source Han Sans SC）、Noto Sans SC（Windows 11 自带 `NotoSansSC-VF.ttf`）、微软雅黑粗体。要指定就设环境变量 `HC_FONT` 指向字体文件。
- 素材默认在仓库根目录的 `footage/<Pexels 编号>.mp4`，配乐在 `music/`；分集 YAML 可以用 `footage:`、`music_dir:` 改。

## 测试

```powershell
& $py -X utf8 templates/explainer/demo/make_demo.py                   # 生成测试素材到 work/demo/
& $py -X utf8 templates/explainer/build.py templates/explainer/demo/jz5.yaml
& $py -X utf8 templates/explainer/render.py build/jz5
& $py -X utf8 templates/explainer/check.py build/jz5
```

`demo/jz5.yaml` 是 docs/03 的例子原样照搬，`demo/cards.yaml` 把其余各种卡片各放一张。测试素材是程序生成的画面，配音是 Windows 自带的 Huihui，只用来测时间轴和字幕，**成片不能用**。

## 重建时自己定的参数

docs/04 只写了样子，没写数值的地方，按下面定。拿到以前交付的成片后，可以对照着改这些数。

| 项目 | 定成 | 在哪改 |
|---|---|---|
| 字幕 | 中心 y=1395，66 px 粗体，白字深色描边，一屏最多约 14 字；一句的最后一屏在句间停顿里继续显示，SRT 仍按配音时间 | `overlay.js` `captions()`，`build.py` `MAX_W` |
| 角标 | 左上角 (48, 96)，图标高 92 px，半透明深色底；片头标题卡结束后淡入 | `overlay.js` `badge()` |
| `blur` | ffmpeg `gblur`，sigma = blur × 2 | `render.py` `BLUR_SIGMA` |
| `dim` | 亮度和色度按 (1 − dim) 缩放 | `render.py` `filter_graph()` |
| 片尾背景 | 不写就压暗 0.55、模糊 3 | `build.py` |
| 暗角 0.1 | 四角最多压暗 30%，中心不变 | `render.py` `vignette_png()` |
| 颗粒 1.4 | 亮度噪声标准差约 1.4 级（ffmpeg `noise=c0s=5:c0f=t+u`，实测） | `render.py` `GRAIN_STRENGTH` |
| 配乐避让 | 第一句前 0.5 秒内从 `open_db` 降到 `duck_db`，最后一句后升回；配乐开头 0.25 秒淡入 | `build.py` `duck_curve()` |
| 响度 | 整体增益到 −15 LUFS，再过 −2 dBFS 的限幅器，真峰值约 −1.5～−2 dBTP | `build.py` |
| 无字幕版 | 也带暗角、颗粒和结尾淡出（这些算画面质感，不算叠加物）；人声和完整版同一增益 | `render.py`、`build.py` |
| 片尾卡末句 | 最后一句的 `pause` 也算，片尾卡从这个停顿之后开始 | `build.py` |
