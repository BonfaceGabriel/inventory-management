import { useState, useEffect } from 'react';
import { X, Funnel, MagnifyingGlass, CaretDown } from '@phosphor-icons/react';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { api } from '@/services/api';

export interface TransactionFilters {
  search?: string;
  status?: string;
  gateway_id?: number;
  gateway_type?: string;
  min_amount?: number;
  max_amount?: number;
  min_confidence?: number;
  max_confidence?: number;
  min_date?: string;
  max_date?: string;
  is_registration?: boolean;
}

interface Gateway {
  id: number;
  name: string;
  gateway_type: string;
  gateway_number: string;
}

interface AdvancedFiltersProps {
  filters: TransactionFilters;
  onFiltersChange: (filters: TransactionFilters) => void;
  onClear: () => void;
}

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'NOT_PROCESSED', label: 'Not Processed' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'PARTIALLY_FULFILLED', label: 'Partially Fulfilled' },
  { value: 'FULFILLED', label: 'Fulfilled' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

const REGISTRATION_OPTIONS = [
  { value: '', label: 'All Transactions' },
  { value: 'true', label: 'Registration Only' },
  { value: 'false', label: 'Non-Registration Only' },
];

export function AdvancedFilters({ filters, onFiltersChange, onClear }: AdvancedFiltersProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [gateways, setGateways] = useState<Gateway[]>([]);

  useEffect(() => {
    const fetchGateways = async () => {
      try {
        const response = await api.get('/gateways/');
        setGateways(response.data);
      } catch {}
    };
    fetchGateways();
  }, []);

  const hasActiveFilters = Object.values(filters).some(
    (value) => value !== undefined && value !== ''
  );

  const updateFilter = (key: keyof TransactionFilters, value: any) => {
    onFiltersChange({ ...filters, [key]: value || undefined });
  };

  const activeCount = Object.keys(filters).filter(
    (k) => filters[k as keyof TransactionFilters] !== undefined && filters[k as keyof TransactionFilters] !== ''
  ).length;

  return (
    <>
      {/* Filter bar — always visible */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <MagnifyingGlass className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-[rgb(var(--color-muted-foreground))]" />
          <input
            type="text"
            placeholder="Search TX ID, sender, phone..."
            value={filters.search || ''}
            onChange={(e) => updateFilter('search', e.target.value)}
            className="w-full h-11 pl-10 pr-4 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))] transition-all"
          />
        </div>

        <div className="relative">
          <select
            value={filters.status || ''}
            onChange={(e) => updateFilter('status', e.target.value)}
            className="h-11 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 pr-8 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <CaretDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[rgb(var(--color-muted-foreground))]" />
        </div>

        <button
          onClick={() => setIsOpen(true)}
          className={cn(
            'touch-target-sm flex items-center justify-center gap-2 px-4 rounded-xl border text-sm font-semibold transition-all',
            hasActiveFilters
              ? 'border-[rgb(var(--color-primary))] bg-[rgb(var(--color-primary))]/10 text-[rgb(var(--color-primary))]'
              : 'border-[rgb(var(--color-border))] text-[rgb(var(--color-muted-foreground))] hover:bg-[rgb(var(--color-muted))]'
          )}
        >
          <Funnel className="h-4 w-4" />
          <span className="hidden sm:inline">Filters</span>
          {activeCount > 0 && (
            <span className="inline-flex items-center justify-center h-5 min-w-[20px] px-1 rounded-full bg-[rgb(var(--color-primary))] text-xs font-bold text-[rgb(var(--color-primary-foreground))]">
              {activeCount}
            </span>
          )}
        </button>

        {hasActiveFilters && (
          <button
            onClick={onClear}
            className="touch-target-sm flex items-center justify-center rounded-xl text-[rgb(var(--color-destructive))] hover:bg-[rgb(var(--color-destructive))]/10 transition-colors"
            aria-label="Clear filters"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      {/* Bottom Sheet */}
      {isOpen && (
        <>
          <div className="bottom-sheet-overlay" onClick={() => setIsOpen(false)} />
          <div className="bottom-sheet">
            <div className="bottom-sheet-handle" />
            <div className="px-5 pb-2">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold">Filters</h2>
                <button
                  onClick={onClear}
                  className="text-sm font-semibold text-[rgb(var(--color-destructive))] touch-target-sm flex items-center justify-center px-3"
                >
                  Clear All
                </button>
              </div>
            </div>

            <div className="px-5 pb-6 space-y-5">
              {/* Status */}
              <div>
                <Label>Status</Label>
                <select
                  value={filters.status || ''}
                  onChange={(e) => updateFilter('status', e.target.value)}
                  className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              {/* Gateway */}
              <div>
                <Label>Gateway</Label>
                <select
                  value={filters.gateway_id?.toString() || ''}
                  onChange={(e) => updateFilter('gateway_id', e.target.value ? Number(e.target.value) : undefined)}
                  className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                >
                  <option value="">All Gateways</option>
                  {gateways.map((gw) => (
                    <option key={gw.id} value={gw.id}>{gw.name} ({gw.gateway_number})</option>
                  ))}
                </select>
              </div>

              {/* Registration Type */}
              <div>
                <Label>Transaction Type</Label>
                <select
                  value={filters.is_registration === undefined ? '' : filters.is_registration.toString()}
                  onChange={(e) => {
                    const value = e.target.value;
                    updateFilter('is_registration', value === '' ? undefined : value === 'true');
                  }}
                  className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                >
                  {REGISTRATION_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              {/* Date Range */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>From Date</Label>
                  <input
                    type="date"
                    value={filters.min_date?.split('T')[0] || ''}
                    onChange={(e) => updateFilter('min_date', e.target.value ? new Date(e.target.value).toISOString() : undefined)}
                    className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                  />
                </div>
                <div>
                  <Label>To Date</Label>
                  <input
                    type="date"
                    value={filters.max_date?.split('T')[0] || ''}
                    onChange={(e) => updateFilter('max_date', e.target.value ? new Date(e.target.value).toISOString() : undefined)}
                    className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                  />
                </div>
              </div>

              {/* Amount Range */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Min Amount (KES)</Label>
                  <input
                    type="number"
                    placeholder="0"
                    value={filters.min_amount || ''}
                    onChange={(e) => updateFilter('min_amount', e.target.value ? Number(e.target.value) : undefined)}
                    className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                  />
                </div>
                <div>
                  <Label>Max Amount (KES)</Label>
                  <input
                    type="number"
                    placeholder="Any"
                    value={filters.max_amount || ''}
                    onChange={(e) => updateFilter('max_amount', e.target.value ? Number(e.target.value) : undefined)}
                    className="w-full h-12 rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))]"
                  />
                </div>
              </div>

              {/* Apply button */}
              <button
                onClick={() => setIsOpen(false)}
                className="w-full h-12 rounded-xl bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] font-bold text-sm transition-all active:scale-[0.98]"
              >
                Apply Filters
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
