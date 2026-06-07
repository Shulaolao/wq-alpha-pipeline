'use client';

import { useMemo } from 'react';

interface FieldUsage {
  field: string;
  count: number;
  pct?: number;
}

interface Props {
  data: FieldUsage[];
}

// 字段颜色映射
const FIELD_COLORS: Record<string, string> = {
  revenue: '#818cf8', close: '#34d399', volume: '#f59e0b',
  high: '#22d3ee', low: '#22d3ee', open: '#22d3ee',
  vwap: '#67e8f9', returns: '#f472b6', adv20: '#fb923c',
  cap: '#f472b6', debt: '#a78bfa', equity: '#c084fc',
  enterprise_value: '#e879f9', operating_income: '#f0abfc',
  ebitda: '#d8b4fe', cash: '#fbcfe8', sales: '#fecdd3',
  subindustry: '#9ca3af', sector: '#9ca3af',
};

export default function FieldHeatmap({ data }: Props) {
  const isEmpty = !data || data.length === 0;

  const sorted = useMemo(() => {
    if (isEmpty) return [];
    return [...data].sort((a, b) => b.count - a.count);
  }, [data, isEmpty]);

  const maxCount = useMemo(() => {
    if (isEmpty) return 1;
    return Math.max(...sorted.map(d => d.count), 1);
  }, [sorted, isEmpty]);

  if (isEmpty) {
    return (
      <div className="card p-2.5 md:p-4">
        <div className="section-header mb-1.5">
          <span className="text-amber-400 text-[10px] shrink-0">▦</span>
          <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">Fields</h2>
        </div>
        <div className="h-28 md:h-36 flex items-center justify-center text-gray-600 text-[10px] bg-black/10 rounded-lg">
          No field usage data yet
        </div>
      </div>
    );
  }

  return (
    <div className="card p-2.5 md:p-4 animate-[fade-in_0.3s_ease-out]">
      <div className="section-header mb-2">
        <span className="text-amber-400 text-[10px] shrink-0">▦</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">Fields</h2>
        <span className="text-gray-600 font-normal text-[8px] md:text-[10px] truncate">{data.length} fields</span>
      </div>

      <div className="space-y-0.5 max-h-44 overflow-y-auto pr-1">
        {sorted.map((item) => {
          const pct = maxCount > 0 ? item.count / maxCount : 0;
          const color = FIELD_COLORS[item.field] || '#6b7280';
          return (
            <div key={item.field} className="flex items-center gap-2 py-0.5 group">
              {/* 字段名 */}
              <span
                className="text-[10px] font-mono w-20 md:w-28 shrink-0 truncate"
                style={{ color }}
              >
                {item.field}
              </span>
              {/* 进度条 */}
              <div className="flex-1 h-4 bg-gray-800/60 rounded-sm overflow-hidden relative">
                <div
                  className="h-full rounded-sm transition-all duration-700"
                  style={{
                    width: `${Math.max(pct * 100, 3)}%`,
                    backgroundColor: color + '30',
                    borderRight: `2px solid ${color}`,
                  }}
                />
                <span className="absolute right-1 top-0 text-[9px] font-mono text-gray-500 leading-4">
                  {item.count}
                </span>
              </div>
              {/* 百分比 */}
              <span className="text-[8px] text-gray-700 w-10 text-right shrink-0 font-mono">
                {maxCount > 0 ? ((item.count / maxCount) * 100).toFixed(0) : '0'}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
