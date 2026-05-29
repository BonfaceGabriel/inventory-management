import { useState, useMemo } from 'react';
import { NavLink } from 'react-router-dom';
import {
  ListBullets,
  CurrencyDollar,
  FileText,
  Package,
  TShirt,
  ChartBar,
  ClipboardText,
  TrendUp,
  UsersThree,
  Ticket,
  CaretLeft,
  CaretRight,
} from '@phosphor-icons/react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

const allNavigation = [
  { name: 'Orders', to: '/transactions', icon: ListBullets, requiresAuth: true },
  { name: 'Manual Payments', to: '/manual-payments', icon: CurrencyDollar, requiresProcessor: true },
  { name: 'Products', to: '/products', icon: Package, requiresAuth: true },
  { name: 'Stock Taking', to: '/stock-taking', icon: ClipboardText, requiresIssuer: true },
  { name: 'Stock Report', to: '/stock-report', icon: TrendUp, requiresIssuer: true },
  { name: 'Analytics', to: '/analytics', icon: ChartBar, requiresAuth: true },
  { name: 'Reports', to: '/reports', icon: FileText, requiresProcessor: true },
  { name: 'Merch Stock & Reports', to: '/merchandise', icon: TShirt, requiresProcessor: true },
  { name: 'User Management', to: '/users', icon: UsersThree, requiresAdmin: true },
  { name: 'Promotions', to: '/promotions', icon: Ticket, requiresProcessor: true },
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
        'relative border-r border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/70 backdrop-blur-xl transition-all duration-300',
        isCollapsed ? 'w-20' : 'w-64'
      )}
    >
      {/* Header */}
      <div className="flex h-16 items-center border-b border-[rgb(var(--color-border))] px-6">
        {!isCollapsed && (
          <h1 className="text-xl font-bold text-[rgb(var(--color-primary))] transition-opacity duration-300">
            Payment System
          </h1>
        )}
      </div>

      {/* Toggle Button */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="absolute -right-3 top-20 z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-muted-foreground))] hover:text-[rgb(var(--color-primary))] hover:border-[rgb(var(--color-primary))] transition-all duration-200 hover:scale-110"
        aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {isCollapsed ? <CaretRight className="h-4 w-4" /> : <CaretLeft className="h-4 w-4" />}
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
                'group flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold transition-all duration-200',
                isCollapsed ? 'justify-center' : '',
                isActive
                  ? 'bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] shadow-lg'
                  : 'text-[rgb(var(--color-muted-foreground))] hover:bg-[rgb(var(--color-muted))]/80 hover:text-[rgb(var(--color-primary))]'
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
