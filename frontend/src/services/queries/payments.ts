import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createManualPayment, getManualPayments, getManualPaymentsSummary } from '../api';

export function useCreateManualPayment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createManualPayment,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      queryClient.invalidateQueries({ queryKey: ['manual-payments'] });
      queryClient.invalidateQueries({ queryKey: ['reports'] });
    },
  });
}

export function useManualPayments(params?: {
  page?: number;
  payment_method?: string;
  start_date?: string;
  end_date?: string;
}) {
  return useQuery({
    queryKey: ['manual-payments', params],
    queryFn: () => getManualPayments(params),
  });
}

export function useManualPaymentsSummary() {
  return useQuery({
    queryKey: ['manual-payments', 'summary'],
    queryFn: () => getManualPaymentsSummary(),
  });
}
