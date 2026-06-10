// WQ Command Center — TypeScript types matching Flask API v2 responses

export interface CurrentCandidate {
  name?: string;
  expr?: string;
  orthogonality_score?: number;
  sim_progress?: number | null;
  skeleton?: string;
  weight?: number;
  sim_id?: string;
  alpha_id?: string;
  sharpe?: number | null;
  fitness?: number | null;
  is_status?: string;
  sc_value?: number;
  sc_result?: string;
  fields?: string[];
}

export interface FieldUsage {
  field: string;
  count: number;
  pct?: number;
}

export interface LogEntry {
  level?: string;
  msg?: string;
  time?: string;
  raw: string;
}

export interface ActiveAlpha {
  id: string;
  expr: string;
  fields?: string[];
  sharpe?: number;
  fitness?: number;
  sc_value?: number;
}

export interface PipelineStatus {
  status: string;
  phase: string;
  active_count: number;
  target: number;
  started_at: string;
  last_updated: string;
  duration?: string | null;
  last_activity?: string | null;
  current_candidate: CurrentCandidate | null;
  batch_total: number;
  batch_index: number;
  batch_id: string;
  candidates_generated: number;
  candidates_passed_is: number;
  candidates_passed_sc: number;
  candidates_submitted: number;
  candidates_is_fail: number;
  candidates_sc_fail: number;
  candidates_failed: number;
  iterations: number;
  errors: string[];
  field_chart: FieldUsage[];
  log: LogEntry[];
  actives: ActiveAlpha[];
  system?: {
    cpu_percent: number;
    memory_percent: number;
    memory_used_gb: number;
    memory_total_gb: number;
  } | null;
}

export interface HistoryEvent {
  timestamp: string;
  level: string;
  event: string;
  details: Record<string, any>;
  raw: string;
}

export interface BatchPhase {
  A?: string;
  B?: string;
  C?: string;
}

export interface BatchCandidate {
  index: number;
  name: string;
  expr: string;
  skeleton: string;
  weight: number;
  orthogonality_score: number;
  fields: string[];
  field_count: number;
  is_current: boolean;
  status: string;
  alpha_id?: string;
  sim_id?: string;
  sharpe?: number | null;
  fitness?: number | null;
}

export interface BatchInfo {
  batch_id: string;
  batch_size: number;
  current_index: number;
  current_name?: string;
  phases: BatchPhase;
  created_at: string;
  updated_at: string;
  candidates: BatchCandidate[];
}
