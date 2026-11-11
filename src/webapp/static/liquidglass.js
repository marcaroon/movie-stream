/*
 * Liquid glass for MarTube: real refraction, dispersion and a springy press for every `.glass` surface.
 *
 * The lens maths (rounded-box distance field, edge normals, the t·tan(asin(t)/2) lens profile,
 * corner-weighted dispersion) follows the panel shader of LiquidGlass-Cpp
 * (https://github.com/SilentEaves/LiquidGlass-Cpp, Apache License 2.0), which ports Kyant's
 * AndroidLiquidGlass (Copyright 2025 Kyant, https://github.com/Kyant0/AndroidLiquidGlass,
 * Apache License 2.0). Here it is rewritten for the web: the lens becomes a displacement map
 * fed to an SVG filter that the browser applies with `backdrop-filter`.
 *
 * Tuning per element through CSS custom properties (unitless numbers):
 *   --lg-blur        backdrop blur, px               --lg-lens        lens band from the edge, px
 *   --lg-refract     lens strength (1 = band width)  --lg-dispersion  colour split at the rim (0–0.3)
 *   --lg-saturate    backdrop saturation
 * Chromium only (WebView2 / Chrome / Edge); elsewhere the plain CSS blur in app.css remains.
 */
(() => {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const BUCKET = 4;          // sizes are rounded to this many px so resizing text does not mint new maps
  const MAX_MAP_SIDE = 1400; // larger surfaces reuse a scaled map
  const MAX_FILTERS = 140;

  const root = document.documentElement;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const reduceTransparency = matchMedia('(prefers-reduced-transparency: reduce)');
  // Settings › Appearance (full | blur | solid), remembered so the first paint already matches.
  try { root.dataset.glass = JSON.parse(localStorage.getItem('martube.glass')) || 'full'; } catch { root.dataset.glass = 'full'; }

  // ------------------------------------------------------------
  // Spring easing for presses (stiffness 300, damping ratio 0.5, like LiquidGlass-Cpp's press spring)
  // ------------------------------------------------------------
  function springEasing(stiffness, ratio, seconds, steps = 48) {
    const omega = Math.sqrt(stiffness);
    const decay = ratio * omega;
    const damped = omega * Math.sqrt(1 - ratio * ratio);
    const points = [];
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * seconds;
      const value = 1 - Math.exp(-decay * t) * (Math.cos(damped * t) + (decay / damped) * Math.sin(damped * t));
      points.push(i === steps ? '1' : value.toFixed(4));
    }
    return `linear(${points.join(', ')})`;
  }
  if (CSS.supports('transition-timing-function', 'linear(0, 1)')) {
    root.style.setProperty('--lg-spring', springEasing(300, 0.5, 0.6));
    root.style.setProperty('--lg-spring-soft', springEasing(250, 0.7, 0.6));
  }

  // ------------------------------------------------------------
  // Pointer glow and press for glass controls (works everywhere)
  // ------------------------------------------------------------
  const interactive = el => el.matches('button, a, [role="button"], label, summary');
  document.addEventListener('pointermove', event => {
    const glass = event.target.closest && event.target.closest('.glass');
    if (!glass || !interactive(glass)) return;
    const box = glass.getBoundingClientRect();
    glass.style.setProperty('--lg-x', `${event.clientX - box.left}px`);
    glass.style.setProperty('--lg-y', `${event.clientY - box.top}px`);
  }, {passive: true});
  document.addEventListener('pointerdown', event => {
    const glass = event.target.closest && event.target.closest('.glass');
    if (!glass || !interactive(glass) || glass.disabled) return;
    glass.classList.add('lg-pressed');
    const release = () => {
      glass.classList.remove('lg-pressed');
      removeEventListener('pointerup', release, true);
      removeEventListener('pointercancel', release, true);
    };
    addEventListener('pointerup', release, true);
    addEventListener('pointercancel', release, true);
  }, {passive: true});

  // ------------------------------------------------------------
  // Refraction (Chromium: backdrop-filter accepts SVG filters)
  // ------------------------------------------------------------
  const supported = /\bChrom(e|ium)\//.test(navigator.userAgent) && CSS.supports('backdrop-filter', 'url(#lg)');
  if (!supported) return;

  const defs = document.createElementNS(SVG_NS, 'svg');
  defs.setAttribute('width', '0');
  defs.setAttribute('height', '0');
  defs.setAttribute('aria-hidden', 'true');
  defs.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
  const filterHost = document.createElementNS(SVG_NS, 'defs');
  defs.append(filterHost);
  document.body.prepend(defs);

  const filters = new Map(); // key -> filter id
  const maps = new Map();    // map key -> {url, shift}
  let nextId = 0;

  /** Signed distance to a rounded box (negative inside), as boxMetric in the shader. */
  function boxMetric(px, py, hx, hy, r) {
    const qx = Math.abs(px) - hx + r, qy = Math.abs(py) - hy + r;
    const pocket = Math.min(Math.max(qx, qy), 0);
    const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
    return pocket + Math.hypot(ox, oy) - r;
  }

  /** Outward normal of the nearest edge, as boxNormal in the shader. */
  function boxNormal(px, py, hx, hy, r) {
    const qx = Math.abs(px) - hx + r, qy = Math.abs(py) - hy + r;
    const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
    const len = Math.hypot(ox, oy);
    let nx, ny;
    if (Math.max(qx, qy) >= 0 && len > 1e-4) { nx = ox / len; ny = oy / len; }
    else if (qx >= qy) { nx = 1; ny = 0; }
    else { nx = 0; ny = 1; }
    return [nx * Math.sign(px || 1), ny * Math.sign(py || 1)];
  }

  const lensCurve = t => (t <= 0 ? 0 : t >= 1 ? 1 : t * Math.tan(Math.asin(t) / 2));

  /**
   * Displacement map for a w×h rounded box: inside the lens band each pixel samples the
   * backdrop further in along the edge normal, so the rim bends and magnifies what is behind.
   * Red/green carry x/y offsets around 128; blue carries the dispersion weight (corners).
   */
  function lensMap(w, h, radius, band, refract) {
    const key = [w, h, radius, band, refract].join(':');
    if (maps.has(key)) return maps.get(key);
    const scale = Math.min(1, MAX_MAP_SIDE / Math.max(w, h));
    const mw = Math.max(2, Math.round(w * scale)), mh = Math.max(2, Math.round(h * scale));
    const canvas = document.createElement('canvas');
    canvas.width = mw;
    canvas.height = mh;
    const context = canvas.getContext('2d');
    const image = context.createImageData(mw, mh);
    const data = image.data;
    const hx = w / 2, hy = h / 2;
    const r = Math.min(radius, hx, hy);
    const lensHeight = Math.max(1, Math.min(band, hx, hy));
    const amount = lensHeight * refract;
    const depthBias = 0.15; // uLensDepth: lean the offsets a little toward the centre
    const shift = Math.max(1, amount);
    for (let j = 0; j < mh; j++) {
      const py = (j + 0.5) / scale - hy;
      for (let i = 0; i < mw; i++) {
        const px = (i + 0.5) / scale - hx;
        const o = (j * mw + i) * 4;
        const field = boxMetric(px, py, hx, hy, r);
        const depth = -Math.min(field, 0);
        const t = 1 - depth / lensHeight;
        let dx = 0, dy = 0;
        if (t > 0) {
          let [nx, ny] = boxNormal(px, py, hx, hy, r);
          const cl = Math.hypot(px, py) || 1;
          nx += depthBias * (px / cl);
          ny += depthBias * (py / cl);
          const nl = Math.hypot(nx, ny) || 1;
          const lens = lensCurve(Math.min(t, 1)) * amount;
          dx = (-lens * nx) / nl; // sample inward: the rim gathers light from further in
          dy = (-lens * ny) / nl;
        }
        data[o] = Math.round(128 + (dx / shift) * 127);
        data[o + 1] = Math.round(128 + (dy / shift) * 127);
        // Dispersion is strongest on the diagonals, like the shader's (x·y)/(hx·hy) weight.
        data[o + 2] = Math.round(Math.min(1, Math.abs((px * py) / (hx * hy))) * 255);
        data[o + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    const entry = {url: canvas.toDataURL(), shift};
    maps.set(key, entry);
    return entry;
  }

  const number = (style, name, fallback) => {
    const value = parseFloat(style.getPropertyValue(name));
    return Number.isFinite(value) ? value : fallback;
  };

  function el(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
    return node;
  }

  /** An SVG filter: blur → saturate → lens displacement, with red and blue split at the rim. */
  function filterFor(w, h, radius, params) {
    const key = [w, h, radius, params.blur, params.band, params.refract, params.dispersion, params.saturate].join(':');
    if (filters.has(key)) return filters.get(key);
    if (filters.size >= MAX_FILTERS) prune();
    const id = `lg-${++nextId}`;
    const map = lensMap(w, h, radius, params.band, params.refract);
    const scale = map.shift * 2; // feDisplacementMap: offset = scale × (channel − 0.5)
    const f = el('filter', {id, x: 0, y: 0, width: w, height: h, filterUnits: 'userSpaceOnUse',
      primitiveUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB'});
    f.append(
      el('feGaussianBlur', {in: 'SourceGraphic', stdDeviation: params.blur, edgeMode: 'duplicate', result: 'blur'}),
      el('feColorMatrix', {in: 'blur', type: 'saturate', values: params.saturate, result: 'tone'}),
      el('feImage', {href: map.url, x: 0, y: 0, width: w, height: h, preserveAspectRatio: 'none', result: 'map'}),
      el('feDisplacementMap', {in: 'tone', in2: 'map', scale, xChannelSelector: 'R', yChannelSelector: 'G', result: 'lens'}));
    if (params.dispersion > 0) {
      const spread = scale * params.dispersion;
      f.append(
        el('feDisplacementMap', {in: 'tone', in2: 'map', scale: scale + spread, xChannelSelector: 'R', yChannelSelector: 'G', result: 'wide'}),
        el('feDisplacementMap', {in: 'tone', in2: 'map', scale: Math.max(0, scale - spread), xChannelSelector: 'R', yChannelSelector: 'G', result: 'narrow'}),
        el('feColorMatrix', {in: 'wide', type: 'matrix', values: '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0', result: 'red'}),
        el('feColorMatrix', {in: 'lens', type: 'matrix', values: '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0', result: 'green'}),
        el('feColorMatrix', {in: 'narrow', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0', result: 'blue'}),
        el('feComposite', {in: 'red', in2: 'green', operator: 'arithmetic', k2: 1, k3: 1, result: 'rg'}),
        el('feComposite', {in: 'rg', in2: 'blue', operator: 'arithmetic', k2: 1, k3: 1, result: 'split'}),
        // Use the split colour only where the map's blue channel says so (corners); plain lens elsewhere.
        el('feColorMatrix', {in: 'map', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0', result: 'weight'}),
        el('feComposite', {in: 'split', in2: 'weight', operator: 'in', result: 'corner'}),
        el('feComposite', {in: 'corner', in2: 'lens', operator: 'over'}));
    }
    filterHost.append(f);
    filters.set(key, id);
    return id;
  }

  /** Drop filters no element uses any more. */
  function prune() {
    const used = new Set();
    for (const node of document.querySelectorAll('.glass.lg-on')) used.add(node.dataset.lgFilter);
    for (const [key, id] of filters) {
      if (!used.has(id)) {
        filters.delete(key);
        document.getElementById(id)?.remove();
      }
    }
  }

  const bucket = value => Math.max(BUCKET, Math.round(value / BUCKET) * BUCKET);

  function apply(node) {
    if (!node.isConnected) return;
    const off = reduceTransparency.matches || node.dataset.lg === 'off' || (root.dataset.glass || 'full') !== 'full';
    const w = bucket(node.offsetWidth), h = bucket(node.offsetHeight);
    if (off || node.offsetWidth < 16 || node.offsetHeight < 16) {
      node.classList.remove('lg-on');
      node.style.removeProperty('backdrop-filter');
      delete node.dataset.lgFilter;
      return;
    }
    const style = getComputedStyle(node);
    const radius = Math.min(parseFloat(style.borderTopLeftRadius) || 0, w / 2, h / 2);
    const params = {
      blur: number(style, '--lg-blur', 4),
      band: number(style, '--lg-lens', 20),
      refract: number(style, '--lg-refract', 1),
      dispersion: reduceMotion.matches ? 0 : number(style, '--lg-dispersion', 0.1),
      saturate: number(style, '--lg-saturate', 1.6),
    };
    const id = filterFor(w, h, Math.round(radius), params);
    if (node.dataset.lgFilter !== id) {
      node.dataset.lgFilter = id;
      node.style.setProperty('backdrop-filter', `url(#${id})`);
    }
    if (!node.classList.contains('lg-on')) node.classList.add('lg-on');
  }

  const resized = new ResizeObserver(entries => entries.forEach(entry => apply(entry.target)));
  const tracked = new WeakSet();
  function track(node) {
    if (tracked.has(node)) return;
    tracked.add(node);
    resized.observe(node);
  }
  function scan(rootNode) {
    if (rootNode.nodeType !== 1) return;
    if (rootNode.classList.contains('glass')) track(rootNode);
    rootNode.querySelectorAll('.glass').forEach(track);
  }

  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes') {
        if (record.target.classList.contains('glass')) track(record.target);
      } else {
        record.addedNodes.forEach(scan);
      }
    }
  }).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
  scan(document.body);
  reduceTransparency.addEventListener('change', () => document.querySelectorAll('.glass').forEach(apply));
  window.LiquidGlass = {refresh: node => (node ? apply(node) : document.querySelectorAll('.glass').forEach(apply))};
})();
