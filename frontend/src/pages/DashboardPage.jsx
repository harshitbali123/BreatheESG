import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/axios';
import StatsCard from '../components/StatsCard';
import StatusBadge from '../components/StatusBadge';
import {
  BarChart3,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Lock,
  Clock,
  Zap,
  Flame,
  Plane,
} from 'lucide-react';
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts';

const SCOPE_COLORS = ['#10b981', '#06b6d4', '#8b5cf6'];
const STATUS_COLORS = ['#f59e0b', '#10b981', '#ef4444', '#64748b'];

function formatKg(val) {
  const n = parseFloat(val);
  if (isNaN(n)) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toFixed(1);
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const load = async () => {
      try {
        const [summaryRes, runsRes] = await Promise.all([
          api.get('/review/summary/'),
          api.get('/ingestion/runs/?page=1'),
        ]);
        setSummary(summaryRes.data);
        setRuns((runsRes.data.results || runsRes.data).slice(0, 5));
      } catch (err) {
        console.error('Dashboard load error:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <p className="text-slate-500">Unable to load dashboard data.</p>
      </div>
    );
  }

  const scope1 = parseFloat(summary.kg_co2e_by_scope['1'] || 0);
  const scope2 = parseFloat(summary.kg_co2e_by_scope['2'] || 0);
  const scope3 = parseFloat(summary.kg_co2e_by_scope['3'] || 0);
  const totalEmissions = scope1 + scope2 + scope3;

  const scopeData = [
    { name: 'Scope 1', value: scope1 },
    { name: 'Scope 2', value: scope2 },
    { name: 'Scope 3', value: scope3 },
  ].filter((d) => d.value > 0);

  const reviewData = [
    { name: 'Pending', value: summary.review_status_counts.pending },
    { name: 'Approved', value: summary.review_status_counts.approved },
    { name: 'Flagged', value: summary.review_status_counts.flagged },
    { name: 'Locked', value: summary.review_status_counts.locked },
  ].filter((d) => d.value > 0);

  const sourceData = [
    { name: 'SAP MB51', count: summary.source_type_counts.sap_mb51 },
    { name: 'Utility', count: summary.source_type_counts.utility },
    { name: 'Travel', count: summary.source_type_counts.travel },
  ];

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload?.length) {
      return (
        <div className="glass-card px-3 py-2 text-xs">
          <p className="text-white font-medium">{payload[0].name}</p>
          <p className="text-slate-400">{formatKg(payload[0].value)} kg CO₂e</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-sm text-slate-400 mt-1">Overview of your carbon emissions data</p>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Total Emissions"
          value={`${formatKg(totalEmissions)} kg`}
          subtitle="CO₂ equivalent"
          icon={BarChart3}
          color="brand"
        />
        <StatsCard
          title="Pending Review"
          value={summary.review_status_counts.pending}
          subtitle="Activities awaiting review"
          icon={Clock}
          color="amber"
        />
        <StatsCard
          title="Flagged Items"
          value={summary.review_status_counts.flagged}
          subtitle="Require attention"
          icon={AlertTriangle}
          color="red"
        />
        <StatsCard
          title="Approved"
          value={summary.review_status_counts.approved}
          subtitle="Activities verified"
          icon={CheckCircle2}
          color="brand"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Scope pie chart */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Emissions by Scope</h3>
          {scopeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={scopeData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  dataKey="value"
                  strokeWidth={0}
                >
                  {scopeData.map((_, i) => (
                    <Cell key={i} fill={SCOPE_COLORS[i % SCOPE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-slate-600 text-sm">No emission data</div>
          )}
          <div className="flex justify-center gap-4 mt-2">
            {['Scope 1', 'Scope 2', 'Scope 3'].map((label, i) => (
              <div key={label} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: SCOPE_COLORS[i] }} />
                {label}
              </div>
            ))}
          </div>
        </div>

        {/* Source bar chart */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Activities by Source</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={sourceData} barSize={32}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '0.75rem', fontSize: '12px' }}
                labelStyle={{ color: '#e2e8f0' }}
                itemStyle={{ color: '#10b981' }}
              />
              <Bar dataKey="count" fill="#10b981" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Review status donut */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Review Status</h3>
          {reviewData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={reviewData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  dataKey="value"
                  strokeWidth={0}
                >
                  {reviewData.map((_, i) => (
                    <Cell key={i} fill={STATUS_COLORS[i % STATUS_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '0.75rem', fontSize: '12px' }}
                  labelStyle={{ color: '#e2e8f0' }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-slate-600 text-sm">No review data</div>
          )}
          <div className="flex flex-wrap justify-center gap-3 mt-2">
            {['Pending', 'Approved', 'Flagged', 'Locked'].map((label, i) => (
              <div key={label} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: STATUS_COLORS[i] }} />
                {label}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent runs */}
      <div className="glass-card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Recent Ingestion Runs</h3>
          <button
            onClick={() => navigate('/ingestion')}
            className="text-xs text-brand-400 hover:text-brand-300 font-medium transition-colors"
          >
            View All →
          </button>
        </div>
        {runs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">File</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Source</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Rows</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/50">
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => navigate(`/ingestion/${run.id}`)}
                    className="cursor-pointer hover:bg-white/[0.03] transition-colors"
                  >
                    <td className="px-3 py-2.5 text-slate-300 whitespace-nowrap max-w-[200px] truncate">
                      {run.original_filename}
                    </td>
                    <td className="px-3 py-2.5 text-slate-400 whitespace-nowrap">
                      {run.source_type_display || run.source_type}
                    </td>
                    <td className="px-3 py-2.5"><StatusBadge status={run.status} /></td>
                    <td className="px-3 py-2.5 text-slate-400">{run.row_count_total}</td>
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                      {new Date(run.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500 py-4 text-center">No ingestion runs yet</p>
        )}
      </div>
    </div>
  );
}
