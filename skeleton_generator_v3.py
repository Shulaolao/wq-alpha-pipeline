#!/usr/bin/env python3
"""
Advanced Alpha Skeleton Generator v3
=====================================
基于金融逻辑门控与非线性拓扑的骨架生成范式。

4大重构方向:
  A. 跨域条件门控 (Conditional Gating) — 突破同域限制
  B. 深度嵌套算子级联 (Deep Operator Cascading) — 从扁平到嵌套
  C. 非线性时序破坏器 (Non-linear Temporality Breakers) — 脉冲型信号
  D. 主动熵增调度 (Active Entropy Drive) — 结构距离矩阵驱动的主动探索

取代: 硬编码模板填充 → 基于算子拓扑的生成
"""

import re
import math
from collections import defaultdict
from typing import Any

# ─── Skeleton type constants ───
SKELETON_CROSS_GATE = "cross_gate"          # 跨域门控
SKELETON_DEEP_CASCADE = "deep_cascade"      # 深度嵌套级联
SKELETON_NONLINEAR_BREAKER = "nonlinear_breaker"  # 非线性时序破坏
SKELETON_TSRANK_CORR = "tsrank_corr"        # ts_rank(ts_corr(...))
SKELETON_RESIDUAL = "residual"              # 残差/回归模式
SKELETON_SIGN_SWITCH = "sign_switch"        # 符号切换
SKELETON_RANGE_ABS = "range_abs"            # 区间绝对值
SKELETON_MOMENTUM_FILTER = "momentum_filter"  # 动量过滤
SKELETON_VOL_ADJ = "vol_adj"                # 波动率调整
SKELETON_TREND_BREAK = "trend_break"        # 趋势突破

# ─── Cross-domain field groups ───
PV1_FIELDS = {"close", "volume", "adv20", "returns", "vwap", "open", "high", "low"}
FUND_FIELDS = {"revenue", "enterprise_value", "debt", "equity", "operating_income",
               "ebitda", "cap", "cash", "sales"}
PV1_RATIO_FIELDS = {"close", "volume", "adv20", "returns", "vwap"}  # 可用于比率
FUND_RATIO_FIELDS = {"revenue", "enterprise_value", "debt", "equity", "operating_income",
                     "ebitda", "cap", "cash", "sales"}

ALL_FIELDS = PV1_FIELDS | FUND_FIELDS


class StructuralDistanceMatrix:
    """
    骨架结构距离矩阵 — 衡量两个表达式的 AST 拓扑相似度。
    
    使用多重特征向量计算结构相似度:
    - 算子组成直方图
    - 嵌套深度
    - 比率结构分布
    - 时序/截面算子比例
    - 算子序列特征
    
    相似度 > threshold 的骨架被硬裁剪。
    """

    def __init__(self):
        # 历史表达式 → 结构特征向量
        self._feature_cache: dict[str, dict] = {}
    
    def extract_features(self, expr: str) -> dict:
        """从表达式提取结构化特征向量。"""
        if expr in self._feature_cache:
            return self._feature_cache[expr]
        
        features = {}
        
        # 1. 算子频率直方图
        operator_counts = defaultdict(int)
        for op in ['rank', 'ts_mean', 'ts_sum', 'ts_std', 'ts_corr', 'ts_rank',
                    'ts_min', 'ts_max', 'ts_argmin', 'ts_argmax', 'ts_zscore',
                    'ts_delta', 'ts_trend', 'ts_percentile', 'scale', 'log',
                    'sign', 'abs', 'max', 'min', 'ind_neutral', 'ts_cov']:
            operator_counts[op] = len(re.findall(r'\b' + op + r'\(', expr))
        features['operator_counts'] = dict(operator_counts)
        features['total_operators'] = sum(operator_counts.values())
        
        # 2. 嵌套深度 (max paren depth within function args)
        max_depth = 0
        depth = 0
        for ch in expr:
            if ch == '(':
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == ')':
                depth -= 1
        features['max_nesting'] = max_depth
        
        # 3. 比率结构深度
        ratio_matches = re.findall(r'rank\(([^)]+/(?:[^)(]+))*\)', expr)
        features['ratio_depths'] = [len(re.findall(r'\b[a-z_]+\b', r)) for r in ratio_matches]
        
        # 4. 时序vs截面算子比例
        ts_ops = ['ts_mean', 'ts_sum', 'ts_std', 'ts_corr', 'ts_rank',
                   'ts_min', 'ts_max', 'ts_argmin', 'ts_argmax', 'ts_zscore',
                   'ts_delta', 'ts_trend', 'ts_percentile', 'ts_cov']
        n_ts = sum(1 for op in ts_ops if op + '(' in expr)
        n_rank_only = operator_counts.get('rank', 0) - n_ts
        features['ts_ratio'] = n_ts / max(features['total_operators'], 1)
        features['rank_only_count'] = n_rank_only
        
        # 5. 乘号数量 (截面混合度)
        features['mul_count'] = expr.count('*')
        features['plus_count'] = len(re.findall(r'\+', expr))
        features['minus_count'] = len(re.findall(r'(?<![-(])-(?=\s*rank|\s*ts_|[0-9])', expr))
        
        # 6. sign/abs 出现标记 (非线性强度)
        features['has_sign'] = bool(re.search(r'\bsign\(', expr))
        features['has_abs'] = bool(re.search(r'\babs\(', expr))
        
        self._feature_cache[expr] = features
        return features
    
    def structural_similarity(self, expr1: str, expr2: str) -> float:
        """
        计算两个表达式的结构相似度 [0, 1]。
        0 = 完全不同, 1 = 完全相同结构。
        """
        f1 = self.extract_features(expr1)
        f2 = self.extract_features(expr2)
        
        scores = []
        
        # A. 算子组成 Jaccard 相似度
        ops1 = {op for op, c in f1['operator_counts'].items() if c > 0}
        ops2 = {op for op, c in f2['operator_counts'].item