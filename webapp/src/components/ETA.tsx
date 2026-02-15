interface Props {
  snapshotUrl: string | null;
}

export function ETA({ snapshotUrl }: Props) {
  return (
    <div className="bg-base-900 border-2 border-base-700 rounded p-4 h-full flex flex-col font-mono">
      <div className="text-[14px] uppercase tracking-widest text-base-500 mb-3">Camera Feed</div>
      <div className="flex-1 w-full flex items-center justify-center rounded border-2 border-base-700 bg-base-850 overflow-hidden">
        {snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Robot camera"
            className="w-full h-full object-contain"
            onError={(e) => {
              e.currentTarget.style.display = 'none';
              e.currentTarget.parentElement!.innerHTML = '<span class="text-[14px] text-base-500 italic">Camera unavailable</span>';
            }}
          />
        ) : (
          <span className="text-[14px] text-base-500 italic">Waiting for camera...</span>
        )}
      </div>
    </div>
  );
}
