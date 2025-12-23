import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: 'ADMIN' | 'PROCESSOR' | 'ISSUER';
  requireProcessorAccess?: boolean;
  requireIssuerAccess?: boolean;
  requireAdminAccess?: boolean;
}

export function ProtectedRoute({
  children,
  requiredRole,
  requireProcessorAccess,
  requireIssuerAccess,
  requireAdminAccess,
}: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, hasRole, hasProcessorAccess, hasIssuerAccess } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Check admin access requirement
  if (requireAdminAccess && !hasRole('ADMIN')) {
    return <Navigate to="/unauthorized" replace />;
  }

  // Check specific role requirement
  if (requiredRole && !hasRole(requiredRole)) {
    return <Navigate to="/unauthorized" replace />;
  }

  // Check processor access requirement
  if (requireProcessorAccess && !hasProcessorAccess()) {
    return <Navigate to="/unauthorized" replace />;
  }

  // Check issuer access requirement
  if (requireIssuerAccess && !hasIssuerAccess()) {
    return <Navigate to="/unauthorized" replace />;
  }

  return <>{children}</>;
}
