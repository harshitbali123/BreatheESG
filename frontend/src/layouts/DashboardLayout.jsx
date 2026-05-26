import { Outlet } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import Topbar from '../components/Topbar';

export default function DashboardLayout() {
  return (
    <div className="min-h-screen bg-surface-dark">
      <Sidebar />
      {/* Main content area shifts based on sidebar — default expanded */}
      <div className="ml-[260px] transition-all duration-300 min-h-screen flex flex-col">
        <Topbar />
        <main className="flex-1 p-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
