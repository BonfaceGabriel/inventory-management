---
name: react-frontend
description: React 19 / TypeScript frontend architecture and development for this project. Use when working with React components, pages, hooks, API services, React Query, routing, context providers, shadcn/ui components, Tailwind CSS, Axios API client, or barcode scanner integration. Use for frontend state management patterns, form handling with React Hook Form + Zod, and websocket integration.
metadata:
  domain: frontend
  framework: react-typescript-vite
---

## Project Conventions

- **React 19 + TypeScript 5.9 + Vite 7.1** with `@` path alias → `src/`
- **State management**: React Context (Auth, WebSocket, Theme) + React Query for server state. No Redux.
- **API client**: `services/api.ts` (1523 lines) — Axios instance with JWT auto-refresh interceptor. All API calls exported as named functions from this file.
- **Query hooks**: `services/queries/` split by domain: `payments.ts`, `transactions.ts`, `reports.ts`, `analytics.ts`, `merchandise.ts`
- **shadcn/ui** + Radix primitives + Tailwind CSS v4. Components in `components/ui/`.
- **Routing**: React Router v7 in `App.tsx`. Role-aware route protection via `ProtectedRoute` component.
- **Forms**: React Hook Form + Zod validation.

## Key Gotchas

- **`X-Location-ID` header**: Set from `sessionStorage.getItem('current_location_id')` via Axios interceptor (not `localStorage`). Different browser tabs can have different locations.
- **JWT refresh queue**: `api.ts` has a `failedQueue` pattern — when multiple requests fail with 401, only one refresh request is sent and all queued requests retry with the new token.
- **WebSocket connection**: Managed by `WebSocketContext` + `useWebSocket` hook. Connects to `ws://.../ws/transactions/`. Provides `onTransactionCreated` and `onTransactionUpdated` callbacks.
- **Role-aware components**: Use `useAuth()` hook methods — `hasProcessorAccess()`, `hasIssuerAccess()`, `isAdmin()` — never check roles with string comparison.
- **Product search for barcode**: The `api.ts` function `searchProductBySku` accepts `sku`, `prod_code`, or `barcode` params. The backend tries `barcode` field first, then falls back to `sku`/`prod_code`.
- **Pagination**: All list endpoints return `PaginatedResponse` with `results`, `count`, `next`, `previous`. Transaction list also returns `page`, `page_size`, `total_pages`.
- **Combined order IDs**: Start with `CMB-` prefix. The `ScanningPage` checks `id?.startsWith('CMB-')` to determine if it's dealing with a combined order vs single transaction.

## File Map

```
frontend/src/
├── main.tsx                  # Entry point
├── App.tsx                   # Routing + providers
├── index.css                 # Tailwind globals
├── pages/                    # 15 page components
│   ├── LoginPage.tsx
│   ├── TransactionsPage.tsx  # Main dashboard + combine dialog
│   ├── FulfillmentPage.tsx   # Issuer fulfillment queue + barcode scan
│   ├── ScanningPage.tsx      # Active scanning (single + combined)
│   ├── ManualPaymentsPage.tsx # PDQ/Cash payment form
│   ├── ProductsPage.tsx      # Product catalog + create
│   ├── StockTakingPage.tsx   # Stock take sessions
│   ├── StockReportPage.tsx   # Stock report + reconciliation
│   ├── ReportsPage.tsx       # Reports console + XLSX download
│   ├── AnalyticsPage.tsx     # Charts (Recharts)
│   ├── MerchandiseFulfillmentPage.tsx  # Merchandise pipeline
│   ├── MerchendiseTransactionFulfillmentPage.tsx
│   ├── PromotionsPage.tsx    # Promotion CRUD
│   ├── UserManagementPage.tsx # Admin user management
│   └── UnauthorizedPage.tsx
├── services/
│   ├── api.ts                # Axios client + ALL API functions (1523 lines)
│   └── queries/              # React Query hooks
│       ├── transactions.ts   # useTransactions, useTransaction
│       ├── payments.ts       # useCreateManualPayment
│       ├── reports.ts        # useDailyReport, useDailyReconciliationV2
│       ├── analytics.ts      # useAnalyticsOverview, useRevenueAnalytics, etc.
│       └── merchandise.ts    # useMerchandiseCatalog, etc.
├── components/
│   ├── layout/               # AppLayout, Header, Sidebar
│   ├── ui/                   # shadcn/ui (button, card, table, dialog, etc.)
│   ├── transactions/         # AdvancedFilters, StatusDropdown, TransactionDetailModal
│   ├── scanner/              # BarcodeScanner wrapper
│   └── products/             # ProductDetailDialog, CreateProductDialog
│   └── ProtectedRoute.tsx    # Role-based routing guard
├── contexts/
│   ├── AuthContext.tsx        # JWT auth state + login/logout + role checks
│   ├── WebSocketContext.tsx   # WebSocket connection management
│   └── ThemeContext.tsx       # Light/dark theme toggle
├── hooks/
│   └── useWebSocket.ts
├── types/
│   ├── transaction.types.ts   # Transaction, PaginatedResponse, etc.
│   └── product.types.ts
├── config/
│   └── runtimeEndpoints.ts    # API base URL resolution
└── lib/
    ├── query-client.ts        # React Query client config
    └── utils.ts               # cn() utility for Tailwind class merging
```

## Key Patterns

- **Data fetching**: Always use React Query hooks (not raw `useEffect` + `fetch`). Hooks auto-refetch on window focus and handle caching.
- **Forms**: React Hook Form with `useForm` + Zod schemas. Use `Controller` for custom components like `DateTimePicker`.
- **Modals**: Use `Dialog` from shadcn/ui. Pattern: `showDetail` boolean state → `Dialog` open prop → `onOpenChange` reset.
- **Tables**: shadcn/ui `Table` component. Pagination via `Pagination` component at bottom.
- **Filtering**: `AdvancedFilters` component emits `TransactionFilters` object → passed as query params to `useTransactions`.
- **Toasts**: `sonner` library — `toast.success()`, `toast.error()`, `toast.loading()` + `toast.dismiss()`.
- **CSV/XLSX downloads**: API returns `Blob` → `URL.createObjectURL` → trigger download via hidden anchor.

## Anti-patterns

- Don't use Redux or Zustand — Context + React Query is the established pattern.
- Don't access `localStorage` directly for auth tokens — use `AuthContext` methods.
- Don't use raw class names — always use `cn()` utility for conditional classes.
- Don't duplicate API call definitions in page components — add them to `services/api.ts`.
- Don't use `any` types — use the proper types from `types/` or `api.ts` exports.
- Don't forget to invalidate React Query cache after mutations (`queryClient.invalidateQueries({ queryKey: [...] })`).
