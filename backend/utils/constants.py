"""
Constants used throughout the application.
"""

# Transaction Status Colors
# Using Tailwind CSS color palette for consistency
STATUS_COLORS = {
    'NOT_PROCESSED': '#EF4444',      # Red-500 - Urgent, needs attention
    'PROCESSING': '#3B82F6',         # Blue-500 - In progress
    'PARTIALLY_FULFILLED': '#8B5CF6',# Purple-500 - Partial, still available
    'FULFILLED': '#10B981',          # Green-500 - Complete, locked
    'CANCELLED': '#6B7280',          # Gray-500 - Cancelled, locked
}

# Status Display Names
STATUS_LABELS = {
    'NOT_PROCESSED': 'Not Processed',
    'PROCESSING': 'Processing',
    'PARTIALLY_FULFILLED': 'Partially Fulfilled',
    'FULFILLED': 'Fulfilled',
    'CANCELLED': 'Cancelled',
}

# Status Icons (optional, for frontend use)
STATUS_ICONS = {
    'NOT_PROCESSED': '⚠️',
    'PROCESSING': '⏳',
    'PARTIALLY_FULFILLED': '📊',
    'FULFILLED': '✅',
    'CANCELLED': '❌',
}
