import type { CommandCenterEvent } from '../api/types';

type Props = {
  event: CommandCenterEvent | null;
  snapshotUrl: string | null;
};

/** Live status and snapshot from Python/robot via command center. */
export function RobotStatus({ event, snapshotUrl }: Props) {
  const phaseLabel = event?.phase_label ?? event?.phase ?? '—';
  const numPersons = event?.num_persons ?? 0;
  const confidence = event?.confidence ?? 0;

  return (
    <div className="flex flex-col h-full bg-base-900 border border-base-700 rounded overflow-hidden">
      <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Robot feed
        </span>
        <span className="text-[9px] text-base-500 font-mono">{phaseLabel}</span>
      </div>
      <div className="flex-1 min-h-0 flex flex-col gap-2 p-2">
        {snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Latest snapshot"
            className="w-full object-contain rounded border border-base-700 max-h-[140px] bg-base-950"
          />
        ) : (
          <div className="flex-1 flex items-center justify-center rounded border border-base-700 bg-base-950 text-base-500 text-[10px] font-mono">
            No snapshot yet
          </div>
        )}
        <div className="text-[10px] font-mono text-base-500 space-y-0.5 shrink-0">
          <div>Persons: {numPersons}</div>
          <div>Confidence: {(confidence * 100).toFixed(0)}%</div>
        </div>
      </div>
    </div>
  );
}
