/* ── OrbitWhisper App – LeoLabs-style satellite visualization ── */

// ── Category → color mapping ──
const CATEGORY_COLORS = {
  "空间站与特殊兴趣": "#ff6600",
  "气象与地球资源":   "#00ccff",
  "通信卫星":         "#ffcc00",
  "导航卫星":         "#00ff88",
  "科学卫星":         "#cc44ff",
  "其他":             "#888888",
  "大型星座":         "#4488ff",
};

// Default-on categories (shown on first load)
const DEFAULT_VISIBLE = new Set([
  "空间站与特殊兴趣",
  "导航卫星",
  "科学卫星",
]);

// ── Orbit animation constants ──
const MIN_ORBIT_PERIOD_SEC = 4800;
const BASE_ORBIT_PERIOD_SEC = 5600;
const ORBIT_PERIOD_ALTITUDE_FACTOR = 12;
const GOLDEN_ANGLE_DEG = 137.5;

// ── State ──
let allOrbits = [];               // full satellite database from report
let visibleCategories = new Set(); // currently visible categories
let entityMap = {};
let orbitStateMap = {};
let orbitMap = {};
let nextOrbitPhaseIndex = 0;
let viewer = null;

// ── Helpers ──
const wrapLng = v => ((((v + 180) % 360) + 360) % 360) - 180;
const clampLat = v => Math.max(-85, Math.min(85, v));
const safeAltM = km => { const a = Number(km); return Number.isFinite(a) ? Math.max(a, 0) * 1000 : 550000; };

function calcPosition(state, time, result) {
  const o = state.orbit;
  const period = Math.max(MIN_ORBIT_PERIOD_SEC, BASE_ORBIT_PERIOD_SEC + Number(o.alt || 0) * ORBIT_PERIOD_ALTITUDE_FACTOR);
  const elapsed = Cesium.JulianDate.secondsDifference(time, state.startTime);
  const phase = ((state.phaseDeg + (elapsed * 360) / period) % 360) * (Math.PI / 180);
  const swing = Math.max(2, Math.min(22, Math.abs(Number(o.lat || 0)) * 0.5 + 6));
  const lat = clampLat(Number(o.lat || 0) + Math.sin(phase) * swing);
  const lng = wrapLng(Number(o.lng || 0) + (elapsed * 360) / period);
  return Cesium.Cartesian3.fromDegrees(lng, lat, safeAltM(o.alt), Cesium.Ellipsoid.WGS84, result);
}

// ── Category filter UI ──
function buildCategoryFilters(catStats) {
  const container = document.getElementById("categoryFilters");
  container.innerHTML = "";

  const categories = Object.entries(catStats).sort((a, b) => b[1] - a[1]);

  categories.forEach(([cat, count]) => {
    const color = CATEGORY_COLORS[cat] || "#aaa";
    const isDefault = DEFAULT_VISIBLE.has(cat);

    const item = document.createElement("label");
    item.className = "category-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "category-checkbox";
    checkbox.checked = isDefault;
    checkbox.style.backgroundColor = isDefault ? color : "transparent";
    checkbox.style.borderColor = isDefault ? color : "";
    checkbox.dataset.category = cat;
    checkbox.dataset.color = color;

    checkbox.addEventListener("change", () => {
      checkbox.style.backgroundColor = checkbox.checked ? color : "transparent";
      checkbox.style.borderColor = checkbox.checked ? color : "";
      toggleCategory(cat, checkbox.checked);
    });

    if (isDefault) visibleCategories.add(cat);

    const dot = document.createElement("span");
    dot.className = "category-dot";
    dot.style.backgroundColor = color;

    const label = document.createElement("span");
    label.className = "category-label";
    label.textContent = cat;

    const countSpan = document.createElement("span");
    countSpan.className = "category-count";
    countSpan.textContent = count.toLocaleString();

    item.append(checkbox, dot, label, countSpan);
    container.appendChild(item);
  });
}

function toggleCategory(cat, show) {
  if (show) {
    visibleCategories.add(cat);
  } else {
    visibleCategories.delete(cat);
  }
  applyFilters();
}

function applyFilters() {
  let visibleCount = 0;

  allOrbits.forEach(orbit => {
    const key = String(orbit.asset_id || "").toLowerCase();
    const entity = entityMap[key];
    if (!entity) return;

    const cat = orbit.category || "其他";
    const shouldShow = visibleCategories.has(cat);
    entity.show = shouldShow;
    if (shouldShow) visibleCount++;
  });

  document.getElementById("visibleCount").textContent = visibleCount.toLocaleString();
  document.getElementById("bottomCount").textContent = `${visibleCount.toLocaleString()} 颗卫星显示中`;
}

function setAllCategories(checked) {
  document.querySelectorAll(".category-checkbox").forEach(cb => {
    cb.checked = checked;
    const color = cb.dataset.color;
    cb.style.backgroundColor = checked ? color : "transparent";
    cb.style.borderColor = checked ? color : "";
    const cat = cb.dataset.category;
    if (checked) visibleCategories.add(cat);
    else visibleCategories.delete(cat);
  });
  applyFilters();
}

// ── Legend ──
function buildLegend(catStats) {
  const container = document.getElementById("legendItems");
  container.innerHTML = "";
  Object.entries(catStats).sort((a, b) => b[1] - a[1]).forEach(([cat]) => {
    const color = CATEGORY_COLORS[cat] || "#aaa";
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<span class="legend-dot" style="background:${color};color:${color}"></span><span>${cat}</span>`;
    container.appendChild(item);
  });
}

// ── Satellite entity management ──
function addSatelliteEntity(orbit) {
  const key = String(orbit.asset_id || "").toLowerCase();
  if (!key || !viewer) return;

  const cat = orbit.category || "其他";
  const color = CATEGORY_COLORS[cat] || "#aaa";
  const cesiumColor = Cesium.Color.fromCssColorString(color);

  orbitMap[key] = orbit;

  if (!orbitStateMap[key]) {
    orbitStateMap[key] = {
      orbit,
      phaseDeg: (nextOrbitPhaseIndex * GOLDEN_ANGLE_DEG) % 360,
      startTime: Cesium.JulianDate.now(),
    };
    nextOrbitPhaseIndex++;

    const shouldShow = visibleCategories.has(cat);
    const displayName = orbit.name || orbit.asset_id;

    const entity = viewer.entities.add({
      id: orbit.asset_id,
      name: displayName,
      show: shouldShow,
      position: new Cesium.CallbackProperty((time, result) => calcPosition(orbitStateMap[key], time, result), false),
      point: {
        pixelSize: 4,
        color: cesiumColor,
        outlineWidth: 0,
        scaleByDistance: new Cesium.NearFarScalar(5e5, 2.0, 2e7, 0.5),
      },
      label: {
        text: displayName,
        font: "11px Inter, sans-serif",
        fillColor: Cesium.Color.WHITE,
        showBackground: true,
        backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.65),
        backgroundPadding: new Cesium.Cartesian2(4, 3),
        scaleByDistance: new Cesium.NearFarScalar(1e5, 0.9, 3e6, 0.0),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 3e6),
        pixelOffset: new Cesium.Cartesian2(0, -12),
      },
    });

    entityMap[key] = entity;
  } else {
    orbitStateMap[key].orbit = orbit;
  }
}

// ── Detail panel ──
function showDetailPanel(orbit) {
  const panel = document.getElementById("detailPanel");
  const body = document.getElementById("detailBody");
  const title = document.getElementById("detailTitle");

  // Hide legend when detail is shown
  document.getElementById("legend").style.display = "none";

  const name = orbit.name || orbit.asset_id;
  title.textContent = name;

  const cat = orbit.category || "其他";
  const color = CATEGORY_COLORS[cat] || "#aaa";

  body.innerHTML = `
    <div class="detail-row"><span class="label">NORAD ID</span><span class="value">${orbit.norad_id || orbit.asset_id}</span></div>
    <div class="detail-row"><span class="label">名称</span><span class="value">${name}</span></div>
    <div class="detail-row"><span class="label">分类</span><span class="value" style="color:${color}">${cat}</span></div>
    <div class="detail-row"><span class="label">纬度</span><span class="value">${Number(orbit.lat).toFixed(4)}°</span></div>
    <div class="detail-row"><span class="label">经度</span><span class="value">${Number(orbit.lng).toFixed(4)}°</span></div>
    <div class="detail-row"><span class="label">高度</span><span class="value">${Number(orbit.alt).toFixed(1)} km</span></div>
  `;

  panel.classList.remove("hidden");
}

function hideDetailPanel() {
  document.getElementById("detailPanel").classList.add("hidden");
  document.getElementById("legend").style.display = "";
  if (viewer) viewer.trackedEntity = undefined;
}

// ── Search ──
function searchSatellites(keyword) {
  const results = document.getElementById("searchResults");
  results.innerHTML = "";
  if (!keyword || keyword.length < 2) return;

  const q = keyword.toLowerCase();
  const matches = allOrbits
    .filter(o => (o.name || "").toLowerCase().includes(q) || String(o.asset_id).includes(q) || String(o.norad_id || "").includes(q))
    .slice(0, 15);

  matches.forEach(orbit => {
    const li = document.createElement("li");
    const nameSpan = document.createElement("span");
    nameSpan.textContent = orbit.name || orbit.asset_id;

    const catSpan = document.createElement("span");
    catSpan.className = "sat-cat";
    const cat = orbit.category || "其他";
    catSpan.style.color = CATEGORY_COLORS[cat] || "#aaa";
    catSpan.textContent = cat;

    li.append(nameSpan, catSpan);
    li.addEventListener("click", () => {
      // Make sure category is visible
      if (!visibleCategories.has(cat)) {
        const cb = document.querySelector(`.category-checkbox[data-category="${cat}"]`);
        if (cb) { cb.checked = true; cb.style.backgroundColor = cb.dataset.color; cb.style.borderColor = cb.dataset.color; }
        visibleCategories.add(cat);
        applyFilters();
      }

      const key = String(orbit.asset_id || "").toLowerCase();
      const entity = entityMap[key];
      if (entity) {
        entity.show = true;
        viewer.trackedEntity = entity;
        viewer.flyTo(entity, { duration: 1.2 });
      }
      showDetailPanel(orbit);
      results.innerHTML = "";
      document.getElementById("searchInput").value = orbit.name || orbit.asset_id;
    });

    results.appendChild(li);
  });
}

// ── Bootstrap ──
(async function bootstrap() {
  // Load report
  let report;
  try {
    report = await fetch("./data/daily_report.json", { cache: "no-store" }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
  } catch (err) {
    document.getElementById("bottomStatus").textContent = `数据加载失败: ${err.message}`;
    return;
  }

  window.__orbitwhisperReport = report;
  allOrbits = report.orbits || [];

  const hudData = report.hud_data || {};
  const catStats = hudData.category_stats || {};
  const totalSats = allOrbits.length;

  // Stats
  document.getElementById("totalCount").textContent = totalSats.toLocaleString();
  document.getElementById("updateTime").textContent = (report.generated_at || "").replace("T", " ").substring(0, 19);
  document.getElementById("bottomStatus").textContent = `数据来源: CelesTrak | ${report.generated_at || ""}`;

  // Build UI
  buildCategoryFilters(catStats);
  buildLegend(catStats);

  // Buttons
  document.getElementById("selectAllBtn").addEventListener("click", () => setAllCategories(true));
  document.getElementById("deselectAllBtn").addEventListener("click", () => setAllCategories(false));

  // Search
  document.getElementById("searchInput").addEventListener("input", e => searchSatellites(e.target.value.trim()));

  // Collapsible sections
  document.querySelectorAll(".section-title.clickable").forEach(title => {
    title.addEventListener("click", () => {
      const targetId = title.dataset.toggle;
      const target = document.getElementById(targetId);
      if (target) {
        target.classList.toggle("collapsed");
        const icon = title.querySelector(".toggle-icon");
        if (icon) icon.classList.toggle("open");
      }
    });
  });

  // Upload
  const tleBtn = document.getElementById("tleUploadBtn");
  const tleInput = document.getElementById("tleFileInput");
  if (tleBtn && tleInput) {
    tleBtn.addEventListener("click", () => tleInput.click());
    tleInput.addEventListener("change", () => { tleInput.value = ""; });
  }

  // Detail close
  document.getElementById("detailClose").addEventListener("click", hideDetailPanel);

  // ── Cesium setup ──
  if (!window.Cesium) {
    document.getElementById("bottomStatus").textContent = "Cesium 加载失败";
    return;
  }

  const fallbackToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIzY2ZlZjYxZi1kOGM1LTRhN2MtOGRhNi1mMDBkMWEwNjZlYTkiLCJpZCI6NDA4NzUzLCJpYXQiOjE3NzQ0MDkwMTl9.StFh8-TIWbpATRQHRmTiHtxHGeRWFSc6SNsUcESHmhc";
  Cesium.Ion.defaultAccessToken = window.CESIUM_ACCESS_TOKEN || fallbackToken;

  viewer = new Cesium.Viewer("cesiumContainer", {
    animation: false,
    timeline: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    baseLayerPicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: true,
    terrain: Cesium.Terrain.fromWorldTerrain(),
  });

  window.__orbitwhisperViewer = viewer;
  viewer.scene.globe.enableLighting = true;
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0a0e17");
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 500000;

  // ── Add all satellites ──
  console.time("addSatellites");
  allOrbits.forEach(orbit => addSatelliteEntity(orbit));
  console.timeEnd("addSatellites");

  // Apply initial filter (show only default categories)
  applyFilters();

  // ── Click to select satellite ──
  viewer.selectedEntityChanged.addEventListener(entity => {
    if (!entity) {
      hideDetailPanel();
      return;
    }
    const key = (entity.id || "").toLowerCase();
    const orbit = orbitMap[key];
    if (orbit) {
      showDetailPanel(orbit);
    }
  });

  // Focus satellite (exposed for API use)
  window.focusSatellite = function(keyword) {
    const key = String(keyword || "").trim().toLowerCase();
    if (!key) return false;
    const entity = entityMap[key];
    if (entity) {
      entity.show = true;
      viewer.trackedEntity = entity;
      viewer.flyTo(entity, { duration: 1.2 });
      const orbit = orbitMap[key];
      if (orbit) showDetailPanel(orbit);
      return true;
    }
    return false;
  };

  // Initial camera
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(110, 30, 20000000),
    duration: 0,
  });

  // ── Auto refresh ──
  setInterval(async () => {
    try {
      const latest = await fetch(`./data/daily_report.json?t=${Date.now()}`, { cache: "no-store" }).then(r => r.ok ? r.json() : null);
      if (latest && latest.generated_at !== report.generated_at) {
        window.location.reload();
      }
    } catch (_) {}
  }, 120000);

})();
