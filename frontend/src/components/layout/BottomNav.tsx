import { useMemo, useRef, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
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
} from '@phosphor-icons/react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

interface NavItem {
  name: string;
  to: string;
  icon: React.ElementType;
  requiresAuth?: boolean;
  requiresProcessor?: boolean;
  requiresIssuer?: boolean;
  requiresAdmin?: boolean;
}

const allNavigation: NavItem[] = [
  { name: 'Orders', to: '/transactions', icon: ListBullets, requiresAuth: true },
  { name: 'Payments', to: '/manual-payments', icon: CurrencyDollar, requiresProcessor: true },
  { name: 'Products', to: '/products', icon: Package, requiresAuth: true },
  { name: 'Stock Take', to: '/stock-taking', icon: ClipboardText, requiresIssuer: true },
  { name: 'Stock Report', to: '/stock-report', icon: TrendUp, requiresIssuer: true },
  { name: 'Analytics', to: '/analytics', icon: ChartBar, requiresAuth: true },
  { name: 'Reports', to: '/reports', icon: FileText, requiresProcessor: true },
  { name: 'Merch', to: '/merchandise', icon: TShirt, requiresProcessor: true },
  { name: 'Users', to: '/users', icon: UsersThree, requiresAdmin: true },
  { name: 'Promos', to: '/promotions', icon: Ticket, requiresProcessor: true },
];

export function BottomNav() {
  const { hasProcessorAccess, hasIssuerAccess, hasRole } = useAuth();
  const location = useLocation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLAnchorElement>(null);

  const visibleItems = useMemo(() => {
    return allNavigation.filter((item) => {
      if (item.requiresAdmin) return hasRole('ADMIN');
      if (item.requiresProcessor) return hasProcessorAccess();
      if (item.requiresIssuer) return hasIssuerAccess();
      return true;
    });
  }, [hasProcessorAccess, hasIssuerAccess, hasRole]);

  useEffect(() => {
    if (activeRef.current && scrollRef.current) {
      const container = scrollRef.current;
      const active = activeRef.current;
      const scrollLeft = active.offsetLeft - container.clientWidth / 2 + active.clientWidth / 2;
      container.scrollTo({ left: Math.max(0, scrollLeft), behavior: 'smooth' });
    }
  }, [location.pathname]);

  return (
    <nav
      className={cn(
        'app-bottom-nav',
        'border-t border-[rgb(var(--color-border))]',
        'bg-[rgb(var(--color-card))]/95 backdrop-blur-xl',
        'safe-area-bottom'
      )}
    >
      <div
        ref={scrollRef}
        className="flex items-center overflow-x-auto px-1 py-0 scrollbar-none"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none', WebkitOverflowScrolling: 'touch' }}
      >
        {visibleItems.map((item) => {
          const isActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/');
          return (
            <NavLink
              key={item.to}
              ref={isActive ? activeRef : undefined}
              to={item.to}
              end
              className={cn(
                'flex flex-col items-center justify-center gap-0.5 flex-1 shrink-0',
                'min-h-[52px] min-w-[72px]',
                'px-2 py-1.5 rounded-xl',
                'transition-all duration-200',
                'no-tap-highlight',
                isActive
                  ? 'text-[rgb(var(--color-primary))] nav-tide-active nav-glow'
                  : 'text-[rgb(var(--color-muted-foreground))]'
              )}
            >
              <item.icon
                className={cn(
                  'h-6 w-6 transition-transform duration-200',
                  isActive && 'scale-110'
                )}
                weight={isActive ? 'fill' : 'regular'}
              />
              <span className="text-xs font-semibold leading-tight text-center whitespace-nowrap">
                {item.name}
              </span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
