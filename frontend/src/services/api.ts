import axios, { type AxiosInstance } from 'axios';
import type {
  Transaction,
  PaginatedResponse,
  DailyReport,
  CreateManualPaymentRequest,
  ManualPayment,
  Location,
} from '../types/transaction.types';

// Re-export types for convenience
export type { Transaction, ManualPayment, DailyReport } from '../types/transaction.types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const API_KEY = import.meta.env.VITE_API_KEY;

// Create axios instance
export const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - ensure Authorization header is always set from localStorage
api.interceptors.request.use(
  (config) => {
    // Ensure Authorization header is set from localStorage if not already present
    const token = localStorage.getItem('access_token');
    if (token && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // Inject location header for location-aware concurrency.
    // Uses sessionStorage (tab-isolated) so different tabs can operate on different locations.
    const locationId = sessionStorage.getItem('current_location_id');
    if (locationId) {
      config.headers['X-Location-ID'] = locationId;
    }

    console.log(`API Request: ${config.method?.toUpperCase()} ${config.url}`);
    console.log('  Authorization:', config.headers.Authorization || 'NOT SET');
    return config;
  },
  (error) => {
    console.error('Request interceptor error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor - handle 401/403 with token refresh logic
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: any) => void;
  reject: (reason?: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Handle 401 - Token expired
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Skip refresh logic if this IS the refresh endpoint failing
      if (originalRequest.url?.includes('/auth/refresh/')) {
        console.log('Refresh endpoint failed, clearing auth');
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        delete api.defaults.headers.common['Authorization'];

        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // Queue this request while refresh is in progress
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(token => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        }).catch(err => {
          return Promise.reject(err);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('refresh_token');

      if (refreshToken) {
        try {
          console.log('Attempting token refresh via interceptor...');
          // Attempt to refresh token
          const response = await api.post('/auth/refresh/', { refresh: refreshToken });
          const { access } = response.data;

          console.log('Token refreshed successfully via interceptor');
          // Update stored token
          localStorage.setItem('access_token', access);
          api.defaults.headers.common['Authorization'] = `Bearer ${access}`;

          // Process queued requests with new token
          processQueue(null, access);

          // Retry original request with new token
          originalRequest.headers.Authorization = `Bearer ${access}`;
          return api(originalRequest);
        } catch (refreshError) {
          // Refresh failed - clear auth and redirect
          console.log('Token refresh failed via interceptor, clearing auth');
          processQueue(refreshError, null);
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          localStorage.removeItem('user');
          delete api.defaults.headers.common['Authorization'];

          if (window.location.pathname !== '/login') {
            window.location.href = '/login';
          }
          return Promise.reject(refreshError);
        } finally {
          isRefreshing = false;
        }
      } else {
        // No refresh token - redirect to login
        console.log('No refresh token found, redirecting to login');
        localStorage.clear();
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    }

    // Handle 403 - Forbidden (insufficient permissions)
    if (error.response?.status === 403) {
      console.error('403 Forbidden:', error.response.data);
      console.error('Request URL:', error.config?.url);
      console.error('Request headers:', error.config?.headers);

      if (window.location.pathname !== '/unauthorized') {
        window.location.href = '/unauthorized';
      }
    }

    return Promise.reject(error);
  }
);

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
  // Add cache busting timestamp to prevent stale data
  const response = await api.get(`/transactions/${id}/`, {
    params: { _t: Date.now() }
  });
  return response.data;
};

export const getTransactionByTxId = async (txId: string): Promise<Transaction> => {
  // Add cache busting timestamp to prevent stale data
  const response = await api.get(`/transactions/by-tx-id/${txId}/`, {
    params: { _t: Date.now() }
  });
  return response.data;
};

export const revertToProcessing = async (
  transactionId: number,
  reason?: string
): Promise<{ success: boolean; message: string; transaction: Transaction }> => {
  const response = await api.post(`/transactions/${transactionId}/revert-to-processing/`, {
    reason: reason || 'Reverted to add more items'
  });
  return response.data;
};

export const revertToNotProcessed = async (
  transactionId: number,
  reason?: string
): Promise<{ success: boolean; message: string; transaction: Transaction }> => {
  const response = await api.post(`/transactions/${transactionId}/revert-to-not-processed/`, {
    reason: reason || 'Reverted to not processed for correction'
  });
  return response.data;
};

export const issueRegistrationFromPartial = async (
  transactionId: number
): Promise<{ success: boolean; message: string; transaction: Transaction }> => {
  const response = await api.post(`/transactions/${transactionId}/issue-registration-from-partial/`);
  return response.data;
};

export const addTransactionsToCombinedOrder = async (
  combinedOrderId: string,
  transactionIds: number[]
): Promise<{
  success: boolean;
  message: string;
  combined_order: any;
  added_count: number;
  new_total_amount: string;
}> => {
  const response = await api.post(
    `/combined-orders/${combinedOrderId}/add-transactions/`,
    { transaction_ids: transactionIds }
  );
  return response.data;
};

// ===================
// Issuer APIs
// ===================

export interface IssuerStats {
  fulfilled_today: number;
  amount_fulfilled_today: string;
}

export const getIssuerStats = async (): Promise<IssuerStats> => {
  const response = await api.get('/issuer/stats/');
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

// New V2 Reconciliation Report with X/Y formula
export interface ReconciliationV2Report {
  report_date: string;
  generated_at: string;
  x_value: number;
  y_value: number;
  result: number;
  is_balanced: boolean;
  x_formula: {
    description: string;
    mpesa_paybill: number;
    unused: number;
    pdq: number;
    previous: number;
    sales: number;
  };
  y_formula: {
    description: string;
    till: number;
    credit: number;
    kits: number;
  };
  raw_breakdown: {
    paybill: number;
    till: number;
    pdq: number;
  };
  details: {
    mpesa_paybill: { amount: number; count: number; description: string };
    unused: { amount: number; count: number; description: string; month_boundary?: string };
    pdq: { amount: number; count: number; description: string };
    previous: { amount: number; count: number; description: string };
    till: { amount: number; count: number; description: string; gateways?: string[] };
    credit: { amount: number; count: number; description: string };
    kits: { amount: number; count: number; unit_value: number; description: string };
    sales: { amount: number; count: number; description: string; by_gateway?: Record<string, { amount: number; count: number }> };
  };
  paybill_gateway: string | null;
  cmb_exception?: { tx_id: string; remaining_treated_as_fulfilled: number };
  is_launch_date: boolean;
}

export const getDailyReconciliationV2 = async (date?: string): Promise<ReconciliationV2Report> => {
  const params = date ? { report_date: date } : {};
  const response = await api.get('/reports/daily-reconciliation-v2/', { params });
  return response.data;
};

// ===================
// Unified Report Download
// ===================

export const downloadUnifiedReport = async (date: string) => {
  const response = await api.get(`/exports/report/?date=${date}`, {
    responseType: 'blob',
  });

  const url = window.URL.createObjectURL(new Blob([response.data]));
  const a = document.createElement('a');
  a.href = url;
  a.download = `eagle_shop_report_${date}.xlsx`;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
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
    COMBINED_FULFILLED: '#8B5CF6',
    CANCELLED: '#EF4444',
  };
  return colors[status] || '#6B7280';
};

export const getGatewayColor = (gatewayType: string): string => {
  const colors: Record<string, string> = {
    MPESA_PAYBILL: '#EC4899',
    MPESA_TILL: '#10B981',
    PDQ: '#0EA5E9',
  };
  return colors[gatewayType] || colors.PDQ;
};

export const getGatewayLabel = (gatewayType: string): string => {
  const labels: Record<string, string> = {
    MPESA_PAYBILL: 'PAYBILL',
    MPESA_TILL: 'TILL',
    PDQ: 'PDQ',
  };
  return labels[gatewayType] || gatewayType?.toUpperCase() || 'N/A';
};

export const getStatusLabel = (status: string): string => {
  const labels: Record<string, string> = {
    NOT_PROCESSED: 'Not Processed',
    PROCESSING: 'Processing',
    PARTIALLY_FULFILLED: 'Partially Fulfilled',
    FULFILLED: 'Fulfilled',
    COMBINED_FULFILLED: 'Combined Order Fulfilled',
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
  barcode: string | null;
  current_price: string;
  cost_price: string;
  current_pv: string;
  quantity: number;
  reorder_level: number;
  stock_status: 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK';
  product_line: number | null;
  product_line_name?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductLine {
  id: number;
  name: string;
  description: string;
  parent_line: number | null;
  subline_count: number;
  product_count: number;
  created_at: string;
  updated_at: string;
}

// Keep for backwards compatibility
export type ProductCategory = ProductLine;

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
  product_line?: number;
  is_active?: boolean;
}): Promise<Product[]> => {
  const response = await api.get('/products/', { params });
  return response.data;
};

export const getProductById = async (id: number): Promise<Product> => {
  const response = await api.get(`/products/${id}/`);
  return response.data;
};

export const searchProductBySku = async (sku?: string, prod_code?: string, barcode?: string): Promise<Product> => {
  const params = sku ? { sku } : prod_code ? { prod_code } : barcode ? { barcode } : {};
  const response = await api.get('/products/search/', { params });
  return response.data;
};

export const getProductSummary = async (): Promise<ProductSummary> => {
  const response = await api.get('/products/summary/');
  return response.data;
};

export const getProductLines = async (): Promise<ProductLine[]> => {
  const response = await api.get('/products/lines/');
  return response.data;
};

// Keep for backwards compatibility
export const getProductCategories = getProductLines;

export const updateProduct = async (id: number, data: Partial<Product>): Promise<Product> => {
  const response = await api.patch(`/products/${id}/`, data);
  return response.data;
};

export const createProduct = async (data: Omit<Product, 'id' | 'created_at' | 'updated_at' | 'stock_status' | 'product_line_name'>): Promise<Product> => {
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
  barcode?: string;
  quantity: number;
  scanned_by?: string;
}

export interface AppliedPromotion {
  promotion_name: string;
  discount_applied: string;
  discount_type: string;
  discount_value: string;
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
  applied_promotions?: AppliedPromotion[];
  message: string;
}

export interface PromotionProductItem {
  id?: number;
  product: number;
  product_name: string;
  product_code: string;
  min_quantity: number;
}

export interface Promotion {
  id: number;
  name: string;
  discount_type: 'FIXED' | 'PERCENTAGE';
  discount_value: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
  is_currently_active: boolean;
  products: PromotionProductItem[];
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatePromotionRequest {
  name: string;
  discount_type: 'FIXED' | 'PERCENTAGE';
  discount_value: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
  product_items: Array<{ product_id: number; min_quantity: number }>;
}

export const getPromotions = async (): Promise<Promotion[]> => {
  const response = await api.get('/promotions/');
  return response.data;
};

export const createPromotion = async (data: CreatePromotionRequest): Promise<Promotion> => {
  const response = await api.post('/promotions/', data);
  return response.data;
};

export const updatePromotion = async (id: number, data: Partial<CreatePromotionRequest>): Promise<Promotion> => {
  const response = await api.patch(`/promotions/${id}/`, data);
  return response.data;
};

export const deletePromotion = async (id: number): Promise<void> => {
  await api.delete(`/promotions/${id}/`);
};

// ===================
// Location APIs
// ===================

export const getLocations = (): Promise<Location[]> =>
  api.get<Location[]>('/locations/').then(r => r.data);

export const createLocation = (data: { name: string; notes?: string }): Promise<Location> =>
  api.post<Location>('/locations/', { ...data, location_type: 'FIELD' }).then(r => r.data);

export const closeLocation = (locationId: string): Promise<Location> =>
  api.post<Location>(`/locations/${locationId}/close/`).then(r => r.data);

export const setMyLocation = (locationId: string): Promise<{ success: boolean; current_location: Location }> =>
  api.post('/locations/set-mine/', { location_id: locationId }).then(r => r.data);

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

export const issueRegistrationKit = async (
  transactionId: number,
  quantity: number = 1
): Promise<any> => {
  // Issue registration kit for a registration transaction
  // User is automatically tracked from JWT token
  const response = await api.post(`/transactions/${transactionId}/issue-registration-kit/`, {
    quantity
  });
  return response.data;
};

export const completeIssuance = async (
  transactionId: number,
  _performedBy?: string,
  quantity?: number
): Promise<any> => {
  // User is automatically tracked from JWT token, no need to send performed_by
  // quantity is used for registration transactions
  const response = await api.post(`/transactions/${transactionId}/complete-issuance/`, {
    quantity: quantity || 1
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

export const removeLineItem = async (
  transactionId: number,
  lineItemId: number
): Promise<any> => {
  const response = await api.delete(`/transactions/${transactionId}/line-items/${lineItemId}/`);
  return response.data;
};

export const getCurrentIssuance = async (): Promise<CurrentIssuance | null> => {
  const response = await api.get('/transactions/current-issuance/');
  return response.data.current_issuance || response.data;
};

// ===================
// Time-Locking APIs (Phase 1)
// ===================

export interface LockPartialTransactionsRequest {
  target_date?: string; // Format: YYYY-MM-DD
  locked_by: string;
}

export interface LockPartialTransactionsResponse {
  success: boolean;
  locked_count: number;
  locked_tx_ids: string[];
  total_remaining_amount: string;
  locked_by: string;
  locked_at: string;
}

export const lockPartialTransactions = async (
  data: LockPartialTransactionsRequest
): Promise<LockPartialTransactionsResponse> => {
  const response = await api.post('/transactions/lock-partial/', data);
  return response.data;
};

export const getLockableTransactions = async (date?: string): Promise<PaginatedResponse<Transaction>> => {
  const params = date ? { date } : {};
  const response = await api.get('/transactions/lockable/', { params });
  return {
    count: response.data.count,
    next: null,
    previous: null,
    results: response.data.transactions,
  };
};

// ===================
// Combined Order APIs
// ===================

export interface CreateCombinedOrderRequest {
  transaction_ids: number[];
  customer_name?: string;
  customer_phone?: string;
  notes?: string;
  created_by: string;
}

export interface CreateCombinedOrderResponse {
  success: boolean;
  combined_order_id: string;
  combined_order: any;
  transaction_count: number;
  total_amount: string;
  transaction_ids: string[];
}

export const createCombinedOrder = async (
  data: CreateCombinedOrderRequest
): Promise<CreateCombinedOrderResponse> => {
  const response = await api.post('/combined-orders/', data);
  return response.data;
};

// ===================
// Combined Order Fulfillment APIs
// ===================

export const getCombinedOrderDetails = async (combinedOrderId: string) => {
  // Add cache busting timestamp to prevent stale data
  const response = await api.get(`/combined-orders/${combinedOrderId}/`, {
    params: { _t: Date.now() }
  });
  return response.data;
};

export const activateCombinedOrder = async (combinedOrderId: string, activatedBy: string) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/activate/`, {
    activated_by: activatedBy
  });
  return response.data;
};

export const scanProductToCombinedOrder = async (
  combinedOrderId: string,
  productId: number,
  quantity: number,
  scannedBy: string
) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/scan-staged/`, {
    product_id: productId,
    quantity,
    scanned_by: scannedBy
  });
  return response.data;
};

export const completeCombinedOrder = async (combinedOrderId: string, completedBy: string) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/complete/`, {
    completed_by: completedBy
  });
  return response.data;
};

export const cancelCombinedOrder = async (combinedOrderId: string) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/cancel/`);
  return response.data;
};

export const cancelCombinedOrderIssuance = async (combinedOrderId: string, reason?: string) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/cancel-issuance/`, {
    reason,
  });
  return response.data;
};

export const revertCombinedOrder = async (combinedOrderId: string, reason?: string, revertedBy?: string) => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/revert/`, {
    cancelled_by: revertedBy || 'user', // API uses cancelled_by field
    reason,
  });
  return response.data;
};

export const removeCombinedOrderLineItem = async (combinedOrderId: string, lineItemId: number) => {
  const response = await api.delete(`/combined-orders/${combinedOrderId}/line-items/${lineItemId}/`);
  return response.data;
};

export const markCombinedOrderAsRegistration = async (
  combinedOrderId: string,
  notes?: string
): Promise<{ success: boolean; message: string; is_registration: boolean }> => {
  const response = await api.post(`/combined-orders/${combinedOrderId}/mark-registration/`, {
    notes
  });
  return response.data;
};

// ===================
// Stock Take APIs
// ===================

export const createStockTakeSession = async (createdBy: string, notes?: string) => {
  const response = await api.post('/stock-take/sessions/', {
    created_by: createdBy,
    notes: notes || ''
  });
  return response.data;
};

export const getStockTakeSession = async (sessionId: string) => {
  const response = await api.get(`/stock-take/sessions/${sessionId}/`);
  return response.data;
};

export const scanProductToStockTake = async (
  sessionId: string,
  productId: number,
  quantity: number,
  scannedBy: string
) => {
  const response = await api.post(`/stock-take/sessions/${sessionId}/scan/`, {
    product_id: productId,
    quantity,
    scanned_by: scannedBy
  });
  return response.data;
};

export const completeStockTakeSession = async (sessionId: string, completedBy: string) => {
  const response = await api.post(`/stock-take/sessions/${sessionId}/complete/`, {
    completed_by: completedBy
  });
  return response.data;
};

export const removeStockTakeItem = async (sessionId: string, itemId: number) => {
  const response = await api.delete(`/stock-take/sessions/${sessionId}/items/${itemId}/delete/`);
  return response.data;
};

export const updateStockTakeItemQuantity = async (sessionId: string, itemId: number, quantity: number) => {
  const response = await api.patch(`/stock-take/sessions/${sessionId}/items/${itemId}/`, {
    quantity
  });
  return response.data;
};

export const listActiveStockTakeSessions = async () => {
  const response = await api.get('/stock-take/sessions/active/');
  return response.data;
};

export const cancelStockTakeSession = async (sessionId: string, cancelledBy: string) => {
  const response = await api.post(`/stock-take/sessions/${sessionId}/cancel/`, {
    cancelled_by: cancelledBy
  });
  return response.data;
};

export const cancelAllActiveStockTakeSessions = async (cancelledBy: string) => {
  const response = await api.post('/stock-take/sessions/cancel-all/', {
    cancelled_by: cancelledBy
  });
  return response.data;
};

export const updateStockTakeKitQuantity = async (sessionId: string, kitQuantity: number) => {
  const response = await api.patch(`/stock-take/sessions/${sessionId}/kit-quantity/`, {
    kit_quantity: kitQuantity
  });
  return response.data;
};

// ===================
// Admin Operations
// ===================

export const cancelFulfilledTransaction = async (
  transactionId: number,
  reason: string
): Promise<any> => {
  const response = await api.post(`/transactions/${transactionId}/cancel-fulfilled/`, {
    reason
  });
  return response.data;
};

// Cancel registration order (Admin only)
export const cancelRegistrationOrder = async (
  transactionId: number,
  reason: string
): Promise<any> => {
  const response = await api.post(`/transactions/${transactionId}/cancel-registration/`, {
    reason
  });
  return response.data;
};

// Delete transaction (Admin only)
export const deleteTransaction = async (
  transactionId: number,
  reason: string
): Promise<any> => {
  const response = await api.delete(`/transactions/${transactionId}/delete/`, {
    data: { reason }
  });
  return response.data;
};

// Mark transaction as registration
export const markTransactionAsRegistration = async (
  transactionId: number,
  notes?: string
): Promise<{
  success: boolean;
  transaction_id: number;
  tx_id: string;
  is_registration: boolean;
  message: string;
}> => {
  const response = await api.post(`/transactions/${transactionId}/mark-registration/`, {
    notes: notes || ''
  });
  return response.data;
};

// Unmark transaction as registration (before kit issuance)
export const unmarkTransactionAsRegistration = async (
  transactionId: number,
): Promise<{
  success: boolean;
  tx_id: string;
  is_registration: boolean;
  status: string;
  message: string;
}> => {
  const response = await api.post(`/transactions/${transactionId}/unmark-registration/`);
  return response.data;
};

// ============================================================================
// Stock Report API
// ============================================================================

export interface StockReportProduct {
  id: number;
  prod_code: string;
  prod_name: string;
  sku: string;
  barcode: string | null;
  quantity: number;
  reorder_level: number;
  current_price: number;
  cost_price: number;
  stock_value: number;
  stock_status: 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK';
  // Adjustment fields (present when viewing historical reports with adjustments)
  quantity_added?: number;
  quantity_deducted?: number;
  adjustment_notes?: string;
  opening_stock?: number;
  closing_stock?: number;
}

export interface StockReportProductLine {
  product_line_name: string;
  product_count: number;
  total_quantity: number;
  stock_value: number;
  products: StockReportProduct[];
}

export interface StockReportSummary {
  total_products: number;
  total_stock_value: number;
  total_cost_value: number;
  out_of_stock_count: number;
  low_stock_count: number;
  in_stock_count: number;
}

export interface StockReport {
  generated_at: string;
  report_date?: string; // Only for historical reports
  summary: StockReportSummary;
  product_lines: StockReportProductLine[];
}

// Get current stock report (JSON)
export const getStockReport = async (): Promise<StockReport> => {
  const response = await api.get('/reports/stock/');
  return response.data;
};

// Get historical stock report for a specific date (JSON)
export const getHistoricalStockReport = async (date: string): Promise<StockReport> => {
  const response = await api.get('/reports/stock/historical/', {
    params: { date }
  });
  return response.data;
};

// Download current stock report as XLSX
export const downloadStockReportXlsx = async () => {
  const response = await api.get('/reports/stock/xlsx/', {
    responseType: 'blob',
  });

  const blob = new Blob([response.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;

  // Extract filename from Content-Disposition header or use default
  const contentDisposition = response.headers['content-disposition'];
  const filename = contentDisposition
    ? contentDisposition.split('filename=')[1]?.replace(/"/g, '')
    : `Stock_Report_${new Date().toISOString().split('T')[0]}.xlsx`;

  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// Download historical stock report as XLSX for a specific date
export const downloadHistoricalStockReportXlsx = async (date: string) => {
  const response = await api.get('/reports/stock/historical/xlsx/', {
    params: { date },
    responseType: 'blob',
  });

  const blob = new Blob([response.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;

  // Extract filename from Content-Disposition header or use default
  const contentDisposition = response.headers['content-disposition'];
  const filename = contentDisposition
    ? contentDisposition.split('filename=')[1]?.replace(/"/g, '')
    : `Stock_Report_${date}.xlsx`;

  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};
