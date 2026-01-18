import { useQuery } from '@tanstack/react-query';
import { getDailyReport, getDateRangeReport, getDiscrepanciesReport, getDailyReconciliationV2 } from '../api';

export function useDailyReport(date?: string, enabled: boolean = true) {
  return useQuery({
    queryKey: ['reports', 'daily', date],
    queryFn: () => getDailyReport(date),
    enabled,
  });
}

export function useDailyReconciliationV2(date?: string, enabled: boolean = true) {
  return useQuery({
    queryKey: ['reports', 'daily-v2', date],
    queryFn: () => getDailyReconciliationV2(date),
    enabled,
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
