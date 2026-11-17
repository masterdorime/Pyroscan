/* PyroScan mission console — static shell over the real Brighton ODM output. */
const C = Cesium;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const rad = (d) => (d * Math.PI) / 180;
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

const fmtDay = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).toUpperCase();
};
const fmtClock = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-GB', {
    hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  });
};
const fmtCoord = (lat, lon) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? 'E' : 'W'}`;
const fmtWindow = (start, end) => {
  const day = fmtDay(start);
  const a = fmtClock(start), b = fmtClock(end);
  if (!day) return '—';
  return a && b ? `${day} · ${a}–${b} UTC` : day;
};

const CONTEXT_CAMERA = { heading: 45, pitch: -22, range: 300 };

/* ---- view modes: Drone / Terrain / Regional ---- */
const MODES = {
  drone: { scene: 'reconstruction', camera: { heading: 45, pitch: -30, range: 220 } },
  terrain: { scene: 'context', camera: { heading: 45, pitch: -25, range: 600 } },
  regional: { scene: 'context', camera: { heading: 45, pitch: -45, range: 3000 } },
};
const MODE_ORDER = ['drone', 'terrain', 'regional'];

function hasPatch() {
  const m = state.f && state.f.mission;
  return Boolean(m && m.gsd_cm && m.aligned);
}

function hasTerrain() {
  const a = state.f && state.f.assets;
  return Boolean(a && a.context_dem);
}

function modeAvailability() {
  const den = hasTerrain();
  return {
    drone: hasPatch(),
    terrain: den,
    regional: den,
  };
}

function fmtAge(seconds) {
  if (seconds == null) return '—';
  const mins = Math.round(seconds / 60);
  if (mins < 90) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

function modeBadge(mode) {
  const items = (state.f && state.f.providers && state.f.providers.items) || {};
  const mins = (it) => fmtAge(it && it.age_s);
  if (mode === 'drone') {
    const gsd = state.f && state.f.mission && state.f.mission.gsd_cm;
    return `${gsd} cm · patch`;
  }
  if (mode === 'regional') {
    const ring = state.f && state.f.providers && state.f.providers.ring_km;
    return `${Math.round(ring || 15)} km ring · ${mins(items.weather)}`;
  }
  const dem = items.context_dem;
  const cell = dem && dem.detail ? `30 m · ${dem.detail}` : '30 m';
  return `${cell} · ${mins(dem)}`;
}

function readModeFromHash() {
  const m = (location.hash.match(/^#\/[^/]+\/(\w+)/) || [])[1];
  return MODE_ORDER.includes(m) ? m : null;
}

function writeModeHash(mode) {
  const id = state.f && state.f.mission && state.f.mission.id;
  if (!id) return;
  const next = `#/${id}/${mode}`;
  if (location.hash !== next) history.replaceState(null, '', next);
}

function syncTabs() {
  const mode = state.viewMode || 'terrain';
  const avail = modeAvailability();
  $$('#modes button').forEach((b) => {
    const m = b.dataset.mode;
    b.classList.toggle('active', m === mode);
    b.disabled = !avail[m];
    b.title = avail[m] ? '' : (m === 'drone' ? 'no reconstruction yet' : 'no context terrain');
  });
  const badge = $('#mode-badge');
  if (badge) badge.textContent = modeBadge(mode);
}

function setViewMode(mode, { animate = true } = {}) {
  const cfg = MODES[mode];
  if (!cfg) return;
  state.viewMode = mode;
  setMode(cfg.scene);
  const to = { ...cfg.camera };
  if (animate) flyCamera(to); else { state.camera = to; applyCamera(); }
  syncTabs();
  writeModeHash(mode);
}

function initModes() {
  const avail = modeAvailability();
  let mode = readModeFromHash();
  if (!mode || !avail[mode]) mode = avail.drone ? 'drone' : 'terrain';
  $$('#modes button').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled) return;
    setViewMode(b.dataset.mode);
  }));
  setViewMode(mode, { animate: false });
}const RECON_CAMERA = { heading: 45, pitch: -30, range: 220 };
const RECON_ENTER_RANGE = 220;
const RECON_EXIT_RANGE = 380;

const state = {
  h: null, f: null,
  orthoUrl: 'data/ortho.webp', orthoShadedUrl: 'data/ortho_shaded.webp',
  base: 'terrain',
  mode: 'context',
  forecast: 0, playing: false, is2D: false,
  camera: { ...CONTEXT_CAMERA },
  prims: {}, bases: {}, mats: {}, groups: {}, pred: [], predLabels: [],
  windEntities: [], center: null, W: 0, H: 0, heights: null, elevProfile: null,
  flight: null, hotspotPins: [], footprintEntities: [], flyRaf: 0,
};

const AMBER = C.Color.fromCssColorString('#e5a954');
const FLAME = C.Color.fromCssColorString('#ff6b35');
const RED = C.Color.fromCssColorString('#e5443b');
const SILVER = C.Color.fromCssColorString('#9494a0');

function fail(e) {
  console.error(e);
  $('#err').textContent = `BOOT ${e?.stack || e}`;
}

(async function init() {
  const live = await fetch('api/v1/missions/latest', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  const f = live || await fetch('data/fixtures.json').then((r) => r.json());
  const hmUrl = (live && live.assets && live.assets.heightmap) || 'data/heightmap.json';
  const h = await fetch(hmUrl, { cache: 'no-store' }).then((r) => r.json());
  state.h = h; state.f = f;
  loadContextImagery(live);
  state.orthoUrl = (live && live.assets && live.assets.ortho) || 'data/ortho.webp';
  state.orthoShadedUrl = (live && live.assets && live.assets.ortho_shaded) || 'data/ortho_shaded.webp';
  state.W = h.width; state.H = h.height;
  state.heights = Float32Array.from(h.heights_m);

  let hmin = Infinity, hmax = -Infinity;
  for (const v of state.heights) { if (v < hmin) hmin = v; if (v > hmax) hmax = v; }
  const cx = (h.west + h.east) / 2;
  const cy = (h.south + h.north) / 2;
  state.center = { lon: cx, lat: cy, height: (hmin + hmax) / 2, hmin, hmax };
  state.elevProfile = elevationProfile();

  initViewer();
  buildStudioFloor();
  buildLandscape();
  loadContextDem(live);
  buildShadow();
  buildMission();
  buildOverlays();
  buildWind();
  buildPrediction();
  buildHotspots();
  buildFlightPath();
  buildFootprint();
  setMode(state.mode);
  applyCamera();
  wireCamera();
  wireSceneClicks();
  populateRail();
  renderProviders();
  renderFiresInset();
  initModes();
  wireUI();
  wireTheme();
  renderCharts();
  startFps();
  window.__ready = true;
})().catch(fail);

/* ---------------- scene ---------------- */
function initViewer() {
  const viewer = new C.Viewer('cesium', {
    baseLayer: false,
    globe: false,
    creditContainer: document.createElement('div'),
    baseLayerPicker: false, geocoder: false, homeButton: false,
    sceneModePicker: false, navigationHelpButton: false,
    animation: false, timeline: false, infoBox: false,
    selectionIndicator: false, fullscreenButton: false, vrButton: false,
    skyBox: false, skyAtmosphere: false, scene3DOnly: true,
  });
  viewer.scene.backgroundColor = C.Color.fromCssColorString('#dfe8e3');
  viewer.scene.fog.enabled = false;
  viewer.scene.screenSpaceCameraController.enableInputs = false;
  state.viewer = viewer;
  state.canvas = viewer.scene.canvas;
  state.canvas.style.touchAction = 'none';
}

function hAt(u, v) {
  const i = clamp(Math.round(u * (state.W - 1)), 0, state.W - 1);
  const j = clamp(Math.round((1 - v) * (state.H - 1)), 0, state.H - 1);
  return state.heights[j * state.W + i];
}
function uv2ll(u, v) {
  return {
    lon: state.h.west + (state.h.east - state.h.west) * u,
    lat: state.h.south + (state.h.north - state.h.south) * v,
  };
}

function elevationProfile(n = 48) {
  const labels = { 0: 'N–S', 45: 'NE–SW', 90: 'E–W', 135: 'NW–SE' };
  let best = null;
  for (const deg of [0, 45, 90, 135]) {
    const ang = rad(deg);
    const du = Math.sin(ang), dv = Math.cos(ang);
    const tx = du ? 0.5 / Math.abs(du) : Infinity;
    const ty = dv ? 0.5 / Math.abs(dv) : Infinity;
    const tmax = Math.min(tx, ty);
    const data = [];
    for (let i = 0; i < n; i++) {
      const t = -tmax + (2 * tmax * i) / (n - 1);
      data.push(hAt(clamp(0.5 + du * t, 0, 1), clamp(0.5 + dv * t, 0, 1)));
    }
    const min = Math.min(...data), max = Math.max(...data);
    const relief = max - min;
    if (!best || relief > best.relief) {
      best = { data, min, max, bearing: deg, relief, label: labels[deg] };
    }
  }
  return best;
}

function buildGeometry() {
  const { W, H, heights } = state;
  const { west, south, east, north } = state.h;
  const pos = new Float64Array(W * H * 3);
  const st = new Float32Array(W * H * 2);
  let p = 0, q = 0;
  for (let j = 0; j < H; j++) {
    const lat = north - (north - south) * (j / (H - 1));
    for (let i = 0; i < W; i++) {
      const lon = west + (east - west) * (i / (W - 1));
      const c = C.Cartesian3.fromDegrees(lon, lat, heights[j * W + i]);
      pos[p++] = c.x; pos[p++] = c.y; pos[p++] = c.z;
      st[q++] = i / (W - 1); st[q++] = 1 - j / (H - 1);
    }
  }
  const idx = new Uint32Array((W - 1) * (H - 1) * 6);
  let k = 0;
  for (let j = 0; j < H - 1; j++) {
    for (let i = 0; i < W - 1; i++) {
      const a = j * W + i, b = a + 1, c = a + W, d = c + 1;
      idx[k++] = a; idx[k++] = c; idx[k++] = b;
      idx[k++] = b; idx[k++] = c; idx[k++] = d;
    }
  }
  const geo = new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: pos }),
      st: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 2, values: st }),
    },
    indices: idx,
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(pos),
  });
  return C.GeometryPipeline.computeNormal(geo);
}

function offsetMatrix(m) {
  const c = state.center;
  const up = C.Ellipsoid.WGS84.geodeticSurfaceNormal(C.Cartesian3.fromDegrees(c.lon, c.lat, c.height), new C.Cartesian3());
  const t = C.Cartesian3.multiplyByScalar(up, m, new C.Cartesian3());
  return C.Matrix4.fromTranslation(t);
}

function imageMaterial(texture, alpha = 0.99) {
  return new C.Material({
    fabric: { type: 'Image', uniforms: { image: texture, color: new C.Color(1, 1, 1, alpha) } },
  });
}

function addMaterialPrimitive(geometry, texture, alpha, offset, flat = false) {
  const mat = imageMaterial(texture, alpha);
  const prim = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry, modelMatrix: offsetMatrix(offset) }),
    appearance: new C.MaterialAppearance({ material: mat, translucent: true, flat, faceForward: true, renderState: { depthMask: true } }),
    asynchronous: false,
  });
  state.viewer.scene.primitives.add(prim);
  return { prim, mat };
}

function buildMission() {
  const geo = buildGeometry();
  state.geometry = geo;
  const ortho = addMaterialPrimitive(geo, state.orthoShadedUrl, 0.99, 0, true);
  const terrain = addMaterialPrimitive(geo, 'data/terrain_base.webp', 0.99, 0, true);
  const elev = addMaterialPrimitive(geo, 'data/elevation.png', 0.99, 0, true);
  const sev = addMaterialPrimitive(geo, 'data/severity_base.png', 0.99, 0, true);
  state.bases = { terrain: terrain.prim, ortho: ortho.prim, elevation: elev.prim, severity: sev.prim };
  state.baseMats = {
    terrain: { dark: terrain.mat, paper: imageMaterial('data/terrain_base_paper.webp') },
    ortho: { dark: ortho.mat, paper: imageMaterial('data/ortho_shaded_paper.webp') },
    elevation: { dark: elev.mat, paper: imageMaterial('data/elevation_paper.png') },
    severity: { dark: sev.mat, paper: imageMaterial('data/severity_base_paper.png') },
  };
  showBase(state.base);
}

function buildOverlays() {
  const heat = addMaterialPrimitive(state.geometry, 'data/heat.png', 0.65, 0.9, true);
  state.prims.heat = heat.prim;
  state.mats.heat = heat.mat;
}

function buildStudioFloor() {
  const pad = 1.5;
  const h = state.h;
  const base = state.center.hmin - 1.6;
  const west = h.west - (h.east - h.west) * pad;
  const east = h.east + (h.east - h.west) * pad;
  const south = h.south - (h.north - h.south) * pad;
  const north = h.north + (h.north - h.south) * pad;
  const corners = [
    [west, north], [east, north], [east, south], [west, south],
  ];
  const pos = [];
  for (const [lon, lat] of corners) {
    const p = C.Cartesian3.fromDegrees(lon, lat, base);
    pos.push(p.x, p.y, p.z);
  }
  const geo = new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(pos) }),
      st: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 2, values: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]) }),
    },
    indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(pos),
  });
  const mat = new C.Material({
    fabric: { type: 'Image', uniforms: { image: 'data/studio_floor.png', color: new C.Color(1, 1, 1, 0.99) } },
  });
  const prim = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry: geo }),
    appearance: new C.MaterialAppearance({ material: mat, translucent: true, flat: true }),
    asynchronous: false,
  });
  state.viewer.scene.primitives.add(prim);
  state.prims.studio = prim;
}

function buildLandscape() {
  const c = state.f.context;
  const base = state.center.hmin - 1.6;
  const mat = new C.Material({
    fabric: { type: 'Image', uniforms: { image: 'data/context_bright.png', color: new C.Color(1, 1, 1, 1) } },
  });
  const lonAt = (u) => c.west + (c.east - c.west) * u;
  const latAt = (v) => c.north - (c.north - c.south) * v;
  const quad = (u0, u1, v0, v1, translucent) => {
    const corners = [
      [u0, v0], [u1, v0], [u1, v1], [u0, v1],
    ];
    const pos = [];
    for (const [u, v] of corners) {
      const p = C.Cartesian3.fromDegrees(lonAt(u), latAt(v), base);
      pos.push(p.x, p.y, p.z);
    }
    const geo = new C.Geometry({
      attributes: {
        position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(pos) }),
        st: new C.GeometryAttribute({
          componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 2,
          values: new Float32Array([u0, v0, u1, v0, u1, v1, u0, v1]),
        }),
      },
      indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
      primitiveType: C.PrimitiveType.TRIANGLES,
      boundingSphere: C.BoundingSphere.fromVertices(pos),
    });
    return new C.Primitive({
      geometryInstances: new C.GeometryInstance({ geometry: geo }),
      appearance: new C.MaterialAppearance({ material: mat, flat: true, translucent }),
      asynchronous: false,
    });
  };
  const collection = new C.PrimitiveCollection();
  // The imagery asset covers 4 km; the mosaic covers 1.35 km. Map only the
  // matching sub-rectangle so the scene is not zoomed out by a factor of three.
  const inner = 0.2;
  const outer = 1 - inner;
  state.prims.landscapeCenter = quad(inner, outer, inner, outer, false);  // opaque centre
  collection.add(state.prims.landscapeCenter);
  if (!state.contextImageryUrl) {
    // Feathered bands exist to fade the Esri PNG's alpha edge. Sentinel-2 is
    // opaque, and translucent quads over the bright terrain compound to white.
    collection.add(quad(0, 1, 0, inner, true));          // north band
    collection.add(quad(0, 1, outer, 1, true));          // south band
    collection.add(quad(0, inner, inner, outer, true));  // west band
    collection.add(quad(outer, 1, inner, outer, true));  // east band
  }
  state.viewer.scene.primitives.add(collection);
  state.prims.landscape = collection;
}

function applySceneTheme() {
  if (!state.viewer) return;
  const context = state.mode === 'context';
  const dark = document.documentElement.dataset.theme === 'obsidian';
  const useStudio = dark && !context;
  if (state.prims.studio) state.prims.studio.show = useStudio;
  if (state.prims.landscape) state.prims.landscape.show = !useStudio;
  state.viewer.scene.backgroundColor = useStudio
    ? C.Color.fromCssColorString('#070709')
    : C.Color.fromCssColorString('#dfe8e3');
  const tint = dark ? 1 : 1.55;
  for (const [name, pair] of Object.entries(state.baseMats || {})) {
    const mat = dark ? pair.dark : pair.paper;
    const prim = state.bases[name];
    if (prim && prim.appearance.material !== mat) prim.appearance.material = mat;
    mat.uniforms.color = new C.Color(tint, tint, tint * 0.98, 0.99);
  }
  if (state.flight) {
    const col = C.Color.fromCssColorString(dark ? '#9494a0' : '#575248').withAlpha(0.55);
    state.flight.polyline.material = new C.PolylineDashMaterialProperty({ color: col, dashLength: 10 });
  }
}

function buildShadow() {
  const c = state.center;
  const base = state.center.hmin - 0.8;
  const pad = 0.16;
  const west = state.h.west - (state.h.east - state.h.west) * pad;
  const east = state.h.east + (state.h.east - state.h.west) * pad;
  const south = state.h.south - (state.h.north - state.h.south) * pad;
  const north = state.h.north + (state.h.north - state.h.south) * pad;
  const corners = [[west, north], [east, north], [east, south], [west, south]];
  const pos = [];
  for (const [lon, lat] of corners) {
    const p = C.Cartesian3.fromDegrees(lon, lat, base);
    pos.push(p.x, p.y, p.z);
  }
  const geo = new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(pos) }),
      st: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 2, values: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]) }),
    },
    indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(pos),
  });
  const mat = new C.Material({
    fabric: { type: 'Image', uniforms: { image: 'data/shadow.png', color: new C.Color(1, 1, 1, 0.99) } },
  });
  const prim = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry: geo }),
    appearance: new C.MaterialAppearance({ material: mat, translucent: true, flat: true }),
    asynchronous: false,
  });
  state.viewer.scene.primitives.add(prim);
  state.prims.shadow = prim;
}

/* ---------------- camera ---------------- */
function applyCamera() {
  const c = state.center;
  const { heading, pitch, range } = state.camera;
  const target = C.Cartesian3.fromDegrees(c.lon, c.lat, c.height);
  state.viewer.camera.lookAt(
    target,
    new C.HeadingPitchRange(rad(heading), rad(pitch), range)
  );
  state.viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
  $('#compass').style.setProperty('--heading', `${-heading}deg`);
}

function flyCamera(to, duration = 700) {
  if (state.flyRaf) cancelAnimationFrame(state.flyRaf);
  const from = { ...state.camera };
  const start = performance.now();
  const tick = (now) => {
    const t = clamp((now - start) / duration, 0, 1);
    const e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    state.camera.heading = from.heading + (to.heading - from.heading) * e;
    state.camera.pitch = from.pitch + (to.pitch - from.pitch) * e;
    state.camera.range = from.range + (to.range - from.range) * e;
    applyCamera();
    if (t < 1) {
      state.flyRaf = requestAnimationFrame(tick);
    } else {
      state.camera = { ...to };
      state.flyRaf = 0;
    }
  };
  state.flyRaf = requestAnimationFrame(tick);
}

function openReconstruction() {
  if (state.mode === 'reconstruction') return;
  state.is2D = false;
  $('#toggle-2d').textContent = '2D';
  $('#app').classList.remove('is-2d');
  setMode('reconstruction');
  flyCamera(RECON_CAMERA);
}

function closeReconstruction() {
  if (state.mode === 'context') return;
  state.is2D = false;
  $('#toggle-2d').textContent = '2D';
  $('#app').classList.remove('is-2d');
  setMode('context');
  flyCamera(CONTEXT_CAMERA);
}

function checkZoomMode() {
  if (state.is2D) return;
  if (state.mode === 'context' && state.camera.range <= RECON_ENTER_RANGE) openReconstruction();
  else if (state.mode === 'reconstruction' && state.camera.range >= RECON_EXIT_RANGE) closeReconstruction();
}

function wireCamera() {
  const el = state.canvas;
  let drag = null;
  el.addEventListener('pointerdown', (e) => {
    if (state.flyRaf) { cancelAnimationFrame(state.flyRaf); state.flyRaf = 0; }
    drag = { x: e.clientX, y: e.clientY, id: e.pointerId };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    state.camera.heading += dx * 0.28;
    state.camera.pitch = clamp(state.camera.pitch + dy * 0.22, -85, -12);
    applyCamera();
  });
  el.addEventListener('pointerup', (e) => {
    if (drag && e.pointerId === drag.id) { drag = null; el.releasePointerCapture(e.pointerId); }
  });
  el.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (state.flyRaf) { cancelAnimationFrame(state.flyRaf); state.flyRaf = 0; }
    state.camera.range = clamp(state.camera.range * Math.exp(e.deltaY * 0.0011), 150, 1000);
    applyCamera();
    checkZoomMode();
  }, { passive: false });
}

function wireSceneClicks() {
  const handler = new C.ScreenSpaceEventHandler(state.canvas);
  handler.setInputAction((movement) => {
    if (state.mode !== 'context') return;
    const picked = state.viewer.scene.pick(movement.position);
    if (!C.defined(picked)) return;
    const id = picked.id;
    if (state.footprintEntities.includes(id) || state.hotspotPins.includes(id)) openReconstruction();
  }, C.ScreenSpaceEventType.LEFT_CLICK);
}

function setMode(mode) {
  state.mode = mode;
  const ctx = mode === 'context';
  $('#app').classList.toggle('mode-context', ctx);
  applyAllLayers();
  if (state.prims.shadow) state.prims.shadow.show = !ctx;
  if (state.groups.footprint) state.groups.footprint.show = ctx;
  applySceneTheme();
  renderLegend();
  renderFiresInset();
  syncTabs();
}

/* ---------------- context imagery (Sentinel-2) ---------------- */
const CONTEXT_TEXTURE = 'data/context_bright.png';

function loadContextImagery(live) {
  const url = live && live.assets && live.assets.context_imagery;
  if (url) state.contextImageryUrl = url;
}

function contextTexture() {
  return state.contextImageryUrl || CONTEXT_TEXTURE;
}

/* ---------------- context terrain (30 m DEM) ---------------- */
function loadContextDem(live) {
  const url = live && live.assets && live.assets.context_dem;
  if (!url) return;
  fetch(url, { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((dem) => {
      if (!dem || !dem.heights_m || !dem.width) return;
      state.contextDem = dem;
      buildContextTerrain();
    })
    .catch(() => { /* the flat plane stays; Context still works */ });
}

function buildContextTerrain() {
  const dem = state.contextDem;
  const collection = state.prims.landscape;
  if (!dem || !collection || !state.prims.landscapeCenter) return;

  const c = state.f.context;
  const base = state.center.hmin - 1.6;
  const N = 96;

  const sample = (lon, lat) => {
    const u = (lon - dem.west) / (dem.east - dem.west);
    const v = (dem.north - lat) / (dem.north - dem.south);
    if (u < 0 || u > 1 || v < 0 || v > 1) return null;
    const x = clamp(Math.round(u * (dem.width - 1)), 0, dem.width - 1);
    const y = clamp(Math.round(v * (dem.height - 1)), 0, dem.height - 1);
    return dem.heights_m[y * dem.width + x];
  };

  // Anchor relief so the DEM at the mission centre meets the existing plane:
  // the shape is real, the datum stays tied to the mission so the patch and
  // its surroundings never invert.
  const centreH = sample((c.west + c.east) / 2, (c.south + c.north) / 2);
  const offset = centreH == null ? 0 : base - centreH;

  const pos = [];
  const st = [];
  const idx = [];
  for (let j = 0; j <= N; j++) {
    const v = j / N;
    const lat = c.north - (c.north - c.south) * v;
    for (let i = 0; i <= N; i++) {
      const u = i / N;
      const lon = c.west + (c.east - c.west) * u;
      const h = sample(lon, lat);
      const p = C.Cartesian3.fromDegrees(lon, lat, h == null ? base : h + offset);
      pos.push(p.x, p.y, p.z);
      st.push(0.2 + 0.6 * u, 0.2 + 0.6 * v);
    }
  }
  for (let j = 0; j < N; j++) {
    for (let i = 0; i < N; i++) {
      const a = j * (N + 1) + i;
      const b = a + 1;
      const d = a + N + 1;
      const e = d + 1;
      idx.push(a, b, d, b, e, d);
    }
  }

  const material = new C.Material({
    fabric: { type: 'Image', uniforms: { image: 'data/context_bright.png', color: new C.Color(1, 1, 1, 1) } },
  });
  const geometry = new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({
        componentDatatype: C.ComponentDatatype.DOUBLE,
        componentsPerAttribute: 3,
        values: new Float64Array(pos),
      }),
      st: new C.GeometryAttribute({
        componentDatatype: C.ComponentDatatype.FLOAT,
        componentsPerAttribute: 2,
        values: new Float32Array(st),
      }),
    },
    indices: new Uint32Array(idx),
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(pos),
  });

  state.prims.contextTerrain = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry }),
    appearance: new C.MaterialAppearance({ material, flat: true, translucent: false }),
    asynchronous: false,
  });
  collection.add(state.prims.contextTerrain);
  state.prims.landscapeCenter.show = false;
}

/* ---------------- wind ---------------- */
function buildWind() {
  const ds = new C.CustomDataSource('wind');
  state.viewer.dataSources.add(ds);
  state.groups.wind = ds;
  const f = state.f;
  const ang = rad(f.prediction.wind_to_deg);
  const mLat = 111320, mLon = 111320 * Math.cos(rad(state.center.lat));
  const len = 26 + f.weather.wind_speed_kmh * 0.8;
  for (let iv = 0; iv < 4; iv++) {
    for (let iu = 0; iu < 4; iu++) {
      const u = 0.20 + iu * 0.20, v = 0.20 + iv * 0.20;
      const start = uv2ll(u, v);
      const sh = hAt(u, v) + 3;
      const e = Math.sin(ang) * len, n = Math.cos(ang) * len;
      const end = { lon: start.lon + e / mLon, lat: start.lat + n / mLat };
      const eh = hAt((end.lon - state.h.west) / (state.h.east - state.h.west), (end.lat - state.h.south) / (state.h.north - state.h.south)) + 3;
      const color = C.Color.fromCssColorString('#2f7f8f').withAlpha(0.8);
      const ent = ds.entities.add({
        polyline: {
          positions: C.Cartesian3.fromDegreesArrayHeights([start.lon, start.lat, sh, end.lon, end.lat, eh]),
          width: 2.2, material: new C.ColorMaterialProperty(color), arcType: C.ArcType.NONE,
        },
      });
      state.windEntities.push({ ent, base: color });
      if (iu % 2 === 0 && iv % 2 === 0) {
        const back = 7;
        for (const s of [-1, 1]) {
          const a2 = ang + Math.PI + s * 0.45;
          const hx = end.lon + (Math.sin(a2) * back) / mLon;
          const hy = end.lat + (Math.cos(a2) * back) / mLat;
          ds.entities.add({
            polyline: {
              positions: C.Cartesian3.fromDegreesArrayHeights([end.lon, end.lat, eh, hx, hy, eh]),
              width: 2.2, material: new C.ColorMaterialProperty(color), arcType: C.ArcType.NONE,
            },
          });
        }
      }
    }
  }
}

/* ---------------- prediction ---------------- */
function ellipsePoints(step) {
  const c = state.center;
  const ang = rad(state.f.prediction.wind_to_deg);
  const along = 20 + step * 0.9;
  const across = 15 + step * 0.52;
  const drift = step * 0.35;
  const mLat = 111320, mLon = 111320 * Math.cos(rad(c.lat));
  const out = [];
  for (let i = 0; i < 48; i++) {
    const t = (i / 48) * Math.PI * 2;
    const e = Math.sin(ang) * (drift + along * Math.cos(t)) - Math.cos(ang) * (across * Math.sin(t));
    const n = Math.cos(ang) * (drift + along * Math.cos(t)) + Math.sin(ang) * (across * Math.sin(t));
    const lon = c.lon + e / mLon;
    const lat = c.lat + n / mLat;
    const u = (lon - state.h.west) / (state.h.east - state.h.west);
    const v = (lat - state.h.south) / (state.h.north - state.h.south);
    out.push(C.Cartesian3.fromDegrees(lon, lat, hAt(u, v) + 2));
  }
  return out;
}

function buildPrediction() {
  const ds = new C.CustomDataSource('prediction');
  state.viewer.dataSources.add(ds);
  state.groups.prediction = ds;
  const steps = state.f.prediction.steps;
  for (const s of steps) {
    const pts = ellipsePoints(s.min);
    const fillBase = s.min === 0 ? 0.12 : s.min === 30 ? 0.08 : 0.05;
    const color = s.min === 0 ? RED : s.min === 30 ? FLAME : AMBER;
    const ent = ds.entities.add({
      polygon: {
        hierarchy: new C.PolygonHierarchy(pts),
        perPositionHeight: true,
        material: new C.ColorMaterialProperty(color.withAlpha(fillBase)),
        outline: false,
      },
    });
    const front = ds.entities.add({
      polyline: {
        positions: pts,
        width: s.min === 0 ? 3.2 : 2.6,
        material: new C.ColorMaterialProperty(color.withAlpha(0.95)),
        arcType: C.ArcType.NONE,
      },
    });
    state.pred.push({ step: s.min, ent, front, baseAlpha: fillBase });

    const ang = rad(state.f.prediction.wind_to_deg);
    const along = 20 + s.min * 0.9 + 10;
    const lon = state.center.lon + (Math.sin(ang) * along) / (111320 * Math.cos(rad(state.center.lat)));
    const lat = state.center.lat + (Math.cos(ang) * along) / 111320;
    const u = (lon - state.h.west) / (state.h.east - state.h.west);
    const v = (lat - state.h.south) / (state.h.north - state.h.south);
    const label = ds.entities.add({
      position: C.Cartesian3.fromDegrees(lon, lat, hAt(u, v) + 4),
      label: {
        text: s.min === 0 ? 'Now' : `+${s.min} min`,
        font: '600 10px Consolas, monospace',
        fillColor: color,
        showBackground: true,
        backgroundColor: C.Color.fromCssColorString('#070709').withAlpha(0.82),
        backgroundPadding: new C.Cartesian2(6, 4),
        pixelOffset: new C.Cartesian2(0, -8),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    state.predLabels.push({ step: s.min, ent: label });
  }
}

/* ---------------- hotspots / path ---------------- */
function buildHotspots() {
  const ds = new C.CustomDataSource('hotspots');
  state.viewer.dataSources.add(ds);
  state.groups.hotspots = ds;
  for (const [idx, s] of state.f.hotspots.entries()) {
    const p = uv2ll(s.u, s.v);
    const h = hAt(s.u, s.v) + 3;
    const color = s.confidence > 0.8 ? RED : FLAME;
    const ent = {
      position: C.Cartesian3.fromDegrees(p.lon, p.lat, h),
      point: { pixelSize: idx === 0 ? 11 : 8, color, outlineColor: C.Color.WHITE, outlineWidth: 2 },
    };
    if (idx === 0) {
      ent.label = {
        text: s.id + ' - ' + Math.round(s.confidence * 100) + '%',
        font: '10px Consolas, monospace',
        fillColor: C.Color.fromCssColorString('#e8e8ea'),
        showBackground: true,
        backgroundColor: C.Color.fromCssColorString('#070709').withAlpha(0.82),
        backgroundPadding: new C.Cartesian2(5, 3),
        pixelOffset: new C.Cartesian2(0, -15),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }
    ds.entities.add(ent);
    state.hotspotPins.push(ent);
    ds.entities.add({
      position: C.Cartesian3.fromDegrees(p.lon, p.lat, h),
      ellipse: {
        semiMajorAxis: 6, semiMinorAxis: 6,
        material: C.Color.TRANSPARENT,
        outline: true, outlineColor: C.Color.WHITE.withAlpha(0.55), outlineWidth: 1,
        height: h,
      },
    });
  }
}
function buildFlightPath() {
  const ds = new C.CustomDataSource('flight');
  state.viewer.dataSources.add(ds);
  state.groups.flight = ds;
  const path = [...state.f.flight_path, state.f.flight_path[0]];
  const pts = path.map(([u, v]) => {
    const p = uv2ll(u, v);
    return [p.lon, p.lat, hAt(u, v) + 5];
  }).flat();
  state.flight = ds.entities.add({
    polyline: {
      positions: C.Cartesian3.fromDegreesArrayHeights(pts),
      width: 1.4,
      material: new C.PolylineDashMaterialProperty({ color: SILVER.withAlpha(0.45), dashLength: 10 }),
      arcType: C.ArcType.NONE,
    },
  });
}

function buildFootprint() {
  const ds = new C.CustomDataSource('footprint');
  state.viewer.dataSources.add(ds);
  state.groups.footprint = ds;
  const c = state.center;
  const h = c.hmin - 1.1;
  const radius = Math.sqrt(state.f.mission.area_m2 / Math.PI);
  const outline = ds.entities.add({
    position: C.Cartesian3.fromDegrees(c.lon, c.lat, h),
    ellipse: {
      semiMajorAxis: radius,
      semiMinorAxis: radius,
      height: h,
      material: AMBER.withAlpha(0.07),
      outline: true,
      outlineColor: AMBER.withAlpha(0.95),
      outlineWidth: 2.4,
    },
  });
  const area = (state.f.mission.area_m2 / 10000).toFixed(2);
  const label = ds.entities.add({
    position: C.Cartesian3.fromDegrees(c.lon, c.lat, c.hmin + 6),
    label: {
      text: `ODM RECONSTRUCTION · ${area} ha`,
      font: '600 10px Consolas, monospace',
      fillColor: AMBER,
      showBackground: true,
      backgroundColor: C.Color.fromCssColorString('#070709').withAlpha(0.82),
      backgroundPadding: new C.Cartesian2(6, 4),
      pixelOffset: new C.Cartesian2(0, 34),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  state.footprintEntities = [outline, label];
}

/* ---------------- UI ---------------- */
/* ---------------- live data card ---------------- */
const PROVIDER_ORDER = ['weather', 'regional_fires', 'context_dem', 'context_imagery', 'places'];

function providerAgeLabel(item) {
  if (!item) return '—';
  if (item.status === 'unconfigured') return 'add key to enable';
  if (item.status === 'unavailable') return item.reason === 'warming' ? 'fetching…' : 'unavailable';
  if (item.status === 'error' && item.reason === 'fixture_fallback') return 'offline sample';
  if (item.age_s == null) return 'no data';
  const mins = Math.round(item.age_s / 60);
  if (mins < 60) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

function renderProviders() {
  const providers = state.f && state.f.providers;
  const list = $('#ld-list');
  const card = $('#live-data-card');
  if (!list || !card) return;
  if (!providers) { card.hidden = true; return; }

  $('#ld-ring').textContent = `${Math.round(providers.ring_km || 0)} km ring`;
  const rows = [];
  const attributions = new Set();

  for (const key of PROVIDER_ORDER) {
    const item = providers.items && providers.items[key];
    if (!item) continue;
    const suffix = item.simulated ? ' · SIMULASI' : '';
    let fact = '';
    if (key === 'context_dem') fact = ' · 30 m';
    if (key === 'context_imagery') fact = ' · 10 m source';
    if (item.detail) fact += ` · ${item.detail}`;
    rows.push(
      `<li class="ld-row">`
      + `<i class="ld-dot" data-status="${item.status}" data-sim="${item.simulated}"></i>`
      + `<span class="ld-name">${item.source_label}</span>`
      + `<span class="ld-age">${providerAgeLabel(item)}${fact}${suffix}</span>`
      + `</li>`,
    );
    if (item.attribution) attributions.add(item.attribution);
  }

  list.innerHTML = rows.join('');
  const footer = [...attributions].join(' · ');
  $('#ld-attrib').textContent = providers.offline
    ? `OFFLINE — cached data${footer ? ` · ${footer}` : ''}`
    : footer;
}

/* ---------------- weather source line ---------------- */
function renderWeatherNote() {
  const w = state.f && state.f.weather;
  const item = state.f && state.f.providers && state.f.providers.items.weather;
  const flag = $('#w-flag');
  const note = $('#w-note');
  if (!note) return;

  const simulated = item ? item.simulated : Boolean(w && w.simulated);
  if (flag) flag.hidden = !simulated;

  const mins = item && item.age_s != null ? Math.round(item.age_s / 60) : null;
  let line = '';
  if (simulated) {
    line = 'sample data — not live';
  } else if (item && (item.reason === 'adm4_unresolved' || item.fallback_from === 'bmkg')) {
    line = 'BMKG code unresolved for this location — using Open-Meteo';
  } else if (w && w.source === 'bmkg' && w.forecast_hours != null) {
    line = `BMKG · forecast ${w.forecast_hours} h ahead`;
  } else if (item && item.status === 'offline') {
    line = `${item.source_label} · offline — cached reading`;
  } else if (item && item.status === 'stale' && mins != null) {
    line = `${item.source_label} · wind data ${mins} min old`;
  } else if (item && mins != null) {
    line = `${item.source_label} · observed ${mins} min ago`;
  }

  note.textContent = line;
  note.className = 'small w-note'
    + (item && item.status === 'stale' ? ' warn' : '')
    + (simulated ? ' muted' : '');
}

/* ---------------- regional fires inset ---------------- */
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

const compassOf = (deg) => COMPASS[Math.round((deg || 0) / 22.5) % 16];

function distanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371.0088;
  const p1 = rad(lat1), p2 = rad(lat2);
  const dp = p2 - p1, dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, a)));
}

function bearingOf(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2);
  const dl = rad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function focusPoint(lon, lat) {
  const height = (state.center && state.center.height) || 0;
  const target = C.Cartesian3.fromDegrees(lon, lat, height);
  state.viewer.camera.lookAt(target, new C.HeadingPitchRange(
    rad(CONTEXT_CAMERA.heading), rad(CONTEXT_CAMERA.pitch), CONTEXT_CAMERA.range));
  state.viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
}

function renderFiresInset() {
  const inset = $('#fires-inset');
  if (!inset) return;
  const item = state.f && state.f.providers && state.f.providers.items.regional_fires;
  inset.hidden = !(state.mode === 'context' && item);
  if (inset.hidden) return;

  const fires = state.f.regional_fires;
  const title = $('#fi-title');
  const count = $('#fi-count');
  const sub = $('#fi-sub');
  const rows = $('#fi-rows');
  title.textContent = `NASA FIRMS · NRT${item.simulated ? ' · SIMULASI' : ''}`;

  if (item.status === 'unconfigured') {
    count.textContent = '';
    sub.textContent = 'add MAP_KEY to enable';
    rows.innerHTML = '';
    return;
  }
  if (!fires) {
    count.textContent = '';
    sub.textContent = item.status === 'unavailable' ? 'fetching…' : 'no data yet';
    rows.innerHTML = '';
    return;
  }

  count.textContent = fires.count;
  if (!fires.count) {
    sub.textContent = `No detections in the last ${fires.window_days * 24} h`;
    rows.innerHTML = '';
    return;
  }

  const centre = state.center || { lon: 0, lat: 0 };
  const newest = fires.detections[0];
  const newestMin = newest
    ? Math.max(0, Math.round((Date.now() - new Date(newest.acq_at).getTime()) / 60000))
    : 0;
  sub.textContent = `nearest ${fires.nearest_km} km · `
    + `${compassOf(fires.nearest_bearing_deg)} · ${newestMin} min`;

  rows.innerHTML = fires.detections.slice(0, 5).map((d) => {
    const km = distanceKm(centre.lat, centre.lon, d.lat, d.lon).toFixed(1);
    const bearing = compassOf(bearingOf(centre.lat, centre.lon, d.lat, d.lon));
    const conf = Math.round((d.confidence || 0) * 100);
    return `<li data-lon="${d.lon}" data-lat="${d.lat}">`
      + `<span>${km} km ${bearing}</span>`
      + `<span>${conf}% · ${d.acq_at.slice(11, 16)}Z</span>`
      + `</li>`;
  }).join('');

  rows.querySelectorAll('li').forEach((li) => {
    li.addEventListener('click', () => {
      focusPoint(Number(li.dataset.lon), Number(li.dataset.lat));
    });
  });
}

function populateRail() {
  const f = state.f;
  const c = f.context;
  const lat = (c.south + c.north) / 2;
  const lon = (c.west + c.east) / 2;
  const day = fmtDay(f.mission.started_at);
  const areaHa = (f.mission.area_m2 / 10000).toFixed(2);
  const proc = `${Math.floor(f.mission.processing_s / 60)}m ${f.mission.processing_s % 60}s`;
  const severity = f.advisory.severity;

  $('#mission-id').textContent = f.mission.id;
  $('#incident-name').textContent = c.name || 'Brighton Beach';
  $('#incident-meta').textContent = [day, fmtCoord(lat, lon)].filter(Boolean).join(' · ');
  $('#mode').textContent = f.mission.mode;
  $('#ic-mode').textContent = f.mission.mode;
  $('#status-text').textContent = f.mission.status;
  $('#status').classList.toggle('working', f.mission.status !== 'DONE');
  $('#sync').textContent = `${f.weather.age_min}m`;

  $('#ic-area').textContent = `${areaHa} ha`;
  $('#ic-photos').textContent = f.mission.photos;
  $('#ic-gsd').textContent = `${f.mission.gsd_cm} cm`;
  $('#ic-time').textContent = proc;
  $('#ic-aligned').textContent = `${f.mission.aligned}/${f.mission.photos}`;
  $('#ic-sev').textContent = severity;
  $('#ic-sev').dataset.sev = severity.toUpperCase();

  $('#m-mode').textContent = f.mission.mode;
  $('#m-area').textContent = `${areaHa} ha`;
  $('#m-photos').textContent = f.mission.photos;
  $('#m-aligned').textContent = `${f.mission.aligned} · ${Math.round(f.mission.align_ratio * 100)}%`;
  $('#m-time').textContent = proc;
  $('#m-gsd').textContent = `${f.mission.gsd_cm} cm`;
  $('#m-window').textContent = fmtWindow(f.mission.started_at, f.mission.ended_at);
  $('#open-recon-area').textContent = `${areaHa} ha`;
  $('#rc-area').textContent = `${areaHa} ha`;
  $('#rc-gsd').textContent = `${f.mission.gsd_cm} cm`;
  $('#rc-aligned').textContent = `${f.mission.aligned}/${f.mission.photos}`;

  const sev = severity.toLowerCase();
  const box = $('#severity');
  box.className = `sev-${sev}`;
  $('.sev-value', box).textContent = severity;

  $('#a-summary').textContent = f.advisory.summary;
  $('#a-actions').innerHTML = f.advisory.actions.map((a) => `<li>${a}</li>`).join('');
  $('#a-audit').textContent = `${f.advisory.model} · seed ${f.advisory.seed} · sha ${f.advisory.prompt_sha} · draft=${f.advisory.draft} · simulated=${f.advisory.simulated}`;

  const w = f.weather;
  $('#w-speed').innerHTML = `${w.wind_speed_kmh} <span>km/h</span>`;
  $('#w-dir').textContent = `FROM ${w.wind_dir_deg}° · SW`;
  $('#wind-arrow').style.transform = `rotate(${w.wind_dir_deg}deg)`;
  $('#w-temp').textContent = `${w.temp_c} °C`;
  $('#w-rh').textContent = `${w.humidity_pct}%`;
  $('#w-age').textContent = w.age_min == null ? '—' : `${w.age_min} min`;
  $('#w-source').textContent = w.source_label || w.source;
  renderWeatherNote();
  $('#basemap-note').textContent = `${f.context.source}. ${f.context.attribution}`;
  $('#attrib').textContent = f.context.attribution;

  $('#stepper').innerHTML = f.mission.stages.map((s) => {
    const active = s === f.mission.stage;
    const done = !active;
    return `<div class="step ${active ? 'active' : done ? 'done' : ''}"><i class="dot"></i><span>${s}</span><span class="t">${active ? 'active' : done ? 'done' : ''}</span></div>`;
  }).join('');

  $('#events').innerHTML = f.prediction.key_events.map((e) =>
    `<li class="${e.tone}"><span class="t">${e.time}</span><span>${e.label}</span></li>`
  ).join('');
  renderLegend();
  renderMinimap();
}

function wireUI() {
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => {
    $$('#tabs button').forEach((x) => x.classList.toggle('active', x === b));
    $$('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${b.dataset.tab}`));
  }));

  $('#rail-toggle').addEventListener('click', () => {
    $('#app').classList.toggle('collapsed');
    $('#rail-toggle').textContent = $('#app').classList.contains('collapsed') ? '<' : '>';
  });

  $('#open-recon').addEventListener('click', openReconstruction);
  $('#open-recon-card').addEventListener('click', openReconstruction);
  $('#close-recon').addEventListener('click', closeReconstruction);

  $$('input[name="base"]').forEach((r) => r.addEventListener('change', () => {
    if (r.checked) showBase(r.value);
  }));
  $$('.presets button').forEach((b) => b.addEventListener('click', () => applyPreset(b.dataset.preset)));

  $('#minimap').addEventListener('click', () => {
    if (state.mode === 'reconstruction') { closeReconstruction(); return; }
    state.camera = { ...CONTEXT_CAMERA };
    state.is2D = false;
    $('#toggle-2d').textContent = '2D';
    $('#app').classList.remove('is-2d');
    applyCamera();
  });

  $$('input[data-layer]').forEach((cb) => cb.addEventListener('change', () => {
    setLayer(cb.dataset.layer, cb.checked);
    const range = $(`input[data-opacity="${cb.dataset.layer}"]`);
    if (range) range.disabled = !cb.checked;
  }));
  $$('input[data-opacity]').forEach((r) => r.addEventListener('input', () => {
    setOpacity(r.dataset.opacity, +r.value / 100);
    const cb = $(`input[data-layer="${r.dataset.opacity}"]`);
    if (cb && +r.value > 0 && !cb.checked) { cb.checked = true; setLayer(r.dataset.opacity, true); }
  }));

  $('#forecast').addEventListener('input', (e) => applyForecast(+e.target.value));
  $('#play').addEventListener('click', togglePlay);
  $('#zoom-in').addEventListener('click', () => { state.camera.range = clamp(state.camera.range * 0.8, 150, 1000); applyCamera(); checkZoomMode(); });
  $('#zoom-out').addEventListener('click', () => { state.camera.range = clamp(state.camera.range * 1.25, 150, 1000); applyCamera(); checkZoomMode(); });
  $('#reset').addEventListener('click', () => {
    state.camera = { ...(state.mode === 'context' ? CONTEXT_CAMERA : RECON_CAMERA) };
    state.is2D = false;
    $('#toggle-2d').textContent = '2D';
    $('#app').classList.remove('is-2d');
    applyCamera();
  });
  $('#toggle-2d').addEventListener('click', () => {
    state.is2D = !state.is2D;
    const base = state.mode === 'context' ? CONTEXT_CAMERA : RECON_CAMERA;
    state.camera.pitch = state.is2D ? -89 : base.pitch;
    $('#toggle-2d').textContent = state.is2D ? '3D' : '2D';
    $('#app').classList.toggle('is-2d', state.is2D);
    applyCamera();
  });
}

function wireTheme() {
  const root = document.documentElement;
  const trigger = $('#theme-trigger');
  const popover = $('#theme-popover');
  const options = $$('[data-theme-set]', popover);
  const isOpen = () => !popover.hidden;
  const setOpen = (open) => {
    popover.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
    if (open) {
      const checked = options.find((b) => b.getAttribute('aria-checked') === 'true') || options[0];
      checked.focus();
    }
  };
  const sync = () => {
    const dark = root.dataset.theme === 'obsidian';
    trigger.setAttribute('aria-label', `Theme: ${dark ? 'Obsidian' : 'Paper'}`);
    trigger.title = `Theme: ${dark ? 'Obsidian' : 'Paper'}`;
    options.forEach((b) => {
      b.setAttribute('aria-checked', String((b.dataset.themeSet === 'obsidian') === dark));
    });
  };
  sync();

  trigger.addEventListener('click', () => setOpen(!isOpen()));
  trigger.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); }
    if (e.key === 'Escape') setOpen(false);
  });

  options.forEach((b) => b.addEventListener('click', () => {
    const theme = b.dataset.themeSet;
    if (theme === 'obsidian') root.dataset.theme = 'obsidian';
    else delete root.dataset.theme;
    try { localStorage.setItem('pyroscan-theme', theme); } catch (e) {}
    sync();
    setOpen(false);
    trigger.focus();
    applySceneTheme();
    renderCharts();
    renderLegend();
  }));

  options.forEach((b, i) => b.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); trigger.focus(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = options[(i + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length];
      next.focus();
    }
  }));

  document.addEventListener('pointerdown', (e) => {
    if (isOpen() && e.target instanceof Element && !e.target.closest('#theme-menu')) setOpen(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen()) { setOpen(false); trigger.focus(); }
  });
}

function applyAllLayers() {
  const checked = $('input[name="base"]:checked');
  showBase((checked && checked.value) || 'elevation');
  $$('input[data-layer]').forEach((cb) => {
    setLayer(cb.dataset.layer, cb.checked);
    const r = $(`input[data-opacity="${cb.dataset.layer}"]`);
    if (r) { r.disabled = !cb.checked; setOpacity(r.dataset.opacity, +r.value / 100); }
  });
  renderLegend();
}

function showBase(name) {
  state.base = name;
  const ctx = state.mode === 'context';
  for (const [k, p] of Object.entries(state.bases)) p.show = !ctx && k === name;
  $$('input[name="base"]').forEach((r) => {
    r.checked = r.value === name;
    r.closest('.base-opt').classList.toggle('active', r.value === name);
  });
  renderLegend();
}

function setLayer(name, on) {
  const ctx = state.mode === 'context';
  if (state.prims[name]) state.prims[name].show = !ctx && on;
  if (state.groups[name]) state.groups[name].show = !ctx && on;
  if (ctx) {
    if (state.groups.hotspots) state.groups.hotspots.show = true;
    if (state.groups.footprint) state.groups.footprint.show = true;
  }
  renderLegend();
}

function setOpacity(name, a) {
  if (name === 'heat' && state.mats.heat) {
    state.mats.heat.uniforms.color = new C.Color(1, 1, 1, Math.min(a, 0.95));
    return;
  }
  if (name === 'wind') {
    for (const { ent, base } of state.windEntities) {
      ent.polyline.material = new C.ColorMaterialProperty(base.withAlpha(0.65 * a));
    }
  }
  if (name === 'prediction') {
    for (const p of state.pred) {
      const color = (p.step === 0 ? RED : p.step === 30 ? FLAME : AMBER).withAlpha(p.baseAlpha * a);
      p.ent.polygon.material = new C.ColorMaterialProperty(color);
    }
  }
}

function applyPreset(name) {
  const map = {
    terrain: { base: 'terrain', on: ['hotspots', 'flight'] },
    fire: { base: 'terrain', on: ['heat', 'prediction', 'hotspots', 'flight'] },
    forecast: { base: 'terrain', on: ['prediction', 'wind', 'hotspots', 'flight'] },
    burn: { base: 'severity', on: ['hotspots', 'flight'] },
  };
  const p = map[name];
  if (!p) return;
  showBase(p.base);
  $$('input[data-layer]').forEach((cb) => {
    const on = p.on.includes(cb.dataset.layer);
    cb.checked = on;
    setLayer(cb.dataset.layer, on);
    const r = $(`input[data-opacity="${cb.dataset.layer}"]`);
    if (r) { r.disabled = !on; if (on) setOpacity(r.dataset.opacity, +r.value / 100); }
  });
  $$('.presets button').forEach((b) => b.classList.toggle('active', b.dataset.preset === name));
  renderLegend();
}

function renderLegend() {
  const el = $('#legend-body');
  if (!el) return;
  if (state.mode === 'context') {
    const area = (state.f.mission.area_m2 / 10000).toFixed(2);
    el.innerHTML = `
      <div class="legend-group"><div class="legend-label">Reconstruction</div>
        <div class="legend-inline"><i style="background:var(--amber)"></i>ODM patch · ${area} ha</div>
        <div class="legend-class">Click outline or hotspot to open</div>
      </div>
      <div class="legend-group"><div class="legend-label">Hotspots</div>
        <div class="legend-class"><i style="background:var(--red);border-radius:50%"></i>Detection · confidence</div>
        <div class="legend-class">Hotspot data SIMULASI</div>
      </div>
      <div class="legend-group"><div class="legend-label">Context</div>
        <div class="legend-class">Cached satellite · not reconstruction</div>
      </div>`;
    return;
  }
  let html = '';
  if (state.base === 'terrain') {
    html += `<div class="legend-group"><div class="legend-label">Terrain</div>
      <div class="legend-ramp" style="background:linear-gradient(90deg,#2e4a3a,#68704a,#a89660,#d8c9a0)"></div>
      <div class="legend-ends"><span>153 m</span><span>174 m</span></div>
      <div class="legend-class">Shaded ortho · contours 2 m / 10 m</div></div>`;
  } else if (state.base === 'elevation') {
    html += `<div class="legend-group"><div class="legend-label">Elevation</div>
      <div class="legend-ramp" style="background:linear-gradient(90deg,#2e4a3a,#68704a,#a89660,#d8c9a0)"></div>
      <div class="legend-ends"><span>153 m</span><span>174 m</span></div>
      <div class="legend-class">Contours 2 m · index 10 m</div></div>`;
  } else if (state.base === 'ortho') {
    html += `<div class="legend-group"><div class="legend-label">Base</div>
      <div class="legend-class">Shaded orthophoto · hillshade NW</div></div>`;
  } else {
    html += `<div class="legend-group"><div class="legend-label">Burn severity</div>` +
      [['Severe', '#5c2b28'], ['High', '#c2452f'], ['Moderate', '#e08a3c'], ['Low', '#e5c15a'], ['Unburned', '#6fbf8f']]
        .map(([l, c]) => `<div class="legend-class"><i style="background:${c}"></i>${l}</div>`).join('') +
      `</div>`;
  }
  const on = (n) => { const cb = $(`input[data-layer="${n}"]`); return cb && cb.checked; };
  if (on('heat')) {
    html += `<div class="legend-group"><div class="legend-label">Detection density</div>
      <div class="legend-ramp" style="background:linear-gradient(90deg,#ffdc78,#ffb450,#ff7832,#e5443b,#fff0d2)"></div>
      <div class="legend-ends"><span>0%</span><span>100%</span></div></div>`;
  }
  if (on('wind')) {
    const w = state.f.weather;
    html += `<div class="legend-group"><div class="legend-label">Wind</div>
      <div class="legend-class">${w.wind_speed_kmh} km/h · TO ${((w.wind_dir_deg + 180) % 360).toFixed(0)}°</div></div>`;
  }
  if (on('prediction')) {
    html += `<div class="legend-group"><div class="legend-label">Prediction</div>
      <div class="legend-inline"><i style="background:var(--pred-now)"></i>Now</div>
      <div class="legend-inline"><i style="background:var(--pred-30)"></i>+30 min</div>
      <div class="legend-inline"><i style="background:var(--pred-60)"></i>+60 min</div></div>`;
  }
  el.innerHTML = html;
}

function renderMinimap() {
  const h = state.h;
  const padLon = (h.east - h.west) * 1.2;
  const padLat = (h.north - h.south) * 1.2;
  const c = {
    west: h.west - padLon, east: h.east + padLon,
    south: h.south - padLat, north: h.north + padLat,
  };
  const box = $('#minimap-box');
  if (!box) return;
  const left = (h.west - c.west) / (c.east - c.west);
  const width = (h.east - h.west) / (c.east - c.west);
  const top = (c.north - h.north) / (c.north - c.south);
  const height = (h.north - h.south) / (c.north - c.south);
  box.style.left = `${clamp(left, 0, 1) * 100}%`;
  box.style.top = `${clamp(top, 0, 1) * 100}%`;
  box.style.width = `${clamp(width, 0, 1) * 100}%`;
  box.style.height = `${clamp(height, 0, 1) * 100}%`;
}

function applyForecast(t) {
  state.forecast = t;
  $('#tl-now').textContent = `+${t} min`;
  $('#forecast').value = t;
  for (const p of state.pred) {
    const show = p.step === 0 || (p.step === 30 && t >= 15) || (p.step === 60 && t >= 45);
    p.ent.show = show;
    if (p.front) p.front.show = show;
  }
  for (const l of state.predLabels) {
    l.ent.show = l.step === 0 || (l.step === 30 && t >= 15) || (l.step === 60 && t >= 45);
  }
  renderCharts();
}

function togglePlay() {
  state.playing = !state.playing;
  $('#play').textContent = state.playing ? '||' : '>';
  if (!state.playing) return;
  let start = performance.now();
  const from = state.forecast >= 60 ? 0 : state.forecast;
  const tick = (now) => {
    if (!state.playing) return;
    const p = clamp(from + ((now - start) / 12000) * 60, 0, 60);
    applyForecast(Math.round(p));
    if (p >= 60) { state.playing = false; $('#play').textContent = '>'; return; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---------------- charts ---------------- */
function interp(data, t) {
  const p = (t / 60) * (data.length - 1);
  const i = Math.floor(p), f = p - i;
  return data[i] * (1 - f) + data[Math.min(i + 1, data.length - 1)] * f;
}

function drawChart(svg, data, t, color) {
  const w = 240, h = 56, pad = 4;
  const min = Math.min(...data), max = Math.max(...data);
  const axis = cssVar('--chart-axis', '#d3c9b6');
  const cursor = cssVar('--chart-cursor', '#575248');
  const x = (i) => pad + (i / (data.length - 1)) * (w - pad * 2);
  const y = (v) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
  const pts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const cx = x((t / 60) * (data.length - 1));
  svg.innerHTML = `
    <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="${axis}" stroke-width="1"/>
    <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}" stroke="${axis}" stroke-width="1"/>
    <polygon points="${pad},${h - pad} ${pts} ${w - pad},${h - pad}" fill="${color}" fill-opacity="0.09"/>
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/>
    <line x1="${cx}" y1="${pad}" x2="${cx}" y2="${h - pad}" stroke="${cursor}" stroke-width="1" stroke-dasharray="2 2" stroke-opacity=".45"/>
    <circle cx="${cx}" cy="${y(interp(data, t))}" r="2.2" fill="${color}"/>`;
}

function drawElevation(svg, data) {
  if (!svg || !data || !data.length) return;
  const w = 240, h = 56, pad = 4;
  const min = Math.min(...data), max = Math.max(...data);
  const axis = cssVar('--chart-axis', '#d3c9b6');
  const color = cssVar('--chart-elev', '#2f648c');
  const x = (i) => pad + (i / (data.length - 1)) * (w - pad * 2);
  const y = (v) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
  const pts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  svg.innerHTML = `
    <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="${axis}" stroke-width="1"/>
    <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}" stroke="${axis}" stroke-width="1"/>
    <polygon points="${pad},${h - pad} ${pts} ${w - pad},${h - pad}" fill="${color}" fill-opacity="0.10"/>
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/>`;
}

function renderCharts() {
  const t = state.forecast;
  const p = state.f.prediction;
  drawChart($('#chart-area'), p.chart_area, t, cssVar('--chart-area', '#a05a10'));
  drawChart($('#chart-rate'), p.chart_rate, t, cssVar('--chart-rate', '#b0401c'));
  const elev = state.elevProfile || (state.elevProfile = elevationProfile());
  drawElevation($('#chart-elev'), elev.data);
  $('#ch-elev-val').textContent = `${Math.round(elev.min)}–${Math.round(elev.max)} m`;
  $('#ch-elev-label').textContent = `Elevation · ${elev.label}`;
  $('#ch-elev-label').title = `Steepest transect through the mission center (${elev.bearing}°)`;
  $('#ch-area-val').textContent = `${interp(p.chart_area, t).toFixed(2)} ha`;
  $('#ch-rate-val').textContent = `${Math.round(interp(p.chart_rate, t))} m/min`;
}

/* ---------------- fps ---------------- */
function startFps() {
  const s = [];
  let last = performance.now();
  state.viewer.scene.postRender.addEventListener(() => {
    const now = performance.now();
    s.push(now - last); last = now;
    if (s.length > 240) s.shift();
  });
  setInterval(() => {
    if (s.length < 20) return;
    const sorted = [...s].sort((a, b) => a - b);
    const p95 = sorted[Math.floor(sorted.length * 0.95)];
    $('#fps').textContent = `${p95.toFixed(0)} ms`;
  }, 1000);
}







