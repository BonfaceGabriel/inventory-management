from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import PaymentGateway, Device, RawMessage, Transaction, ManualPayment


@admin.register(PaymentGateway)
class PaymentGatewayAdmin(admin.ModelAdmin):
    """Admin interface for Payment Gateway configuration"""
    list_display = [
        'name', 'gateway_type_display', 'gateway_number',
        'settlement_badge', 'transaction_count', 'is_active'
    ]
    list_filter = ['gateway_type', 'settlement_type', 'requires_parent_settlement', 'is_active']
    search_fields = ['name', 'gateway_number', 'description']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Gateway Information', {
            'fields': ('name', 'gateway_type', 'gateway_number', 'description')
        }),
        ('Settlement Configuration', {
            'fields': (
                'requires_parent_settlement',
                'settlement_type',
                'settlement_percentage'
            ),
            'description': 'Configure how payments are split with parent company'
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def gateway_type_display(self, obj):
        """Display gateway type with badge"""
        colors = {
            'MPESA_TILL': '#10B981',      # Green
            'MPESA_PAYBILL': '#3B82F6',   # Blue
            'PDQ': '#8B5CF6',              # Purple
            'BANK_TRANSFER': '#F59E0B',    # Amber
            'CASH': '#EF4444',             # Red
            'OTHER': '#6B7280',            # Gray
        }
        color = colors.get(obj.gateway_type, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_gateway_type_display()
        )
    gateway_type_display.short_description = 'Type'
    gateway_type_display.admin_order_field = 'gateway_type'

    def settlement_badge(self, obj):
        """Display settlement type with indicator"""
        if not obj.requires_parent_settlement:
            return format_html('<span style="color: green;">✓ 100% to Shop</span>')

        colors = {
            'PARENT_TAKES_ALL': '#EF4444',   # Red
            'COST_MARKUP': '#F59E0B',        # Amber
            'PERCENTAGE': '#3B82F6',         # Blue
            'CUSTOM': '#8B5CF6',             # Purple
        }
        color = colors.get(obj.settlement_type, '#6B7280')

        label = obj.get_settlement_type_display()
        if obj.settlement_type == 'PERCENTAGE' and obj.settlement_percentage:
            label += f' ({obj.settlement_percentage}%)'

        return format_html(
            '<span style="color: {};">⚖️ {}</span>',
            color,
            label
        )
    settlement_badge.short_description = 'Settlement'

    def transaction_count(self, obj):
        """Display count of transactions for this gateway"""
        count = obj.transactions.count()
        if count > 0:
            url = reverse('admin:payments_transaction_changelist') + f'?gateway__id__exact={obj.id}'
            return format_html('<a href="{}">{} transactions</a>', url, count)
        return '0 transactions'
    transaction_count.short_description = 'Transactions'


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Admin interface for Device model"""
    list_display = [
        'name', 'phone_number', 'default_gateway', 'gateway_number',
        'message_count', 'created_at', 'last_seen_at'
    ]
    list_filter = ['default_gateway', 'created_at']
    search_fields = ['name', 'phone_number', 'gateway_number']
    readonly_fields = ['id', 'api_key', 'created_at', 'last_seen_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'name', 'phone_number')
        }),
        ('Gateway Configuration', {
            'fields': ('default_gateway', 'gateway_number')
        }),
        ('Security', {
            'fields': ('api_key',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_seen_at'),
            'classes': ('collapse',)
        }),
    )

    def message_count(self, obj):
        """Display count of messages from this device"""
        count = obj.messages.count()
        url = reverse('admin:payments_rawmessage_changelist') + f'?device__id__exact={obj.id}'
        return format_html('<a href="{}">{} messages</a>', url, count)
    message_count.short_description = 'Messages'


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    """Admin interface for RawMessage model"""
    list_display = [
        'id', 'device_link', 'raw_text_preview', 'received_at',
        'processed_status', 'transaction_link', 'created_at'
    ]
    list_filter = ['processed', 'device', 'received_at', 'created_at']
    search_fields = ['raw_text', 'device__name']
    readonly_fields = ['id', 'created_at', 'device', 'transaction']
    date_hierarchy = 'received_at'

    fieldsets = (
        ('Message Information', {
            'fields': ('id', 'device', 'raw_text', 'received_at')
        }),
        ('Processing', {
            'fields': ('processed', 'transaction')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def device_link(self, obj):
        """Link to device"""
        url = reverse('admin:payments_device_change', args=[obj.device.id])
        return format_html('<a href="{}">{}</a>', url, obj.device.name)
    device_link.short_description = 'Device'

    def raw_text_preview(self, obj):
        """Show preview of raw text"""
        if len(obj.raw_text) > 50:
            return obj.raw_text[:50] + '...'
        return obj.raw_text
    raw_text_preview.short_description = 'Message Preview'

    def processed_status(self, obj):
        """Show processed status with color"""
        if obj.processed:
            return format_html(
                '<span style="color: green;">✓ Processed</span>'
            )
        return format_html(
            '<span style="color: orange;">⏳ Pending</span>'
        )
    processed_status.short_description = 'Status'

    def transaction_link(self, obj):
        """Link to transaction if exists"""
        if obj.transaction:
            url = reverse('admin:payments_transaction_change', args=[obj.transaction.id])
            return format_html('<a href="{}">{}</a>', url, obj.transaction.tx_id)
        return '-'
    transaction_link.short_description = 'Transaction'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin interface for Transaction model"""
    list_display = [
        'tx_id', 'sender_name', 'amount_display', 'status_badge',
        'remaining_display', 'lock_status', 'gateway_type',
        'timestamp', 'confidence_display'
    ]
    list_filter = [
        'status', 'gateway_type', 'timestamp', 'created_at'
    ]
    search_fields = [
        'tx_id', 'sender_name', 'sender_phone', 'notes'
    ]
    readonly_fields = [
        'id', 'tx_id', 'amount', 'unique_hash', 'duplicate_of',
        'remaining_amount', 'is_locked', 'status_display',
        'created_at', 'updated_at'
    ]
    date_hierarchy = 'timestamp'

    fieldsets = (
        ('Transaction Details', {
            'fields': (
                'id', 'tx_id', 'amount', 'sender_name', 'sender_phone',
                'timestamp', 'gateway_type', 'destination_number', 'confidence'
            )
        }),
        ('Payment Tracking', {
            'fields': (
                'amount_expected', 'amount_paid', 'remaining_amount',
                'status', 'status_display', 'is_locked'
            )
        }),
        ('Notes & References', {
            'fields': ('notes',)
        }),
        ('Deduplication', {
            'fields': ('unique_hash', 'duplicate_of'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_processing', 'cancel_selected_transactions']

    def amount_display(self, obj):
        """Display amount with currency"""
        return f'KES {obj.amount:,.2f}'
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'

    def status_badge(self, obj):
        """Display status with color badge"""
        status_info = obj.status_display
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">'
            '{} {}</span>',
            status_info['color'],
            status_info['icon'],
            status_info['label']
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    def remaining_display(self, obj):
        """Display remaining amount"""
        remaining = obj.remaining_amount
        if remaining > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">KES {:.2f}</span>',
                remaining
            )
        return format_html('<span style="color: gray;">-</span>')
    remaining_display.short_description = 'Remaining'

    def lock_status(self, obj):
        """Display lock status"""
        if obj.is_locked:
            return format_html(
                '<span style="color: red;" title="Locked - Cannot be modified">🔒 Locked</span>'
            )
        return format_html(
            '<span style="color: green;" title="Unlocked - Can be modified">🔓 Unlocked</span>'
        )
    lock_status.short_description = 'Lock'

    def confidence_display(self, obj):
        """Display confidence as percentage"""
        percentage = obj.confidence * 100
        if percentage >= 90:
            color = 'green'
        elif percentage >= 70:
            color = 'orange'
        else:
            color = 'red'
        return format_html(
            '<span style="color: {};">{:.0f}%</span>',
            color, percentage
        )
    confidence_display.short_description = 'Confidence'
    confidence_display.admin_order_field = 'confidence'

    def mark_as_processing(self, request, queryset):
        """Action to mark selected transactions as PROCESSING"""
        from payments.services import OrderStatusService
        service = OrderStatusService()

        count = 0
        for transaction in queryset:
            try:
                if not transaction.is_locked:
                    service.mark_as_processing(transaction, notes="Marked as PROCESSING via admin")
                    count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error processing {transaction.tx_id}: {str(e)}",
                    level='ERROR'
                )

        self.message_user(
            request,
            f"{count} transaction(s) marked as PROCESSING",
            level='SUCCESS'
        )
    mark_as_processing.short_description = "Mark as PROCESSING"

    def cancel_selected_transactions(self, request, queryset):
        """Action to cancel selected transactions"""
        from payments.services import OrderStatusService
        service = OrderStatusService()

        count = 0
        for transaction in queryset:
            try:
                if not transaction.is_locked:
                    service.cancel_transaction(
                        transaction,
                        reason="Cancelled via admin interface"
                    )
                    count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error cancelling {transaction.tx_id}: {str(e)}",
                    level='ERROR'
                )

        self.message_user(
            request,
            f"{count} transaction(s) cancelled",
            level='WARNING'
        )
    cancel_selected_transactions.short_description = "Cancel selected transactions"


@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    """Admin interface for ManualPayment model"""
    list_display = [
        'id_display', 'payer_name', 'payment_method_badge',
        'amount_display', 'reference_number', 'payment_date',
        'created_by', 'transaction_link'
    ]
    list_filter = [
        'payment_method', 'created_by', 'payment_date', 'created_at'
    ]
    search_fields = [
        'payer_name', 'payer_phone', 'payer_email',
        'reference_number', 'notes', 'created_by'
    ]
    readonly_fields = [
        'id', 'transaction', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'payment_date'

    fieldsets = (
        ('Payment Information', {
            'fields': (
                'id', 'transaction', 'payment_method', 'amount', 'payment_date'
            )
        }),
        ('Payer Details', {
            'fields': (
                'payer_name', 'payer_phone', 'payer_email'
            )
        }),
        ('Reference & Notes', {
            'fields': ('reference_number', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def id_display(self, obj):
        """Display shortened UUID"""
        return str(obj.id)[:8]
    id_display.short_description = 'ID'

    def payment_method_badge(self, obj):
        """Display payment method with badge"""
        colors = {
            'PDQ': '#3B82F6',         # Blue
            'BANK_TRANSFER': '#10B981',  # Green
            'CASH': '#F59E0B',        # Amber
            'CHEQUE': '#8B5CF6',      # Purple
            'OTHER': '#6B7280',       # Gray
        }
        color = colors.get(obj.payment_method, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_payment_method_display()
        )
    payment_method_badge.short_description = 'Method'
    payment_method_badge.admin_order_field = 'payment_method'

    def amount_display(self, obj):
        """Display amount with currency"""
        return f'KES {obj.amount:,.2f}'
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'

    def transaction_link(self, obj):
        """Link to associated transaction"""
        url = reverse('admin:payments_transaction_change', args=[obj.transaction.id])
        return format_html('<a href="{}">{}</a>', url, obj.transaction.tx_id)
    transaction_link.short_description = 'Transaction'


# Customize admin site headers
admin.site.site_header = "Payment Management System Admin"
admin.site.site_title = "Payment Admin"
admin.site.index_title = "Payment Management Dashboard"
