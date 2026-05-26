import { useEffect, useState } from 'react';
import api from '../api/axios';
import DataTable from '../components/DataTable';

export default function EmissionFactorsPage() {
  const [factors, setFactors] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/normalization/emission-factors/')
      .then(({ data }) => setFactors(data.results || data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const columns = [
    {
      key: 'fuel_type',
      label: 'Fuel Type',
      render: (v) => <span className="font-medium text-white capitalize">{v?.replace(/_/g, ' ')}</span>,
    },
    { key: 'unit', label: 'Unit' },
    {
      key: 'kg_co2e_per_unit',
      label: 'kg CO₂e / Unit',
      render: (v) => <span className="text-brand-400 font-mono">{parseFloat(v).toFixed(5)}</span>,
    },
    {
      key: 'source',
      label: 'Source',
      render: (v) => (
        <span className="px-2 py-1 rounded-md bg-blue-500/10 text-blue-400 text-xs font-medium">{v}</span>
      ),
    },
    { key: 'valid_from_year', label: 'Valid From' },
    {
      key: 'valid_to_year',
      label: 'Valid To',
      render: (v) => <span className="text-slate-400">{v || 'Present'}</span>,
    },
    {
      key: 'notes',
      label: 'Notes',
      render: (v) => <span className="text-slate-500 text-xs max-w-[200px] truncate block">{v || '—'}</span>,
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-white">Emission Factors</h1>
        <p className="text-sm text-slate-400 mt-1">Reference table of emission conversion factors (DEFRA 2023)</p>
      </div>
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable columns={columns} data={factors} pageSize={15} emptyMessage="No emission factors found." />
      )}
    </div>
  );
}
