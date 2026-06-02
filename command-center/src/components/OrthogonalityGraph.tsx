'use client';

import { useMemo, useRef, useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { HeatmapChart } from 'echarts/charts';
import { TooltipComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([HeatmapChart, TooltipComponent, VisualMapComponent, CanvasRenderer]);

interface NodeData { id: string; expr: string; fields: string[]; field_count: number }
interface EdgeData { source: string; target: string; similarity: number; shared_fields: string[] }
interface OrthogonalityData {
  nodes: NodeData[]; edges: EdgeData[]; node_count: number; edge_count: number;
  sim_min?: number; sim_max?: number; sim_avg?: number;
}
interface Props { data: OrthogonalityData | null; loading?: boolean }

const FIELD_COLORS: Record<string, string> = {
  revenue: '#818cf8', close: '#34d399', volume: '#f59e0b',
  high: '#22d3ee', low: '#22d3ee', open: '#22d3ee',
  vwap: '#67e8f9', returns: '#f472b6', adv20: '#fb923c',
  cap: '#f472b6', debt: '#a78bfa', equity: '#c084fc',
  enterprise_value: '#e879f9', operating_income: '#f0abfc',
  ebitda: '#d8b4fe', cash: '#fbcfe8', sales: '#fecdd3',
};

export default function OrthogonalityGraph({ data, loading }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const echartsRef = useRef<ReactEChartsCore | null>(null);

  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;
    const update = () => setChartWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const isCompact = chartWidth < 400;
  const isMobile = chartWidth < 360;

  const option = useMemo(() => {
    if (!data || data.nodes.length === 0) return null;

    const nodes = data.nodes;
    const ids = nodes.map(n => n.id);
    const n = ids.length;

    const simMap = new Map<string, number>();
    for (const e of data.edges) {
      simMap.set([e.source, e.target].sort().join('::'), e.similarity);
    }

    const sorted = [...nodes].sort((a, b) => b.field_count - a.field_count || a.id.localeCompare(b.id));
    const sortedIds = sorted.map(n => n.id);

    const heatData: [number, number, number][] = [];
    for (let i = 0; i < n; i++) {
      for (let j = 0; j <= i; j++) {
        const id1 = sortedIds[i], id2 = sortedIds[j];
        if (id1 === id2) { heatData.push([j, i, 1]); continue; }
        heatData.push([j, i, simMap.get([id1, id2].sort().join('::')) ?? 0]);
      }
    }

    const shortLen = isCompact ? 5 : 8;
    const shortIds = sortedIds.map(id => id.length > shortLen ? id.slice(0, shortLen) + '…' : id);
    const isDense = n > 8;

    return {
      tooltip: {
        position: 'top',
        backgroundColor: '#18181b',
        borderColor: '#27272a',
        textStyle: { color: '#e2e8f0', fontSize: isCompact ? 10 : 11, fontFamily: 'JetBrains Mono, monospace' },
        formatter: (p: any) => {
          const rowIdx = p.value[1], colIdx = p.value[0];
          const a = sortedIds[rowIdx], b = sortedIds[colIdx];
          const sim = p.value[2];
          if (a === b) return `<b>${a}</b><br/>Fields: ${nodes.find(x => x.id === a)?.fields.join(', ') || ''}`;
          const shared = data.edges.find(e =>
            [e.source, e.target].sort().join('::') === [a, b].sort().join('::')
          )?.shared_fields || [];
          return `<b>${a}</b> ↔ <b>${b}</b><br/>Similarity: <b>${(sim * 100).toFixed(1)}%</b><br/>Shared: ${shared.join(', ') || 'none'}`;
        },
      },
      grid: { left: isCompact ? 50 : 90, right: 3, top: 3, bottom: isCompact ? 5 : 20 },
      xAxis: {
        type: 'category', data: shortIds, splitArea: { show: true },
        axisLabel: {
          rotate: isCompact ? 60 : 45, fontSize: isCompact ? 6 : 8,
          fontFamily: 'JetBrains Mono, monospace', color: '#71717a',
          interval: isDense ? 1 : 0, overflow: 'truncate', width: isCompact ? 40 : 70,
        },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
      yAxis: {
        type: 'category', data: shortIds, splitArea: { show: true },
        axisLabel: {
          fontSize: isCompact ? 6 : 8, fontFamily: 'JetBrains Mono, monospace',
          color: '#71717a', width: isCompact ? 40 : 80, overflow: 'truncate',
        },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
      visualMap: {
        min: 0, max: 1,
        calculable: !isCompact,
        orient: 'horizontal', left: 'center', bottom: 0,
        inRange: {
          color: ['#0f172a', '#1e1b4b', '#312e81', '#4338ca', '#6366f1', '#818cf8', '#a5b4fc', '#c7d2fe'],
          opacity: [0.2, 1],
        },
        textStyle: { color: '#52525b', fontSize: isCompact ? 7 : 9 },
        itemHeight: isCompact ? 40 : 80, itemWidth: isCompact ? 6 : 10,
      },
      series: [{
        type: 'heatmap', data: heatData,
        label: { show: false },
        emphasis: {
          itemStyle: { shadowBlur: 6, shadowColor: 'rgba(99, 102, 241, 0.3)' },
          label: { show: !isDense && !isCompact, formatter: (p: any) => (p.value[2] * 100).toFixed(0) + '%', color: '#fff', fontSize: 9 },
        },
        itemStyle: { borderRadius: 1, borderWidth: isCompact ? 0.5 : 1, borderColor: '#18181b' },
      }],
    };
  }, [data, isCompact]);

  const avgSim = data && data.edges.length > 0
    ? data.edges.reduce((s, e) => s + e.similarity, 0) / data.edges.length
    : 0;

  const isEmpty = !data || data.nodes.length === 0;

  return (
    <div className="card p-2.5 md:p-4 animate-[fade-in_0.3s_ease-out]">
      {/* Header */}
      <div className="section-header mb-1.5 md:mb-2">
        <span className="text-emerald-400 text-[10px] shrink-0">⧉</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
          Orthogonality
        </h2>
        {!isEmpty && (
          <span className="text-gray-600 font-normal text-[8px] md:text-[10px] truncate">
            {data.node_count}α · {data.edge_count}pairs
            <span className="ml-1 hidden sm:inline">avg {(avgSim * 100).toFixed(1)}%</span>
          </span>
        )}
      </div>

      {/* Loading / Empty state */}
      {(!data || loading) && (
        <div style={{ height: isMobile ? 160 : 240 }} className="flex items-center justify-center rounded-lg bg-black/10">
          <div className="flex flex-col items-center gap-2">
            <div className="skeleton w-48 h-2" />
            <div className="skeleton w-32 h-2" />
            <div className="text-gray-600 text-[10px] mt-1">{loading ? 'Loading...' : 'No data'}</div>
          </div>
        </div>
      )}

      {/* Heatmap */}
      {!isEmpty && option && (
        <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden">
          <ReactEChartsCore
            ref={echartsRef}
            echarts={echarts}
            option={option}
            style={{ height: isCompact ? Math.min(240, 32 * data.nodes.length) : Math.min(400, 36 * data.nodes.length), width: '100%' }}
            notMerge lazyUpdate theme="dark"
          />
        </div>
      )}

      {/* Alpha detail rows */}
      {!isEmpty && (
        <>
          <div className={`mt-1 md:mt-2 space-y-px overflow-y-auto transition-all duration-200 ${
            showAll ? 'max-h-48' : 'max-h-20 md:max-h-36'
          }`}>
            {[...data.nodes].sort((a, b) => b.field_count - a.field_count || a.id.localeCompare(b.id)).map(n => {
              const avg = data.edges.filter(e => e.source === n.id || e.target === n.id)
                .reduce((s, e) => s + e.similarity, 0);
              const cnt = data.edges.filter(e => e.source === n.id || e.target === n.id).length;
              const simAvg = cnt > 0 ? avg / cnt : 0;
              return (
                <div key={n.id} className="flex items-center gap-1 text-[8px] md:text-[10px] py-0.5 px-1 rounded hover:bg-white/[0.02] cursor-default">
                  <span className="font-mono text-gray-400 w-12 md:w-20 truncate shrink-0">
                    {n.id.length > (isMobile ? 5 : 8) ? n.id.slice(0, isMobile ? 5 : 8) + '…' : n.id}
                  </span>
                  <span className="text-gray-600 w-4 md:w-5 text-right shrink-0">{n.field_count}</span>
                  <div className="flex-1 flex flex-wrap gap-px min-w-0">
                    {n.fields.slice(0, isMobile ? 3 : 8).map(f => (
                      <span key={f}
                        className="px-1 rounded-sm text-[6px] md:text-[8px] font-mono leading-tight"
                        style={{ backgroundColor: (FIELD_COLORS[f] || '#6b7280') + '18', color: FIELD_COLORS[f] || '#6b7280' }}
                      >{f}</span>
                    ))}
                    {n.fields.length > (isMobile ? 3 : 8) && (
                      <span className="text-gray-700 text-[6px] md:text-[8px]">+{n.fields.length - (isMobile ? 3 : 8)}</span>
                    )}
                  </div>
                  <span className="text-gray-700 w-8 md:w-10 text-right shrink-0 font-mono text-[8px] md:text-[10px]">
                    {(simAvg * 100).toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
          {data.nodes.length > 4 && (
            <button onClick={() => setShowAll(!showAll)}
              className="w-full mt-1 text-[8px] md:text-[9px] text-indigo-400/50 hover:text-indigo-400 transition-colors cursor-pointer">
              {showAll ? '▲ Less' : `▼ ${data.nodes.length} alphas`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
