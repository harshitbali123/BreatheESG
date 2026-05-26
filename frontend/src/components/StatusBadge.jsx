const statusConfig = {
  // Ingestion statuses
  pending: { label: 'Pending', bg: 'bg-amber-500/15', text: 'text-amber-400', dot: 'bg-amber-400' },
  processing: { label: 'Processing', bg: 'bg-blue-500/15', text: 'text-blue-400', dot: 'bg-blue-400' },
  completed: { label: 'Completed', bg: 'bg-brand-500/15', text: 'text-brand-400', dot: 'bg-brand-400' },
  failed: { label: 'Failed', bg: 'bg-red-500/15', text: 'text-red-400', dot: 'bg-red-400' },
  // Review statuses
  approved: { label: 'Approved', bg: 'bg-brand-500/15', text: 'text-brand-400', dot: 'bg-brand-400' },
  flagged: { label: 'Flagged', bg: 'bg-red-500/15', text: 'text-red-400', dot: 'bg-red-400' },
  locked: { label: 'Locked', bg: 'bg-slate-500/15', text: 'text-slate-400', dot: 'bg-slate-400' },
  // Parse statuses
  ok: { label: 'OK', bg: 'bg-brand-500/15', text: 'text-brand-400', dot: 'bg-brand-400' },
  warning: { label: 'Warning', bg: 'bg-amber-500/15', text: 'text-amber-400', dot: 'bg-amber-400' },
};

export default function StatusBadge({ status }) {
  const config = statusConfig[status] || {
    label: status,
    bg: 'bg-slate-500/15',
    text: 'text-slate-400',
    dot: 'bg-slate-400',
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}
