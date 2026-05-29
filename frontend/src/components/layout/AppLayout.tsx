import { Outlet, useLocation } from 'react-router-dom';
import { BottomNav } from './BottomNav';
import { Header } from './Header';

function PageTransition() {
  const location = useLocation();
  return (
    <div key={location.pathname} className="page-transition">
      <Outlet />
    </div>
  );
}

export function AppLayout() {
  return (
    <div className="app-shell">
      <Header />
      <main className="app-content px-4 sm:px-6">
        <PageTransition />
      </main>
      <BottomNav />
    </div>
  );
}
