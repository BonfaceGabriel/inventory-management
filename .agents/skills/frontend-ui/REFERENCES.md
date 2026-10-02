# Frontend UI Reference

## Design Tokens (from index.css)

### Color Palette
| Token | Light | Dark |
|---|---|---|
| `--background` | 246 242 236 (warm cream) | 15 17 20 (near black) |
| `--foreground` | 24 23 22 | 238 232 223 |
| `--card` | 255 252 248 | 24 27 33 |
| `--primary` | 184 112 52 (amber/gold) | 227 157 89 |
| `--secondary` | 19 126 124 (teal) | 83 188 182 |
| `--muted` | 237 229 219 | 40 43 50 |
| `--accent` | 255 242 225 | 60 42 30 |
| `--destructive` | 191 58 58 | 233 105 97 |
| `--border` | 214 194 169 | 64 55 47 |

### Typography
- `--font-display: "Fraunces", serif` (headings, display text)
- `--font-body: "Manrope", sans-serif` (body, UI text)

## Component Library (shadcn/ui)
Components in `components/ui/`: alert-dialog, alert, badge, button, card, checkbox, date-range-picker, dialog, dropdown-menu, input, label, pagination, select (radix + native), skeleton, table, tabs, textarea, theme-toggle

## Layout Components
- `AppLayout` — sidebar + header + main content area
- `Sidebar` — navigation with role-based items
- `Header` — user menu, location selector, theme toggle

## Icon Libraries
- `lucide-react` (primary)
- `@phosphor-icons/react` (secondary)

## Context Providers
- `ThemeContext` — light/dark toggle, persisted
- `AuthContext` — user, tokens, login/logout
- `WebSocketContext` — real-time transaction updates

## Toast Notifications
- `sonner` library (imported as `toast`)

## Key Patterns
- CSV downloads: construct CSV text, trigger via `URL.createObjectURL` + hidden `<a>` click
- XLSX downloads: fetch blob from API, trigger download
- Barcode scanning: `html5-qrcode` library in `BarcodeScanner` component
- Date picking: `date-fns` + custom date-range-picker shadcn component
