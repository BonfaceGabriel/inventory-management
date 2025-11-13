import { useQuery } from '@tanstack/react-query';
import { getDailyReport, getDateRangeReport, getDiscrepanciesReport } from '../api';

export function useDailyReport(date?: string) {
  return useQuery({
    queryKey: ['reports', 'daily', date],
    queryFn: () => getDailyReport(date),
  });
}

export function useDateRangeReport(startDate: string, endDate: string) {
  return useQuery({
    queryKey: ['reports', 'range', startDate, endDate],
    queryFn: () => getDateRangeReport(startDate, endDate),
    enabled: !!startDate && !!endDate,
  });
}

export function useDiscrepanciesReport(date?: string) {
  return useQuery({
    queryKey: ['reports', 'discrepancies', date],
    queryFn: () => getDiscrepanciesReport(date),
  });
}
