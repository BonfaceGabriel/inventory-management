import * as React from 'react';
import { CalendarIcon } from 'lucide-react';
import { format } from 'date-fns';
import { DayPicker } from 'react-day-picker';
import type { DateRange } from 'react-day-picker';
import 'react-day-picker/dist/style.css';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

interface DateRangePickerProps {
  from?: Date;
  to?: Date;
  onSelect: (range: { from?: Date; to?: Date }) => void;
  className?: string;
}

export function DateRangePicker({
  from,
  to,
  onSelect,
  className,
}: DateRangePickerProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [range, setRange] = React.useState<DateRange | undefined>({
    from,
    to,
  });

  const handleSelect = (selectedRange: DateRange | undefined) => {
    setRange(selectedRange);
    if (selectedRange?.from && selectedRange?.to) {
      onSelect({
        from: selectedRange.from,
        to: selectedRange.to,
      });
      setIsOpen(false);
    }
  };

  const handleClear = () => {
    setRange(undefined);
    onSelect({});
    setIsOpen(false);
  };

  return (
    <div className={cn('relative', className)}>
      <Button
        variant="outline"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full justify-start text-left font-normal',
          !range && 'text-gray-500 dark:text-gray-400'
        )}
      >
        <CalendarIcon className="mr-2 h-4 w-4" />
        {range?.from ? (
          range.to ? (
            <>
              {format(range.from, 'LLL dd, y')} -{' '}
              {format(range.to, 'LLL dd, y')}
            </>
          ) : (
            format(range.from, 'LLL dd, y')
          )
        ) : (
          <span>Pick a date range</span>
        )}
      </Button>

      {isOpen && (
        <div className="absolute z-50 mt-2 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-slate-800 p-4 shadow-lg">
          <DayPicker
            mode="range"
            selected={range}
            onSelect={handleSelect}
            numberOfMonths={2}
            className="date-range-picker"
          />
          <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <Button variant="outline" size="sm" onClick={handleClear}>
              Clear
            </Button>
            <Button variant="outline" size="sm" onClick={() => setIsOpen(false)}>
              Close
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
