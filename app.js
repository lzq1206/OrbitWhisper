const EXTERNAL_ORBIT_FEED_POLL_MS = 60000;
const EXTERNAL_ORBIT_FEED_TIMEOUT_MS = 15000;
const MIN_ORBIT_PERIOD_SEC = 4800;
const BASE_ORBIT_PERIOD_SEC = 5600;
const ORBIT_PERIOD_ALTITUDE_FACTOR = 12;
const MIN_LAT_SWING_DEG = 2;
const MAX_LAT_SWING_DEG = 22;
const LAT_SWING_SCALE = 0.5;
const LAT_SWING_OFFSET = 6;
const GOLDEN_ANGLE_DEG = 137.5;
const DEFAULT_ALLOWED_ORBIT_FEED_HOSTS = ["platform.leolabs.space"];

function normalizeExternalOrbitPayload(payload) {
  const nestedCandidates = payload?.orbits ?? payload?.orbit ?? payload?.satellites ?? payload?.data;
  const candidates = Array.isArray(payload) ? payload : nestedCandidates;
  if (!Array.isArray(candidates)) return [];
  return candidates
    .map((item, index) => {
      const assetId = String(item?.asset_id || item?.id || item?.norad_id || "").trim();
      const name = String(item?.name || assetId || `EXT-${index + 1}`).trim();
      const lat = Number(item?.lat ?? item?.latitude ?? item?.position?.lat ?? item?.position?.latitude);
      const lng = Number(item?.lng ?? item?.lon ?? item?.longitude ?? item?.position?.lng ?? item?.position?.lon ?? item?.position?.longitude);
      const alt = Number(item?.alt ?? item?.alt_km ?? item?.altitude ?? item?.position?.alt ?? item?.position?.alt_km ?? item?.position?.altitude ?? 550);
      if (!assetId || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
      return { asset_id: assetId, name, lat, lng, alt: Number.isFinite(alt) ? alt : 550 };
    })
    .filter(Boolean);
}

function getExternalOrbitFeedUrl() {
  const queryUrl = new URLSearchParams(window.location.search).get("orbitFeedUrl");
  const configured = typeof window.ORBITWHISPER_ORBIT_FEED_URL === "string"
    ? window.ORBITWHISPER_ORBIT_FEED_URL
    : queryUrl;
  if (!configured) return "";
  try {
    const parsed = new URL(configured, window.location.href);
    if (!["http:", "https:"].includes(parsed.protocol)) return "";
    const configuredHosts = Array.isArray(window.ORBITWHISPER_ALLOWED_ORBIT_FEED_HOSTS)
      ? window.ORBITWHISPER_ALLOWED_ORBIT_FEED_HOSTS
      : DEFAULT_ALLOWED_ORBIT_FEED_HOSTS;
    const allowedHosts = new Set([window.location.hostname, ...configuredHosts].map((h) => String(h || "").toLowerCase()).filter(Boolean));
    if (!allowedHosts.has(parsed.hostname.toLowerCase())) return "";
    return parsed.href;
  } catch (_) {
    return "";
  }
}

async function fetchExternalOrbitFeed(url) {
  if (!url) return [];
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), EXTERNAL_ORBIT_FEED_TIMEOUT_MS);
  try {
    const payload = await fetch(url, { cache: "no-store", signal: controller.signal }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
    return normalizeExternalOrbitPayload(payload);
  } catch (err) {
    console.debug("OrbitWhisper external orbit feed unavailable:", err);
    return [];
  } finally {
    clearTimeout(timeoutId);
  }
}

(async function bootstrap() {
  let report;
  try {
    report = await fetch("./data/daily_report.json", { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
  } catch (err) {
    const summary = document.getElementById("summary");
    summary.innerHTML = `<div class="metric warn">数据加载失败: ${err.message}</div>`;
    return;
  }
  window.__orbitwhisperReport = report;
  const hud = document.getElementById("hud");
  const hudData = report.hud_data || {};
  const isHudAlert = String(hudData.status || "").includes("警报");
  hud.innerHTML = `
    <h1>AstroQuant 风险评估终端</h1>
    <p>资产状态: <span style="color: ${isHudAlert ? "#ff0044" : "#00ff00"};">${hudData.status || "风险监控中"}</span></p>
    <p>高危交会预警: ${Number(hudData.high_risk_count || 0)} 起</p>
    <p>全盘动态保费: ${hudData.total_premium_var || "+0.0%"}</p>
    <p style="font-size: 0.7rem; color: #666;">最后更新: ${hudData.update_time || report.generated_at || "-"}</p>
    <div id="summary"></div>
  `;
  const renderedSummary = document.getElementById("summary");
  renderedSummary.innerHTML = `
    <div class="metric">生成时间: ${report.generated_at}</div>
    <div class="metric">资产数量: ${report.asset_pricing.length}</div>
    <div class="metric warn">高危交会事件: ${report.high_risk_events.length}</div>
  `;

  if (window.Cesium) {
    const fallbackToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIzY2ZlZjYxZi1kOGM1LTRhN2MtOGRhNi1mMDBkMWEwNjZlYTkiLCJpZCI6NDA4NzUzLCJpYXQiOjE3NzQ0MDkwMTl9.StFh8-TIWbpATRQHRmTiHtxHGeRWFSc6SNsUcESHmhc";
    Cesium.Ion.defaultAccessToken = window.CESIUM_ACCESS_TOKEN || fallbackToken;
    const safeAltitudeMeters = (altKm) => {
      const alt = Number(altKm);
      if (!Number.isFinite(alt)) return 550000; // Default to 550 km LEO altitude when data is invalid.
      return Math.max(alt, 0) * 1000;
    };
    const viewer = new Cesium.Viewer("cesiumContainer", {
      animation: false,
      timeline: false,
      geocoder: false,
      homeButton: true,
      sceneModePicker: false,
      baseLayerPicker: false,
      terrain: Cesium.Terrain.fromWorldTerrain(),
    });
    window.__orbitwhisperViewer = viewer;
    viewer.scene.globe.enableLighting = true;

    const entityMap = {};
    const orbitStateMap = {};
    const orbitMap = {};
    let nextOrbitPhaseIndex = 0;
    const DEFAULT_SATELLITE_RADIUS = 0.5;
    const DEFAULT_SATELLITE_COLOR = "#00ffcc";
    const MIN_SATELLITE_RADIUS = 0.1;
    const satelliteStyles = Object.fromEntries(
      (report.satellites || []).map((s) => [
        s.id,
        {
          radius: Number(s.radius || DEFAULT_SATELLITE_RADIUS),
          color: String(s.color || DEFAULT_SATELLITE_COLOR),
          isHighRisk: Boolean(s.is_high_risk),
        },
      ]),
    );
    const ELLIPSOID_SCALE_METERS = 4000; // Visual scaling: map 0.5~0.8 business radius to ~2~3.2 km.
    const wrapLongitude = (value) => ((((value + 180) % 360) + 360) % 360) - 180;
    const clampLatitude = (value) => Math.max(-85, Math.min(85, value));
    const calculateSatellitePosition = (state, time, result) => {
      const currentOrbit = state.orbit;
      // Empirical period (sec): typical LEO is ~80-110 min, linearly stretched by altitude.
      const periodSec = Math.max(
        MIN_ORBIT_PERIOD_SEC,
        BASE_ORBIT_PERIOD_SEC + Number(currentOrbit.alt || 0) * ORBIT_PERIOD_ALTITUDE_FACTOR,
      );
      const elapsedSec = Cesium.JulianDate.secondsDifference(time, state.startTime);
      const phase = ((state.phaseDeg + (elapsedSec * 360) / periodSec) % 360) * (Math.PI / 180);
      // Keep latitude oscillation in a stable 2-22° range to avoid polar jitter.
      const latSwing = Math.max(
        MIN_LAT_SWING_DEG,
        Math.min(MAX_LAT_SWING_DEG, Math.abs(Number(currentOrbit.lat || 0)) * LAT_SWING_SCALE + LAT_SWING_OFFSET),
      );
      const dynamicLat = clampLatitude(Number(currentOrbit.lat || 0) + Math.sin(phase) * latSwing);
      const dynamicLng = wrapLongitude(Number(currentOrbit.lng || 0) + (elapsedSec * 360) / periodSec);
      return Cesium.Cartesian3.fromDegrees(dynamicLng, dynamicLat, safeAltitudeMeters(currentOrbit.alt), Cesium.Ellipsoid.WGS84, result);
    };
    const upsertSatelliteEntity = (orbit) => {
      const key = String(orbit.asset_id || "").toLowerCase();
      if (!key) return;
      const satStyle = satelliteStyles[orbit.asset_id] || {
        radius: DEFAULT_SATELLITE_RADIUS,
        color: DEFAULT_SATELLITE_COLOR,
        isHighRisk: false,
      };
      const radius = Math.max(satStyle.radius, MIN_SATELLITE_RADIUS) * ELLIPSOID_SCALE_METERS;
      orbitMap[key] = orbit;
      if (!orbitStateMap[key]) {
        orbitStateMap[key] = {
          orbit,
          // Golden-angle spacing (~137.5°) reduces initial visual clustering.
          phaseDeg: (nextOrbitPhaseIndex * GOLDEN_ANGLE_DEG) % 360,
          startTime: Cesium.JulianDate.now(),
        };
        nextOrbitPhaseIndex += 1;
        const entity = viewer.entities.add({
          id: orbit.asset_id,
          name: orbit.name,
          position: new Cesium.CallbackProperty((time, result) => calculateSatellitePosition(orbitStateMap[key], time, result), false),
          point: { pixelSize: 9, color: Cesium.Color.CYAN },
          ellipsoid: {
            radii: new Cesium.Cartesian3(radius, radius, radius),
            material: satStyle.isHighRisk ? Cesium.Color.RED.withAlpha(0.75) : Cesium.Color.CYAN.withAlpha(0.6),
          },
          label: {
            text: orbit.asset_id,
            font: "12px sans-serif",
            fillColor: Cesium.Color.WHITE,
            showBackground: true,
            backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6),
          },
        });
        entityMap[key] = entity;
      } else {
        orbitStateMap[key].orbit = orbit;
        const existing = entityMap[key];
        if (existing) {
          existing.name = orbit.name;
          if (existing.label) existing.label.text = orbit.asset_id;
        }
      }
    };
    report.orbits.forEach((orbit) => upsertSatelliteEntity(orbit));
    window.__orbitwhisperAddUploadedOrbit = function addUploadedOrbit(orbit) {
      if (!orbit || !orbit.asset_id) return false;
      upsertSatelliteEntity(orbit);
      return true;
    };
    window.focusSatellite = function focusSatellite(keyword) {
      const key = String(keyword || "").trim().toLowerCase();
      if (!key) return false;
      const orbit = orbitMap[key];
      if (!orbit) return false;
      const entity = entityMap[key];
      if (entity) {
        viewer.trackedEntity = entity;
        viewer.flyTo(entity, { duration: 1.2 });
        return true;
      }
      // Fallback path when entity isn't available yet (for example, while feed is loading).
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(orbit.lng, orbit.lat, safeAltitudeMeters(orbit.alt) + 600000),
        duration: 1.2,
      });
      return true;
    };

    const externalOrbitFeedUrl = getExternalOrbitFeedUrl();
    async function refreshExternalOrbitFeed() {
      if (!externalOrbitFeedUrl) return false;
      const externalOrbits = await fetchExternalOrbitFeed(externalOrbitFeedUrl);
      if (!externalOrbits.length) return false;
      externalOrbits.forEach((orbit) => upsertSatelliteEntity(orbit));
      return true;
    }
    window.__orbitwhisperRefreshExternalOrbitFeed = refreshExternalOrbitFeed;
    refreshExternalOrbitFeed();
    setInterval(refreshExternalOrbitFeed, EXTERNAL_ORBIT_FEED_POLL_MS);

    report.high_risk_events.forEach((evt, idx) => {
      const lon = 90 + idx * 15;
      const lat = -5 + idx * 12;
      viewer.entities.add({
        name: `${evt.asset_id} risk`,
        position: Cesium.Cartesian3.fromDegrees(lon, lat, 500000),
        ellipsoid: {
          radii: new Cesium.Cartesian3(12000, 12000, 12000),
          material: Cesium.Color.RED.withAlpha(0.6),
        },
        label: {
          text: `TCA ${evt.tca_utc}\nmiss ${evt.miss_distance_km} km\nPoC ${evt.poc.toExponential(2)}`,
          font: "11px monospace",
          fillColor: Cesium.Color.RED,
        },
      });
    });

    viewer.zoomTo(viewer.entities);
  } else {
    const fallback = document.getElementById("cesiumContainer");
    fallback.style.background = "radial-gradient(circle at 20% 20%, #16345f, #05070c 65%)";
    fallback.innerHTML = '<div style="position:absolute;left:16px;bottom:16px;color:#b7c8ff;font-family:Arial,sans-serif;">Cesium CDN 不可用：当前显示离线占位视图</div>';
  }

  const firstPricing = report.asset_pricing[0];
  if (firstPricing && window.echarts) {
    const chart = echarts.init(document.getElementById("survivalChart"));
    chart.setOption({
      backgroundColor: "transparent",
      title: { text: `${firstPricing.asset_id} 生存曲线`, textStyle: { color: "#d9e5ff", fontSize: 13 } },
      xAxis: {
        type: "category",
        data: firstPricing.survival_curve.map((p) => p.timeline_days),
        axisLabel: { color: "#9fb2d9" },
      },
      yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: "#9fb2d9" } },
      series: [
        {
          type: "line",
          smooth: true,
          data: firstPricing.survival_curve.map((p) => p.survival_prob),
          lineStyle: { color: "#58a6ff" },
          areaStyle: { color: "rgba(88,166,255,0.25)" },
        },
      ],
    });
  }

  async function checkForReportUpdate(options = {}) {
    try {
      const latest = await fetch(`./data/daily_report.json?t=${Date.now()}`, { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
      const latestGeneratedAt = latest?.generated_at == null ? "" : String(latest.generated_at);
      const currentGeneratedAt = window.__orbitwhisperReport?.generated_at == null ? "" : String(window.__orbitwhisperReport.generated_at);
      if (latestGeneratedAt && latestGeneratedAt !== currentGeneratedAt) {
        if (options.dryRun) return true;
        window.location.reload();
      }
    } catch (err) {
      console.debug("OrbitWhisper refresh check failed:", err);
    }
    return false;
  }

  window.__orbitwhisperCheckForReportUpdate = checkForReportUpdate;
  setInterval(checkForReportUpdate, 120000);
})();
