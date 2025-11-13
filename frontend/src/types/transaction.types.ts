// Raw Message Type
export interface RawMessage {
  id: number;
  raw_text: string;
  sender: string;
  timestamp: string;
  device_name?: string;
  processed: boolean;
}

// Transaction Types
export interface Transaction {
  id: number;
  tx_id: string;
  amount: string;
  sender_name: string;
  sender_phone: string;
  timestamp: string;
  gateway_type: string;
  gateway_name?: string | null;
  destination_number: string;
  confidence: number;
  status: TransactionStatus;
  amount_expected: string;
  amount_paid: string;
  notes: string;
  created_at: string;
  updated_at: string;
  remaining_amount?: number;
  is_locked?: boolean;
  raw_messages?: RawMessage[];
  manual_payments?: ManualPayment[];
}

export type TransactionStatus =
  | 'NOT_PROCESSED'
  | 'PROCESSING'
  | 'PARTIALLY_FULFILLED'
  | 'FULFILLED'
  | 'CANCELLED';

export interface StatusDisplay {
  status: TransactionStatus;
  label: string;
  color: string;
  icon: string;
  is_locked: boolean;
}

// Report Types
export interface DailyReport {
  report_date: string;
  generated_at: string;
  date_range: {
    start: string;
    end: string;
  };
  gateway_reports: GatewayReport[];
  overall_totals: {
    total_amount: number;
    total_parent_settlement: number;
    total_shop_amount: number;
    total_transactions: number;
  };
  status_breakdown: {
    [key: string]: {
      label: string;
      count: number;
      total_amount: number;
    };
  };
  manual_payments: {
    total_count: number;
    total_amount: number;
    by_method: {
      [key: string]: {
        label: string;
        count: number;
        total_amount: number;
      };
    };
  };
  summary: {
    total_transactions: number;
    total_amount: number;
    total_to_parent: number;
    total_to_shop: number;
    gateways_count: number;
  };
}

export interface GatewayReport {
  gateway_id: number;
  gateway_name: string;
  gateway_type: string;
  gateway_number: string;
  settlement_type: string;
  transaction_count: number;
  total_amount: number;
  settlement: {
    parent_amount: number;
    shop_amount: number;
    settlement_type: string;
    calculation_note: string;
  };
  status_breakdown: {
    [key: string]: {
      label: string;
      count: number;
      total_amount: number;
    };
  };
  confidence_breakdown: {
    high_confidence: number;
    medium_confidence: number;
    low_confidence: number;
  };
  transactions: TransactionSummary[];
}

export interface TransactionSummary {
  tx_id: string;
  amount: number;
  sender_name: string;
  timestamp: string;
  status: TransactionStatus;
  confidence: number;
}

// WebSocket Message Types
export interface WebSocketMessage {
  type: 'transaction.created' | 'transaction.updated';
  transaction: Transaction;
}

// API Response Types
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ApiError {
  error: string;
  details?: any;
}

// Manual Payment Types
export interface ManualPayment {
  id: string;
  transaction: number;
  payment_method: 'PDQ' | 'BANK_TRANSFER' | 'CASH' | 'CHEQUE' | 'OTHER';
  reference_number: string;
  payer_name: string;
  payer_phone: string;
  payer_email: string;
  amount: string;
  payment_date: string;
  notes: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateManualPaymentRequest {
  payment_method: string;
  reference_number?: string;
  payer_name: string;
  payer_phone?: string;
  payer_email?: string;
  amount: string;
  payment_date: string;
  notes?: string;
  created_by?: string;
  gateway_id?: string;
}
