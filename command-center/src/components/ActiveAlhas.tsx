'use client';

import type { ActiveAlpha } from '@/types/dashboard';

interface ActiveAlhasProps {
  alphas: ActiveAlpha[];
  total?: number;
  target?: number;
}

function highlightExpr(expr: string) {
  if (!expr) return '—';
  const fieldRx = /\b(revenue|enterprise_value|debt|equity|operating_income|ebitda|cap|cash|sales|close|volume|adv20|returns|vwap|open|high|low)\b/g;
  const kwRx = /\b(rank|ts_mean|ts_sum|ts_std|ts_corr|ts_rank|ts_min|ts_max|ts_delta|ts_zscore|log|sign|abs|scale|group_rank|zscore|max|min|clip)\b/g;
  let html = expr.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  html = html.replace(fieldRx, '<span class="af">$1</span>');
  html = html.replace(kwRx, '<span class="ao">$1</span>');
  html = html.replace(/[()*+\\-]/g, '<span class="ap">$&</span>');
  html = html.replace(/\b\d+\.?\d*\b/g, '<span class="an">$&</span>');
  return html;
}

export default function ActiveAlhas({ alphas, total, target }: ActiveAlhasProps) {
  if (!alphas || alphas.length === 0) {
    return (
      <div className="card p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
          Active Alhas
          <span className="ml-2 text-gray-600 font-normal normal-case">{total ?? 0}</span>
          {target != null && (
            <span className="ml-1 text-gray-700 font-normal normal-case">/ {target}</span>
          )}
        </h2>
        <div className="text-gray-600 text-xs text-center py-6">No active alphas yet</div>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Active Alhas
        <span className="ml-2 text-gray-600 font-normal normal-case">{alphas.length}</span>
        {target != null && (
          <span className="ml-1 text-gray-700 font-normal normal-case">/ {target}</span>
        )}
      </h2>
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
        .af { color: #818cf8; }
        .ao { color: #34d399; }
        .an { color: #fbbf24; }
        .ap { color: #6b7280; }
      `}</style>
    </div>
  );
}
