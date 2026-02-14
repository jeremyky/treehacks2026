/** Command center API types (matches Python event/report payloads). */

export interface LatestResponse {
  event: CommandCenterEvent | null;
  snapshot_path: string | null;
  report: IncidentReport | null;
  comms?: CommsEntry[];
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
  boot_ready?: boolean;
  degraded_mode?: boolean;
  num_persons?: number;
  confidence?: number;
  primary_person_center_offset?: number;
  robot_map_x?: number;
  robot_map_y?: number;
  snapshot_paths?: string[];
  received_at?: string;
  [key: string]: unknown;
}

export interface IncidentReport {
  incident_id?: string;
  received_at?: string;
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
