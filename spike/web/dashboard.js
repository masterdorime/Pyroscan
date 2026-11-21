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
  indonesia: { scene: 'indonesia', camera: { heading: 0, pitch: -60, range: 4500000 },
               limits: { min: 800000, max: 6000000 } },
  drone: { scene: 'reconstruction', camera: { heading: 45, pitch: -30, range: 220 },
           limits: { min: 150, max: 400 } },
  terrain: { scene: 'context', camera: { heading: 45, pitch: -30, range: 1200 },
             limits: { min: 400, max: 8000 } },
  regional: { scene: 'context', camera: { heading: 45, pitch: -35, range: 25000 },
              limits: { min: 8000, max: 80000 } },
};
const MODE_ORDER = ['indonesia', 'drone', 'terrain', 'regional'];
const INDONESIA = { lat: -2.0, lon: 118.0 };

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
    indonesia: true,
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
  if (mode === 'indonesia') return 'COVERAGE · INDONESIA';
  if (mode === 'drone') {
    const gsd = state.f && state.f.mission && state.f.mission.gsd_cm;
    return `${gsd} cm · patch`;
  }
  if (mode === 'regional') {
    const wide = state.contextImageryWide;
    if (wide) {
      const km = Math.round(wide.window_km || 60);
      const res = wide.resolution_m ? `${wide.resolution_m} m image` : 'mosaic';
      const n = wide.scene_count || 1;
      return `${km} km · ${res} · ${n} tile${n > 1 ? 's' : ''} · ${mins(items.context_imagery_wide)}`;
    }
    const ring = state.f && state.f.providers && state.f.providers.ring_km;
    return `${Math.round(ring || 15)} km ring · ${mins(items.weather)}`;
  }
  const dem = items.context_dem;
  const width = detailWidthKm();
  const km = width ? `${width} km image` : 'mosaic';
  const cell = dem && dem.detail ? `30 m · ${dem.detail}` : '30 m';
  return `${cell} · ${km} · ${mins(dem)}`;
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
  state.rangeLimits = modeLimits(mode);
  setMode(cfg.scene);
  const to = modeCamera(mode);
  if (animate) flyCamera(to); else { state.camera = to; applyCamera(); }
  syncTabs();
  writeModeHash(mode);
  // The globe is fill-rate bound; measure once per entry and pick a scale.
  if (state.viewer) {
    if (mode === 'indonesia') {
      state.viewer.resolutionScale = 1;
      tuneToken += 1;
      clearTimeout(state.tuneTimer);
      state.tuneTimer = setTimeout(tuneGlobeQuality, 3000);
    } else {
      tuneToken += 1;
      clearTimeout(state.tuneTimer);
      if (state.viewer.resolutionScale !== 1) state.viewer.resolutionScale = 1;
    }
  }
}

let tuneToken = 0;

function renderCadence(n = 24) {
  // rAF can fire in bursts headless; postRender is the real rendered-frame
  // cadence and matches the HUD's p95 metric.
  return new Promise((resolve) => {
    const scene = state.viewer.scene;
    const samples = [];
    let last = 0;
    const listener = () => {
      const now = performance.now();
      if (last) samples.push(now - last);
      last = now;
      if (samples.length >= n) {
        scene.postRender.removeEventListener(listener);
        samples.sort((a, b) => a - b);
        resolve(samples[Math.floor(samples.length / 2)]);
      }
    };
    scene.postRender.addEventListener(listener);
  });
}

/**
 * Pick a globe resolution that holds ~30 fps. Median frame time, two passes at
 * most, and never below 0.6 — the globe is a poster, not a survey view.
 */
async function tuneGlobeQuality() {
  if (!state.viewer || state.viewMode !== 'indonesia') return;
  const token = ++tuneToken;
  const setScale = (s) => {
    if (token === tuneToken && state.viewMode === 'indonesia') {
      state.viewer.resolutionScale = s;
    }
  };
  await new Promise((r) => setTimeout(r, 250));
  let ms = await renderCadence();
  if (token !== tuneToken || state.viewMode !== 'indonesia') return;
  if (ms > 40) {
    setScale(0.75);
    await new Promise((r) => setTimeout(r, 400));
    ms = await renderCadence();
    if (token !== tuneToken || state.viewMode !== 'indonesia') return;
    if (ms > 40) setScale(0.6);
  } else if (ms > 30) {
    setScale(0.85);
  }
}

/** Regional needs its wide surface before it can promise 60 km. */
function modeCamera(mode) {
  if (mode === 'regional' && !state.prims.ringTerrainWide) {
    return { heading: 45, pitch: -45, range: 3000 };
  }
  return { ...MODES[mode].camera };
}

function modeLimits(mode) {
  if (mode === 'regional' && !state.prims.ringTerrainWide) {
    return { min: 2000, max: 40000 };
  }
  return { ...MODES[mode].limits };
}

function initModes() {
  const avail = modeAvailability();
  let mode = readModeFromHash();
  if (!mode || !avail[mode]) mode = 'indonesia';
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
  viewMode: 'terrain', rangeLimits: { min: 400, max: 5000 },
  // Indonesia globe skin: 'texture' (NASA Blue Marble) or 'flat' (one colour).
  globeSkin: 'texture', globeSkinFallback: false, globeLayerState: null,
  selectedIso: null, selectedFeature: null,
  fires: null, firesReason: null, fireDs: null, fireCount: 0,
  plateLayer: null, plateMeta: null, detailLayer: null, detailMeta: null,
  plateToken: 0, selectedDetection: null, plateLoading: null,
  site: null, siteTerrain: null, siteImagery: null, siteData: null,
  siteDetection: null,
  siteExaggeration: 2.2, siteRelief: 2.2,
  siteSpreadDs: null, spreadFrames: [], spreadEntities: [], spreadHead: null,
  spreadIdx: 0, spreadTimer: 0, spreadPlaying: false,
};

const AMBER = C.Color.fromCssColorString('#e5a954');
const FLAME = C.Color.fromCssColorString('#ff6b35');
const RED = C.Color.fromCssColorString('#e5443b');
const SILVER = C.Color.fromCssColorString('#9494a0');
const PROVINCE_LINE = C.Color.fromCssColorString('#a8cbb8').withAlpha(0.8);
const PROVINCE_HOVER = C.Color.fromCssColorString('#ffe3b0').withAlpha(1);
const PROVINCE_DIM = C.Color.fromCssColorString('#a8cbb8').withAlpha(0.22);
const PROVINCE_SELECTED = C.Color.fromCssColorString('#ffcf7a').withAlpha(1);

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
  state.globeSkin = storedGlobeSkin();
  loadContextImagery(live);
  loadContextDemMeta(live);
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
  loadProvinces();
  loadFires();
  buildStudioFloor();
  buildLandscape();
  loadContextDem(live);
  loadWideContext(live);
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
    // Cesium's `globe` option takes a Globe or false, not true; leave it
    // undefined so the default globe is created, then hide it per mode.
    skyAtmosphere: new C.SkyAtmosphere(),
    creditContainer: document.createElement('div'),
    baseLayerPicker: false, geocoder: false, homeButton: false,
    sceneModePicker: false, navigationHelpButton: false,
    animation: false, timeline: false, infoBox: false,
    selectionIndicator: false, fullscreenButton: false, vrButton: false,
    skyBox: false, scene3DOnly: true,
    // MSAA 4 is the dominant cost on the globe (fill-rate bound); edges are
    // handled by FXAA instead.
    msaaSamples: 1,
  });
  viewer.scene.backgroundColor = C.Color.fromCssColorString('#dfe8e3');
  viewer.scene.fog.enabled = false;
  viewer.scene.screenSpaceCameraController.enableInputs = false;
  // The globe is only shown in Indonesia mode; the mission modes keep the
  // flat scene exactly as before.
  viewer.scene.globe.show = false;
  viewer.scene.globe.baseColor = C.Color.fromCssColorString('#0a1418');
  viewer.scene.globe.enableLighting = false;
  if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = false;
  state.worldLayer = viewer.imageryLayers.addImageryProvider(
    new C.SingleTileImageryProvider({
      url: 'data/world_blue_marble.jpg',
      rectangle: C.Rectangle.MAX_VALUE,
    }));
  // The 4096x1700 archipelago crop, shown only when zoomed in (see
  // syncGlobeLayers). It is data at the zoom level, not another post-process.
  state.indonesiaLayer = viewer.imageryLayers.addImageryProvider(
    new C.SingleTileImageryProvider({
      url: 'data/indonesia_blue_marble.jpg',
      rectangle: C.Rectangle.fromDegrees(94, -12, 142, 8),
    }));
  state.indonesiaLayer.show = false;
  state.viewer = viewer;
  state.canvas = viewer.scene.canvas;
  state.canvas.style.touchAction = 'none';
  wireBaseImageFallback();
  // Cesium's controller rotates in Indonesia mode, so the compass needs the
  // live camera heading rather than the custom camera state.
  viewer.scene.postRender.addEventListener(() => {
    if (state.viewMode !== 'indonesia') return;
    const compass = document.getElementById('compass');
    if (compass) {
      const heading = C.Math.toDegrees(viewer.camera.heading);
      compass.style.setProperty('--heading', `${-heading}deg`);
    }
    // Toggle imagery show only when the boolean changes: postRender is every
    // frame and imageryLayers.show is not free.
    syncGlobeLayers();
  });
}

/* ---------------- globe skin + regional LOD ---------------- */
const SKIN_KEY = 'pyroscan-globe-skin';
const MAP_SKINS = ['relief', 'satellite', 'atlas', 'flat'];
const FLAT_BASE = '#14211c';
const TEXTURE_BASE = '#0a1418';
const CROP_MAX_HEIGHT = 2500000;

function storedGlobeSkin() {
  try {
    const value = localStorage.getItem(SKIN_KEY);
    if (value === 'texture') return 'relief'; // migrate the old toggle
    return MAP_SKINS.includes(value) ? value : 'relief';
  } catch (e) {
    return 'relief';
  }
}

/** Flat hides every imagery layer; borders + atmosphere stay. */
function applyGlobeSkin() {
  if (!state.viewer) return;
  const texture = state.globeSkin !== 'flat';
  state.viewer.scene.globe.baseColor = C.Color.fromCssColorString(
    texture ? TEXTURE_BASE : FLAT_BASE);
  // Force the next sync to write both layers instead of short-circuiting.
  state.globeLayerState = null;
  if (state.viewMode === 'indonesia') syncGlobeLayers();
  else hideGlobeLayers();
  syncGlobeSkinUI();
  const attrib = $('#attrib');
  if (attrib) attrib.textContent = contextAttribution();
  renderLegend();
}

function hideGlobeLayers() {
  if (state.worldLayer) state.worldLayer.show = false;
  if (state.indonesiaLayer) state.indonesiaLayer.show = false;
  state.globeLayerState = { world: false, crop: false };
}

/**
 * Texture skin: world base everywhere, the sharper crop below 2,500 km.
 * The desired state is cached so a frame with no change writes nothing — and
 * so `perf-globe.mjs` can isolate a layer without the loop reverting it.
 */
function syncGlobeLayers() {
  if (!state.viewer || state.viewMode !== 'indonesia') return;
  const texture = state.globeSkin !== 'flat';
  const height = C.Cartesian3.magnitude(state.viewer.camera.positionWC) - 6378137;
  const next = { world: texture, crop: texture && height < CROP_MAX_HEIGHT };
  const prev = state.globeLayerState;
  if (prev && prev.world === next.world && prev.crop === next.crop) return;
  state.worldLayer.show = next.world;
  if (state.indonesiaLayer) state.indonesiaLayer.show = next.crop;
  state.globeLayerState = next;
  // The legend names whichever base is on screen; only on a threshold cross,
  // and outside the Cesium render loop so a DOM error cannot stop rendering.
  if (state.mode === 'indonesia') requestAnimationFrame(renderLegend);
}

function setGlobeSkin(skin, { persist = true } = {}) {
  const next = MAP_SKINS.includes(skin) ? skin : 'relief';
  state.globeSkin = next;
  if (persist) {
    state.globeSkinFallback = false;
    try { localStorage.setItem(SKIN_KEY, next); } catch (e) { /* private mode */ }
  }
  if (state.map2d) state.map2d.setSkin(next);
  applyGlobeSkin();
  renderProvincePanel();
}

function syncGlobeSkinUI() {
  $$('#globe-skin button').forEach((b) => {
    const on = b.dataset.skin === state.globeSkin;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

/** If the bundled base cannot load, the flat skin is the honest surface. */
function wireBaseImageFallback() {
  const fellBack = () => {
    if (state.map2d) return; // the 2D map owns its own skin fallback
    if (state.globeSkin === 'flat') return;
    state.globeSkinFallback = true;
    // Do not persist: the next load retries the texture.
    setGlobeSkin('flat', { persist: false });
  };
  const provider = state.worldLayer && state.worldLayer.imageryProvider;
  if (provider && provider.errorEvent && provider.errorEvent.addEventListener) {
    provider.errorEvent.addEventListener(fellBack);
  }
  const probe = new Image();
  probe.onerror = fellBack;
  probe.src = 'data/world_blue_marble.jpg';
}

function loadProvinces() {
  fetch('api/v1/provinces.geojson', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((fc) => {
      if (!fc || !Array.isArray(fc.features)) throw new Error('no provinces');
      const ds = new C.CustomDataSource('provinces');
      state.viewer.dataSources.add(ds);
      state.provinceFeatures = fc.features;
      state.provinceEntities = {};
      for (const f of fc.features) {
        const geom = f.geometry;
        const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
        const bucket = state.provinceEntities[f.properties.iso] || [];
        for (const poly of polys) {
          for (const ring of poly) {
            const flat = [];
            for (const [lon, lat] of ring) flat.push(lon, lat);
            bucket.push(ds.entities.add({
              properties: { iso: f.properties.iso, name: f.properties.name },
              polyline: {
                positions: C.Cartesian3.fromDegreesArray(flat),
                width: 1,
                material: new C.ColorMaterialProperty(PROVINCE_LINE),
                clampToGround: true,
                arcType: C.ArcType.GEODESIC,
              },
            }));
          }
        }
        state.provinceEntities[f.properties.iso] = bucket;
      }
      state.provinces = ds;
      ds.show = state.mode === 'indonesia';
      initMap2d(fc.features);
    })
    .catch(() => {
      // The globe and the coverage label still work without boundaries.
      state.provincesFailed = true;
    });
}

function initMap2d(features) {
  if (state.map2d) return;
  const canvas = $('#map2d');
  if (!window.PyroMap2D || !canvas) {
    console.error('map2d unavailable; keeping the Cesium fallback');
    const skin = $('#globe-skin');
    if (skin) skin.style.display = 'none';
    return;
  }
  try {
    state.map2d = window.PyroMap2D.create({
      canvas,
      features,
      skin: state.globeSkin,
      onSelect: (f) => {
        hideProvinceTip();
        if (f) selectProvince(f);
        else if (state.selectedIso) selectProvince(null, { resetCamera: true });
      },
      onDotHover: (dot, pt) => {
        if (!dot || !pt) { hideProvinceTip(); return; }
        const rect = canvas.getBoundingClientRect();
        const when = String(dot.acq_at || '').slice(11, 16);
        showProvinceTip(
          `${dot.sensor || 'FIRMS'} · ${dot.frp ?? '—'} MW · ${when}Z`,
          rect.left + pt.x, rect.top + pt.y - 16, null);
      },
      onDot: (dot, f) => {
        if (!f) return;
        selectProvince(f);
        state.selectedDetection = dot;
        renderProvincePanel();
      },
    });
  } catch (e) {
    console.error('map2d init failed; keeping the Cesium fallback', e);
    state.map2d = null;
    $('#app').classList.remove('map2d-ready');
    const skin = $('#globe-skin');
    if (skin) skin.style.display = 'none';
    return;
  }
  state.map2d.setFires((state.fires && state.fires.dots) || []);
  state.map2d.select(state.selectedIso);
  state.map2d.setSkin(state.globeSkin);
  state.map2d.resize();
  $('#app').classList.add('map2d-ready');
}

function ringContains(ring, lon, lat) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat)
        && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function provinceAt(lon, lat) {
  for (const f of state.provinceFeatures || []) {
    const [w, s, e, n] = f.properties.bbox;
    if (lon < w || lon > e || lat < s || lat > n) continue;
    const geom = f.geometry;
    const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
    if (polys.some((poly) => ringContains(poly[0], lon, lat))) return f;
  }
  return null;
}

/**
 * Selection wins over hover; with a selection on screen the other 37 dim so
 * the chosen province reads without a fill that would fake coverage.
 */
function provinceStyle(iso) {
  if (iso && iso === state.selectedIso) {
    return { color: PROVINCE_SELECTED, width: 2 };
  }
  if (iso && iso === state.hoverIso) {
    return { color: PROVINCE_HOVER, width: 2 };
  }
  if (state.selectedIso) return { color: PROVINCE_DIM, width: 1 };
  return { color: PROVINCE_LINE, width: 1 };
}

function restyleProvince(iso) {
  const bucket = iso && state.provinceEntities ? state.provinceEntities[iso] : null;
  if (!bucket) return;
  const s = provinceStyle(iso);
  for (const ent of bucket) {
    ent.polyline.material = new C.ColorMaterialProperty(s.color);
    ent.polyline.width = s.width;
  }
}

function applyProvinceStyle() {
  for (const iso of Object.keys(state.provinceEntities || {})) restyleProvince(iso);
}

function setHoverProvince(f) {
  const iso = f ? f.properties.iso : null;
  if (state.hoverIso === iso) return;
  restyleProvince(state.hoverIso);
  state.hoverIso = iso;
  restyleProvince(iso);
  state.canvas.style.cursor = iso ? 'pointer' : '';
}

function showProvinceTip(name, x, y, count) {
  const el = $('#province-tip');
  if (!el) return;
  el.textContent = count ? `${name} · ${count}` : name;
  el.hidden = false;
  const left = Math.min(x + 14, window.innerWidth - 220);
  const top = Math.min(y + 14, window.innerHeight - 40);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function hideProvinceTip() {
  const el = $('#province-tip');
  if (el) el.hidden = true;
}

/* ---------------- country fires ---------------- */
function ageLabel(seconds) {
  if (seconds == null) return '—';
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

/* ---------------- province plate ---------------- */
function plateRect(meta) {
  const [w, s, e, n] = meta.rectangle;
  return C.Rectangle.fromDegrees(w, s, e, n);
}

function removePlateLayer(kind) {
  const key = kind === 'detail' ? 'detailLayer' : 'plateLayer';
  if (state[key]) {
    state.viewer.imageryLayers.remove(state[key], true);
    state[key] = null;
  }
  if (kind === 'detail') state.detailMeta = null;
  else state.plateMeta = null;
}

function clearPlate() {
  state.plateLoading = null;
  if (state.map2d) state.map2d.clearPlate();
  removePlateLayer('preview');
  removePlateLayer('detail');
  const chip = $('#pp-imagery');
  if (chip) chip.textContent = 'Imagery · next slice';
  const btn = $('#pp-detail');
  if (btn) { btn.disabled = true; btn.textContent = '59 m detail'; }
  const prog = $('#pp-progress');
  if (prog) prog.hidden = true;
}

function plateLabel(meta) {
  const range = meta.date_range && meta.date_range.length
    ? `${meta.date_range[0]}–${meta.date_range[meta.date_range.length - 1]}` : '—';
  const pct = Math.round((meta.coverage || 0) * 100);
  return `${meta.scenes} scenes · ${range} · ${pct} % · ${meta.resolution_m} m`;
}

function loadProvinceImagery(f, tier = 'preview', { fly = false } = {}) {
  if (!f) return;
  const iso = f.properties.iso;
  const token = ++state.plateToken;
  state.plateLoading = tier;
  const chip = $('#pp-imagery');
  if (chip) chip.textContent = tier === 'preview'
    ? 'Building preview…' : 'Building 59 m detail…';
  renderProvincePanel();
  fetch(`api/v1/provinces/${iso}/imagery?tier=${tier}`, { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`http ${r.status}`))))
    .then((data) => {
      if (token !== state.plateToken || state.selectedIso !== iso) return;
      state.plateLoading = null;
      if (!data.available) {
        if (chip) chip.textContent = `Imagery unavailable (${data.reason})`;
        renderProvincePanel();
        return;
      }
      const isDetail = tier === 'detail';
      if (state.map2d) {
        state.map2d.setPlate(data.url, data, isDetail);
        if (isDetail) state.detailMeta = data;
        else state.plateMeta = data;
      } else {
        const kind = isDetail ? 'detailLayer' : 'plateLayer';
        removePlateLayer(tier);
        const layer = state.viewer.imageryLayers.addImageryProvider(
          new C.SingleTileImageryProvider({
            url: data.url, rectangle: plateRect(data),
          }));
        state[kind] = layer;
        if (isDetail) state.detailMeta = data;
      }
      if (isDetail) {
        if (chip) chip.textContent = `59 m detail · ${Math.round(
          (data.rectangle[2] - data.rectangle[0]) * 111)} km · ${Math.round(
          (data.coverage || 0) * 100)} %`;
        const btn = $('#pp-detail');
        if (btn) { btn.disabled = true; btn.textContent = '59 m loaded'; }
        if (fly) {
          if (state.map2d) state.map2d.focusRect(data.rectangle);
          else {
            state.viewer.camera.flyTo({
              destination: plateRect(data), duration: 1.2,
            });
          }
        }
      } else {
        if (chip) chip.textContent = plateLabel(data);
        const btn = $('#pp-detail');
        if (btn) { btn.disabled = false; btn.textContent = '59 m detail'; }
      }
      renderProvincePanel();
      renderLegend();
    })
    .catch(() => {
      if (token !== state.plateToken) return;
      state.plateLoading = null;
      const chip = $('#pp-imagery');
      if (chip) chip.textContent = 'Imagery unavailable';
      renderProvincePanel();
    });
}

function fireRow(iso) {
  return state.fires && state.fires.provinces
    ? state.fires.provinces[iso] || null : null;
}

function loadFires() {
  fetch('api/v1/overview/fires?days=5', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`http ${r.status}`))))
    .then((data) => {
      state.fires = data;
      state.firesReason = data.available ? null : (data.reason || 'unavailable');
      renderFires();
      renderProvincePanel();
      renderLegend();
    })
    .catch(() => {
      state.fires = null;
      state.firesReason = 'unavailable';
      renderProvincePanel();
      renderLegend();
    });
}

function renderFires() {
  const dots = (state.fires && state.fires.dots) || [];
  state.fireCount = dots.length;
  if (state.map2d) state.map2d.setFires(dots);
}

/* ---------------- province selection ---------------- */
function renderProvincePanel() {
  const panel = $('#province-panel');
  if (!panel) return;
  const f = state.selectedFeature;
  if (!f || state.viewMode !== 'indonesia') { panel.hidden = true; return; }
  const { name, iso, area_km2 } = f.properties;
  $('#pp-name').textContent = name || '—';
  $('#pp-iso').textContent = iso || '—';
  $('#pp-area').textContent = area_km2
    ? `${new Intl.NumberFormat('en-GB').format(area_km2)} km²` : '—';

  const days = (state.fires && state.fires.window_days) || 5;
  const row = fireRow(iso);
  const count = $('#pp-count');
  const meta = $('#pp-meta');
  $('#pp-window').textContent = `detections · ${days} days`;
  if (!state.fires) {
    count.textContent = '—';
    meta.textContent = state.firesReason
      ? 'Detections unavailable' : 'FIRMS loading…';
  } else if (!state.fires.available) {
    count.textContent = '—';
    meta.textContent = `Detections unavailable (${state.fires.reason || 'no source'})`;
  } else if (!row || !row.count) {
    count.textContent = '0';
    meta.textContent = `No detections in the last ${days} days`;
  } else {
    count.textContent = String(row.count);
    const frp = row.max_frp != null ? `${row.max_frp} MW max FRP · ` : '';
    const newest = row.dots && row.dots[0] ? row.dots[0].acq_at : null;
    const age = newest ? Math.max(0, (Date.now() - Date.parse(newest)) / 1000) : null;
    meta.textContent = `${frp}newest ${ageLabel(age)}`;
  }
  const det = state.selectedDetection;
  const detect = $('#pp-detect');
  if (detect) {
    detect.hidden = !det;
    if (det) {
      const when = String(det.acq_at || '').replace('T', ' ').replace('Z', 'Z');
      detect.textContent = `${det.sensor || 'FIRMS'} · ${when} · `
        + `${det.frp != null ? `${det.frp} MW · ` : ''}`
        + `${Math.round((det.confidence || 0) * 100)} % · Drone: no survey at this detection`;
    }
  }
  const hiddenPlate = ['atlas', 'flat'].includes(state.globeSkin);
  const patchy = state.plateMeta && (state.plateMeta.coverage || 0) < 0.80;
  if (state.plateMeta) {
    const chip = $('#pp-imagery');
    if (chip && !chip.textContent.startsWith('Building')) {
      const label = state.detailMeta
        ? `59 m detail · ${Math.round(
          (state.detailMeta.rectangle[2] - state.detailMeta.rectangle[0]) * 111)} km`
          + ` · ${Math.round((state.detailMeta.coverage || 0) * 100)} %`
        : plateLabel(state.plateMeta);
      let suffix = '';
      if (hiddenPlate) suffix = ` · hidden on ${state.globeSkin}`;
      else if (patchy) suffix = ' · hidden (low coverage)';
      chip.textContent = label + suffix;
    }
  }
  const detailBtn = $('#pp-detail');
  if (detailBtn) {
    detailBtn.disabled = hiddenPlate || !state.plateMeta
      || Boolean(state.detailMeta);
    detailBtn.title = hiddenPlate
      ? 'Switch to Satellite or Relief to see imagery'
      : (patchy ? 'Preview too patchy; the 121 km detail is still available' : '');
  }
  const siteBtn = $('#pp-site');
  if (siteBtn) {
    siteBtn.disabled = !(state.selectedFeature || state.selectedDetection);
  }
  const prog = $('#pp-progress');
  if (prog) prog.hidden = !state.plateLoading;
  panel.hidden = false;
}

function flyToProvince(f) {
  const [w, s, e, n] = f.properties.bbox;
  const dx = Math.max((e - w) * 0.08, 0.05);
  const dy = Math.max((n - s) * 0.08, 0.05);
  state.viewer.camera.flyTo({
    destination: C.Rectangle.fromDegrees(
      clamp(w - dx, -180, 180), clamp(s - dy, -90, 90),
      clamp(e + dx, -180, 180), clamp(n + dy, -90, 90)),
    duration: 1.4,
  });
}

function resetIndonesiaCamera() {
  state.camera = { ...MODES.indonesia.camera };
  applyCamera();
}

/**
 * `f` null clears. `fly` frames the bbox; `resetCamera` returns to the
 * Indonesia camera (Esc, sea click) without touching the camera when we are
 * simply leaving the mode.
 */
function selectProvince(f, { fly = true, resetCamera = false } = {}) {
  state.selectedIso = f ? f.properties.iso : null;
  state.selectedFeature = f || null;
  state.selectedDetection = null;
  if (!state.map2d) applyProvinceStyle();
  renderProvincePanel();
  if (state.map2d) {
    state.map2d.select(state.selectedIso);
    if (f && fly) state.map2d.focusProvince(f);
    else if (!f && resetCamera) state.map2d.reset();
  } else if (f && fly) {
    flyToProvince(f);
  } else if (!f && resetCamera && state.viewMode === 'indonesia') {
    resetIndonesiaCamera();
  }
  clearPlate();
  if (f) loadProvinceImagery(f);
  renderLegend();
}

function clearProvinceSelection() {
  if (!state.selectedIso) return;
  selectProvince(null, { resetCamera: true });
  hideProvinceTip();
}

/* ---------------- fire-site 3D context ---------------- */
function siteRect(site) {
  const b = site.bbox;
  return C.Rectangle.fromDegrees(b.west, b.south, b.east, b.north);
}

function sampleSiteHeight(site, lon, lat) {
  const b = site.bbox;
  const hm = site.heightmap;
  if (lon < b.west || lon > b.east || lat < b.south || lat > b.north) return 0;
  const fx = (lon - b.west) / (b.east - b.west) * (hm.width - 1);
  const fy = (b.north - lat) / (b.north - b.south) * (hm.height - 1);
  const x0 = clamp(Math.floor(fx), 0, hm.width - 1);
  const y0 = clamp(Math.floor(fy), 0, hm.height - 1);
  const x1 = Math.min(hm.width - 1, x0 + 1);
  const y1 = Math.min(hm.height - 1, y0 + 1);
  const sx = fx - x0, sy = fy - y0;
  const h = hm.heights_m;
  const a = h[y0 * hm.width + x0], b1 = h[y0 * hm.width + x1];
  const c = h[y1 * hm.width + x0], d = h[y1 * hm.width + x1];
  return (a * (1 - sx) + b1 * sx) * (1 - sy)
    + (c * (1 - sx) + d * sx) * sy;
}

function openSiteFromSelection() {
  const det = state.selectedDetection;
  const f = state.selectedFeature;
  if (!det && !f) return;
  const b = f ? f.properties.bbox : null;
  const lon = det ? det.lon : (b[0] + b[2]) / 2;
  const lat = det ? det.lat : (b[1] + b[3]) / 2;
  openSite(lon, lat, det);
}

async function openSite(lon, lat, det) {  const loading = $('#site-loading');
  const btn = $('#pp-site');
  if (loading) loading.hidden = false;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(
      `api/v1/sites?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`,
      { cache: 'no-store' });
    const data = await r.json();
    if (!data.available) throw new Error(data.reason || 'unavailable');
    state.siteDetection = det || null;
    enterSite(data);
  } catch (e) {
    const chip = $('#pp-imagery');
    if (chip) chip.textContent = `Site unavailable (${e.message})`;
  } finally {
    if (loading) loading.hidden = true;
    if (btn) btn.disabled = false;
  }
}

async function loadSiteWindow(km) {
  if (!state.site) return;
  const c = state.site.centre;
  const loading = $('#site-loading');
  const text = $('#site-loading-text');
  if (loading) loading.hidden = false;
  if (text) text.textContent = `Building ${km} km context…`;
  try {
    const r = await fetch(
      `api/v1/sites?lat=${c.lat.toFixed(4)}&lon=${c.lon.toFixed(4)}`
      + `&window_km=${km}`, { cache: 'no-store' });
    const data = await r.json();
    if (!data.available) throw new Error(data.reason || 'unavailable');
    enterSite(data);
  } catch (e) {
    const chip = $('#pp-imagery');
    if (chip) chip.textContent = `Site unavailable (${e.message})`;
  } finally {
    if (loading) loading.hidden = true;
  }
}

function focusSiteCamera(site = state.site) {
  if (!site || !state.viewer) return;
  const km = site.window_km || 18;
  const range = km >= 40 ? 28000 : (km <= 6 ? 3500 : 9000);
  const c = site.centre;
  state.viewer.camera.lookAt(
    C.Cartesian3.fromDegrees(c.lon, c.lat, 0),
    new C.HeadingPitchRange(0, C.Math.toRadians(-40), range));
  state.viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
}

function clearSiteSpread() {
  if (state.spreadTimer) {
    clearInterval(state.spreadTimer);
    state.spreadTimer = 0;
  }
  state.spreadPlaying = false;
  if (state.siteSpreadDs && state.viewer) {
    state.viewer.dataSources.remove(state.siteSpreadDs, true);
  }
  state.siteSpreadDs = null;
  state.spreadFrames = [];
  state.spreadEntities = [];
  state.spreadHead = null;
  state.spreadIdx = 0;
  const panel = $('#site-spread');
  if (panel) panel.hidden = true;
  const btn = $('#spread-play');
  if (btn) btn.textContent = '▶';
}

function setSpreadFrame(idx) {
  const frames = state.spreadFrames;
  if (!frames.length) return;
  const i = clamp(idx, 0, frames.length - 1);
  state.spreadIdx = i;
  state.spreadEntities.forEach((ent, n) => {
    ent.show = n <= i;
    const current = n === i;
    ent.polyline.material = new C.ColorMaterialProperty(
      current ? AMBER.withAlpha(0.95) : AMBER.withAlpha(0.22));
    ent.polyline.width = current ? 2.2 : 1.1;
  });
  const frame = frames[i];
  if (state.spreadHead) {
    state.spreadHead.position = C.Cartesian3.fromDegrees(
      frame.head.lon, frame.head.lat, 0);
    state.spreadHead.label.text = new C.ConstantProperty(`+${frame.t_min} min`);
  }
  const slider = $('#spread-time');
  if (slider) slider.value = String(i);
  const label = $('#spread-label');
  if (label) label.textContent = `+${frame.t_min} min`;
}

function playSpread(on) {
  if (state.spreadTimer) {
    clearInterval(state.spreadTimer);
    state.spreadTimer = 0;
  }
  state.spreadPlaying = Boolean(on);
  const btn = $('#spread-play');
  if (btn) btn.textContent = on ? '❚❚' : '▶';
  if (on && state.spreadFrames.length > 1) {
    state.spreadTimer = setInterval(() => {
      setSpreadFrame((state.spreadIdx + 1) % state.spreadFrames.length);
    }, 700);
  }
}

function initSiteSpread(site) {
  clearSiteSpread();
  const spread = site.spread;
  const frames = spread && spread.frames;
  const panel = $('#site-spread');
  if (!frames || frames.length < 2) {
    if (panel) panel.hidden = true;
    return;
  }
  if (panel) panel.hidden = false;
  const risk = $('#spread-risk');
  if (risk) risk.textContent = `${spread.risk} · ${spread.rate_m_min} m/min`;
  const slider = $('#spread-time');
  if (slider) {
    slider.max = String(frames.length - 1);
    slider.value = '0';
  }
  const ds = new C.CustomDataSource('site-spread');
  state.viewer.dataSources.add(ds);
  state.siteSpreadDs = ds;
  state.spreadFrames = frames;
  state.spreadEntities = [];
  for (const frame of frames) {
    const flat = [];
    for (const [lon, lat] of frame.ring) flat.push(lon, lat);
    state.spreadEntities.push(ds.entities.add({
      polyline: {
        positions: C.Cartesian3.fromDegreesArray(flat),
        width: 1.1,
        clampToGround: true,
        arcType: C.ArcType.GEODESIC,
        material: new C.ColorMaterialProperty(AMBER.withAlpha(0.22)),
      },
    }));
  }
  const h = frames[0].head;
  state.spreadHead = ds.entities.add({
    position: C.Cartesian3.fromDegrees(h.lon, h.lat, 0),
    point: {
      pixelSize: 8, color: FLAME,
      outlineColor: C.Color.BLACK.withAlpha(0.4), outlineWidth: 1,
      heightReference: C.HeightReference.CLAMP_TO_GROUND,
      disableDepthTestDistance: 5000,
    },
    label: {
      text: '+0 min',
      font: '600 10px Consolas, monospace',
      fillColor: C.Color.fromCssColorString('#ffcf7a'),
      showBackground: true,
      backgroundColor: C.Color.fromCssColorString('#0a1418').withAlpha(0.75),
      pixelOffset: new C.Cartesian2(0, -18),
      heightReference: C.HeightReference.CLAMP_TO_GROUND,
      disableDepthTestDistance: 5000,
    },
  });
  setSpreadFrame(0);
  playSpread(true);
}

function applySiteScene(site) {
  const viewer = state.viewer;
  if (!viewer) return;
  if (state.siteImagery) {
    viewer.imageryLayers.remove(state.siteImagery, true);
    state.siteImagery = null;
  }
  if (state.siteData) {
    viewer.dataSources.remove(state.siteData, true);
    state.siteData = null;
  }
  const scheme = new C.GeographicTilingScheme();
  const N = 65;
  const provider = new C.CustomHeightmapTerrainProvider({
    width: N, height: N, tilingScheme: scheme,
    callback: (x, y, level) => {
      const rect = scheme.tileXYToRectangle(x, y, level);
      const west = C.Math.toDegrees(rect.west);
      const east = C.Math.toDegrees(rect.east);
      const south = C.Math.toDegrees(rect.south);
      const north = C.Math.toDegrees(rect.north);
      const out = new Float32Array(N * N);
      for (let j = 0; j < N; j++) {
        for (let i = 0; i < N; i++) {
          const lon = west + (east - west) * i / (N - 1);
          const lat = north - (north - south) * j / (N - 1);
          out[j * N + i] = sampleSiteHeight(site, lon, lat);
        }
      }
      return out;
    },
  });
  viewer.terrainProvider = provider;
  state.siteTerrain = provider;
  if (site.imagery_url) {
    state.siteImagery = viewer.imageryLayers.addImageryProvider(
      new C.SingleTileImageryProvider({
        url: site.imagery_url, rectangle: siteRect(site),
      }));
  }
  if (state.worldLayer) state.worldLayer.show = true;
  if (state.indonesiaLayer) state.indonesiaLayer.show = true;
  const scene = viewer.scene;
  scene.globe.enableLighting = true;
  scene.globe.terrainExaggeration = state.siteExaggeration;
  scene.light = new C.DirectionalLight({
    direction: new C.Cartesian3(-0.55, -0.5, -0.67),
  });
  scene.globe.depthTestAgainstTerrain = true;
  if (scene.skyAtmosphere) scene.skyAtmosphere.show = true;
  focusSiteCamera(site);
  const ds = new C.CustomDataSource('site');
  viewer.dataSources.add(ds);
  const det = state.siteDetection;
  ds.entities.add({
    position: C.Cartesian3.fromDegrees(
      det ? det.lon : site.centre.lon, det ? det.lat : site.centre.lat, 0),
    point: {
      pixelSize: 8, color: RED,
      outlineColor: C.Color.BLACK.withAlpha(0.5), outlineWidth: 1,
      heightReference: C.HeightReference.CLAMP_TO_GROUND,
    },
    label: {
      text: det ? 'FIRMS detection' : 'site centre',
      font: '10px Consolas, monospace',
      fillColor: C.Color.fromCssColorString('#ffe3b0'),
      style: C.LabelStyle.FILL,
      pixelOffset: new C.Cartesian2(0, -18),
      heightReference: C.HeightReference.CLAMP_TO_GROUND,
      disableDepthTestDistance: 5000,
    },
  });
  state.siteData = ds;
}

function teardownSite() {
  clearSiteSpread();
  const viewer = state.viewer;
  if (viewer) {
    if (state.siteImagery) viewer.imageryLayers.remove(state.siteImagery, true);
    if (state.siteData) viewer.dataSources.remove(state.siteData, true);
    viewer.terrainProvider = new C.EllipsoidTerrainProvider();
    if (viewer.scene.globe) {
      viewer.scene.globe.enableLighting = false;
      viewer.scene.globe.depthTestAgainstTerrain = false;
    }
  }
  state.siteImagery = null;
  state.siteData = null;
  state.siteTerrain = null;
  state.site = null;
  state.siteDetection = null;
  const panel = $('#site-panel');
  if (panel) panel.hidden = true;
  const rail = $('#site-rail');
  if (rail) rail.hidden = true;
  const strip = $('#site-strip');
  if (strip) strip.hidden = true;
}

function firesNearSite(site) {
  const lat0 = site.centre.lat, lon0 = site.centre.lon;
  const limit = site.window_km * 0.5;
  let n = 0;
  for (const d of (state.fires && state.fires.dots) || []) {
    const p1 = lat0 * Math.PI / 180;
    const p2 = d.lat * Math.PI / 180;
    const dp = p2 - p1;
    const dl = (d.lon - lon0) * Math.PI / 180;
    const a = Math.sin(dp / 2) ** 2
      + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    const km = 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
    if (km <= limit) n++;
  }
  return n;
}

function drawSiteProfile(site) {
  const c = $('#site-profile');
  if (!c || !site.heightmap) return;
  const ctx = c.getContext('2d');
  const w = c.width, h = c.height;
  const hm = site.heightmap;
  const row = Math.floor(hm.height / 2);
  const vals = [];
  let mn = Infinity, mx = -Infinity;
  for (let i = 0; i < hm.width; i++) {
    const v = hm.heights_m[row * hm.width + i];
    vals.push(v);
    if (v < mn) mn = v;
    if (v > mx) mx = v;
  }
  const span = (mx - mn) || 1;
  ctx.clearRect(0, 0, w, h);
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = i / (vals.length - 1) * w;
    const y = h - 7 - ((v - mn) / span) * (h - 14);
    if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.strokeStyle = '#a05a10';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.fillStyle = 'rgba(160, 90, 16, .14)';
  ctx.fill();
  ctx.fillStyle = '#6f685c';
  ctx.font = '10px Consolas, monospace';
  ctx.textAlign = 'left';
  ctx.fillText(`${Math.round(mn)} m`, 4, 12);
  ctx.textAlign = 'right';
  ctx.fillText(`${Math.round(mx)} m`, w - 4, 12);
  ctx.textAlign = 'left';
}

function chartLine(canvas, values, stroke, fill) {
  if (!canvas || !values.length) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const mn = Math.min(...values), mx = Math.max(...values);
  const span = (mx - mn) || 1;
  ctx.clearRect(0, 0, w, h);
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = i / Math.max(1, values.length - 1) * w;
    const y = h - 4 - ((v - mn) / span) * (h - 8);
    if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.6;
  ctx.stroke();
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
}

function renderSiteShell(site) {
  const spread = site.spread;
  $('#sr-risk').textContent = spread ? spread.risk : '—';
  $('#ss-risk').textContent = spread
    ? `${spread.risk} · ${spread.rate_m_min} m/min` : '—';
  $('#ss-time').textContent = spread
    ? `${spread.fuel_label || spread.model} · `
      + `${Math.round((spread.moisture || 0) * 100)}% FM · 0–360 min` : '—';
  $('#sr-name').textContent = `${site.name} · ${site.iso || ''}`;
  $('#sr-window').textContent = `${site.window_km} km · ${site.imagery_mpp} m/px`;
  $('#sr-centre').textContent = `${site.centre.lat.toFixed(3)}, ${site.centre.lon.toFixed(3)}`;
  const det = state.siteDetection;
  $('#sr-detection').textContent = det
    ? `${det.sensor} · ${det.frp ?? '—'} MW · ${String(det.acq_at).slice(11, 16)}Z`
    : 'opened from province centre';
  const near = firesNearSite(site);
  $('#sr-fires').textContent = `${near} dots ≤ ${Math.round(site.window_km / 2)} km`;

  const w = site.weather;
  $('#sr-firms').textContent = `${near} dots · 5 d`;
  $('#sr-met').textContent = w
    ? `${Math.round(w.wind_speed_kmh)} km/h · ${Math.round(w.temp_c)} °C`
    : 'unavailable';
  $('#sr-dem').textContent = site.terrain
    ? `30 m · ${site.terrain.grid_m} m grid` : '30 m';
  const range = (site.imagery_date_range || []).join(' → ');
  $('#sr-s2').textContent = `${site.imagery_scenes || 0} scenes · `
    + `${Math.round((site.imagery_coverage || 0) * 100)} %`;
  $('#sr-s2').title = range;

  const events = [];
  if (det) events.push([String(det.acq_at).slice(11, 16), 'FIRMS detection']);
  if (site.generated_at) {
    events.push([String(site.generated_at).slice(11, 16), 'site context built']);
  }
  if (spread) events.push(['model', spread.model]);
  $('#ss-events-list').innerHTML = events.map(
    ([t, label]) => `<li><b>${t}</b>${label}</li>`).join('');

  if (spread) {
    const frames = spread.frames;
    const areas = frames.map((f) => {
      const head = spread.rate_m_min * f.t_min;
      return Math.PI * (0.6 * head) * (0.32 * head) / 10000;
    });
    chartLine($('#ss-area'), areas, '#a05a10', 'rgba(160,90,16,.12)');
    chartLine($('#ss-rate'), frames.map(() => spread.rate_m_min),
      '#b0401c', 'rgba(176,64,28,.12)');
    $('#ss-area-val').textContent = `${Math.round(Math.max(...areas))} ha`;
    $('#ss-rate-val').textContent = `${spread.rate_m_min} m/min`;
  }
  const hm = site.heightmap;
  if (hm) {
    const col = Math.floor(hm.width / 2);
    const vals = [];
    for (let j = 0; j < hm.height; j++) vals.push(hm.heights_m[j * hm.width + col]);
    chartLine($('#ss-elev'), vals, '#2f648c', 'rgba(47,100,140,.12)');
    $('#ss-elev-val').textContent =
      `${Math.round(Math.min(...vals))}–${Math.round(Math.max(...vals))} m`;
  }
  const rail = $('#site-rail');
  const strip = $('#site-strip');
  if (rail) rail.hidden = false;
  if (strip) strip.hidden = false;
  const img = $('#sr-l-imagery');
  if (img && state.siteImagery) state.siteImagery.show = img.checked;
  const terr = $('#sr-l-terrain');
  if (terr && state.viewer) {
    state.viewer.scene.globe.terrainExaggeration = state.siteExaggeration;
  }
  const spr = $('#sr-l-spread');
  if (spr && state.siteSpreadDs) state.siteSpreadDs.show = spr.checked;
  const fire = $('#sr-l-fire');
  if (fire && state.siteData) state.siteData.show = fire.checked;
  $$('.sr-relief button').forEach((b) => b.classList.toggle(
    'active', Number(b.dataset.ex) === state.siteRelief));
  const terrCb = $('#sr-l-terrain');
  if (terrCb) terrCb.checked = state.siteExaggeration > 1;
}

function enterSite(site) {  state.site = site;
  state.viewMode = 'site';
  setMode('site');
  applySiteScene(site);
  initSiteSpread(site);
  const panel = $('#site-panel');
  if (panel) panel.hidden = false;
  $('#site-name').textContent = site.name;
  $('#site-facts').textContent = `${site.window_km || 18} km · 30 m DEM · `
    + `${site.imagery_scenes || 0} Sentinel scenes · `
    + `${Math.round((site.imagery_coverage || 0) * 100)} % · `
    + `${site.imagery_mpp || 9} m/px`;
  $$('.site-scales button').forEach((b) => {
    b.classList.toggle('active',
      Number(b.dataset.km) === Math.round(site.window_km || 18));
  });
  const terrain = site.terrain;
  const terrainEl = $('#site-terrain');
  if (terrainEl) {
    terrainEl.textContent = terrain
      ? `${terrain.min_m}–${terrain.max_m} m · ${terrain.relief_m} m relief · `
        + `${terrain.slope_deg}° slope · ${terrain.aspect_deg}° aspect`
      : '—';
  }
  const imageryEl = $('#site-imagery-facts');
  if (imageryEl) {
    const range = (site.imagery_date_range || []).join(' → ') || '—';
    imageryEl.textContent = `${site.imagery_scenes || 0} scenes · ${range} · `
      + `${Math.round((site.imagery_coverage || 0) * 100)} % · `
      + `${site.imagery_mpp || 9} m/px`;
  }
  const firesEl = $('#site-fire-count');
  if (firesEl) {
    firesEl.textContent = `${firesNearSite(site)} FIRMS dots within `
      + `${Math.round(site.window_km / 2)} km`;
  }
  const spreadEl = $('#site-spread-facts');
  if (spreadEl) {
    spreadEl.textContent = site.spread
      ? `${site.spread.risk} · ${site.spread.rate_m_min} m/min · `
        + `${site.spread.bearing_deg}° bearing`
      : '—';
  }
  drawSiteProfile(site);
  renderSiteShell(site);
  const weather = site.weather;
  const weatherEl = $('#site-weather');
  if (weatherEl) {
    weatherEl.hidden = !weather;
    if (weather) {
      weatherEl.textContent = `Wind ${Math.round(weather.wind_speed_kmh)} km/h `
        + `${Math.round(weather.wind_dir_deg)}° · ${Math.round(weather.temp_c)} °C`
        + ` · ${weather.humidity_pct} % RH`;
    }
  }
  const det = state.siteDetection;
  const detEl = $('#site-detection');
  if (detEl) {
    detEl.hidden = !det;
    if (det) {
      detEl.textContent = `${det.sensor} · ${String(det.acq_at).replace('T', ' ')}`
        + ` · ${det.frp ?? '—'} MW · ${Math.round((det.confidence || 0) * 100)} %`;
    }
  }
  syncTabs();
}

function exitSite() {
  teardownSite();
  state.viewMode = 'indonesia';
  setMode('indonesia');
  syncTabs();
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

/* The Esri fallback PNG carries a feathered ring in its outer 20 %; the bands
   below draw that ring and the centre quad samples only the opaque middle. */
const FALLBACK_EDGE = 0.2;

/** Texture coordinates for a mesh box, whichever landscape texture is in use. */
function texRectFor(box) {
  if (state.contextImageryBbox) return TM.textureRect(box, state.contextImageryBbox);
  return [FALLBACK_EDGE, FALLBACK_EDGE, 1 - FALLBACK_EDGE, 1 - FALLBACK_EDGE];
}

function texCoordsFor(u, v, box) {
  if (state.contextImageryBbox) return texCoordsIn(u, v, box, state.contextImageryBbox);
  return [FALLBACK_EDGE + (1 - 2 * FALLBACK_EDGE) * u,
    FALLBACK_EDGE + (1 - 2 * FALLBACK_EDGE) * v];
}

function texCoordsIn(u, v, box, imageBox) {
  const [u0, v0, u1, v1] = TM.textureRect(box, imageBox);
  return [u0 + (u1 - u0) * u, v0 + (v1 - v0) * v];
}

function buildLandscape() {
  const c = state.f.context;
  const base = state.center.hmin - 1.6;
  // `st` defaults to the geometry rectangle (the fallback crops geometry and
  // texture together); imagery passes a geographic sub-rectangle instead.
  const quad = (material, box, u0, u1, v0, v1, translucent, st = null) => {
    const corners = [
      [u0, v0], [u1, v0], [u1, v1], [u0, v1],
    ];
    const pos = [];
    for (const [u, v] of corners) {
      const lon = box.west + (box.east - box.west) * u;
      const lat = box.north - (box.north - box.south) * v;
      const p = C.Cartesian3.fromDegrees(lon, lat, base);
      pos.push(p.x, p.y, p.z);
    }
    const [t0, s0, t1, s1] = st || [u0, v0, u1, v1];
    const geo = new C.Geometry({
      attributes: {
        position: new C.GeometryAttribute({ componentDatatype: C.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(pos) }),
        st: new C.GeometryAttribute({
          componentDatatype: C.ComponentDatatype.FLOAT, componentsPerAttribute: 2,
          values: new Float32Array([t0, s0, t1, s0, t1, s1, t0, s1]),
        }),
      },
      indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
      primitiveType: C.PrimitiveType.TRIANGLES,
      boundingSphere: C.BoundingSphere.fromVertices(pos),
    });
    return new C.Primitive({
      geometryInstances: new C.GeometryInstance({ geometry: geo }),
      appearance: new C.MaterialAppearance({ material, flat: true, translucent }),
      asynchronous: false,
    });
  };

  // 1. The cached Esri mosaic, unchanged: inset to its opaque centre with the
  //    feathered ring drawn by four translucent bands. This is the
  //    reconstruction backdrop and the no-imagery fallback.
  const fbMat = new C.Material({
    fabric: { type: 'Image', uniforms: { image: CONTEXT_TEXTURE, color: new C.Color(1, 1, 1, 1) } },
  });
  const edge = FALLBACK_EDGE;
  const outer = 1 - edge;
  const fallback = new C.PrimitiveCollection();
  state.prims.landscapeFallbackCenter = quad(fbMat, c, edge, outer, edge, outer, false);
  fallback.add(state.prims.landscapeFallbackCenter);
  fallback.add(quad(fbMat, c, 0, 1, 0, edge, true));          // north band
  fallback.add(quad(fbMat, c, 0, 1, outer, 1, true));         // south band
  fallback.add(quad(fbMat, c, 0, edge, edge, outer, true));   // west band
  fallback.add(quad(fbMat, c, outer, 1, edge, outer, true));  // east band
  state.viewer.scene.primitives.add(fallback);
  state.prims.landscapeFallback = fallback;

  // 2. Sentinel-2, only when its footprint is known. It is stretched over the
  //    detail box (image limited by the DEM tile) and samples its own
  //    geographic sub-rect. Shown in Terrain/Regional only: Drone keeps the
  //    cached backdrop it has always had.
  if (state.contextImageryUrl && state.contextImageryBbox) {
    const imgMat = new C.Material({
      fabric: { type: 'Image', uniforms: { image: state.contextImageryUrl, color: new C.Color(1, 1, 1, 1) } },
    });
    const box = detailBox();
    const collection = new C.PrimitiveCollection();
    state.prims.landscapeCenter = quad(imgMat, box, 0, 1, 0, 1, false, texRectFor(box));
    collection.add(state.prims.landscapeCenter);
    state.viewer.scene.primitives.add(collection);
    state.prims.landscapeImagery = collection;
  }
}

/** The collection the DEM surfaces belong to: imagery when we have it. */
function landscapeTarget() {
  return state.prims.landscapeImagery || state.prims.landscapeFallback;
}

function applySceneTheme() {
  if (!state.viewer) return;
  const indonesia = state.mode === 'indonesia';
  const context = state.mode === 'context';
  const dark = document.documentElement.dataset.theme === 'obsidian';
  const useStudio = dark && !context && !indonesia;
  const imagery = Boolean(state.prims.landscapeImagery);
  if (state.prims.studio) state.prims.studio.show = useStudio;
  // Sentinel-2 belongs to Terrain/Regional; Drone keeps its cached backdrop.
  if (state.prims.landscapeImagery) {
    state.prims.landscapeImagery.show = !indonesia && imagery && context && !useStudio;
  }
  if (state.prims.landscapeFallback) {
    state.prims.landscapeFallback.show = !indonesia && (!imagery || !context) && !useStudio;
  }
  state.viewer.scene.backgroundColor = indonesia
    ? C.Color.fromCssColorString('#070b0d')
    : (useStudio ? C.Color.fromCssColorString('#070709')
      : C.Color.fromCssColorString('#dfe8e3'));
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
  const target = state.viewMode === 'indonesia'
    ? C.Cartesian3.fromDegrees(INDONESIA.lon, INDONESIA.lat, 0)
    : C.Cartesian3.fromDegrees(c.lon, c.lat, c.height);
  state.viewer.camera.lookAt(
    target,
    new C.HeadingPitchRange(rad(heading), rad(pitch), range)
  );
  state.viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
  $('#compass').style.setProperty('--heading', `${-heading}deg`);
  updateScaleBar();
}

/** Ground metres per screen pixel at the camera target, then a round bar. */
function updateScaleBar() {
  const el = $('#scalebar');
  if (!el) return;
  const show = state.viewMode === 'regional' && state.mode === 'context'
    && state.viewer && state.viewer.camera.frustum.fovy;
  el.hidden = !show;
  if (!show) return;
  const height = state.canvas.clientHeight || 1;
  const mpp = (2 * state.camera.range * Math.tan(state.viewer.camera.frustum.fovy / 2)) / height;
  const bar = TM.scaleBar(mpp, 132);
  $('#sb-bar').style.width = `${Math.round(bar.px)}px`;
  $('#sb-label').textContent = bar.label;
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
  // Zoom no longer switches mode: the tab is the only authority (modes spec 3).
  return;
}

function wireCamera() {
  const el = state.canvas;
  const cesiumOwns = () => state.viewMode === 'indonesia'
    || state.viewMode === 'site'; // Cesium's controls, not the mission orbit
  let drag = null;
  el.addEventListener('pointerdown', (e) => {
    if (cesiumOwns()) return;
    if (state.flyRaf) { cancelAnimationFrame(state.flyRaf); state.flyRaf = 0; }
    drag = { x: e.clientX, y: e.clientY, id: e.pointerId };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (cesiumOwns()) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    state.camera.heading += dx * 0.28;
    state.camera.pitch = clamp(state.camera.pitch + dy * 0.22, -85, -12);
    applyCamera();
  });
  el.addEventListener('pointerup', (e) => {
    if (cesiumOwns()) return;
    if (drag && e.pointerId === drag.id) { drag = null; el.releasePointerCapture(e.pointerId); }
  });
  el.addEventListener('wheel', (e) => {
    if (cesiumOwns()) return;
    e.preventDefault();
    if (state.flyRaf) { cancelAnimationFrame(state.flyRaf); state.flyRaf = 0; }
    state.camera.range = clamp(state.camera.range * Math.exp(e.deltaY * 0.0011), state.rangeLimits.min, state.rangeLimits.max);
    applyCamera();
    checkZoomMode();
  }, { passive: false });
  // Province hover is independent of drag; it works with Cesium's controls.
  el.addEventListener('pointermove', (e) => {
    if (state.viewMode !== 'indonesia') return;
    const rect = el.getBoundingClientRect();
    const pos = new C.Cartesian2(e.clientX - rect.left, e.clientY - rect.top);
    const cartesian = state.viewer.camera.pickEllipsoid(pos, C.Ellipsoid.WGS84);
    if (!C.defined(cartesian)) {
      setHoverProvince(null);
      hideProvinceTip();
      return;
    }
    const carto = C.Cartographic.fromCartesian(cartesian);
    const f = provinceAt(C.Math.toDegrees(carto.longitude),
      C.Math.toDegrees(carto.latitude));
    setHoverProvince(f);
    if (f) {
      const row = fireRow(f.properties.iso);
      showProvinceTip(f.properties.name, e.clientX, e.clientY, row ? row.count : null);
    }
    else hideProvinceTip();
  });
  el.addEventListener('pointerleave', () => {
    setHoverProvince(null);
    hideProvinceTip();
  });
  window.addEventListener('resize', updateScaleBar);
}

function wireSceneClicks() {
  const handler = new C.ScreenSpaceEventHandler(state.canvas);
  // One LEFT_CLICK action: a second setInputAction on the same type would
  // silently replace the first and break the mission-scene clicks.
  handler.setInputAction((movement) => {
    if (state.viewMode === 'indonesia') {
      // Province click: the same ellipsoid pick as hover, then the bundled
      // point-in-polygon. A sea click clears and brings the archipelago back.
      const had = Boolean(state.selectedIso);
      const cartesian = state.viewer.camera.pickEllipsoid(movement.position, C.Ellipsoid.WGS84);
      const picked = state.viewer.scene.pick(movement.position);
      const dot = picked && picked.id && picked.id.__fire;
      if (dot) {
        const df = provinceAt(dot.lon, dot.lat);
        if (df) {
          selectProvince(df);
          state.selectedDetection = dot;
          renderProvincePanel();
        }
        return;
      }
      if (!C.defined(cartesian)) {
        if (had) selectProvince(null, { resetCamera: true });
        return;
      }
      const carto = C.Cartographic.fromCartesian(cartesian);
      const f = provinceAt(C.Math.toDegrees(carto.longitude), C.Math.toDegrees(carto.latitude));
      if (f) selectProvince(f);
      else if (had) selectProvince(null, { resetCamera: true });
      return;
    }
    if (state.mode !== 'context') return;
    const picked = state.viewer.scene.pick(movement.position);
    if (!C.defined(picked)) return;
    const id = picked.id;
    if (state.footprintEntities.includes(id) || state.hotspotPins.includes(id)) openReconstruction();
  }, C.ScreenSpaceEventType.LEFT_CLICK);
}

function setMode(mode) {
  if (mode !== 'site' && state.site) teardownSite();
  state.mode = mode;
  const ctx = mode === 'context';
  const indonesia = mode === 'indonesia';
  const site = mode === 'site';
  $('#app').classList.toggle('mode-context', ctx);
  $('#app').classList.toggle('mode-indonesia', indonesia);
  $('#app').classList.toggle('mode-site', site);
  if (state.viewer) {
    state.viewer.useDefaultRenderLoop = !indonesia;
    state.viewer.scene.globe.show = indonesia || site;
    if (state.viewer.scene.skyAtmosphere) {
      state.viewer.scene.skyAtmosphere.show = indonesia || site;
    }
    // FXAA smooths the 1 px province borders; it is not worth its cost on the
    // mission scene, which is already MSAA-free.
    const stages = state.viewer.scene.postProcessStages;
    if (stages && stages.fxaa) stages.fxaa.enabled = indonesia;
    // Cesium's own globe controls (rotate + zoom to the cursor) only make
    // sense on the site globe; the mission modes keep the custom orbit.
    const ssc = state.viewer.scene.screenSpaceCameraController;
    ssc.enableInputs = site;
    ssc.minimumZoomDistance = site ? 800 : (indonesia ? 500000 : 0);
    ssc.maximumZoomDistance = site ? 40000
      : (indonesia ? 12000000 : Number.POSITIVE_INFINITY);
    if (!indonesia) {
      setHoverProvince(null);
      hideProvinceTip();
      clearPlate();
    }
  }
  if (!indonesia && !site) applyAllLayers();
  if (state.prims.shadow) state.prims.shadow.show = !ctx && !indonesia && !site;
  applyRingVisibility();
  if (state.groups.footprint) state.groups.footprint.show = ctx;
  if (indonesia || site) hideLocalScene();
  if (state.provinces) state.provinces.show = indonesia;
  if (state.fireDs) state.fireDs.show = indonesia;
  // The globe only exists here; so do the skin, the LOD layer and selection.
  if (indonesia) applyGlobeSkin();
  else if (site) {
    if (state.worldLayer) state.worldLayer.show = true;
    if (state.indonesiaLayer) state.indonesiaLayer.show = true;
  } else hideGlobeLayers();
  if (!indonesia && state.selectedIso) {
    state.selectedIso = null;
    state.selectedFeature = null;
    applyProvinceStyle();
  }
  renderProvincePanel();
  const nameEl = $('#incident-name');
  const idEl = $('#mission-id');
  const metaEl = $('#incident-meta');
  if (site) {
    if (nameEl) nameEl.textContent = state.site ? state.site.name : 'Site';
    if (idEl) idEl.textContent = 'SITE CONTEXT';
    if (metaEl) metaEl.textContent = `${state.site ? state.site.window_km : 18} km · Copernicus DEM + Sentinel-2`;
  } else if (state.incident) {
    if (nameEl) nameEl.textContent = indonesia ? 'Indonesia' : state.incident.name;
    if (idEl) idEl.textContent = indonesia ? 'NATIONAL VIEW' : state.incident.id;
    if (metaEl) metaEl.textContent = indonesia ? '38 provinces · OSM boundaries' : state.incident.meta;
  }
  applySceneTheme();
  renderLegend();
  renderFiresInset();
  const attrib = $('#attrib');
  if (attrib) attrib.textContent = contextAttribution();
  syncTabs();
  // Hiding the rail/strip changes the stage size without a window resize.
  requestAnimationFrame(() => {
    if (state.map2d) state.map2d.resize();
    if (state.viewer) state.viewer.resize();
  });
}

/** Indonesia shows the globe, not the mission's flat scene. */
function hideLocalScene() {
  for (const p of Object.values(state.bases || {})) if (p) p.show = false;
  for (const k of ['heat', 'contextTerrain', 'ringTerrain', 'ringTerrainWide',
    'shadow', 'studio']) {
    if (state.prims[k]) state.prims[k].show = false;
  }
  for (const g of Object.values(state.groups || {})) if (g) g.show = false;
}

/* ---------------- context imagery (Sentinel-2) ---------------- */
const CONTEXT_TEXTURE = 'data/context_bright.png';

function loadContextImagery(live) {
  // The footprint is what makes the asset placeable; a URL alone cannot be
  // registered against the mosaic, so it is not used.
  const meta = live && live.imagery;
  const url = (meta && meta.url) || (live && live.assets && live.assets.context_imagery);
  if (!url || !meta || !meta.bbox) return;
  state.contextImageryUrl = url;
  state.contextImageryBbox = meta.bbox;
  state.contextImageryMeta = meta;
}

function loadContextDemMeta(live) {
  const meta = live && live.dem;
  if (meta && meta.bbox) state.contextDemMeta = meta;
}

function boxIntersect(a, b) {
  if (!a) return b || null;
  if (!b) return a;
  const west = Math.max(a.west, b.west);
  const east = Math.min(a.east, b.east);
  const south = Math.max(a.south, b.south);
  const north = Math.min(a.north, b.north);
  return west < east && south < north ? { west, south, east, north } : a;
}

/**
 * The area the local surface is drawn over: as much of the image as the DEM
 * actually covers. The DEM tile is the limit — drawing the full 4 km image past
 * its edge would leave a flat shelf the ring cannot join.
 */
function detailBox() {
  const img = state.contextImageryBbox;
  const dem = state.contextDemMeta && state.contextDemMeta.bbox;
  if (img && dem) return boxIntersect(img, dem);
  return img || state.f.context;
}

function detailWidthKm() {
  const b = detailBox();
  if (!b) return 0;
  const kmPerDegLon = 111.32 * Math.cos(rad((b.south + b.north) / 2));
  return Math.max(0.1, Math.round((b.east - b.west) * kmPerDegLon * 10) / 10);
}

function contextTexture() {
  return state.contextImageryUrl || CONTEXT_TEXTURE;
}

function imageryFact() {
  const m = state.contextImageryMeta;
  if (!m) return '';
  const when = m.acquired_at ? fmtDay(m.acquired_at) : '';
  const cloud = m.cloud_pct == null ? ''
    : (m.cloud_pct < 1 ? '<1' : String(Math.round(m.cloud_pct))) + ' % cloud';
  const res = m.resolution_m ? `${m.resolution_m} m source` : '';
  const win = m.window_km ? `${m.window_km} km window` : '';
  return [when, cloud, res, win].filter(Boolean).join(' · ');
}

function contextSourceNote() {
  const c = state.f.context;
  const fact = imageryFact();
  if (!fact) return `${c.source}. ${c.attribution}`;
  const credit = state.contextImageryMeta.attribution
    || 'Contains modified Copernicus Sentinel data';
  return `Sentinel-2 L2A · ${fact}. ${credit}`;
}

function contextAttribution() {
  if (state.viewMode === 'indonesia') {
    return state.globeSkin === 'flat'
      ? '© OpenStreetMap contributors · flat skin'
      : '© OpenStreetMap contributors · NASA Blue Marble';
  }
  const m = state.contextImageryMeta;
  // Only claim Sentinel-2 while it is the surface on screen.
  if (m && state.mode === 'context') return m.attribution;
  return state.f.context.attribution;
}

function contextLegendLine() {
  const wide = state.viewMode === 'regional' ? state.contextImageryWide : null;
  if (wide) {
    const n = wide.scene_count || 1;
    const when = (wide.date_range || []).join(' – ');
    return `Sentinel-2 mosaic · ${n} scene${n > 1 ? 's' : ''} · ${when || 'dated'}`
      + ` · ${wide.resolution_m || '?'} m`;
  }
  if (state.contextImageryMeta) return `Sentinel-2 · ${imageryFact() || '10 m source'}`;
  return 'Cached satellite · not reconstruction';
}

/* ---------------- context terrain (30 m DEM) ---------------- */
const TM = window.TerrainMath;
const PATCH_DATUM_OFFSET = -1.6;   // the mosaic plane sits just below the DSM
const RING_SINK = 0.45;            // keep the coarse ring under the fine patch

function loadContextDem(live) {
  const url = live && live.assets && live.assets.context_dem;
  if (!url) return;
  fetch(url, { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((dem) => {
      if (!dem || !dem.heights_m || !dem.width) return;
      state.contextDem = dem;
      buildContextTerrain();
      buildRingTerrain();
    })
    .catch(() => { /* the flat plane stays; Context still works */ });
}

/**
 * The 60 km Regional layer. Independent of the local one: the wide imagery
 * arrives with the payload, the wide heightmap needs its own fetch. A failure
 * leaves Regional on the 15 km ring.
 */
function loadWideContext(live) {
  const img = live && live.imagery_wide;
  if (img && img.url && img.bbox) state.contextImageryWide = img;

  const dem = live && live.dem_wide;
  if (!dem || !dem.url || !dem.bbox) return;
  state.demWideMeta = dem;
  fetch(dem.url, { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => {
      if (!json || !json.heights_m || !json.width) return;
      state.contextDemWide = json;
      buildRingTerrainWide();
    })
    .catch(() => { /* Regional keeps the local ring */ });
}

function geometryFromGrid(grid, texRect) {
  const pos = new Float64Array(grid.vertexCount * 3);
  const st = new Float32Array(grid.vertexCount * 2);
  for (let k = 0; k < grid.vertexCount; k++) {
    const p = C.Cartesian3.fromDegrees(grid.lon[k], grid.lat[k], grid.height[k]);
    pos[k * 3] = p.x; pos[k * 3 + 1] = p.y; pos[k * 3 + 2] = p.z;
    const [t, s] = texRect
      ? texRect(grid.st[k * 2], grid.st[k * 2 + 1])
      : [grid.st[k * 2], grid.st[k * 2 + 1]];
    st[k * 2] = t; st[k * 2 + 1] = s;
  }
  return new C.Geometry({
    attributes: {
      position: new C.GeometryAttribute({
        componentDatatype: C.ComponentDatatype.DOUBLE,
        componentsPerAttribute: 3,
        values: pos,
      }),
      st: new C.GeometryAttribute({
        componentDatatype: C.ComponentDatatype.FLOAT,
        componentsPerAttribute: 2,
        values: st,
      }),
    },
    indices: new Uint32Array(grid.idx),
    primitiveType: C.PrimitiveType.TRIANGLES,
    boundingSphere: C.BoundingSphere.fromVertices(pos),
  });
}

function buildContextTerrain() {
  const dem = state.contextDem;
  const collection = landscapeTarget();
  if (!dem || !collection) return;

  const box = detailBox();
  const base = state.center.hmin + PATCH_DATUM_OFFSET;
  // Anchor relief so the DEM at the mission centre meets the existing plane:
  // the shape is real, the datum stays tied to the mission so the patch and
  // its surroundings never invert.
  const offset = TM.anchorOffset(dem, (box.west + box.east) / 2,
    (box.south + box.north) / 2, base);
  const grid = TM.fillMissing(TM.buildGrid(box, dem, 128, offset), base);

  const material = new C.Material({
    fabric: { type: 'Image', uniforms: { image: contextTexture(), color: new C.Color(1, 1, 1, 1) } },
  });
  const geometry = geometryFromGrid(grid, (u, v) => texCoordsFor(u, v, box));

  state.prims.contextTerrain = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry }),
    appearance: new C.MaterialAppearance({ material, flat: true, translucent: false }),
    asynchronous: false,
  });
  state.prims.contextTerrain.show = state.mode !== 'indonesia';
  state.contextTerrainMin = Math.min(...grid.height);
  state.contextTerrainSampler = {
    west: box.west, south: box.south, east: box.east, north: box.north,
    width: grid.nx + 1, height: grid.ny + 1, heights_m: grid.height,
  };
  collection.add(state.prims.contextTerrain);
  const centre = state.prims.landscapeImagery
    ? state.prims.landscapeCenter : state.prims.landscapeFallbackCenter;
  if (centre) centre.show = false;
}

/* ---------------- regional ring terrain (30 m DEM) ---------------- */

/**
 * Hillshade tint for the ring. The ring is a 30 m surface at 2-40 km, so a flat
 * fill would read as a coloured sheet; slope/aspect is the only honest detail
 * this resolution carries. Sun from the NW, 45° up, matching the patch.
 */
function ringShadeTexture(grid, dem) {
  const nx = grid.nx, ny = grid.ny;
  const lat = (dem.south + dem.north) / 2;
  const dx = ((dem.east - dem.west) * 111320 * Math.cos(rad(lat))) / nx;
  const dy = ((dem.north - dem.south) * 110574) / ny;
  const az = rad(315), alt = rad(45);
  const lx = Math.cos(alt) * Math.sin(az);
  const ly = Math.cos(alt) * Math.cos(az);
  const lz = Math.sin(alt);
  const canvas = document.createElement('canvas');
  canvas.width = nx;
  canvas.height = ny;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(nx, ny);
  const H = (i, j) => {
    const k = Math.min(ny, Math.max(0, j)) * (nx + 1) + Math.min(nx, Math.max(0, i));
    return grid.height[k] == null ? 0 : grid.height[k];
  };
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const dzdx = (H(i + 1, j) - H(i - 1, j)) / (2 * dx);
      const dzdy = (H(i, j - 1) - H(i, j + 1)) / (2 * dy);
      const len = Math.sqrt(dzdx * dzdx + dzdy * dzdy + 1);
      const shade = clamp((-dzdx * lx - dzdy * ly + lz) / len, 0, 1);
      const t = Math.pow(shade, 0.8);
      const p = (j * nx + i) * 4;
      img.data[p] = 38 + 176 * t;         // sage grey-green ramp, wide enough
      img.data[p + 1] = 50 + 172 * t;     // to read relief at 3 km
      img.data[p + 2] = 40 + 150 * t;
      img.data[p + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL('image/png');
}

/**
 * Build a DEM ring surface. Used twice: the local 15 km ring (hillshade) and the
 * wide 60 km ring (imagery), both cut around the detailed mosaic.
 */
function buildRingSurface({ dem, box, key, image = null, imageBox = null }) {
  const collection = landscapeTarget();
  if (!dem || !collection || state.prims[key]) return null;

  const base = state.center.hmin + PATCH_DATUM_OFFSET;
  const datum = base - RING_SINK;
  const hole = detailBox();
  const offset = TM.anchorOffset(dem, (hole.west + hole.east) / 2,
    (hole.south + hole.north) / 2, datum);
  const grid = TM.fillMissing(TM.buildGrid(box, dem, 128, offset), datum);

  // Flatten the ring under the mosaic, but not abruptly. A fixed sink is not
  // enough: coarse cells interpolate the 30 m DEM differently from the fine
  // ones, and near the shoreline the coarse surface can sit several metres
  // higher and punch through the imagery. Clamping straight to the mosaic's
  // minimum instead leaves a step at the rim that shows the background through
  // the gap. So: match the fine surface at the rim, reach the hidden floor one
  // cell in, and interpolate between.
  const sampler = state.contextTerrainSampler;
  const hidden = (state.contextTerrainMin == null ? datum : state.contextTerrainMin) - RING_SINK;
  const midLat = (hole.south + hole.north) / 2;
  const lonM = 111320 * Math.cos(rad(midLat));
  const latM = 110574;
  const cellLon = (box.east - box.west) * lonM / 128;
  const cellLat = (box.north - box.south) * latM / 128;
  const rampM = Math.min(cellLon, cellLat);
  for (let k = 0; k < grid.vertexCount; k++) {
    const lon = grid.lon[k], lat = grid.lat[k];
    if (!(lon > hole.west && lon < hole.east && lat > hole.south && lat < hole.north)) continue;
    const dM = Math.min((lon - hole.west) * lonM, (hole.east - lon) * lonM,
      (lat - hole.south) * latM, (hole.north - lat) * latM);
    const w = clamp(dM / Math.max(rampM, 1e-6), 0, 1);
    const fineH = sampler ? TM.sampleDem(sampler, lon, lat) : null;
    const rim = fineH == null ? grid.height[k] : fineH - RING_SINK;
    grid.height[k] = rim + (hidden - rim) * w;
  }

  // Cut the patch's footprint out of the ring so the two surfaces never
  // z-fight. Only cells whose four corners are all inside the (slightly
  // shrunk) mosaic are dropped: using cell centres instead would leave a gap
  // up to half a cell wide around the patch.
  const padLon = (hole.east - hole.west) * 0.02;
  const padLat = (hole.north - hole.south) * 0.02;
  const keep = [];
  for (let j = 0; j < grid.ny; j++) {
    for (let i = 0; i < grid.nx; i++) {
      const k = j * (grid.nx + 1) + i;
      const corners = [k, k + 1, k + grid.nx + 1, k + grid.nx + 2];
      const inside = corners.every((q) =>
        grid.lon[q] > hole.west + padLon && grid.lon[q] < hole.east - padLon
        && grid.lat[q] > hole.south + padLat && grid.lat[q] < hole.north - padLat);
      if (inside) continue;
      keep.push(k, k + 1, k + grid.nx + 1, k + 1, k + grid.nx + 2, k + grid.nx + 1);
    }
  }
  const ring = { ...grid, idx: keep, triangleCount: keep.length / 3 };

  const texture = image || ringShadeTexture(grid, dem);
  const material = new C.Material({
    fabric: { type: 'Image', uniforms: { image: texture, color: new C.Color(1, 1, 1, 1) } },
  });
  const geometry = geometryFromGrid(ring, image && imageBox
    ? (u, v) => texCoordsIn(u, v, box, imageBox)
    : null);

  const prim = new C.Primitive({
    geometryInstances: new C.GeometryInstance({ geometry }),
    appearance: new C.MaterialAppearance({ material, flat: true, translucent: false }),
    asynchronous: false,
  });
  prim.show = state.mode === 'context';
  state.prims[key] = prim;
  collection.add(prim);
  return prim;
}

function buildRingTerrain() {
  const dem = state.contextDem;
  if (!dem) return;
  buildRingSurface({ dem, box: dem, key: 'ringTerrain' });
  applyRingVisibility();
}

/** The 60 km Regional surface: DEM relief with the wide Sentinel-2 mosaic. */
function buildRingTerrainWide() {
  const dem = state.contextDemWide;
  const meta = state.demWideMeta;
  if (!dem || !meta || !meta.bbox) return;
  const wide = state.contextImageryWide;
  buildRingSurface({
    dem,
    box: meta.bbox,
    key: 'ringTerrainWide',
    image: wide && wide.url ? wide.url : null,
    imageBox: wide && wide.bbox ? wide.bbox : null,
  });
  applyRingVisibility();

  // The tab was opened while the wide surface was still missing, so it used the
  // fallback camera. Now that the surface exists, adopt the Regional preset —
  // but only if the user has not already moved the camera somewhere else.
  if (state.viewMode === 'regional' && state.mode === 'context'
      && state.camera.range <= 4000) {
    state.rangeLimits = modeLimits('regional');
    state.camera = modeCamera('regional');
    applyCamera();
    syncTabs();
  }
}

/** Terrain shows the local ring; Regional shows the wide one when it exists. */
function applyRingVisibility() {
  const ctx = state.mode === 'context';
  const wide = Boolean(state.prims.ringTerrainWide);
  const regional = state.viewMode === 'regional';
  if (state.prims.ringTerrain) {
    state.prims.ringTerrain.show = ctx && !(wide && regional);
  }
  if (state.prims.ringTerrainWide) {
    state.prims.ringTerrainWide.show = ctx && regional;
  }
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
const PROVIDER_ORDER = ['weather', 'regional_fires', 'context_dem', 'context_imagery',
  'context_dem_wide', 'context_imagery_wide', 'places'];

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
    // The cached envelope keeps the label it was fetched with; the wide rows
    // are named by scope so two "Sentinel-2" lines are not ambiguous.
    const label = key === 'context_dem_wide' ? 'Copernicus DEM (60 km)'
      : key === 'context_imagery_wide' ? 'Sentinel-2 (60 km)'
        : item.source_label;
    let fact = '';
    if (key === 'context_dem') fact = ' · 30 m';
    if (key === 'context_imagery') fact = ' · 10 m source';
    if (key === 'context_dem_wide') fact = ' · 60 km';
    if (key === 'context_imagery_wide') fact = ' · mosaic';
    if (item.detail) fact += ` · ${item.detail}`;
    rows.push(
      `<li class="ld-row">`
      + `<i class="ld-dot" data-status="${item.status}" data-sim="${item.simulated}"></i>`
      + `<span class="ld-name">${label}</span>`
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
  state.incident = {
    name: $('#incident-name').textContent,
    id: $('#mission-id').textContent,
    meta: $('#incident-meta').textContent,
  };
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
  $('#basemap-note').textContent = contextSourceNote();
  $('#attrib').textContent = contextAttribution();

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
  $('#zoom-in').addEventListener('click', () => {
    if (state.viewMode === 'site') {
      const cam = state.viewer.camera;
      const h = cam.positionCartographic.height;
      if (h > 1000) cam.zoomIn(Math.min(h - 800, h * 0.35));
      return;
    }
    if (state.viewMode === 'indonesia') {
      if (state.map2d) state.map2d.zoomBy(1.35);
      return;
    }
    state.camera.range = clamp(state.camera.range * 0.8, state.rangeLimits.min, state.rangeLimits.max); applyCamera(); checkZoomMode();
  });
  $('#zoom-out').addEventListener('click', () => {
    if (state.viewMode === 'site') {
      const cam = state.viewer.camera;
      const h = cam.positionCartographic.height;
      if (h < 38000) cam.zoomOut(Math.min(40000 - h, Math.max(h * 0.4, 800)));
      return;
    }
    if (state.viewMode === 'indonesia') {
      if (state.map2d) state.map2d.zoomBy(1 / 1.35);
      return;
    }
    state.camera.range = clamp(state.camera.range * 1.25, state.rangeLimits.min, state.rangeLimits.max); applyCamera(); checkZoomMode();
  });
  $('#reset').addEventListener('click', () => {
    if (state.viewMode === 'site') {
      focusSiteCamera();
      return;
    }
    if (state.viewMode === 'indonesia') {
      if (state.map2d) state.map2d.reset();
      return;
    }
    state.camera = { ...(state.mode === 'context' ? CONTEXT_CAMERA : RECON_CAMERA) };
    state.is2D = false;
    $('#toggle-2d').textContent = '2D';
    $('#app').classList.remove('is-2d');
    applyCamera();
  });
  $('#toggle-2d').addEventListener('click', () => {
    if (state.viewMode === 'indonesia' || state.viewMode === 'site') return;
    state.is2D = !state.is2D;
    const base = state.mode === 'context' ? CONTEXT_CAMERA : RECON_CAMERA;
    state.camera.pitch = state.is2D ? -89 : base.pitch;
    $('#toggle-2d').textContent = state.is2D ? '3D' : '2D';
    $('#app').classList.toggle('is-2d', state.is2D);
    applyCamera();
  });

  $$('#globe-skin button').forEach((b) => b.addEventListener('click', () => {
    setGlobeSkin(b.dataset.skin);
  }));
  const clear = $('#province-clear');
  if (clear) clear.addEventListener('click', () => clearProvinceSelection());
  const detail = $('#pp-detail');
  if (detail) detail.addEventListener('click', () => {
    if (state.selectedFeature && state.plateMeta && !state.detailMeta) {
      loadProvinceImagery(state.selectedFeature, 'detail', { fly: true });
    }
  });
  const siteBtn = $('#pp-site');
  if (siteBtn) siteBtn.addEventListener('click', openSiteFromSelection);
  const siteBack = $('#site-back');
  if (siteBack) siteBack.addEventListener('click', exitSite);
  $$('.site-scales button').forEach((b) => b.addEventListener('click',
    () => loadSiteWindow(Number(b.dataset.km))));
  const siteLayer = (id, fn) => {
    const el = $(id);
    if (el) el.addEventListener('change', () => fn(el.checked));
  };
  siteLayer('#sr-l-imagery', (on) => {
    if (state.siteImagery) state.siteImagery.show = on;
  });
  siteLayer('#sr-l-terrain', (on) => {
    state.siteExaggeration = on ? state.siteRelief : 1.0;
    if (state.viewer) {
      state.viewer.scene.globe.terrainExaggeration = state.siteExaggeration;
    }
  });
  siteLayer('#sr-l-spread', (on) => {
    if (state.siteSpreadDs) state.siteSpreadDs.show = on;
  });
  siteLayer('#sr-l-fire', (on) => {
    if (state.siteData) state.siteData.show = on;
  });
  $$('.sr-relief button').forEach((b) => b.addEventListener('click', () => {
    const x = Number(b.dataset.ex);
    state.siteRelief = x;
    state.siteExaggeration = x;
    const cb = $('#sr-l-terrain');
    if (cb) cb.checked = true;
    if (state.viewer) {
      state.viewer.scene.globe.terrainExaggeration = x;
    }
    $$('.sr-relief button').forEach((q) => {
      q.classList.toggle('active', Number(q.dataset.ex) === x);
    });
  }));
  const spreadPlay = $('#spread-play');
  if (spreadPlay) spreadPlay.addEventListener('click', () => {
    playSpread(!state.spreadPlaying);
  });
  const spreadTime = $('#spread-time');
  if (spreadTime) spreadTime.addEventListener('input', (e) => {
    playSpread(false);
    setSpreadFrame(Number(e.target.value));
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const t = e.target;
    if (t instanceof Element && t.closest('input, textarea, select')) return;
    if (state.viewMode !== 'indonesia' || !state.selectedIso) return;
    clearProvinceSelection();
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
  if (state.mode === 'indonesia') return;
  const ctx = state.mode === 'context';
  for (const [k, p] of Object.entries(state.bases)) p.show = !ctx && k === name;
  $$('input[name="base"]').forEach((r) => {
    r.checked = r.value === name;
    r.closest('.base-opt').classList.toggle('active', r.value === name);
  });
  renderLegend();
}

function setLayer(name, on) {
  if (state.mode === 'indonesia') return;
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
  if (state.mode === 'indonesia') {
    const skinLine = {
      relief: 'Relief · terrain shading',
      satellite: 'Satellite · Blue Marble 1.3 km',
      atlas: 'Atlas · paper grade',
      flat: 'Flat skin · no imagery',
    }[state.globeSkin] || 'Relief';
    let fires = 'loading…';
    if (!state.fires && state.firesReason) fires = 'unavailable';
    else if (state.fires && !state.fires.available) fires = 'unavailable';
    else if (state.fires) {
      const n = state.fires.dots ? state.fires.dots.length : 0;
      const provinces = Object.keys(state.fires.provinces || {}).length;
      fires = n ? `${n} dots · ${provinces} provinces · 5 days`
        : 'none in the last 5 days';
    }
    el.innerHTML = `
      <div class="legend-group"><div class="legend-label">Indonesia</div>
        <div class="legend-class">Province borders · OSM</div>
        <div class="legend-class">${skinLine}</div>
      </div>
      ${state.selectedFeature ? `<div class="legend-group"><div class="legend-label">Selected</div>
        <div class="legend-class">${state.selectedFeature.properties.name}</div>
        <div class="legend-class">${state.selectedFeature.properties.iso || ''}</div></div>` : ''}
      <div class="legend-group"><div class="legend-label">Fires</div>
        <div class="legend-class"><i style="background:var(--red);border-radius:50%"></i>${fires}</div>
        <div class="legend-class">NASA FIRMS NRT${state.fires && state.fires.sensors
          ? ` · ${state.fires.sensors.join(' / ')}` : ''}</div>
      </div>
      <div class="legend-group"><div class="legend-label">Next</div>
        <div class="legend-class">${state.plateMeta
          ? `Plate · ${Math.round(state.plateMeta.coverage * 100)} % · ${state.plateMeta.resolution_m} m`
            + (['atlas', 'flat'].includes(state.globeSkin)
              ? ' · hidden on this skin'
              : (state.plateMeta.coverage < 0.80
                ? ' · hidden (low coverage)' : ''))
          : 'Province imagery · pending'}</div>
      </div>`;
    return;
  }
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
        <div class="legend-class">${contextLegendLine()}</div>
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








