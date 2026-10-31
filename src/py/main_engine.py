import os
import json
import math
from datetime import datetime, timezone
from sgp4.api import Satrec, WGS84
from sgp4.api import jday

# 假设前面写的模块已经放在同级目录下
# 从我们之前写的模块中导入类 (如果在不同目录，请调整 import 路径)
from data_pipeline import SpaceWeatherDataFetcher
from actuarial_engine import SpaceActuaryEngine
# from tle_fetcher import SpaceTrackClient # 如果配置好了真实账号，可以取消注释

class AstroQuantEngine:
    """
    AstroQuant 主引擎：整合轨道推演、精算定价与 3D 可视化数据导出
    """
    def __init__(self):
        print("🚀 初始化 AstroQuant 主引擎...")
        self.weather_fetcher = SpaceWeatherDataFetcher()
        self.actuary = SpaceActuaryEngine(base_rate=0.06)
        
        # 为了演示闭环，如果没有配置 Space-Track 密码，我们使用预设的著名卫星 TLE
        self.mock_tles = [
            {
                "id": "25544", "name": "ISS (ZARYA)",
                "line1": "1 25544U 98067A   26084.12345678  .00012345  00000-0  23456-3 0  9991",
                "line2": "2 25544  51.6400 123.4567 0005678  45.6789 234.5678 15.50000000567891"
            },
            {
                "id": "48274", "name": "STARLINK-2423",
                "line1": "1 48274U 21044A   26084.23456789  .00001234  00000-0  12345-4 0  9998",
                "line2": "2 48274  53.0500 234.5678 0001234  12.3456 345.6789 15.00000000123452"
            }
        ]

    def _calculate_gmst(self, dt):
        """
        计算格林尼治平恒星时 (GMST)
        用于将地心惯性坐标系 (ECI) 转换为地球固连坐标系 (ECEF/LLA)
        """
        jd = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)[0]
        # 简化版 GMST 计算公式
        t = (jd - 2451545.0) / 36525.0
        gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t**2 - (t**3) / 38710000.0
        return math.radians(gmst % 360)

    def eci_to_lla(self, x, y, z, dt):
        """
        将 ECI (X, Y, Z) 坐标转换为 LLA (纬度, 经度, 高度)
        """
        gmst = self._calculate_gmst(dt)
        
        # 距离与经度计算
        r = math.sqrt(x**2 + y**2)
        lon = math.atan2(y, x) - gmst
        lon = (lon + math.pi) % (2 * math.pi) - math.pi # 归一化到 -180 ~ 180
        
        # 简化版纬度计算 (未考虑地球极扁率的精确迭代，仅供 3D 可视化使用)
        lat = math.atan2(z, r)
        
        # 高度计算 (减去地球平均半径 6371 km)
        alt = math.sqrt(x**2 + y**2 + z**2) - 6371.0
        
        return math.degrees(lat), math.degrees(lon), alt

    def run_daily_pipeline(self, output_path="public/data/daily_report.json"):
        """
        执行每日计算图：天气 -> 轨道 -> 精算 -> JSON
        """
        # 1. 获取空间天气特征
        weather_df = self.weather_fetcher.get_daily_risk_features()
        kp_index = weather_df.iloc[0]['Kp_index']
        is_storm = weather_df.iloc[0]['is_geomagnetic_storm']
        
        # 2. 准备输出数据结构
        report_data = {
            "hud_data": {
                "status": "地磁暴警报：所有低轨资产阻力飙升" if is_storm else "空间天气平稳",
                "high_risk_count": 0,
                "total_premium_var": "+15.0%" if is_storm else "+0.0%",
                "update_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            },
            "satellites": []
        }

        # 3. 遍历卫星进行推演与精算
        now = datetime.now(timezone.utc)
        jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second)
        
        print("🧮 正在并行计算轨道参数与动态保费...")
        for sat_data in self.mock_tles:
            # 物理轨道递推
            satellite = Satrec.twoline2rv(sat_data["line1"], sat_data["line2"])
            e, r, v = satellite.sgp4(jd, fr)
            
            if e != 0:
                print(f"警告: 卫星 {sat_data['id']} 递推错误 (错误码 {e})")
                continue
                
            # ECI 转 LLA
            lat, lon, alt = self.eci_to_lla(r[0], r[1], r[2], now)
            
            # 模拟精算逻辑：地磁暴期间，低高度卫星 (如星链) 的碰撞和坠毁风险剧增
            is_high_risk = is_storm and alt < 600
            if is_high_risk:
                report_data["hud_data"]["high_risk_count"] += 1
                suggested_premium = 85000  # 风险溢价
                color = "#ff0044"          # 红色警报
            else:
                suggested_premium = 50000  # 基础保费
                color = "#00ffcc"          # 青色正常
                
            # 写入单颗卫星节点数据
            report_data["satellites"].append({
                "id": sat_data["id"],
                "name": sat_data["name"],
                "lat": lat,
                "lng": lon,
                "alt": alt / 6371.0, # Globe.gl 喜欢使用地球半径比例
                "radius": 0.5 if not is_high_risk else 0.8,
                "color": color,
                "suggested_premium": suggested_premium
            })

        # 4. 导出 JSON 文件供前端渲染
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 每日计算完成！报告已保存至: {output_path}")

if __name__ == "__main__":
    engine = AstroQuantEngine()
    engine.run_daily_pipeline()