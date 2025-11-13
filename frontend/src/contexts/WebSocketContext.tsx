import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
import type { Transaction, WebSocketMessage } from '@/types/transaction.types';
import { formatCurrency } from '@/services/api';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

interface WebSocketContextType {
  isConnected: boolean;
  transactions: Transaction[];
  lastMessage: WebSocketMessage | null;
  error: string | null;
  reconnect: () => void;
  onTransactionCreated: (callback: (transaction: Transaction) => void) => () => void;
  onTransactionUpdated: (callback: (transaction: Transaction) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const useWebSocketContext = () => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocketContext must be used within WebSocketProvider');
  }
  return context;
};

interface WebSocketProviderProps {
  children: React.ReactNode;
}

export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isConnectingRef = useRef(false);

  // Callback refs for transaction events
  const transactionCreatedCallbacksRef = useRef<Set<(transaction: Transaction) => void>>(new Set());
  const transactionUpdatedCallbacksRef = useRef<Set<(transaction: Transaction) => void>>(new Set());
  const toastShownForTransactionRef = useRef<Set<number>>(new Set());

  const maxReconnectAttempts = 5;
  const reconnectDelay = 3000;

  const connect = () => {
    // Don't create multiple connections
    if (isConnectingRef.current || wsRef.current?.readyState === WebSocket.OPEN) {
      console.log('⚠️ WebSocket already connected or connecting');
      return;
    }

    isConnectingRef.current = true;

    try {
      console.log('🔌 Connecting to WebSocket...');
      const ws = new WebSocket(`${WS_URL}/ws/transactions/`);

      ws.onopen = () => {
        console.log('✅ WebSocket connected');
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
        isConnectingRef.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data);
          console.log('📨 WebSocket message:', data.type, data.transaction?.tx_id);

          setLastMessage(data);

          if (data.type === 'transaction.created') {
            const newTransaction = data.transaction;
            console.log('➕ New transaction created:', newTransaction.tx_id);

            // Show toast notification ONCE (centrally)
            if (!toastShownForTransactionRef.current.has(newTransaction.id)) {
              toastShownForTransactionRef.current.add(newTransaction.id);

              toast.success('New transaction received!', {
                description: `${newTransaction.tx_id} - ${formatCurrency(newTransaction.amount)} from ${newTransaction.sender_name}`,
                duration: 4000, // Auto-dismiss after 4 seconds
              });

              // Clean up old toast IDs (keep only last 50)
              if (toastShownForTransactionRef.current.size > 50) {
                const idsArray = Array.from(toastShownForTransactionRef.current);
                toastShownForTransactionRef.current = new Set(idsArray.slice(-50));
              }
            }

            // Update state
            setTransactions((prev) => {
              if (prev.some(t => t.id === newTransaction.id)) {
                console.log('⚠️ Transaction already exists in state, skipping');
                return prev;
              }
              return [newTransaction, ...prev];
            });

            // Notify all registered callbacks
            transactionCreatedCallbacksRef.current.forEach(callback => {
              try {
                callback(newTransaction);
              } catch (err) {
                console.error('Error in transaction created callback:', err);
              }
            });

          } else if (data.type === 'transaction.updated') {
            const updatedTransaction = data.transaction;
            console.log('🔄 Transaction updated:', updatedTransaction.tx_id);

            setTransactions((prev) =>
              prev.map((t) => (t.id === updatedTransaction.id ? updatedTransaction : t))
            );

            // Notify all registered callbacks
            transactionUpdatedCallbacksRef.current.forEach(callback => {
              try {
                callback(updatedTransaction);
              } catch (err) {
                console.error('Error in transaction updated callback:', err);
              }
            });
          }
        } catch (err) {
          console.error('❌ Error parsing WebSocket message:', err);
        }
      };

      ws.onerror = (event) => {
        console.error('❌ WebSocket error:', event);
        setError('WebSocket connection error');
        isConnectingRef.current = false;
      };

      ws.onclose = (event) => {
        console.log('🔌 WebSocket disconnected', event.code, event.reason);
        setIsConnected(false);
        isConnectingRef.current = false;

        // Only reconnect if not intentionally closed and haven't exceeded max attempts
        if (event.code !== 1000 && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current += 1;
          console.log(
            `🔄 Reconnecting... (Attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectDelay);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          console.error('❌ Max reconnect attempts reached');
          setError('Failed to connect to WebSocket after multiple attempts');
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('❌ Error creating WebSocket connection:', err);
      setError('Failed to create WebSocket connection');
      isConnectingRef.current = false;
    }
  };

  const disconnect = () => {
    console.log('🧹 Disconnecting WebSocket');
    isConnectingRef.current = false;

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Provider unmounting');
      wsRef.current = null;
    }
  };

  const reconnect = () => {
    console.log('🔄 Manual reconnect triggered');
    reconnectAttemptsRef.current = 0;
    disconnect();
    setTimeout(() => connect(), 100);
  };

  // Callback registration functions
  const onTransactionCreated = useCallback((callback: (transaction: Transaction) => void) => {
    transactionCreatedCallbacksRef.current.add(callback);
    // Return cleanup function
    return () => {
      transactionCreatedCallbacksRef.current.delete(callback);
    };
  }, []);

  const onTransactionUpdated = useCallback((callback: (transaction: Transaction) => void) => {
    transactionUpdatedCallbacksRef.current.add(callback);
    // Return cleanup function
    return () => {
      transactionUpdatedCallbacksRef.current.delete(callback);
    };
  }, []);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect();
    return () => disconnect();
  }, []);

  const value: WebSocketContextType = {
    isConnected,
    transactions,
    lastMessage,
    error,
    reconnect,
    onTransactionCreated,
    onTransactionUpdated,
  };

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
};
