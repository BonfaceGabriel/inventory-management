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
  search?: string;
  status?: string;
  min_date?: string;
  max_date?: string;
  min_amount?: number;
  max_amount?: number;
}): Promise<PaginatedResponse<Transaction>> => {
  const response = await api.get('/transactions/', { params });
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

export const formatCurrency = (amount: number | string): string => {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
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
