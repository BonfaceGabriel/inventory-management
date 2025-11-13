import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { cn } from '@/lib/utils';

interface DateTimePickerProps {
  selected: Date | null;
  onChange: (date: Date | null) => void;
  showTimeSelect?: boolean;
  dateFormat?: string;
  timeFormat?: string;
  className?: string;
  placeholderText?: string;
  disabled?: boolean;
}

export function DateTimePicker({
  selected,
  onChange,
  showTimeSelect = true,
  dateFormat = "yyyy-MM-dd HH:mm",
  timeFormat = "HH:mm",
  className,
  placeholderText = "Select date and time",
  disabled = false,
}: DateTimePickerProps) {
  return (
    <DatePicker
      selected={selected}
      onChange={onChange}
      showTimeSelect={showTimeSelect}
      dateFormat={dateFormat}
      timeFormat={timeFormat}
      timeIntervals={15}
      timeCaption="Time"
      placeholderText={placeholderText}
      disabled={disabled}
      className={cn(
        "flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 ring-offset-white dark:ring-offset-slate-900 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-gray-500 dark:placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      wrapperClassName="w-full"
    />
  );
}
