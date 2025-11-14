import { useState, useEffect } from 'react';
import { Filter, X } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { DateRangePicker } from '@/components/ui/date-range-picker';
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

export function AdvancedFilters({
  filters,
  onFiltersChange,
  onClear,
}: AdvancedFiltersProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [gateways, setGateways] = useState<Gateway[]>([]);

  useEffect(() => {
    // Fetch gateways from backend
    const fetchGateways = async () => {
      try {
        const response = await api.get('/gateways/');
        setGateways(response.data);
      } catch (error) {
        console.error('Failed to fetch gateways:', error);
      }
    };
    fetchGateways();
  }, []);

  const updateFilter = (key: keyof TransactionFilters, value: any) => {
    onFiltersChange({
      ...filters,
      [key]: value || undefined,
    });
  };

  const handleDateRangeChange = (range: { from?: Date; to?: Date }) => {
    onFiltersChange({
      ...filters,
      min_date: range.from?.toISOString(),
      max_date: range.to?.toISOString(),
    });
  };

  const hasActiveFilters = Object.values(filters).some(
    (value) => value !== undefined && value !== ''
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Filter className="h-5 w-5" />
              Filters
            </CardTitle>
            <CardDescription>
              {hasActiveFilters
                ? `${Object.keys(filters).filter((k) => filters[k as keyof TransactionFilters]).length} active filter(s)`
                : 'Search and filter orders'}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {hasActiveFilters && (
              <Button variant="outline" size="sm" onClick={onClear}>
                <X className="h-4 w-4 mr-1" />
                Clear All
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? 'Hide' : 'Show'} Advanced
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Basic Filters - Always Visible */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label htmlFor="search">Search</Label>
            <Input
              id="search"
              placeholder="TX ID, sender name, or phone..."
              value={filters.search || ''}
              onChange={(e) => updateFilter('search', e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="status">Status</Label>
            <Select
              id="status"
              value={filters.status || ''}
              onChange={(e) => updateFilter('status', e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="NOT_PROCESSED">Not Processed</option>
              <option value="PROCESSING">Processing</option>
              <option value="PARTIALLY_FULFILLED">Partially Fulfilled</option>
              <option value="FULFILLED">Fulfilled</option>
              <option value="CANCELLED">Cancelled</option>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="gateway">Gateway</Label>
            <Select
              id="gateway"
              value={filters.gateway_id?.toString() || ''}
              onChange={(e) => updateFilter('gateway_id', e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">All Gateways</option>
              {gateways.map((gw) => (
                <option key={gw.id} value={gw.id}>
                  {gw.name} ({gw.gateway_number})
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/* Advanced Filters - Collapsible */}
        {isExpanded && (
          <div className="space-y-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="space-y-2">
              <Label>Date Range</Label>
              <DateRangePicker
                from={filters.min_date ? new Date(filters.min_date) : undefined}
                to={filters.max_date ? new Date(filters.max_date) : undefined}
                onSelect={handleDateRangeChange}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="min_amount">Min Amount (KSh)</Label>
                <Input
                  id="min_amount"
                  type="number"
                  placeholder="e.g., 100"
                  value={filters.min_amount || ''}
                  onChange={(e) =>
                    updateFilter('min_amount', e.target.value ? Number(e.target.value) : undefined)
                  }
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="max_amount">Max Amount (KSh)</Label>
                <Input
                  id="max_amount"
                  type="number"
                  placeholder="e.g., 10000"
                  value={filters.max_amount || ''}
                  onChange={(e) =>
                    updateFilter('max_amount', e.target.value ? Number(e.target.value) : undefined)
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="min_confidence">Min Confidence (%)</Label>
                <Input
                  id="min_confidence"
                  type="number"
                  min="0"
                  max="100"
                  placeholder="e.g., 70"
                  value={filters.min_confidence ? filters.min_confidence * 100 : ''}
                  onChange={(e) =>
                    updateFilter(
                      'min_confidence',
                      e.target.value ? Number(e.target.value) / 100 : undefined
                    )
                  }
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="max_confidence">Max Confidence (%)</Label>
                <Input
                  id="max_confidence"
                  type="number"
                  min="0"
                  max="100"
                  placeholder="e.g., 100"
                  value={filters.max_confidence ? filters.max_confidence * 100 : ''}
                  onChange={(e) =>
                    updateFilter(
                      'max_confidence',
                      e.target.value ? Number(e.target.value) / 100 : undefined
                    )
                  }
                />
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
