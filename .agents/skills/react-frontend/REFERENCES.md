# React Frontend Reference

## File Structure
```
frontend/src/
├── App.tsx              # Router config, provider wrappers
├── main.tsx             # Entry point
├── index.css            # Tailwind v4 imports, CSS theme variables
├── assets/              # Static assets (react.svg)
├── components/
│   ├── layout/          # AppLayout, Header, Sidebar
│   ├── products/        # CreateProductDialog, ProductDetailDialog
│   ├── scanner/         # BarcodeScanner
│   ├── transactions/    # StatusDropdown, StatusChangeDialog,
│   │                    # TransactionDetailModal, AdvancedFilters,
│   │                    # AddToCombinedOrderDialog, EditableStatusCell,
│   │                    # CombinedOrderDetailsView, IssueRegistrationKitDialog
│   ├── ui/              # shadcn/ui components (button, dialog, table, etc.)
│   └── ProtectedRoute.tsx
├── config/
│   └── runtimeEndpoints.ts
├── contexts/            # AuthContext, ThemeContext, WebSocketContext
├── hooks/               # useWebSocket
├── lib/                 # query-client, utils
├── pages/               # 15 page components
├── services/
│   ├── api.ts           # Axios client with JWT interceptors
│   ├── mockData.ts
│   └── queries/         # analytics.ts, merchandise.ts, payments.ts,
│                        # reports.ts, transactions.ts
├── types/               # product.types.ts, transaction.types.ts
└── utils/               # barcodeParser.ts
```

## Route Map
```
/login                  → LoginPage
/                       → TransactionsPage (index)
/transactions           → TransactionsPage
/transactions/:id/scan  → ScanningPage
/transactions/:id/merchandise-fulfill → MerchandiseTransactionFulfillmentPage
/manual-payments        → ManualPaymentsPage
/products               → ProductsPage
/analytics              → AnalyticsPage
/reports                → ReportsPage
/merchandise            → MerchandiseFulfillmentPage
/stock-taking           → StockTakingPage
/stock-report           → StockReportPage
/users                  → UserManagementPage
/promotions             → PromotionsPage
/unauthorized           → UnauthorizedPage
*                       → redirect to /
```

## Theme (Tailwind v4 CSS-based, no tailwind.config.*)
```
Light:  --color-background: 246 242 236 (warm cream)
        --color-primary: 184 112 52 (amber)
        --color-secondary: 19 126 124 (teal)
Dark:   --color-background: 15 17 20
        --color-primary: 227 157 89
Fonts:  --font-display: "Fraunces" (serif)
        --font-body: "Manrope" (sans-serif)
```

## Key Packages
- React 19 / React Router v7 / React Hook Form 7 + Zod 4
- TanStack Query 5 / Axios
- shadcn/ui @ Radix primitives / Tailwind CSS 4 / class-variance-authority
- lucide-react + @phosphor-icons/react
- recharts / html5-qrcode / sonner (toast) / date-fns
