import type { MedicalAssessment } from '../api/types';

const SEV_COLOR: Record<string, string> = {
  CRITICAL: 'bg-red-500/10 text-red-400/80 border-red-500/20',
  MODERATE: 'bg-amber-500/10 text-amber-400/80 border-amber-500/20',
  MINOR: 'bg-emerald-500/10 text-emerald-400/80 border-emerald-500/20',
};

type Props = { medical: MedicalAssessment | null };

export function InjuryReport({ medical }: Props) {
  return (
    <div className="bg-base-900 border border-base-700 rounded p-3 h-full flex flex-col font-mono overflow-hidden">
      <div className="flex items-center justify-between mb-2 shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-base-500">Injury Report</span>
        {medical && (
          <span
            className={`text-[9px] font-semibold tracking-wider px-2 py-0.5 rounded border ${
              SEV_COLOR[medical.severity] ?? SEV_COLOR['MODERATE']
            }`}
          >
            {medical.severity}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {medical ? (
          <div className="text-[11px] text-base-200 leading-relaxed">{medical.injuryReport}</div>
        ) : (
          <div className="text-[11px] text-base-500 italic">Awaiting victim report...</div>
        )}
      </div>
    </div>
  );
}
