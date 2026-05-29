# WQ Alpha Pipeline

> WorldQuant BRAIN 自动化 Alpha 因子挖掘流水线 — 单进程全链路，`launchd` 守护

**当前状态** 🔄 15/20 ACTIVE（2026-05-30）

[![GitHub](https://img.shields.io/badge/GitHub-Shulaolao/wq--alpha--pipeline-181717?logo=github)](https://github.com/Shulaolao/wq-alpha-pipeline)

---

## 架构

```
wq_workflow_v2.py → launchd (后台守护，崩溃自愈) → 飞书 Bot 推送
     ├── 1. 正交分析 — 字段使用频率 + AST 结构去重
     ├── 2. 候选生成 — 正交性评分驱动，乘法/减法骨架自适应
     ├── 3. Quick SIM — P1Y 轻量过滤弱信号
     ├── 4. Full IS  — 全量回测 + 自适应轮询 (15s→60s→120s)
     ├── 5. 调参重试 — 5 变体 × 权重扫描
     ├── 6. SC 提交  — 自适应轮询 (30s→120s)
     └── 7. Loop    — 直到 20 ACTIVE
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
├── wq_workflow_v2.py               # 主工作流 (1343 行)
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
