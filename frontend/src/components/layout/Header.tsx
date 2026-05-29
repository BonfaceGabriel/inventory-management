import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  SignOut,
  UserCircle,
  MapPin,
  Check,
  Plus,
  CaretLeft,
  CirclesFour,
} from '@phosphor-icons/react';
import { toast } from 'sonner';
import { ThemeToggle } from '../ui/theme-toggle';
import { Badge } from '../ui/badge';
import { Input } from '../ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../ui/alert-dialog';
import { useTransactionWebSocket } from '@/hooks/useWebSocket';
import { useAuth } from '@/contexts/AuthContext';
import { getLocations, createLocation } from '@/services/api';
import type { Location } from '@/types/transaction.types';

const PAGE_TITLES: Record<string, string> = {
  '/transactions': 'Orders',
  '/manual-payments': 'Manual Payments',
  '/products': 'Products',
  '/stock-taking': 'Stock Taking',
  '/stock-report': 'Stock Report',
  '/analytics': 'Analytics',
  '/reports': 'Reports',
  '/merchandise': 'Merch Stock & Reports',
  '/users': 'User Management',
  '/promotions': 'Promotions',
};

export function Header() {
  const { isConnected } = useTransactionWebSocket();
  const { user, logout, currentLocation, setCurrentLocation } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [locations, setLocations] = useState<Location[]>([]);
  const [locationDropdownOpen, setLocationDropdownOpen] = useState(false);
  const [newLocationDialogOpen, setNewLocationDialogOpen] = useState(false);
  const [newLocationName, setNewLocationName] = useState('');
  const [creatingLocation, setCreatingLocation] = useState(false);

  const pageTitle = Object.entries(PAGE_TITLES).find(([path]) =>
    location.pathname === path || location.pathname.startsWith(path + '/')
  )?.[1] || 'Payment System';

  const showBack = location.pathname !== '/transactions' && location.pathname !== '/';

  useEffect(() => {
    if (locationDropdownOpen) {
      getLocations()
        .then(locs => setLocations(locs.filter(l => l.status === 'ACTIVE')))
        .catch(() => {});
    }
  }, [locationDropdownOpen]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const handleSelectLocation = async (loc: Location) => {
    try {
      await setCurrentLocation(loc);
      toast.success(`Switched to ${loc.name}`);
    } catch {
      toast.error('Failed to switch location');
    }
    setLocationDropdownOpen(false);
  };

  const handleCreateLocation = async () => {
    if (!newLocationName.trim()) return;
    setCreatingLocation(true);
    try {
      const created = await createLocation({ name: newLocationName.trim() });
      await setCurrentLocation(created);
      toast.success(`Created and switched to "${created.name}"`);
      setNewLocationName('');
      setNewLocationDialogOpen(false);
    } catch {
      toast.error('Failed to create location');
    } finally {
      setCreatingLocation(false);
    }
  };

  const locationLabel = currentLocation?.name ?? 'Main Shop';

  return (
    <header className="app-header flex items-center justify-between border-b border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/80 backdrop-blur-xl px-4 sm:px-6 gap-3">
      <div className="flex items-center gap-3 min-w-0">
        {showBack && (
          <button
            onClick={() => navigate(-1)}
            className="touch-target-sm flex items-center justify-center rounded-xl hover:bg-[rgb(var(--color-muted))] transition-colors -ml-1"
            aria-label="Go back"
          >
            <CaretLeft className="h-5 w-5" />
          </button>
        )}

        <div className="min-w-0">
          <h1 className="text-lg font-bold truncate flex items-center gap-2">
            <span key={location.pathname} className="flex items-center gap-2 header-title-enter">
              <CirclesFour className="h-5 w-5 text-[rgb(var(--color-primary))] shrink-0" />
              <span className="truncate">{pageTitle}</span>
            </span>
          </h1>
        </div>

        <Badge
          variant={isConnected ? 'default' : 'destructive'}
          className="hidden sm:inline-flex h-6 text-xs px-2 gap-1 shrink-0"
        >
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-[rgb(var(--color-secondary))] animate-pulse' : 'bg-[rgb(var(--color-destructive))]'}`} />
          {isConnected ? 'Live' : 'Off'}
        </Badge>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {/* Location badge — simple tap target */}
        {user && (
          <DropdownMenu open={locationDropdownOpen} onOpenChange={setLocationDropdownOpen}>
            <DropdownMenuTrigger asChild>
              <button className="touch-target-sm flex items-center gap-1.5 px-3 rounded-xl text-sm font-medium text-[rgb(var(--color-muted-foreground))] hover:bg-[rgb(var(--color-muted))] transition-colors">
                <MapPin className="h-4 w-4 text-[rgb(var(--color-primary))]" />
                <span className="max-w-[100px] truncate hidden xs:inline">{locationLabel}</span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Location</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {locations.length === 0 ? (
                <DropdownMenuItem disabled>Loading…</DropdownMenuItem>
              ) : (
                locations.map(loc => (
                  <DropdownMenuItem
                    key={loc.id}
                    onClick={() => handleSelectLocation(loc)}
                    className="flex items-center justify-between"
                  >
                    <span>{loc.name}</span>
                    {currentLocation?.id === loc.id && (
                      <Check className="h-4 w-4 text-green-500" />
                    )}
                  </DropdownMenuItem>
                ))
              )}
              {user.role === 'ADMIN' && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => {
                      setLocationDropdownOpen(false);
                      setNewLocationDialogOpen(true);
                    }}
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    New field location…
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <ThemeToggle />

        {/* User menu */}
        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="touch-target-sm flex items-center justify-center rounded-xl hover:bg-[rgb(var(--color-muted))] transition-colors">
                <UserCircle className="h-5 w-5 text-[rgb(var(--color-muted-foreground))]" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>
                <div className="flex flex-col space-y-1">
                  <p className="text-sm font-medium">{user.username}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{user.email}</p>
                  <Badge variant="secondary" className="w-fit mt-1">
                    {user.role_display}
                  </Badge>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="text-red-600 dark:text-red-400">
                <SignOut className="mr-2 h-4 w-4" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* New location dialog */}
      <AlertDialog open={newLocationDialogOpen} onOpenChange={setNewLocationDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>New field location</AlertDialogTitle>
            <AlertDialogDescription>
              Enter a name for the new field location. You will be switched to it automatically.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            placeholder="e.g. Nairobi Expo"
            value={newLocationName}
            onChange={e => setNewLocationName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreateLocation()}
          />
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setNewLocationName('')}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleCreateLocation} disabled={!newLocationName.trim() || creatingLocation}>
              {creatingLocation ? 'Creating…' : 'Create & Switch'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </header>
  );
}
