'use client';

import { useRef, useEffect, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { FieldUsage } from '@/types/dashboard';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface Props { data: FieldUsage[] }

export default function FieldHeatmap({ data }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [chartWidth, setChartWidth] = useState(0);

  useEffect(() => {
    const el = chartRef.current?.parentElement;
    if (!el) return;
    const update = () => setChartWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const isCompact = chartWidth < 360;
  const isEmpty = !data || data.length === 0;

  useEffect(() => {
    const div = chartRef.current;
    if (!div || isEmpty) return;

    if (!instanceRef.current) {
      instanceRef.current = echarts.init(div, undefined, { renderer: 'canvas' });
    }
    const chart = instanceRef.current;

    const sorted = [...data].sort((a, b) => b.count - a.count);
    const maxCount = Math.max(...sorted.map(d => d.count), 1);

    chart.setOption({
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(15,15,26,0.95)', borderColor: 'rgba(255,255,255,0.08)',
        textStyle: { color: '#e2e8f0', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
        formatter: (params: any) => {
          const p = params[0];
          const total = sorted.reduce((s, d) => s + d.count, 0);
          const pct = total > 0 ? ((p.value / total) * 100).toFixed(1) : '0';
          return `<div style="font-size:12px"><b style="color:#818cf8">${p.name}</b><br/>Used by <b style="color:#34d399">${p.value}</b> alphas <span style="color:#52525b">(${pct}%)</span></div>`;
        },
      },
      grid: { left: isCompact ? 2 : 8, right: isCompact ? 18 : 28, top: 3, bottom: 0, containLabel: true },
      xAxis: {
        type: 'value', axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } },
        axisLabel: { color: '#6b7280', fontSize: isCompact ? 8 : 10, fontFamily: 'JetBrains Mono, monospace' },
      },
      yAxis: {
        type: 'category',
        data: sorted.map(d => d.field).reverse(),
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: '#9ca3af', fontSize: isCompact ? 8 : 10, fontFamily: 'JetBrains Mono, monospace', fontWeight: 500 },
      },
      series: [{
        type: 'bar',
        data: sorted.map((d, i) => ({
          value: d.count,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: `rgba(99,102,241,${(d.count / maxCount) * 0.3})` },
              { offset: 1, color: `rgba(99,102,241,${0.4 + (d.count / maxCount) * 0.6})` },
            ]),
          },
        })).reverse(),
        barWidth: isCompact ? 10 : 14,
        barMaxWidth: 20,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: {
          show: sorted.length <= 8,
          position: 'right', color: '#6b7280',
          fontSize: isCompact ? 9 : 10, fontFamily: 'JetBrains Mono, monospace',
          formatter: (p: any) => `${p.value}`,
        },
      }],
    });

    chart.resize();

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(div);
    return () => ro.disconnect();
  }, [data, isCompact, isEmpty]);

  return (
    <div className="card p-2.5 md:p-4 animate-[fade-in_0.3s_ease-out]">
      <div className="section-header mb-1.5">
        <span className="text-amber-400 text-[10px] shrink-0">▦</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
          Fields
        </h2>
        {!isEmpty && (
          <span className="text-gray-600 font-normal text-[8px] md:text-[10px] truncate">
            {data.length} fields
          </span>
        )}
      </div>

      {isEmpty ? (
        <div className="h-28 md:h-36 flex items-center justify-center text-gray-600 text-[10px] bg-black/10 rounded-lg">
          No field usage data yet
        </div>
      ) : (
        <div ref={chartRef} style={{ height: isCompact ? 120 : 160, width: '100%' }} />
      )}
    </div>
  );
}