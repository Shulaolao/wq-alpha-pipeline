'use client';

import { useRef, useEffect } from 'react';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { FieldUsage } from '@/types/dashboard';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface FieldHeatmapProps {
  data: FieldUsage[];
}

export default function FieldHeatmap({ data }: FieldHeatmapProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    }
    const chart = instanceRef.current;

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(15,15,26,0.95)',
        borderColor: 'rgba(255,255,255,0.08)',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        formatter: (params: any) => {
          const p = params[0];
          return `<div style="font-size:12px">
            <b style="color:#818cf8">${p.name}</b><br/>
            Used by <b style="color:#34d399">${p.value}</b> alphas
          </div>`;
        },
      },
      grid: {
        left: 10, right: 30, top: 10, bottom: 0,
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } },
        axisLabel: { color: '#6b7280', fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        data: data.map(d => d.field).reverse(),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      series: [{
        type: 'bar',
        data: data.map(d => d.count).reverse(),
        barWidth: 12,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: 'rgba(99,102,241,0.3)' },
            { offset: 1, color: '#6366f1' },
          ]),
        },
        label: {
          show: true,
          position: 'right',
          color: '#6b7280',
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
          formatter: (p: any) => `${p.value}`,
        },
      }],
    });

    return () => {
      chart.dispose();
      instanceRef.current = null;
    };
  }, [data]);

  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Field Usage
      </h2>
      <div ref={chartRef} className="h-44 w-full" />
    </div>
  );
}
