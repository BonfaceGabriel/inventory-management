import { useEffect, useState } from 'react';
import {
  getTransactions,
  getDailyReport,
  downloadDailyReportPDF,
  formatCurrency,
  formatDate,
  getStatusColor,
  getStatusLabel,
} from '../services/api';
import { useTransactionWebSocket } from '../hooks/useWebSocket';
import type { Transaction, DailyReport } from '../types/transaction.types';

export const Dashboard = () => {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [dailyReport, setDailyReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // WebSocket for real-time updates
  const {
    isConnected: wsConnected,
    transactions: liveTransactions,
    error: wsError,
  } = useTransactionWebSocket();

  // Load initial data
  useEffect(() => {
    loadData();
  }, []);

  // Update transactions from WebSocket
  useEffect(() => {
    if (liveTransactions.length > 0) {
      setTransactions((prev) => {
        // Avoid duplicates by checking transaction IDs
        const existingIds = new Set(prev.map(t => t.id));
        const newTransactions = liveTransactions.filter(t => !existingIds.has(t.id));
        return [...newTransactions, ...prev].slice(0, 50); // Keep last 50
      });
    }
  }, [liveTransactions]);

  const loadData = async () => {
    try {
      setLoading(true);
      const [txResponse, report] = await Promise.all([
        getTransactions({ page: 1 }),
        getDailyReport(),
      ]);

      setTransactions(txResponse.results);
      setDailyReport(report);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load data');
      console.error('Load error:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading">Loading...</div>;
  }

  if (error && !dailyReport) {
    return (
      <div className="error">
        <h2>Error</h2>
        <p>{error}</p>
        <button onClick={loadData}>Retry</button>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <header>
        <h1>Payment Dashboard</h1>
        <div className="connection-status">
          <span className={wsConnected ? 'connected' : 'disconnected'}>
            {wsConnected ? '● Connected' : '○ Disconnected'}
          </span>
          {wsError && <span className="error">{wsError}</span>}
        </div>
      </header>

      {/* Daily Summary */}
      {dailyReport && (
        <section className="summary">
          <h2>Today's Summary</h2>
          <div className="summary-cards">
            <div className="card">
              <h3>Total Transactions</h3>
              <p className="big-number">{dailyReport.summary.total_transactions}</p>
            </div>
            <div className="card">
              <h3>Total Amount</h3>
              <p className="big-number">{formatCurrency(dailyReport.summary.total_amount)}</p>
            </div>
            <div className="card">
              <h3>To Parent</h3>
              <p className="big-number">{formatCurrency(dailyReport.summary.total_to_parent)}</p>
            </div>
            <div className="card">
              <h3>To Shop</h3>
              <p className="big-number">{formatCurrency(dailyReport.summary.total_to_shop)}</p>
            </div>
          </div>
          <button onClick={() => downloadDailyReportPDF()} className="download-btn">
            📄 Download PDF Report
          </button>
        </section>
      )}

      {/* Recent Transactions */}
      <section className="transactions">
        <h2>Recent Transactions</h2>
        {transactions.length === 0 ? (
          <p>No transactions yet</p>
        ) : (
          <div className="transaction-table">
            <table>
              <thead>
                <tr>
                  <th>TX ID</th>
                  <th>Amount</th>
                  <th>Sender</th>
                  <th>Status</th>
                  <th>Time</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.id}>
                    <td>{tx.tx_id}</td>
                    <td>{formatCurrency(tx.amount)}</td>
                    <td>{tx.sender_name}</td>
                    <td>
                      <span
                        className="status-badge"
                        style={{ backgroundColor: getStatusColor(tx.status) }}
                      >
                        {getStatusLabel(tx.status)}
                      </span>
                    </td>
                    <td>{formatDate(tx.timestamp)}</td>
                    <td>{(tx.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};
