import { useState, useMemo } from 'react';
import { NavLink } from 'react-router-dom';
import {
  ListChecks,
  DollarSign,
  FileText,
  Package,
  BarChart3,
  ClipboardList,
  TrendingUp,
  Users,
  Tag,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

const allNavigation = [
  { name: 'Orders', to: '/transactions', icon: ListChecks, requiresAuth: true },
  { name: 'Manual Payments', to: '/manual-payments', icon: DollarSign, requiresProcessor: true },
  { name: 'Products', to: '/products', icon: Package, requiresAuth: true },
  { name: 'Stock Taking', to: '/stock-taking', icon: ClipboardList, requiresIssuer: true },
  { name: 'Stock Report', to: '/stock-report', icon: TrendingUp, requiresIssuer: true },
  { name: 'Analytics', to: '/analytics', icon: BarChart3, requiresAuth: true },
  { name: 'Reports', to: '/reports', icon: FileText, requiresProcessor: true },
  { name: 'User Management', to: '/users', icon: Users, requiresAdmin: true },
  { name: 'Promotions', to: '/promotions', icon: Tag, requiresAdmin: true },
];

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { hasProcessorAccess, hasIssuerAccess, hasRole } = useAuth();

  // Filter navigation based on user permissions
  const navigation = useMemo(() => {
    return allNavigation.filter((item) => {
      if (item.requiresAdmin) {
        return hasRole('ADMIN');
      }
      if (item.requiresProcessor) {
        return hasProcessorAccess();
      }
      if (item.requiresIssuer) {
        return hasIssuerAccess();
      }
      return true; // Show items that only require basic auth
    });
  }, [hasProcessorAccess, hasIssuerAccess, hasRole]);

  return (
    <aside
      className={cn(
        'relative border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 transition-all duration-300',
        isCollapsed ? 'w-20' : 'w-64'
      )}
    >
      {/* Header */}
      <div className="flex h-16 items-center border-b border-gray-200 dark:border-gray-700 px-6">
        {!isCollapsed && (
          <h1 className="text-xl font-bold text-blue-600 dark:text-blue-400 transition-opacity duration-300">
            Payment System
          </h1>
        )}
      </div>

      {/* Toggle Button */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="absolute -right-3 top-20 z-10 flex h-6 w-6 items-center justify-center rounded-full border-2 border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-600 dark:hover:border-blue-400 transition-all duration-200 hover:scale-110"
        aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>

      {/* Navigation */}
      <nav className="space-y-2 p-4">
        {navigation.map((item) => (
          <NavLink
            key={item.name}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-all duration-200',
                isCollapsed ? 'justify-center' : '',
                isActive
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/50'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:text-blue-600 dark:hover:text-blue-400'
              )
            }
            title={isCollapsed ? item.name : ''}
          >
            <item.icon
              className={cn(
                'h-5 w-5 transition-transform duration-200',
                isCollapsed && 'group-hover:scale-125'
              )}
            />
            {!isCollapsed && (
              <span className="transition-opacity duration-300">{item.name}</span>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
