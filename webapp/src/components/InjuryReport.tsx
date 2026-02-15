import type { MedicalAssessment, IncidentReport } from '../api/types';

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
  incidentReport?: IncidentReport | null;
};

export function InjuryReport({ medical, reportPath, pdfPath, incidentReport }: Props) {
  const handleDownload = (path: string, filename: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const link = document.createElement('a');
    link.href = `http://localhost:8000/download/${encodeURIComponent(path)}`;
    link.download = filename;
    link.click();
  };

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (pdfPath) {
      window.open(`http://localhost:8000/download/${encodeURIComponent(pdfPath)}`, '_blank');
    } else if (reportPath) {
      window.open(`http://localhost:8000/download/${encodeURIComponent(reportPath)}`, '_blank');
    }
  };

  const isClickable = !!(reportPath || pdfPath);
  const doc = incidentReport?.document;
  const receivedAt = incidentReport?.received_at;
  const hasIncidentContent = doc || (incidentReport && (incidentReport.incident_id ?? receivedAt));

  return (
    <div
      className={`bg-base-900 border-2 rounded p-3 h-full flex flex-col font-mono overflow-hidden min-h-0 ${
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
        <div className="flex items-center gap-2">
          {incidentReport?.pdf_path && (
            <button
              onClick={(e) => handleDownload(incidentReport.pdf_path!, 'medical_report.pdf', e)}
              className="text-[9px] font-mono px-2 py-0.5 rounded bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/30 transition-colors"
              title="Download PDF"
            >
              PDF
            </button>
          )}
          {incidentReport?.report_path && (
            <button
              onClick={(e) => handleDownload(incidentReport.report_path!, 'medical_report.md', e)}
              className="text-[9px] font-mono px-2 py-0.5 rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-600/30 transition-colors"
              title="Download Markdown"
            >
              MD
            </button>
          )}
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
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
        {medical ? (
          <div className="text-[13px] text-base-200 leading-relaxed whitespace-pre-line">
            {medical.injuryReport}
          </div>
        ) : (
          <div className="text-[13px] text-base-500 italic">Awaiting medical assessment...</div>
        )}
        {hasIncidentContent && (
          <div className="pt-2 border-t border-base-700/50">
            <div className="text-[11px] uppercase tracking-widest text-base-500 font-semibold mb-1">
              Incident report
            </div>
            {receivedAt && (
              <div className="text-[10px] text-base-500 mb-1">
                Received: {typeof receivedAt === 'string' ? receivedAt.slice(0, 19) : String(receivedAt)}
              </div>
            )}
            {incidentReport?.pdf_path ? (
              <div className="space-y-2">
                <div 
                  className="p-2 rounded bg-red-600/10 border border-red-600/20 hover:bg-red-600/20 transition-colors cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    window.open(`http://localhost:8000/download/${encodeURIComponent(incidentReport.pdf_path!)}`, '_blank');
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[14px]">📄</span>
                    <div className="flex-1">
                      <div className="text-[11px] font-semibold text-red-400">Full Medical Report (PDF)</div>
                      <div className="text-[9px] text-base-500">Click to open in new tab</div>
                    </div>
                  </div>
                </div>
                {doc && typeof doc === 'string' && doc.length > 0 && doc.length < 200 && (
                  <div className="text-[10px] text-base-400 italic">{doc}</div>
                )}
              </div>
            ) : doc && typeof doc === 'string' ? (
              <pre className="whitespace-pre-wrap break-words text-[10px] text-base-200 border-l border-base-600 pl-2">
                {doc.slice(0, 300)}{doc.length > 300 && '...\n\n[Full report available via download]'}
              </pre>
            ) : incidentReport?.incident_id ? (
              <div className="text-[11px] text-base-500 italic">Report received (no details).</div>
            ) : null}
          </div>
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
