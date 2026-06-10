'use client';

import type { CurrentCandidate as Candidate } from '@/types/dashboard';

interface CandidateCardProps {
  candidate: Candidate | null;
  batchIndex?: number;
  batchTotal?: number;
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

      {/* 表达式 */}
      <pre className="font-mono text-sm bg-dark-900/80 rounded-lg p-3 border border-white/[0.04] leading-relaxed overflow-x-auto whitespace-pre-wrap text-zinc-200">
        {candidate.expr || '—'}
      </pre>

      {/* 字段分布可视化 */}
      {candidate.fields && candidate.fields.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[9px] text-gray-500 uppercase tracking-wider">Fields</span>
            <span className="text-[9px] text-gray-600 font-mono">{candidate.fields.length}</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {candidate.fields.slice(0, 12).map((field, i) => (
              <span
                key={field}
                className="px-1.5 py-0.5 rounded text-[8px] font-mono bg-gray-800/40 border border-white/[0.03] text-gray-400"
                title={field}
              >
                {field}
              </span>
            ))}
            {candidate.fields.length > 12 && (
              <span className="px-1.5 py-0.5 rounded text-[8px] text-gray-500">
                +{candidate.fields.length - 12}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 正交性得分 */}
      {candidate.orthogonality_score !== undefined && (
        <div className="mt-2">
          <div className="flex items-center justify-between">
            <span className="text-[9px] text-gray-500 uppercase tracking-wider">Orthogonality</span>
            <span className={`text-[10px] font-bold font-mono ${
              candidate.orthogonality_score >= 0.8 ? 'text-emerald-400' :
              candidate.orthogonality_score >= 0.5 ? 'text-amber-400' : 'text-rose-400'
            }`}>
              {(candidate.orthogonality_score * 100).toFixed(1)}%
            </span>
          </div>
          <div className="h-1 bg-gray-800/70 rounded-full overflow-hidden mt-1">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                candidate.orthogonality_score >= 0.8 ? 'bg-gradient-to-r from-emerald-600 to-emerald-400' :
                candidate.orthogonality_score >= 0.5 ? 'bg-gradient-to-r from-amber-600 to-amber-400' : 'bg-gradient-to-r from-rose-600 to-rose-400'
              }`}
              style={{ width: `${candidate.orthogonality_score * 100}%` }}
            />
          </div>
        </div>
      )}

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
    </div>
  );
}
