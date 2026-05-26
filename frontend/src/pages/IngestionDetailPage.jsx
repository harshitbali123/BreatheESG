import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import StatusBadge from '../components/StatusBadge';
import {
  ArrowLeft, FileText, Hash, Calendar, User,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown,
  ChevronRight, ChevronLeft, Info, Database, Eye, EyeOff,
} from 'lucide-react';

/* ──────────────────────────────────────────────────────────────
   Helper: turn a raw error string like
   "missing_cost_centre: KOSTL is blank — cost centre not assigned in SAP"
   into { category, message, severity }
   ────────────────────────────────────────────────────────────── */
function parseError(errorStr) {
  if (!errorStr || typeof errorStr !== 'string') return { category: 'Error', message: String(errorStr), severity: 'error' };

  const colonIdx = errorStr.indexOf(':');
  if (colonIdx === -1) return { category: 'Error', message: errorStr, severity: 'error' };

  const rawCategory = errorStr.slice(0, colonIdx).trim();
  const message = errorStr.slice(colonIdx + 1).trim();

  // Determine severity from category name
  let severity = 'warning';
  if (rawCategory.includes('missing_critical') || rawCategory.includes('invalid') || rawCategory.includes('unknown_material') || rawCategory.includes('missing_emission_factor')) {
    severity = 'error';
  } else if (rawCategory.includes('missing_optional') || rawCategory.includes('defaulted') || rawCategory.includes('missing_cost') || rawCategory.includes('missing_cabin') || rawCategory.includes('missing_distance')) {
    severity = 'info';
  }

  // Pretty-format the category
  const category = rawCategory
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return { category, message, severity };
}

/* ──────────────────────────────────────────────────────────────
   Helper: nice labels for data keys
   ────────────────────────────────────────────────────────────── */
const KEY_LABELS = {
  consumption_kwh: 'Consumption (kWh)',
  period_start: 'Billing Start',
  period_end: 'Billing End',
  meter_id: 'Meter ID',
  service_address: 'Service Address',
  tariff_code: 'Tariff Code',
  demand_kw: 'Peak Demand (kW)',
  amount: 'Amount',
  currency: 'Currency',
  quantity: 'Quantity',
  unit: 'Unit',
  material_number: 'Material Number',
  material_desc: 'Material Description',
  posting_date: 'Posting Date',
  plant_code: 'Plant Code',
  movement_type: 'Movement Type',
  cost_centre: 'Cost Centre',
  cost_center: 'Cost Centre',
  vendor_name: 'Vendor Name',
  vendor_id: 'Vendor ID',
  vendor: 'Vendor',
  po_number: 'PO Number',
  doc_number: 'Document #',
  expense_type: 'Expense Type',
  travel_date: 'Travel Date',
  origin: 'Origin',
  destination: 'Destination',
  cabin_class: 'Cabin Class',
  nights: 'Nights',
  distance_km: 'Distance (km)',
  employee_id: 'Employee ID',
  trip_id: 'Trip ID',
};

function prettyKey(key) {
  return KEY_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ──────────────────────────────────────────────────────────────
   Severity icon + color config
   ────────────────────────────────────────────────────────────── */
const severityConfig = {
  error: {
    icon: XCircle,
    bg: 'bg-red-500/8',
    border: 'border-red-500/20',
    iconColor: 'text-red-400',
    textColor: 'text-red-300',
    categoryBg: 'bg-red-500/15',
    categoryText: 'text-red-400',
  },
  warning: {
    icon: AlertTriangle,
    bg: 'bg-amber-500/8',
    border: 'border-amber-500/20',
    iconColor: 'text-amber-400',
    textColor: 'text-amber-300',
    categoryBg: 'bg-amber-500/15',
    categoryText: 'text-amber-400',
  },
  info: {
    icon: Info,
    bg: 'bg-blue-500/8',
    border: 'border-blue-500/20',
    iconColor: 'text-blue-400',
    textColor: 'text-blue-300',
    categoryBg: 'bg-blue-500/15',
    categoryText: 'text-blue-400',
  },
};

/* ──────────────────────────────────────────────────────────────
   ErrorChip — a single styled error/warning/info item
   ────────────────────────────────────────────────────────────── */
function ErrorChip({ errorStr }) {
  const { category, message, severity } = parseError(errorStr);
  const config = severityConfig[severity];
  const Icon = config.icon;

  return (
    <div className={`flex items-start gap-2.5 px-3 py-2.5 rounded-xl ${config.bg} border ${config.border} transition-all duration-200`}>
      <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${config.iconColor}`} />
      <div className="flex-1 min-w-0">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider ${config.categoryBg} ${config.categoryText} mb-1`}>
          {category}
        </span>
        <p className={`text-xs ${config.textColor} leading-relaxed mt-0.5`}>{message}</p>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   DataPreview — structured display of raw_data as key-value pairs
   ────────────────────────────────────────────────────────────── */
function DataPreview({ data, maxVisible = 4 }) {
  const [expanded, setExpanded] = useState(false);

  if (!data || typeof data !== 'object') return <span className="text-xs text-slate-500">—</span>;

  const entries = Object.entries(data).filter(([, v]) => v !== '' && v !== null && v !== undefined);
  const visibleEntries = expanded ? entries : entries.slice(0, maxVisible);
  const hasMore = entries.length > maxVisible;

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1.5">
        {visibleEntries.map(([key, value]) => (
          <span key={key} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-white/5 border border-white/5 text-[11px]">
            <span className="text-slate-500 font-medium">{prettyKey(key)}:</span>
            <span className="text-slate-300 font-mono max-w-[200px] truncate">{String(value)}</span>
          </span>
        ))}
      </div>
      {hasMore && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          className="inline-flex items-center gap-1 text-[10px] text-brand-400 hover:text-brand-300 font-medium transition-colors mt-0.5"
        >
          {expanded ? (
            <><EyeOff className="w-3 h-3" /> Show less</>
          ) : (
            <><Eye className="w-3 h-3" /> +{entries.length - maxVisible} more fields</>
          )}
        </button>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   ExpandableRow — each row can be expanded to show full details
   ────────────────────────────────────────────────────────────── */
function ExpandableRow({ row, index }) {
  const [expanded, setExpanded] = useState(false);

  const errors = row.parse_errors || [];
  const status = row.parse_status;

  // Row-level accent color
  const rowAccent =
    status === 'failed' ? 'border-l-red-500/60' :
    status === 'warning' ? 'border-l-amber-500/60' :
    'border-l-transparent';

  return (
    <>
      {/* Main row */}
      <tr
        onClick={() => setExpanded(!expanded)}
        className={`cursor-pointer transition-all duration-200 border-l-2 ${rowAccent}
          ${expanded ? 'bg-white/[0.04]' : 'hover:bg-white/[0.02]'}
          ${index % 2 === 0 ? '' : 'bg-white/[0.01]'}`}
      >
        {/* Row number */}
        <td className="px-4 py-3.5 w-12">
          <span className="text-slate-500 font-mono text-xs">{row.row_number}</span>
        </td>

        {/* Status */}
        <td className="px-4 py-3.5 w-28">
          <StatusBadge status={status} />
        </td>

        {/* Data preview */}
        <td className="px-4 py-3.5">
          <DataPreview data={row.raw_data} maxVisible={3} />
        </td>

        {/* Errors summary */}
        <td className="px-4 py-3.5">
          {errors.length > 0 ? (
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
                ${status === 'failed' ? 'bg-red-500/15 text-red-400' : 'bg-amber-500/15 text-amber-400'}`}
              >
                {status === 'failed' ? (
                  <XCircle className="w-3 h-3" />
                ) : (
                  <AlertTriangle className="w-3 h-3" />
                )}
                {errors.length} {errors.length === 1 ? 'issue' : 'issues'}
              </span>
            </div>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-brand-500/10 text-brand-400">
              <CheckCircle2 className="w-3 h-3" />
              Clean
            </span>
          )}
        </td>

        {/* Expand toggle */}
        <td className="px-4 py-3.5 w-10">
          <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
        </td>
      </tr>

      {/* Expanded detail */}
      {expanded && (
        <tr className={`border-l-2 ${rowAccent}`}>
          <td colSpan={5} className="px-0 py-0">
            <div className="px-6 py-4 bg-white/[0.02] border-t border-b border-border-subtle/30 animate-fade-in">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Left: All Data Fields */}
                <div>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5" />
                    Row Data
                  </h4>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                    {Object.entries(row.raw_data || {}).map(([key, value]) => (
                      <div key={key} className="flex flex-col">
                        <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">{prettyKey(key)}</span>
                        <span className="text-xs text-slate-300 font-mono mt-0.5 truncate" title={String(value)}>
                          {value || <span className="text-slate-600 italic">empty</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Right: Issues */}
                {errors.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      Issues ({errors.length})
                    </h4>
                    <div className="space-y-2">
                      {errors.map((err, idx) => (
                        <ErrorChip key={idx} errorStr={err} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ──────────────────────────────────────────────────────────────
   Main Page
   ────────────────────────────────────────────────────────────── */
export default function IngestionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const pageSize = 15;

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
  const totalPages = Math.ceil(filteredRows.length / pageSize);
  const pagedRows = filteredRows.slice(page * pageSize, (page + 1) * pageSize);

  // Reset page when filter changes
  const handleFilterChange = (key) => {
    setFilter(key);
    setPage(0);
  };

  const tabs = [
    { key: 'all', label: 'All', count: rows.length, icon: Database, color: 'brand' },
    { key: 'ok', label: 'OK', count: rows.filter((r) => r.parse_status === 'ok').length, icon: CheckCircle2, color: 'brand' },
    { key: 'warning', label: 'Warnings', count: rows.filter((r) => r.parse_status === 'warning').length, icon: AlertTriangle, color: 'amber' },
    { key: 'failed', label: 'Failed', count: rows.filter((r) => r.parse_status === 'failed').length, icon: XCircle, color: 'red' },
  ];

  const metaItems = [
    { icon: FileText, label: 'File', value: run.original_filename },
    { icon: Hash, label: 'Source', value: run.source_type?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) },
    { icon: Calendar, label: 'Uploaded', value: new Date(run.created_at).toLocaleString() },
    { icon: User, label: 'By', value: run.uploaded_by || 'System' },
  ];

  const statCards = [
    { label: 'Total Rows', value: run.row_count_total || rows.length, icon: Database, color: 'slate' },
    { label: 'Success', value: run.row_count_success, icon: CheckCircle2, color: 'brand' },
    { label: 'Failed', value: run.row_count_failed, icon: XCircle, color: 'red' },
    { label: 'Flagged', value: run.row_count_flagged, icon: AlertTriangle, color: 'amber' },
  ];

  const colorMap = {
    brand: { bg: 'bg-brand-500/10', text: 'text-brand-400', border: 'border-brand-500/20' },
    red: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/20' },
    amber: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' },
    slate: { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/20' },
  };

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

      {/* Metadata card */}
      <div className="glass-card p-5">
        <div className="flex flex-wrap gap-6 mb-5">
          {metaItems.map(({ icon: Icon, label, value }) => (
            <div key={label} className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center">
                <Icon className="w-4 h-4 text-slate-400" />
              </div>
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">{label}</p>
                <p className="text-sm text-white font-medium truncate max-w-[200px]">{value}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {statCards.map(({ label, value, icon: Icon, color }) => {
            const c = colorMap[color];
            return (
              <div key={label} className={`flex items-center gap-3 px-4 py-3 rounded-xl ${c.bg} border ${c.border}`}>
                <Icon className={`w-5 h-5 ${c.text}`} />
                <div>
                  <p className={`text-xl font-bold ${c.text}`}>{value}</p>
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">{label}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Global error message */}
        {run.error_message && (
          <div className="mt-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 flex items-start gap-3">
            <XCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-red-400 uppercase tracking-wider">Ingestion Error</p>
              <p className="text-sm text-red-300 mt-1">{run.error_message}</p>
            </div>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 flex-wrap">
        {tabs.map(({ key, label, count, icon: Icon, color }) => {
          const isActive = filter === key;
          return (
            <button
              key={key}
              onClick={() => handleFilterChange(key)}
              className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 border
                ${isActive
                  ? `bg-${color === 'brand' ? 'brand' : color}-500/15 border-${color === 'brand' ? 'brand' : color}-500/40 text-${color === 'brand' ? 'brand' : color}-400`
                  : 'bg-white/5 border-border-subtle text-slate-400 hover:text-white hover:bg-white/10'
                }`}
            >
              <Icon className="w-4 h-4" />
              {label}
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-md text-xs font-bold
                ${isActive ? 'bg-white/10' : 'bg-white/5'}`}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Rows table */}
      {filteredRows.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <Database className="w-8 h-8 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">No rows found with this filter.</p>
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider w-12">#</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider w-28">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Data</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider w-32">Issues</th>
                  <th className="px-4 py-3 w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/30">
                {pagedRows.map((row, i) => (
                  <ExpandableRow key={row.id || i} row={row} index={i} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-border-subtle">
              <p className="text-xs text-slate-500">
                Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, filteredRows.length)} of {filteredRows.length} rows
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let p;
                  if (totalPages <= 5) p = i;
                  else if (page < 3) p = i;
                  else if (page > totalPages - 4) p = totalPages - 5 + i;
                  else p = page - 2 + i;
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`w-8 h-8 rounded-lg text-xs font-medium transition-colors
                        ${p === page ? 'bg-brand-500/20 text-brand-400' : 'text-slate-400 hover:text-white hover:bg-white/5'}`}
                    >
                      {p + 1}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
