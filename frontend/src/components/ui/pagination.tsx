import { CaretLeft, CaretRight } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  itemsPerPage: number;
  onPageChange: (page: number) => void;
  onItemsPerPageChange: (itemsPerPage: number) => void;
  className?: string;
}

export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  itemsPerPage,
  onPageChange,
  onItemsPerPageChange,
  className,
}: PaginationProps) {
  if (totalPages <= 1) return null;

  return (
    <div className={cn('flex flex-col sm:flex-row items-center justify-between gap-4 pt-4', className)}>
      <div className="flex items-center gap-3 text-sm text-[rgb(var(--color-muted-foreground))]">
        <span>Items per page:</span>
        <select
          value={itemsPerPage}
          onChange={(e) => onItemsPerPageChange(Number(e.target.value))}
          className="h-9 rounded-lg border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] px-2 text-sm font-medium"
        >
          <option value="10">10</option>
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
        <span>
          {(currentPage - 1) * itemsPerPage + 1}–{Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] disabled:opacity-30 transition-all"
          aria-label="Previous page"
        >
          <CaretLeft className="h-5 w-5" />
        </button>

        {generatePageNumbers(currentPage, totalPages).map((page, i) =>
          page === '...' ? (
            <span key={`e${i}`} className="px-1 text-[rgb(var(--color-muted-foreground))]">...</span>
          ) : (
            <button
              key={page}
              onClick={() => onPageChange(page as number)}
              className={cn(
                'touch-target-sm flex items-center justify-center rounded-xl font-semibold text-sm transition-all min-w-[40px]',
                page === currentPage
                  ? 'bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))]'
                  : 'border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] hover:bg-[rgb(var(--color-muted))]'
              )}
            >
              {page}
            </button>
          )
        )}

        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className="touch-target-sm flex items-center justify-center rounded-xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] disabled:opacity-30 transition-all"
          aria-label="Next page"
        >
          <CaretRight className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}

function generatePageNumbers(current: number, total: number): (number | string)[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages: (number | string)[] = [];

  if (current <= 4) {
    for (let i = 1; i <= 5; i++) pages.push(i);
    pages.push('...');
    pages.push(total);
  } else if (current >= total - 3) {
    pages.push(1);
    pages.push('...');
    for (let i = total - 4; i <= total; i++) pages.push(i);
  } else {
    pages.push(1);
    pages.push('...');
    pages.push(current - 1);
    pages.push(current);
    pages.push(current + 1);
    pages.push('...');
    pages.push(total);
  }

  return pages;
}
