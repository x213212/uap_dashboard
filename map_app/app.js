"use strict";

const CONFIG = Object.freeze({
  currentManifest: "../data/derived/current_release.json",
  appConfig: "map_config.json",
  basemapManifest: "assets/basemap_manifest.json?v=20260829-3d-pyramid",
  basemapAsset: "assets/ne_110m_land.geojson",
  minZoom: 1,
  maxZoom: 262144,
  clusterDetailZoom: 128,
  maxClusterRecords: 40,
  maxTileCacheEntries: 256,
  maxEarthTileCacheEntries: 8,
  globeMinimumZoom: 0.84,
  globeMaximumZoom: 24,
  globePreviewPixels: 600,
  globeMaximumPixels: 2048,
  earthTextureOverviewWidth: 2048,
  earthTextureOverviewHeight: 1024,
  globeGlMaxDimension: 4096,
  globeTextureBudgetBytes: 201326592,
  globeMaxTiles: 28,
  globeTileConcurrency: 6,
  globeCpuMaxTiles: 8,
  globeCpuMaxLevel: 1,
  countryLabelLimit: 42,
});

const MAX_MERCATOR_LATITUDE = 85.05112878;

const numberFormatter = new Intl.NumberFormat("zh-TW");
const compactNumberFormatter = new Intl.NumberFormat("zh-TW", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const localDateFormatter = new Intl.DateTimeFormat("zh-TW", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Taipei",
});

const state = {
  manifest: null,
  mapConfig: null,
  basemapManifest: null,
  landPolygons: [],
  records: [],
  filteredRecords: [],
  clusters: [],
  sources: new Map(),
  yearMin: null,
  yearMax: null,
  unknownYearCount: 0,
  width: 0,
  height: 0,
  dpr: 1,
  view: { centerLon: 0, centerLat: 0, zoom: 1 },
  globe: { yaw: 12, pitch: 18, zoom: 1 },
  viewMode: "globe",
  globeRaster: null,
  globeGl: null,
  globeGlDisabled: false,
  landTexture: null,
  earthTexture: null,
  earthTextureLod: null,
  earthTileCache: new Map(),
  earthTileQueue: [],
  earthTileActive: 0,
  earthTileBytes: 0,
  visibleEarthTileKeys: new Set(),
  earthTextureGeneration: 0,
  earthTextureStatus: null,
  texturePackPollId: null,
  texturePackCheckedAt: 0,
  countryLayer: null,
  starfield: null,
  spaceLayer: null,
  clusterCache: null,
  filterGeneration: 0,
  pointer: null,
  hoveredCluster: null,
  drawQueued: false,
  filterDurationMs: 0,
  tileCache: new Map(),
  visibleTileKeys: new Set(),
  ready: false,
};

const dom = {};

void init();

async function init() {
  cacheDom();
  bindControls();
  observeCanvasSize();

  try {
    setLoading("讀取 release manifest", "確認目前釋出版本與地圖檔案…");
    const [manifest, basemap, mapConfig] = await Promise.all([
      fetchJson(CONFIG.currentManifest, { cache: "no-store" }),
      loadBasemap(),
      fetchJson(CONFIG.appConfig, { cache: "no-store" }),
    ]);
    validateManifest(manifest);
    validateMapConfig(mapConfig);
    state.manifest = manifest;
    state.mapConfig = mapConfig;
    state.basemapManifest = basemap.manifest;
    state.landPolygons = normalizeLandPolygons(basemap.geojson);

    setLoading("載入觀測圖層", "正在解壓目擊報告與獨立控制資料…");
    const earthTexturePromise = loadEarthTexture(basemap.manifest).catch((error) => {
      console.warn("無法載入 NASA 地球紋理，改用離線輪廓。", error);
      return null;
    });
    const earthTextureLodPromise = loadEarthTextureLod(basemap.manifest).catch((error) => {
      console.warn("無法載入 NASA 高解析地球紋理索引，改用概覽紋理。", error);
      return null;
    });
    const countryLayerPromise = loadCountryLayer(basemap.manifest).catch((error) => {
      console.warn("無法載入國家圖層，地圖將不顯示國界。", error);
      return null;
    });
    const [
      sightingCollection,
      controlCollection,
      earthTexture,
      earthTextureLod,
      countryLayer,
    ] = await Promise.all([
      loadReleaseLayer("sightings_current", "map_features/sightings_current.geojson.gz"),
      loadReleaseLayer("controls_current", "map_features/controls_current.geojson.gz"),
      earthTexturePromise,
      earthTextureLodPromise,
      countryLayerPromise,
    ]);
    state.earthTexture = earthTexture;
    state.earthTextureLod = earthTextureLod;
    state.countryLayer = countryLayer;

    state.records = [
      ...normalizeRecords(sightingCollection, "sighting"),
      ...normalizeRecords(controlCollection, "control"),
    ];
    prepareRecordMetadata();
    populateSourceFilters();
    populateReleaseInfo();
    updateBasemapUi();
    updateCountryStatus();
    updateTexturePackUi();
    updateViewModeUi();
    state.ready = true;
    dom.loadingPanel.hidden = true;
    applyFilters();
  } catch (error) {
    showFatalError(error);
  }
}

function cacheDom() {
  const ids = [
    "header-release",
    "metric-total",
    "metric-visible",
    "metric-sources",
    "reset-filters",
    "layer-sighting",
    "layer-control",
    "layer-sighting-count",
    "layer-control-count",
    "basemap-osm",
    "basemap-status",
    "layer-countries",
    "country-status",
    "texture-pack-button",
    "texture-pack-state",
    "texture-pack-panel",
    "texture-pack-command",
    "texture-pack-copy",
    "search-input",
    "year-from",
    "year-to",
    "include-unknown-year",
    "unknown-year-count",
    "toggle-sources",
    "source-filters",
    "release-id",
    "release-built-at",
    "release-versions",
    "release-current",
    "integrity-badge",
    "h3-status",
    "viewport-status",
    "filter-summary",
    "map-hint",
    "map-stage",
    "space-canvas",
    "globe-canvas",
    "map-canvas",
    "zoom-in",
    "zoom-out",
    "fit-world",
    "mode-globe",
    "mode-flat",
    "map-tooltip",
    "loading-panel",
    "loading-title",
    "loading-detail",
    "error-panel",
    "error-message",
    "detail-drawer",
    "detail-kicker",
    "detail-content",
    "close-detail",
    "render-timing",
    "osm-credit",
    "natural-earth-credit",
    "earth-texture-credit",
    "projection-credit",
  ];
  for (const id of ids) {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`頁面缺少必要元件：${id}`);
    }
    dom[toCamelCase(id)] = node;
  }
  dom.context = dom.mapCanvas.getContext("2d", { alpha: true });
  if (!dom.context) {
    throw new Error("此瀏覽器無法建立 Canvas 2D 地圖。請改用新版瀏覽器。");
  }
}

function toCamelCase(value) {
  return value.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

function bindControls() {
  const refilter = () => applyFilters();
  dom.layerSighting.addEventListener("change", refilter);
  dom.layerControl.addEventListener("change", refilter);
  dom.texturePackButton.addEventListener("click", toggleTexturePackPanel);
  dom.texturePackCopy.addEventListener("click", async () => {
    const copied = await copyText(dom.texturePackCommand.textContent);
    dom.texturePackCopy.textContent = copied ? "已複製" : "複製失敗";
    window.setTimeout(() => {
      dom.texturePackCopy.textContent = "複製指令";
    }, 1500);
  });
  dom.layerCountries.addEventListener("change", () => {
    updateCountryStatus();
    requestDraw();
  });
  dom.basemapOsm.addEventListener("change", () => {
    updateBasemapUi();
    hideTooltip();
    requestDraw();
  });
  dom.includeUnknownYear.addEventListener("change", refilter);
  dom.yearFrom.addEventListener("input", debounce(refilter, 100));
  dom.yearTo.addEventListener("input", debounce(refilter, 100));
  dom.searchInput.addEventListener("input", debounce(refilter, 120));
  dom.sourceFilters.addEventListener("change", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.dataset.sourceId) {
      updateSourceToggleLabel();
      applyFilters();
    }
  });
  dom.toggleSources.addEventListener("click", toggleAllSources);
  dom.resetFilters.addEventListener("click", resetFilters);

  dom.zoomIn.addEventListener("click", () => zoomAround(1.7));
  dom.zoomOut.addEventListener("click", () => zoomAround(1 / 1.7));
  dom.fitWorld.addEventListener("click", fitWorld);
  dom.modeGlobe.addEventListener("click", () => setViewMode("globe"));
  dom.modeFlat.addEventListener("click", () => setViewMode("flat"));
  dom.closeDetail.addEventListener("click", closeDetails);

  dom.mapCanvas.addEventListener("pointerdown", handlePointerDown);
  dom.mapCanvas.addEventListener("pointermove", handlePointerMove);
  dom.mapCanvas.addEventListener("pointerup", handlePointerUp);
  dom.mapCanvas.addEventListener("pointercancel", cancelPointer);
  dom.mapCanvas.addEventListener("pointerleave", handlePointerLeave);
  dom.mapCanvas.addEventListener("wheel", handleWheel, { passive: false });
  dom.mapCanvas.addEventListener("keydown", handleMapKeydown);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDetails();
    }
  });
}

function observeCanvasSize() {
  const resize = () => {
    const rect = dom.mapStage.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) {
      return;
    }
    state.width = rect.width;
    state.height = rect.height;
    state.dpr = Math.min(window.devicePixelRatio || 1, 2);
    dom.mapCanvas.width = Math.round(rect.width * state.dpr);
    dom.mapCanvas.height = Math.round(rect.height * state.dpr);
    dom.mapCanvas.style.width = `${rect.width}px`;
    dom.mapCanvas.style.height = `${rect.height}px`;
    dom.context.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    dom.spaceCanvas.style.width = `${rect.width}px`;
    dom.spaceCanvas.style.height = `${rect.height}px`;
    dom.globeCanvas.style.width = `${rect.width}px`;
    dom.globeCanvas.style.height = `${rect.height}px`;
    state.clusterCache = null;
    if (!isGlobeView()) clampView();
    requestDraw();
  };

  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(resize);
    observer.observe(dom.mapStage);
  } else {
    window.addEventListener("resize", resize);
  }
  resize();
}

async function loadBasemap() {
  setLoading("驗證離線底圖", "核對 Natural Earth 資產大小與 SHA-256…");
  const [manifest, response] = await Promise.all([
    fetchJson(CONFIG.basemapManifest),
    fetchAsset(CONFIG.basemapAsset),
  ]);
  if (!response.ok) {
    throw new Error(`無法讀取離線底圖（HTTP ${response.status}）。`);
  }
  const bytes = await response.arrayBuffer();
  if (Number(manifest.bytes) !== bytes.byteLength) {
    throw new Error(
      `離線底圖大小不符：預期 ${manifest.bytes} bytes，實際 ${bytes.byteLength} bytes。`,
    );
  }
  if (globalThis.crypto?.subtle && typeof manifest.sha256 === "string") {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const actual = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (actual !== manifest.sha256) {
      throw new Error("離線底圖 SHA-256 驗證失敗。");
    }
  }
  let geojson;
  try {
    geojson = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(`離線底圖不是有效的 UTF-8 GeoJSON：${error.message}`);
  }
  return { manifest, geojson };
}

async function loadEarthTexture(basemapManifest) {
  const specification = basemapManifest?.earth_texture;
  if (!specification) return null;
  if (
    !specification ||
    typeof specification !== "object" ||
    typeof specification.path !== "string" ||
    !/^[A-Za-z0-9_.-]+\.jpg$/i.test(specification.path) ||
    specification.media_type !== "image/jpeg" ||
    !Number.isInteger(specification.width) ||
    !Number.isInteger(specification.height) ||
    specification.width < 1 ||
    specification.height < 1 ||
    !Number.isInteger(specification.bytes) ||
    specification.bytes < 1 ||
    !/^[a-f0-9]{64}$/i.test(String(specification.sha256 || ""))
  ) {
    throw new Error("NASA 地球紋理的本機資產宣告無效。");
  }
  const response = await fetchAsset(assetUrl(specification.path, specification.sha256));
  if (!response.ok) {
    throw new Error(`無法讀取 NASA 地球紋理（HTTP ${response.status}）。`);
  }
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== specification.bytes) {
    throw new Error("NASA 地球紋理大小驗證失敗。");
  }
  if (globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const actual = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (actual !== specification.sha256.toLowerCase()) {
      throw new Error("NASA 地球紋理 SHA-256 驗證失敗。");
    }
  }
  const blob = new Blob([bytes], { type: specification.media_type });
  const image = await decodeImage(blob);
  const sourceWidth = Number(image.width || image.naturalWidth);
  const sourceHeight = Number(image.height || image.naturalHeight);
  if (sourceWidth !== specification.width || sourceHeight !== specification.height) {
    image.close?.();
    throw new Error("NASA 地球紋理解析度與資產宣告不符。");
  }
  const width = Math.min(sourceWidth, CONFIG.earthTextureOverviewWidth);
  const height = Math.min(sourceHeight, CONFIG.earthTextureOverviewHeight);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    image.close?.();
    throw new Error("無法建立 NASA 地球紋理的本機像素快取。");
  }
  context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, width, height);
  return {
    attribution: String(specification.attribution || "NASA Earth Observatory"),
    width: sourceWidth,
    height: sourceHeight,
    // Full-resolution source for the GPU; released once it is uploaded.
    bitmap: image,
    // Overview pixels, only read by the CPU fallback rasteriser.
    sample: {
      width,
      height,
      pixels: context.getImageData(0, 0, width, height).data,
    },
  };
}

async function loadEarthTextureLod(basemapManifest) {
  const specification = basemapManifest?.earth_texture_lod_manifest;
  if (!specification) return null;
  if (
    !specification ||
    typeof specification !== "object" ||
    typeof specification.path !== "string" ||
    !/^[A-Za-z0-9_.-]+\.json$/i.test(specification.path) ||
    !Number.isInteger(specification.bytes) ||
    specification.bytes < 1 ||
    !/^[a-f0-9]{64}$/i.test(String(specification.sha256 || ""))
  ) {
    throw new Error("NASA 高解析地球紋理索引宣告無效。");
  }
  const response = await fetchAsset(assetUrl(specification.path, specification.sha256), {
    cache: "no-cache",
  });
  if (!response.ok) {
    throw new Error(`無法讀取 NASA 高解析紋理索引（HTTP ${response.status}）。`);
  }
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== specification.bytes) {
    throw new Error("NASA 高解析紋理索引大小驗證失敗。");
  }
  if (globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const actual = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (actual !== specification.sha256.toLowerCase()) {
      throw new Error("NASA 高解析紋理索引 SHA-256 驗證失敗。");
    }
  }
  let manifest;
  try {
    manifest = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(`NASA 高解析紋理索引不是有效 JSON：${error.message}`);
  }
  return normalizeEarthTextureLod(manifest);
}

/**
 * Normalise a v1 (single level) or v2 (pyramid) LOD manifest into levels that
 * grow from coarse to fine and share one tile grid.
 */
function normalizeEarthTextureLod(manifest) {
  const columns = manifest?.columns;
  const rows = manifest?.rows;
  const schemaVersion = manifest?.schema_version;
  let rawLevels = null;
  if (schemaVersion === "uap.earth_texture_lod.v2") {
    rawLevels = manifest.levels;
  } else if (schemaVersion === "uap.earth_texture_lod.v1") {
    rawLevels = [
      {
        tile_width: manifest.tile_width,
        tile_height: manifest.tile_height,
        tiles: manifest.tiles,
      },
    ];
  }
  if (
    !Number.isInteger(columns) ||
    !Number.isInteger(rows) ||
    columns < 1 ||
    rows < 1 ||
    !Array.isArray(rawLevels) ||
    !rawLevels.length
  ) {
    throw new Error("NASA 高解析紋理索引的網格設定無效。");
  }

  const levels = [];
  for (const level of rawLevels) {
    // A level may refine the grid instead of the tile, so it carries its own
    // columns and rows and only falls back to the manifest grid.
    const levelColumns = Number.isInteger(level?.columns) ? level.columns : columns;
    const levelRows = Number.isInteger(level?.rows) ? level.rows : rows;
    const tileWidth = level?.tile_width;
    const tileHeight = level?.tile_height;
    if (
      !Number.isInteger(tileWidth) ||
      !Number.isInteger(tileHeight) ||
      tileWidth < 1 ||
      tileHeight < 1 ||
      levelColumns < 1 ||
      levelRows < 1 ||
      levelColumns * tileWidth !== 2 * levelRows * tileHeight ||
      !Array.isArray(level.tiles) ||
      level.tiles.length !== levelColumns * levelRows
    ) {
      throw new Error("NASA 高解析紋理索引的網格設定無效。");
    }
    if (
      levels.length &&
      levelColumns * tileWidth <= levels[levels.length - 1].pixelsPerDegree * 360
    ) {
      throw new Error("NASA 高解析紋理索引的層級必須由粗到細。");
    }
    const tiles = new Map();
    for (const tile of level.tiles) {
      if (
        !tile ||
        !Number.isInteger(tile.column) ||
        !Number.isInteger(tile.row) ||
        tile.column < 0 ||
        tile.column >= levelColumns ||
        tile.row < 0 ||
        tile.row >= levelRows ||
        typeof tile.path !== "string" ||
        !/^earth_lod1\/(l\d\/)?tile_\d{2}_\d{2}\.jpg$/i.test(tile.path) ||
        !Number.isInteger(tile.bytes) ||
        tile.bytes < 1 ||
        !/^[a-f0-9]{64}$/i.test(String(tile.sha256 || ""))
      ) {
        throw new Error("NASA 高解析紋理索引包含無效圖磚。");
      }
      const key = `${tile.column}/${tile.row}`;
      if (tiles.has(key)) {
        throw new Error("NASA 高解析紋理索引包含重複圖磚。");
      }
      tiles.set(key, { path: tile.path, sha256: tile.sha256 });
    }
    levels.push({
      index: levels.length,
      columns: levelColumns,
      rows: levelRows,
      tileWidth,
      tileHeight,
      pixelsPerDegree: (levelColumns * tileWidth) / 360,
      tiles,
    });
  }

  const optionalLevels = [];
  for (const optional of Array.isArray(manifest.optional_levels) ? manifest.optional_levels : []) {
    if (!optional || !Number.isInteger(optional.level)) continue;
    optionalLevels.push({
      level: optional.level,
      installed: optional.installed === true,
      label: String(optional.label || optional.pack || `level ${optional.level}`),
      pixelsPerDegree: Number(optional.pixels_per_degree) || 0,
      installCommand: String(optional.install_command || ""),
    });
  }

  const finest = levels[levels.length - 1];
  if (
    manifest.source_width !== finest.columns * finest.tileWidth ||
    manifest.source_height !== finest.rows * finest.tileHeight
  ) {
    throw new Error("NASA 高解析紋理索引的來源尺寸與網格不符。");
  }
  return { columns, rows, levels, optionalLevels };
}

/**
 * Fetch a local asset, defeating a poisoned HTTP cache entry.
 *
 * `force-cache` overrides even a hard reload, so a 404 cached while an asset
 * was missing would keep being replayed forever.  Any non-ok reply is retried
 * once straight from the network.
 */
async function fetchAsset(url, init = {}) {
  const response = await fetch(url, { cache: "force-cache", ...init });
  if (response.ok || init.cache === "reload") return response;
  return fetch(url, { ...init, cache: "reload" });
}

/** Cache-busting URL keyed by the manifest-declared digest of the asset. */
function assetUrl(relativePath, sha256) {
  const digest = String(sha256 || "").slice(0, 16);
  return digest ? `assets/${relativePath}?sha=${digest}` : `assets/${relativePath}`;
}

function decodeImage(blob) {
  if (typeof createImageBitmap === "function") {
    return createImageBitmap(blob);
  }
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(blob);
    image.addEventListener("load", () => {
      URL.revokeObjectURL(url);
      resolve(image);
    }, { once: true });
    image.addEventListener("error", () => {
      URL.revokeObjectURL(url);
      reject(new Error("瀏覽器無法解碼 NASA 地球紋理。"));
    }, { once: true });
    image.src = url;
  });
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`無法讀取 ${path}（HTTP ${response.status}）。`);
  }

  const isGzipPath = new URL(response.url).pathname.endsWith(".gz");
  const isEncodedByServer = response.headers.get("content-encoding")
    ?.toLowerCase()
    .includes("gzip");
  try {
    if (isGzipPath && !isEncodedByServer) {
      if (!("DecompressionStream" in window)) {
        throw new Error("瀏覽器不支援 gzip 解壓；請使用 serve_map.py 啟動地圖。");
      }
      const decompressed = response.body.pipeThrough(new DecompressionStream("gzip"));
      return await new Response(decompressed).json();
    }
    return await response.json();
  } catch (error) {
    throw new Error(`無法解析 ${path}：${error.message}`);
  }
}

function validateManifest(manifest) {
  if (!manifest || manifest.schema_version !== "uap.map_release.v1") {
    throw new Error("current_release.json 不是支援的 uap.map_release.v1。");
  }
  if (
    typeof manifest.release_id !== "string" ||
    !/^[A-Za-z0-9_.-]+$/.test(manifest.release_id)
  ) {
    throw new Error("release_id 缺失或含有不安全字元。");
  }
  if (!manifest.map_features || typeof manifest.map_features !== "object") {
    throw new Error("release manifest 缺少 map_features 計數。");
  }
}

function validateMapConfig(config) {
  if (!config || config.schema_version !== "uap.map_app_config.v1") {
    throw new Error("map_config.json 不是支援的 uap.map_app_config.v1。");
  }
  const basemap = config.basemaps?.[config.default_basemap];
  if (!basemap || typeof basemap.tile_url_template !== "string") {
    throw new Error("map_config.json 缺少預設底圖 tile_url_template。");
  }
  const template = basemap.tile_url_template;
  if (!template.startsWith("https://") || !["{z}", "{x}", "{y}"].every((key) => template.includes(key))) {
    throw new Error("OpenStreetMap tile URL 必須使用 HTTPS 並包含 {z}/{x}/{y}。");
  }
  if (basemap.prefetch !== false || basemap.offline_download !== false) {
    throw new Error("公開 OSM tile 服務不得啟用 prefetch 或離線下載。");
  }
  if (basemap.network_mode !== "visible_viewport_only") {
    throw new Error("公開 OSM tile 服務只允許 visible_viewport_only 模式。");
  }
}

async function loadReleaseLayer(key, fallbackPath) {
  const path = releaseArtifactUrl(key, fallbackPath);
  const collection = await fetchJson(path);
  if (!collection || collection.type !== "FeatureCollection" || !Array.isArray(collection.features)) {
    throw new Error(`${key} 不是有效的 GeoJSON FeatureCollection。`);
  }
  const expected = Number(
    state.manifest.map_artifacts?.[key]?.feature_count ?? state.manifest.map_features?.[key],
  );
  if (Number.isFinite(expected) && collection.features.length !== expected) {
    throw new Error(
      `${key} 筆數不符：manifest=${expected}，GeoJSON=${collection.features.length}。`,
    );
  }
  return collection;
}

function releaseArtifactUrl(key, fallbackPath) {
  const configured = state.manifest.map_artifacts?.[key]?.path;
  const relativePath = typeof configured === "string" ? configured : fallbackPath;
  const segments = relativePath.split("/");
  if (
    relativePath.startsWith("/") ||
    segments.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new Error(`release artifact 路徑不安全：${relativePath}`);
  }
  const encodedRelease = encodeURIComponent(state.manifest.release_id);
  const encodedPath = segments.map((segment) => encodeURIComponent(segment)).join("/");
  return `../data/derived/releases/${encodedRelease}/${encodedPath}`;
}

function normalizeLandPolygons(collection) {
  if (!collection || collection.type !== "FeatureCollection" || !Array.isArray(collection.features)) {
    throw new Error("Natural Earth 底圖不是有效的 FeatureCollection。");
  }
  const polygons = [];
  for (const feature of collection.features) {
    const geometry = feature?.geometry;
    if (!geometry) {
      continue;
    }
    const coordinateSets =
      geometry.type === "Polygon"
        ? [geometry.coordinates]
        : geometry.type === "MultiPolygon"
          ? geometry.coordinates
          : [];
    for (const polygon of coordinateSets) {
      const rings = polygon
        .filter((ring) => Array.isArray(ring) && ring.length >= 4)
        .map(unwrapLongitudeRing);
      if (rings.length) {
        polygons.push(rings);
      }
    }
  }
  if (!polygons.length) {
    throw new Error("Natural Earth 底圖沒有可繪製的陸地 polygon。");
  }
  return polygons;
}

function unwrapLongitudeRing(ring) {
  const result = [];
  let previous = null;
  for (const coordinate of ring) {
    if (!Array.isArray(coordinate) || coordinate.length < 2) {
      continue;
    }
    let lon = Number(coordinate[0]);
    const lat = Number(coordinate[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
      continue;
    }
    if (previous !== null) {
      while (lon - previous > 180) lon -= 360;
      while (lon - previous < -180) lon += 360;
    }
    result.push([lon, lat]);
    previous = lon;
  }
  return result;
}

function normalizeRecords(collection, fallbackLayer) {
  const records = [];
  for (const feature of collection.features) {
    const coordinates = feature?.geometry?.coordinates;
    const properties = feature?.properties;
    if (
      feature?.geometry?.type !== "Point" ||
      !Array.isArray(coordinates) ||
      coordinates.length < 2 ||
      !properties ||
      typeof properties !== "object"
    ) {
      continue;
    }
    const lon = Number(coordinates[0]);
    const lat = Number(coordinates[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < -180 || lon > 180 || lat < -90 || lat > 90) {
      continue;
    }
    const layer = properties.record_role === "sighting" ? "sighting" : fallbackLayer;
    const observedAt = stringValue(properties.observed_at_start);
    const yearMatch = observedAt.match(/^(\d{4})/);
    const year = yearMatch ? Number(yearMatch[1]) : null;
    const source = stringValue(properties.source_id) || "unknown_source";
    const searchable = [
      properties.title,
      properties.location_name,
      properties.country_code,
      properties.source_record_id,
      properties.source_id,
      properties.record_type,
      properties.status,
      properties.summary,
      properties.explanation,
      properties.country_iso_a2,
      countryDisplayName(stringValue(properties.country_iso_a2)),
    ]
      .map(stringValue)
      .join(" ")
      .normalize("NFKC")
      .toLocaleLowerCase("zh-Hant");
    records.push({
      id: stringValue(feature.id || properties.observation_id),
      lon,
      lat,
      year: Number.isFinite(year) ? year : null,
      source,
      layer,
      searchable,
      properties,
    });
  }
  return records;
}

function stringValue(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function prepareRecordMetadata() {
  const years = [];
  const layerCounts = { sighting: 0, control: 0 };
  state.sources.clear();
  state.unknownYearCount = 0;

  for (const record of state.records) {
    layerCounts[record.layer] += 1;
    state.sources.set(record.source, (state.sources.get(record.source) || 0) + 1);
    if (record.year === null) {
      state.unknownYearCount += 1;
    } else {
      years.push(record.year);
    }
  }

  state.yearMin = years.length ? Math.min(...years) : null;
  state.yearMax = years.length ? Math.max(...years) : null;
  dom.yearFrom.value = state.yearMin ?? "";
  dom.yearTo.value = state.yearMax ?? "";
  if (state.yearMin !== null && state.yearMax !== null) {
    dom.yearFrom.min = String(state.yearMin);
    dom.yearFrom.max = String(state.yearMax);
    dom.yearTo.min = String(state.yearMin);
    dom.yearTo.max = String(state.yearMax);
  }

  dom.layerSightingCount.textContent = numberFormatter.format(layerCounts.sighting);
  dom.layerControlCount.textContent = numberFormatter.format(layerCounts.control);
  dom.unknownYearCount.textContent = numberFormatter.format(state.unknownYearCount);
  dom.metricTotal.textContent = numberFormatter.format(state.records.length);
  dom.metricSources.textContent = numberFormatter.format(state.sources.size);
}

function populateSourceFilters() {
  dom.sourceFilters.replaceChildren();
  const entries = [...state.sources.entries()].sort((left, right) => right[1] - left[1]);
  for (const [sourceId, count] of entries) {
    const label = createElement("label", "source-option");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.dataset.sourceId = sourceId;
    input.setAttribute("aria-label", `${sourceDisplayName(sourceId)} ${numberFormatter.format(count)} 筆`);
    const name = createElement("span", "source-name", sourceDisplayName(sourceId));
    const countNode = createElement("span", "source-count", numberFormatter.format(count));
    label.append(input, name, countNode);
    dom.sourceFilters.append(label);
  }
  updateSourceToggleLabel();
}

function sourceDisplayName(sourceId) {
  const known = {
    uapdrop: "UAPDrop",
    nasa_fireball: "NASA Fireball",
  };
  return known[sourceId] || sourceId.replaceAll("_", " ");
}

function populateReleaseInfo() {
  const manifest = state.manifest;
  dom.headerRelease.textContent = manifest.release_id;
  dom.releaseId.textContent = manifest.release_id;
  dom.releaseBuiltAt.textContent = formatBuildTime(manifest.built_at);
  dom.releaseVersions.textContent = numberFormatter.format(manifest.observation_version_count || 0);
  dom.releaseCurrent.textContent = numberFormatter.format(manifest.observation_current_count || 0);
  dom.integrityBadge.textContent = "計數一致";
  dom.integrityBadge.title = "地圖檔 FeatureCollection 筆數與 release manifest 相符；伺服器啟動檢查另驗 SHA-256。";

  if (manifest.h3?.computed) {
    dom.h3Status.textContent = "H3 聚合層已建立；目前畫面仍採用即時視窗群集。";
  } else {
    dom.h3Status.textContent = "H3 聚合尚未建立；目前使用瀏覽器視窗群集，不能當固定統計網格。";
  }
}

function formatBuildTime(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? stringValue(value) || "未知" : localDateFormatter.format(parsed);
}

function setLoading(title, detail) {
  dom.loadingTitle.textContent = title;
  dom.loadingDetail.textContent = detail;
}

function showFatalError(error) {
  console.error(error);
  state.ready = false;
  dom.loadingPanel.hidden = true;
  dom.errorPanel.hidden = false;
  dom.errorMessage.textContent = error instanceof Error ? error.message : String(error);
  dom.integrityBadge.textContent = "驗證失敗";
}

function selectedSources() {
  return new Set(
    [...dom.sourceFilters.querySelectorAll("input[data-source-id]:checked")].map(
      (input) => input.dataset.sourceId,
    ),
  );
}

function applyFilters() {
  if (!state.ready) {
    return;
  }
  const startedAt = performance.now();
  const sources = selectedSources();
  const query = dom.searchInput.value
    .trim()
    .normalize("NFKC")
    .toLocaleLowerCase("zh-Hant");
  const rawFrom = dom.yearFrom.value.trim() ? Number(dom.yearFrom.value) : Number.NaN;
  const rawTo = dom.yearTo.value.trim() ? Number(dom.yearTo.value) : Number.NaN;
  const from = Number.isFinite(rawFrom) ? rawFrom : state.yearMin;
  const to = Number.isFinite(rawTo) ? rawTo : state.yearMax;
  const yearLow = from === null || to === null ? null : Math.min(from, to);
  const yearHigh = from === null || to === null ? null : Math.max(from, to);
  const includeUnknown = dom.includeUnknownYear.checked;
  const showSightings = dom.layerSighting.checked;
  const showControls = dom.layerControl.checked;

  state.filteredRecords = state.records.filter((record) => {
    if ((record.layer === "sighting" && !showSightings) || (record.layer === "control" && !showControls)) {
      return false;
    }
    if (!sources.has(record.source)) {
      return false;
    }
    if (record.year === null) {
      if (!includeUnknown) return false;
    } else if (
      (yearLow !== null && record.year < yearLow) ||
      (yearHigh !== null && record.year > yearHigh)
    ) {
      return false;
    }
    return !query || record.searchable.includes(query);
  });

  state.filterGeneration += 1;
  state.filterDurationMs = performance.now() - startedAt;
  dom.metricVisible.textContent = numberFormatter.format(state.filteredRecords.length);
  const summary = [];
  if (yearLow !== null && yearHigh !== null) summary.push(`${yearLow}–${yearHigh}`);
  if (includeUnknown) summary.push("含日期不明");
  if (query) summary.push(`搜尋「${dom.searchInput.value.trim()}」`);
  summary.push(`${sources.size}/${state.sources.size} 個來源`);
  dom.filterSummary.textContent = summary.join(" · ");
  requestDraw();
}

function resetFilters() {
  dom.layerSighting.checked = true;
  dom.layerControl.checked = true;
  dom.searchInput.value = "";
  dom.yearFrom.value = state.yearMin ?? "";
  dom.yearTo.value = state.yearMax ?? "";
  dom.includeUnknownYear.checked = true;
  for (const input of dom.sourceFilters.querySelectorAll("input[data-source-id]")) {
    input.checked = true;
  }
  updateSourceToggleLabel();
  closeDetails();
  applyFilters();
}

function toggleAllSources() {
  const inputs = [...dom.sourceFilters.querySelectorAll("input[data-source-id]")];
  const shouldEnable = inputs.some((input) => !input.checked);
  for (const input of inputs) {
    input.checked = shouldEnable;
  }
  updateSourceToggleLabel();
  applyFilters();
}

function updateSourceToggleLabel() {
  const inputs = [...dom.sourceFilters.querySelectorAll("input[data-source-id]")];
  dom.toggleSources.textContent = inputs.length && inputs.every((input) => input.checked)
    ? "全部關閉"
    : "全部開啟";
}

function longitudeToWorldX(longitude) {
  return (longitude + 180) / 360;
}

function latitudeToWorldY(latitude) {
  const clipped = clamp(latitude, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE);
  const sine = Math.sin((clipped * Math.PI) / 180);
  return 0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI);
}

function worldXToLongitude(worldX) {
  return normalizeLongitude(worldX * 360 - 180);
}

function worldYToLatitude(worldY) {
  const latitude = (Math.atan(Math.sinh(Math.PI * (1 - 2 * worldY))) * 180) / Math.PI;
  return clamp(latitude, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE);
}

function normalizeLongitude(longitude) {
  return ((longitude + 180) % 360 + 360) % 360 - 180;
}

function mapWorldSize() {
  const fittedWorld = Math.max(state.width * 0.94, state.height * 0.94, 256);
  return fittedWorld * state.view.zoom;
}

function centerWorld() {
  return {
    x: longitudeToWorldX(state.view.centerLon),
    y: latitudeToWorldY(state.view.centerLat),
  };
}

function project(lon, lat) {
  const center = centerWorld();
  let deltaX = longitudeToWorldX(lon) - center.x;
  deltaX -= Math.round(deltaX);
  return [
    state.width / 2 + deltaX * mapWorldSize(),
    state.height / 2 + (latitudeToWorldY(lat) - center.y) * mapWorldSize(),
  ];
}

function projectUnwrapped(lon, lat) {
  const center = centerWorld();
  return [
    state.width / 2 + (longitudeToWorldX(lon) - center.x) * mapWorldSize(),
    state.height / 2 + (latitudeToWorldY(lat) - center.y) * mapWorldSize(),
  ];
}

function screenToWorld(x, y) {
  const center = centerWorld();
  const size = mapWorldSize();
  return {
    x: center.x + (x - state.width / 2) / size,
    y: center.y + (y - state.height / 2) / size,
  };
}

function unproject(x, y) {
  const world = screenToWorld(x, y);
  return {
    lon: worldXToLongitude(world.x),
    lat: worldYToLatitude(world.y),
  };
}

function clampView() {
  state.view.centerLon = normalizeLongitude(state.view.centerLon);
  const halfWorldHeight = state.height / (2 * mapWorldSize());
  let centerY = latitudeToWorldY(state.view.centerLat);
  centerY = halfWorldHeight >= 0.5 ? 0.5 : clamp(centerY, halfWorldHeight, 1 - halfWorldHeight);
  state.view.centerLat = worldYToLatitude(centerY);
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function isGlobeView() {
  return state.viewMode === "globe";
}

function setViewMode(mode) {
  if (mode !== "globe" && mode !== "flat") return;
  if (state.viewMode === mode) return;
  state.viewMode = mode;
  closeDetails();
  hideTooltip();
  updateBasemapUi();
  updateViewModeUi();
  requestDraw();
}

function updateViewModeUi() {
  const globe = isGlobeView();
  dom.modeGlobe.classList.toggle("active", globe);
  dom.modeFlat.classList.toggle("active", !globe);
  dom.modeGlobe.setAttribute("aria-pressed", String(globe));
  dom.modeFlat.setAttribute("aria-pressed", String(!globe));
  dom.mapHint.textContent = globe
    ? "拖曳旋轉地球 · 滾輪近距離檢視真彩色紋理 · 點擊群集深入"
    : "拖曳平移 · 滾輪縮放 · 點擊群集深入";
  dom.projectionCredit.textContent = globe
    ? state.earthTexture
      ? "投影：3D orthographic globe · NASA 真彩色地表紋理"
      : "投影：3D orthographic globe · Natural Earth 離線輪廓"
    : "投影：Web Mercator · 顯示座標為來源公開位置";
}

function globeCenter() {
  return { x: state.width / 2, y: state.height / 2 };
}

function globeRadius() {
  const minimumDimension = Math.min(state.width, state.height);
  return Math.max(80, minimumDimension * 0.39 * state.globe.zoom);
}

function fitWorld() {
  if (isGlobeView()) {
    state.globe = { yaw: 12, pitch: 18, zoom: 1 };
  } else {
    state.view = { centerLon: 0, centerLat: 0, zoom: 1 };
  }
  hideTooltip();
  requestDraw();
}

function zoomAround(factor, x = state.width / 2, y = state.height / 2) {
  if (isGlobeView()) {
    const nextZoom = clamp(
      state.globe.zoom * factor,
      CONFIG.globeMinimumZoom,
      CONFIG.globeMaximumZoom,
    );
    if (Math.abs(nextZoom - state.globe.zoom) < 0.0001) return;
    state.globe.zoom = nextZoom;
    hideTooltip();
    requestDraw();
    return;
  }
  const before = screenToWorld(x, y);
  const nextZoom = clamp(state.view.zoom * factor, CONFIG.minZoom, CONFIG.maxZoom);
  if (Math.abs(nextZoom - state.view.zoom) < 0.0001) {
    return;
  }
  state.view.zoom = nextZoom;
  const size = mapWorldSize();
  const centerX = before.x - (x - state.width / 2) / size;
  const centerY = before.y - (y - state.height / 2) / size;
  state.view.centerLon = worldXToLongitude(centerX);
  state.view.centerLat = worldYToLatitude(centerY);
  clampView();
  hideTooltip();
  requestDraw();
}

function requestDraw() {
  if (state.drawQueued || !state.ready || !state.width || !state.height) {
    return;
  }
  state.drawQueued = true;
  requestAnimationFrame(() => {
    state.drawQueued = false;
    drawMap();
  });
}

function makeSeededRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function ensureStarfield() {
  const width = Math.max(1, Math.round(state.width));
  const height = Math.max(1, Math.round(state.height));
  if (state.starfield?.width === width && state.starfield?.height === height) {
    return state.starfield;
  }
  const random = makeSeededRandom(width * 92821 + height * 68917 + 17);
  const count = clamp(Math.round((width * height) / 5600), 110, 280);
  const stars = [];
  for (let index = 0; index < count; index += 1) {
    const brightness = 0.22 + random() * 0.7;
    stars.push({
      x: random() * width,
      y: random() * height,
      radius: random() < 0.08 ? 1.3 + random() * 0.75 : 0.35 + random() * 0.85,
      brightness,
      blue: 210 + Math.round(random() * 45),
      red: 180 + Math.round(random() * 75),
    });
  }
  state.starfield = { width, height, stars };
  return state.starfield;
}

/** The starfield only depends on the stage size, so it lives on its own layer. */
function renderSpaceLayer() {
  const canvas = dom.spaceCanvas;
  const width = Math.max(1, Math.round(state.width * state.dpr));
  const height = Math.max(1, Math.round(state.height * state.dpr));
  if (state.spaceLayer?.width === width && state.spaceLayer?.height === height) {
    return;
  }
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  drawUniverse(context);
  state.spaceLayer = { width, height };
}

function drawUniverse(context) {
  const starfield = ensureStarfield();
  context.save();
  const space = context.createLinearGradient(0, 0, state.width, state.height);
  space.addColorStop(0, "#020611");
  space.addColorStop(0.48, "#071325");
  space.addColorStop(1, "#01040b");
  context.fillStyle = space;
  context.fillRect(0, 0, state.width, state.height);

  const nebula = context.createRadialGradient(
    state.width * 0.16,
    state.height * 0.28,
    0,
    state.width * 0.16,
    state.height * 0.28,
    Math.max(state.width, state.height) * 0.66,
  );
  nebula.addColorStop(0, "rgba(31, 99, 143, 0.15)");
  nebula.addColorStop(0.42, "rgba(46, 58, 127, 0.065)");
  nebula.addColorStop(1, "rgba(0, 0, 0, 0)");
  context.fillStyle = nebula;
  context.fillRect(0, 0, state.width, state.height);

  for (const star of starfield.stars) {
    context.fillStyle = `rgba(${star.red}, ${star.blue}, 255, ${star.brightness})`;
    context.beginPath();
    context.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
}

/** Clusters only change with the filter set and the camera, not with hover. */
function cachedClusters() {
  const key = isGlobeView()
    ? `globe|${state.filterGeneration}|${state.globe.yaw.toFixed(4)}|${state.globe.pitch.toFixed(4)}|${state.globe.zoom.toFixed(5)}`
    : `flat|${state.filterGeneration}|${state.view.centerLon.toFixed(6)}|${state.view.centerLat.toFixed(6)}|${state.view.zoom.toFixed(5)}`;
  const sized = `${key}|${Math.round(state.width)}x${Math.round(state.height)}`;
  if (state.clusterCache?.key === sized) return state.clusterCache.value;
  const value = isGlobeView() ? clusterGlobeRecords() : clusterVisibleRecords();
  state.clusterCache = { key: sized, value };
  return value;
}

function earthTextureSummary() {
  const status = state.earthTextureStatus;
  if (!status) return "";
  const resolution = Math.round(status.pixelsPerDegree);
  const level = status.level === null ? "概覽" : `L${status.level}`;
  if (status.demand <= status.pixelsPerDegree * 1.05) {
    return ` · 紋理 ${level} ${resolution}px/°`;
  }
  // Say a sharper pack exists rather than let the view look like the ceiling.
  const pack = (state.earthTextureLod?.optionalLevels || []).find(
    (entry) => !entry.installed && entry.pixelsPerDegree > status.pixelsPerDegree,
  );
  if (pack) void refreshEarthTextureLod().then((changed) => changed && updateTexturePackUi());
  const magnification = (status.demand / status.pixelsPerDegree).toFixed(1);
  const offer = pack
    ? `，安裝 ${pack.label} 可達 ${Math.round(pack.pixelsPerDegree)}px/°`
    : "";
  return ` · 紋理 ${level} ${resolution}px/°（放大 ${magnification}×${offer}）`;
}

function drawMap() {
  const startedAt = performance.now();
  const context = dom.context;
  context.clearRect(0, 0, state.width, state.height);
  const globe = isGlobeView();
  dom.spaceCanvas.hidden = !globe;
  if (!globe) dom.globeCanvas.hidden = true;

  if (globe) {
    renderSpaceLayer();
    const globeResult = drawGlobe(context);
    state.clusters = globeResult.clusters;
    for (const cluster of globeResult.clusters) {
      drawCluster(context, cluster, cluster === state.hoveredCluster);
    }
    drawGlobeCountryLabels(context, globeCenter(), globeRadius());
    const elapsed = performance.now() - startedAt;
    dom.viewportStatus.textContent = `${numberFormatter.format(globeResult.viewportCount)} 個前半球點位 · ${numberFormatter.format(globeResult.clusters.length)} 個畫面群集 · 3D ${state.globe.zoom.toFixed(2)}×${earthTextureSummary()}`;
    dom.renderTiming.textContent = `filter ${state.filterDurationMs.toFixed(1)} ms · render ${elapsed.toFixed(1)} ms`;
    return;
  }

  drawGraticule(context);
  drawLand(context);
  const tileStats = dom.basemapOsm.checked ? drawOsmTiles(context) : null;
  updateBasemapStatus(tileStats);
  drawFlatCountries(context);

  const { clusters, viewportCount } = cachedClusters();
  state.clusters = clusters;
  for (const cluster of clusters) {
    drawCluster(context, cluster, cluster === state.hoveredCluster);
  }
  drawFlatCountryLabels(context);

  const elapsed = performance.now() - startedAt;
  dom.viewportStatus.textContent = `${numberFormatter.format(viewportCount)} 個可見點位 · ${numberFormatter.format(clusters.length)} 個畫面群集 · ${state.view.zoom.toFixed(1)}×`;
  dom.renderTiming.textContent = `filter ${state.filterDurationMs.toFixed(1)} ms · render ${elapsed.toFixed(1)} ms`;
}

function drawGraticule(context) {
  context.save();
  context.lineWidth = 1;
  context.strokeStyle = "rgba(124, 179, 192, 0.09)";
  context.beginPath();
  for (let lon = -180; lon <= 180; lon += 30) {
    const [x] = project(lon, state.view.centerLat);
    context.moveTo(x, 0);
    context.lineTo(x, state.height);
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const [, y] = project(state.view.centerLon, lat);
    context.moveTo(0, y);
    context.lineTo(state.width, y);
  }
  context.stroke();

  const [, equatorY] = project(state.view.centerLon, 0);
  context.strokeStyle = "rgba(124, 179, 192, 0.15)";
  context.beginPath();
  context.moveTo(0, equatorY);
  context.lineTo(state.width, equatorY);
  context.stroke();
  context.restore();
}

function drawLand(context) {
  context.save();
  context.fillStyle = "rgba(19, 48, 58, 0.9)";
  context.strokeStyle = "rgba(129, 184, 194, 0.32)";
  context.lineWidth = state.view.zoom >= 5 ? 0.8 : 0.55;

  for (const polygon of state.landPolygons) {
    for (const longitudeOffset of [-360, 0, 360]) {
      context.beginPath();
      let drawable = false;
      for (const ring of polygon) {
        if (!ring.length) continue;
        const first = projectUnwrapped(ring[0][0] + longitudeOffset, ring[0][1]);
        context.moveTo(first[0], first[1]);
        for (let index = 1; index < ring.length; index += 1) {
          const point = projectUnwrapped(ring[index][0] + longitudeOffset, ring[index][1]);
          context.lineTo(point[0], point[1]);
        }
        context.closePath();
        drawable = true;
      }
      if (drawable) {
        context.fill("evenodd");
        context.stroke();
      }
    }
  }
  context.restore();
}

function degreesToRadians(value) {
  return (value * Math.PI) / 180;
}

function vectorFromLongitudeLatitude(longitude, latitude) {
  const lon = degreesToRadians(longitude);
  const lat = degreesToRadians(latitude);
  const cosineLatitude = Math.cos(lat);
  return [
    cosineLatitude * Math.sin(lon),
    Math.sin(lat),
    cosineLatitude * Math.cos(lon),
  ];
}

function globeRotation() {
  const yaw = degreesToRadians(state.globe.yaw);
  const pitch = degreesToRadians(state.globe.pitch);
  return {
    cosinePitch: Math.cos(pitch),
    sinePitch: Math.sin(pitch),
    cosineYaw: Math.cos(yaw),
    sineYaw: Math.sin(yaw),
  };
}

function cameraToWorldVector(x, y, z, rotation = globeRotation()) {
  const pitchedY = y * rotation.cosinePitch + z * rotation.sinePitch;
  const pitchedZ = -y * rotation.sinePitch + z * rotation.cosinePitch;
  return [
    x * rotation.cosineYaw + pitchedZ * rotation.sineYaw,
    pitchedY,
    -x * rotation.sineYaw + pitchedZ * rotation.cosineYaw,
  ];
}

function worldToCameraVector(x, y, z, rotation = globeRotation()) {
  const yawedX = x * rotation.cosineYaw - z * rotation.sineYaw;
  const yawedZ = x * rotation.sineYaw + z * rotation.cosineYaw;
  return [
    yawedX,
    y * rotation.cosinePitch - yawedZ * rotation.sinePitch,
    y * rotation.sinePitch + yawedZ * rotation.cosinePitch,
  ];
}

function projectGlobe(longitude, latitude, rotation = globeRotation(), center = globeCenter(), radius = globeRadius()) {
  const vector = vectorFromLongitudeLatitude(longitude, latitude);
  const camera = worldToCameraVector(vector[0], vector[1], vector[2], rotation);
  return {
    x: center.x + camera[0] * radius,
    y: center.y - camera[1] * radius,
    z: camera[2],
  };
}

// ---------------------------------------------------------------------------
// 3D globe surface.
//
// The surface is rasterised by the GPU (WebGL2) at device-pixel resolution and
// textured from the local Blue Marble pyramid.  One level is chosen per frame
// from the on-screen pixels-per-degree demand, so zooming keeps sampling a
// texture at or above screen resolution instead of magnifying the overview
// image.  A CPU rasteriser stays as the fallback for browsers without WebGL2.
// ---------------------------------------------------------------------------

const GLOBE_VERTEX_SHADER = `#version 300 es
in vec2 aGrid;
uniform vec2 uLongitude;
uniform vec2 uLatitude;
uniform vec4 uUvRect;
uniform mat3 uRotation;
uniform vec2 uCenter;
uniform vec2 uViewport;
uniform float uRadius;
uniform float uDepthBias;
out vec2 vUv;
out vec3 vCamera;
void main() {
  float lon = radians(uLongitude.x + aGrid.x * uLongitude.y);
  float lat = radians(uLatitude.x + aGrid.y * uLatitude.y);
  float cosineLatitude = cos(lat);
  vec3 world = vec3(cosineLatitude * sin(lon), sin(lat), cosineLatitude * cos(lon));
  vec3 camera = uRotation * world;
  vCamera = camera;
  vUv = uUvRect.xy + aGrid * uUvRect.zw;
  vec2 screen = vec2(uCenter.x + camera.x * uRadius, uCenter.y - camera.y * uRadius);
  vec2 ndc = vec2(screen.x / uViewport.x * 2.0 - 1.0, 1.0 - screen.y / uViewport.y * 2.0);
  // Half the depth range: the sub-camera point sits at camera.z = 1, so a raw
  // -camera.z plus a level bias would fall outside NDC and clip the sharpest
  // tile away exactly at the centre of the screen.
  gl_Position = vec4(ndc, (-camera.z + uDepthBias) * 0.5, 1.0);
}`;

const GLOBE_FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec2 vUv;
in vec3 vCamera;
uniform sampler2D uTexture;
uniform float uBlendOcean;
out vec4 fragColor;
void main() {
  vec3 camera = normalize(vCamera);
  if (camera.z <= 0.0) discard;
  vec4 texel = texture(uTexture, vUv);
  vec3 base = texel.rgb;
  if (uBlendOcean > 0.5) {
    vec3 ocean = vec3(8.0 + 8.0 * camera.z, 52.0 + 34.0 * camera.z, 76.0 + 35.0 * camera.z) / 255.0;
    base = mix(ocean, texel.rgb, texel.a);
  }
  float light = clamp(
    0.4 + 0.6 * (camera.z * 0.78 - camera.x * 0.28 + camera.y * 0.2),
    0.22,
    1.0
  );
  fragColor = vec4(base * light, 1.0);
}`;

const GLOBE_UNIFORM_NAMES = [
  "uLongitude",
  "uLatitude",
  "uUvRect",
  "uRotation",
  "uCenter",
  "uViewport",
  "uRadius",
  "uDepthBias",
  "uTexture",
  "uBlendOcean",
];

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`地球著色器編譯失敗：${log}`);
  }
  return shader;
}

function createGlobeProgram(gl) {
  const vertex = compileShader(gl, gl.VERTEX_SHADER, GLOBE_VERTEX_SHADER);
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, GLOBE_FRAGMENT_SHADER);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.bindAttribLocation(program, 0, "aGrid");
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`地球著色器連結失敗：${log}`);
  }
  return program;
}

function createGlobeMesh(gl, columns, rows) {
  const vertices = new Float32Array((columns + 1) * (rows + 1) * 2);
  let offset = 0;
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      vertices[offset] = column / columns;
      vertices[offset + 1] = row / rows;
      offset += 2;
    }
  }
  const indices = new Uint32Array(columns * rows * 6);
  let indexOffset = 0;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const topLeft = row * (columns + 1) + column;
      const topRight = topLeft + 1;
      const bottomLeft = topLeft + columns + 1;
      const bottomRight = bottomLeft + 1;
      indices[indexOffset] = topLeft;
      indices[indexOffset + 1] = bottomLeft;
      indices[indexOffset + 2] = topRight;
      indices[indexOffset + 3] = topRight;
      indices[indexOffset + 4] = bottomLeft;
      indices[indexOffset + 5] = bottomRight;
      indexOffset += 6;
    }
  }
  const vertexArray = gl.createVertexArray();
  gl.bindVertexArray(vertexArray);
  const vertexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
  gl.bindVertexArray(null);
  return { vertexArray, count: indices.length };
}

function ensureGlobeRenderer() {
  if (state.globeGl) return state.globeGl;
  if (state.globeGlDisabled) return null;
  const canvas = dom.globeCanvas;
  const gl = canvas.getContext("webgl2", {
    alpha: true,
    antialias: true,
    depth: true,
    premultipliedAlpha: true,
    preserveDrawingBuffer: false,
    powerPreference: "high-performance",
  });
  if (!gl) {
    state.globeGlDisabled = true;
    canvas.hidden = true;
    return null;
  }
  try {
    const program = createGlobeProgram(gl);
    const uniforms = {};
    for (const name of GLOBE_UNIFORM_NAMES) {
      uniforms[name] = gl.getUniformLocation(program, name);
    }
    const anisotropic =
      gl.getExtension("EXT_texture_filter_anisotropic") ||
      gl.getExtension("WEBKIT_EXT_texture_filter_anisotropic");
    state.globeGl = {
      gl,
      program,
      uniforms,
      anisotropic,
      maxAnisotropy: anisotropic
        ? Math.min(8, gl.getParameter(anisotropic.MAX_TEXTURE_MAX_ANISOTROPY_EXT))
        : 0,
      maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
      maxDimension: Math.min(
        CONFIG.globeGlMaxDimension,
        gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
      ),
      baseMesh: createGlobeMesh(gl, 192, 96),
      tileMesh: createGlobeMesh(gl, 24, 24),
      baseTexture: null,
      width: 0,
      height: 0,
    };
    canvas.addEventListener("webglcontextlost", handleGlobeContextLost, { once: true });
  } catch (error) {
    console.warn("WebGL 地球初始化失敗，改用 CPU 描繪。", error);
    state.globeGlDisabled = true;
    state.globeGl = null;
    canvas.hidden = true;
    return null;
  }
  return state.globeGl;
}

function handleGlobeContextLost(event) {
  event.preventDefault();
  state.globeGl = null;
  state.globeGlDisabled = true;
  dom.globeCanvas.hidden = true;
  for (const entry of state.earthTileCache.values()) {
    entry.texture = null;
  }
  state.earthTileBytes = 0;
  requestDraw();
}

function uploadGlobeTexture(renderer, source, { repeat = false } = {}) {
  const gl = renderer.gl;
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(
    gl.TEXTURE_2D,
    gl.TEXTURE_WRAP_S,
    repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE,
  );
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  if (renderer.anisotropic && renderer.maxAnisotropy > 1) {
    gl.texParameterf(
      gl.TEXTURE_2D,
      renderer.anisotropic.TEXTURE_MAX_ANISOTROPY_EXT,
      renderer.maxAnisotropy,
    );
  }
  return texture;
}

function downscaleToLimit(source, width, height, limit) {
  if (width <= limit && height <= limit) return source;
  const scale = Math.min(limit / width, limit / height);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(width * scale));
  canvas.height = Math.max(1, Math.floor(height * scale));
  const context = canvas.getContext("2d");
  context.imageSmoothingQuality = "high";
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function ensureGlobeBaseTexture(renderer) {
  if (renderer.baseTexture) return renderer.baseTexture;
  const earth = state.earthTexture;
  if (earth?.bitmap) {
    const source = downscaleToLimit(
      earth.bitmap,
      earth.width,
      earth.height,
      renderer.maxTextureSize,
    );
    renderer.baseTexture = {
      texture: uploadGlobeTexture(renderer, source, { repeat: true }),
      blendOcean: 0,
      pixelsPerDegree:
        (source === earth.bitmap ? earth.width : source.width) / 360,
    };
    earth.bitmap.close?.();
    earth.bitmap = null;
    return renderer.baseTexture;
  }
  const land = ensureLandTexture();
  renderer.baseTexture = {
    texture: uploadGlobeTexture(renderer, land.canvas, { repeat: true }),
    blendOcean: 1,
    pixelsPerDegree: land.width / 360,
  };
  return renderer.baseTexture;
}

function earthTileKey(level, column, row) {
  return `${level}:${column}:${row}`;
}

function earthTileResidentBytes(lod, level) {
  const entry = lod.levels[level];
  // RGBA plus the mip chain (4/3 of the base level).
  return Math.round((entry.tileWidth * entry.tileHeight * 4 * 4) / 3);
}

function pumpEarthTileQueue() {
  while (
    state.earthTileActive < CONFIG.globeTileConcurrency &&
    state.earthTileQueue.length
  ) {
    const task = state.earthTileQueue.shift();
    state.earthTileActive += 1;
    task().finally(() => {
      state.earthTileActive -= 1;
      pumpEarthTileQueue();
    });
  }
}

async function fetchEarthTileSource(path, sha256) {
  const response = await fetchAsset(assetUrl(path, sha256));
  if (!response.ok) {
    throw new Error(`無法讀取地球紋理圖磚（HTTP ${response.status}）。`);
  }
  const blob = await response.blob();
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(blob, {
        imageOrientation: "none",
        premultiplyAlpha: "none",
        colorSpaceConversion: "none",
      });
    } catch (_error) {
      return await createImageBitmap(blob);
    }
  }
  return decodeImage(blob);
}

function requestEarthTile(lod, level, column, row) {
  const key = earthTileKey(level, column, row);
  const existing = state.earthTileCache.get(key);
  if (existing) {
    existing.lastUsed = performance.now();
    return existing;
  }
  const tile = lod.levels[level]?.tiles.get(`${column}/${row}`);
  if (!tile) return null;
  const entry = {
    key,
    level,
    column,
    row,
    status: "loading",
    source: null,
    texture: null,
    pixels: null,
    bytes: earthTileResidentBytes(lod, level),
    lastUsed: performance.now(),
  };
  state.earthTileCache.set(key, entry);
  state.earthTileQueue.push(async () => {
    try {
      entry.source = await fetchEarthTileSource(tile.path, tile.sha256);
      entry.status = "ready";
      state.earthTileBytes += entry.bytes;
    } catch (error) {
      entry.status = "error";
      console.warn("地球紋理圖磚載入失敗。", error);
    }
    state.earthTextureGeneration += 1;
    requestDraw();
  });
  pumpEarthTileQueue();
  return entry;
}

function releaseEarthTile(entry) {
  if (entry.texture && state.globeGl) {
    state.globeGl.gl.deleteTexture(entry.texture);
  }
  entry.source?.close?.();
  entry.source = null;
  entry.texture = null;
  entry.pixels = null;
  if (entry.status === "ready") {
    state.earthTileBytes = Math.max(0, state.earthTileBytes - entry.bytes);
  }
  state.earthTileCache.delete(entry.key);
}

function pruneEarthTiles() {
  if (state.earthTileBytes <= CONFIG.globeTextureBudgetBytes) return;
  const removable = [...state.earthTileCache.values()]
    .filter((entry) => !state.visibleEarthTileKeys.has(entry.key))
    .sort((left, right) => left.lastUsed - right.lastUsed);
  for (const entry of removable) {
    if (state.earthTileBytes <= CONFIG.globeTextureBudgetBytes) return;
    releaseEarthTile(entry);
  }
}

function earthTextureTileAddress(level, longitude, latitude) {
  const u = (normalizeLongitude(longitude) + 180) / 360;
  const v = (90 - clamp(latitude, -90, 90)) / 180;
  const rawColumn = Math.floor(u * level.columns);
  const rawRow = Math.floor(v * level.rows);
  const column = clamp(rawColumn, 0, level.columns - 1);
  const row = clamp(rawRow, 0, level.rows - 1);
  return { key: `${column}/${row}`, column, row, u, v };
}

/** The tile of `target` that contains the same ground as `tile` of `source`. */
function mapTileBetweenLevels(tile, source, target) {
  return {
    column: clamp(
      Math.floor((tile.column * target.columns) / source.columns),
      0,
      target.columns - 1,
    ),
    row: clamp(Math.floor((tile.row * target.rows) / source.rows), 0, target.rows - 1),
  };
}

/**
 * Tiles whose patch overlaps the drawn globe.
 *
 * Screen samples find the tiles under the viewport (they stay correct once a
 * tile is larger than the screen), tile-corner samples find the tiles that only
 * clip the viewport edge.  The union is complete at every zoom, and costs a few
 * hundred transforms instead of one ray cast per screen cell.
 */
function visibleGlobeTiles(level, rotation, center, radius, viewport) {
  const found = new Map();
  const consider = (column, row, score) => {
    const key = `${column}/${row}`;
    const current = found.get(key);
    if (!current || score > current.score) {
      found.set(key, { column, row, score });
    }
  };

  const screenSamples = 10;
  for (let row = 0; row <= screenSamples; row += 1) {
    const screenY = (viewport.height * row) / screenSamples;
    const cameraY = -(screenY - center.y) / radius;
    for (let column = 0; column <= screenSamples; column += 1) {
      const screenX = (viewport.width * column) / screenSamples;
      const cameraX = (screenX - center.x) / radius;
      const squaredRadius = cameraX * cameraX + cameraY * cameraY;
      if (squaredRadius > 1) continue;
      const cameraZ = Math.sqrt(1 - squaredRadius);
      const world = cameraToWorldVector(cameraX, cameraY, cameraZ, rotation);
      const longitude = (Math.atan2(world[0], world[2]) * 180) / Math.PI;
      const latitude = (Math.asin(clamp(world[1], -1, 1)) * 180) / Math.PI;
      const address = earthTextureTileAddress(level, longitude, latitude);
      consider(address.column, address.row, cameraZ);
    }
  }

  const longitudeSpan = 360 / level.columns;
  const latitudeSpan = 180 / level.rows;
  const margin = 8;
  for (let row = 0; row < level.rows; row += 1) {
    for (let column = 0; column < level.columns; column += 1) {
      if (found.has(`${column}/${row}`)) continue;
      let best = 0;
      for (let sampleY = 0; sampleY <= 2 && best <= 0; sampleY += 1) {
        for (let sampleX = 0; sampleX <= 2 && best <= 0; sampleX += 1) {
          const longitude = -180 + (column + sampleX / 2) * longitudeSpan;
          const latitude = 90 - (row + sampleY / 2) * latitudeSpan;
          const point = projectGlobe(longitude, latitude, rotation, center, radius);
          if (
            point.z > 0 &&
            point.x >= -margin &&
            point.x <= viewport.width + margin &&
            point.y >= -margin &&
            point.y <= viewport.height + margin
          ) {
            best = point.z;
          }
        }
      }
      if (best > 0) consider(column, row, best);
    }
  }

  return [...found.values()]
    .sort((left, right) => right.score - left.score)
    .slice(0, CONFIG.globeMaxTiles);
}

function chooseEarthTextureLevel(lod, demandPerDegree) {
  for (let index = 0; index < lod.levels.length; index += 1) {
    if (lod.levels[index].pixelsPerDegree >= demandPerDegree) return index;
  }
  return lod.levels.length - 1;
}

/**
 * Pick one texture level for this frame and return the tiles to draw over the
 * overview texture, each with the finest level that is actually resident.
 */
function planEarthTiles(rotation, center, radius, viewport, basePixelsPerDegree, maxLevel = Infinity) {
  const lod = state.earthTextureLod;
  const demand = (radius * Math.PI) / 180;
  state.earthTextureStatus = {
    demand,
    level: null,
    pixelsPerDegree: basePixelsPerDegree,
    tiles: 0,
    pending: 0,
  };
  if (!lod || basePixelsPerDegree >= demand) {
    state.visibleEarthTileKeys = new Set();
    return [];
  }

  // Levels refine the grid, so the visible set is recounted whenever the
  // resident bytes of the wanted level would exceed the texture budget.
  let level = Math.min(chooseEarthTextureLevel(lod, demand), maxLevel);
  let visible = visibleGlobeTiles(lod.levels[level], rotation, center, radius, viewport);
  while (
    level > 0 &&
    visible.length * earthTileResidentBytes(lod, level) > CONFIG.globeTextureBudgetBytes
  ) {
    level -= 1;
    visible = visibleGlobeTiles(lod.levels[level], rotation, center, radius, viewport);
  }
  if (!visible.length) {
    state.visibleEarthTileKeys = new Set();
    return [];
  }
  const keys = new Set();
  const plans = [];
  const drawn = new Set();
  let pending = 0;
  for (const tile of visible) {
    const requested = requestEarthTile(lod, level, tile.column, tile.row);
    if (requested) keys.add(requested.key);
    let resolved = null;
    for (let candidate = level; candidate >= 0; candidate -= 1) {
      const address = candidate === level
        ? tile
        : mapTileBetweenLevels(tile, lod.levels[level], lod.levels[candidate]);
      const entry = state.earthTileCache.get(
        earthTileKey(candidate, address.column, address.row),
      );
      if (entry?.status === "ready") {
        entry.lastUsed = performance.now();
        keys.add(entry.key);
        resolved = entry;
        break;
      }
    }
    if (!resolved) {
      pending += 1;
      continue;
    }
    // A coarse tile can back several fine ones; draw it once.
    if (drawn.has(resolved.key)) continue;
    drawn.add(resolved.key);
    plans.push(resolved);
  }
  state.visibleEarthTileKeys = keys;
  pruneEarthTiles();
  plans.sort((left, right) => left.level - right.level);
  state.earthTextureStatus = {
    demand,
    level,
    pixelsPerDegree: Math.max(
      basePixelsPerDegree,
      plans.length ? lod.levels[plans[plans.length - 1].level].pixelsPerDegree : 0,
    ),
    tiles: plans.length,
    pending,
  };
  return plans;
}

function globeRotationMatrix(rotation) {
  const { cosineYaw, sineYaw, cosinePitch, sinePitch } = rotation;
  // Column-major mat3 of worldToCameraVector().
  return new Float32Array([
    cosineYaw,
    -sineYaw * sinePitch,
    sineYaw * cosinePitch,
    0,
    cosinePitch,
    sinePitch,
    -sineYaw,
    -cosineYaw * sinePitch,
    cosineYaw * cosinePitch,
  ]);
}

function drawGlobePatch(renderer, mesh, patch) {
  const gl = renderer.gl;
  const uniforms = renderer.uniforms;
  gl.uniform2f(uniforms.uLongitude, patch.longitudeStart, patch.longitudeSpan);
  gl.uniform2f(uniforms.uLatitude, patch.latitudeStart, patch.latitudeSpan);
  gl.uniform4f(uniforms.uUvRect, patch.u0, patch.v0, patch.uSpan, patch.vSpan);
  gl.uniform1f(uniforms.uDepthBias, patch.depthBias);
  gl.uniform1f(uniforms.uBlendOcean, patch.blendOcean);
  gl.bindTexture(gl.TEXTURE_2D, patch.texture);
  gl.bindVertexArray(mesh.vertexArray);
  gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_INT, 0);
}

function renderGlobeSurfaceWebgl(center, radius) {
  const renderer = ensureGlobeRenderer();
  if (!renderer) return false;
  const gl = renderer.gl;
  const canvas = dom.globeCanvas;
  const scale = Math.min(
    state.dpr,
    renderer.maxDimension / Math.max(1, state.width),
    renderer.maxDimension / Math.max(1, state.height),
  );
  const width = Math.max(1, Math.round(state.width * scale));
  const height = Math.max(1, Math.round(state.height * scale));
  if (renderer.width !== width || renderer.height !== height) {
    canvas.width = width;
    canvas.height = height;
    renderer.width = width;
    renderer.height = height;
  }

  const base = ensureGlobeBaseTexture(renderer);
  const rotation = globeRotation();
  const deviceCenter = { x: center.x * scale, y: center.y * scale };
  const deviceRadius = radius * scale;
  const viewport = { width, height };
  const tiles = planEarthTiles(
    rotation,
    deviceCenter,
    deviceRadius,
    viewport,
    base.pixelsPerDegree,
  );

  gl.viewport(0, 0, width, height);
  gl.clearColor(0, 0, 0, 0);
  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.disable(gl.BLEND);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.useProgram(renderer.program);
  gl.uniformMatrix3fv(renderer.uniforms.uRotation, false, globeRotationMatrix(rotation));
  gl.uniform2f(renderer.uniforms.uCenter, deviceCenter.x, deviceCenter.y);
  gl.uniform2f(renderer.uniforms.uViewport, width, height);
  gl.uniform1f(renderer.uniforms.uRadius, deviceRadius);
  gl.uniform1i(renderer.uniforms.uTexture, 0);
  gl.activeTexture(gl.TEXTURE0);

  drawGlobePatch(renderer, renderer.baseMesh, {
    longitudeStart: -180,
    longitudeSpan: 360,
    latitudeStart: 90,
    latitudeSpan: -180,
    u0: 0,
    v0: 0,
    uSpan: 1,
    vSpan: 1,
    depthBias: 0,
    blendOcean: base.blendOcean,
    texture: base.texture,
  });

  const lod = state.earthTextureLod;
  for (const entry of tiles) {
    if (!entry.texture) {
      if (!entry.source) continue;
      entry.texture = uploadGlobeTexture(renderer, entry.source);
      entry.source.close?.();
      entry.source = null;
    }
    const level = lod.levels[entry.level];
    const insetU = 0.5 / level.tileWidth;
    const insetV = 0.5 / level.tileHeight;
    drawGlobePatch(renderer, renderer.tileMesh, {
      longitudeStart: -180 + (entry.column * 360) / level.columns,
      longitudeSpan: 360 / level.columns,
      latitudeStart: 90 - (entry.row * 180) / level.rows,
      latitudeSpan: -180 / level.rows,
      u0: insetU,
      v0: insetV,
      uSpan: 1 - 2 * insetU,
      vSpan: 1 - 2 * insetV,
      depthBias: -0.0004 * (entry.level + 1),
      blendOcean: 0,
      texture: entry.texture,
    });
  }
  gl.bindVertexArray(null);
  canvas.hidden = false;
  return true;
}

// --- CPU fallback -----------------------------------------------------------

function globeRasterPlan(center, radius) {
  const left = Math.max(0, center.x - radius);
  const top = Math.max(0, center.y - radius);
  const right = Math.min(state.width, center.x + radius);
  const bottom = Math.min(state.height, center.y + radius);
  const width = Math.max(1, right - left);
  const height = Math.max(1, bottom - top);
  const target = state.pointer?.mode === "globe"
    ? CONFIG.globePreviewPixels
    : CONFIG.globeMaximumPixels;
  const scale = Math.min(state.dpr, target / Math.max(width, height));
  return {
    left,
    top,
    width,
    height,
    scale,
    rasterWidth: Math.max(1, Math.round(width * scale)),
    rasterHeight: Math.max(1, Math.round(height * scale)),
  };
}

function ensureGlobeRaster(width, height) {
  if (
    state.globeRaster?.width === width &&
    state.globeRaster?.height === height
  ) {
    return state.globeRaster;
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  state.globeRaster = { canvas, context, width, height };
  return state.globeRaster;
}

function ensureLandTexture() {
  if (state.landTexture) return state.landTexture;
  const width = 1024;
  const height = 512;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("無法建立 3D 地球的本機陸地紋理。");

  const xForLongitude = (longitude) => ((longitude + 180) / 360) * width;
  const yForLatitude = (latitude) => ((90 - clamp(latitude, -90, 90)) / 180) * height;
  context.fillStyle = "rgba(68, 132, 91, 0.96)";
  context.strokeStyle = "rgba(184, 231, 174, 0.82)";
  context.lineWidth = 1.1;
  context.lineJoin = "round";

  for (const polygon of state.landPolygons) {
    for (const longitudeOffset of [-360, 0, 360]) {
      context.beginPath();
      let drawable = false;
      for (const ring of polygon) {
        if (!ring.length) continue;
        let previousLongitude = ring[0][0] + longitudeOffset;
        context.moveTo(xForLongitude(previousLongitude), yForLatitude(ring[0][1]));
        for (let index = 1; index < ring.length; index += 1) {
          let longitude = ring[index][0] + longitudeOffset;
          while (longitude - previousLongitude > 180) longitude -= 360;
          while (longitude - previousLongitude < -180) longitude += 360;
          context.lineTo(xForLongitude(longitude), yForLatitude(ring[index][1]));
          previousLongitude = longitude;
        }
        context.closePath();
        drawable = true;
      }
      if (drawable) {
        context.fill("evenodd");
        context.stroke();
      }
    }
  }
  state.landTexture = { canvas, context, width, height, pixels: null };
  return state.landTexture;
}

function landTextureSampler() {
  const land = ensureLandTexture();
  if (!land.pixels) {
    land.pixels = land.context.getImageData(0, 0, land.width, land.height).data;
  }
  return land;
}

/** Overview pixels for the CPU fallback; the GPU path never builds this copy. */
function overviewSampler() {
  const earth = state.earthTexture;
  if (earth?.sample) return earth.sample;
  return landTextureSampler();
}

function textureSample(texture, longitude, latitude) {
  const x = clamp(
    Math.floor(((normalizeLongitude(longitude) + 180) / 360) * texture.width),
    0,
    texture.width - 1,
  );
  const y = clamp(
    Math.floor(((90 - clamp(latitude, -90, 90)) / 180) * texture.height),
    0,
    texture.height - 1,
  );
  const offset = (y * texture.width + x) * 4;
  return {
    red: texture.pixels[offset],
    green: texture.pixels[offset + 1],
    blue: texture.pixels[offset + 2],
    alpha: texture.pixels[offset + 3] / 255,
  };
}

function ensureEarthTilePixels(entry, level) {
  if (entry.pixels) return entry.pixels;
  if (entry.status !== "ready" || !entry.source) return null;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = level.tileWidth;
    canvas.height = level.tileHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(entry.source, 0, 0, level.tileWidth, level.tileHeight);
    entry.pixels = context.getImageData(0, 0, level.tileWidth, level.tileHeight).data;
    entry.source.close?.();
    entry.source = null;
    return entry.pixels;
  } catch (_error) {
    entry.status = "error";
    entry.source = null;
    return null;
  }
}

function highTextureSample(lod, plans, longitude, latitude) {
  const level = plans.level;
  const address = earthTextureTileAddress(level, longitude, latitude);
  const entry = plans.tiles.get(address.key);
  if (!entry) return null;
  const pixels = ensureEarthTilePixels(entry, level);
  if (!pixels) return null;
  const x = clamp(
    Math.floor((address.u * level.columns - address.column) * level.tileWidth),
    0,
    level.tileWidth - 1,
  );
  const y = clamp(
    Math.floor((address.v * level.rows - address.row) * level.tileHeight),
    0,
    level.tileHeight - 1,
  );
  const offset = (y * level.tileWidth + x) * 4;
  return {
    red: pixels[offset],
    green: pixels[offset + 1],
    blue: pixels[offset + 2],
    alpha: pixels[offset + 3] / 255,
  };
}

function drawGlobeSurfaceCpu(context, center, radius) {
  const plan = globeRasterPlan(center, radius);
  const raster = ensureGlobeRaster(plan.rasterWidth, plan.rasterHeight);
  const texture = overviewSampler();
  const rotation = globeRotation();
  const lod = state.earthTextureLod;
  let highTiles = null;
  if (lod && state.earthTexture) {
    const plans = planEarthTiles(
      rotation,
      center,
      radius,
      { width: state.width, height: state.height },
      texture.width / 360,
      CONFIG.globeCpuMaxLevel,
    );
    const chosen = plans.slice(0, CONFIG.globeCpuMaxTiles);
    if (chosen.length) {
      // One level per frame keeps the software sampler on a single grid.
      const level = lod.levels[chosen[chosen.length - 1].level];
      const tiles = new Map();
      for (const entry of chosen) {
        if (entry.level === level.index) tiles.set(`${entry.column}/${entry.row}`, entry);
      }
      if (tiles.size) highTiles = { level, tiles };
    }
  }
  const surfaceKey = [
    state.globe.yaw.toFixed(5),
    state.globe.pitch.toFixed(5),
    state.globe.zoom.toFixed(5),
    plan.left.toFixed(2),
    plan.top.toFixed(2),
    plan.width.toFixed(2),
    plan.height.toFixed(2),
    plan.rasterWidth,
    plan.rasterHeight,
    state.earthTextureGeneration,
  ].join("|");
  if (raster.surfaceKey === surfaceKey) {
    context.drawImage(raster.canvas, plan.left, plan.top, plan.width, plan.height);
    return;
  }
  const image = raster.context.createImageData(raster.width, raster.height);
  const data = image.data;

  for (let pixelY = 0; pixelY < raster.height; pixelY += 1) {
    const screenY = plan.top + (pixelY + 0.5) / plan.scale;
    const sphereY = (screenY - center.y) / radius;
    for (let pixelX = 0; pixelX < raster.width; pixelX += 1) {
      const screenX = plan.left + (pixelX + 0.5) / plan.scale;
      const sphereX = (screenX - center.x) / radius;
      const squaredRadius = sphereX * sphereX + sphereY * sphereY;
      const destination = (pixelY * raster.width + pixelX) * 4;
      if (squaredRadius > 1) {
        data[destination + 3] = 0;
        continue;
      }
      const cameraZ = Math.sqrt(1 - squaredRadius);
      const world = cameraToWorldVector(sphereX, -sphereY, cameraZ, rotation);
      const latitude = (Math.asin(clamp(world[1], -1, 1)) * 180) / Math.PI;
      const longitude = (Math.atan2(world[0], world[2]) * 180) / Math.PI;
      const land = highTiles
        ? highTextureSample(lod, highTiles, longitude, latitude)
        : null;
      const source = land || textureSample(texture, longitude, latitude);
      const light = clamp(
        0.4 + 0.6 * (cameraZ * 0.78 + sphereX * -0.28 + sphereY * -0.2),
        0.22,
        1,
      );
      const oceanRed = 8 + 8 * cameraZ;
      const oceanGreen = 52 + 34 * cameraZ;
      const oceanBlue = 76 + 35 * cameraZ;
      const baseRed = oceanRed * (1 - source.alpha) + source.red * source.alpha;
      const baseGreen = oceanGreen * (1 - source.alpha) + source.green * source.alpha;
      const baseBlue = oceanBlue * (1 - source.alpha) + source.blue * source.alpha;
      data[destination] = Math.round(baseRed * light);
      data[destination + 1] = Math.round(baseGreen * light);
      data[destination + 2] = Math.round(baseBlue * light);
      data[destination + 3] = 255;
    }
  }
  raster.context.putImageData(image, 0, 0);
  raster.surfaceKey = surfaceKey;
  context.save();
  context.drawImage(raster.canvas, plan.left, plan.top, plan.width, plan.height);
  context.restore();
}

function drawGlobeGraticule(context, center, radius) {
  const rotation = globeRotation();
  // Chord error stays below half a pixel; coarser when small, finer when zoomed.
  const step = clamp(114.6 / Math.sqrt(radius), 0.6, 6);
  context.save();
  context.strokeStyle = "rgba(203, 241, 238, 0.18)";
  context.lineWidth = 0.7;
  for (let longitude = -150; longitude <= 180; longitude += 30) {
    context.beginPath();
    let drawing = false;
    for (let latitude = -84; latitude <= 84; latitude += step) {
      const point = projectGlobe(longitude, latitude, rotation, center, radius);
      if (point.z <= 0) {
        drawing = false;
        continue;
      }
      if (!drawing) {
        context.moveTo(point.x, point.y);
        drawing = true;
      } else {
        context.lineTo(point.x, point.y);
      }
    }
    context.stroke();
  }
  for (let latitude = -60; latitude <= 60; latitude += 30) {
    context.beginPath();
    let drawing = false;
    for (let longitude = -180; longitude <= 180; longitude += step) {
      const point = projectGlobe(longitude, latitude, rotation, center, radius);
      if (point.z <= 0) {
        drawing = false;
        continue;
      }
      if (!drawing) {
        context.moveTo(point.x, point.y);
        drawing = true;
      } else {
        context.lineTo(point.x, point.y);
      }
    }
    context.stroke();
  }
  context.restore();
}

// ---------------------------------------------------------------------------
// Country layer.
//
// Natural Earth admin-0 outlines drawn over both views so the globe says which
// country is under the cursor.  Ring vertices are pre-projected to unit vectors
// once, then each frame only rotates them, culls by the ring's bounding cap and
// drops points that land within a pixel of the previous one.
// ---------------------------------------------------------------------------

async function loadCountryLayer(basemapManifest) {
  const specification = basemapManifest?.country_layer;
  if (!specification) return null;
  if (
    typeof specification.path !== "string" ||
    !/^[A-Za-z0-9_.-]+\.geojson$/i.test(specification.path) ||
    !Number.isInteger(specification.bytes) ||
    specification.bytes < 1 ||
    !/^[a-f0-9]{64}$/i.test(String(specification.sha256 || "")) ||
    typeof specification.name_field !== "string"
  ) {
    throw new Error("國家圖層的本機資產宣告無效。");
  }
  const response = await fetchAsset(assetUrl(specification.path, specification.sha256));
  if (!response.ok) {
    throw new Error(`無法讀取國家圖層（HTTP ${response.status}）。`);
  }
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== specification.bytes) {
    throw new Error("國家圖層大小驗證失敗。");
  }
  if (globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const actual = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    if (actual !== specification.sha256.toLowerCase()) {
      throw new Error("國家圖層 SHA-256 驗證失敗。");
    }
  }
  const collection = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  return prepareCountryLayer(collection, specification.name_field);
}

function prepareCountryLayer(collection, nameField) {
  const rings = [];
  const labels = [];
  const names = new Map();
  for (const feature of collection?.features || []) {
    const geometry = feature?.geometry;
    const properties = feature?.properties || {};
    if (!geometry) continue;
    const polygons =
      geometry.type === "Polygon"
        ? [geometry.coordinates]
        : geometry.type === "MultiPolygon"
          ? geometry.coordinates
          : [];
    for (const polygon of polygons) {
      for (const ring of polygon) {
        if (!Array.isArray(ring) || ring.length < 4) continue;
        const count = ring.length;
        const vectors = new Float32Array(count * 3);
        const coordinates = new Float32Array(count * 2);
        let sumX = 0;
        let sumY = 0;
        let sumZ = 0;
        for (let index = 0; index < count; index += 1) {
          const longitude = ring[index][0];
          const latitude = ring[index][1];
          const vector = vectorFromLongitudeLatitude(longitude, latitude);
          vectors[index * 3] = vector[0];
          vectors[index * 3 + 1] = vector[1];
          vectors[index * 3 + 2] = vector[2];
          coordinates[index * 2] = longitude;
          coordinates[index * 2 + 1] = latitude;
          sumX += vector[0];
          sumY += vector[1];
          sumZ += vector[2];
        }
        const length = Math.hypot(sumX, sumY, sumZ) || 1;
        const capX = sumX / length;
        const capY = sumY / length;
        const capZ = sumZ / length;
        let minimumDot = 1;
        for (let index = 0; index < count; index += 1) {
          const dot =
            vectors[index * 3] * capX +
            vectors[index * 3 + 1] * capY +
            vectors[index * 3 + 2] * capZ;
          if (dot < minimumDot) minimumDot = dot;
        }
        const capCosine = clamp(minimumDot, -1, 1);
        rings.push({
          vectors,
          coordinates,
          count,
          capX,
          capY,
          capZ,
          // Sine of the cap's angular radius: how far the ring reaches from its centre.
          capSine: Math.sqrt(Math.max(0, 1 - capCosine * capCosine)),
        });
      }
    }
    const name =
      properties[nameField] || properties.NAME_ZH || properties.NAME_EN || properties.NAME;
    // ISO_A2 is -99 for France and Norway; several territories share a
    // sovereign's code, so the most prominent feature wins the name.
    const iso = String(properties.ISO_A2_EH || properties.ISO_A2 || "").trim();
    const rank = Number(properties.LABELRANK) || 10;
    if (name && iso && iso !== "-99") {
      for (const key of iso.includes("-") ? [iso, iso.split("-").pop()] : [iso]) {
        const current = names.get(key);
        if (!current || rank < current.rank) names.set(key, { name: String(name), rank });
      }
    }
    const longitude = Number(properties.LABEL_X);
    const latitude = Number(properties.LABEL_Y);
    if (name && Number.isFinite(longitude) && Number.isFinite(latitude)) {
      labels.push({
        name: String(name),
        iso,
        longitude,
        latitude,
        vector: vectorFromLongitudeLatitude(longitude, latitude),
        rank,
        minimumLabel: Number(properties.MIN_LABEL) || 0,
      });
    }
  }
  labels.sort((left, right) => left.rank - right.rank);
  return {
    rings,
    labels,
    names: new Map([...names].map(([iso, entry]) => [iso, entry.name])),
    vertexCount: rings.reduce((total, ring) => total + ring.count, 0),
  };
}

function countriesEnabled() {
  return Boolean(state.countryLayer) && dom.layerCountries.checked;
}

/** Web-Mercator-equivalent zoom, so Natural Earth label ranks stay meaningful. */
function effectiveLabelZoom(radius) {
  return Math.log2(Math.max(1, (2 * Math.PI * radius) / 256));
}

function drawGlobeCountries(context, center, radius) {
  if (!countriesEnabled()) return;
  const rotation = globeRotation();
  const { cosineYaw, sineYaw, cosinePitch, sinePitch } = rotation;
  const minimumStep = radius > 2000 ? 1.4 : 1.1;
  const minimumStepSquared = minimumStep * minimumStep;
  context.save();
  context.strokeStyle = "rgba(255, 236, 176, 0.62)";
  context.lineWidth = radius > 2400 ? 1.2 : 0.9;
  context.lineJoin = "round";
  context.beginPath();
  for (const ring of state.countryLayer.rings) {
    // Cull whole rings that cannot reach the visible hemisphere.
    const capYawedX = ring.capX * cosineYaw - ring.capZ * sineYaw;
    const capYawedZ = ring.capX * sineYaw + ring.capZ * cosineYaw;
    const capCameraZ = ring.capY * sinePitch + capYawedZ * cosinePitch;
    if (capCameraZ < -ring.capSine) continue;
    const capCameraX = capYawedX;
    const capCameraY = ring.capY * cosinePitch - capYawedZ * sinePitch;
    const screenX = center.x + capCameraX * radius;
    const screenY = center.y - capCameraY * radius;
    const reach = ring.capSine * radius + 4;
    if (
      screenX + reach < 0 ||
      screenX - reach > state.width ||
      screenY + reach < 0 ||
      screenY - reach > state.height
    ) {
      continue;
    }
    const vectors = ring.vectors;
    let drawing = false;
    let lastX = 0;
    let lastY = 0;
    for (let index = 0; index < ring.count; index += 1) {
      const x = vectors[index * 3];
      const y = vectors[index * 3 + 1];
      const z = vectors[index * 3 + 2];
      const yawedX = x * cosineYaw - z * sineYaw;
      const yawedZ = x * sineYaw + z * cosineYaw;
      const cameraZ = y * sinePitch + yawedZ * cosinePitch;
      if (cameraZ <= 0) {
        drawing = false;
        continue;
      }
      const pointX = center.x + yawedX * radius;
      const pointY = center.y - (y * cosinePitch - yawedZ * sinePitch) * radius;
      if (!drawing) {
        context.moveTo(pointX, pointY);
        drawing = true;
        lastX = pointX;
        lastY = pointY;
        continue;
      }
      const deltaX = pointX - lastX;
      const deltaY = pointY - lastY;
      // Skip vertices that would land on the previous pixel.
      if (deltaX * deltaX + deltaY * deltaY < minimumStepSquared) continue;
      context.lineTo(pointX, pointY);
      lastX = pointX;
      lastY = pointY;
    }
  }
  context.stroke();
  context.restore();
}

function drawGlobeCountryLabels(context, center, radius) {
  if (!countriesEnabled()) return;
  const { cosineYaw, sineYaw, cosinePitch, sinePitch } = globeRotation();
  drawCountryLabels(context, radius, (label) => {
    const [x, y, z] = label.vector;
    const yawedX = x * cosineYaw - z * sineYaw;
    const yawedZ = x * sineYaw + z * cosineYaw;
    if (y * sinePitch + yawedZ * cosinePitch <= 0.02) return null;
    return {
      x: center.x + yawedX * radius,
      y: center.y - (y * cosinePitch - yawedZ * sinePitch) * radius,
    };
  });
}

function drawFlatCountries(context) {
  if (!countriesEnabled()) return;
  const size = mapWorldSize();
  context.save();
  context.strokeStyle = "rgba(255, 236, 176, 0.5)";
  context.lineWidth = 0.9;
  context.lineJoin = "round";
  context.beginPath();
  for (const ring of state.countryLayer.rings) {
    for (const longitudeOffset of [-360, 0, 360]) {
      let drawing = false;
      let lastX = 0;
      let lastY = 0;
      for (let index = 0; index < ring.count; index += 1) {
        const [x, y] = projectUnwrapped(
          ring.coordinates[index * 2] + longitudeOffset,
          ring.coordinates[index * 2 + 1],
        );
        if (x < -600 || x > state.width + 600 || y < -600 || y > state.height + 600) {
          drawing = false;
          continue;
        }
        if (!drawing) {
          context.moveTo(x, y);
          drawing = true;
          lastX = x;
          lastY = y;
          continue;
        }
        const deltaX = x - lastX;
        const deltaY = y - lastY;
        if (deltaX * deltaX + deltaY * deltaY < 1.2) continue;
        context.lineTo(x, y);
        lastX = x;
        lastY = y;
      }
    }
  }
  context.stroke();
  context.restore();
}

function drawFlatCountryLabels(context) {
  if (!countriesEnabled()) return;
  drawCountryLabels(context, mapWorldSize() / (2 * Math.PI), (label) => {
    const [x, y] = project(label.longitude, label.latitude);
    return { x, y };
  });
}

function drawCountryLabels(context, radius, projector) {
  const zoom = effectiveLabelZoom(radius);
  const placed = [];
  context.save();
  context.font = '600 12px "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif';
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  context.strokeStyle = "rgba(4, 12, 18, 0.86)";
  context.lineWidth = 3;
  context.fillStyle = "rgba(255, 243, 214, 0.94)";
  for (const label of state.countryLayer.labels) {
    if (placed.length >= CONFIG.countryLabelLimit) break;
    if (zoom < label.minimumLabel - 0.6) continue;
    const point = projector(label);
    if (!point) continue;
    if (
      point.x < 4 ||
      point.x > state.width - 4 ||
      point.y < 10 ||
      point.y > state.height - 10
    ) {
      continue;
    }
    const width = context.measureText(label.name).width;
    const box = {
      left: point.x - width / 2 - 3,
      right: point.x + width / 2 + 3,
      top: point.y - 8,
      bottom: point.y + 8,
    };
    let overlapping = false;
    for (const other of placed) {
      if (
        box.left < other.right &&
        box.right > other.left &&
        box.top < other.bottom &&
        box.bottom > other.top
      ) {
        overlapping = true;
        break;
      }
    }
    if (overlapping) continue;
    placed.push(box);
    context.strokeText(label.name, point.x, point.y);
    context.fillText(label.name, point.x, point.y);
  }
  context.restore();
}

function drawGlobeFallbackLand(context) {
  context.save();
  context.strokeStyle = "rgba(132, 205, 202, 0.76)";
  context.lineWidth = 0.8;
  for (const polygon of state.landPolygons) {
    for (const ring of polygon) {
      context.beginPath();
      let drawing = false;
      for (const coordinate of ring) {
        const point = projectGlobe(coordinate[0], coordinate[1]);
        if (point.z <= 0.005) {
          drawing = false;
          continue;
        }
        if (!drawing) {
          context.moveTo(point.x, point.y);
          drawing = true;
        } else {
          context.lineTo(point.x, point.y);
        }
      }
      context.stroke();
    }
  }
  context.restore();
}

function drawGlobeEdge(context, center, radius) {
  context.save();
  context.shadowColor = "rgba(76, 226, 211, 0.32)";
  context.shadowBlur = 22;
  context.strokeStyle = "rgba(177, 247, 239, 0.7)";
  context.lineWidth = 1.1;
  context.beginPath();
  context.arc(center.x, center.y, radius, 0, Math.PI * 2);
  context.stroke();
  context.restore();
}

function clusterGlobeRecords() {
  const cellSize = state.globe.zoom < 1.15 ? 30 : 22;
  const cells = new Map();
  let viewportCount = 0;
  const center = globeCenter();
  const radius = globeRadius();
  const rotation = globeRotation();
  for (const record of state.filteredRecords) {
    const point = projectGlobe(record.lon, record.lat, rotation, center, radius);
    if (point.z <= 0 || Math.hypot(point.x - center.x, point.y - center.y) > radius + 2) continue;
    viewportCount += 1;
    const key = `${record.layer}:${Math.floor(point.x / cellSize)}:${Math.floor(point.y / cellSize)}`;
    let cluster = cells.get(key);
    if (!cluster) {
      cluster = { layer: record.layer, count: 0, xSum: 0, ySum: 0, records: [] };
      cells.set(key, cluster);
    }
    cluster.count += 1;
    cluster.xSum += point.x;
    cluster.ySum += point.y;
    cluster.records.push(record);
  }
  const clusters = [...cells.values()].map((cluster) => {
    cluster.x = cluster.xSum / cluster.count;
    cluster.y = cluster.ySum / cluster.count;
    cluster.radius = cluster.count === 1 ? 3.3 : clamp(6 + Math.log10(cluster.count) * 4.2, 7, 21);
    return cluster;
  });
  clusters.sort((left, right) => {
    if (left.layer !== right.layer) return left.layer === "sighting" ? -1 : 1;
    return right.count - left.count;
  });
  return { clusters, viewportCount };
}

function drawGlobe(context) {
  const center = globeCenter();
  const radius = globeRadius();
  if (!renderGlobeSurfaceWebgl(center, radius)) {
    dom.globeCanvas.hidden = true;
    drawGlobeSurfaceCpu(context, center, radius);
  }
  updateBasemapStatus(null);
  drawGlobeGraticule(context, center, radius);
  drawGlobeCountries(context, center, radius);
  drawGlobeEdge(context, center, radius);
  return cachedClusters();
}

function osmBasemapConfig() {
  return state.mapConfig?.basemaps?.[state.mapConfig.default_basemap] || null;
}

function drawOsmTiles(context) {
  const config = osmBasemapConfig();
  if (!config) return { needed: 0, loaded: 0, loading: 0, errors: 1, zoom: 0 };

  const size = mapWorldSize();
  const minimumZoom = Number(config.minimum_zoom) || 0;
  const maximumZoom = Number(config.maximum_zoom) || 19;
  const tileZoom = clamp(Math.floor(Math.log2(size / 256)), minimumZoom, maximumZoom);
  const tileCount = 2 ** tileZoom;
  const tileWorldPixels = tileCount * 256;
  const tileScale = size / tileWorldPixels;
  const center = centerWorld();
  const centerPixelX = center.x * tileWorldPixels;
  const centerPixelY = center.y * tileWorldPixels;
  const halfWidthInTilePixels = state.width / (2 * tileScale);
  const halfHeightInTilePixels = state.height / (2 * tileScale);
  const firstTileX = Math.floor((centerPixelX - halfWidthInTilePixels) / 256);
  const lastTileX = Math.floor((centerPixelX + halfWidthInTilePixels) / 256);
  const firstTileY = Math.max(0, Math.floor((centerPixelY - halfHeightInTilePixels) / 256));
  const lastTileY = Math.min(
    tileCount - 1,
    Math.floor((centerPixelY + halfHeightInTilePixels) / 256),
  );
  const stats = { needed: 0, loaded: 0, loading: 0, errors: 0, zoom: tileZoom };
  const visibleKeys = new Set();

  context.save();
  context.imageSmoothingEnabled = true;
  for (let tileY = firstTileY; tileY <= lastTileY; tileY += 1) {
    for (let unwrappedTileX = firstTileX; unwrappedTileX <= lastTileX; unwrappedTileX += 1) {
      const tileX = ((unwrappedTileX % tileCount) + tileCount) % tileCount;
      const key = `${tileZoom}/${tileX}/${tileY}`;
      visibleKeys.add(key);
      stats.needed += 1;
      const entry = getTileEntry(config, tileZoom, tileX, tileY, key);
      entry.lastUsed = performance.now();
      if (entry.status === "loaded") {
        const screenX =
          state.width / 2 + (unwrappedTileX * 256 - centerPixelX) * tileScale;
        const screenY = state.height / 2 + (tileY * 256 - centerPixelY) * tileScale;
        const renderedSize = 256 * tileScale + 0.5;
        context.drawImage(entry.image, screenX, screenY, renderedSize, renderedSize);
        stats.loaded += 1;
      } else if (entry.status === "error") {
        stats.errors += 1;
      } else {
        stats.loading += 1;
      }
    }
  }
  if (stats.loaded > 0) {
    context.fillStyle = "rgba(3, 16, 22, 0.24)";
    context.fillRect(0, 0, state.width, state.height);
  }
  context.restore();
  state.visibleTileKeys = visibleKeys;
  pruneTileCache();
  return stats;
}

function getTileEntry(config, zoom, x, y, key) {
  const existing = state.tileCache.get(key);
  if (existing) return existing;

  const image = new Image();
  const entry = { image, status: "loading", lastUsed: performance.now() };
  image.crossOrigin = "anonymous";
  image.referrerPolicy = "strict-origin-when-cross-origin";
  image.decoding = "async";
  image.addEventListener("load", () => {
    entry.status = "loaded";
    requestDraw();
  });
  image.addEventListener("error", () => {
    entry.status = "error";
    requestDraw();
  });
  image.src = config.tile_url_template
    .replace("{z}", String(zoom))
    .replace("{x}", String(x))
    .replace("{y}", String(y));
  state.tileCache.set(key, entry);
  return entry;
}

function pruneTileCache() {
  if (state.tileCache.size <= CONFIG.maxTileCacheEntries) return;
  const removable = [...state.tileCache.entries()]
    .filter(([key]) => !state.visibleTileKeys.has(key))
    .sort((left, right) => left[1].lastUsed - right[1].lastUsed);
  const removeCount = state.tileCache.size - CONFIG.maxTileCacheEntries;
  for (const [key] of removable.slice(0, removeCount)) {
    state.tileCache.delete(key);
  }
}

// --- optional high-resolution texture pack ---------------------------------
//
// The pack is installed from the command line, so the page's job is to notice
// when it appears and switch to it without a reload.

function texturePack() {
  return (state.earthTextureLod?.optionalLevels || []).find((entry) => !entry.installed)
    || (state.earthTextureLod?.optionalLevels || [])[0]
    || null;
}

/** Re-read the texture manifests and adopt a level that has since been installed. */
async function refreshEarthTextureLod({ force = false } = {}) {
  const now = performance.now();
  if (!force && now - state.texturePackCheckedAt < 8000) return false;
  state.texturePackCheckedAt = now;
  try {
    const basemap = await fetchJson(CONFIG.basemapManifest, { cache: "no-cache" });
    const lod = await loadEarthTextureLod(basemap);
    if (!lod) return false;
    const before = state.earthTextureLod?.levels.length ?? 0;
    if (lod.levels.length === before) return false;
    // Drop cached tiles of levels that no longer exist before swapping.
    for (const entry of [...state.earthTileCache.values()]) {
      if (entry.level >= lod.levels.length) releaseEarthTile(entry);
    }
    state.basemapManifest = basemap;
    state.earthTextureLod = lod;
    state.earthTextureGeneration += 1;
    requestDraw();
    return true;
  } catch (error) {
    console.warn("重新檢查地球紋理索引失敗。", error);
    return false;
  }
}

function stopTexturePackPolling() {
  if (state.texturePackPollId !== null) {
    window.clearInterval(state.texturePackPollId);
    state.texturePackPollId = null;
  }
}

function startTexturePackPolling() {
  if (state.texturePackPollId !== null) return;
  state.texturePackPollId = window.setInterval(async () => {
    const changed = await refreshEarthTextureLod();
    if (changed) {
      updateTexturePackUi();
      if (texturePack()?.installed) {
        stopTexturePackPolling();
        dom.texturePackPanel.hidden = true;
      }
    }
  }, 8000);
}

function updateTexturePackUi() {
  const pack = texturePack();
  if (!pack) {
    dom.texturePackState.textContent = "不適用";
    dom.texturePackButton.disabled = true;
    dom.texturePackPanel.hidden = true;
    return;
  }
  dom.texturePackButton.disabled = false;
  dom.texturePackCommand.textContent = pack.installCommand || "python3 earth_texture_500m.py --install";
  if (pack.installed) {
    dom.texturePackState.textContent = `已啟用 ${Math.round(pack.pixelsPerDegree)}px/°`;
    dom.texturePackButton.textContent = "高清地表";
    dom.texturePackPanel.hidden = true;
    stopTexturePackPolling();
    return;
  }
  dom.texturePackState.textContent = "未安裝";
  dom.texturePackButton.textContent = "下載高清地表";
}

function toggleTexturePackPanel() {
  const pack = texturePack();
  if (!pack || pack.installed) {
    void refreshEarthTextureLod({ force: true }).then(updateTexturePackUi);
    return;
  }
  const open = dom.texturePackPanel.hidden;
  dom.texturePackPanel.hidden = !open;
  if (open) {
    void refreshEarthTextureLod({ force: true }).then(updateTexturePackUi);
    startTexturePackPolling();
  } else {
    stopTexturePackPolling();
  }
}

function updateCountryStatus() {
  if (!state.countryLayer) {
    dom.countryStatus.textContent = "無資料";
    dom.layerCountries.disabled = true;
    return;
  }
  dom.countryStatus.textContent = dom.layerCountries.checked
    ? `${numberFormatter.format(state.countryLayer.labels.length)} 國`
    : "已關閉";
}

function updateBasemapUi() {
  const globe = isGlobeView();
  const osmEnabled = dom.basemapOsm.checked && !globe;
  const earthTextureEnabled = globe && Boolean(state.earthTexture);
  dom.osmCredit.hidden = !osmEnabled;
  dom.naturalEarthCredit.hidden = globe ? earthTextureEnabled : osmEnabled;
  dom.earthTextureCredit.hidden = !earthTextureEnabled;
  dom.basemapStatus.textContent = globe
    ? earthTextureEnabled ? "3D 真彩" : "3D 輪廓"
    : osmEnabled ? "線上" : "離線";
}

function updateBasemapStatus(stats) {
  if (isGlobeView()) {
    const level = state.earthTextureStatus?.level;
    const suffix = Number.isInteger(level) ? ` L${level}` : "";
    dom.basemapStatus.textContent = state.earthTexture
      ? `3D 真彩${suffix}`
      : "3D 輪廓";
    return;
  }
  if (!dom.basemapOsm.checked) {
    dom.basemapStatus.textContent = "離線";
    return;
  }
  if (!stats || !stats.needed) {
    dom.basemapStatus.textContent = "備援";
  } else if (stats.loaded === stats.needed) {
    dom.basemapStatus.textContent = `OSM z${stats.zoom}`;
  } else if (stats.errors > 0 && stats.loaded === 0 && stats.loading === 0) {
    dom.basemapStatus.textContent = "離線備援";
  } else {
    dom.basemapStatus.textContent = `${stats.loaded}/${stats.needed}`;
  }
}

function clusterVisibleRecords() {
  const cellSize =
    state.view.zoom < 1.8 ? 34 : state.view.zoom < 4 ? 29 : state.view.zoom < 8 ? 23 : 17;
  const cells = new Map();
  let viewportCount = 0;

  for (const record of state.filteredRecords) {
    const [x, y] = project(record.lon, record.lat);
    if (x < -24 || x > state.width + 24 || y < -24 || y > state.height + 24) {
      continue;
    }
    viewportCount += 1;
    const key = `${record.layer}:${Math.floor(x / cellSize)}:${Math.floor(y / cellSize)}`;
    let cluster = cells.get(key);
    if (!cluster) {
      cluster = {
        layer: record.layer,
        count: 0,
        xSum: 0,
        ySum: 0,
        records: [],
      };
      cells.set(key, cluster);
    }
    cluster.count += 1;
    cluster.xSum += x;
    cluster.ySum += y;
    cluster.records.push(record);
  }

  const clusters = [...cells.values()].map((cluster) => {
    cluster.x = cluster.xSum / cluster.count;
    cluster.y = cluster.ySum / cluster.count;
    const geographicCenter = unproject(cluster.x, cluster.y);
    cluster.lon = geographicCenter.lon;
    cluster.lat = geographicCenter.lat;
    cluster.radius = cluster.count === 1 ? 3.7 : clamp(7 + Math.log10(cluster.count) * 5, 8, 25);
    return cluster;
  });
  clusters.sort((left, right) => {
    if (left.layer !== right.layer) return left.layer === "sighting" ? -1 : 1;
    return right.count - left.count;
  });
  return { clusters, viewportCount };
}

function drawCluster(context, cluster, highlighted) {
  const sighting = cluster.layer === "sighting";
  const globe = isGlobeView();
  const color = sighting ? "255, 137, 111" : "93, 226, 209";
  const radius = cluster.radius + (highlighted ? 2 : 0);

  context.save();
  if (cluster.count > 1 || highlighted) {
    context.fillStyle = `rgba(${color}, ${highlighted ? 0.22 : globe ? 0.085 : 0.12})`;
    context.beginPath();
    context.arc(cluster.x, cluster.y, radius + 4, 0, Math.PI * 2);
    context.fill();
  }
  context.fillStyle = `rgba(${color}, ${cluster.count === 1 ? globe ? 0.68 : 0.78 : globe ? 0.78 : 0.9})`;
  context.strokeStyle = sighting ? "rgba(255, 222, 214, 0.75)" : "rgba(221, 255, 251, 0.88)";
  context.lineWidth = sighting ? 0.7 : 1.2;
  context.beginPath();
  context.arc(cluster.x, cluster.y, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();

  if (cluster.count > 1) {
    context.fillStyle = sighting ? "#2d1210" : "#05211e";
    context.font = `700 ${cluster.count > 999 ? 8 : 9}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(compactNumberFormatter.format(cluster.count), cluster.x, cluster.y + 0.3);
  }
  context.restore();
}

function handlePointerDown(event) {
  if (!state.ready || event.button !== 0) return;
  const point = canvasPoint(event);
  const pointer = {
    id: event.pointerId,
    startX: point.x,
    startY: point.y,
    moved: false,
  };
  if (isGlobeView()) {
    pointer.mode = "globe";
    pointer.startYaw = state.globe.yaw;
    pointer.startPitch = state.globe.pitch;
  } else {
    pointer.mode = "flat";
    pointer.startWorldX = centerWorld().x;
    pointer.startWorldY = centerWorld().y;
  }
  state.pointer = pointer;
  dom.mapCanvas.setPointerCapture(event.pointerId);
  dom.mapCanvas.classList.add("dragging");
  hideTooltip();
}

function handlePointerMove(event) {
  if (!state.ready) return;
  const point = canvasPoint(event);
  if (state.pointer && state.pointer.id === event.pointerId) {
    const dx = point.x - state.pointer.startX;
    const dy = point.y - state.pointer.startY;
    if (Math.hypot(dx, dy) > 3) state.pointer.moved = true;
    if (state.pointer.moved) {
      if (state.pointer.mode === "globe") {
        const degreesPerPixel = 180 / (Math.PI * globeRadius());
        state.globe.yaw = normalizeLongitude(state.pointer.startYaw - dx * degreesPerPixel);
        state.globe.pitch = clamp(state.pointer.startPitch + dy * degreesPerPixel, -82, 82);
      } else {
        const size = mapWorldSize();
        state.view.centerLon = worldXToLongitude(state.pointer.startWorldX - dx / size);
        state.view.centerLat = worldYToLatitude(state.pointer.startWorldY - dy / size);
        clampView();
      }
      requestDraw();
    }
    return;
  }
  updateHover(point.x, point.y);
}

function handlePointerUp(event) {
  if (!state.pointer || state.pointer.id !== event.pointerId) return;
  const point = canvasPoint(event);
  const wasMoved = state.pointer.moved;
  cancelPointer(event);
  if (!wasMoved) {
    const cluster = findCluster(point.x, point.y);
    if (cluster) {
      activateCluster(cluster);
    } else {
      closeDetails();
    }
  }
}

function cancelPointer(event) {
  if (state.pointer && (!event || state.pointer.id === event.pointerId)) {
    try {
      if (dom.mapCanvas.hasPointerCapture(state.pointer.id)) {
        dom.mapCanvas.releasePointerCapture(state.pointer.id);
      }
    } catch (_error) {
      // The browser may already have released capture after pointercancel.
    }
    state.pointer = null;
    dom.mapCanvas.classList.remove("dragging");
    requestDraw();
  }
}

function handlePointerLeave() {
  if (!state.pointer) hideTooltip();
}

function handleWheel(event) {
  if (!state.ready) return;
  event.preventDefault();
  const point = canvasPoint(event);
  const factor = Math.exp(-event.deltaY * 0.0014);
  zoomAround(factor, point.x, point.y);
}

function handleMapKeydown(event) {
  if (!state.ready) return;
  let handled = true;
  if (event.key === "ArrowLeft") {
    if (isGlobeView()) state.globe.yaw = normalizeLongitude(state.globe.yaw - 8);
    else panViewByPixels(-70, 0);
  } else if (event.key === "ArrowRight") {
    if (isGlobeView()) state.globe.yaw = normalizeLongitude(state.globe.yaw + 8);
    else panViewByPixels(70, 0);
  } else if (event.key === "ArrowUp") {
    if (isGlobeView()) state.globe.pitch = clamp(state.globe.pitch - 6, -82, 82);
    else panViewByPixels(0, -70);
  } else if (event.key === "ArrowDown") {
    if (isGlobeView()) state.globe.pitch = clamp(state.globe.pitch + 6, -82, 82);
    else panViewByPixels(0, 70);
  }
  else if (event.key === "+" || event.key === "=") zoomAround(1.6);
  else if (event.key === "-") zoomAround(1 / 1.6);
  else if (event.key === "0") fitWorld();
  else if (event.key === "Enter" && state.hoveredCluster) activateCluster(state.hoveredCluster);
  else handled = false;
  if (handled) {
    event.preventDefault();
    if (!isGlobeView()) clampView();
    requestDraw();
  }
}

function panViewByPixels(deltaX, deltaY) {
  const center = centerWorld();
  const size = mapWorldSize();
  state.view.centerLon = worldXToLongitude(center.x + deltaX / size);
  state.view.centerLat = worldYToLatitude(center.y + deltaY / size);
}

function canvasPoint(event) {
  const rect = dom.mapCanvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function updateHover(x, y) {
  const cluster = findCluster(x, y);
  if (cluster === state.hoveredCluster) {
    if (cluster) positionTooltip(x, y);
    return;
  }
  state.hoveredCluster = cluster;
  if (cluster) {
    showTooltip(cluster, x, y);
    dom.mapCanvas.style.cursor = "pointer";
  } else {
    hideTooltip();
    dom.mapCanvas.style.cursor = "grab";
  }
  requestDraw();
}

function findCluster(x, y) {
  let nearest = null;
  let nearestDistance = Infinity;
  for (let index = state.clusters.length - 1; index >= 0; index -= 1) {
    const cluster = state.clusters[index];
    const distance = Math.hypot(cluster.x - x, cluster.y - y);
    if (distance <= cluster.radius + 7 && distance < nearestDistance) {
      nearest = cluster;
      nearestDistance = distance;
    }
  }
  return nearest;
}

function showTooltip(cluster, x, y) {
  const title = document.createElement("strong");
  const hint = document.createElement("span");
  if (cluster.count === 1) {
    const record = cluster.records[0];
    title.textContent = recordTitle(record);
    const snippet = narrativeSnippet(record, 78);
    hint.textContent = snippet
      ? `${snippet}\n${recordLocation(record)} · 點擊查看來源明細`
      : `${recordLocation(record)} · 點擊查看來源明細`;
  } else {
    title.textContent = `${numberFormatter.format(cluster.count)} 筆${cluster.layer === "sighting" ? "目擊報告" : "天文控制"}`;
    hint.textContent = isGlobeView() || state.view.zoom >= CONFIG.clusterDetailZoom
      ? "點擊查看群集內紀錄"
      : "點擊放大這個群集";
  }
  dom.mapTooltip.replaceChildren(title, hint);
  dom.mapTooltip.hidden = false;
  positionTooltip(x, y);
}

function positionTooltip(x, y) {
  const margin = 10;
  const tooltipWidth = dom.mapTooltip.offsetWidth;
  const tooltipHeight = dom.mapTooltip.offsetHeight;
  const left = clamp(x + 14, margin, state.width - tooltipWidth - margin);
  const top = clamp(y + 14, margin, state.height - tooltipHeight - margin);
  dom.mapTooltip.style.left = `${left}px`;
  dom.mapTooltip.style.top = `${top}px`;
}

function hideTooltip() {
  dom.mapTooltip.hidden = true;
  if (state.hoveredCluster) {
    state.hoveredCluster = null;
    requestDraw();
  }
}

function activateCluster(cluster) {
  hideTooltip();
  if (!isGlobeView() && cluster.count > 1 && state.view.zoom < CONFIG.clusterDetailZoom) {
    state.view.centerLon = cluster.lon;
    state.view.centerLat = cluster.lat;
    state.view.zoom = clamp(state.view.zoom * 2.25, CONFIG.minZoom, CONFIG.maxZoom);
    clampView();
    requestDraw();
    return;
  }
  if (cluster.count === 1) {
    showRecordDetails(cluster.records[0]);
  } else {
    showClusterDetails(cluster);
  }
}

function showRecordDetails(record) {
  const properties = record.properties;
  dom.detailKicker.textContent = record.layer === "sighting" ? "目擊報告明細" : "天文控制明細";
  const content = document.createDocumentFragment();
  const role = createElement(
    "span",
    `detail-role ${record.layer}`,
    record.layer === "sighting" ? "目擊報告" : "獨立控制資料",
  );
  const title = createElement("h2", "detail-title", recordTitle(record));
  const subtitle = createElement(
    "p",
    "detail-subtitle",
    `${recordLocation(record)} · ${formatObservedAt(record)}`,
  );
  const narrative = recordNarrative(record);
  const report = document.createDocumentFragment();
  if (narrative) {
    const block = createElement("blockquote", "record-narrative");
    block.append(createElement("p", "", narrative));
    block.append(
      createElement(
        "footer",
        "record-narrative-note",
        `${sourceDisplayName(record.source)} 發布的原文，未翻譯、未改寫`,
      ),
    );
    report.append(block);
  } else if (record.layer === "sighting") {
    report.append(
      createElement("p", "record-narrative-missing", "這筆來源沒有發布事件描述，只有時間與地點。"),
    );
  }

  const readings = fireballReadings(record);
  if (readings.length) {
    const list = createElement("dl", "record-details record-readings");
    for (const reading of readings) {
      appendDefinition(list, reading.label, reading.value);
    }
    report.append(list);
  }

  const details = createElement("dl", "record-details");

  appendDefinition(details, "來源", sourceDisplayName(record.source));
  appendDefinition(details, "國家／範圍", recordCountry(record));
  appendDefinition(details, "來源編號", stringValue(properties.source_record_id) || "未提供", "record-id");
  appendDefinition(details, "觀測時間", formatObservedAt(record));
  appendDefinition(details, "時間精度", stringValue(properties.time_precision) || "來源未標示");
  appendDefinition(details, "公開座標", `${record.lat.toFixed(3)}, ${record.lon.toFixed(3)}`, "record-id");
  appendDefinition(details, "座標精度", stringValue(properties.coordinate_precision) || "來源未標示");
  appendDefinition(details, "隱私層級", privacyDisplayName(properties.privacy_tier));
  appendDefinition(details, "紀錄類型", stringValue(properties.record_type) || "未提供");
  if (stringValue(properties.status)) appendDefinition(details, "來源狀態", stringValue(properties.status));
  if (stringValue(properties.original_source_url) && !safeHttpUrl(properties.original_source_url)) {
    appendDefinition(details, "原始出處", stringValue(properties.original_source_url));
  }
  appendDefinition(details, "Observation ID", record.id || "未提供", "record-id");

  const actions = createElement("div", "detail-actions");
  appendLinkAction(actions, properties.original_source_url, "開啟原始來源");
  appendLinkAction(actions, properties.source_portal_url, "開啟來源入口");
  if (record.id) {
    const copyButton = createElement("button", "detail-copy-button", "複製 Observation ID");
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      const copied = await copyText(record.id);
      copyButton.textContent = copied ? "已複製" : "複製失敗";
      window.setTimeout(() => {
        copyButton.textContent = "複製 Observation ID";
      }, 1500);
    });
    actions.append(copyButton);
  }

  content.append(role, title, subtitle, report, details, actions);
  dom.detailContent.replaceChildren(content);
  dom.detailDrawer.hidden = false;
}

function showClusterDetails(cluster) {
  dom.detailKicker.textContent = cluster.layer === "sighting" ? "目擊群集" : "控制群集";
  const content = document.createDocumentFragment();
  const role = createElement(
    "span",
    `detail-role ${cluster.layer}`,
    cluster.layer === "sighting" ? "畫面目擊群集" : "畫面控制群集",
  );
  const title = createElement(
    "h2",
    "detail-title",
    `${numberFormatter.format(cluster.count)} 筆同畫面網格紀錄`,
  );
  const summary = createElement(
    "p",
    "cluster-summary",
    "這只是目前縮放層級的瀏覽器群集，不表示這些報告是同一事件。選一筆可查看來源明細。",
  );
  const list = createElement("ol", "cluster-list");
  const records = [...cluster.records].sort((left, right) => (right.year || -Infinity) - (left.year || -Infinity));
  for (const record of records.slice(0, CONFIG.maxClusterRecords)) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.append(
      createElement("strong", "", recordTitle(record)),
      createElement("span", "", `${formatObservedAt(record)} · ${sourceDisplayName(record.source)}`),
    );
    const snippet = narrativeSnippet(record, 110);
    if (snippet) button.append(createElement("span", "cluster-narrative", snippet));
    button.addEventListener("click", () => showRecordDetails(record));
    item.append(button);
    list.append(item);
  }
  content.append(role, title, summary, list);
  if (records.length > CONFIG.maxClusterRecords) {
    content.append(
      createElement(
        "p",
        "cluster-overflow",
        `另有 ${numberFormatter.format(records.length - CONFIG.maxClusterRecords)} 筆未在清單展開；請再放大地圖。`,
      ),
    );
  }
  dom.detailContent.replaceChildren(content);
  dom.detailDrawer.hidden = false;
}

function appendDefinition(list, term, value, valueClass = "") {
  const row = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = value;
  if (valueClass) dd.className = valueClass;
  row.append(dt, dd);
  list.append(row);
}

function appendLinkAction(container, value, label) {
  const href = safeHttpUrl(value);
  if (!href) return;
  const anchor = createElement("a", "detail-link", label);
  anchor.href = href;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  container.append(anchor);
}

function safeHttpUrl(value) {
  try {
    const parsed = new URL(stringValue(value));
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch (_error) {
    return null;
  }
}

function privacyDisplayName(value) {
  const labels = {
    source_published_precision_unspecified: "來源公開；精度未標示",
    source_published_coarse_or_unknown: "來源公開；粗略或未知精度",
    no_geometry: "無公開幾何",
  };
  const normalized = stringValue(value);
  return labels[normalized] || normalized || "未標示";
}

/**
 * The source's own account of the report.
 *
 * It is evidence text, shown verbatim: never rewritten, summarised or
 * translated.  NASA's fireball control feed puts a measurement object in the
 * same field, so that one is unpacked into readings instead.
 */
function recordNarrative(record) {
  const summary = stringValue(record.properties.summary).trim();
  if (!summary) return null;
  if (record.layer !== "sighting" && summary.startsWith("{")) return null;
  return summary;
}

const FIREBALL_READINGS = Object.freeze({
  alt: { label: "進入高度", unit: " km" },
  vel: { label: "速度", unit: " km/s" },
  energy: { label: "輻射能量", unit: " J×10¹⁰" },
  "impact-e": { label: "撞擊能量", unit: " kt TNT" },
});

function fireballReadings(record) {
  const summary = stringValue(record.properties.summary).trim();
  if (!summary.startsWith("{")) return [];
  let parsed;
  try {
    parsed = JSON.parse(summary);
  } catch (_error) {
    return [];
  }
  const readings = [];
  for (const [key, format] of Object.entries(FIREBALL_READINGS)) {
    const value = parsed?.[key];
    if (value === null || value === undefined || value === "") continue;
    readings.push({ label: format.label, value: `${value}${format.unit}` });
  }
  return readings;
}

function narrativeSnippet(record, limit = 96) {
  const narrative = recordNarrative(record);
  if (!narrative) return "";
  const collapsed = narrative.replace(/\s+/g, " ").trim();
  return collapsed.length > limit ? `${collapsed.slice(0, limit - 1)}…` : collapsed;
}

function recordTitle(record) {
  return (
    stringValue(record.properties.title) ||
    stringValue(record.properties.location_name) ||
    stringValue(record.properties.record_type) ||
    "未命名紀錄"
  );
}

const LOCATION_SCOPE_LABELS = Object.freeze({
  multi_country: "跨國區域",
  region: "海域或地理區",
  off_earth: "地球以外",
  unknown: "來源未標明",
});

/** Localised country name for a resolved ISO code, when the layer is loaded. */
function countryDisplayName(iso) {
  if (!iso) return "";
  return state.countryLayer?.names?.get(iso) || "";
}

/**
 * How the record's country reads.
 *
 * Sources bucket reports under their own labels, so the resolved country is
 * shown with the source's original wording kept beside it, and buckets that
 * name no single country say so instead of guessing one.
 */
function recordCountry(record) {
  const properties = record.properties;
  const label = stringValue(properties.country_code);
  const iso = stringValue(properties.country_iso_a2);
  const scope = stringValue(properties.location_scope);
  const name = countryDisplayName(iso);
  if (iso) {
    const resolved = name ? `${name}（${iso}）` : iso;
    return label && label !== iso && label !== name ? `${resolved} · 來源標記「${label}」` : resolved;
  }
  const scopeLabel = LOCATION_SCOPE_LABELS[scope];
  if (scopeLabel) return label ? `${scopeLabel} · 來源標記「${label}」` : scopeLabel;
  return label || "未提供";
}

function recordLocation(record) {
  return (
    stringValue(record.properties.location_name) ||
    stringValue(record.properties.country_code) ||
    `${record.lat.toFixed(2)}, ${record.lon.toFixed(2)}`
  );
}

function formatObservedAt(record) {
  return stringValue(record.properties.observed_at_start) || "日期不明";
}

function closeDetails() {
  dom.detailDrawer.hidden = true;
  dom.detailContent.replaceChildren();
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (_error) {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    return copied;
  }
}

function createElement(tagName, className = "", text = "") {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== "") element.textContent = text;
  return element;
}

function debounce(callback, delay) {
  let timeout = null;
  return (...args) => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => callback(...args), delay);
  };
}
