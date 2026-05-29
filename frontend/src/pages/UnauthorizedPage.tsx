import { useNavigate } from 'react-router-dom';
import { ShieldSlash, House, SignOut } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';

export default function UnauthorizedPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleGoHome = () => {
    navigate('/');
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-slate-900 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-100 dark:bg-red-900">
            <ShieldSlash className="h-10 w-10 text-red-600 dark:text-red-300" />
          </div>
          <CardTitle className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            Access Denied
          </CardTitle>
          <CardDescription className="text-gray-600 dark:text-gray-400">
            You don't have permission to access this page
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-slate-800 p-4">
            <p className="text-sm text-gray-700 dark:text-gray-300">
              {user ? (
                <>
                  You are logged in as <span className="font-semibold">{user.username}</span> with{' '}
                  <span className="font-semibold">{user.role_display}</span> role.
                  <br />
                  <br />
                  This page requires additional permissions that your account doesn't have.
                </>
              ) : (
                'You need to be logged in with the appropriate permissions to access this page.'
              )}
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <Button onClick={handleGoHome} className="w-full" variant="default">
              <House className="mr-2 h-4 w-4" />
              Go to Home
            </Button>
            {user && (
              <Button onClick={handleLogout} className="w-full" variant="outline">
                <SignOut className="mr-2 h-4 w-4" />
                Logout
              </Button>
            )}
          </div>

          <div className="text-center text-xs text-gray-500 dark:text-gray-400">
            If you believe you should have access to this page, please contact your administrator.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
