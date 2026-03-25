# OrbitWhisper / AstroQuant 3D

`AstroQuant 3D` 是 OrbitWhisper 的 GitHub Pages 可视化终端：把 **高精度避碰决策引擎** 与 **在轨资产精算定价引擎** 合并到同一套 Serverless 流程中。  
系统每天由 GitHub Actions 触发 Python 计算管线，产出静态 JSON/Markdown，再自动部署到 `gh-pages`，前端使用 CesiumJS 进行 3D 地球展示。

---

## 1) Serverless 架构总览

1. **定时计算（GitHub Actions）**
   - 工作流：`.github/workflows/daily_compute.yml`
   - 每日 UTC 定时触发 + 手动触发
   - 安装依赖并执行 `python -m src.engine.json_generator`
2. **后端分析（Python 3.10+）**
   - ETL：`src/engine/data_pipeline.py`
   - 避碰计算骨架：`src/engine/collision_math.py`
   - 精算与生存分析：`src/engine/actuarial_model.py`（调用 `src/models/cox_survival.py`）
   - 产物生成：`src/engine/json_generator.py`
3. **静态托管（GitHub Pages）**
   - 输出到 `data/daily_report.json` 和 `data/daily_report.md`
   - 使用 `peaceiris/actions-gh-pages` 部署仓库根目录到 `gh-pages`
4. **3D 可视化前端**
   - 页面入口：`index.html`
   - 渲染逻辑：`app.js`
   - CesiumJS 负责地球/空间实体展示，ECharts 显示生存曲线

---

## 2) 数学与精算逻辑

### 2.1 碰撞风险层（PoC / TCA）
- 目标输出：
  - `TCA`（最近交会时间）
  - `miss_distance_km`（最近距离）
  - `PoC`（碰撞概率）
- 当前仓库提供的是可运行骨架，使用确定性样例数据输出，便于先打通 CI/CD + 前端链路。
- 后续可替换为：SGP4 轨道递推 + XGBoost 残差修正（来自 `src/models/ml_corrector.py`）。

### 2.2 生存分析与动态定价层
- 核心模型：Cox Proportional Hazards（`lifelines`）
- 失效概率：`PoF = 1 - S(12m)`，其中 `S(t)` 为生存函数
- 精算公式：
  - `EL = PoF × EA × LGF`
  - `PurePremium = EL × (1 + loading)`

### 2.3 面板数据固定效应处理
- 在 `src/engine/actuarial_model.py` 中，`manufacturer` 和 `bus_type` 作为固定效应变量。
- 在 `src/models/cox_survival.py` 中通过 one-hot 哑变量编码（`pd.get_dummies(..., drop_first=True)`）引入模型。
- 这样可以在不改变 Cox 主体形式的情况下，控制不同平台/制造商的结构性差异。

---

## 3) 目录结构（新增 AstroQuant 3D 相关）

```text
OrbitWhisper/
├── .github/workflows/
│   └── daily_compute.yml
├── index.html
├── app.js
├── data/
│   └── daily_report.json             # 由工作流每天生成
├── src/
│   ├── engine/
│   │   ├── data_pipeline.py
│   │   ├── collision_math.py
│   │   ├── actuarial_model.py
│   │   └── json_generator.py
│   ├── models/
│   │   └── cox_survival.py
│   └── ...                           # 现有模块保持不变
└── tests/
```

---

## 4) 本地运行与验证

1. 安装依赖
```bash
python -m pip install -r requirements.txt
```

2. 生成日报 JSON
```bash
python -m src.engine.json_generator
```

3. 启动静态页面（本地预览）
```bash
python -m http.server 8000
# 打开 http://localhost:8000/
```

4. 运行测试
```bash
python -m unittest discover tests
```

---

## 5) GitHub Actions 自动化说明

工作流文件：`.github/workflows/daily_compute.yml`

- 触发：
  - `schedule`: 每 6 小时一次（`00:00 / 06:00 / 12:00 / 18:00 UTC`）
  - `workflow_dispatch`: 手动触发
- 步骤：
  1. **collect-real-tles**：从 Space-Track 拉取真实 TLE（未配置密钥时自动回退）
  2. **compute-and-deploy**：运行 `src.engine` 计算并生成 JSON/Markdown
  3. 发布仓库根目录到 `gh-pages`（网页随仓库改动自动更新）

---

## 6) 外部数据源接入建议（后续）

- 物理/轨道层：Space-Track、Celestrak CDM
- 环境层：NOAA F10.7/Kp
- 资产层：ESA DISCOS / Seradata（或内部资产台账）

当前代码将这些来源预留为可替换的 ETL 接口，先确保仓库在无外部密钥时也能稳定运行。
