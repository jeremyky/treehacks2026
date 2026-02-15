import type { IncidentReport } from '../api/types';

type Props = { report: IncidentReport };

/** Shows the incident report / docs from the robot once created; stays visible. */
export function ReportDoc({ report }: Props) {
  const { incident_id, received_at, document: documentText, report_path, pdf_path, ...rest } = report;
  const restKeys = Object.keys(rest).filter(
    (k) => rest[k] !== undefined && rest[k] !== null && rest[k] !== '' && k !== 'document' && k !== 'report_path' && k !== 'pdf_path'
  );

  const handleDownload = (path: string, filename: string) => {
    // Create download link
    const link = document.createElement('a');
    link.href = `http://localhost:8000/download/${encodeURIComponent(path)}`;
    link.download = filename;
    link.click();
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-base-900 border border-base-700 rounded overflow-hidden">
      <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Incident report
        </span>
        <div className="flex items-center gap-2">
          {pdf_path && (
            <button
              onClick={() => handleDownload(pdf_path, 'medical_report.pdf')}
              className="text-[9px] font-mono px-2 py-1 rounded bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/30 transition-colors"
              title="Download PDF"
            >
              📄 PDF
            </button>
          )}
          {report_path && (
            <button
              onClick={() => handleDownload(report_path, 'medical_report.md')}
              className="text-[9px] font-mono px-2 py-1 rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-600/30 transition-colors"
              title="Download Markdown"
            >
              📝 MD
            </button>
          )}
          {incident_id && (
            <span className="text-[9px] font-mono text-base-500">{incident_id}</span>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 text-[11px] font-mono text-base-200 space-y-1">
        {received_at && (
          <div className="text-base-500">
            Received: {typeof received_at === 'string' ? received_at.slice(0, 19) : String(received_at)}
          </div>
        )}
        {documentText && typeof documentText === 'string' && (
          <pre className="whitespace-pre-wrap break-words text-[10px] text-base-200 border-l border-base-600 pl-2">
            {documentText}
          </pre>
        )}
        {!documentText && restKeys.length === 0 && !incident_id && !received_at && (
          <div className="text-base-500 italic">Report received (no details).</div>
        )}
        {!documentText && restKeys.map((key) => {
          const val = rest[key];
          if (val == null) return null;
          if (typeof val === 'object' && !Array.isArray(val)) {
            return (
              <div key={key} className="pl-2 border-l border-base-600">
                <span className="text-base-500">{key}:</span>
                <pre className="whitespace-pre-wrap break-words mt-0.5 text-[10px]">
                  {JSON.stringify(val, null, 2)}
                </pre>
              </div>
            );
          }
          if (Array.isArray(val)) {
            return (
              <div key={key}>
                <span className="text-base-500">{key}:</span>{' '}
                {val.map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ')}
              </div>
            );
          }
          return (
            <div key={key}>
              <span className="text-base-500">{key}:</span> {String(val)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
