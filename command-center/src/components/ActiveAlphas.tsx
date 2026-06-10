'use client';

import type { ActiveAlpha } from '@/types/dashboard';

interface ActiveAlphasProps {
  alphas: ActiveAlpha[];
  total?: number;
  target?: number;
}

function highlightExpr(expr: string) {
  if (!expr) return '—';
  const fieldRx = /\b(revenue|enterprise_value|debt|equity|operating_income|ebitda|cap|cash|sales|close|volume|adv20|returns|vwap|open|high|low)\b/g;
  const kwRx = /\b(rank|ts_mean|ts_sum|ts_std|ts_corr|ts_rank|ts_min|ts_max|ts_delta|ts_zscore|log|sign|abs|scale|group_rank|zscore|max|min|clip)\b/g;
  let html = expr.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  html = html.replace(fieldRx, '<span class="sf">$1</span>');
  html = html.replace(kwRx, '<span class="so">$1</span>');
  html = html.replace(/[()*+\-]/g, '<span class="sp">$&</span>');
  html = html.replace(/\b\d+\.?\d*\b/g, '<span class="sn">$&</span>');
  return html;
}

export default function ActiveAlphas({ alphas, total, target }: ActiveAlphasProps) {
  if (!alphas || alphas.length === 0) {
    return (
      <div className="card p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
          Active Alphas
        </h2>
        <div className="text-gray-600 text-xs text-center py-6">No active alphas yet</div>
      </div>
    );
  }

  // 质量统计
  const avgSharpe = alphas.reduce((s, a) => s + (a.sharpe ?? 0), 0) / alphas.length;
  const avgFitness = alphas.reduce((s, a) => s + (a.fitness ?? 0), 0) / alphas.length;
  const highSharpe = alphas.filter(a => (a.sharpe ?? 0) >= 1.5).length;
  const mediumSharpe = alphas.filter(a => (a.sharpe ?? 0) >= 1.0 && (a.sharpe ?? 0) < 1.5).length;
  const lowSharpe = alphas.filter(a => (a.sharpe ?? 0) < 1.0).length;

  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Active Alphas
        <span className="ml-2 text-gray-600 font-normal normal-case">{alphas.length}</span>
        {target != null && (
          <span className="ml-1 text-gray-700 font-normal normal-case">/ {target}</span>
        )}
      </h2>

      {/* 质量评分面板 */}
      <div className="grid grid-cols-3 gap-1.5 mb-3">
        <div className="bg-zinc-900/60 border border-white/[0.03] rounded-lg p-2">
          <div className="text-[8px] text-gray-500 uppercase tracking-wider mb-0.5">Avg Sharpe</div>
          <div className={`text-sm font-bold font-mono tabular-nums ${
            avgSharpe >= 1.5 ? 'text-emerald-400' : avgSharpe >= 1.0 ? 'text-amber-400' : 'text-rose-400'
          }`}>
            {avgSharpe.toFixed(2)}
          </div>
        </div>
        <div className="bg-zinc-900/60 border border-white/[0.03] rounded-lg p-2">
          <div className="text-[8px] text-gray-500 uppercase tracking-wider mb-0.5">Avg Fitness</div>
          <div className="text-sm font-bold font-mono tabular-nums text-indigo-400">
            {avgFitness.toFixed(2)}
          </div>
        </div>
        <div className="bg-zinc-900/60 border border-white/[0.03] rounded-lg p-2">
          <div className="text-[8px] text-gray-500 uppercase tracking-wider mb-0.5">Quality</div>
          <div className="text-sm font-bold font-mono tabular-nums">
            <span className="text-emerald-400">{highSharpe}</span>
            <span className="text-gray-600">/</span>
            <span className="text-amber-400">{mediumSharpe}</span>
            <span className="text-gray-600">/</span>
            <span className="text-rose-400">{lowSharpe}</span>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto" style={{ maxWidth: '100%' }}>
        <table className="w-full text-[11px]" style={{ tableLayout: 'fixed', minWidth: '640px' }}>
          <thead>
            <tr className="text-gray-600 border-b border-white/[0.06]">
              <th className="text-left py-2 font-medium" style={{ width: '4.5rem' }}>ID</th>
              <th className="text-left py-2 font-medium">Expression</th>
              <th className="text-right py-2 font-medium" style={{ width: '3.5rem' }}>S</th>
              <th className="text-right py-2 font-medium" style={{ width: '3.5rem' }}>F</th>
            </tr>
          </thead>
          <tbody>
            {alphas.map((alpha) => (
              <tr key={alpha.id} className="border-b border-white/[0.02] hover:bg-white/[0.02] transition-colors">
                <td className="py-2 font-mono text-indigo-300 align-top whitespace-nowrap" style={{ width: '4.5rem' }}>
                  {alpha.id}
                </td>
                <td className="py-2">
                  <span
                    className="font-mono text-xs leading-relaxed whitespace-nowrap"
                    dangerouslySetInnerHTML={{ __html: highlightExpr(alpha.expr) }}
                  />
                </td>
                <td className="py-2 text-right font-mono tabular-nums whitespace-nowrap" style={{ width: '3.5rem' }}>
                  {alpha.sharpe != null ? alpha.sharpe.toFixed(2) : '—'}
                </td>
                <td className="py-2 text-right font-mono tabular-nums whitespace-nowrap" style={{ width: '3.5rem' }}>
                  {alpha.fitness != null ? alpha.fitness.toFixed(2) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <style jsx>{`
        .sf { color: #818cf8; }
        .so { color: #34d399; }
        .sn { color: #fbbf24; }
        .sp { color: #6b7280; }
      `}</style>
    </div>
  );
}
