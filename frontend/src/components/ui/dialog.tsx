import * as React from 'react';
import { createPortal } from 'react-dom';
import { X } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  fullScreen?: boolean;
}

export function Dialog({ open, onOpenChange, children, fullScreen }: DialogProps) {
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

  const content = fullScreen ? (
    <div className="fullscreen-overlay animate-slide-up-full z-[100]">
      <div className="flex flex-col h-full">{children}</div>
    </div>
  ) : (
    <div
      className={cn(
        'fixed inset-0 z-[100] flex items-end sm:items-center justify-center',
        // Keep modal panel above the fixed bottom nav on tablet/mobile
        'pb-[calc(var(--nav-height)+var(--nav-tab-lip)+var(--safe-bottom))] sm:pb-0'
      )}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="fixed inset-0 z-0 bg-black/55 backdrop-blur-md"
        onClick={() => onOpenChange(false)}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-[min(100%,42rem)] px-0 sm:px-4 animate-slide-up">
        {children}
      </div>
    </div>
  );

  return createPortal(content, document.body);
}

interface DialogContentProps {
  children: React.ReactNode;
  className?: string;
  fullScreen?: boolean;
}

export function DialogContent({ children, className, fullScreen }: DialogContentProps) {
  return (
    <div
      className={cn(
        fullScreen
          ? 'flex-1 flex flex-col min-h-0'
          : 'bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] border border-[rgb(var(--color-border))] rounded-t-2xl sm:rounded-2xl shadow-[0_24px_70px_rgb(10_7_4/0.35)] w-full max-h-[min(90vh,calc(100dvh-var(--nav-height)-var(--safe-bottom)-2rem))] sm:max-h-[90vh] overflow-y-auto',
        className
      )}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  );
}

interface DialogHeaderProps {
  children: React.ReactNode;
  onClose?: () => void;
  className?: string;
}

export function DialogHeader({ children, onClose, className }: DialogHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between p-5 border-b border-[rgb(var(--color-border))]', className)}>
      <div className="flex-1 min-w-0">{children}</div>
      {onClose && (
        <button
          onClick={onClose}
          className="touch-target-sm flex items-center justify-center rounded-xl hover:bg-[rgb(var(--color-muted))] transition-colors shrink-0"
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>
      )}
    </div>
  );
}

interface DialogTitleProps {
  children: React.ReactNode;
  className?: string;
}

export function DialogTitle({ children, className }: DialogTitleProps) {
  return (
    <h2 className={cn('text-lg font-semibold text-[rgb(var(--color-foreground))]', className)}>
      {children}
    </h2>
  );
}

interface DialogDescriptionProps {
  children: React.ReactNode;
  className?: string;
}

export function DialogDescription({ children, className }: DialogDescriptionProps) {
  return (
    <p className={cn('text-sm text-[rgb(var(--color-muted-foreground))] mt-0.5', className)}>
      {children}
    </p>
  );
}

interface DialogBodyProps {
  children: React.ReactNode;
  className?: string;
}

export function DialogBody({ children, className }: DialogBodyProps) {
  return <div className={cn('p-5', className)}>{children}</div>;
}

interface DialogFooterProps {
  children: React.ReactNode;
  className?: string;
}

export function DialogFooter({ children, className }: DialogFooterProps) {
  return (
    <div className={cn('flex items-center justify-end gap-3 p-5 border-t border-[rgb(var(--color-border))]', className)}>
      {children}
    </div>
  );
}
