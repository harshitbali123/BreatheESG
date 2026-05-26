import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import StatusBadge from '../components/StatusBadge';
import DataTable from '../components/DataTable';
import { ArrowLeft, FileText, Hash, Calendar, User, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';

export default function IngestionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [runRes, rowsRes] = await Promise.all([
          api.get(`/ingestion/runs/${id}/`),
          api.get(`/ingestion/runs/${id}/raw-rows/`),
        ]);
        setRun(runRes.data);
        setRows(rowsRes.data.results || rowsRes.data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <p className="text-slate-500">Ingestion run not found.</p>
        <button onClick={() => navigate('/ingestion')} className="text-brand-400 text-sm hover:underline">
          ← Back to Ingestion
        </button>
      </div>
    );
  }

  const filteredRows = filter === 'all' ? rows : rows.filter((r) => r.parse_status === filter);

  const tabs = [
    { key: 'all', label: 'All', count: rows.length },
    { key: 'ok', label: 'OK', count: rows.filter((r) => r.parse_status === 'ok').length },
    { key: 'warning', label: 'Warning', count: rows.filter((r) => r.parse_status === 'warning').length },
    { key: 'failed', label: 'Failed', count: rows.filter((r) => r.parse_status === 'failed').length },
  ];

  const metaItems = [
    { icon: FileText, label: 'File', value: run.original_filename },
    { icon: Hash, label: 'Source', value: run.source_type },
    { icon: Calendar, label: 'Uploaded', value: new Date(run.created_at).toLocaleString() },
    { icon: User, label: 'By', value: run.uploaded_by || 'System' },
    { icon: CheckCircle2, label: 'Success', value: run.row_count_success, color: 'text-brand-400' },
    { icon: XCircle, label: 'Failed', value: run.row_count_failed, color: 'text-red-400' },
    { icon: AlertTriangle, label: 'Flagged', value: run.row_count_flagged, color: 'text-amber-400' },
  ];

  const rowColumns = [
    { key: 'row_number', label: '#', render: (v) => <span className="text-slate-500 font-mono text-xs">{v}</span> },
    { key: 'parse_status', label: 'Status', render: (v) => <StatusBadge status={v} /> },
    {
      key: 'raw_data',
      label: 'Data',
      sortable: false,
      render: (v) => (
        <pre className="text-xs text-slate-400 max-w-[500px] truncate font-mono">
          {JSON.stringify(v, null, 0)}
        </pre>
      ),
    },
    {
      key: 'parse_errors',
      label: 'Errors',
      sortable: false,
      render: (v) =>
        v && v.length > 0 ? (
          <span className="text-xs text-red-400">{v.join('; ')}</span>
        ) : (
          <span className="text-xs text-slate-600">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/ingestion')}
          className="p-2 rounded-lg hover:bg-white/5 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white">Ingestion Run</h1>
            <StatusBadge status={run.status} />
          </div>
          <p className="text-xs text-slate-500 mt-1 font-mono">{run.id}</p>
        </div>
      </div>

      {/* Metadata */}
      <div className="glass-card p-5">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
          {metaItems.map(({ icon: Icon, label, value, color }) => (
            <div key={label}>
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-xs text-slate-500">{label}</span>
              </div>
              <p className={`text-sm font-medium ${color || 'text-white'} truncate`}>{value}</p>
            </div>
          ))}
        </div>
        {run.error_message && (
          <div className="mt-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20">
            <p className="text-xs font-medium text-red-400">Error</p>
            <p className="text-sm text-red-300 mt-1">{run.error_message}</p>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {tabs.map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 border
              ${
                filter === key
                  ? 'bg-brand-500/15 border-brand-500/40 text-brand-400'
                  : 'bg-white/5 border-border-subtle text-slate-400 hover:text-white hover:bg-white/10'
              }`}
          >
            {label} <span className="ml-1 text-xs opacity-60">({count})</span>
          </button>
        ))}
      </div>

      {/* Raw rows table */}
      <DataTable
        columns={rowColumns}
        data={filteredRows}
        pageSize={20}
        emptyMessage="No rows found with this filter."
      />
    </div>
  );
}
