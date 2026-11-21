/* PyroScan 2D Indonesia map. No dependencies, no tiles, classic script.
   Web Mercator, affine view, prebuilt Path2D per province, clipped plates. */
(function (root) {
  'use strict';

  const BOUNDS = { west: 94, south: -12, east: 142, north: 8 };
  // The skin's real texture extends past the fit bounds; the viewport is
  // clamped to this image so no flat sea or vignette is ever revealed.
  const IMAGE = { west: 88, south: -20, east: 150, north: 10 };
  const SKINS = {
    satellite: 'data/skin_satellite.jpg',
    relief: 'data/skin_relief.jpg',
    atlas: 'data/skin_atlas.jpg',
  };
  const SEA = {
    satellite: '#0b171c', relief: '#0a1513', atlas: '#dfe5db',
    flat: '#0e1b18',
  };
  const LAND_LINE = {
    satellite: '#a8cbb8', relief: '#b9d0bd', atlas: '#4e5a50',
    flat: '#a8cbb8',
  };

  function wx(lon) { return (lon + 180) / 360; }
  function wy(lat) {
    const s = Math.sin(lat * Math.PI / 180);
    return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
  }
  function lx(x) { return x * 360 - 180; }
  function ly(y) {
    const n = Math.PI * (1 - 2 * y);
    return Math.atan(Math.sinh(n)) * 180 / Math.PI;
  }
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));


  function ringContains(ring, lon, lat) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1];
      const xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat)
          && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  function geometryContains(geometry, lon, lat) {
    const polys = geometry.type === 'Polygon'
      ? [geometry.coordinates] : geometry.coordinates;
    for (const poly of polys) {
      if (ringContains(poly[0], lon, lat)) return true;
    }
    return false;
  }

  function create(opts) {
    const canvas = opts.canvas;
    const ctx = canvas.getContext('2d');
    const cbs = opts;
    const state = {
      skin: opts.skin || 'relief',
      selected: null,
      dots: [],
      hoverDot: null,
      counts: {},
      labelCount: 0,
      plate: null,
      detail: null,
      images: {},
      paths: [],
      view: { s: 1, tx: 0, ty: 0 },
      fit: { s: 1, tx: 0, ty: 0 },
      minS: 1, maxS: 1,
      w: 1, h: 1, dpr: 1,
      raf: 0, move: null, pointers: new Map(), pinch: null, dragged: false,
    };

    function ringCentroid(ring) {
      let twice = 0, cx = 0, cy = 0;
      for (let i = 0; i < ring.length - 1; i++) {
        const x1 = ring[i][0], y1 = ring[i][1];
        const x2 = ring[i + 1][0], y2 = ring[i + 1][1];
        const cross = x1 * y2 - x2 * y1;
        twice += cross;
        cx += (x1 + x2) * cross;
        cy += (y1 + y2) * cross;
      }
      if (Math.abs(twice) < 1e-12) return ring[0];
      return [cx / (3 * twice), cy / (3 * twice)];
    }

    function buildPaths(features) {
      state.paths = features.map((feature) => {
        const path = new Path2D();
        const geom = feature.geometry;
        const polys = geom.type === 'Polygon' ? [geom.coordinates]
          : geom.coordinates;
        let main = null;
        let mainArea = -1;
        for (const poly of polys) {
          for (const ring of poly) {
            for (let i = 0; i < ring.length; i++) {
              const x = wx(ring[i][0]);
              const y = wy(ring[i][1]);
              if (i === 0) path.moveTo(x, y); else path.lineTo(x, y);
            }
            path.closePath();
          }
          const pts = poly[0];
          let area = 0;
          for (let i = 0; i < pts.length - 1; i++) {
            area += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1];
          }
          if (Math.abs(area) > mainArea) { mainArea = Math.abs(area); main = poly; }
        }
        const c = ringCentroid(main[0]);
        return {
          feature, path, iso: feature.properties.iso,
          name: feature.properties.name,
          bbox: feature.properties.bbox,
          label: { x: wx(c[0]), y: wy(c[1]) },
        };
      });
    }

    function boundsWorld() {
    return {
      x0: wx(BOUNDS.west), x1: wx(BOUNDS.east),
      y0: wy(BOUNDS.north), y1: wy(BOUNDS.south),
    };
  }

  function imageWorld() {
    return {
      x0: wx(IMAGE.west), x1: wx(IMAGE.east),
      y0: wy(IMAGE.north), y1: wy(IMAGE.south),
    };
  }

  function coverScale(w, h) {
    const b = boundsWorld();
    return Math.min(w / (b.x1 - b.x0), h / (b.y1 - b.y0)) * 0.94;
  }

  function fitView() {
    const b = boundsWorld();
    const s = coverScale(state.w, state.h);
    state.fit = {
      s,
      tx: state.w / 2 - s * (b.x0 + b.x1) / 2,
      ty: state.h / 2 - s * (b.y0 + b.y1) / 2,
    };
    state.minS = s;
    state.maxS = s * 22;
    state.view = { ...state.fit };
  }

  function clampView() {
    const v = state.view;
    const ib = imageWorld();
    v.s = clamp(v.s, state.minS, state.maxS);
    const imgW = v.s * (ib.x1 - ib.x0);
    const imgH = v.s * (ib.y1 - ib.y0);
    v.tx = imgW <= state.w
      ? (state.w - imgW) / 2 - v.s * ib.x0
      : clamp(v.tx, state.w - v.s * ib.x1, -v.s * ib.x0);
    v.ty = imgH <= state.h
      ? (state.h - imgH) / 2 - v.s * ib.y0
      : clamp(v.ty, state.h - v.s * ib.y1, -v.s * ib.y0);
  }

    function project(lon, lat) {
      return {
        x: wx(lon) * state.view.s + state.view.tx,
        y: wy(lat) * state.view.s + state.view.ty,
      };
    }

    function unproject(sx, sy) {
      return {
        lon: lx((sx - state.view.tx) / state.view.s),
        lat: ly((sy - state.view.ty) / state.view.s),
      };
    }

    function pick(lon, lat) {
      for (const p of state.paths) {
        const b = p.bbox;
        if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) continue;
        if (geometryContains(p.feature.geometry, lon, lat)) return p;
      }
      return null;
    }

    function pinSize() {
      const z = state.view.s / (state.fit.s || 1);
      return clamp(4.5 + Math.max(0, z - 1) * 1.6, 4.5, 9);
    }

    function pickDot(sx, sy) {
      const size = pinSize();
      let best = null;
      let bestD = 1e9;
      for (const d of state.dots) {
        const p = project(d.lon, d.lat);
        const headY = p.y - size * 1.5;
        const dx = p.x - sx;
        const head = Math.hypot(dx, headY - sy);
        const stem = Math.abs(dx) <= size * 0.9
          && sy >= headY && sy <= p.y + 2;
        if (head <= size + 4 || stem) {
          if (head < bestD) { bestD = head; best = d; }
        }
      }
      return best;
    }

    function drawSkin() {
      ctx.fillStyle = SEA[state.skin] || SEA.relief;
      ctx.fillRect(0, 0, state.w, state.h);
      if (state.skin === 'flat') return;
      if (state.skin === 'atlas') {
        // A vector atlas: light sea, muted land, no clouds from the raster.
        const v = state.view;
        ctx.setTransform(state.dpr * v.s, 0, 0, state.dpr * v.s,
          state.dpr * v.tx, state.dpr * v.ty);
        ctx.fillStyle = '#e6dfcb';
        for (const p of state.paths) ctx.fill(p.path);
        ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
        return;
      }
      const img = state.images[state.skin];
      if (!img || !img.complete || !img.naturalWidth) return;
      const v = state.view;
      ctx.setTransform(state.dpr * v.s, 0, 0, state.dpr * v.s,
        state.dpr * v.tx, state.dpr * v.ty);
      const x = wx(IMAGE.west);
      const y = wy(IMAGE.north);
      ctx.drawImage(img, x, y, wx(IMAGE.east) - x, wy(IMAGE.south) - y);
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    }

    function drawPlate(entry) {
      if (!entry || !entry.img || !entry.img.complete || !entry.img.naturalWidth) {
        return;
      }
      // Vector skins stay clean; the raster plate belongs on Satellite/Relief.
      if (state.skin === 'atlas' || state.skin === 'flat') return;
      // A low-coverage preview is a patchwork; the base and the explicit
      // 59 m detail are better than showing it.
      if (entry.meta.tier !== 'detail' && (entry.meta.coverage || 0) < 0.80) {
        return;
      }
      const p = state.paths.find((q) => q.iso === state.selected);
      if (!p) return;
      const v = state.view;
      const m = entry.meta.rectangle;
      ctx.save();
      ctx.setTransform(state.dpr * v.s, 0, 0, state.dpr * v.s,
        state.dpr * v.tx, state.dpr * v.ty);
      ctx.clip(p.path);
      if (state.skin === 'atlas') ctx.filter = 'saturate(.55) sepia(.16)';
      else if (state.skin === 'relief') ctx.filter = 'saturate(.85)';
      ctx.drawImage(entry.img, wx(m[0]), wy(m[3]),
        wx(m[2]) - wx(m[0]), wy(m[1]) - wy(m[3]));
      ctx.restore();
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    }

    function drawBorders() {
      const v = state.view;
      const line = LAND_LINE[state.skin] || LAND_LINE.relief;
      ctx.setTransform(state.dpr * v.s, 0, 0, state.dpr * v.s,
        state.dpr * v.tx, state.dpr * v.ty);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      const width = 1.1 / v.s;
      const dim = Boolean(state.selected);
      for (const p of state.paths) {
        if (p.iso === state.selected) continue;
        ctx.globalAlpha = dim ? 0.22 : 0.85;
        ctx.strokeStyle = line;
        ctx.lineWidth = width;
        ctx.stroke(p.path);
      }
      const hot = state.paths.find((p) => p.iso === state.selected);
      if (hot) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = '#ffcf7a';
        ctx.lineWidth = 2.2 / v.s;
        ctx.stroke(hot.path);
      }
      ctx.globalAlpha = 1;
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    }

    function drawPins() {
      if (!state.dots.length) return;
      const size = pinSize();
      ctx.lineJoin = 'round';
      for (const d of state.dots) {
        const p = project(d.lon, d.lat);
        if (p.x < -size || p.y < -size * 3
            || p.x > state.w + size || p.y > state.h + size) {
          continue;
        }
        const headY = p.y - size * 1.5;
        if (d === state.hoverDot) {
          ctx.beginPath();
          ctx.arc(p.x, headY, size + 5, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 107, 53, .25)';
          ctx.fill();
        }
        ctx.beginPath();
        ctx.moveTo(p.x - size * 0.8, p.y - size * 0.9);
        ctx.lineTo(p.x, p.y);
        ctx.lineTo(p.x + size * 0.8, p.y - size * 0.9);
        ctx.closePath();
        ctx.fillStyle = '#e5443b';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(p.x, headY, size, 0, Math.PI * 2);
        ctx.fillStyle = '#e5443b';
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(10, 14, 12, .65)';
        ctx.stroke();
        if (d === state.hoverDot) {
          ctx.beginPath();
          ctx.arc(p.x, headY, size - 2, 0, Math.PI * 2);
          ctx.fillStyle = '#ffe3b0';
          ctx.fill();
        }
      }
    }

    function drawLabels() {
      state.labelCount = 0;
      if (state.view.s < state.fit.s * 1.6) return;
      ctx.font = '600 10px "Cascadia Mono", Consolas, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const p of state.paths) {
        const count = state.counts[p.iso] || 0;
        if (!count && p.iso !== state.selected) continue;
        const x = p.label.x * state.view.s + state.view.tx;
        const y = p.label.y * state.view.s + state.view.ty;
        if (x < 60 || y < 20 || x > state.w - 60 || y > state.h - 20) continue;
        const text = count ? `${p.name} · ${count}` : p.name;
        const w = ctx.measureText(text).width;
        ctx.fillStyle = p.iso === state.selected
          ? 'rgba(255,207,122,.95)' : 'rgba(12,20,17,.82)';
        ctx.beginPath();
        ctx.roundRect(x - w / 2 - 5, y - 8, w + 10, 16, 3);
        ctx.fill();
        ctx.fillStyle = p.iso === state.selected ? '#2a1d0c' : '#ece5d5';
        ctx.fillText(text, x, y);
        state.labelCount++;
      }
    }

    function render() {
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
      drawSkin();
      drawPlate(state.plate);
      drawPlate(state.detail);
      drawBorders();
      drawPins();
      drawLabels();
    }

    function schedule() {
      if (state.raf) return;
      state.raf = requestAnimationFrame(() => {
        state.raf = 0;
        render();
      });
    }

    function setSkin(name) {
      if (!(name in SKINS) && name !== 'flat') name = 'relief';
      state.skin = name;
      if (name !== 'flat' && name !== 'atlas' && !state.images[name]) {
        const img = new Image();
        img.onload = schedule;
        img.onerror = () => {
          if (state.skin === name) { state.skin = 'atlas'; schedule(); }
        };
        img.src = SKINS[name];
        state.images[name] = img;
      }
      schedule();
    }

    function setPlate(url, meta, detail) {
      if (!url) {
        if (detail) state.detail = null; else state.plate = null;
        schedule();
        return;
      }
      const img = new Image();
      img.onload = schedule;
      img.src = url;
      if (detail) state.detail = { img, meta };
      else state.plate = { img, meta };
      schedule();
    }

    function select(iso) {
      state.selected = iso || null;
      schedule();
    }

    function setFires(dots, counts) {
      state.dots = Array.isArray(dots) ? dots : [];
      state.counts = counts || {};
      schedule();
    }

    function animateTo(target, ms = 420) {
      const from = { ...state.view };
      const t0 = performance.now();
      function step(now) {
        const t = clamp((now - t0) / ms, 0, 1);
        const e = 1 - Math.pow(1 - t, 3);
        state.view.s = from.s + (target.s - from.s) * e;
        state.view.tx = from.tx + (target.tx - from.tx) * e;
        state.view.ty = from.ty + (target.ty - from.ty) * e;
        render();
        if (t < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }

    function focusProvince(feature) {
      if (!feature) return reset();
      const b = feature.properties.bbox;
      const x0 = wx(b[0]), x1 = wx(b[2]);
      const y0 = wy(b[3]), y1 = wy(b[1]);
      const dx = Math.max(x1 - x0, 1e-6), dy = Math.max(y1 - y0, 1e-6);
      const s = clamp(Math.min(state.w / dx, state.h / dy) * 0.82,
        state.minS, state.maxS);
      animateTo({
        s,
        tx: state.w / 2 - s * (x0 + x1) / 2,
        ty: state.h / 2 - s * (y0 + y1) / 2,
      });
    }

    function reset() { animateTo({ ...state.fit }, 480); }

    function focusRect(rect) {
      const x0 = wx(rect[0]), x1 = wx(rect[2]);
      const y0 = wy(rect[3]), y1 = wy(rect[1]);
      const dx = Math.max(x1 - x0, 1e-6), dy = Math.max(y1 - y0, 1e-6);
      const s = clamp(Math.min(state.w / dx, state.h / dy) * 0.9,
        state.minS, state.maxS);
      animateTo({
        s,
        tx: state.w / 2 - s * (x0 + x1) / 2,
        ty: state.h / 2 - s * (y0 + y1) / 2,
      });
    }

    function zoomBy(k) {
      const mx = state.w / 2, my = state.h / 2;
      zoomAt(mx, my, k);
    }

    function zoomAt(mx, my, k) {
      const v = state.view;
      const target = clamp(v.s * k, state.minS, state.maxS);
      const r = target / v.s;
      v.s = target;
      v.tx = mx - (mx - v.tx) * r;
      v.ty = my - (my - v.ty) * r;
      clampView();
      schedule();
    }

    function localPoint(e) {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }


    canvas.addEventListener('pointerdown', (e) => {
      canvas.setPointerCapture(e.pointerId);
      state.pointers.set(e.pointerId, localPoint(e));
      state.dragged = false;
      if (state.pointers.size === 2) {
        const [a, b] = [...state.pointers.values()];
        state.pinch = {
          dist: Math.hypot(a.x - b.x, a.y - b.y),
          mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        };
      } else {
        state.move = { ...localPoint(e), tx: state.view.tx, ty: state.view.ty };
        canvas.style.cursor = 'grabbing';
      }
    });

    canvas.addEventListener('pointermove', (e) => {
      const pt = localPoint(e);
      if (!state.pointers.has(e.pointerId)) {
        const dot = pickDot(pt.x, pt.y);
        if (dot !== state.hoverDot) {
          state.hoverDot = dot;
          schedule();
        }
        canvas.style.cursor = dot ? 'pointer' : 'grab';
        if (cbs.onDotHover) cbs.onDotHover(dot, pt);
        return;
      }
      state.pointers.set(e.pointerId, pt);
      if (state.pointers.size === 2 && state.pinch) {
        const [a, b] = [...state.pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        if (state.pinch.dist > 0) {
          zoomAt(mid.x, mid.y, dist / state.pinch.dist);
        }
        state.view.tx += mid.x - state.pinch.mid.x;
        state.view.ty += mid.y - state.pinch.mid.y;
        clampView();
        state.pinch = { dist, mid };
        state.dragged = true;
        schedule();
        return;
      }
      if (!state.move) return;
      const dx = pt.x - state.move.x;
      const dy = pt.y - state.move.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) state.dragged = true;
      state.view.tx = state.move.tx + dx;
      state.view.ty = state.move.ty + dy;
      clampView();
      schedule();
    });

    function endPointer(e) {
      state.pointers.delete(e.pointerId);
      if (state.pointers.size < 2) state.pinch = null;
      if (state.move && e.type === 'pointerup' && !state.dragged) {
        const pt = localPoint(e);
        const dot = pickDot(pt.x, pt.y);
        const ll = unproject(pt.x, pt.y);
        const p = dot ? pick(dot.lon, dot.lat) : pick(ll.lon, ll.lat);
        if (cbs.onDot && dot) cbs.onDot(dot, p ? p.feature : null);
        else if (cbs.onSelect) cbs.onSelect(p ? p.feature : null);
      }
      state.move = null;
      canvas.style.cursor = 'grab';
    }
    canvas.addEventListener('pointerup', endPointer);
    canvas.addEventListener('pointercancel', endPointer);
    canvas.addEventListener('pointerleave', () => {
      if (state.hoverDot) {
        state.hoverDot = null;
        schedule();
      }
      canvas.style.cursor = 'grab';
      if (cbs.onDotHover) cbs.onDotHover(null, null);
    });

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const pt = localPoint(e);
      const k = Math.exp(-e.deltaY * 0.0014);
      zoomAt(pt.x, pt.y, k);
    }, { passive: false });

    canvas.addEventListener('dblclick', (e) => {
      const pt = localPoint(e);
      zoomAt(pt.x, pt.y, 1.9);
    });

    function resize() {
      const w = canvas.clientWidth || 1;
      const h = canvas.clientHeight || 1;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const first = state.w === 1;
      state.w = w; state.h = h; state.dpr = dpr;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      if (first) {
        fitView();
      } else {
        const cover = coverScale(w, h);
        const b = boundsWorld();
        state.fit = {
          s: cover,
          tx: w / 2 - cover * (b.x0 + b.x1) / 2,
          ty: h / 2 - cover * (b.y0 + b.y1) / 2,
        };
        state.minS = cover;
        state.maxS = cover * 26;
        if (state.view.s < cover) state.view = { ...state.fit };
      }
      clampView();
      render();
    }

    if (opts.features) buildPaths(opts.features);
    setSkin(state.skin);
    window.addEventListener('resize', resize);
    canvas.style.cursor = 'grab';
    resize();

    return {
      resize, setSkin, setFires, select, setPlate, focusProvince, focusRect,
      reset,
      zoomBy, render,
      setProvinces: (features) => { buildPaths(features); resize(); },
      clearPlate: () => { state.plate = null; state.detail = null; schedule(); },
      clearSelection: () => { state.selected = null; schedule(); },
      view: () => ({
        scale: state.view.s, tx: state.view.tx, ty: state.view.ty,
        fit: state.fit.s, skin: state.skin, selected: state.selected,
        plate: Boolean(state.plate && state.plate.img.complete),
        detail: Boolean(state.detail && state.detail.img.complete),
        dots: state.dots.length,
        labels: state.labelCount,
      }),
      project, unproject,
      element: canvas,
    };
  }

  root.PyroMap2D = { create, wx, wy, BOUNDS };
})(window);
