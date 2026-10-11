# 在轨资产动态核保风险评估报告

> 报告编号：{{ report_id }}  
> 生成时间：{{ generated_at_utc }}  
> 承保标的：{{ satellite_name }} (NORAD: {{ norad_id }})

## 1. 承保摘要

- 制造商：{{ manufacturer }}
- 平台（Bus）：{{ bus_type }}
- 设计寿命（年）：{{ design_life_years }}
- 当前风险暴露敞口 EA（USD）：{{ exposure_amount_usd }}
- 预测失效概率 PoF（未来 12 个月）：**{{ pof_12m }}**
- 失效损失率 LGF：**{{ lgf }}**
- 预期损失 EL = PoF × EA × LGF：**{{ expected_loss_usd }} USD**
- 建议纯保费（Pure Premium）：**{{ pure_premium_usd }} USD**

## 2. 生存分析（Cox PH）

下图展示目标卫星未来 12 个月的生存概率曲线：

![12-month Survival Curve]({{ survival_curve_image_path }})

关键结论：
- 12 个月末生存概率：{{ survival_12m }}
- 对应失效概率（PoF）：{{ pof_12m }}
- 风险驱动因子（按危险比 HR）：
{% for factor in top_hazard_factors %}
- {{ factor.name }}: HR={{ factor.hazard_ratio }}
{% endfor %}

## 3. 实证检验（多重共线性 VIF）

| Feature | VIF | Status |
|---|---:|---|
{% for row in vif_table %}
| {{ row.feature }} | {{ row.vif }} | {{ row.status }} |
{% endfor %}

说明：VIF > 10 的变量在建模阶段被视为高度冗余并剔除，用于缓解估计方差膨胀与系数不稳定问题。

## 4. 定损分类与解释性（XGBoost + SHAP）

- 异常后“全损”概率：{{ total_loss_probability }}
- 异常后“能力降级”概率：{{ partial_degradation_probability }}

SHAP 风险因子解释图：

![SHAP Summary]({{ shap_summary_image_path }})

## 5. 核保意见

{{ underwriting_recommendation }}
