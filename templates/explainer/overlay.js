// Explainer overlay: info cards, captions, the corner badge and the end card, drawn on a transparent 1080×1920
// canvas. render.py first asks __keys(n) for every frame's key, then for each new key calls __draw(f) and takes a
// screenshot; frames whose animations have all settled share a key, so only frames that move are drawn.
(() => {
  const P = window.PROJECT;
  const W = 1080, H = 1920, FPS = P.canvas.fps, S = P.scale || 1;
  const canvas = document.getElementById('c');
  canvas.width = Math.round(W * S); canvas.height = Math.round(H * S);
  const real = canvas.getContext('2d');
  const logo = document.getElementById('logo');
  const G = '#3CD764', RED = '#FF5A4E', BLUE = '#4FB8E8', WHITE = '#FFFFFF', SUB = '#B9C6BE', DARK = '#06140A';
  const TONES = {
    g: {accent: G, fill: 'rgba(14, 28, 18, .88)', line: 'rgba(60, 215, 100, .6)'},
    bad: {accent: RED, fill: 'rgba(40, 15, 14, .88)', line: 'rgba(255, 90, 78, .62)'},
    in: {accent: BLUE, fill: 'rgba(10, 24, 34, .88)', line: 'rgba(79, 184, 232, .62)'},
    plain: {accent: WHITE, fill: 'rgba(16, 22, 19, .88)', line: 'rgba(255, 255, 255, .32)'},
  };
  TONES.prod = TONES.g; TONES.waste = TONES.bad;
  const tone = name => TONES[name] || TONES.plain;

  // ---------------------------------------------------------------- frame state
  // While computing keys, drawing goes to a do-nothing context; only the timing helpers below run for real.
  const noop = () => {};
  const dry = new Proxy({}, {
    get: (_, k) => k === 'measureText' ? () => ({width: 0}) : (String(k).startsWith('create') ? () => ({addColorStop: noop}) : noop),
    set: () => true,
  });
  let ctx = real, t = 0, marks = [], seen = [], moving = false;

  const clamp = x => Math.max(0, Math.min(1, x));
  const ease = p => 1 - Math.pow(1 - p, 3);
  // Progress of an animation starting at t0 and lasting d seconds. Every call is part of the frame's key.
  function prog(t0, d) {
    const p = d <= 0 ? (t >= t0 ? 1 : 0) : clamp((t - t0) / d);
    if (p > 0 && p < 1) moving = true;
    marks.push(p >= 1 ? 1 : p <= 0 ? 0 : 2);
    return p;
  }
  // An element shown from `from` to `to`: fades in over `enter`, out over `exit` (ending at `to`).
  function life(id, from, to, enter = .4, exit = .3) {
    if (t < from || t >= to) return null;
    seen.push(id);
    const span = to - from;
    enter = Math.min(enter, span / 2); exit = Math.min(exit, span / 2);
    const a = ease(prog(from, enter)), b = exit > 0 ? prog(to - exit, exit) : 0;
    return {in: a, out: b, alpha: a * (1 - b)};
  }

  // ---------------------------------------------------------------- text
  const font = (size, weight = 700) => { ctx.font = `${weight} ${size}px HC`; };
  // "*绿色*" marks highlighted runs, "\n" breaks lines.
  function rich(text) {
    return String(text ?? '').replace(/\\n/g, '\n').split('\n').map(line => {
      const runs = [];
      line.split('*').forEach((part, i) => { if (part) runs.push({text: part, hi: i % 2 === 1}); });
      return runs;
    });
  }
  const widthOf = runs => runs.reduce((w, r) => w + ctx.measureText(r.text).width, 0);
  // Largest size up to `size` at which every line fits into maxW.
  function fit(lines, size, weight, maxW, min = 18) {
    for (; size > min; size -= 2) { font(size, weight); if (Math.max(0, ...lines.map(widthOf)) <= maxW) break; }
    font(size, weight);
    return size;
  }
  function drawRuns(runs, x, y, {align = 'left', color = WHITE, hi = G, stroke = null, strokeW = 0} = {}) {
    const w = widthOf(runs);
    const left = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    if (stroke) {
      ctx.save(); ctx.strokeStyle = stroke; ctx.lineWidth = strokeW; ctx.lineJoin = 'round';
      let cx = left;
      for (const r of runs) { ctx.strokeText(r.text, cx, y); cx += ctx.measureText(r.text).width; }
      ctx.restore();
    }
    let cx = left;
    for (const r of runs) { ctx.fillStyle = r.hi ? hi : color; ctx.fillText(r.text, cx, y); cx += ctx.measureText(r.text).width; }
    return w;
  }
  function textLines(text, x, y, {size, weight = 800, maxW = 936, lh = 1.22, align = 'center', color = WHITE, hi = G, min} = {}) {
    const lines = rich(text);
    const s = fit(lines, size, weight, maxW, min);
    ctx.textBaseline = 'middle';
    lines.forEach((runs, i) => drawRuns(runs, x, y + i * s * lh, {align, color, hi}));
    return {size: s, height: lines.length * s * lh, lines: lines.length};
  }
  // Runs for a caption: the key words in green.
  function keyed(text, keys) {
    const on = Array.from(text, () => false);
    for (const key of keys || []) {
      if (!key) continue;
      for (let i = text.indexOf(key); i >= 0; i = text.indexOf(key, i + 1)) for (let k = 0; k < key.length; k++) on[i + k] = true;
    }
    const runs = [];
    Array.from(text).forEach((ch, i) => {
      if (runs.length && runs[runs.length - 1].hi === on[i]) runs[runs.length - 1].text += ch;
      else runs.push({text: ch, hi: on[i]});
    });
    return runs;
  }
  function format(value, dec) {
    return Number(value).toFixed(dec);
  }
  const decimals = (c, v) => c.dec ?? ((String(v).split('.')[1] || '').length);
  const numeric = v => typeof v === 'number' || (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v.trim()));

  // ---------------------------------------------------------------- shapes
  function panel(x, y, w, h, {r = 24, fill = TONES.g.fill, line = TONES.g.line, lw = 2.5} = {}) {
    ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (line) { ctx.strokeStyle = line; ctx.lineWidth = lw; ctx.stroke(); }
  }
  function circle(x, y, r, fill, line, lw = 3) {
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (line) { ctx.strokeStyle = line; ctx.lineWidth = lw; ctx.stroke(); }
  }
  function chip(text, x, y, {size = 36, fill = G, color = DARK, align = 'left', padX = 22, h} = {}) {
    font(size, 900);
    const w = ctx.measureText(text).width + padX * 2, hh = h || size * 1.7;
    const left = align === 'center' ? x - w / 2 : x;
    panel(left, y, w, hh, {r: hh / 2, fill, line: null});
    ctx.fillStyle = color; ctx.textBaseline = 'middle'; ctx.fillText(text, left + padX, y + hh / 2 + 1);
    return w;
  }
  function shadow(blur = 14, alpha = .55) { ctx.shadowColor = `rgba(0, 0, 0, ${alpha})`; ctx.shadowBlur = blur; ctx.shadowOffsetY = 2; }
  function noShadow() { ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0; }

  // ---------------------------------------------------------------- cards
  const CARDS = {};

  CARDS.hook = (c, L) => {
    const y = c.y ?? 700, x = 72;
    ctx.globalAlpha = L.alpha;
    const g = ctx.createLinearGradient(0, y - 300, 0, y + 760);
    g.addColorStop(0, 'rgba(0, 0, 0, 0)'); g.addColorStop(.3, 'rgba(0, 0, 0, .5)');
    g.addColorStop(.75, 'rgba(0, 0, 0, .5)'); g.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = g; ctx.fillRect(0, y - 300, W, 1060);
    const k = ease(prog(c.from, .4));
    ctx.globalAlpha = L.alpha * k;
    if (c.kicker) chip(c.kicker, x - (1 - k) * 30, y, {size: 40});
    const lines = rich(c.title), size = fit(lines, 124, 900, W - 2 * x), lh = size * 1.2;
    const top = y + (c.kicker ? 110 : 0) + size * .6;
    shadow(18, .6); ctx.textBaseline = 'middle';
    lines.forEach((runs, i) => {
      const a = ease(prog(c.from + .1 + .1 * i, .45));
      ctx.globalAlpha = L.alpha * a;
      font(size, 900); drawRuns(runs, x, top + i * lh + (1 - a) * 36);
    });
    noShadow();
    const by = top + lines.length * lh - size * .2 + 24;
    const bar = ease(prog(c.from + .35 + .1 * lines.length, .4));
    ctx.globalAlpha = L.alpha;
    panel(x, by, 96 * bar, 10, {r: 5, fill: G, line: null});
    if (c.line) {
      ctx.globalAlpha = L.alpha * bar;
      font(40, 700); ctx.fillStyle = '#E3ECE6'; ctx.textBaseline = 'middle'; shadow(10, .5);
      ctx.fillText(c.line, x + 96 + 22, by + 6);
    }
  };

  CARDS.tag = (c, L) => {
    const y = (c.y ?? 400) + (1 - L.in) * 24;
    ctx.globalAlpha = L.alpha;
    const runs = rich(c.text).flat(), size = fit([runs], 56, 900, 840), h = 108;
    const w = widthOf(runs) + 68 + 44, x = (W - w) / 2;
    shadow(20, .35); panel(x, y, w, h, {r: h / 2}); noShadow();
    circle(x + 40, y + h / 2, 11, G);
    font(size, 900); ctx.textBaseline = 'middle'; drawRuns(runs, x + 68, y + h / 2 + 1);
    if (c.sub) {
      shadow(10, .6);
      textLines(c.sub, W / 2, y + h + 46, {size: 38, weight: 700, color: SUB, maxW: 900});
      noShadow();
    }
  };

  CARDS.points = (c, L) => {
    const th = tone(c.bad ? 'bad' : 'g'), y = c.y ?? 430, rowH = c.rowH || 116, items = c.items || [];
    ctx.globalAlpha = L.alpha;
    let top = y;
    if (c.title) {
      shadow(14, .6);
      textLines(c.title, W / 2, y + 40, {size: 66, weight: 900, hi: th.accent});
      noShadow();
      top = y + 110;
    }
    items.forEach((it, k) => {
      const ry = top + k * rowH, h = rowH - 22, cy = ry + h / 2;
      const lit = ease(prog(it.at ?? c.from + .2 + .25 * k, .4));
      ctx.globalAlpha = L.alpha * (.3 + .7 * lit);
      const dx = (1 - lit) * -14;
      panel(72 + dx, ry, 936, h, {r: 22, fill: th.fill, line: lit > .01 ? th.line : 'rgba(255, 255, 255, .16)'});
      const cx = 72 + 58 + dx;
      if (it.num != null && it.num !== '') {
        circle(cx, cy, 30, lit > .01 ? th.accent : null, th.accent, 3);
        font(34, 900); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillStyle = lit > .5 ? DARK : th.accent; ctx.fillText(String(it.num), cx, cy + 1); ctx.textAlign = 'left';
      } else {
        circle(cx, cy, 11, th.accent);
      }
      const maxW = it.sub ? 560 : 780;
      textLines(it.text, 72 + 112 + dx, cy + 1, {size: 50, weight: 800, align: 'left', maxW, hi: th.accent});
      if (it.sub) textLines(it.sub, 72 + 936 - 30 + dx, cy + 1, {size: 34, weight: 700, align: 'right', color: SUB, maxW: 230});
    });
  };

  function edgePoint(a, b) {
    // Where the line from a's centre towards b leaves a's box, plus a small gap.
    const dx = b.cx - a.cx, dy = b.cy - a.cy, len = Math.hypot(dx, dy) || 1;
    const s = Math.min(a.w / 2 / (Math.abs(dx) || 1e-6), a.h / 2 / (Math.abs(dy) || 1e-6));
    return {x: a.cx + dx * s + dx / len * 10, y: a.cy + dy * s + dy / len * 10};
  }

  CARDS.flow = (c, L) => {
    const y = c.y ?? 380, h = c.h || 760, x0 = 54;
    ctx.globalAlpha = L.alpha;
    panel(x0, y, 972, h, {r: 28});
    if (c.title) textLines(c.title, W / 2, y + 66, {size: 56, weight: 900});
    const nodes = {};
    for (const n of c.nodes || []) {
      font(44, 800);
      const tw = Math.max(0, ...rich(n.text).map(widthOf));
      nodes[n.id] = {...n, cx: x0 + n.x, cy: y + n.y, w: Math.max(200, tw + 64), h: 96, at: n.at ?? c.from + .2};
    }
    for (const [from, to, label] of c.edges || []) {
      const a = nodes[from], b = nodes[to];
      if (!a || !b) continue;
      const p = ease(prog(Math.max(a.at, b.at) + .15, .45));
      if (p <= 0) continue;
      const s = edgePoint(a, b), e = edgePoint(b, a);
      const ex = s.x + (e.x - s.x) * p, ey = s.y + (e.y - s.y) * p;
      ctx.globalAlpha = L.alpha;
      ctx.strokeStyle = 'rgba(255, 255, 255, .78)'; ctx.lineWidth = 4; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(ex, ey); ctx.stroke();
      const ang = Math.atan2(e.y - s.y, e.x - s.x);
      ctx.fillStyle = 'rgba(255, 255, 255, .9)';
      ctx.beginPath(); ctx.moveTo(ex, ey);
      ctx.lineTo(ex - 20 * Math.cos(ang - .45), ey - 20 * Math.sin(ang - .45));
      ctx.lineTo(ex - 20 * Math.cos(ang + .45), ey - 20 * Math.sin(ang + .45)); ctx.closePath(); ctx.fill();
      if (label) {
        ctx.globalAlpha = L.alpha * p;
        font(32, 700);
        const lw = ctx.measureText(label).width + 28, upright = Math.abs(e.x - s.x) < 40;
        // On an upright arrow the label sits beside it, so the arrow stays visible.
        const mx = (s.x + e.x) / 2 + (upright ? lw / 2 + 18 : 0), my = (s.y + e.y) / 2;
        panel(mx - lw / 2, my - 24, lw, 48, {r: 24, fill: 'rgba(6, 12, 9, .92)', line: null});
        ctx.fillStyle = '#E8EFEA'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(label, mx, my + 1); ctx.textAlign = 'left';
      }
    }
    for (const n of Object.values(nodes)) {
      const a = ease(prog(n.at, .4));
      if (a <= 0) continue;
      const th = tone(n.tone), sc = .92 + .08 * a;
      ctx.save(); ctx.globalAlpha = L.alpha * a;
      ctx.translate(n.cx, n.cy); ctx.scale(sc, sc);
      panel(-n.w / 2, -n.h / 2, n.w, n.h, {r: 22, fill: th.fill, line: th.line, lw: 3});
      textLines(n.text, 0, 1, {size: 44, weight: 800, maxW: n.w - 30, color: n.tone && n.tone !== 'plain' ? th.accent : WHITE});
      ctx.restore();
    }
  };

  CARDS.compare = (c, L) => {
    const y = c.y ?? 420, rowH = c.rowH || 116, colW = 444, lx = 72, rx = 72 + 444 + 48;
    const sides = [[c.left || {}, lx, tone(c.left?.tone || 'g')], [c.right || {}, rx, tone(c.right?.tone || 'bad')]];
    ctx.globalAlpha = L.alpha;
    for (const [side, x, th] of sides) {
      panel(x, y, colW, 96, {r: 48, fill: th.fill, line: th.line, lw: 3});
      textLines(side.title || '', x + colW / 2, y + 49, {size: 50, weight: 900, maxW: colW - 50, color: th.accent});
    }
    circle(W / 2, y + 48, 34, '#0A120D', 'rgba(255, 255, 255, .45)', 2);
    font(30, 900); ctx.fillStyle = WHITE; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('VS', W / 2, y + 49); ctx.textAlign = 'left';
    const n = Math.max(sides[0][0].items?.length || 0, sides[1][0].items?.length || 0);
    const ats = Array.isArray(c.at) ? c.at : [];
    for (let k = 0; k < n; k++) {
      const a = ease(prog(ats[k] ?? c.from + .3 + .3 * k, .4));
      if (a <= 0) continue;
      const ry = y + 130 + k * rowH + (1 - a) * 20;
      ctx.globalAlpha = L.alpha * a;
      for (const [side, x, th] of sides) {
        const item = side.items?.[k];
        if (item == null) continue;
        panel(x, ry, colW, rowH - 20, {r: 20, fill: th.fill, line: 'rgba(255, 255, 255, .18)'});
        textLines(item, x + colW / 2, ry + (rowH - 20) / 2 + 1, {size: 46, weight: 800, maxW: colW - 40, hi: th.accent});
      }
    }
  };

  CARDS.cycle = (c, L) => {
    const cx = W / 2, cy = c.y ?? 800, r = c.r ?? 300;
    const items = (c.items || []).map(it => typeof it === 'object' ? it : {text: String(it)});
    const n = items.length, span = Math.min(2.4, (c.to - c.from) * .6);
    ctx.globalAlpha = L.alpha;
    const disk = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * .95);
    disk.addColorStop(0, 'rgba(0, 0, 0, .45)'); disk.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = disk; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(60, 215, 100, .35)'; ctx.lineWidth = 6;
    ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * L.in); ctx.stroke();
    const at = items.map((it, k) => it.at ?? c.from + .25 + span * k / Math.max(1, n));
    const lit = at.map(a => ease(prog(a, .35)));
    // Chevrons on the ring between neighbours that are both lit.
    for (let k = 0; k < n; k++) {
      const on = Math.min(lit[k], lit[(k + 1) % n]);
      if (on <= 0) continue;
      const ang = -Math.PI / 2 + Math.PI * 2 * (k + .5) / n;
      ctx.save(); ctx.globalAlpha = L.alpha * on;
      ctx.translate(cx + r * Math.cos(ang), cy + r * Math.sin(ang)); ctx.rotate(ang + Math.PI / 2);
      ctx.strokeStyle = G; ctx.lineWidth = 6; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(-9, -13); ctx.lineTo(7, 0); ctx.lineTo(-9, 13); ctx.stroke();
      ctx.restore();
    }
    items.forEach((it, k) => {
      const ang = -Math.PI / 2 + Math.PI * 2 * k / n, x = cx + r * Math.cos(ang), y = cy + r * Math.sin(ang);
      font(40, 800);
      const w = widthOf(rich(it.text).flat()) + 52, h = 78;
      ctx.globalAlpha = L.alpha * (.35 + .65 * lit[k]);
      panel(x - w / 2, y - h / 2, w, h, {r: h / 2, fill: lit[k] > .01 ? 'rgba(14, 28, 18, .94)' : 'rgba(16, 22, 19, .85)',
        line: lit[k] > .01 ? TONES.g.line : 'rgba(255, 255, 255, .25)', lw: 3});
      textLines(it.text, x, y + 1, {size: 40, weight: 800, color: lit[k] > .5 ? WHITE : '#9AA8A0', maxW: 400});
    });
    const ca = ease(prog(c.from + .2, .4));
    ctx.globalAlpha = L.alpha * ca;
    const lines = rich(c.center), size = fit(lines, 64, 900, r * 1.3), lh = size * 1.25;
    shadow(12, .5); ctx.textBaseline = 'middle';
    lines.forEach((runs, i) => drawRuns(runs, cx, cy + (i - (lines.length - 1) / 2) * lh, {align: 'center'}));
    noShadow();
  };

  function bigNumber(c, value, at, x, y, {size = 190, suffixSize, align = 'center', prefix = '', suffix = '', dur = 1.2}) {
    let text = String(value);
    if (c.count !== false && numeric(value)) {
      const p = ease(prog(at, dur));
      text = format(Number(value) * p, decimals(c, value));
    }
    suffixSize = suffixSize || Math.round(size * .36);
    ctx.textBaseline = 'alphabetic';
    font(suffixSize, 900); const pw = prefix ? ctx.measureText(prefix).width + 6 : 0, sw = suffix ? ctx.measureText(suffix).width + 8 : 0;
    font(size, 900); const nw = ctx.measureText(text).width;
    const total = pw + nw + sw, left = align === 'center' ? x - total / 2 : align === 'right' ? x - total : x;
    if (prefix) { font(suffixSize, 900); ctx.fillStyle = WHITE; ctx.fillText(prefix, left, y); }
    font(size, 900); ctx.fillStyle = G; ctx.fillText(text, left + pw, y);
    if (suffix) { font(suffixSize, 900); ctx.fillStyle = WHITE; ctx.fillText(suffix, left + pw + nw + 8, y); }
    return total;
  }

  CARDS.stat = (c, L) => {
    const y = (c.y ?? 520) + (1 - L.in) * 24, h = c.sub ? 440 : 380;
    ctx.globalAlpha = L.alpha;
    panel(72, y, 936, h, {r: 28});
    if (c.label) textLines(c.label, W / 2, y + 70, {size: 46, weight: 800, color: SUB});
    bigNumber(c, c.value, c.from + .25, W / 2, y + 300, {size: 190, suffix: c.suffix || '', prefix: c.prefix || ''});
    if (c.sub) textLines(c.sub, W / 2, y + 380, {size: 36, weight: 700, color: SUB, maxW: 860});
  };

  CARDS.stats = (c, L) => {
    const y = c.y ?? 520, rowH = c.rowH || 230, items = c.items || [];
    ctx.globalAlpha = L.alpha;
    let top = y;
    if (c.title) { shadow(14, .6); textLines(c.title, W / 2, y + 40, {size: 58, weight: 900}); noShadow(); top = y + 100; }
    items.forEach((it, k) => {
      const at = it.at ?? c.from + .2 + .3 * k, a = ease(prog(at, .4));
      if (a <= 0) return;
      const ry = top + k * rowH + (1 - a) * 20, h = rowH - 24;
      ctx.globalAlpha = L.alpha * a;
      panel(72, ry, 936, h, {r: 26});
      const size = Math.min(120, h * .58);
      const used = bigNumber({...c, ...it}, it.value, at, 112, ry + h / 2 + size * .36,
        {size, align: 'left', suffix: it.suffix || '', prefix: it.prefix || '', dur: 1.0});
      const maxW = Math.max(200, 936 - 80 - used - 60);
      if (it.label) textLines(it.label, 72 + 936 - 40, ry + h * (it.sub ? .38 : .5), {size: 44, weight: 800, align: 'right', maxW});
      if (it.sub) textLines(it.sub, 72 + 936 - 40, ry + h * .7, {size: 32, weight: 700, align: 'right', color: SUB, maxW});
    });
  };

  CARDS.bars = (c, L) => {
    const y = c.y ?? 420, rowH = c.rowH || 210, series = c.series || [];
    const twin = series.some(s => s.b != null), legend = c.legend !== false && twin && (c.la || c.lb);
    const max = Math.max(1e-9, ...series.flatMap(s => [Number(s.a) || 0, Number(s.b) || 0]));
    let top = y + (c.title ? 100 : 20) + (legend ? 64 : 0);
    const height = top - y + series.length * rowH;
    ctx.globalAlpha = L.alpha;
    panel(54, y - 20, 972, height + 20, {r: 28});
    if (c.title) textLines(c.title, W / 2, y + 44, {size: 52, weight: 900, maxW: 900});
    if (legend) {
      let lx = 96;
      for (const [name, color] of [[c.la, G], [c.lb, BLUE]]) {
        if (!name) continue;
        panel(lx, top - 64 + 10, 30, 30, {r: 8, fill: color, line: null});
        font(34, 700); ctx.fillStyle = SUB; ctx.textBaseline = 'middle'; ctx.fillText(name, lx + 44, top - 64 + 26);
        lx += 44 + ctx.measureText(name).width + 48;
      }
    }
    const track = 690;
    series.forEach((s, k) => {
      const ry = top + k * rowH, grow = ease(prog(s.at ?? c.from + .3 + .3 * k, .8));
      textLines(s.label, 96, ry + 32, {size: 42, weight: 800, align: 'left', maxW: 860});
      const bars = [[s.a, s.hi ? G : (twin ? G : '#7FA08A')], ...(s.b != null ? [[s.b, BLUE]] : [])];
      const bh = twin ? 42 : 52;
      bars.forEach(([v, color], j) => {
        if (v == null) return;
        const by = ry + 72 + j * (bh + 14), len = Math.max(4, track * (Number(v) / max) * grow);
        panel(96, by, track, bh, {r: bh / 2, fill: 'rgba(255, 255, 255, .07)', line: null});
        panel(96, by, len, bh, {r: bh / 2, fill: color, line: null});
        font(38, 800); ctx.fillStyle = WHITE; ctx.textBaseline = 'middle';
        ctx.fillText(format(Number(v) * grow, s.dec ?? c.dec ?? decimals(c, v)) + (s.suffix ?? c.suffix ?? ''), 96 + len + 16, by + bh / 2 + 1);
      });
    });
  };

  CARDS.quad = (c, L) => {
    const y = c.y ?? 430, ch = c.ch || 250, items = c.items || [];
    ctx.globalAlpha = L.alpha;
    let top = y;
    if (c.title) { shadow(14, .6); textLines(c.title, W / 2, y + 40, {size: 58, weight: 900}); noShadow(); top = y + 100; }
    items.slice(0, 4).forEach((it, k) => {
      const x = 72 + (k % 2) * (458 + 20), cy = top + Math.floor(k / 2) * (ch + 20);
      const at = c.allOn ? c.from + .2 : it.at ?? c.from + .2 + .3 * k, lit = ease(prog(at, .4));
      ctx.globalAlpha = L.alpha * (.3 + .7 * lit);
      panel(x, cy, 458, ch, {r: 26, line: lit > .01 ? TONES.g.line : 'rgba(255, 255, 255, .16)'});
      if (it.label) textLines(it.label, x + 30, cy + 50, {size: 38, weight: 800, align: 'left', color: SUB, maxW: 400});
      const size = Math.min(96, ch * .4);
      bigNumber({...c, ...it}, it.value, at, x + 30, cy + ch * .62 + size * .3,
        {size, align: 'left', prefix: it.prefix || '', suffix: it.suffix || '', suffixSize: 44, dur: .9});
      if (it.sub) textLines(it.sub, x + 30, cy + ch - 34, {size: 30, weight: 700, align: 'left', color: SUB, maxW: 400});
    });
  };

  CARDS.route = (c, L) => {
    const y = (c.y ?? 400) + (1 - L.in) * 24, items = c.items || [];
    const h = 190 + items.length * 92 + (c.invest ? 130 : 30);
    ctx.globalAlpha = L.alpha;
    panel(54, y, 972, h, {r: 28});
    circle(54 + 78, y + 92, 44, G);
    font(46, 900); ctx.fillStyle = DARK; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(c.idx ?? ''), 54 + 78, y + 94); ctx.textAlign = 'left';
    textLines(c.name || '', 54 + 148, y + (c.cap ? 70 : 92), {size: 58, weight: 900, align: 'left', maxW: 780});
    if (c.cap) textLines(c.cap, 54 + 148, y + 128, {size: 34, weight: 700, align: 'left', color: SUB, maxW: 780});
    items.forEach((it, k) => {
      const a = ease(prog(c.from + .25 + .15 * k, .35)), ry = y + 190 + k * 92;
      ctx.globalAlpha = L.alpha * a;
      ctx.fillStyle = 'rgba(255, 255, 255, .1)'; ctx.fillRect(96, ry, 888, 2);
      textLines(it.k || '', 96, ry + 47, {size: 36, weight: 700, align: 'left', color: SUB, maxW: 300});
      textLines(it.v || '', 984, ry + 47, {size: 42, weight: 800, align: 'right', maxW: 560});
    });
    if (c.invest) {
      const a = ease(prog(c.from + .3 + .15 * items.length, .4)), iy = y + h - 120;
      ctx.globalAlpha = L.alpha * a;
      panel(90, iy, 900, 90, {r: 20, fill: 'rgba(60, 215, 100, .14)', line: 'rgba(60, 215, 100, .4)'});
      textLines(c.invest, W / 2, iy + 46, {size: 40, weight: 800, maxW: 860});
    }
  };

  // "CaSO4 + 2C → CaS + 2CO2↑": numbers after a letter or ")" become subscripts; a leading number stays a coefficient.
  function formula(token, size) {
    const parts = [];
    const m = token.match(/^(\d*)(.*)$/);
    if (m[1]) parts.push({text: m[1], sub: false});
    for (const piece of m[2].match(/\d+|[^\d]+/g) || []) {
      const prev = parts.length ? parts[parts.length - 1].text.slice(-1) : '';
      parts.push({text: piece, sub: /^\d+$/.test(piece) && /[A-Za-z)\]]/.test(prev)});
    }
    return parts.map(p => ({...p, size: p.sub ? size * .62 : size}));
  }
  CARDS.eq = (c, L) => {
    const y = (c.y ?? 520) + (1 - L.in) * 24, size0 = c.size || 64;
    const h = (c.title ? 100 : 30) + size0 * 2.3 + (c.note ? 80 : 20);
    ctx.globalAlpha = L.alpha;
    panel(54, y, 972, h, {r: 28});
    let top = y + 30;
    if (c.step) chip(String(c.step), 90, y + 30, {size: 32});
    if (c.title) { textLines(c.title, c.step ? 584 : W / 2, y + 58, {size: 52, weight: 900, maxW: c.step ? 640 : 900}); top = y + 100; }
    const tokens = String(c.eq || '').replace(/->/g, '→').replace(/<=>/g, '⇌').split(/\s+/).filter(Boolean);
    const hi = new Set((Array.isArray(c.hi) ? c.hi : c.hi ? [c.hi] : []).map(String));
    let size = size0, layout;
    for (;; size -= 2) {
      layout = tokens.map(tok => {
        const ops = /^[+=→⇌]$/.test(tok);
        const parts = ops ? [{text: tok, sub: false, size}] : formula(tok, size);
        const w = parts.reduce((s, p) => { font(p.size, 800); return s + ctx.measureText(p.text).width; }, 0);
        return {tok, ops, parts, w, hi: hi.has(tok) || hi.has(tok.replace(/^\d+/, ''))};
      });
      const total = layout.reduce((s, l) => s + l.w, 0) + (layout.length - 1) * size * .35;
      if (total <= 880 || size <= 24) { layout.total = total; break; }
    }
    const reveal = ease(prog(c.from + .3, .9));
    const base = top + size0 * 1.2;
    ctx.save(); ctx.beginPath(); ctx.rect(54, top, 972 * reveal + 1, size0 * 2.2); ctx.clip();
    let x = (W - layout.total) / 2;
    ctx.textBaseline = 'alphabetic';
    for (const l of layout) {
      for (const p of l.parts) {
        font(p.size, 800); ctx.fillStyle = l.ops ? SUB : l.hi ? G : WHITE;
        ctx.fillText(p.text, x, base + (p.sub ? size * .2 : 0)); x += ctx.measureText(p.text).width;
      }
      x += size * .35;
    }
    ctx.restore();
    if (c.note) textLines(c.note, W / 2, y + h - 52, {size: 34, weight: 700, color: SUB, maxW: 880});
  };

  CARDS.note = (c, L) => {
    ctx.globalAlpha = L.alpha * .92;
    shadow(10, .7);
    textLines(c.text, W / 2, (c.y ?? 1262) + 20, {size: 32, weight: 700, color: '#DCE4DF', maxW: 960});
    noShadow();
  };

  // ---------------------------------------------------------------- frame parts
  function badge() {
    const L = life('badge', P.hook_end || 0, P.end.t0, .5, .3);
    if (!L) return;
    ctx.globalAlpha = L.alpha;
    const x = 48, y = 96, ih = 92, iw = ih * logo.naturalWidth / logo.naturalHeight;
    font(46, 900); const nw = ctx.measureText(P.corp.name).width;
    font(26, 700); const sw = ctx.measureText(P.corp.series || '').width;
    panel(x - 16, y - 14, iw + 22 + Math.max(nw, sw) + 40, ih + 28, {r: 24, fill: 'rgba(6, 12, 9, .42)', line: null});
    ctx.drawImage(logo, x, y, iw, ih);
    ctx.textBaseline = 'middle'; shadow(8, .5);
    font(46, 900); ctx.fillStyle = WHITE; ctx.fillText(P.corp.name, x + iw + 20, y + 30);
    font(26, 700); ctx.fillStyle = '#C9D4CD'; ctx.fillText(P.corp.series || '', x + iw + 22, y + 72);
    noShadow();
  }

  function captions() {
    if (t >= P.end.t0) return;
    const i = P.caps.findIndex(c => t >= c.t0 && t < c.t1);
    if (i < 0) return;
    seen.push('cap' + i);
    const c = P.caps[i], runs = keyed(c.text, c.keys);
    ctx.globalAlpha = 1;
    fit([runs], 66, 800, 960);
    ctx.textBaseline = 'middle';
    shadow(16, .6);
    drawRuns(runs, W / 2, 1395, {align: 'center', stroke: 'rgba(6, 10, 8, .92)', strokeW: 11});
    noShadow();
  }

  function endCard() {
    const e = P.end, L = life('end', e.t0, e.t1 + 10, .6, 0);
    if (!L) return;
    const step = (d, len = .5) => ease(prog(e.t0 + d, len));
    ctx.globalAlpha = L.alpha;
    ctx.fillStyle = 'rgba(4, 10, 7, .35)'; ctx.fillRect(0, 0, W, H);
    const a0 = step(0, .6), iw = 300, ih = iw * logo.naturalHeight / logo.naturalWidth, sc = .85 + .15 * a0;
    ctx.save(); ctx.globalAlpha = a0; ctx.translate(W / 2, 380 + ih / 2); ctx.scale(sc, sc);
    ctx.drawImage(logo, -iw / 2, -ih / 2, iw, ih); ctx.restore();
    const rows = [[P.corp.name, 108, 900, WHITE, 780, .15], [P.corp.tagline, 50, 800, G, 886, .25],
                  [P.corp.company, 36, 700, SUB, 960, .35], [P.corp.site, 36, 700, WHITE, 1010, .4]];
    shadow(12, .5);
    for (const [text, size, weight, color, y, d] of rows) {
      const a = step(d);
      ctx.globalAlpha = a;
      textLines(text, W / 2, y + (1 - a) * 20, {size, weight, color, maxW: 940});
    }
    noShadow();
    if (e.next) {
      const a = step(.55), y = 1110 + (1 - a) * 20;
      ctx.globalAlpha = a;
      panel(90, y, 900, 200, {r: 28, fill: 'rgba(14, 28, 18, .9)', line: TONES.g.line, lw: 3});
      chip('下集预告', W / 2, y - 26, {size: 32, align: 'center'});
      textLines(e.next, W / 2, y + 112, {size: 52, weight: 900, maxW: 820});
    }
  }

  function scene(f, draw) {
    ctx = draw ? real : dry;
    t = f / FPS; marks = []; seen = []; moving = false;
    if (draw) {
      real.setTransform(1, 0, 0, 1, 0, 0); real.clearRect(0, 0, canvas.width, canvas.height);
      real.setTransform(S, 0, 0, S, 0, 0); real.globalAlpha = 1;
    }
    const cards = P.cards || [];
    for (const pass of ['main', 'note']) {
      cards.forEach((c, i) => {
        if ((c.kind === 'note') !== (pass === 'note') || t >= P.end.t0) return;
        const draw = CARDS[c.kind];
        if (!draw) throw new Error(`不认识的卡片 kind: ${c.kind}`);
        const L = c.kind === 'hook' ? life('c' + i, c.from, c.to, .01, .35) : life('c' + i, c.from, c.to, c.kind === 'note' ? .35 : .4, .3);
        if (!L) return;
        ctx.save(); draw(c, L); ctx.restore();
      });
    }
    ctx.save(); badge(); ctx.restore();
    ctx.save(); captions(); ctx.restore();
    ctx.save(); endCard(); ctx.restore();
    return seen.join(',') + '|' + marks.join('') + (moving ? '#' + f : '');
  }

  window.__keys = n => Array.from({length: n}, (_, f) => scene(f, false));
  window.__draw = f => { scene(f, true); return true; };
  window.__ready = Promise.all([
    document.fonts.load('700 40px HC'), document.fonts.load('800 40px HC'), document.fonts.load('900 40px HC'),
    logo.decode(),
  ]).then(() => document.fonts.ready).then(() => true);
})();
