import * as React from 'react';
import { cn } from '@/lib/utils';

interface AlertDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

export function AlertDialog({ open, onOpenChange, children }: AlertDialogProps) {
  React.useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      <div
        className="fixed inset-0 bg-black/55 backdrop-blur-md"
        onClick={() => onOpenChange(false)}
      />
      <div className="relative z-50 w-full sm:max-w-md animate-slide-up">
        {children}
      </div>
    </div>
  );
}

interface AlertDialogContentProps {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogContent({ children, className }: AlertDialogContentProps) {
  return (
    <div
      className={cn(
        'bg-[rgb(var(--color-card))] border border-[rgb(var(--color-border))] rounded-t-2xl sm:rounded-2xl shadow-[0_24px_70px_rgb(10_7_4/0.35)] text-[rgb(var(--color-foreground))] w-full backdrop-blur-md',
        className
      )}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  );
}

interface AlertDialogHeaderProps {
  children: React.ReactNode;
}

export function AlertDialogHeader({ children }: AlertDialogHeaderProps) {
  return <div className="p-5 pb-2">{children}</div>;
}

interface AlertDialogTitleProps {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogTitle({ children, className }: AlertDialogTitleProps) {
  return (
    <h2 className={cn('text-lg font-semibold text-[rgb(var(--color-foreground))]', className)}>
      {children}
    </h2>
  );
}

interface AlertDialogDescriptionProps {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogDescription({ children, className }: AlertDialogDescriptionProps) {
  return (
    <p className={cn('text-sm text-[rgb(var(--color-muted-foreground))] mt-2 leading-relaxed', className)}>
      {children}
    </p>
  );
}

interface AlertDialogFooterProps {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogFooter({ children, className }: AlertDialogFooterProps) {
  return (
    <div className={cn('flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-end gap-2 p-5 pt-3', className)}>
      {children}
    </div>
  );
}

interface AlertDialogActionProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogAction({ children, className, ...props }: AlertDialogActionProps) {
  return (
    <button
      className={cn(
        'touch-target flex items-center justify-center px-5 py-2.5 bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] rounded-xl hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed font-semibold text-sm transition-all',
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

interface AlertDialogCancelProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  className?: string;
}

export function AlertDialogCancel({ children, className, ...props }: AlertDialogCancelProps) {
  return (
    <button
      className={cn(
        'touch-target flex items-center justify-center px-5 py-2.5 rounded-xl font-semibold text-sm transition-all border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] hover:bg-[rgb(var(--color-muted))] disabled:opacity-50 disabled:cursor-not-allowed',
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
