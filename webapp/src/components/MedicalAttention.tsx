import type { MedicalAssessment } from '../api/types';

type Props = { medical: MedicalAssessment | null };

export function MedicalAttention({ medical }: Props) {
  return (
    <div className="bg-base-900 border border-base-700 rounded p-3 h-full flex flex-col font-mono overflow-hidden">
      <div className="px-0 py-0 mb-2 shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-base-500">
          Medical Attention Needed
        </span>
      </div>
      <div className="flex-1 overflow-y-auto flex flex-col gap-1">
        {medical ? (
          medical.medicalAttention.map((item, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px]">
              <span className="text-base-500 mt-px">-</span>
              <span className="text-base-200">{item}</span>
            </div>
          ))
        ) : (
          <div className="text-[11px] text-base-500 italic">Awaiting medical injury report...</div>
        )}
      </div>
    </div>
  );
}
