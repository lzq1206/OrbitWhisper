# OrbitWhisper

OrbitWhisper 是一个面向航天保险与在轨运营场景的风险引擎项目骨架。当前版本同时覆盖：

- **空间避碰评估**（SGP4 轨道递推 + TCA/PoC）
- **在轨资产精算与动态风险评估**（VIF 实证检验 + Cox 生存分析 + EL 定价）

目标是为核保人与风控团队提供动态核保定价、在轨资产定损和风险量化报告能力。

## 架构概览（文字架构图）

系统按数据流拆分为 7 个可独立迭代模块：

1. **Data Ingestion (`src/data/`)**
   - 拉取 Space-Track TLE 数据、NOAA 空间天气数据（F10.7/Kp）
   - 标准化解析与清洗，统一 UTC 时间戳
2. **Propagation & Features (`src/physics/`, `src/features/`)**
   - 使用 SGP4 对目标对象进行 72 小时轨道递推
   - 提取 BSTAR、轨道几何、空间天气特征
3. **AI Error Correction (`src/models/`)**
   - 训练多输出 XGBoost 模型，预测 ΔX/ΔY/ΔZ 递推残差
   - 支持模型保存/加载与在线推理
4. **Conjunction Assessment (`src/assessment/`)**
   - Smart Sieve 快速筛选候选碰撞对
   - 计算 TCA（最近交会时间）、Miss Distance、PoC
5. **Alerting (`src/alerts/`)**
    - 依据阈值（PoC > 1e-4 且 miss distance < 1 km）触发高危告警
    - 通过飞书 Custom Bot Webhook 推送 Markdown 卡片
6. **Empirical Testing (`src/empirical/`)**
   - 对空间天气与轨道风险特征进行多重共线性诊断（VIF）
   - 自动剔除高冗余解释变量（默认 VIF > 10）
7. **Actuarial Survival & Pricing (`src/models/cox_survival.py`)**
   - 基于 lifelines 的 Cox 比例风险模型估计在轨失效风险
   - 输出未来 12 个月失效概率（PoF）并计算 EL 与纯保费

## 目录结构

```text
OrbitWhisper/
├── src/
│   ├── alerts/
│   │   └── feishu_bot.py
│   ├── assessment/
│   │   └── tca_calculator.py
│   ├── data/
│   │   ├── tle_fetcher.py
│   │   └── tle_parser.py
│   ├── empirical/
│   │   └── vif_tester.py
│   ├── features/
│   ├── models/
│   │   └── ml_corrector.py
│   │   └── cox_survival.py
│   ├── physics/
│   │   └── sgp4_propagator.py
│   ├── reporting/
│   │   └── templates/
│   │       └── underwriting_report_template.md
│   └── main.py
├── tests/
│   ├── test_vif_tester.py
│   └── test_cox_survival.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 关键依赖

详见 `requirements.txt`：
- 轨道与动力学：`sgp4`, `poliastro`
- 机器学习：`xgboost`, `lightgbm`, `scikit-learn`
- 生存分析与实证统计：`lifelines`, `statsmodels`
- 数据处理：`pandas`, `numpy`
- 报告生成：`jinja2`, `weasyprint`
- 工程能力：`requests`, `python-dotenv`, `joblib`

## 核心模块

- `src/data/tle_fetcher.py`: `SpaceTrackClient`，支持登录和按 NORAD ID 拉取最新 TLE
- `src/physics/sgp4_propagator.py`: `OrbitalPropagator`，输出时间序列状态矢量（x/y/z/vx/vy/vz）
- `src/models/ml_corrector.py`: `ResidualPredictor`，多输出 XGBoost 残差预测
- `src/empirical/vif_tester.py`: `VIFTester`，VIF 检验与高共线特征剔除
- `src/models/cox_survival.py`: `OrbitCoxSurvivalModel`，Cox 生存分析、PoF/EL/纯保费计算
- `src/assessment/tca_calculator.py`: Smart Sieve + TCA + 2D PoC 近似计算
- `src/alerts/feishu_bot.py`: `FeishuAlerter`，带超时重试的 Webhook 告警
- `src/reporting/templates/underwriting_report_template.md`: 核保报告 Markdown 模板（可由 Jinja2 注入渲染）

## 精算引擎实施阶段（Phase）

### Phase 1: 精算数据湖构建（`src/data/`）
- 拼接卫星静态承保特征、TLE 轨道特征、空间天气时间序列
- 构建可用于实证研究与生存分析的 Panel Data

### Phase 2: 实证检验与特征工程（`src/empirical/`）
- `VIFTester.compute_vif()` 输出特征共线性报告
- `VIFTester.drop_high_vif()` 自动迭代剔除高 VIF 特征

### Phase 3: 生存分析与定损定价（`src/models/`）
- `OrbitCoxSurvivalModel.fit()` 支持连续风险因子 + 制造商/平台固定效应哑变量
- `predict_pof_12m()` 输出 12 个月 PoF
- 按精算公式计算：`EL = PoF × EA × LGF`

### Phase 4: 自动化核保报告（`src/reporting/`）
- 通过 Jinja2 将模型结果注入报告模板
- 可进一步用 WeasyPrint 渲染为 PDF 供核保审核

## 关键公式

- **Expected Loss**: `EL = PoF × EA × LGF`
- **Pure Premium**: `PurePremium = EL × (1 + loading)`

## 本地 Linux 部署指南

1. **准备环境变量**
   ```bash
   cp .env.example .env
   # 编辑 .env，填入 Space-Track 与 Feishu 配置
   ```

2. **本地 Python 方式运行**
    ```bash
    python -m pip install -r requirements.txt
    python -m src.main
    ```

3. **运行测试**
   ```bash
   python -m unittest discover tests
   ```

4. **Docker 方式运行**
    ```bash
    docker compose up --build
    ```

## 后续扩展建议

- 在 `src/data/` 增加 NOAA SWPC 与 CDM ETL 任务
- 在 `src/assessment/` 增加更高保真的碰撞概率积分模型
- 在 `src/main.py` 中接入定时调度器（如 APScheduler）实现自动化流水线
> 兼容性说明：`poliastro` 在较新 Python 版本（如 3.11+）上可能存在上游依赖构建限制；当前已在依赖中按 Python 版本进行条件安装，核心 SGP4 流程不受影响。
