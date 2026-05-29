'use client';

import type { CurrentCandidate as Candidate } from '@/types/dashboard';

interface CandidateCardProps {
  candidate: Candidate | null;
  batchIndex?: number;
  batchTotal?: number;
}

function highlightExpr(expr: string) {
  if (!expr) return '<span class="text-gray-600">—</span>';
  const fieldRx = /\b(revenue|enterprise_value|debt|equity|operating_income|ebitda|cap|cash|sales|close|volume|adv20|returns|vwap|open|high|low)\b/g;
  const kwRx = /\b(rank|ts_mean|ts_sum|ts_std|ts_corr|ts_rank|ts_min|ts_max|ts_delta|ts_zscore|log|sign|abs|scale|group_rank|zscore|max|min|clip|ind_neutral|sector_neutral)\b/g;
  let html = expr.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  html = html.replace(fieldRx, '<span class="syntax-field">$1</span>');
  html = html.replace(kwRx, '<span class="syntax-op">$1</span>');
  html = html.replace(/[()*+\-]/g, '<span class="syntax-paren">$&</span>');
  html = html.replace(/\b\d+\.?\d*\b/g, '<span class="syntax-num">$&</span>');
  return html;
}

export default function CandidateCard({ candidate, batchIndex, batchTotal }: CandidateCardProps) {
  if (!candidate) return null;

  return (
    <div className="card p-4 active-glow">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
          <span className="text-sm font-medium text-white">{candidate.name || 'unnamed'}</span>
          {batchIndex != null && batchTotal != null && batchTotal > 0 && (
            <span className="text-[10px] font-mono text-zinc-500">
              batch {batchIndex}/{batchTotal}
            </span>
          )}
        </div>
        {candidate.orthogonality_score !== undefined && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-dark-600 text-gray-400 font-mono">
            ortho {candidate.orthogonality_score}
          </span>
        )}
      </div>

      <div
        className="font-mono text-sm bg-dark-900/80 rounded-lg p-3 border border-white/[0.04] leading-relaxed"
        dangerouslySetInnerHTML={{ __html: highlightExpr(candidate.expr || '') }}
      />

      <div className="grid grid-cols-3 gap-3 mt-3">
        {/* IS Status */}
        <div className="stat-card">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">IS Status</div>
          {candidate.is_status ? (
            <>
              <div className={`text-sm font-semibold ${
                candidate.is_status === 'PASS' ? 'text-emerald-400' :
                candidate.is_status === 'FAIL' ? 'text-red-400' : 'text-gray-500'
              }`}>
                {candidate.is_status}
              </div>
              {(candidate.sharpe != null || candidate.fitness != null) && (
                <div className="text-[10px] text-gray-600 mt-0.5 font-mono">
                  {candidate.sharpe != null && `S=${candidate.sharpe.toFixed(2)}`}
                  {candidate.sharpe != null && candidate.fitness != null && ' · '}
                  {candidate.fitness != null && `F=${candidate.fitness.toFixed(2)}`}
                </div>
              )}
            </>
          ) : (
            <div className="text-sm font-semibold text-gray-500">—</div>
          )}
        </div>

        {/* SC Value */}
        <div className="stat-card">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">SC Value</div>
          {candidate.sc_value != null ? (
            <>
              <div className={`text-sm font-semibold ${
                candidate.sc_result === 'PASS' ? 'text-emerald-400' :
                candidate.sc_result === 'FAIL' ? 'text-red-400' : 'text-gray-500'
              }`}>
                {candidate.sc_value.toFixed(3)}
              </div>
              <div className="relative mt-1.5">
                <div className="h-1.5 bg-dark-600/50 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${Math.min(100, candidate.sc_value * 100)}%`,
                      background: candidate.sc_value >= 0.7
                        ? 'linear-gradient(90deg, #ef4444, #fb7185)'
                        : candidate.sc_value > 0.5
                          ? 'linear-gradient(90deg, #f59e0b, #fbbf24)'
                          : 'linear-gradient(90deg, #10b981, #34d399)',
                    }}
                  />
                </div>
                <div className="flex justify-between text-[8px] text-gray-600 mt-0.5">
                  <span>0</span>
                  <span className="text-red-400">0.7</span>
                  <span>1</span>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm font-semibold text-gray-500">—</div>
          )}
        </div>

        {/* Sim ID */}
        <div className="stat-card">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Sim ID</div>
          <div className="text-[11px] text-gray-500 font-mono truncate">
            {candidate.sim_id ? candidate.sim_id.slice(0, 12) + '…' : '—'}
          </div>
        </div>
      </div>

      <style jsx>{`
        .syntax-field { color: #818cf8; }
        .syntax-op { color: #34d399; }
        .syntax-num { color: #fbbf24; }
        .syntax-paren { color: #6b7280; }
      `}</style>
    </div>
  );
}