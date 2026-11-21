import os
import requests
import pandas as pd
from dotenv import load_dotenv

# 加载本地 .env 文件中的环境变量
load_dotenv()

class SpaceTrackClient:
    """
    Space-Track.org API 客户端
    负责安全登录、会话保持，并批量拉取目标卫星的最新 TLE (Two-Line Element) 数据。
    """
    
    # Space-Track API 基础端点
    LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
    QUERY_BASE_URL = "https://www.space-track.org/basicspacedata/query/class/tle_latest"

    def __init__(self):
        # 强制从环境变量读取凭证，符合 CI/CD 安全规范
        self.username = os.getenv("SPACETRACK_USER")
        self.password = os.getenv("SPACETRACK_PWD")
        
        if not self.username or not self.password:
            raise ValueError("❌ 未找到 Space-Track 凭证！请在 .env 文件或 GitHub Secrets 中设置 SPACETRACK_USER 和 SPACETRACK_PWD。")
        
        # 使用 Session 保持 Cookies，这是 Space-Track 官方强烈建议的做法
        self.session = requests.Session()
        self._login()

    def _login(self):
        """执行登录并保存 Session Cookie"""
        print("🔐 正在连接 Space-Track.org 并进行身份认证...")
        payload = {
            'identity': self.username,
            'password': self.password
        }
        try:
            # Space-Track 登录成功返回 HTTP 200，内容为空或带有成功标记
            response = self.session.post(self.LOGIN_URL, data=payload, timeout=15)
            response.raise_for_status()
            
            # 验证 Cookie 是否成功写入
            if 'spacetrack_session' in self.session.cookies.get_dict():
                print("✅ 身份认证成功！已建立安全会话。")
            else:
                raise ConnectionError("登录失败：账号密码错误或触发了网站的风控验证。")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ 登录 Space-Track 发生网络错误: {e}")
            raise

    def get_latest_tle_by_ids(self, norad_ids: list) -> pd.DataFrame:
        """
        根据 NORAD 目录编号批量拉取最新 TLE，并返回 DataFrame 以供 SGP4 和机器学习模块使用
        :param norad_ids: 卫星编号列表，例如 [25544, 48274] (ISS 和 星链)
        """
        if not norad_ids:
            return pd.DataFrame()

        # 将 ID 列表转换为逗号分隔的字符串
        id_str = ",".join(map(str, norad_ids))
        
        # 构建 RESTful 查询 URL: 
        # /ORDINAL/1 表示只取最新的一条 TLE
        # /FORMAT/json 方便我们直接解析为字典和 DataFrame
        query_url = f"{self.QUERY_BASE_URL}/NORAD_CAT_ID/{id_str}/ORDINAL/1/FORMAT/json"
        
        print(f"🛰️ 正在拉取 {len(norad_ids)} 颗卫星的最新轨道参数...")
        
        try:
            response = self.session.get(query_url, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                print("⚠️ 未找到对应卫星的数据，请检查 NORAD ID 是否正确。")
                return pd.DataFrame()
            
            # 将 JSON 解析为 Pandas DataFrame
            df_tle = pd.DataFrame(data)
            
            # 提取我们最关心的核心列：名称、ID、第一行、第二行、BSTAR 阻力项
            columns_to_keep = ['OBJECT_NAME', 'NORAD_CAT_ID', 'EPOCH', 'TLE_LINE1', 'TLE_LINE2', 'BSTAR']
            df_tle = df_tle[columns_to_keep]
            
            print("✅ TLE 数据拉取并清洗完成！")
            return df_tle
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 拉取 TLE 数据失败: {e}")
            return pd.DataFrame()

    def logout(self):
        """释放服务器资源，遵守 API 使用礼仪"""
        logout_url = "https://www.space-track.org/ajaxauth/logout"
        self.session.get(logout_url)
        self.session.close()
        print("🔒 已安全注销 Space-Track 会话。")

# ==========================================
# 本地测试模块
# ==========================================
if __name__ == "__main__":
    # 测试前，请在当前目录下创建一个 .env 文件，内容如下：
    # SPACETRACK_USER=你的注册邮箱
    # SPACETRACK_PWD=你的登录密码
    
    try:
        client = SpaceTrackClient()
        
        # 测试目标：国际空间站 (25544), 哈勃望远镜 (20580), 一颗星链卫星 (48274)
        target_satellites = [25544, 20580, 48274]
        
        # 拉取数据
        tle_data = client.get_latest_tle_by_ids(target_satellites)
        
        print("\n=== 真实在轨资产 TLE 参数 ===")
        print(tle_data.to_string(index=False))
        
        # 使用完毕后注销
        client.logout()
        
    except Exception as e:
        print(f"\n程序运行中断: {e}")