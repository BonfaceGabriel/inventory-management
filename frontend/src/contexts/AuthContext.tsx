import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { api } from '../services/api';
import { jwtDecode } from 'jwt-decode';

interface User {
  id: number;
  username: string;
  email: string;
  role: 'ADMIN' | 'PROCESSOR' | 'ISSUER';
  role_display: string;
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
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

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

  // Helper function to clear auth state
  const clearAuth = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    delete api.defaults.headers.common['Authorization'];
  };

  // Load token and user from localStorage on mount with validation
  useEffect(() => {
    const initAuth = async () => {
      const storedToken = localStorage.getItem('access_token');
      const storedRefresh = localStorage.getItem('refresh_token');
      const storedUser = localStorage.getItem('user');

      if (storedToken && storedUser) {
        // Check if access token is expired
        if (isTokenExpired(storedToken)) {
          // Try to refresh with refresh token
          if (storedRefresh && !isTokenExpired(storedRefresh)) {
            const newAccessToken = await refreshAccessToken(storedRefresh);
            if (newAccessToken) {
              // Successfully refreshed
              setToken(newAccessToken);
              setUser(JSON.parse(storedUser));
              api.defaults.headers.common['Authorization'] = `Bearer ${newAccessToken}`;
            } else {
              // Refresh failed, clear auth
              clearAuth();
            }
          } else {
            // Both tokens expired, clear auth
            clearAuth();
          }
        } else {
          // Token still valid
          setToken(storedToken);
          setUser(JSON.parse(storedUser));
          api.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
        }
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
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      delete api.defaults.headers.common['Authorization'];
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
