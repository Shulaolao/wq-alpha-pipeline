# WQ 字段可用性验证报告

> 最后更新：2026-05-29
> 方法：对每个候选字段执行 `rank(field)` 轻量 sim（P6M），检查是否 ERROR("unknown variable")

## 已验证可用字段（17个）

### fundamental6（财务数据）

| 字段 | 在 ACTIVE 中占用 | 说明 |
|------|-----------------|------|
| `revenue` | 高 (3/15) | 核心财务字段 |
| `enterprise_value` | 中 (2/15) | 企业价值 |
| `debt` | 高 (4/15) | 总负债 |
| `equity` | 中 (3/15) | 股东权益 |
| `operating_income` | 中 (3/15) | 营业利润 |
| `ebitda` | 低 (0/15) | 最稀有的财务字段 |
| `cap` | 低 (1/15) | 市值/资本 |
| `cash` | 低 (0/15) | 现金及等价物 — **新发现** |
| `sales` | 低 (0/15) | 销售收入 — **新发现** |

### pv1（量价数据）

| 字段 | 在 ACTIVE 中占用 | 说明 |
|------|-----------------|------|
| `close` | 高 (9/15) | 收盘价 |
| `volume` | 中 (3/15) | 交易量 |
| `adv20` | 低 (1/15) | 20日均量 |
| `returns` | 低 (2/15) | 收益率 |
| `vwap` | 低 (2/15) | 均价 |
| `open` | 低 (1/15) | 开盘价 |
| `high` | 低 (2/15) | 最高价 |
| `low` | 低 (1/15) | 最低价 |

## 验证为无效的字段（❗❗）

以下所有字段在 WQ FastExpr 引擎中返回 "Attempted to use unknown variable"：

```
earnings, book_value, roe, roa, roic, net_income, ebit, gross_profit,
free_cash_flow, accruals, asset_growth, price_to_earnings, price_to_book,
price_to_sales, price_to_cash_flow, dividend_yield, beta_capm, market_cap,
current_assets, current_liabilities, total_assets, total_liabilities,
cogs, research_development, sg_and_a, intangible_assets, goodwill,
long_term_debt, short_term_debt, working_capital, shares_outstanding,
cap_1d, div_yield, earnings_estimate, eps_estimate, analyst_rating,
recommendation, price_target, implied_volatility, put_call_ratio,
news_sentiment, social_sentiment, credit_score, default_probability
```

## 验证方法

```python
# 单字段验证
payload = {
    "type": "REGULAR",
    "regular": f"rank({field})",
    "settings": {
        "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
        "delay": 1, "decay": 1, "neutralization": "INDUSTRY",
        "truncation": 0.08, "pasteurization": "ON",
        "language": "FASTEXPR",
        "startDate": "2022-01-01", "endDate": "2023-12-31", "testPeriod": "P6M",
    }
}
r = session.post("https://api.worldquantbrain.com/simulations", json=payload)
sim_id = r.headers["Location"].split("/")[-1]
time.sleep(8)
r2 = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}")
data = r2.json()
valid = data.get("status") != "ERROR"
```

## 重要发现

1. **WQ FastExpr 引擎不支持 `dataset/field` 语法**。新数据源（analyst4, model51, model53, model77, fundamental2, sentiment1 等）的字段无法在表达式引擎中使用
2. **168 个数据集中只有 fundamental6（财务）+ pv1（量价）的字段可用**
3. **先验证再使用**：不要假设财务字段名称在 WQ 中有效。必须逐个提交轻量 sim 验证
4. **零占用 ≠ 无效**：`ebitda` 在 15 ACTIVE 中 0 次使用但完全有效。`cash` 和 `sales` 也是后来才被验证的
