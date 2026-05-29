import { useQuery } from '@tanstack/react-query';
import {
  getAnalyticsOverview,
  getMerchandiseAnalytics,
  getProductAnalytics,
  getRevenueAnalytics,
  type AnalyticsDateRange,
} from '../api';

export function useAnalyticsOverview(params: AnalyticsDateRange) {
  return useQuery({
    queryKey: ['analytics', 'overview', params],
    queryFn: () => getAnalyticsOverview(params),
  });
}

export function useRevenueAnalytics(params: AnalyticsDateRange & { granularity?: 'day' | 'week' | 'month' }) {
  return useQuery({
    queryKey: ['analytics', 'revenue', params],
    queryFn: () => getRevenueAnalytics(params),
  });
}

export function useProductAnalytics(params: AnalyticsDateRange) {
  return useQuery({
    queryKey: ['analytics', 'products', params],
    queryFn: () => getProductAnalytics(params),
  });
}

export function useMerchandiseAnalytics(params: AnalyticsDateRange) {
  return useQuery({
    queryKey: ['analytics', 'merchandise', params],
    queryFn: () => getMerchandiseAnalytics(params),
  });
}
