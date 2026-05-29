import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  adjustMerchandiseStock,
  fulfillMerchandiseOrder,
  getMerchandiseCatalog,
  getMerchandiseDailyReport,
  getMerchandiseOrder,
  getMerchandisePendingOrders,
  getMerchandiseStock,
  getMerchandiseStockMovements,
  type MerchandiseStockAdjustment,
  type MerchandiseFulfillRequest,
} from '../api';

export function useMerchandiseCatalog() {
  return useQuery({
    queryKey: ['merchandise', 'catalog'],
    queryFn: getMerchandiseCatalog,
  });
}

export function useMerchandisePendingOrders() {
  return useQuery({
    queryKey: ['merchandise', 'orders', 'pending'],
    queryFn: getMerchandisePendingOrders,
  });
}

export function useMerchandiseOrder(orderId: number | null) {
  return useQuery({
    queryKey: ['merchandise', 'orders', orderId],
    queryFn: () => getMerchandiseOrder(orderId as number),
    enabled: !!orderId,
  });
}

export function useFulfillMerchandiseOrder() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ orderId, payload }: { orderId: number; payload: MerchandiseFulfillRequest }) =>
      fulfillMerchandiseOrder(orderId, payload),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['merchandise', 'orders', 'pending'] });
      queryClient.invalidateQueries({ queryKey: ['merchandise', 'orders', variables.orderId] });
    },
  });
}

export function useMerchandiseDailyReport(date?: string) {
  return useQuery({
    queryKey: ['reports', 'merchandise', date],
    queryFn: () => getMerchandiseDailyReport(date),
  });
}

export function useMerchandiseStock() {
  return useQuery({
    queryKey: ['merchandise', 'stock'],
    queryFn: getMerchandiseStock,
  });
}

export function useMerchandiseStockMovements(limit: number = 100) {
  return useQuery({
    queryKey: ['merchandise', 'stock', 'movements', limit],
    queryFn: () => getMerchandiseStockMovements(limit),
  });
}

export function useAdjustMerchandiseStock() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ adjustments, notes }: { adjustments: MerchandiseStockAdjustment[]; notes?: string }) =>
      adjustMerchandiseStock(adjustments, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['merchandise', 'stock'] });
      queryClient.invalidateQueries({ queryKey: ['merchandise', 'stock', 'movements'] });
    },
  });
}
