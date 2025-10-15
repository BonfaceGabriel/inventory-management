import { useEffect, useState, useRef, useCallback } from 'react';
import type { Transaction, WebSocketMessage } from '../types/transaction.types';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

interface UseWebSocketReturn {
  isConnected: boolean;
  transactions: Transaction[];
  lastMessage: WebSocketMessage | null;
  error: string | null;
  reconnect: () => void;
}

export const useTransactionWebSocket = (): UseWebSocketReturn => {
  const [isConnected, setIsConnected] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isConnectingRef = useRef(false);

  const maxReconnectAttempts = 5;
  const reconnectDelay = 3000;

  useEffect(() => {
    // Prevent multiple simultaneous connections
    if (isConnectingRef.current || wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    isConnectingRef.current = true;

    const connect = () => {
      try {
        console.log('🔌 Connecting to WebSocket...');
        const ws = new WebSocket(`${WS_URL}/transactions/`);

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
            console.log('📨 WebSocket message:', data.type);

            setLastMessage(data);

            if (data.type === 'transaction.created') {
              setTransactions((prev) => [data.transaction, ...prev]);
            } else if (data.type === 'transaction.updated') {
              setTransactions((prev) =>
                prev.map((t) => (t.id === data.transaction.id ? data.transaction : t))
              );
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

          // Only reconnect if not intentionally closed (code 1000 from our cleanup)
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

    connect();

    // Cleanup on unmount
    return () => {
      console.log('🧹 Cleaning up WebSocket connection');
      isConnectingRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
        wsRef.current = null;
      }
    };
  }, []); // Empty deps - only run on mount/unmount

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    if (wsRef.current) {
      wsRef.current.close();
    }
  }, []);

  return {
    isConnected,
    transactions,
    lastMessage,
    error,
    reconnect,
  };
};

// Alternative: Simple WebSocket hook without auto-reconnect
export const useSimpleWebSocket = (onMessage: (message: WebSocketMessage) => void) => {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/transactions/`);

    ws.onopen = () => {
      console.log('✅ WebSocket connected');
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      const data: WebSocketMessage = JSON.parse(event.data);
      onMessage(data);
    };

    ws.onclose = () => {
      console.log('🔌 WebSocket disconnected');
      setIsConnected(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [onMessage]);

  return { isConnected };
};
