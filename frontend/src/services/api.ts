import axios, { type AxiosInstance } from 'axios';
import type {
  Transaction,
  PaginatedResponse,
  DailyReport,
  CreateManualPaymentRequest,
  ManualPayment,
} from '../types/transaction.types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const API_KEY = import.meta.env.VITE_API_KEY;

// Create axios instance
export const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add API key to requests
if (API_KEY && API_KEY !== 'your-api-key-here') {
  api.defaults.headers.common['X-API-KEY'] = API_KEY;
}

// Set API key dynamically (for when user logs in/registers)
export const setApiKey = (apiKey: string) => {
  api.defaults.headers.common['X-API-KEY'] = apiKey;
  // Store in localStorage for persistence
  localStorage.setItem('api_key', apiKey);
};

// Load API key from localStorage on app start
const storedApiKey = localStorage.getItem('api_key');
if (storedApiKey) {
  setApiKey(storedApiKey);
}

// Clear API key (logout)
export const clearApiKey = () => {
  delete api.defaults.headers.common['X-API-KEY'];
  localStorage.removeItem('api_key');
};

// ===================
// Transaction APIs
// ===================

export const getTransactions = async (params?: {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  gateway_type?: string;
  gateway_id?: number;
  min_date?: string;
  max_date?: string;
  min_amount?: number;
  max_amount?: number;
  min_confidence?: number;
  max_confidence?: number;
}): Promise<PaginatedResponse<Transaction>> => {
  // Filter out empty string parameters to avoid sending ?status=&search=
  const filteredParams = Object.entries(params || {}).reduce((acc, [key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      acc[key] = value;
    }
    return acc;
  }, {} as Record<string, any>);

  const response = await api.get('/transactions/', { params: filteredParams });
  return response.data;
};

export const getTransactionById = async (id: number): Promise<Transaction> => {
  const response = await api.get(`/transactions/${id}/`);
  return response.data;
};

export const getTransactionByTxId = async (txId: string): Promise<Transaction> => {
  const response = await api.get(`/transactions/by-tx-id/${txId}/`);
  return response.data;
};

// ===================
// Report APIs
// ===================

export const getDailyReport = async (date?: string): Promise<DailyReport> => {
  const params = date ? { report_date: date } : {};
  const response = await api.get('/reports/daily-reconciliation/', { params });
  return response.data;
};

export const getDateRangeReport = async (startDate: string, endDate: string): Promise<any> => {
  const response = await api.get('/reports/date-range-reconciliation/', {
    params: {
      start_date: startDate,
      end_date: endDate,
    },
  });
  return response.data;
};

export const getDiscrepanciesReport = async (date?: string): Promise<any> => {
  const params = date ? { report_date: date } : {};
  const response = await api.get('/reports/discrepancies/', { params });
  return response.data;
};

// ===================
// PDF Downloads
// ===================

export const downloadDailyReportPDF = (date?: string) => {
  const params = date ? `?report_date=${date}` : '';
  const url = `${API_URL}/reports/daily-reconciliation/pdf/${params}`;

  // Get API key from headers
  const apiKey = api.defaults.headers.common['X-API-KEY'];

  // Open in new window with API key in query (or use fetch with auth header)
  window.open(`${url}&api_key=${apiKey}`, '_blank');
};

export const downloadDateRangeReportPDF = (startDate: string, endDate: string) => {
  const url = `${API_URL}/reports/date-range-reconciliation/pdf/?start_date=${startDate}&end_date=${endDate}`;

  const apiKey = api.defaults.headers.common['X-API-KEY'];
  window.open(`${url}&api_key=${apiKey}`, '_blank');
};

// Alternative: Download using fetch with proper auth
export const downloadReportWithAuth = async (endpoint: string, filename: string) => {
  try {
    const apiKey = api.defaults.headers.common['X-API-KEY'];
    const response = await fetch(`${API_URL}${endpoint}`, {
      headers: {
        'X-API-KEY': apiKey as string,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to download report');
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  } catch (error) {
    console.error('Download error:', error);
    throw error;
  }
};

// ===================
// Export APIs (CSV/XLSX)
// ===================

export const downloadTransactionsCSV = async (params?: {
  date?: string;
  start_date?: string;
  end_date?: string;
}) => {
  const queryParams = new URLSearchParams();
  if (params?.date) queryParams.append('date', params.date);
  if (params?.start_date) queryParams.append('start_date', params.start_date);
  if (params?.end_date) queryParams.append('end_date', params.end_date);

  const endpoint = `/exports/transactions/csv/?${queryParams}`;
  const filename = params?.date
    ? `transactions_${params.date}.csv`
    : params?.start_date && params?.end_date
    ? `transactions_${params.start_date}_to_${params.end_date}.csv`
    : `transactions_${new Date().toISOString().split('T')[0]}.csv`;

  await downloadReportWithAuth(endpoint, filename);
};

export const downloadTransactionsXLSX = async (params?: {
  date?: string;
  start_date?: string;
  end_date?: string;
}) => {
  const queryParams = new URLSearchParams();
  if (params?.date) queryParams.append('date', params.date);
  if (params?.start_date) queryParams.append('start_date', params.start_date);
  if (params?.end_date) queryParams.append('end_date', params.end_date);

  const endpoint = `/exports/transactions/xlsx/?${queryParams}`;
  const filename = params?.date
    ? `transactions_${params.date}.xlsx`
    : params?.start_date && params?.end_date
    ? `transactions_${params.start_date}_to_${params.end_date}.xlsx`
    : `transactions_${new Date().toISOString().split('T')[0]}.xlsx`;

  await downloadReportWithAuth(endpoint, filename);
};

// ===================
// Manual Payment APIs
// ===================

export const createManualPayment = async (
  payment: CreateManualPaymentRequest
): Promise<{ transaction: Transaction; manual_payment: ManualPayment }> => {
  const response = await api.post('/payments/manual/', payment);
  return response.data;
};

export const getManualPayments = async (params?: {
  page?: number;
  payment_method?: string;
  start_date?: string;
  end_date?: string;
}): Promise<PaginatedResponse<ManualPayment>> => {
  const response = await api.get('/payments/manual/list/', { params });
  return response.data;
};

export const getManualPaymentsSummary = async (params?: {
  start_date?: string;
  end_date?: string;
  payment_method?: string;
}): Promise<any> => {
  const response = await api.get('/payments/manual/summary/', { params });
  return response.data;
};

// ===================
// Device Registration (for getting API key)
// ===================

export interface DeviceRegistrationRequest {
  name: string;
  phone_number: string;
}

export interface DeviceRegistrationResponse {
  id: string;
  name: string;
  phone_number: string;
  api_key: string;
  created_at: string;
}

export const registerDevice = async (
  device: DeviceRegistrationRequest
): Promise<DeviceRegistrationResponse> => {
  // This endpoint doesn't require auth
  const response = await axios.post(`${API_URL}/devices/register/`, device);
  return response.data;
};

// ===================
// Helper Functions
// ===================

export const formatCurrency = (amount: number | string | null | undefined): string => {
  if (amount === null || amount === undefined || amount === '') {
    return 'KES 0.00';
  }
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (isNaN(num)) {
    return 'KES 0.00';
  }
  return `KES ${num.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleString('en-KE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const getStatusColor = (status: string): string => {
  const colors: Record<string, string> = {
    NOT_PROCESSED: '#6B7280',
    PROCESSING: '#3B82F6',
    PARTIALLY_FULFILLED: '#F59E0B',
    FULFILLED: '#10B981',
    CANCELLED: '#EF4444',
  };
  return colors[status] || '#6B7280';
};

export const getStatusLabel = (status: string): string => {
  const labels: Record<string, string> = {
    NOT_PROCESSED: 'Not Processed',
    PROCESSING: 'Processing',
    PARTIALLY_FULFILLED: 'Partially Fulfilled',
    FULFILLED: 'Fulfilled',
    CANCELLED: 'Cancelled',
  };
  return labels[status] || status;
};

// ===================
// Product APIs
// ===================

export interface Product {
  id: number;
  prod_code: string;
  prod_name: string;
  sku: string;
  sku_name: string;
  current_price: string;
  cost_price: string;
  current_pv: string;
  quantity: number;
  reorder_level: number;
  stock_status: 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK';
  category: number | null;
  category_name?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductCategory {
  id: number;
  name: string;
  description: string;
  parent_category: number | null;
  subcategory_count: number;
  product_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProductSummary {
  total_products: number;
  active_products: number;
  out_of_stock: number;
  low_stock: number;
  total_inventory_value: string;
  total_retail_value: string;
}

export const getProducts = async (params?: {
  search?: string;
  category?: number;
  is_active?: boolean;
}): Promise<Product[]> => {
  const response = await api.get('/products/', { params });
  return response.data;
};

export const getProductById = async (id: number): Promise<Product> => {
  const response = await api.get(`/products/${id}/`);
  return response.data;
};

export const searchProductBySku = async (sku?: string, prod_code?: string): Promise<Product> => {
  const params = sku ? { sku } : prod_code ? { prod_code } : {};
  const response = await api.get('/products/search/', { params });
  return response.data;
};

export const getProductSummary = async (): Promise<ProductSummary> => {
  const response = await api.get('/products/summary/');
  return response.data;
};

export const getProductCategories = async (): Promise<ProductCategory[]> => {
  const response = await api.get('/products/categories/');
  return response.data;
};

export const updateProduct = async (id: number, data: Partial<Product>): Promise<Product> => {
  const response = await api.patch(`/products/${id}/`, data);
  return response.data;
};

export const createProduct = async (data: Omit<Product, 'id' | 'created_at' | 'updated_at' | 'stock_status' | 'category_name'>): Promise<Product> => {
  const response = await api.post('/products/', data);
  return response.data;
};

export const deleteProduct = async (id: number): Promise<void> => {
  await api.delete(`/products/${id}/`);
};

// ===================
// Transaction Fulfillment APIs
// ===================

export interface BarcodeScanRequest {
  sku?: string;
  prod_code?: string;
  quantity: number;
  scanned_by?: string;
}

export interface BarcodeScanResponse {
  success: boolean;
  line_item_id: number;
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  transaction_totals: {
    amount_fulfilled: string;
    total_cost: string;
    total_pv: string;
    remaining_amount: string;
    status: string;
  };
  message: string;
}

export interface IssuanceResponse {
  success: boolean;
  transaction_id: number;
  tx_id: string;
  status: string;
  amount?: string;
  amount_fulfilled?: string;
  remaining_amount?: string;
  message: string;
}

export interface CurrentIssuance {
  transaction_id: number;
  tx_id: string;
  amount: string;
  amount_fulfilled: string;
  remaining_amount: string;
  total_cost: string;
  total_pv: string;
  status: string;
  line_items_count: number;
  line_items: Array<{
    id: number;
    product_code: string;
    product_name: string;
    quantity: number;
    unit_price: string;
    line_total: string;
  }>;
}

export const activateIssuance = async (transactionId: number): Promise<IssuanceResponse> => {
  const response = await api.post(`/transactions/${transactionId}/activate-issuance/`);
  return response.data;
};

export const scanBarcode = async (
  transactionId: number,
  data: BarcodeScanRequest
): Promise<BarcodeScanResponse> => {
  const response = await api.post(`/transactions/${transactionId}/scan-barcode/`, data);
  return response.data;
};

export const completeIssuance = async (
  transactionId: number,
  performedBy?: string
): Promise<any> => {
  const response = await api.post(`/transactions/${transactionId}/complete-issuance/`, {
    performed_by: performedBy,
  });
  return response.data;
};

export const cancelIssuance = async (
  transactionId: number,
  reason?: string
): Promise<any> => {
  const response = await api.post(`/transactions/${transactionId}/cancel-issuance/`, {
    reason,
  });
  return response.data;
};

export const getCurrentIssuance = async (): Promise<CurrentIssuance | null> => {
  const response = await api.get('/transactions/current-issuance/');
  return response.data.current_issuance || response.data;
};
