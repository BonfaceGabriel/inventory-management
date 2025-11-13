import { useQuery } from '@tanstack/react-query';
import { getTransactions, getTransactionById, getTransactionByTxId } from '../api';

export function useTransactions(params?: any) {
  return useQuery({
    queryKey: ['transactions', params],
    queryFn: () => getTransactions(params),
  });
}

export function useTransaction(id: number) {
  return useQuery({
    queryKey: ['transaction', id],
    queryFn: () => getTransactionById(id),
    enabled: !!id,
  });
}

export function useTransactionByTxId(txId: string) {
  return useQuery({
    queryKey: ['transaction', 'tx-id', txId],
    queryFn: () => getTransactionByTxId(txId),
    enabled: !!txId,
  });
}
