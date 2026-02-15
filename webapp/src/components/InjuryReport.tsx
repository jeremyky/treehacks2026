import type { MedicalAssessment } from '../api/types';

const SEV_COLOR: Record<string, string> = {
  HIGH: 'bg-red-500/10 text-red-500/80 border-red-500/20',
  CRITICAL: 'bg-red-500/10 text-red-500/80 border-red-500/20',
  URGENT: 'bg-amber-500/10 text-amber-500/80 border-amber-500/20',
  MODERATE: 'bg-amber-500/10 text-amber-500/80 border-amber-500/20',
  DELAYED: 'bg-emerald-500/10 text-emerald-500/80 border-emerald-500/20',
  MINOR: 'bg-emerald-500/10 text-emerald-500/80 border-emerald-500/20',
};

type Props = { 
  medical: MedicalAssessment | null;
  reportPath?: string;
  pdfPath?: string;
};

export function InjuryReport({ medical, reportPath, pdfPath }: Props) {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (pdfPath) {
      // Open PDF in new tab
      window.open(`http://localhost:8000/download/${encodeURIComponent(pdfPath)}`, '_blank');
    } else if (reportPath) {
      // Open MD in new tab
      window.open(`http://localhost:8000/download/${encodeURIComponent(reportPath)}`, '_blank');
    }
  };

  const isClickable = !!(reportPath || pdfPath);

  return (
    <div 
      className={`bg-base-900 border-2 rounded p-3 h-full flex flex-col font-mono overflow-hidden ${
        isClickable 
          ? 'border-red-600/50 cursor-pointer hover:border-red-500 hover:bg-base-850 transition-all shadow-lg shadow-red-900/20' 
          : 'border-base-700'
      }`}
      onClick={isClickable ? handleClick : undefined}
      title={isClickable ? 'Click to open full medical report (PDF)' : ''}
    >
      <div className="flex items-center justify-between mb-2 shrink-0">
        <span className="text-[13px] uppercase tracking-widest text-base-400 font-semibold">
          Medical Report {isClickable && '📄'}
        </span>
        {medical && (
          <span
            className={`text-[12px] font-bold tracking-wider px-2 py-0.5 rounded border ${
              SEV_COLOR[medical.severity] ?? SEV_COLOR['MODERATE']
            }`}
          >
            {medical.severity}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto min-h-0">
        {medical ? (
          <div className="text-[13px] text-base-200 leading-relaxed whitespace-pre-line">
            {medical.injuryReport}
          </div>
        ) : (
          <div className="text-[13px] text-base-500 italic">Awaiting medical assessment...</div>
        )}
      </div>
      {isClickable && (
        <div className="mt-2 pt-2 border-t border-base-700/50 text-[10px] text-red-400/80 font-semibold text-center shrink-0 animate-pulse">
          ▶ CLICK TO VIEW FULL REPORT
        </div>
      )}
    </div>
  );
}
