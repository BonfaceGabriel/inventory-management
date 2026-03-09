import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, User, MapPin, Check, Plus } from 'lucide-react';
import { toast } from 'sonner';
import { ThemeToggle } from '../ui/theme-toggle';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
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

export function Header() {
  const { isConnected } = useTransactionWebSocket();
  const { user, logout, currentLocation, setCurrentLocation } = useAuth();
  const navigate = useNavigate();

  const [locations, setLocations] = useState<Location[]>([]);
  const [locationDropdownOpen, setLocationDropdownOpen] = useState(false);
  const [newLocationDialogOpen, setNewLocationDialogOpen] = useState(false);
  const [newLocationName, setNewLocationName] = useState('');
  const [creatingLocation, setCreatingLocation] = useState(false);

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

  const handleSelectLocation = async (location: Location) => {
    try {
      await setCurrentLocation(location);
      toast.success(`Switched to ${location.name}`);
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
    <header className="flex h-16 items-center justify-between border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 px-6">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">M-Pesa Payment Management</h2>
        <Badge variant={isConnected ? "default" : "destructive"}>
          {isConnected ? '● Live' : '○ Offline'}
        </Badge>
      </div>
      <div className="flex items-center gap-4">
        <ThemeToggle />

        {/* Location switcher */}
        {user && (
          <DropdownMenu open={locationDropdownOpen} onOpenChange={setLocationDropdownOpen}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2">
                <MapPin className="h-4 w-4" />
                <span className="hidden sm:inline-block">{locationLabel}</span>
              </Button>
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

        {/* User menu */}
        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2">
                <User className="h-4 w-4" />
                <span className="hidden sm:inline-block">{user.username}</span>
              </Button>
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
                <LogOut className="mr-2 h-4 w-4" />
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
