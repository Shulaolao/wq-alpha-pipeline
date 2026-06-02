# WQ Alpha Pipeline

> WorldQuant BRAIN 自动化 Alpha 因子挖掘流水线 — 单进程全链路，`launchd` 守护

**当前状态** 🔄 15/20 ACTIVE（2026-05-30）

[![GitHub](https://img.shields.io/badge/GitHub-Shulaolao/wq--alpha--pipeline-181717?logo=github)](https://github.com/Shulaolao/wq-alpha-pipeline)

---

## 完整工作流

```mermaid
---
config:
  flowchart:
    curve: basis
    padding: 16
---
graph TD
    %% Node styling
    classDef phase fill:#1e293b,stroke:#6366f1,color:#e2e8f0
    classDef decision fill:#1e293b,stroke:#f59e0b,color:#fbbf24
    classDef action fill:#1e293b,stroke:#34d399,color:#6ee7b7
    classDef endNode fill:#065f46,stroke:#34d399,color:#a7f3d0
    classDef subgraphTitle fill:#0f172a,stroke:#334155,color:#94a3b8

    %% 1. Orthogonality
    subgraph S1["1️⃣ 正交分析"]
        O1[fetch_actives]:::action --> O2[字段频率 + AST 骨架 + ratio pattern family +<br>field quadruple 四元组追踪 (A/B,C/D)]:::action
        O2 --> O3{active_count ≥ 20?}:::decision
        O3 -->|✅ 是| DONE[🏆 TARGET REACHED]:::endNode
    end

    O3 -->|否| S2

    %% 2. Generate
    subgraph S2["2️⃣ 候选生成"]
        G1[MULT 模板已耗尽 ≥50%?]:::decision -->|否| G2[Phase 0: MULT<br>rank(A/B)*rank(C/D)+W*rank(M)]:::action
        G1 -->|是| G3{stuck_batches % 3<br>+ 结构化骨架计数}:::decision
        G3 -->|0| G2
        G3 -->|1| G4[Phase 1: DIRECT_RANK + PURE_ADD<br>零 ratio pair + 零时序]:::action
        G3 -->|2| G5[Phase 2: THREE_TERM + SUB<br>IND_NEUT + RATIO_LAG + PURE_MULT]:::action
        G2 & G4 & G5 --> G6[模板去重 + 取 Top-N]:::action
    end

    G6 -->|for each candidate| S3

    %% 3. Quick Test
    subgraph S3["3️⃣ Quick Test (P1Y)"]
        Q1[_quick_test<br>P1Y 轻量回测<br>P6: HTTP失败→False]:::action --> Q2{S=?}:::decision
        Q2 -->|S=None<br>死对| SKIP[跳过]:::action
        Q2 -->|S &lt; 1.0| FAIL[丢弃]:::action
        Q2 -->|S ≥ 1.0| PASS[通过 → Full IS]:::action
    end

    PASS --> S4
    SKIP --> STUCK
    FAIL --> STUCK

    %% 4. Full IS
    subgraph S4["4️⃣ Full IS"]
        F1[_run_full_sim<br>全量 5Y 回测]:::action --> F2[adaptive_poll<br>15s → 60s → 120s<br>卡300s放弃]:::action
        F2 --> F3{IS status?}:::decision
        F3 -->|PASS<br>fail≤1 pass≥6| F4[✅ 优化策略<br>S≥2.0直接提交<br>&lt;1.3进调参]:::action
        F3 -->|PASS(软)<br>fail≤2 pass≥4<br>&amp;&amp; (S≥1.25<br>或 S≥1.0+F≥0.8)| F5
        F3 -->|TUNE - S强<br>S≥1.25 fail≤2<br>软通过路径| F5
        F3 -->|FAIL| F9[✖ 候选丢弃<br>飞书通知 ⚠️]:::action
        F4 & F5 --> F8[进入 SC<br>飞书通知 ✅]:::action
    end

    F8 --> S5
    F9 --> STUCK

    %% 5. SC
    subgraph S5["5️⃣ SC 提交"]
        S1SC[_run_sc<br>SELF_CORRELATION]:::action --> S2SC[adaptive_poll<br>30s → 120s<br>超时 2h]:::action
        S2SC --> S2SC2[📈 quadruple SC<br>回归数据自动记录<br>(v3.17)]:::action
        S2SC2 --> S3SC{SC < 0.90?}:::decision
        S3SC -->|✅ ≥0.90| S4SC[✅ 提交 → ACTIVE 🎉<br>飞书通知 🎉]:::action
        S3SC -->|❌ &lt;0.90| S5SC[SC 调参重试<br>换字段组合<br>5变体上限]:::action
        S5SC --> S6SC{成功?}:::decision
        S6SC -->|✅ 是| S2SC
        S6SC -->|❌ 否| S7SC[✖ SC 耗尽<br>飞书通知 ⚠️]:::action
    end

    S4SC --> STUCK
    S7SC --> STUCK

    %% 6. Stuck Detection
    subgraph STUCK["6️⃣ 卡死检测"]
        D1{batch 有产出?}:::decision
        D1 -->|✅ 有| D2[stuck = 0]:::action
        D1 -->|❌ 全体失败| D3[stuck += 1]:::action
        D3 --> D4{stuck ≥ 3?}:::decision
        D4 -->|✅ 是| D5[⚠️ 卡死模式<br>跳过零占用字段<br>DIRECT_RANK 优先]:::action
        D4 -->|否| LOOP
    end

    D2 --> LOOP
    D5 --> LOOP
    LOOP[🔄 回到正交分析<br>while 循环]:::action -.-> S1
```

### 7 种骨架类型

| 骨架 | 模式 | Phase | 特点 |
|------|------|-------|------|
| **MULT** | `rank(A/B)*rank(C/D)+W*rank(M)` | 0 | 经典乘法，动量加成，最成熟的 SC 通过模式 |
| **DIRECT_RANK** | `rank(A) ± W*rank(B)` | 1 | 零 ratio pair，零时序算子，S=None 风险最低 |
| **PURE_ADD** | `rank(A/B)+rank(C/D)` | 1 | 纯截面加法，无动量项，避免覆盖不兼容 |
| **PURE_MULT** | `rank(A/B)*rank(C/D)` | 2 | 纯截面乘法，无动量项 |
| **THREE_TERM** | `rank(A/B)+rank(C/D)-W*rank(ts)` | 2 | 三项混合，加法+动量减法 |
| **IND_NEUT** | `ind_neutral(rank(ts_X))+W*rank(F)` | 2 | 行业中性化，减少行业暴露 |
| **SUB** | `rank(A/B)-rank(ts_delta(C,N))` | 2 | 因子增长率减法 |

---

## 架构

```
wq_workflow_v2.py → launchd (后台守护，崩溃自愈) → 飞书 Bot 推送
     ├── 1. 正交分析 — 字段频率 + AST 骨架 + ratio pattern family (numerator/denominator)
     │      └── 新增: ratio pattern family 惩罚 — 同族>1 ACTIVE 时降重 (Audit1)
     ├── 2. 候选生成 — 7 骨架轮换 + MULT 枯竭检测 + pure_mult 放宽 overlap
     ├── 3. Quick SIM — P1Y 轻量过滤 (S=None 跳过 / S<1.0 丢弃)
     │      └── P6: HTTP 失败保守化 → return False
     ├── 4. Full IS  — 全量回测 + 自适应轮询 (15s→60s→120s)
     │      ├── Hard Pass: fail≤1 pass≥6
     │      └── Soft Pass: fail≤2 pass≥4 && (S≥1.25 或 S≥1.0+F≥0.8)
     ├── 5. SC 提交  — 自适应轮询 (30s→120s) + 超时 4h (P7)
     ├── 6. 调参重试 — 救火/策略优化 + SC 调参 (tune 409 幂等 P9)
     ├── 7. 卡死检测 — stuck_batches 统计 + 骨架旋转
     ├── 8. 骨架旋转 — 结构化 7 种骨架计数 (Audit7) + 稀有骨架+2 bonus (Audit4)
     └── 9. Loop    — 直到 20 ACTIVE
```

**Dashboard 监控面板** (端口 8765) 实时读取状态文件。

---

## 快速启动

```bash
pip install -r requirements.txt

# 直接运行（调试）
python3 wq_workflow_v2.py

# launchd 管理（生产）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hermes.wq-workflow.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hermes.wq-dashboard.plist

# 停止
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hermes.wq-workflow.plist

# Dashboard
open http://localhost:8765
```

---

## 目录结构

```
wq-alpha-pipeline/
├── wq_workflow_v2.py               # 主工作流 (2652 行)
│   ├── P1(2026-05-30): 修复 S=None 被误判 IS PASS → 死对候选不再浪费 SC slot
│   ├── P3(2026-05-30): stuck 模式旁路多样性约束，DIRECT_RANK 优先选入
│   ├── P4(2026-05-30): 骨架旋转系统 — MULT 枯竭检测 + 3 Phase 轮换
│   ├── P5(2026-05-30): fitness 补偿软通过 — S≥1.0+F≥0.8 也能进调参
│   ├── P6(2026-06-01): quick_test HTTP 失败保守化 → return False
│   ├── P7(2026-06-01): SC 轮询超时 1h→4h
│   ├── P8(2026-06-01): SC 403 fallback 死代码修复
│   ├── P9(2026-06-01): tune sim POST 409 幂等性
│   ├── P10(2026-06-01): ratio_prefix 骨架感知 — _strip_last_term() 逆序解析
│   ├── P11(2026-06-01): 卡死检测升级 — 任意进度停滞 (35%/15%)
│   ├── P12(2026-06-02): _strip_last_term paren-depth 扫描
│   ├── Audit1: ratio pattern family 惩罚 (numerator/denominator)
│   ├── Audit2: RATIO_PATTERN_STRICT 嵌套 ratio 匹配
│   ├── Audit4: 骨架优先级逆转 — 稀有+2 bonus
│   ├── P6(审计): pure_mult 放宽字段重叠
│   ├── P7(审计): 结构化骨架计数替代 regex
│   ├── P0(6489980): 凭据安全 — 删除硬编码 WQ_PASS/DEEPSEEK_API_KEY
│   ├── P13(2026-06-02): SC 调参 field pair 裂缝 — sales死字段/时频不兼容/_generate_new_ratio_variations 不同步
├── scripts/
│   └── wq_pipeline.py              # 旧版三阶段流水线（已废弃）
├── config/
│   ├── com.hermes.wq-workflow.plist  # 工作流 launchd 配置
│   └── com.hermes.wq-dashboard.plist # 面板 launchd 配置
├── dashboard/
│   ├── server.py                    # Flask 后端 (171 行)
│   └── index.html                   # 暗色主题前端面板 (611 行)
├── docs/
│   ├── v2-workflow-architecture.md  # v2 工作流架构说明
│   └── wq-valid-fields-audit.md     # WQ 字段验证审计
├── requirements.txt
└── README.md
```

---

## 核心特性

### 设计理念

- **替代 cron**：旧版 6 个定时任务 → 1 个后台进程。IS/SC 回测时长 3-40 分钟不等，固定时间切片要么空转要么漏结果。单进程内部自适应轮询，IS 完成立即进 SC。
- **launchd 守护**：macOS 原生服务管理，`KeepAlive` + `ThrottleInterval` 30s 自动恢复，等同于 Linux systemd。
- **自适应轮询**：IS/SC 提交后不等固定时间，从短间隔开始逐级降频（15s → 30s → 60s → 120s），任意进度停滞超时自动放弃（不再仅监禁 0%）。
- **安全**：WQ_PASS / DEEPSEEK_API_KEY 全部走环境变量，无硬编码（P0 凭据安全修复）。

### Skeleton Rotation（2026-05-30 新特性）

字段池饱和时（15 ACTIVE），MULT 骨架的 ratio pair 空间迅速耗尽。新选择逻辑：

1. **Phase 0 — MULT**：常规模式，尝试乘法骨架，模板去重选择
2. **Phase 1 — 无比例骨架**：DIRECT_RANK + PURE_ADD，零 S=None 风险
3. **Phase 2 — 混合探索**：THREE_TERM + IND_NEUT + SUB + PURE_MULT

**MULT 枯竭检测**：当 failed_expressions 包含所有 4 种权重变体（0.3/0.5/0.7/0.9）的 ≥50% 模板时，自动跳过 Phase 0 进入 Phase 1。当 failed_expressions > 20 条时强制旋转。

### 正交分析增强（2026-06-02 审计修复）

| 维度 | 策略 |
|------|------|
| 字段使用频率 | 优先用 0/1 次使用字段构造 ratio 对 |
| ratio pattern family | 追踪 numerator/denominator 家族，同族>1 ACTIVE 时惩罚降重 (Audit1) |
| 嵌套 ratio 匹配 | RATIO_PATTERN_STRICT 支持 `rank(ts_delta(close,5)/ev)` (Audit2) |
| 骨架优先级 | 稀有骨架+2 bonus，替代惩罚主导骨架 (Audit4) |
| PURE_MULT overlap | 允许共享分子不同分母的有限重叠 (审计P6) |
| 骨架旋转计数 | 7种结构化骨架分类替代 regex 不可靠分类 (审计P7) |

### IS 通过标准

| 类型 | fail | pass | Sharpe | Fitness |
|------|------|------|--------|---------|
| Hard Pass | ≤1 | ≥6 | 任意 | 任意 |
| Soft Pass | ≤2 | ≥4 | ≥1.25 | — |
| Soft Pass (补偿) | ≤2 | ≥4 | ≥1.0 | ≥0.8 |

### 骨架优先级逆转（Audit4）

旧版惩罚主导骨架导致结构锁定。新版**奖励稀缺骨架**：
- 稀有骨架类型 → +2~3 bonus
- 主导骨架（占比>2/3） → -2 penalty
- 特殊骨架（IND_NEUT 等） → 额外 +3 bonus

### Quick Test 保守化（P6）

HTTP 请求失败时 → `return False`，不再泄露弱候选进 Full IS。

### SC 超时延长（P7）

繁忙账户 SC 排队可达数小时，轮询超时从 1h 延长至 **4h**。

### Tune 409 幂等（P9）

tune sim POST 返回 409 → 检测重复表达式 → 复用现有 sim_id 继续轮询。

### ratio_prefix 骨架感知提取

_strip_last_term() 演进路线：
1. **P10**: 逆序字符解析替代 rsplit(+) → DIRECT_RANK/THREE_TERM 不再生成畸形表达式
2. **P12**: 改用 paren-depth 逆序扫描 → 修复 ts_corr 嵌套括号被 regex `[^)]+` 截断的 bug

### 卡死检测升级（P11）

旧版仅检测 0% 停滞。新版检测**任意进度停滞**（35%/15% 也触发），加速发现卡死并切换到 DIRECT_RANK 优先模式。

### SC 调参 field pair 裂缝修复（P13 / v3.18）

`_tune_and_retry()` SC 失败分支的 field pair 生成有三项裂缝：

1. **`sales` 死字段**：零覆盖率 S=None，不应进入任何生成池
2. **时频兼容性缺失**：pv1 num × fund den → S=None，必须拆分 fund/pv1 子池
3. **与 `_generate_new_ratio_variations` 不同步**：后者已有时频过滤，前者没有

修复：denoms/nums 拆分为 fund/pv1 子池，pair 生成时通过 `FUND_FIELDS` 分组检查，确保 num/den 同组。

---

## 已验证 WQ 字段（17 个）

```
fundamental6: revenue, enterprise_value, debt, equity, operating_income,
              ebitda, cap, cash, sales
pv1:          close, volume, adv20, returns, vwap, open, high, low
```

---

## 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
|| v3.18 | 2026-06-02 | **_tune_and_retry SC 失败分支 field pair 生成修复（3 项裂缝）**：① 移除 `sales`（零覆盖率 S=None 死字段）；② 新增时间频率兼容性检查（pv1 num × fund den → S=None），将 denoms/nums 拆分为 fund/ pv1 两个子池分别过滤；③ 与 `_generate_new_ratio_variations` 逻辑同步（二者均使用 `FUND_FIELDS` 分组 + time-frequency 过滤） |
|| v3.16 | 2026-06-02 | **field quadruple → SC 关联模型**：从 pair-family 二阶近似升级为 field-level 四元组追踪。`_extract_field_quadruples()` 提取 `rank(A/B)*rank(C/D)` 的四元组 `(A,B,C,D)`；正交分析追踪所有 ACTIVE 的四元组；候选评分时对共享 field pair 的 MULT 表达式施加 -5（精确重叠）/ -2（部分重叠）/ -8（完全复用）惩罚，更精确地预测 WQ SELF_CORRELATION |
| v3.15 | 2026-06-02 | SC 轮询卡死 + Session 泄露 + 提交前健康探测 |
| v3.14 | 2026-06-02 | P7: 骨架旋转结构化计数 + 优先级逆转；P12: _strip_last_term paren-depth 扫描 |
| v3.13 | 2026-06-02 | P0-P2 六项修复：正向激励→反向激励、ratio pattern 嵌套支持、SELF_CORRELATION 四元组频率追踪、pure_mult 字段重叠放宽、骨架旋转结构化分类 |

- 事件：IS/SC 通过、调参成功、新 ACTIVE、调参耗尽、流水线错误
- 零 LLM Token 成本（纯 Bot API）
- 30s 同事件去重
- 通知事件在流程图中以虚线标注

### 认知框架

5 步思考闭环（Pre-Collision → Observe → Reflect → Critique → Execute），严格 JSON Schema 输出。

### 凭据安全（P0）

WQ_PASS / DEEPSEEK_API_KEY 全部通过环境变量注入，无硬编码。`.env` 加载器适配 launchd 环境（`Path.home()` 返回 `/` 修复）。

---

## 状态文件

```
~/.wq_workflow_v2.db      # SQLite 数据库（状态 + 事件 + 日志 + 统计）
~/.wq_workflow_v2.json    # 旧格式，首次启动自动迁移至 .db
~/.wq_workflow_v2.log     # 结构化日志（时间戳|级别|消息）
~/.wq_workflow_v2_stdout.log   # launchd stdout
~/.wq_workflow_v2_stderr.log   # launchd stderr
```

### SQLite 数据库结构

| 表名 | 用途 |
|---|---|
| `workflow_state` | 实时工作流状态（替代 state.json） |
| `alpha_events` | 每个 alpha 全生命周期事件（生成/IS pass/SC pass/提交/失败/优化） |
| `alpha_stats` | 每个 alpha 的最新统计快照 |
| `cumulative_stats` | 全局累计计数器（total_generated / total_is_pass / total_sc_pass / total_submitted / total_failed） |
| `workflow_logs` | 所有 alpha 相关的日志行（INFO / WARN / ERROR） |

---

## 配置

```bash
export WQ_EMAIL="shufengln@gmail.com"
export WQ_PASS="your_password"
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
```

或编辑 `wq_workflow_v2.py` 头部常量。字段在 `ALL_WQ_FIELDS` 中维护，新增需同步更新。

---

## 项目信息

- **仓库**: https://github.com/Shulaolao/wq-alpha-pipeline
- **运行时**: macOS ARM64, Python 3.13 (Anaconda)
- **依赖**: requests, urllib3, flask
- **工作流**: launchd → `com.hermes.wq-workflow`
- **监控**: Dashboard `:8765` + 飞书推送 + cron 晨报 `06:00 CST`
