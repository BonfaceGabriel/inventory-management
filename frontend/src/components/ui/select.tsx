import * as React from 'react';
import { cn } from '@/lib/utils';
import { CaretDown } from '@phosphor-icons/react';

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  error?: string;
}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, error, ...props }, ref) => {
    return (
      <div className="relative">
        <select
          className={cn(
            'flex h-12 w-full rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 pr-10 py-2 text-sm text-[rgb(var(--color-foreground))] appearance-none cursor-pointer transition-all',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(var(--color-ring))] focus-visible:ring-offset-2',
            'disabled:cursor-not-allowed disabled:opacity-50',
            error && 'border-red-500',
            className
          )}
          ref={ref}
          {...props}
        >
          {children}
        </select>
        <CaretDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[rgb(var(--color-muted-foreground))]" />
      </div>
    );
  }
);
Select.displayName = 'Select';

export { Select };
