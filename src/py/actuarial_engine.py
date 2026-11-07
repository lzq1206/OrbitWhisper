import numpy as np
import pandas as pd
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.tools import add_constant
from lifelines import CoxPHFitter
import warnings

# 忽略一些生存分析库中常见的弃用警告以保持输出整洁
warnings.filterwarnings("ignore")

class SpaceActuaryEngine:
    """
    在轨资产动态精算与定价引擎
    融合了 VIF 共线性检验、Cox 生存分析以及规避机动（CAM）预期损失模型。
    """
    
    def __init__(self, base_rate=0.06):
        """
        初始化引擎
        :param base_rate: 行业平均基础费率 (例如 6%)
        """
        self.base_rate = base_rate
        self.cox_model = CoxPHFitter(penalizer=0.1) # 引入正则化惩罚项，防止过拟合
        self.is_fitted = False

    def check_collinearity(self, df_features, threshold=10.0):
        """
        [核心实证] VIF 检验：剔除高度共线性的空间天气和轨道特征
        """
        print("--- 正在执行方差膨胀因子 (VIF) 检验 ---")
        df_with_const = add_constant(df_features)
        
        while True:
            vif_data = pd.DataFrame()
            vif_data["Feature"] = df_with_const.columns
            vif_data["VIF"] = [variance_inflation_factor(df_with_const.values, i) 
                               for i in range(df_with_const.shape[1])]
            
            # 排除常数项后，找到最大的 VIF 值
            max_vif_row = vif_data[vif_data["Feature"] != "const"].sort_values(by="VIF", ascending=False).iloc[0]
            
            if max_vif_row["VIF"] > threshold:
                print(f"剔除共线性特征: {max_vif_row['Feature']} (VIF = {max_vif_row['VIF']:.2f})")
                df_with_const = df_with_const.drop(columns=[max_vif_row["Feature"]])
            else:
                break
                
        final_features = df_with_const.drop(columns=["const"]).columns.tolist()
        print(f"VIF 检验通过。保留的独立特征: {final_features}\n")
        return df_features[final_features]

    def fit_survival_model(self, historical_data, duration_col='lifespan_months', event_col='is_failure'):
        """
        [精算基石] 拟合 Cox 比例风险模型，计算基础失效概率 (PoF)
        """
        # 提取特征并进行 VIF 检验
        feature_cols = [c for c in historical_data.columns if c not in [duration_col, event_col, 'sat_id']]
        clean_features = self.check_collinearity(historical_data[feature_cols])
        
        # 拼接用于生存分析的最终数据集
        survival_df = pd.concat([clean_features, historical_data[[duration_col, event_col]]], axis=1)
        
        print("--- 正在拟合 Cox 比例风险模型 ---")
        self.cox_model.fit(survival_df, duration_col=duration_col, event_col=event_col)
        self.is_fitted = True
        print("模型拟合完成。底层风险系数 (Log-Hazards):")
        print(self.cox_model.params_.to_frame().T, "\n")

    def calculate_cam_cost(self, asset_value, dv_used, dv_total, downtime_revenue_loss):
        """
        [定损模型] 计算单次规避机动 (CAM) 的财务损失
        公式: L_CAM = (dv_used / dv_total) * Asset_Value + Downtime_Loss
        """
        fuel_depreciation = (dv_used / dv_total) * asset_value
        total_cam_cost = fuel_depreciation + downtime_revenue_loss
        return total_cam_cost

    def decision_and_pricing(self, sat_id, poc, poc_residual, asset_value, dv_used, dv_total, downtime_loss, current_month):
        """
        [动态定价] 基于预期损失最小化原则，输出避碰决策与风险溢价
        """
        if not self.is_fitted:
            raise ValueError("请先调用 fit_survival_model() 拟合历史数据。")

        # 1. 计算机动成本 L_CAM
        l_cam = self.calculate_cam_cost(asset_value, dv_used, dv_total, downtime_loss)
        
        # 2. 计算两种决策下的预期损失 (Expected Loss)
        # 不机动：直接承受原始 PoC 的全损风险
        el_no_cam = poc * asset_value 
        # 机动：承受确定的机动成本，外加机动后残余 PoC 的全损风险
        el_cam = l_cam + (poc_residual * asset_value)

        # 3. 决策逻辑
        decision = "EXECUTE_CAM" if el_cam < el_no_cam else "IGNORE"
        optimized_el = min(el_no_cam, el_cam)

        # 4. 计算参数化保险的动态保费 (纯保费 Pure Premium)
        # 提取 Cox 模型预测的特定时间窗口基础失效概率
        # 这里简化处理，假设当前特征为均值，提取基准生存率
        baseline_survival = self.cox_model.baseline_survival_
        # 获取最接近当前月份的生存概率
        idx = (np.abs(baseline_survival.index - current_month)).argmin()
        s_t = baseline_survival.iloc[idx, 0]
        baseline_pof = 1 - s_t 

        # 最终保费 = 基础保费 + 特定事件带来的预期损失溢价
        base_premium = asset_value * self.base_rate * baseline_pof
        dynamic_premium = base_premium + optimized_el

        return {
            "sat_id": sat_id,
            "decision": decision,
            "L_CAM": round(l_cam, 2),
            "EL_No_CAM": round(el_no_cam, 2),
            "EL_CAM": round(el_cam, 2),
            "baseline_PoF": round(baseline_pof, 6),
            "suggested_premium": round(dynamic_premium, 2)
        }

# ==========================================
# 测试与运行模块 (Mock Data)
# ==========================================
if __name__ == "__main__":
    # 1. 生成模拟的面板数据 (历史卫星故障与空间天气记录)
    np.random.seed(42)
    n_samples = 500
    mock_history = pd.DataFrame({
        'sat_id': [f"SAT_{i}" for i in range(n_samples)],
        # 空间天气特征 (故意制造共线性，F10.7 和 Sunspot_Number 高度相关)
        'F10_7_index': np.random.normal(120, 30, n_samples),
        'Sunspot_Number': np.random.normal(0, 1, n_samples), 
        'Kp_index': np.random.uniform(0, 9, n_samples),
        # 轨道特征
        'altitude_km': np.random.normal(550, 50, n_samples),
        'inclination_deg': np.random.normal(53, 5, n_samples),
        # 生存分析目标变量
        'lifespan_months': np.random.exponential(60, n_samples).clip(1, 120),
        'is_failure': np.random.binomial(1, 0.3, n_samples) # 30%的记录为失效
    })
    
    # 手动让黑子数与 F10.7 高度相关，测试 VIF 剔除功能
    mock_history['Sunspot_Number'] = mock_history['F10_7_index'] * 0.8 + np.random.normal(0, 5, n_samples)

    # 2. 初始化引擎并拟合模型
    actuary_engine = SpaceActuaryEngine(base_rate=0.06)
    actuary_engine.fit_survival_model(mock_history)

    # 3. 针对某一颗面临空间碎片威胁的商业卫星进行定价
    print("--- 正在执行单星高危交会事件精算 ---")
    assessment_result = actuary_engine.decision_and_pricing(
        sat_id="STARLINK-9999",
        poc=0.005,                # 官方预警碰撞概率 0.5%
        poc_residual=0.00001,     # 机动后残余概率
        asset_value=1_000_000,    # 卫星重置成本 100 万美元
        dv_used=0.5,              # 本次规避需要消耗 0.5 m/s 的速度增量
        dv_total=150.0,           # 卫星全寿命总速度增量 150 m/s
        downtime_loss=2000,       # 规避期间通信中断损失 2000 美元
        current_month=24          # 该卫星目前在轨第 24 个月
    )

    import json
    print(json.dumps(assessment_result, indent=4, ensure_ascii=False))