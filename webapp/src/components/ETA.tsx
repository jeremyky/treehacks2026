interface Props {
  snapshotUrl: string | null;
}

export function ETA({ snapshotUrl }: Props) {
  return (
    <div className="bg-base-900 border-2 border-base-700 rounded p-3 h-full flex flex-col font-mono overflow-hidden min-h-0">
      <div className="text-[13px] uppercase tracking-widest text-base-400 mb-2 font-semibold shrink-0">Camera Feed</div>
      <div className="flex-1 w-full flex items-center justify-center rounded border-2 border-base-700 bg-base-850 overflow-hidden min-h-0">
        {snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Robot camera"
            className="w-full h-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = 'none';
              e.currentTarget.parentElement!.innerHTML = '<span class="text-[13px] text-base-500 italic">Camera unavailable</span>';
            }}
          />
        ) : (
          <span className="text-[13px] text-base-500 italic">Waiting for camera...</span>
        )}
      </div>
    </div>
  );
}
