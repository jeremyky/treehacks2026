/** Command center API types (matches Python event/report payloads). */

export interface LatestResponse {
  event: CommandCenterEvent | null;
  snapshot_path: string | null;
  report: IncidentReport | null;
  comms?: CommsEntry[];
  status?: string;
  stage?: string;
}

export interface CommsEntry {
  id: number;
  role: 'victim' | 'robot' | 'operator';
  text: string;
  timestamp: string;
}

export interface CommandCenterEvent {
  event?: string;
  timestamp?: number;
  phase?: string;
  phase_label?: string;
  mode?: string;
  status?: string;
  stage?: string;
  boot_ready?: boolean;
  degraded_mode?: boolean;
  num_persons?: number;
  confidence?: number;
  primary_person_center_offset?: number;
  robot_map_x?: number;
  robot_map_y?: number;
  snapshot_paths?: string[];
  decision?: {
    action?: string;
    mode?: string;
    say?: string | null;
    wait_for_response_s?: number | null;
    used_llm?: boolean;
    params?: Record<string, unknown>;
  };
  llm_proposal?: unknown;
  last_response?: string | null;
  last_prompt?: string | null;
  received_at?: string;
  [key: string]: unknown;
}

export interface SnapshotHistoryEntry {
  name: string;
  url: string;
  received_at: string;
  metadata?: Record<string, unknown>;
  size_bytes?: number;
  path?: string;
}

export interface SnapshotHistoryResponse {
  snapshots: SnapshotHistoryEntry[];
}

export interface IncidentReport {
  incident_id?: string;
  received_at?: string;
  document?: string;
  report_path?: string;
  pdf_path?: string;
  annotated_images?: string[];
  images?: string[];
  transcript?: string[];
  patient_summary?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface MedicalAssessment {
  injuryReport: string;
  medicalAttention: string[];
  severity: 'CRITICAL' | 'MODERATE' | 'MINOR';
  followUp: string;
}

export interface CommsMessage {
  id: number;
  type: 'v' | 'h' | 'op' | 'sys';
  text: string;
  t?: string;
}
