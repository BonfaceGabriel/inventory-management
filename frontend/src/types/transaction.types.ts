// Location Type
export interface Location {
  id: string;
  name: string;
  location_type: 'MAIN' | 'FIELD';
  location_type_display: string;
  status: 'ACTIVE' | 'CLOSED';
  status_display: string;
  is_main: boolean;
  notes: string;
  created_at: string;
  closed_at: string | null;
}

// Raw Message Type
export interface RawMessage {
  id: number;
  raw_text: string;
  sender: string;
  timestamp: string;
  device_name?: string;
  processed: boolean;
}

// Line Item Type
export interface LineItem {
  id: number;
  product_code: string;
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  scanned_at: string;
  scanned_by: string;
}

// Activity Log Entry Type
export interface ActivityLogEntry {
  action: string;
  timestamp: string;
  user: string;
  role: string;
  details: string;
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
  amount_fulfilled?: string;
  remaining_amount?: string;
  notes: string;
  created_at: string;
  updated_at: string;
  is_locked?: boolean;
  is_in_issuance?: boolean;
  is_in_combined_order?: boolean;
  is_registration?: boolean;
  is_merchandise?: boolean;
  registration_kit_issued?: boolean;
  registration_kit_quantity?: number;
  registration_kit_amount_deducted?: string;
  combined_order_info?: CombinedOrderInfo | null;
  raw_messages?: RawMessage[];
  manual_payments?: ManualPayment[];
  line_items?: LineItem[];
  activity_log?: ActivityLogEntry[];
}

export type TransactionStatus =
  | 'NOT_PROCESSED'
  | 'PROCESSING'
  | 'PARTIALLY_FULFILLED'
  | 'FULFILLED'
  | 'COMBINED_FULFILLED'
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

// Combined Order Types
export interface CombinedOrderInfo {
  combined_order_id: string;
  parent_transaction_id?: number;
  status: string;
  total_amount: string;
  amount_fulfilled: string;
  remaining_amount: string;
  transaction_count: number;
  created_at: string;
  created_by: string;
}

export interface CombinedOrderLineItem {
  id: number;
  product_code: string;
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  scanned_at: string;
  scanned_by: string;
}

export interface CombinedOrder {
  combined_order_id: string;
  parent_transaction_id?: string;
  status: string;
  total_amount: string;
  amount_fulfilled: string;
  remaining_amount: string;
  transaction_count: number;
  customer_name: string;
  customer_phone: string;
  created_at: string;
  created_by: string;
  fulfilled_at?: string | null;
  fulfilled_by?: string;
  line_items?: CombinedOrderLineItem[];
  is_time_locked?: boolean;
  locked_at?: string | null;
  locked_by?: string;
}

// Stock Take Types
export interface StockTakeItem {
  id: number;
  product: number;
  product_name: string;
  product_code: string;
  sku: string;
  quantity_before: number;
  quantity_scanned: number;
  quantity_after: number;
  scanned_at: string;
  scanned_by: string;
}

export interface StockTakeSession {
  session_id: string;
  status: 'DRAFT' | 'COMPLETED' | 'CANCELLED';
  created_by: string;
  created_at: string;
  completed_at?: string | null;
  completed_by?: string;
  notes: string;
  kit_quantity: number;
  items?: StockTakeItem[];
  items_count?: number;
  total_quantity_added?: number;
}
