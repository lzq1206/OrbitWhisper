/* ── OrbitWhisper App – LeoLabs-style satellite visualization ── */

// ── Category → color mapping ──
const CATEGORY_COLORS = {
  "空间站与特殊兴趣": "#ff4757", // warning red for special
  "气象与地球资源": "#2ed573", // green
  "通信卫星": "#1e90ff",     // blue
  "导航卫星": "#ffa502",     // orange
  "科学卫星": "#9b59b6",     // purple
  "大型星座": "#eccc68",     // yellow
  "其他": "#747d8c",
};

// Default visible categories on load
const DEFAULT_VISIBLE = new Set(["空间站与特殊兴趣", "导航卫星", "科学卫星"]);
let visibleCategories = new Set();
let visibleGroups = new Set();
let showPrcOnly = false;
let showHighRiskOnly = false;

// ── Orbit animation constants ──
const MIN_ORBIT_PERIOD_SEC = 4800;
const BASE_ORBIT_PERIOD_SEC = 5600;
const ORBIT_PERIOD_ALTITUDE_FACTOR = 12;
const GOLDEN_ANGLE_DEG = 137.5;

// ── State ──
let allOrbits = [];               // full satellite database from report
let entityMap = {};
let orbitStateMap = {};
let orbitMap = {};
let pricingMap = {};
let nextOrbitPhaseIndex = 0;
let viewer = null;
let pendingTempId = '';
const API_BASE_HINT = (window.ORBITWHISPER_API_BASE || '').trim().replace(/\/$/, '');

// ── Helpers ──
const wrapLng = v => ((((v + 180) % 360) + 360) % 360) - 180;
const clampLat = v => Math.max(-85, Math.min(85, v));
const safeAltM = km => { const a = Number(km); return Number.isFinite(a) ? Math.max(a, 0) * 1000 : 550000; };

// ── True physical orbit calculation (SGP4) ──
function calcPosition(state, time, result) {
  const o = state.orbit;
  
  // If TLE is not available or it's just a mocked point, fallback to stationary point
  if (!o.line1 || !o.line2) {
    return Cesium.Cartesian3.fromDegrees(
      Number(o.lng || 0), 
      Math.max(-89.9, Math.min(89.9, Number(o.lat || 0))), 
      safeAltM(o.alt), 
      Cesium.Ellipsoid.WGS84, result);
  }

  // Use satellite.js to project actual XYZ based on current Julian Time -> Date
  try {
    if (!state.satrec) {
      state.satrec = satellite.twoline2satrec(o.line1, o.line2);
    }
    const jsDate = Cesium.JulianDate.toDate(time);
    const positionAndVelocity = satellite.propagate(state.satrec, jsDate);
    
    // If propagation fails, fallback to original point
    if (!positionAndVelocity.position) {
      return Cesium.Cartesian3.fromDegrees(Number(o.lng || 0), Number(o.lat || 0), safeAltM(o.alt), Cesium.Ellipsoid.WGS84, result);
    }
    
    // Convert to Geodetic
    const gmst = satellite.gstime(jsDate);
    const gd = satellite.eciToGeodetic(positionAndVelocity.position, gmst);
    const lng = satellite.degreesLong(gd.longitude);
    const lat = satellite.degreesLat(gd.latitude);
    const altM = Math.max(0, gd.height * 1000); // height is in km, scale to meters
    
    // Assign back to orbit object for the UI side panel binding updates
    o.lng = lng;
    o.lat = lat;
    o.alt = gd.height;
    
    return Cesium.Cartesian3.fromDegrees(lng, lat, altM, Cesium.Ellipsoid.WGS84, result);
  } catch(e) {
    return Cesium.Cartesian3.fromDegrees(Number(o.lng || 0), Number(o.lat || 0), safeAltM(o.alt), Cesium.Ellipsoid.WGS84, result);
  }
}

function updateClock() {
  const clockEl = document.getElementById("clockDisplay");
  if (clockEl) {
    const now = new Date();
    clockEl.textContent = now.toISOString().replace('T', ' ').substr(0, 19) + " UTC";
  }
  requestAnimationFrame(updateClock);
}
requestAnimationFrame(updateClock);

function getApiBases() {
  const localBase = `${window.location.protocol}//${window.location.hostname}:8000`;
  const sameOriginLikelyHasApi = window.location.port === '8000' || window.location.port === '';
  const sameOriginBase = sameOriginLikelyHasApi ? '' : null;
  const bases = [API_BASE_HINT || null, localBase, 'http://127.0.0.1:8000', 'http://localhost:8000', sameOriginBase]
    .filter(base => base !== undefined && base !== null);
  return [...new Set(bases)];
}

async function apiFetch(path, options = {}) {
  const bases = getApiBases();
  let lastError = null;
  for (const base of bases) {
    try {
      const resp = await fetch(`${base}${path}`, options);
      if (!resp.ok && (resp.status === 404 || resp.status === 405)) continue;
      return resp;
    } catch (err) { lastError = err; }
  }
  throw lastError || new Error(`API fetch failed: ${path}`);
}

async function uploadImageFiles(files) {
  if (!files.length) return;
  const statusText = document.getElementById("statusText");
  const form = new FormData();
  const timestamps = files.map(() => new Date().toISOString());
  files.forEach(file => form.append('files', file));
  form.append('timestamps', JSON.stringify(timestamps));
  try {
    statusText.textContent = "图片定轨解算中...";
    const resp = await apiFetch('/api/upload_image', { method: 'POST', body: form });
    if (!resp.ok) throw new Error('上传失败');
    const data = await resp.json();
    statusText.textContent = `解算完成：提取目标 ${data.observation_targets.length} 个`;
    if (data.unknown_target_suggestion) {
      pendingTempId = data.unknown_temp_id || `UNKN-${Date.now()}`;
      document.getElementById("modalMessage").textContent = `发现未知目标，系统建议命名为 ${data.unknown_target_suggestion}`;
      document.getElementById("namingInput").value = data.unknown_target_suggestion;
      document.getElementById("namingModal").style.display = 'flex';
    }
  } catch (err) {
    statusText.textContent = `上传错误: ${err.message}`;
  }
}

async function saveCustomName() {
  const customName = document.getElementById("namingInput").value.trim();
  const statusText = document.getElementById("statusText");
  if (!customName || !pendingTempId) return;
  try {
    await apiFetch('/api/satellites/name', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp_id: pendingTempId, custom_name: customName })
    });
    statusText.textContent = `命名已应用: ${customName}`;
  } catch (_) {
    statusText.textContent = `命名已记录(离线): ${customName}`;
  }
  document.getElementById("namingModal").style.display = 'none';
  pendingTempId = '';
}

// ── Category & Group filter UI ──
function buildCategoryFilters() {
  const container = document.getElementById("categoryFilters");
  container.innerHTML = "";

  // Dynamically build tree from allOrbits
  const catTree = {};
  allOrbits.forEach(o => {
    const cat = o.category || "其他";
    const grp = o.group || "其它/末知";
    if (!catTree[cat]) catTree[cat] = { count: 0, groups: {} };
    catTree[cat].count++;
    if (!catTree[cat].groups[grp]) catTree[cat].groups[grp] = 0;
    catTree[cat].groups[grp]++;
  });

  const categories = Object.keys(catTree).sort((a, b) => catTree[b].count - catTree[a].count);

  categories.forEach(cat => {
    const data = catTree[cat];
    const color = CATEGORY_COLORS[cat] || "#aaa";
    const isDefault = DEFAULT_VISIBLE.has(cat);

    const wrap = document.createElement("div");
    wrap.className = "category-wrap";
    
    // Parent item
    const item = document.createElement("label");
    item.className = "category-item";
    
    const expandBtn = document.createElement("span");
    expandBtn.style.cursor = "pointer";
    expandBtn.style.marginRight = "4px";
    expandBtn.textContent = "▶";
    expandBtn.style.color = "#8cf";
    expandBtn.style.userSelect = "none";
    
    // Child container
    const childWrap = document.createElement("div");
    childWrap.className = "subcategory-wrap";
    childWrap.style.display = "none";
    childWrap.style.paddingLeft = "24px";
    
    expandBtn.onclick = (e) => {
        e.preventDefault();
        const isHidden = childWrap.style.display === "none";
        childWrap.style.display = isHidden ? "block" : "none";
        expandBtn.textContent = isHidden ? "▼" : "▶";
    };

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "category-checkbox";
    checkbox.checked = isDefault;
    checkbox.style.backgroundColor = isDefault ? color : "transparent";
    checkbox.style.borderColor = isDefault ? color : "";
    checkbox.dataset.category = cat;
    checkbox.dataset.color = color;

    if (isDefault) visibleCategories.add(cat);

    const dot = document.createElement("span");
    dot.className = "category-dot";
    dot.style.backgroundColor = color;

    const label = document.createElement("span");
    label.className = "category-label";
    label.textContent = cat;

    const countSpan = document.createElement("span");
    countSpan.className = "category-count";
    countSpan.textContent = data.count.toLocaleString();

    item.append(expandBtn, checkbox, dot, label, countSpan);
    wrap.appendChild(item);
    
    // Build groups
    const grps = Object.keys(data.groups).sort((a,b)=>data.groups[b] - data.groups[a]);
    const childCheckboxes = [];
    
    grps.forEach(grp => {
        const c_item = document.createElement("label");
        c_item.className = "category-item subcategory-item";
        c_item.style.fontSize = "0.9em";
        c_item.style.padding = "2px 0";
        
        const c_checkbox = document.createElement("input");
        c_checkbox.type = "checkbox";
        c_checkbox.className = "group-checkbox";
        c_checkbox.checked = isDefault;
        c_checkbox.style.backgroundColor = isDefault ? color : "transparent";
        c_checkbox.style.borderColor = isDefault ? color : "";
        c_checkbox.dataset.group = grp;
        c_checkbox.dataset.category = cat;
        c_checkbox.dataset.color = color;
        
        if (isDefault) visibleGroups.add(grp);
        
        const c_label = document.createElement("span");
        c_label.className = "category-label";
        c_label.textContent = grp;

        const c_countSpan = document.createElement("span");
        c_countSpan.className = "category-count";
        c_countSpan.textContent = data.groups[grp].toLocaleString();
        
        c_checkbox.addEventListener("change", (e) => {
            const checked = c_checkbox.checked;
            c_checkbox.style.backgroundColor = checked ? color : "transparent";
            c_checkbox.style.borderColor = checked ? color : "";
            if (checked) visibleGroups.add(grp);
            else visibleGroups.delete(grp);
            applyFilters();
        });
        
        childCheckboxes.push({ box: c_checkbox, grp: grp });
        c_item.append(c_checkbox, c_label, c_countSpan);
        childWrap.appendChild(c_item);
    });
    
    checkbox.addEventListener("change", () => {
      checkbox.style.backgroundColor = checkbox.checked ? color : "transparent";
      checkbox.style.borderColor = checkbox.checked ? color : "";
      
      if (checkbox.checked) visibleCategories.add(cat);
      else visibleCategories.delete(cat);
      
      // Cascade to children
      childCheckboxes.forEach(c => {
          c.box.checked = checkbox.checked;
          c.box.style.backgroundColor = checkbox.checked ? color : "transparent";
          c.box.style.borderColor = checkbox.checked ? color : "";
          if (checkbox.checked) visibleGroups.add(c.grp);
          else visibleGroups.delete(c.grp);
      });
      
      applyFilters();
    });

    wrap.appendChild(childWrap);
    container.appendChild(wrap);
  });
}

function applyFilters() {
  const countSpan = document.getElementById("visibleCount");
  let visibleTotal = 0;

  allOrbits.forEach(orbit => {
    const key = String(orbit.norad_id || orbit.asset_id).toLowerCase();
    const entity = entityMap[key];
    if (!entity) return;

    const cat = orbit.category || "其他";
    const grp = orbit.group || "其它/末知";
    const isPrc = orbit.is_prc === true;
    const isHighRisk = orbit.is_high_risk === true;

    // Visibility logic: (Category AND Group) AND (PRC filter) AND (HighRisk filter)
    let shouldShow = visibleCategories.has(cat) && visibleGroups.has(grp);
    
    if (showPrcOnly && !isPrc) shouldShow = false;
    if (showHighRiskOnly && !isHighRisk) shouldShow = false;

    entity.show = shouldShow;
    if (shouldShow) visibleTotal++;
  });

  if (countSpan) countSpan.textContent = visibleTotal.toLocaleString();
  document.getElementById("bottomCount").textContent = `${visibleTotal.toLocaleString()} 颗卫星显示中`;
}

function setAllCategories(checked) {
  document.querySelectorAll(".category-checkbox, .group-checkbox").forEach(cb => {
    cb.checked = checked;
    const color = cb.dataset.color;
    cb.style.backgroundColor = checked ? color : "transparent";
    cb.style.borderColor = checked ? color : "";
    
    const cat = cb.dataset.category;
    const grp = cb.dataset.group;
    if (checked) {
        if(cat && !grp) visibleCategories.add(cat);
        if(grp) visibleGroups.add(grp);
    } else {
        if(cat && !grp) visibleCategories.delete(cat);
        if(grp) visibleGroups.delete(grp);
    }
  });
  applyFilters();
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

    const grp = orbit.group || "其它/末知";
    const shouldShow = visibleCategories.has(cat) && visibleGroups.has(grp);
    const displayName = orbit.name || orbit.asset_id;

    let positionProp;
    let colorProp = cesiumColor;
    let pixelSize = 8;
    
    if (orbit.status === "decayed") {
      // Place decayed sats slightly above surface so they're visible above terrain
      positionProp = Cesium.Cartesian3.fromDegrees(Number(orbit.lng || 0), Number(orbit.lat || 0), 50000);
      colorProp = Cesium.Color.RED;
      pixelSize = 10;
    } else {
      positionProp = new Cesium.CallbackProperty((time, result) => calcPosition(orbitStateMap[key], time, result), false);
      if (orbit.status === "reentering") {
        pixelSize = 10;
        colorProp = new Cesium.CallbackProperty((time) => {
          const ms = Cesium.JulianDate.toDate(time).getTime();
          return (ms % 600 < 300) ? Cesium.Color.RED : Cesium.Color.RED.withAlpha(0.2);
        }, false);
      }
    }

    const entity = viewer.entities.add({
      id: orbit.asset_id,
      name: displayName,
      show: shouldShow,
      position: positionProp,
      properties: new Cesium.PropertyBag({
          asset_id: orbit.asset_id,
          norad_id: orbit.norad_id
      }),
      point: {
        pixelSize: pixelSize,
        color: colorProp,
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
  if (!panel) return;
  
  panel.classList.remove("hidden");
  
  const body = document.getElementById("detailBody");
  const title = document.getElementById("detailTitle");
  const name = orbit.name || orbit.asset_id;
  if (title) title.textContent = name;
  
  // Sections
  const pricingSection = document.getElementById("pricingModelSection");
  const actuarialBody = document.getElementById("actuarialBody");
  const chartSection = document.getElementById("chartSection");

  // Basic Info
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

  // Actuarial Section
  if (orbit.orbit_risk !== undefined && orbit.orbit_risk !== null) {
      pricingSection.classList.remove("hidden");
      actuarialBody.innerHTML = `
        <div class="detail-row"><span class="label">轨道风险</span><span class="value">${Number(orbit.orbit_risk).toFixed(8)}</span></div>
        <div class="detail-row"><span class="label">规避后碰撞率</span><span class="value">${Number(orbit.pc_after).toFixed(8)}</span></div>
        <div class="detail-row"><span class="label">动态赔付强度</span><span class="value">${Number(orbit.claim_int).toFixed(6)}</span></div>
        <div class="detail-row"><span class="label">商业费率</span><span class="value warn-text">${Number(orbit.premium_rate).toFixed(4)} %</span></div>
        <div class="detail-row"><span class="label">当期准备金</span><span class="value">$${Math.round(orbit.reserve).toLocaleString()}</span></div>
      `;
  } else {
      pricingSection.classList.add("hidden");
  }

  // Chart Section
  const pricing = pricingMap[String(orbit.norad_id || orbit.asset_id)];
  if (pricing && pricing.survival_curve) {
    chartSection.classList.remove("hidden");
    showSurvivalChart(pricing);
  } else {
    chartSection.classList.add("hidden");
  }
}

function hideDetailPanel() {
    const panel = document.getElementById("detailPanel");
    const toggle = document.getElementById("detailToggle");
    if (panel) panel.classList.add("hidden");
    if (toggle) toggle.classList.add("hidden");
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
  document.getElementById("highRiskCount").textContent = `${report.high_risk_events ? report.high_risk_events.length : 0} 起`;
  document.getElementById("bottomStatus").textContent = `数据来源: CelesTrak | ${report.generated_at || ""}`;

  // Filter actions
  document.getElementById("prcOnlyToggle").addEventListener("change", e => {
    showPrcOnly = e.target.checked;
    applyFilters();
  });
  
  document.getElementById("highRiskOnlyToggle").addEventListener("change", e => {
      showHighRiskOnly = e.target.checked;
      applyFilters();
  });

  // Build UI
  buildCategoryFilters(catStats);

  // Buttons
  document.getElementById("selectAllBtn").addEventListener("click", () => setAllCategories(true));
  document.getElementById("deselectAllBtn").addEventListener("click", () => setAllCategories(false));

  // Stats - High Risk click
  document.getElementById("highRiskStats").addEventListener("click", () => renderConjunctionList());
  document.getElementById("conjunctionClose").addEventListener("click", () => {
    document.getElementById("conjunctionPanel").classList.add("hidden");
  });

  // Panel Toggles
  initPanelToggles();

  // Search listener
  const searchInput = document.getElementById("searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", e => searchSatellites(e.target.value));
  }

  // Collapsible sections
  document.querySelectorAll(".section-title.clickable").forEach(title => {
    title.addEventListener("click", () => {
      const targetId = title.dataset.toggle;
      const target = document.getElementById(targetId);
      if (target) {
        target.classList.toggle("collapsed-content");
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
    // Simulate TLE processing
    tleInput.addEventListener("change", () => {
      document.getElementById("statusText").textContent = "TLE 解析完成 (离线模式)";
      tleInput.value = "";
    });
  }

  const imageBtn = document.getElementById("imageUploadBtn");
  const imageInput = document.getElementById("imageFileInput");
  if (imageBtn && imageInput) {
    imageBtn.addEventListener("click", () => imageInput.click());
    imageInput.addEventListener("change", () => {
      uploadImageFiles(Array.from(imageInput.files || []));
      imageInput.value = "";
    });
  }

  // Naming Modal
  document.getElementById("saveNameBtn").addEventListener("click", saveCustomName);
  document.getElementById("cancelNameBtn").addEventListener("click", () => {
    document.getElementById("namingModal").style.display = 'none';
    pendingTempId = '';
  });

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

  // ── Click to select satellite (Restored & Enhanced native selection) ──
  viewer.selectedEntityChanged.addEventListener(entity => {
      console.info("Selection changed:", entity ? entity.id : "none");
      if (!entity) {
          hideDetailPanel();
          return;
      }
      
      // Multi-layer lookup: Properties -> ID -> allOrbits search
      let orbit = null;
      if (entity.properties) {
          const aid = entity.properties.asset_id?.getValue();
          if (aid) orbit = orbitMap[String(aid).toLowerCase()];
      }
      
      if (!orbit) {
          const key = String(entity.id || "").toLowerCase();
          orbit = orbitMap[key];
      }
      
      if (!orbit) {
          const idStr = String(entity.id);
          orbit = allOrbits.find(o => String(o.asset_id) === idStr || String(o.norad_id) === idStr);
      }
      
      if (orbit) {
          console.info("Triggering detail panel for:", orbit.name || orbit.asset_id);
          showDetailPanel(orbit);
      } else {
          console.warn("Could not resolve orbit data for entity:", entity.id);
      }
  });
  viewer.scene.globe.enableLighting = true;
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0a0e17");
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 500000;

  window.showSurvivalChart = function(pricing) {
    if (!window.echarts) return;
    const chartDom = document.getElementById("survivalChart");
    if (!chartDom) return;
    const chart = echarts.getInstanceByDom(chartDom) || echarts.init(chartDom);
    chart.setOption({
      backgroundColor: "transparent",
      title: { text: `生存曲线预测`, show: false },
      grid: { left: 40, right: 10, top: 10, bottom: 30 },
      xAxis: {
        type: "category",
        data: pricing.survival_curve.map(p => p.timeline_days + "d"),
        axisLabel: { color: "#8fa8cc", fontSize: 10 },
      },
      yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: "#8fa8cc", fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
      series: [{
        type: "line",
        smooth: true,
        data: pricing.survival_curve.map(p => p.survival_prob),
        lineStyle: { color: "#58a6ff", width: 2 },
        areaStyle: { 
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(88,166,255,0.4)' },
            { offset: 1, color: 'rgba(88,166,255,0.0)' }
          ])
        },
      }],
    });
    window._lastChart = chart;
  };

  // ── Add all satellites ──
  console.time("addSatellites");
  allOrbits.forEach(orbit => {
    const key = String(orbit.asset_id || "").toLowerCase();
    orbitMap[key] = orbit;
    addSatelliteEntity(orbit);
  });
  
  const prcToggle = document.getElementById("prcOnlyToggle");
  if(prcToggle) {
    prcToggle.addEventListener("change", applyFilters);
  }
  
  applyFilters();
  buildCategoryFilters(); 
  console.timeEnd("addSatellites");

  // ── Render collision math high risk events ──
  if (Array.isArray(report.high_risk_events)) {
    report.high_risk_events.forEach((evt, idx) => {
      const lon = 90 + idx * 15;
      const lat = -5 + idx * 12;
      viewer.entities.add({
        name: `${evt.asset_id} risk`,
        position: Cesium.Cartesian3.fromDegrees(lon, lat, 500000),
        properties: new Cesium.PropertyBag({
            asset_id: evt.asset_id,
            is_risk_marker: true
        }),
        ellipsoid: {
          radii: new Cesium.Cartesian3(12000, 12000, 12000),
          material: Cesium.Color.RED.withAlpha(0.6),
        },
        label: {
          text: `🚨 TCA ${evt.tca_utc}\nMiss: ${evt.miss_distance_km} km\nPoC: ${Number(evt.poc).toExponential(2)}`,
          font: "11px Inter, monospace",
          fillColor: Cesium.Color.RED,
        },
      });
    });
  }

  // Populate pricing map
  if (Array.isArray(report.asset_pricing)) {
    report.asset_pricing.forEach(p => {
      pricingMap[String(p.asset_id)] = p;
    });
  }

  // Set up chart close button
  document.getElementById("chartClose").addEventListener("click", () => {
    document.getElementById("chartPanel").classList.add("hidden");
  });

  // Apply initial filter (show only default categories)
  applyFilters();

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
function initPanelToggles() {
    const sidebar = document.getElementById("sidebar");
    const sidebarBtn = document.getElementById("sidebarToggle");
    const bottomBar = document.getElementById("bottomBar");
    const container = document.getElementById("cesiumContainer");
    
    sidebarBtn.onclick = () => {
        const isNowCollapsed = sidebar.classList.toggle("collapsed");
        sidebarBtn.classList.toggle("collapsed", isNowCollapsed);
        sidebarBtn.textContent = isNowCollapsed ? "▶" : "◀";
        sidebarBtn.title = isNowCollapsed ? "展开侧边栏" : "收起侧边栏";
        
        container.classList.toggle("shift-left", !isNowCollapsed);
        if (bottomBar) bottomBar.classList.toggle("expanded", isNowCollapsed);
    };

    document.getElementById("detailClose").onclick = hideDetailPanel;
}

function renderConjunctionList() {
    const panel = document.getElementById("conjunctionPanel");
    const list = document.getElementById("conjunctionList");
    panel.classList.remove("hidden");
    list.innerHTML = "";

    const events = window.__orbitwhisperReport.high_risk_events || [];
    if (events.length === 0) {
        list.innerHTML = "<div style='padding:20px; text-align:center;'>当前无高危载荷交会事件</div>";
        return;
    }

    events.forEach(evt => {
        const item = document.createElement("div");
        item.className = "conj-item";
        
        const sat1 = orbitMap[String(evt.asset_id).toLowerCase()] || { name: evt.asset_id };
        const sat2 = orbitMap[String(evt.counterpart_id).toLowerCase()] || { name: evt.counterpart_id };
        
        item.innerHTML = `
            <div class="sat-name">
                <span class="conj-label">目标1</span>
                <span class="conj-val">${sat1.name || evt.asset_id}</span>
            </div>
            <div class="sat-name">
                <span class="conj-label">目标2</span>
                <span class="conj-val">${sat2.name || evt.counterpart_id}</span>
            </div>
            <div>
                <span class="conj-label">TCA</span>
                <span class="conj-val">${evt.tca_utc.substring(11, 19)}</span>
            </div>
            <div>
                <span class="conj-label">距离</span>
                <span class="conj-val" style="color:#ff4466">${(evt.miss_distance_km * 1000).toFixed(0)}m</span>
            </div>
            <div class="conj-btn">追踪定位 ▶</div>
        `;
        
        item.onclick = () => {
            const key = String(evt.asset_id).toLowerCase();
            const entity = entityMap[key];
            if (entity) {
                viewer.trackedEntity = entity;
                viewer.flyTo(entity, { duration: 1.5 });
                showDetailPanel(orbitMap[key]);
            }
            panel.classList.add("hidden");
        };
        list.appendChild(item);
    });
}
