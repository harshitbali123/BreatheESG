import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Leaf, Eye, EyeOff, Loader2, Building2, User, Mail, Lock, Globe } from 'lucide-react';
import api from '../api/axios';

const COUNTRY_CODES = [
  { code: 'US', name: 'United States' },
  { code: 'IN', name: 'India' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'DE', name: 'Germany' },
  { code: 'FR', name: 'France' },
  { code: 'AU', name: 'Australia' },
  { code: 'CA', name: 'Canada' },
  { code: 'JP', name: 'Japan' },
  { code: 'SG', name: 'Singapore' },
  { code: 'AE', name: 'UAE' },
];

function InputField({ id, label, icon: Icon, type = 'text', placeholder, value, onChange, required = false, extra }) {
  const [show, setShow] = useState(false);
  const isPassword = type === 'password';
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-400 mb-1.5">{label}{required && <span className="text-red-400 ml-0.5">*</span>}</label>
      <div className="relative">
        {Icon && <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />}
        <input
          id={id}
          type={isPassword && show ? 'text' : type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          className={`w-full py-2.5 rounded-xl bg-white/5 border border-border-subtle text-white text-sm
            placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40 transition-all
            ${Icon ? 'pl-9' : 'px-4'} ${isPassword ? 'pr-10' : 'pr-4'}`}
        />
        {isPassword && (
          <button type="button" onClick={() => setShow(!show)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors">
            {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        )}
      </div>
      {extra}
    </div>
  );
}

export default function SignupPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [form, setForm] = useState({
    first_name: '', last_name: '',
    username: '', email: '',
    password: '', confirm_password: '',
    organization_name: '', country_code: 'US',
  });

  const set = (field) => (e) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
    setErrors((er) => ({ ...er, [field]: '' }));
    setGlobalError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrors({});
    setGlobalError('');
    try {
      const { data } = await api.post('/tenants/register/', form);
      // Store tokens & log in
      localStorage.setItem('access_token', data.access);
      localStorage.setItem('refresh_token', data.refresh);
      // Reload auth state by navigating — AuthContext reads localStorage on mount
      window.location.href = '/';
    } catch (err) {
      const resp = err.response?.data;
      if (resp?.errors) {
        const flat = {};
        Object.entries(resp.errors).forEach(([k, v]) => {
          flat[k] = Array.isArray(v) ? v.join(' ') : v;
        });
        setErrors(flat);
      } else {
        setGlobalError(resp?.detail || 'Registration failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-dark relative overflow-hidden py-8">
      {/* Background decorations */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-[500px] h-[500px] rounded-full bg-brand-500/5 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full bg-cyan-500/5 blur-3xl" />
      </div>

      <div className="relative w-full max-w-lg px-4 animate-fade-in">
        {/* Logo */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 mb-3 shadow-xl shadow-brand-500/20 animate-pulse-glow">
            <Leaf className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">BreatheESG</h1>
          <p className="text-slate-400 text-sm mt-1">Create your organization account</p>
        </div>

        {/* Card */}
        <div className="glass-card p-8">
          <h2 className="text-xl font-semibold text-white mb-1">Get started for free</h2>
          <p className="text-sm text-slate-400 mb-6">Set up your account and organization in seconds</p>

          {globalError && (
            <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              {globalError}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Organization */}
            <div className="p-4 rounded-xl bg-white/[0.03] border border-border-subtle space-y-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Organization</p>
              <InputField
                id="organization_name" label="Organization Name" icon={Building2} required
                placeholder="Acme Corp" value={form.organization_name} onChange={set('organization_name')}
                extra={errors.organization_name && <p className="text-xs text-red-400 mt-1">{errors.organization_name}</p>}
              />
              <div>
                <label htmlFor="country_code" className="block text-xs font-medium text-slate-400 mb-1.5">
                  Country <span className="text-red-400">*</span>
                </label>
                <div className="relative">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
                  <select
                    id="country_code"
                    value={form.country_code}
                    onChange={set('country_code')}
                    className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-white/5 border border-border-subtle text-white text-sm
                      focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer"
                  >
                    {COUNTRY_CODES.map(({ code, name }) => (
                      <option key={code} value={code} className="bg-slate-800">{name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Personal info */}
            <div className="p-4 rounded-xl bg-white/[0.03] border border-border-subtle space-y-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Your Details</p>
              <div className="grid grid-cols-2 gap-3">
                <InputField id="first_name" label="First Name" icon={User} placeholder="Jane" value={form.first_name} onChange={set('first_name')} />
                <InputField id="last_name" label="Last Name" icon={User} placeholder="Doe" value={form.last_name} onChange={set('last_name')} />
              </div>
              <InputField
                id="username" label="Username" icon={User} required
                placeholder="jane_doe" value={form.username} onChange={set('username')}
                extra={errors.username && <p className="text-xs text-red-400 mt-1">{errors.username}</p>}
              />
              <InputField
                id="email" label="Email Address" icon={Mail} type="email"
                placeholder="jane@acmecorp.com" value={form.email} onChange={set('email')}
                extra={errors.email && <p className="text-xs text-red-400 mt-1">{errors.email}</p>}
              />
            </div>

            {/* Password */}
            <div className="p-4 rounded-xl bg-white/[0.03] border border-border-subtle space-y-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Security</p>
              <InputField
                id="password" label="Password" icon={Lock} type="password" required
                placeholder="Min 8 characters" value={form.password} onChange={set('password')}
                extra={errors.password && <p className="text-xs text-red-400 mt-1">{errors.password}</p>}
              />
              <InputField
                id="confirm_password" label="Confirm Password" icon={Lock} type="password" required
                placeholder="Re-enter password" value={form.confirm_password} onChange={set('confirm_password')}
                extra={errors.confirm_password && <p className="text-xs text-red-400 mt-1">{errors.confirm_password}</p>}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold
                bg-gradient-to-r from-brand-500 to-brand-600 text-white
                hover:from-brand-400 hover:to-brand-500
                disabled:opacity-50 disabled:cursor-not-allowed
                transition-all duration-200 shadow-lg shadow-brand-500/20 mt-2"
            >
              {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Creating account…</> : 'Create Account'}
            </button>
          </form>

          <p className="text-center text-sm text-slate-500 mt-5">
            Already have an account?{' '}
            <Link to="/login" className="text-brand-400 hover:text-brand-300 font-medium transition-colors">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
