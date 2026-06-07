'use client';

import { useMemo } from 'react';

interface ActiveAlpha {
  id: string;
  expr: string;
  sharpe?: number;
  fitness?: number;
  sc_value?: number;
}

interface AlphaQualityProps {
  alphas: ActiveAlpha[];
  total: number;
  target: number;
}

/**
 * Alpha 质量评分：基于 Sharpe、Fitness、SC 的综合评分 (0-100)
 */
function alphaScore(a: ActiveAlpha): { score: number; sharpe: number; fitness: number; sc: number; grade: string } {
  const s = a.sharpe ?? 0;
  const f = a.fitness ?? 0;
  const sc = a.sc_value ?? 0;

  // Sharpe 评分 (0-40): S>=2.0满分, S>=1.5良好, S>=1.0及格
  const sScore = Math.min(40, Math.max(0, (s - 0.5) / 1.5 * 40));

  // Fitness 评分 (0-30): F>=5.0满分
  const fScore = Math.min(30, Math.max(0, (f / 5) * 30));

  // SC 评分 (0-30): SC>=0.3良好
  const scScore = Math.min(30, Math.max(0, (sc / 0.3) * 30));

  const total = Math.round(sScore + fScore + scScore);

  let grade: string;
  if (total >= 80) grade = 'A';
  else if (total >= 65) grade = 'B';
  else if (total >= 45) grade = 'C';
  else if (total >= 25) grade = 'D';
  else grade = 'F';

  return { score: total, sharpe: sScore, fitness: fScore, sc: scScore, grade };
}

function fmt(v: number | null | undefined, d = 2): string {
  if (v == null) return '-';
  return v.toFixed(d);
}

export default function AlphaQuality({ alphas, total, target }: AlphaQualityProps) {
  const stats = useMemo(() => {
    if (!alphas.length) return null;

    const scores = alphas.map(alphaScore);
    const avgScore = scores.reduce((s, a) => s + a.score, 0) / scores.length;
    const avgSharpe = alphas.reduce((s, a) => s + (a.sharpe ?? 0), 0) / alphas.length;
    const excellent = scores.filter(a => a.grade === 'A').length;
    const good = scores.filter(a => a.grade === 'B').length;
    const poor = scores.filter(a => a.grade === 'C' || a.grade === 'D').length;
    const progress = `${total}/${target}`;

    return { excellent, good, poor, avgScore: Math.round(avgScore), avgSharpe, totalAlphas: alphas.length, progress };
  }, [alphas, total, target]);

  if (!stats || stats.totalAlphas === 0) {
    return (
      <div className="card p-3 md:p-4 animate-[fade-in_0.3s_ease-out]">
        <div className="section-header mb-2">
          <span className="text-purple-400 text-[10px] shrink-0">◆</span>
          <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
            Alpha Quality
          </h2>
        </div>
        <div className="h-20 flex items-center justify-center text-gray-600 text-[10px] bg-black/10 rounded-lg">
          No active alphas
        </div>
      </div>
    );
  }

  return (
    <div className="card p-3 md:p-4 animate-[fade-in_0.3s_ease-out]">
      <div className="section-header mb-3">
        <span className="text-purple-400 text-[10px] shrink-0">◆</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
          Alpha Quality
        </h2>
        <span className="text-gray-600 font-normal text-[8px] md:text-[10px] truncate">
          {stats.progress} · avg {stats.avgScore}pts
        </span>
      </div>

      {/* 综合分数环 */}
      <div className="flex items-center gap-4 mb-3">
        <div className="relative w-16 h-16 md:w-20 md:h-20 shrink-0">
          <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="#1f2937" strokeWidth="2" />
            <circle
              cx="18" cy="18" r="15.5" fill="none"
              stroke="url(#scoreGrad)"
              strokeWidth="2"
              strokeDasharray={`${(stats.avgScore / 100) * 97.4} 97.4`}
              strokeLinecap="round"
            />
            <defs>
              <linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#818cf8" />
                <stop offset="100%" stopColor="#a78bfa" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[15px] md:text-lg font-bold text-gray-200">
              {stats.avgScore}
            </span>
          </div>
        </div>

        <div className="flex-1 min-w-0 space-y-1">
          {/* 等级分布条 */}
          <div className="flex gap-0.5 h-2 rounded-full overflow-hidden">
            {stats.excellent > 0 && (
              <div
                className="bg-gradient-to-r from-violet-500 to-violet-400 transition-all"
                style={{ width: `${(stats.excellent / stats.totalAlphas) * 100}%` }}
              />
            )}
            {stats.good > 0 && (
              <div
                className="bg-gradient-to-r from-indigo-500 to-indigo-400 transition-all"
                style={{ width: `${(stats.good / stats.totalAlphas) * 100}%` }}
              />
            )}
            {stats.poor > 0 && (
              <div
                className="bg-gradient-to-r from-amber-500 to-amber-400 transition-all"
                style={{ width: `${(stats.poor / stats.totalAlphas) * 100}%` }}
              />
            )}
          </div>

          <div className="flex items-center justify-between text-[9px]">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
              <span className="text-gray-500">A {stats.excellent}</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
              <span className="text-gray-500">B {stats.good}</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="text-gray-500">C D {stats.poor}</span>
            </span>
          </div>
        </div>
      </div>

      {/* Alpha 质量明细 */}
      <div className="space-y-1 max-h-28 overflow-y-auto">
        {alphas.slice(0, 20).map(a => {
          const { score, grade } = alphaScore(a);
          const gradeColor =
            grade === 'A' ? 'text-violet-400' :
            grade === 'B' ? 'text-indigo-400' :
            grade === 'C' ? 'text-amber-400' :
            'text-red-400';
          const barColor =
            grade === 'A' ? 'bg-violet-500/40' :
            grade === 'B' ? 'bg-indigo-500/40' :
            grade === 'C' ? 'bg-amber-500/40' :
            'bg-red-500/40';

          return (
            <div key={a.id} className="flex items-center gap-1.5 text-[9px] py-0.5 px-1 rounded hover:bg-white/[0.02]">
              <span className={`w-4 shrink-0 text-center font-bold ${gradeColor}`}>{grade}</span>
              <span className="font-mono text-gray-400 w-16 md:w-24 truncate shrink-0">
                {a.id.slice(0, 12)}
              </span>
              <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden min-w-[30px]">
                <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${score}%` }} />
              </div>
              <span className="text-gray-600 w-10 text-right shrink-0 font-mono">{score}</span>
              <span className="text-gray-500 w-14 text-right shrink-0 font-mono">
                S={fmt(a.sharpe)}
              </span>
            </div>
          );
        })}
        {alphas.length > 20 && (
          <div className="text-center text-gray-700 text-[8px] py-1">
            +{alphas.length - 20} more alphas
          </div>
        )}
      </div>
    </div>
  );
}
