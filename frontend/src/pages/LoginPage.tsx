import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { extractApiError } from '../lib/error-utils';
import { ThemeToggle } from '../components/ui/theme-toggle';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch (err: any) {
      setError(extractApiError(err, 'Login failed'));
    } finally { setIsLoading(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="fixed top-5 right-5 z-50">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm animate-fade-in">
        <div className="rounded-3xl bg-[rgb(var(--color-card))] border border-[rgb(var(--color-border))]/40 shadow-xl overflow-hidden">
          <div className="h-2 bg-gradient-to-r from-[rgb(var(--color-primary))] via-amber-400 to-[rgb(var(--color-primary))]" />
          <div className="p-8">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[rgb(var(--color-accent))] mb-5">
                <svg className="w-8 h-8 text-[rgb(var(--color-primary))]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
                </svg>
              </div>
              <h1 className="text-2xl font-bold">M-Pesa Payment<br /><span className="text-[rgb(var(--color-primary))]">Management</span></h1>
              <p className="mt-2 text-sm text-[rgb(var(--color-muted-foreground))]">Sign in to your account</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="text-sm font-semibold block mb-1.5">Username</label>
                <input
                  type="text" value={username} onChange={e => setUsername(e.target.value)}
                  required disabled={isLoading} placeholder="Enter your username"
                  className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))] transition-all"
                  autoComplete="username"
                />
              </div>
              <div>
                <label className="text-sm font-semibold block mb-1.5">Password</label>
                <input
                  type="password" value={password} onChange={e => setPassword(e.target.value)}
                  required disabled={isLoading} placeholder="Enter your password"
                  className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))] transition-all"
                  autoComplete="current-password"
                />
              </div>

              {error && (
                <div className="flex items-start gap-2.5 rounded-xl border border-[rgb(var(--color-destructive))]/25 bg-[rgb(var(--color-destructive))]/10 px-4 py-3 text-sm text-[rgb(var(--color-destructive))]">
                  <svg className="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                  <span>{error}</span>
                </div>
              )}

              <button type="submit" disabled={isLoading}
                className="w-full h-12 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm transition-all active:scale-[0.98] disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <><span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> Signing in...</>
                ) : 'Sign in'}
              </button>
            </form>

            <p className="mt-8 text-center text-xs text-[rgb(var(--color-muted-foreground))]">
              &copy; {new Date().getFullYear()} Inventory Management System
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
