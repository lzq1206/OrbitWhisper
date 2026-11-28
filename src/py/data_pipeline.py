import requests
import pandas as pd
from datetime import datetime, timedelta

class SpaceWeatherDataFetcher:
    """
    负责从 NOAA SWPC 拉取真实空间天气数据 (F10.7 和 Kp 指数)
    """
    def __init__(self):
        # NOAA 官方公开 API 接口
        self.f107_url = "https://services.swpc.noaa.gov/products/summary/10cm-flux.json"
        self.kp_url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

    def fetch_f107_flux(self):
        """
        拉取最新的 F10.7 太阳射电流量数据
        """
        print(f"正在拉取 F10.7 数据: {self.f107_url}")
        try:
            response = requests.get(self.f107_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # NOAA 的 F10.7 数据通常是一个字典，包含最新观测值
            # 提取时间戳和 Flux 值
            obs_time = data.get("time_tag")
            flux_value = data.get("flux")
            
            print(f"✅ 成功获取 F10.7: {flux_value} (观测时间: {obs_time})")
            return float(flux_value)
        
        except Exception as e:
            print(f"❌ 拉取 F10.7 数据失败: {e}")
            return None

    def fetch_kp_index(self):
        """
        拉取最新的 Kp 地磁指数数据
        """
        print(f"正在拉取 Kp 指数数据: {self.kp_url}")
        try:
            response = requests.get(self.kp_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # NOAA 的 Kp JSON 格式为列表的列表: [["time_tag", "Kp", "a_running", "station_count"], ["2023-10...", "3.33", ...], ...]
            # 我们提取最新的一条有效数据（跳过表头）
            latest_data = data[-1] 
            obs_time = latest_data[0]
            kp_value = latest_data[1]
            
            print(f"✅ 成功获取 Kp 指数: {kp_value} (观测时间: {obs_time})")
            return float(kp_value)
            
        except Exception as e:
            print(f"❌ 拉取 Kp 指数数据失败: {e}")
            return None

    def get_daily_risk_features(self):
        """
        聚合当前的太空天气特征，输出可供 XGBoost 或精算模型直接使用的 DataFrame
        """
        f107 = self.fetch_f107_flux()
        kp = self.fetch_kp_index()
        
        # 容错处理：如果网络原因拉取失败，使用行业平均安全基准值填补
        if f107 is None: f107 = 90.0 
        if kp is None: kp = 2.0
        
        # 构建特征数据框
        features = pd.DataFrame([{
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "F10_7_index": f107,
            "Kp_index": kp,
            # 衍生特征：当 Kp >= 5 时，定义为地磁暴发生，风险溢价将激增
            "is_geomagnetic_storm": 1 if kp >= 5.0 else 0 
        }])
        
        return features

# ==========================================
# 测试与运行模块
# ==========================================
if __name__ == "__main__":
    print("=== AstroQuant 空间天气数据管道启动 ===")
    fetcher = SpaceWeatherDataFetcher()
    
    # 获取今日真实的太空天气特征
    real_weather_df = fetcher.get_daily_risk_features()
    
    print("\n=== 今日真实空间天气特征提取结果 ===")
    print(real_weather_df.to_string(index=False))
    print("\n提示: 如果 Kp_index >= 5，低轨资产的碰撞概率(PoC)置信区间将大幅扩大，建议引擎上调今日保费。")