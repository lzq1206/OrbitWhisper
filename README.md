# OrbitWhisper

OrbitWhisper 是一个面向低轨航天器的高精度空间避碰决策引擎（Spacecraft Conjunction Assessment Engine）项目骨架。项目融合了**物理轨道递推（SGP4）**与**机器学习残差修正（XGBoost）**，并为碰撞风险评估与自动预警提供标准化模块。

## 架构概览（文字架构图）

系统按数据流拆分为 5 个可独立迭代的模块：

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
│   ├── features/
│   ├── models/
│   │   └── ml_corrector.py
│   ├── physics/
│   │   └── sgp4_propagator.py
│   └── main.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 关键依赖

详见 `requirements.txt`：
- 轨道与动力学：`sgp4`, `poliastro`
- 机器学习：`xgboost`, `lightgbm`, `scikit-learn`
- 数据处理：`pandas`, `numpy`
- 工程能力：`requests`, `python-dotenv`, `joblib`

## 核心模块

- `src/data/tle_fetcher.py`: `SpaceTrackClient`，支持登录和按 NORAD ID 拉取最新 TLE
- `src/physics/sgp4_propagator.py`: `OrbitalPropagator`，输出时间序列状态矢量（x/y/z/vx/vy/vz）
- `src/models/ml_corrector.py`: `ResidualPredictor`，多输出 XGBoost 残差预测
- `src/assessment/tca_calculator.py`: Smart Sieve + TCA + 2D PoC 近似计算
- `src/alerts/feishu_bot.py`: `FeishuAlerter`，带超时重试的 Webhook 告警

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

3. **Docker 方式运行**
   ```bash
   docker compose up --build
   ```

## 后续扩展建议

- 在 `src/data/` 增加 NOAA SWPC 与 CDM ETL 任务
- 在 `src/assessment/` 增加更高保真的碰撞概率积分模型
- 在 `src/main.py` 中接入定时调度器（如 APScheduler）实现自动化流水线
> 兼容性说明：`poliastro` 在较新 Python 版本（如 3.11+）上可能存在上游依赖构建限制；当前已在依赖中按 Python 版本进行条件安装，核心 SGP4 流程不受影响。
