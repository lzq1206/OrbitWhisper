(async function bootstrap() {
  const report = await fetch("./data/daily_report.json").then((r) => r.json());
  window.__orbitwhisperReport = report;
  const summary = document.getElementById("summary");
  summary.innerHTML = `
    <div class="metric">生成时间: ${report.generated_at}</div>
    <div class="metric">资产数量: ${report.asset_pricing.length}</div>
    <div class="metric warn">高危交会事件: ${report.high_risk_events.length}</div>
  `;

  if (window.Cesium) {
    const fallbackToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIzY2ZlZjYxZi1kOGM1LTRhN2MtOGRhNi1mMDBkMWEwNjZlYTkiLCJpZCI6NDA4NzUzLCJpYXQiOjE3NzQ0MDkwMTl9.StFh8-TIWbpATRQHRmTiHtxHGeRWFSc6SNsUcESHmhc";
    Cesium.Ion.defaultAccessToken = window.CESIUM_ACCESS_TOKEN || fallbackToken;
    const safeAltitudeMeters = (altKm) => {
      const alt = Number(altKm);
      if (!Number.isFinite(alt)) return 550000; // 默认 550km，近似低轨高度，避免无效数据导致实体消失
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

    report.orbits.forEach((orbit) => {
      viewer.entities.add({
        id: orbit.asset_id,
        name: orbit.name,
        position: Cesium.Cartesian3.fromDegrees(orbit.lng, orbit.lat, safeAltitudeMeters(orbit.alt)),
        point: { pixelSize: 9, color: Cesium.Color.CYAN },
        label: {
          text: orbit.asset_id,
          font: "12px sans-serif",
          fillColor: Cesium.Color.WHITE,
          showBackground: true,
          backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6),
        },
      });
    });
    const orbitMap = Object.fromEntries(
      report.orbits.map((orbit) => [orbit.asset_id.toLowerCase(), orbit]),
    );
    window.focusSatellite = function focusSatellite(keyword) {
      const key = String(keyword || "").trim().toLowerCase();
      if (!key) return false;
      const orbit = orbitMap[key];
      if (!orbit) return false;
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(orbit.lng, orbit.lat, safeAltitudeMeters(orbit.alt) + 600000),
        duration: 1.2,
      });
      return true;
    };

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
})();
