import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { api, setMyLocation } from '../services/api';
import type { Location } from '../types/transaction.types';
import { jwtDecode } from 'jwt-decode';
import { queryClient } from '../lib/query-client';

interface User {
  id: number;
  username: string;
  email: string;
  role: 'ADMIN' | 'PROCESSOR' | 'ISSUER';
  role_display: string;
  current_location: Location | null;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasRole: (role: 'ADMIN' | 'PROCESSOR' | 'ISSUER') => boolean;
  hasProcessorAccess: () => boolean;
  hasIssuerAccess: () => boolean;
  currentLocation: Location | null;
  setCurrentLocation: (location: Location) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [currentLocation, setCurrentLocationState] = useState<Location | null>(null);

  // Helper function to check if token is expired
  const isTokenExpired = (token: string): boolean => {
    try {
      const decoded: any = jwtDecode(token);
      return decoded.exp * 1000 < Date.now();
    } catch {
      return true;
    }
  };

  // Helper function to refresh access token
  const refreshAccessToken = async (refreshToken: string): Promise<string | null> => {
    try {
      const response = await api.post('/auth/refresh/', { refresh: refreshToken });
      const { access } = response.data;
      localStorage.setItem('access_token', access);
      return access;
    } catch (error) {
      console.error('Token refresh failed:', error);
      return null;
    }
  };

  // Helper to hydrate location from profile response
  const hydrateLocationFromProfile = (profileUser: User) => {
    if (profileUser.current_location) {
      setCurrentLocationState(profileUser.current_location);
      // Use sessionStorage so each tab tracks its own location independently
      sessionStorage.setItem('current_location_id', profileUser.current_location.id);
      sessionStorage.setItem('current_location', JSON.stringify(profileUser.current_location));
    }
  };

  // Helper function to clear auth state
  const clearAuth = () => {
    setToken(null);
    setUser(null);
    setCurrentLocationState(null);
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    sessionStorage.removeItem('current_location_id');
    sessionStorage.removeItem('current_location');
    delete api.defaults.headers.common['Authorization'];
  };

  // Load token and user from localStorage on mount with validation
  useEffect(() => {
    const initAuth = async () => {
      const storedToken = localStorage.getItem('access_token');
      const storedRefresh = localStorage.getItem('refresh_token');
      const storedUser = localStorage.getItem('user');

      if (storedToken && storedUser && storedRefresh) {
        // Check if access token is expired
        if (isTokenExpired(storedToken)) {
          console.log('Access token expired, attempting refresh...');
          const newAccessToken = await refreshAccessToken(storedRefresh);
          if (newAccessToken) {
            console.log('Token refreshed successfully');
            setToken(newAccessToken);
            api.defaults.headers.common['Authorization'] = `Bearer ${newAccessToken}`;
            // Fetch fresh profile including current_location
            try {
              const profileResp = await api.get('/auth/profile/');
              const profileUser: User = profileResp.data;
              setUser(profileUser);
              localStorage.setItem('user', JSON.stringify(profileUser));
              hydrateLocationFromProfile(profileUser);
            } catch {
              setUser(JSON.parse(storedUser));
              const cached = sessionStorage.getItem('current_location');
              if (cached) setCurrentLocationState(JSON.parse(cached));
            }
          } else {
            console.log('Token refresh failed, clearing auth');
            clearAuth();
          }
        } else {
          // Token still valid
          console.log('Access token still valid');
          setToken(storedToken);
          api.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
          // Fetch fresh profile including current_location
          try {
            const profileResp = await api.get('/auth/profile/');
            const profileUser: User = profileResp.data;
            setUser(profileUser);
            localStorage.setItem('user', JSON.stringify(profileUser));
            hydrateLocationFromProfile(profileUser);
          } catch {
            setUser(JSON.parse(storedUser));
            const cached = sessionStorage.getItem('current_location');
            if (cached) setCurrentLocationState(JSON.parse(cached));
          }
        }
      } else if (!storedRefresh && storedToken) {
        // Have access token but no refresh token - clear everything
        console.log('No refresh token found, clearing auth');
        clearAuth();
      }
      setIsLoading(false);
    };

    initAuth();
  }, []);

  const login = async (username: string, password: string) => {
    const response = await api.post('/auth/login/', { username, password });
    const { access, refresh, user: userData } = response.data;

    setToken(access);
    setUser(userData);

    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    localStorage.setItem('user', JSON.stringify(userData));

    api.defaults.headers.common['Authorization'] = `Bearer ${access}`;

    // Hydrate location from login response if present
    if (userData.current_location) {
      setCurrentLocationState(userData.current_location);
      sessionStorage.setItem('current_location_id', userData.current_location.id);
      sessionStorage.setItem('current_location', JSON.stringify(userData.current_location));
    }

    // Clear React Query cache to ensure fresh data with new user permissions
    queryClient.clear();

    // Force page reload to refresh RBAC permissions and clear any cached state
    console.log('Login successful, reloading page to refresh permissions...');
    window.location.href = '/';
  };

  const logout = async () => {
    try {
      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        await api.post('/auth/logout/', { refresh: refreshToken });
      }
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setToken(null);
      setUser(null);
      setCurrentLocationState(null);
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      sessionStorage.removeItem('current_location_id');
      sessionStorage.removeItem('current_location');
      delete api.defaults.headers.common['Authorization'];

      // Clear React Query cache to remove any user-specific cached data
      queryClient.clear();

      // Force page reload to clear all cached state and RBAC permissions
      console.log('Logout successful, reloading page...');
      window.location.href = '/login';
    }
  };

  const hasRole = (role: 'ADMIN' | 'PROCESSOR' | 'ISSUER') => {
    return user?.role === role;
  };

  const hasProcessorAccess = () => {
    return user?.role === 'ADMIN' || user?.role === 'PROCESSOR';
  };

  const hasIssuerAccess = () => {
    return user?.role === 'ADMIN' || user?.role === 'ISSUER';
  };

  const setCurrentLocation = async (location: Location) => {
    await setMyLocation(location.id);
    setCurrentLocationState(location);
    sessionStorage.setItem('current_location_id', location.id);
    sessionStorage.setItem('current_location', JSON.stringify(location));
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        hasRole,
        hasProcessorAccess,
        hasIssuerAccess,
        currentLocation,
        setCurrentLocation,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
