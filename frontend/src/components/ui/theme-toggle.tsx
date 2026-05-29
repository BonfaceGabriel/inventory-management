import { MoonStars, SunDim } from '@phosphor-icons/react';
import { useTheme } from '@/contexts/ThemeContext';
import { Button } from './button';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
    >
      {theme === 'light' ? (
        <MoonStars className="h-5 w-5" />
      ) : (
        <SunDim className="h-5 w-5" />
      )}
    </Button>
  );
}
