import { useState, useRef } from 'react';
import { Upload, FileText, X, Loader2 } from 'lucide-react';

export default function FileUpload({ onUpload, loading = false }) {
  const [file, setFile] = useState(null);
  const [sourceType, setSourceType] = useState('utility');
  const [reportingYear, setReportingYear] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef();

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_type', sourceType);
    if (reportingYear) formData.append('reporting_year', reportingYear);
    onUpload(formData);
  };

  const sourceTypes = [
    { value: 'utility', label: 'Utility Portal CSV' },
    { value: 'sap_mb51', label: 'SAP MB51 Flat File' },
    { value: 'travel', label: 'Corporate Travel CSV' },
  ];

  return (
    <form onSubmit={handleSubmit} className="glass-card p-6 space-y-5 animate-fade-in">
      <h3 className="text-lg font-semibold text-white">Upload Data File</h3>

      {/* Source type selector */}
      <div className="grid grid-cols-3 gap-2">
        {sourceTypes.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => setSourceType(value)}
            className={`px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 border
              ${
                sourceType === value
                  ? 'bg-brand-500/15 border-brand-500/40 text-brand-400'
                  : 'bg-white/5 border-border-subtle text-slate-400 hover:text-white hover:bg-white/10'
              }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Reporting year */}
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Reporting Year (optional)</label>
        <input
          type="number"
          min="2000"
          max="2100"
          value={reportingYear}
          onChange={(e) => setReportingYear(e.target.value)}
          placeholder="e.g. 2024"
          className="w-full px-3 py-2 rounded-lg bg-white/5 border border-border-subtle text-sm text-white 
            placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40 transition-all"
        />
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center gap-3 py-10 px-6 rounded-xl border-2 border-dashed cursor-pointer 
          transition-all duration-200
          ${
            dragOver
              ? 'border-brand-400 bg-brand-500/10'
              : file
              ? 'border-brand-500/30 bg-brand-500/5'
              : 'border-border-subtle hover:border-slate-500 hover:bg-white/[0.02]'
          }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.txt,.tsv"
          onChange={(e) => setFile(e.target.files[0])}
          className="hidden"
        />
        {file ? (
          <>
            <div className="w-12 h-12 rounded-xl bg-brand-500/20 flex items-center justify-center">
              <FileText className="w-6 h-6 text-brand-400" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-white">{file.name}</p>
              <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
            </div>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="absolute top-3 right-3 p-1 rounded-lg hover:bg-white/10 text-slate-500 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </>
        ) : (
          <>
            <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
              <Upload className="w-6 h-6 text-slate-500" />
            </div>
            <div className="text-center">
              <p className="text-sm text-slate-300">
                <span className="text-brand-400 font-medium">Click to upload</span> or drag and drop
              </p>
              <p className="text-xs text-slate-600 mt-1">CSV, TXT, TSV up to 10MB</p>
            </div>
          </>
        )}
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={!file || loading}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold
          bg-gradient-to-r from-brand-500 to-brand-600 text-white
          hover:from-brand-400 hover:to-brand-500 
          disabled:opacity-40 disabled:cursor-not-allowed
          transition-all duration-200 shadow-lg shadow-brand-500/20"
      >
        {loading ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Processing…</>
        ) : (
          <><Upload className="w-4 h-4" /> Upload & Process</>
        )}
      </button>
    </form>
  );
}
