# WQ Alpha Pipeline

> WorldQuant BRAIN 自动化 Alpha 因子挖掘流水线

## 架构

```
wq_workflow_v2.py → launchd (后台守护) → 飞书通知
     ├── 正交分析 (字段/结构/AST 三重去重)
     ├── 候选生成 (乘法骨架 / 减法骨架自适应切换)
     ├── 自适应 IS/SC 轮询 (卡0% 300s自动放弃)
     └── 调参重试 (5变体 × 权重扫描)
```

## 快速启动

```bash
pip install -r requirements.txt

# 直接运行（调试）
python3 wq_workflow_v2.py

# launchd 管理（生产）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hermes.wq-workflow.plist

# Dashboard（监控面板）
cd dashboard && python3 server.py  # 端口 8765
```

## 目录结构

```
wq-alpha-pipeline/
├── wq_workflow_v2.py          # 主工作流（单进程全链路）
├── scripts/
│   └── wq_pipeline.py         # 旧版分段流水线（已废弃）
├── config/
│   ├── com.hermes.wq-workflow.plist   # 工作流 launchd 配置
│   └── com.hermes.wq-dashboard.plist  # 面板 launchd 配置
├── dashboard/
│   ├── server.py               # Flask 后端
│   └── index.html              # 前端面板
├── docs/
│   ├── v2-workflow-architecture.md    # v2 工作流架构
│   └── wq-valid-fields-audit.md       # WQ 字段验证审计
├── requirements.txt
└── README.md
```

## 核心特性

### v3 升级 (2026-05-29)
- **AST 结构树去重**：同骨架（`rank(A/B)*rank(C/D)+W*rank(M)`）在 ACTIVE 中 ≥2 个后自动切换减法型候选
- **时频相容性过滤**：pv1（日频）与 fundamental（季频）禁止混合组 ratio pair → 消除 `S=None` 根因
- **已验证字段对白名单**：优先使用历史 IS PASS 记录中的字段对
- **认知框架 v3**：5 步思考闭环（Pre-Collision → Observe → Reflect → Critique → Execute）

### 自适应轮询
| 阶段 | 初始间隔 | 降频 | 超时 |
|------|---------|------|------|
| Quick SIM | 10s → 30s | 10min | 600s |
| Full IS | 15s → 60s → 120s | 2min/10min | 3600s |
| SC | 30s → 120s | 2min | 3600s |

### 飞书推送
- IS/SC 通过、新 ACTIVE、调参耗尽时自动推送
- 零 LLM Token 成本（纯 Bot API）
- 30s 同事件去重

## WQ 可用字段

共 **17 个** 已验证字段：

| 数据源 | 字段 |
|--------|------|
| **fundamental6** | `revenue`, `enterprise_value`, `debt`, `equity`, `operating_income`, `ebitda`, `cap`, `cash`, `sales` |
| **pv1** | `close`, `volume`, `adv20`, `returns`, `vwap`, `open`, `high`, `low` |

## 配置

通过环境变量配置：

```bash
export EMAIL="your@email.com"
export PASS="your_password"
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
```

或直接编辑脚本中的 `API`, `EMAIL`, `PASS` 常量。