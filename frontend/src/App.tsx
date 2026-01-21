import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { Toaster } from 'sonner';
import { AuthProvider } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { queryClient } from './lib/query-client';
import { AppLayout } from './components/layout/AppLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import TransactionsPage from './pages/TransactionsPage';
import ManualPaymentsPage from './pages/ManualPaymentsPage';
import ReportsPage from './pages/ReportsPage';
import ProductsPage from './pages/ProductsPage';
import AnalyticsPage from './pages/AnalyticsPage';
import ScanningPage from './pages/ScanningPage';
import StockTakingPage from './pages/StockTakingPage';
import StockReportPage from './pages/StockReportPage';
import UserManagementPage from './pages/UserManagementPage';
import UnauthorizedPage from './pages/UnauthorizedPage';

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ThemeProvider>
          <WebSocketProvider>
            <BrowserRouter>
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<LoginPage />} />
                <Route path="/unauthorized" element={<UnauthorizedPage />} />

                {/* Protected routes */}
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <AppLayout />
                    </ProtectedRoute>
                  }
                >
                  <Route index element={<TransactionsPage />} />
                  <Route path="transactions" element={<TransactionsPage />} />
                  <Route
                    path="transactions/:id/scan"
                    element={
                      <ProtectedRoute>
                        <ScanningPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="manual-payments"
                    element={
                      <ProtectedRoute requireProcessorAccess>
                        <ManualPaymentsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route path="products" element={<ProductsPage />} />
                  <Route
                    path="analytics"
                    element={
                      <ProtectedRoute requireProcessorAccess>
                        <AnalyticsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="reports"
                    element={
                      <ProtectedRoute requireProcessorAccess>
                        <ReportsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="stock-taking"
                    element={
                      <ProtectedRoute requireIssuerAccess>
                        <StockTakingPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="stock-report"
                    element={
                      <ProtectedRoute requireIssuerAccess>
                        <StockReportPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="users"
                    element={
                      <ProtectedRoute requireAdminAccess>
                        <UserManagementPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
            </BrowserRouter>
            <Toaster position="top-right" richColors closeButton />
          </WebSocketProvider>
        </ThemeProvider>
      </AuthProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;
