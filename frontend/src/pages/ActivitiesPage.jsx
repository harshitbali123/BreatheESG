import { useEffect, useState, useCallback } from 'react';
import api from '../api/axios';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import toast from 'react-hot-toast';
import { Check, Flag, Lock, X, Loader2 } from 'lucide-react';

export default function ActivitiesPage() {
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [filters, setFilters] = useState({ scope: '', review_status: '', source_type: '', flagged: '' });
  const [modal, setModal] = useState({ open: false, type: '', activityId: null });
  const [note, setNote] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  const loadActivities = useCallback(async () => {
    try {
      const params = {};
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      const { data } = await api.get('/review/activities/', { params });
      setActivities(data.results || data);
    } catch { toast.error('Failed to load activities'); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { loadActivities(); }, [loadActivities]);

  const handleAction = async (id, type) => {
    if (type === 'flag') { setModal({ open: true, type: 'flag', activityId: id }); return; }
    setActionLoading(true);
    try { await api.post(`/review/activities/${id}/${type}/`, {}); toast.success(`Activity ${type}d`); loadActivities(); }
    catch (e) { toast.error(e.response?.data?.detail || `Failed`); }
    finally { setActionLoading(false); }
  };

  const handleModalSubmit = async () => {
    if (!note.trim()) { toast.error('Note required'); return; }
    setActionLoading(true);
    try { await api.post(`/review/activities/${modal.activityId}/${modal.type}/`, { note }); toast.success('Flagged'); setModal({ open: false }); setNote(''); loadActivities(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setActionLoading(false); }
  };

  const handleBulkApprove = async () => {
    if (!selectedIds.length) return;
    setBulkLoading(true);
    try { const { data } = await api.post('/review/activities/bulk-approve/', { ids: selectedIds }); toast.success(`${data.updated} approved`); setSelectedIds([]); loadActivities(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setBulkLoading(false); }
  };

  const columns = [
    { key: 'activity_date', label: 'Date', render: (v) => <span className="text-slate-300 text-xs">{new Date(v).toLocaleDateString()}</span> },
    { key: 'activity_type_display', label: 'Type', render: (v, r) => <span className="font-medium text-white">{v || r.activity_type}</span> },
    { key: 'description', label: 'Description', render: (v) => <span className="text-slate-400 max-w-[200px] truncate block text-xs">{v || '—'}</span> },
    { key: 'facility_name', label: 'Facility', render: (v) => <span className="text-slate-400 text-xs">{v || '—'}</span> },
    { key: 'scope', label: 'Scope', render: (v) => <span className={`inline-flex items-center justify-center w-7 h-7 rounded-lg text-xs font-bold ${v==='1'?'bg-emerald-500/15 text-emerald-400':v==='2'?'bg-cyan-500/15 text-cyan-400':'bg-purple-500/15 text-purple-400'}`}>{v}</span> },
    { key: 'normalized_kg_co2e', label: 'kg CO₂e', render: (v) => <span className="text-white font-mono text-xs">{parseFloat(v).toFixed(2)}</span> },
    { key: 'review_status', label: 'Status', render: (v) => <StatusBadge status={v} /> },
    { key: 'actions', label: 'Actions', sortable: false, render: (_, r) => {
      if (r.review_status === 'locked') return <span className="text-slate-600 text-xs">Locked</span>;
      return (<div className="flex gap-1" onClick={e=>e.stopPropagation()}>
        {r.review_status!=='approved'&&<button onClick={()=>handleAction(r.id,'approve')} className="p-1.5 rounded-lg text-slate-500 hover:text-brand-400 hover:bg-brand-500/10" title="Approve"><Check className="w-3.5 h-3.5"/></button>}
        {r.review_status!=='flagged'&&<button onClick={()=>handleAction(r.id,'flag')} className="p-1.5 rounded-lg text-slate-500 hover:text-amber-400 hover:bg-amber-500/10" title="Flag"><Flag className="w-3.5 h-3.5"/></button>}
        <button onClick={()=>handleAction(r.id,'lock')} className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-500/10" title="Lock"><Lock className="w-3.5 h-3.5"/></button>
      </div>);
    }},
  ];

  const filterOpts = [
    { key:'scope', options:[{v:'',l:'All Scopes'},{v:'1',l:'Scope 1'},{v:'2',l:'Scope 2'},{v:'3',l:'Scope 3'}] },
    { key:'review_status', options:[{v:'',l:'All Statuses'},{v:'pending',l:'Pending'},{v:'approved',l:'Approved'},{v:'flagged',l:'Flagged'},{v:'locked',l:'Locked'}] },
    { key:'source_type', options:[{v:'',l:'All Sources'},{v:'sap_mb51',l:'SAP MB51'},{v:'utility',l:'Utility'},{v:'travel',l:'Travel'}] },
    { key:'flagged', options:[{v:'',l:'All'},{v:'true',l:'Flagged Only'},{v:'false',l:'Not Flagged'}] },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-white">Activities Review</h1><p className="text-sm text-slate-400 mt-1">Review and manage normalized emission activities</p></div>
        {selectedIds.length>0&&<button onClick={handleBulkApprove} disabled={bulkLoading} className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-brand-500/15 text-brand-400 border border-brand-500/30 hover:bg-brand-500/25 disabled:opacity-50">
          {bulkLoading?<Loader2 className="w-4 h-4 animate-spin"/>:<Check className="w-4 h-4"/>}Approve Selected ({selectedIds.length})
        </button>}
      </div>
      <div className="glass-card p-4"><div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {filterOpts.map(({key,options})=><select key={key} value={filters[key]} onChange={e=>{setFilters(f=>({...f,[key]:e.target.value}));setLoading(true);}} className="px-3 py-2 rounded-lg bg-white/5 border border-border-subtle text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer">
          {options.map(({v,l})=><option key={v} value={v} className="bg-slate-800">{l}</option>)}
        </select>)}
      </div></div>
      {loading?<div className="flex items-center justify-center h-48"><div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin"/></div>:
      <DataTable columns={columns} data={activities} pageSize={12} selectable selectedIds={selectedIds} onSelectionChange={setSelectedIds} emptyMessage="No activities found."/>}
      {modal.open&&<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="glass-card w-full max-w-md p-6 mx-4 animate-fade-in">
          <div className="flex items-center justify-between mb-4"><h3 className="text-lg font-semibold text-white">Flag Activity</h3>
          <button onClick={()=>{setModal({open:false});setNote('');}} className="p-1 rounded-lg hover:bg-white/10 text-slate-500"><X className="w-5 h-5"/></button></div>
          <textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Reason for flagging..." rows={4} className="w-full px-4 py-3 rounded-xl bg-white/5 border border-border-subtle text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 resize-none"/>
          <div className="flex gap-3 mt-4">
            <button onClick={()=>{setModal({open:false});setNote('');}} className="flex-1 py-2 rounded-xl text-sm font-medium text-slate-400 bg-white/5 border border-border-subtle hover:bg-white/10">Cancel</button>
            <button onClick={handleModalSubmit} disabled={actionLoading} className="flex-1 flex items-center justify-center gap-2 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-amber-500 to-amber-600 text-white disabled:opacity-50">
              {actionLoading?<Loader2 className="w-4 h-4 animate-spin"/>:<Flag className="w-4 h-4"/>}Flag
            </button>
          </div>
        </div>
      </div>}
    </div>
  );
}
