import { ThemeToggle } from '../ui/theme-toggle';
import { Badge } from '../ui/badge';
import { useTransactionWebSocket } from '@/hooks/useWebSocket';

export function Header() {
  const { isConnected } = useTransactionWebSocket();

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
      </div>
    </header>
  );
}
