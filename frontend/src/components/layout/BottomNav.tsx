import { useMemo, useRef, useEffect, useLayoutEffect, useState, useCallback } from 'react';
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

type TabIndicator = { left: number; width: number };

export function BottomNav() {
  const { hasProcessorAccess, hasIssuerAccess, hasRole } = useAuth();
  const location = useLocation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<string, HTMLAnchorElement>>(new Map());
  const [indicator, setIndicator] = useState<TabIndicator>({ left: 0, width: 0 });

  const visibleItems = useMemo(() => {
    return allNavigation.filter((item) => {
      if (item.requiresAdmin) return hasRole('ADMIN');
      if (item.requiresProcessor) return hasProcessorAccess();
      if (item.requiresIssuer) return hasIssuerAccess();
      return true;
    });
  }, [hasProcessorAccess, hasIssuerAccess, hasRole]);

  const isPathActive = useCallback(
    (path: string) =>
      location.pathname === path ||
      location.pathname.startsWith(path + '/') ||
      (path === '/transactions' && location.pathname === '/'),
    [location.pathname]
  );

  const activePath = useMemo(() => {
    const match = visibleItems.find((item) => isPathActive(item.to));
    return match?.to ?? visibleItems[0]?.to ?? '/transactions';
  }, [visibleItems, isPathActive]);

  const measureIndicator = useCallback(() => {
    const track = trackRef.current;
    const activeEl = itemRefs.current.get(activePath);
    if (!track || !activeEl) return;

    const trackRect = track.getBoundingClientRect();
    const activeRect = activeEl.getBoundingClientRect();
    setIndicator({
      left: activeRect.left - trackRect.left + track.scrollLeft,
      width: activeRect.width,
    });
  }, [activePath]);

  useLayoutEffect(() => {
    measureIndicator();
  }, [measureIndicator, visibleItems.length]);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const ro = new ResizeObserver(() => measureIndicator());
    ro.observe(track);
    window.addEventListener('resize', measureIndicator);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', measureIndicator);
    };
  }, [measureIndicator]);

  useEffect(() => {
    const activeEl = itemRefs.current.get(activePath);
    const container = scrollRef.current;
    if (!activeEl || !container) return;

    const scrollLeft =
      activeEl.offsetLeft - container.clientWidth / 2 + activeEl.clientWidth / 2;
    container.scrollTo({ left: Math.max(0, scrollLeft), behavior: 'auto' });
    requestAnimationFrame(measureIndicator);
  }, [activePath, measureIndicator]);

  const setItemRef = (path: string) => (el: HTMLAnchorElement | null) => {
    if (el) itemRefs.current.set(path, el);
    else itemRefs.current.delete(path);
  };

  return (
    <nav className="app-bottom-nav chrome-bottom-nav safe-area-bottom" aria-label="Main navigation">
      <div
        ref={scrollRef}
        className="chrome-nav-scroll scrollbar-none"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        <div ref={trackRef} className="chrome-nav-track">
          <div
            className="chrome-nav-tab"
            style={{
              width: indicator.width,
              transform: `translateX(${indicator.left}px)`,
              opacity: indicator.width > 0 ? 1 : 0,
            }}
            aria-hidden="true"
          />

          {visibleItems.map((item) => {
            const isActive = isPathActive(item.to);
            return (
              <NavLink
                key={item.to}
                ref={setItemRef(item.to)}
                to={item.to}
                end
                className={cn(
                  'chrome-nav-link no-tap-highlight',
                  isActive && 'chrome-nav-link--active'
                )}
              >
                <item.icon
                  className="chrome-nav-icon"
                  weight={isActive ? 'fill' : 'regular'}
                />
                <span className="chrome-nav-label">{item.name}</span>
              </NavLink>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
