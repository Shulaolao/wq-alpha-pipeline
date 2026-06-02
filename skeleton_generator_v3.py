#!/usr/bin/env python3
import re
from collections import defaultdict

SKELETON_CROSS_GATE = 'cross_gate'
SKELETON_DEEP_CASCADE = 'deep_cascade'
SKELETON_NONLINEAR_BREAKER = 'nonlinear_breaker'
SKELETON_TSRANK_CORR = 'tsrank_corr'
SKELETON_SIGN_SWITCH = 'sign_switch'
SKELETON_TREND_BREAK = 'trend_break'
SKELETON_VOL_ADJ = 'vol_adj'
SKELETON_RESIDUAL = 'residual'

PV1_FIELDS = {'close', 'volume', 'adv20', 'returns', 'vwap', 'open', 'high', 'low'}
FUND_FIELDS = {'revenue', 'enterprise_value', 'debt', 'equity', 'operating_income', 'ebitda', 'cap', 'cash', 'sales'}
ALL_FIELDS = PV1_FIELDS | FUND_FIELDS
