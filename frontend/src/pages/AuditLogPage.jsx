import { useEffect, useState } from 'react';
import api from '../api/axios';
import DataTable from '../components/DataTable';

const actionColors = {
  ingestion_started: 'bg-blue-500/15 text-blue-400',
  ingestion_completed: 'bg-brand-500/15 text-brand-400',
  ingestion_failed: 'bg-red-500/15 text-red-400',
  row_parse_failed: 'bg-red-500/15 text-red-400',
  activity_created: 'bg-cyan-500/15 text-cyan-400',
  activity_approved: 'bg-brand-500/15 text-brand-400',
  activity_flagged: 'bg-amber-500/15 text-amber-400',
  activity_edited: 'bg-purple-500/15 text-purple-400',
  activity_locked: 'bg-slate-500/15 text-slate-400',
  bulk_approved: 'bg-brand-500/15 text-brand-400',
};

export default function AuditLogPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/audit/logs/')
      .then(({ data }) => setLogs(data.results || data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const columns = [
    {
      key: 'timestamp',
      label: 'Timestamp',
      render: (v) => (
        <span className="text-slate-400 text-xs whitespace-nowrap">
          {new Date(v).toLocaleString()}
        </span>
      ),
    },
    {
      key: 'actor',
      label: 'Actor',
      render: (v) => <span className="text-white text-sm">{v || 'System'}</span>,
    },
    {
      key: 'action',
      label: 'Action',
      render: (v) => (
        <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-medium ${actionColors[v] || 'bg-slate-500/15 text-slate-400'}`}>
          {v?.replace(/_/g, ' ')}
        </span>
      ),
    },
    {
      key: 'target_type',
      label: 'Target Type',
      render: (v) => <span className="text-slate-400 text-xs">{v?.replace(/_/g, ' ') || '—'}</span>,
    },
    {
      key: 'target_id',
      label: 'Target ID',
      render: (v) => (
        <span className="text-slate-500 text-xs font-mono max-w-[120px] truncate block">
          {v ? v.slice(0, 8) + '…' : '—'}
        </span>
      ),
    },
    {
      key: 'detail',
      label: 'Detail',
      render: (v) => (
        <span className="text-slate-400 text-xs max-w-[300px] truncate block">{v || '—'}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-white">Audit Log</h1>
        <p className="text-sm text-slate-400 mt-1">Complete audit trail of all system actions</p>
      </div>
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable columns={columns} data={logs} pageSize={15} emptyMessage="No audit log entries." />
      )}
    </div>
  );
}
