import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/axios';
import FileUpload from '../components/FileUpload';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import toast from 'react-hot-toast';

export default function IngestionPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const navigate = useNavigate();

  const loadRuns = async () => {
    try {
      const { data } = await api.get('/ingestion/runs/');
      setRuns(data.results || data);
    } catch (err) {
      console.error(err);
      toast.error('Failed to load ingestion runs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadRuns(); }, []);

  const handleUpload = async (formData) => {
    setUploading(true);
    try {
      const { data } = await api.post('/ingestion/upload/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast.success(`Upload complete! ${data.row_count_total} rows processed.`);
      loadRuns();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Upload failed';
      toast.error(detail);
    } finally {
      setUploading(false);
    }
  };

  const columns = [
    {
      key: 'original_filename',
      label: 'File Name',
      render: (val) => (
        <span className="font-medium text-white max-w-[200px] truncate block">{val}</span>
      ),
    },
    {
      key: 'source_type',
      label: 'Source',
      render: (val, row) => (
        <span className="text-slate-400">{row.source_type_display || val}</span>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      render: (val) => <StatusBadge status={val} />,
    },
    {
      key: 'row_count_total',
      label: 'Total Rows',
    },
    {
      key: 'row_count_success',
      label: 'Success',
      render: (val) => <span className="text-brand-400">{val}</span>,
    },
    {
      key: 'row_count_failed',
      label: 'Failed',
      render: (val) => <span className={val > 0 ? 'text-red-400' : 'text-slate-500'}>{val}</span>,
    },
    {
      key: 'row_count_flagged',
      label: 'Flagged',
      render: (val) => <span className={val > 0 ? 'text-amber-400' : 'text-slate-500'}>{val}</span>,
    },
    {
      key: 'created_at',
      label: 'Uploaded',
      render: (val) => (
        <span className="text-slate-500 text-xs">
          {new Date(val).toLocaleString()}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-white">Data Ingestion</h1>
        <p className="text-sm text-slate-400 mt-1">Upload and process emission data files</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <FileUpload onUpload={handleUpload} loading={uploading} />
        </div>
        <div className="lg:col-span-2">
          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <DataTable
              columns={columns}
              data={runs}
              pageSize={8}
              onRowClick={(row) => navigate(`/ingestion/${row.id}`)}
              emptyMessage="No ingestion runs yet. Upload a file to get started."
            />
          )}
        </div>
      </div>
    </div>
  );
}
