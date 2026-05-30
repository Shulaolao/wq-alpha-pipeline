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
        O1[fetch_actives]:::action --> O2[字段频率 + AST 骨架分析]:::action
        O2 --> O3{active_count ≥ 20?}:::decision
        O3 -->|✅ 是| DONE[🏆 TARGET REACHED]:::endNode
    end

    O3 -->|否| S2

    %% 2. Generate
    subgraph S2["2️⃣ 候选生成"]
        G1[MULT 模板已耗尽 ≥50%?]:::decision -->|否| G2[Phase 0: MULT<br>rank(A/B)*rank(C/D)+W*rank(M)]:::action
        G1 -->|是| G3{stuck_batches % 3}:::decision
        G3 -->|0| G2
        G3 -->|1| G4[Phase 1: DIRECT_RANK + PURE_ADD<br>零 ratio pair + 零时序]:::action
        G3 -->|2| G5[Phase 2: THREE_TERM + SUB<br>IND_NEUT + RATIO_LAG + PURE_MULT]:::action
        G2 & G4 & G5 --> G6[模板去重 + 取 Top-N]:::action
    end

    G6 -->|for each candidate| S3

    %% 3. Quick Test
    subgraph S3["3️⃣ Quick Test (P1Y)"]
        Q1[_quick_test<br>P1Y 轻量回测]:::action --> Q2{S=?}:::decision
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
        F3 -->|PASS<br>S≥1.25 + 检查| F4[✅ 优化策略<br>S≥2.0直接提交<br>&lt;1.3进调参]:::action
        F3 -->|TUNE| F5[调参重试<br>网格搜权重 + 5种动量]:::action
        F3 -->|FAIL| F6[救火调参<br>换动量 + 换权重<br>5变体上限]:::action
        F4 & F5 & F6 --> F7{成功?}:::decision
        F7 -->|✅ 是| F8[进入 SC]:::action
        F7 -->|❌ 否| F9[✖ 候选丢弃<br>飞书通知 ⚠️]:::action
    end

    F8 --> S5
    F9 --> STUCK

    %% 5. SC
    subgraph S5["5️⃣ SC 提交"]
        S1SC[_run_sc<br>SELF_CORRELATION]:::action --> S2SC[adaptive_poll<br>30s → 120s]:::action
        S2SC --> S3SC{SC &lt; 0.90?}:::decision
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
        D5 --> LOOP
    end

    D2 --> LOOP
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
     ├── 1. 正交分析 — 字段使用频率 + AST 结构去重
     ├── 2. 候选生成 — 7 骨架轮换 + MULT 枯竭检测
     ├── 3. Quick SIM — P1Y 轻量过滤 (S=None 跳过 / S<1.0 丢弃)
     ├── 4. Full IS  — 全量回测 + 自适应轮询 (15s→60s→120s)
     ├── 5. 调参重试 — 救火/策略优化 + SC 调参
     ├── 6. SC 提交  — 自适应轮询 (30s→120s)
     ├── 7. 卡死检测 — stuck_batches 统计 + 骨架旋转
     └── 8. Loop    — 直到 20 ACTIVE
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
├── wq_workflow_v2.py               # 主工作流 (2278 行)
│   ├── P1(2026-05-30): 修复 S=None 被误判 IS PASS → 死对候选不再浪费 SC slot
│   ├── P2(2026-05-30): 骨架优先级统一在 _sort_key 管理，移除生成器预加成失真
│   ├── P3(2026-05-30): stuck 模式旁路多样性约束，DIRECT_RANK 优先选入
│   └── P4(2026-05-30): 骨架旋转系统 — MULT 枯竭检测 + 3 Phase 轮换
├── scripts/
│   └── wq_pipeline.py              # 旧版三阶段流水线（已废弃）
├── config/
│   ├── com.hermes.wq-workflow.plist   # 工作流 launchd 配置
│   └── com.hermes.wq-dashboard.plist  # 面板 launchd 配置
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
- **自适应轮询**：IS/SC 提交后不等固定时间，从短间隔开始逐级降频（15s → 30s → 60s → 120s），卡 0% 超时自动放弃。

### Skeleton Rotation（2026-05-30 新特性）

字段池饱和时（15 ACTIVE），MULT 骨架的 ratio pair 空间迅速耗尽。新选择逻辑：

1. **Phase 0 — MULT**：常规模式，尝试乘法骨架，模板去重选择
2. **Phase 1 — 无比例骨架**：DIRECT_RANK + PURE_ADD，零 S=None 风险
3. **Phase 2 — 混合探索**：THREE_TERM + IND_NEUT + SUB + PURE_MULT

**MULT 枯竭检测**：当 failed_expressions 包含所有 4 种权重变体（0.3/0.5/0.7/0.9）的 ≥50% 模板时，自动跳过 Phase 0 进入 Phase 1。当 failed_expressions > 20 条时强制旋转。

### 正交分析 + AST 去重

| 去重维度 | 策略 |
|---------|------|
| 字段使用频率 | 优先用 0/1 次使用字段构造 ratio 对 |
| 结构骨架 | 同骨架（`rank(A/B)*rank(C/D)+W*rank(M)`）超过 2 个自动切减法型 |
| 时频相容 | `pv1`（日频）与 `fundamental`（季频）禁止直接混合 ratio |
| 已验证白名单 | 优先用历史 IS PASS 字段对 |

### 已验证 WQ 字段（17 个）

```
fundamental6: revenue, enterprise_value, debt, equity, operating_income,
              ebitda, cap, cash, sales
pv1:          close, volume, adv20, returns, vwap, open, high, low
```

### 飞书 Bot 推送

- 事件：IS/SC 通过、新 ACTIVE、调参耗尽、流水线错误
- 零 LLM Token 成本（纯 Bot API）
- 30s 同事件去重
- 通知事件在流程图中以虚线标注

### 认知框架

5 步思考闭环（Pre-Collision → Observe → Reflect → Critique → Execute）
严格 JSON Schema 输出，见 `refs/cognitive-framework-v3.md`。

---

## 状态文件

```json
~/.wq_workflow_v2.json    # 实时流水线状态（ACTIVE 列表、阶段、候选、统计）
~/.wq_workflow_v2.log     # 结构化日志（时间戳|级别|消息）
~/.wq_workflow_v2_stdout.log   # launchd stdout
~/.wq_workflow_v2_stderr.log   # launchd stderr
```

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