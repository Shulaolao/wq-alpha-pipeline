# WQ Workflow v2 — 单进程全链路自适应流水线

> 替代 Phase A/B/C/Retry/D 五个 cron（已全部暂停）。
> 运行在 launchd 服务 `com.hermes.wq-workflow` 下，崩溃自动重启。

## 架构决策

- **为什么放弃 cron**：IS/SC 回测时长时短（3 分钟到 40 分钟），固定时间切片要么空转要么漏结果。
- **为什么单进程**：一个进程内部做自适应轮询，IS 出来立刻进 SC 阶段，不需要等下一个 cron 触发。
- **为什么 launchd**：macOS 的 systemd 等价物。`KeepAlive` + `ThrottleInterval` 30s 自动恢复。

## 工作流流程

```
while active < 20:
    ┌─────────────────────────────────────────┐
    │ 1. 正交分析                              │
    │    · 拉取全部 ACTIVE alpha 表达式         │
    │    · 解析字段使用频率 (17个已验证字段)     │
    │    · 识别 0-usage / 1-usage 字段          │
    │    · 统计结构类型 (减法 vs 乘法)           │
    └──────────────┬──────────────────────────┘
                   ↓
    ┌─────────────────────────────────────────┐
    │ 2. 候选生成 (正交性评分驱动)              │
    │    · 从 0/1-usage 字段构造 ratio 对       │
    │    · 正交性评分 = 字段新颖度 + 结构奖励   │
    │    · 取 Top 3 候选                        │
    └──────────────┬──────────────────────────┘
                   ↓
    ┌─────────────────────────────────────────┐
    │ 3. 全量 IS sim + 自适应轮询              │
    │    · POST sim → 获取 sim_id               │
    │    · 自适应轮询: 15s→60s→120s            │
    │    · 卡 0% 超过 5 分钟 → 自动放弃         │
    │    · IS 4P/3F 或 S<1.25 → 进入调参       │
    └──────────────┬──────────────────────────┘
                   ↓
    ┌─────────────────────────────────────────┐
    │ 4. 调参重试 (IS 失败)                    │
    │    · 最多 5 个变体                        │
    │    · 换动量字段 (vol, adv20, ret_vol...) │
    │    · 调整权重 (0.3/0.5/0.7/0.9)          │
    │    · 每个变体重跑 sim + 自适应轮询        │
    │    · 全失败 → 跳下一个候选                │
    └──────────────┬──────────────────────────┘
                   ↓ (IS PASS)
    ┌─────────────────────────────────────────┐
    │ 5. SC 提交 + 自适应轮询                  │
    │    · POST submit → 轮询 SELF_CORRELATION │
    │    · 轮询间隔: 30s→120s                  │
    │    · SC≥0.7 → 进入 SC 调参               │
    └──────────────┬──────────────────────────┘
                   ↓ (SC < 0.7)
    ┌─────────────────────────────────────────┐
    │ 6. SC 调参重试                            │
    │    · 中性化降维：SECTOR → SUBINDUSTRY    │
    │    · 同表达式换中性化维度                │
    │    · 全失败 → 换全新 ratio 对 (不重叠)   │
    │    · 最多 5 个变体                       │
    │    · 全失败 → 跳下一个候选                │
    └──────────────┬──────────────────────────┘
                   ↓
    ┌─────────────────────────────────────────┐
    │ 7. 正式提交 + 飞书通知 🎉                │
    │    · POST submit → alpha 成为 ACTIVE     │
    │    · 飞书推送: IS/SC/ACTIVE/失败          │
    └──────────────────────────────────────────┘
```

## 关键组件

| 组件 | 文件/路径 | 说明 |
|------|-----------|------|
| 主脚本 | `~/.hermes/scripts/wq_workflow_v2.py` | 全链路流水线 |
| 状态文件 | `~/.wq_workflow_v2.json` | 循环状态、当前候选、正交数据 |
| 日志 | `~/.wq_workflow_v2.log` | 详细日志 |
| launchd plist | `~/Library/LaunchAgents/com.hermes.wq-workflow.plist` | 系统服务定义 |
| Dashboard | `~/wq-dashboard/server.py` + `index.html` | Web 面板端口 8765 |

## 已验证可用字段（17 个）

**fundamental6**: `revenue enterprise_value debt equity operating_income ebitda cap cash sales`

**pv1**: `close volume adv20 returns vwap open high low`

所有其他字段（earnings, book_value, roe, roa, price_to_earnings, beta_capm, market_cap 等 30+）→ WQ 返回 "unknown variable"。

## 飞书推送（0 Token 成本）

使用 Feishu Bot API，不经过 LLM：
1. `POST /open-apis/auth/v3/tenant_access_token/internal` → 获取 token（缓存 2h）
2. `POST /open-apis/im/v1/messages?receive_id_type=open_id` → 发私信

推送事件：
- ✅ IS 通过 → S/F 值
- ✅ SC 通过 → SC 值
- 🎉 新 ACTIVE → 完整表达式
- ⚠️ 调参耗尽 → 失败原因

## 调参策略

### IS 失败时
- 换动量字段：`ts_mean(volume,5)` → `ts_std(returns,5)` → `ts_mean(adv20,5)` → `log(adv20)` → `ts_corr(close,volume,10)`
- 调权重：0.3 / 0.5 / 0.7 / 0.9

### SC 失败时
- **v3.19: 中性化降维** — 先试同表达式在 SECTOR/SUBINDUSTRY 中性化下重跑（消除伪相关），再换字段对
- 换 ratio 对的字段组合
- 保证两对 ratio 字段完全不重叠
- 优先使用 0-usage 字段

## launchd 管理

```bash
# 重启服务
launchctl bootout gui/$(id -u)/com.hermes.wq-workflow 2>/dev/null
sleep 1
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hermes.wq-workflow.plist

# 查看状态
launchctl list com.hermes.wq-workflow

# 查看日志
tail -f ~/.wq_workflow_v2.log

# 查看标准输出/错误
tail -f ~/.wq_workflow_v2_stdout.log
tail -f ~/.wq_workflow_v2_stderr.log
```
