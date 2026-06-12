from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import (
    Location,
    Device,
    RawMessage,
    Transaction,
    ManualPayment,
    Product,
    ProductLine,
    TransactionLineItem,
    InventoryMovement,
    CombinedOrder,
    CombinedOrderTransaction,
    CombinedOrderLineItem,
    StockTakeSession,
    StockTakeItem,
    DailyStockReconciliation,
    EndOfDayValueReconciliation,
    StockAdjustmentItem,
    Promotion,
    PromotionProduct,
    MerchandiseCatalogItem,
    MerchandiseCatalogOption,
    MerchandiseOrder,
    MerchandiseOrderLine,
    MerchandiseStock,
    MerchandiseStockMovement,
)

User = get_user_model()


# ============================================================================
# Location Serializers
# ============================================================================


class LocationSerializer(serializers.ModelSerializer):
    location_type_display = serializers.CharField(
        source="get_location_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_main = serializers.BooleanField(read_only=True)

    class Meta:
        model = Location
        fields = [
            "id",
            "name",
            "location_type",
            "location_type_display",
            "status",
            "status_display",
            "is_main",
            "notes",
            "created_at",
            "closed_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "closed_at",
            "is_main",
            "location_type_display",
            "status_display",
        ]


# ============================================================================
# Authentication & User Serializers
# ============================================================================


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token serializer that includes user role and info in the token.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims to the token
        token["username"] = user.username
        token["email"] = user.email
        token["role"] = user.role
        token["first_name"] = user.first_name
        token["last_name"] = user.last_name

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # Add user info to the response (not just the token)
        data["user"] = {
            "id": self.user.id,
            "username": self.user.username,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "role": self.user.role,
            "role_display": self.user.get_role_display(),
            "is_admin": self.user.is_admin(),
            "is_processor": self.user.is_processor(),
            "is_issuer": self.user.is_issuer(),
        }

        return data


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for user profile and listing.
    """

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    is_processor = serializers.BooleanField(read_only=True)
    is_issuer = serializers.BooleanField(read_only=True)
    has_processor_access = serializers.BooleanField(read_only=True)
    has_issuer_access = serializers.BooleanField(read_only=True)
    current_location = LocationSerializer(read_only=True)
    current_location_id = serializers.PrimaryKeyRelatedField(
        source="current_location",
        queryset=Location.objects.filter(status="ACTIVE"),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_display",
            "is_active",
            "date_joined",
            "last_login",
            "is_admin",
            "is_processor",
            "is_issuer",
            "has_processor_access",
            "has_issuer_access",
            "current_location",
            "current_location_id",
        ]
        read_only_fields = [
            "id",
            "date_joined",
            "last_login",
            "role_display",
            "is_admin",
            "is_processor",
            "is_issuer",
            "has_processor_access",
            "has_issuer_access",
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new users (Admin only).
    """

    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "password_confirm",
            "role",
            "is_active",
        ]

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords don't match."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        user = User.objects.create_user(**validated_data)
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user details (Admin only).
    Does not allow password change through this serializer.
    """

    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_display",
            "is_active",
        ]
        read_only_fields = ["id", "username", "role_display"]


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for password change endpoint.
    """

    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "New passwords don't match."}
            )
        return attrs

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class AdminPasswordResetSerializer(serializers.Serializer):
    """
    Serializer for admin to reset user password.
    """

    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords don't match."}
            )
        return attrs


class DeviceRegisterSerializer(serializers.ModelSerializer):
    gateway_id = serializers.IntegerField(required=True, write_only=True)

    class Meta:
        model = Device
        fields = [
            "name",
            "phone_number",
            "gateway_id",
            "default_gateway",
            "gateway_number",
        ]


class DeviceResponseSerializer(serializers.ModelSerializer):
    gateway_name = serializers.CharField(
        source="gateway.name", read_only=True, allow_null=True
    )
    gateway_type = serializers.CharField(
        source="gateway.gateway_type", read_only=True, allow_null=True
    )
    gateway_type_display = serializers.CharField(
        source="gateway.get_gateway_type_display", read_only=True, allow_null=True
    )

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "phone_number",
            "gateway",
            "gateway_name",
            "gateway_type",
            "gateway_type_display",
            "default_gateway",
            "gateway_number",
            "api_key",
        ]
        read_only_fields = [
            "id",
            "api_key",
            "gateway_name",
            "gateway_type",
            "gateway_type_display",
        ]


class RawMessageSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)

    class Meta:
        model = RawMessage
        fields = ["device", "device_name", "raw_text", "received_at"]
        read_only_fields = ["device", "device_name"]


class ManualPaymentSerializer(serializers.ModelSerializer):
    """Serializer for manual payment entries"""

    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )

    class Meta:
        model = ManualPayment
        fields = [
            "id",
            "transaction",
            "payment_method",
            "payment_method_display",
            "reference_number",
            "payer_name",
            "payer_phone",
            "payer_email",
            "amount",
            "payment_date",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "payment_method_display"]


class ManualPaymentCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a manual payment entry.

    This creates both a Transaction and ManualPayment record.
    """

    payment_method = serializers.ChoiceField(
        choices=ManualPayment.PaymentMethod.choices
    )
    reference_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    payer_name = serializers.CharField(max_length=255)
    payer_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    payer_email = serializers.EmailField(required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_date = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True)
    created_by = serializers.CharField(max_length=255)

    def validate_amount(self, value):
        """Ensure amount is positive"""
        from decimal import Decimal

        if value <= Decimal("0.00"):
            raise serializers.ValidationError("Amount must be greater than zero")
        return value

    def validate(self, data):
        """Cross-field validation"""
        # Reference number is now optional for all payment methods
        # Transaction ID is auto-generated, so no validation needed
        return data


class TransactionSerializer(serializers.ModelSerializer):
    raw_messages = serializers.SerializerMethodField()
    manual_payments = ManualPaymentSerializer(many=True, read_only=True)
    line_items = serializers.SerializerMethodField()
    remaining_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    is_locked = serializers.BooleanField(read_only=True)
    is_time_locked = serializers.BooleanField(read_only=True)
    locked_at = serializers.DateTimeField(read_only=True)
    locked_by = serializers.CharField(read_only=True)
    status_display = serializers.ReadOnlyField()
    gateway_name = serializers.CharField(
        source="gateway.name", read_only=True, allow_null=True
    )
    gateway_type = serializers.SerializerMethodField()
    is_in_combined_order = serializers.SerializerMethodField()
    combined_order_info = serializers.SerializerMethodField()
    activity_log = serializers.SerializerMethodField()

    def get_gateway_type(self, obj):
        """
        Return gateway type for display.
        Shows 'MERCH' for merchandise gateways, otherwise returns the actual gateway type.
        """
        from payments.services.merchandise_service import MerchandiseService

        if obj.gateway and MerchandiseService.is_merchandise_gateway(obj.gateway):
            return "MERCH"
        return obj.gateway.gateway_type if obj.gateway else None

    # User tracking fields
    processed_by_username = serializers.CharField(
        source="processed_by.username", read_only=True, allow_null=True
    )
    activated_by_username = serializers.CharField(
        source="activated_by.username", read_only=True, allow_null=True
    )
    completed_by_username = serializers.CharField(
        source="completed_by.username", read_only=True, allow_null=True
    )
    cancelled_by_username = serializers.CharField(
        source="cancelled_by.username", read_only=True, allow_null=True
    )

    def get_raw_messages(self, obj):
        """Return unique raw messages (deduplicated by raw_text)"""
        messages = obj.raw_messages.all()
        seen_texts = set()
        unique_messages = []

        for message in messages:
            if message.raw_text not in seen_texts:
                seen_texts.add(message.raw_text)
                unique_messages.append(message)

        return RawMessageSerializer(unique_messages, many=True).data

    def get_line_items(self, obj):
        """Return fulfilled line items for this transaction.

        If this transaction is the parent of a combined order, return the
        combined order's line items instead (since that's where they're stored).
        """
        # Check if this transaction is a parent of a combined order
        if hasattr(obj, "combined_order_parent"):
            try:
                combined_order = obj.combined_order_parent
                # Return combined order line items
                return [
                    {
                        "id": item.id,
                        "product_code": item.scanned_prod_code,
                        "product_name": item.scanned_prod_name,
                        "sku": item.scanned_sku,
                        "quantity": item.quantity,
                        "unit_price": str(item.scanned_price),
                        "line_total": str(item.line_total),
                        "scanned_at": item.scanned_at,
                        "scanned_by": item.scanned_by,
                        "is_inventory_deducted": item.is_inventory_deducted,
                        "copied_from_tx_id": item.copied_from_transaction.tx_id
                        if item.copied_from_transaction
                        else None,
                    }
                    for item in combined_order.line_items.all()
                ]
            except Exception:
                pass

        # Regular transaction - return its own line items
        line_items = obj.line_items.all()
        return [
            {
                "id": item.id,
                "product_code": item.scanned_prod_code,
                "product_name": item.scanned_prod_name,
                "sku": item.scanned_sku,
                "quantity": item.quantity,
                "unit_price": str(item.scanned_price),
                "line_total": str(item.line_total),
                "scanned_at": item.scanned_at,
                "scanned_by": item.scanned_by,
            }
            for item in line_items
        ]

    def get_is_in_combined_order(self, obj):
        """Check if this transaction is part of a combined order"""
        return obj.combined_orders.exists()

    def get_combined_order_info(self, obj):
        """Return combined order details if transaction is part of one OR if this transaction IS the parent"""
        # First check if this transaction is a child in a combined order
        combined_order_link = obj.combined_orders.first()
        if combined_order_link:
            order = combined_order_link.combined_order
            return {
                "combined_order_id": order.combined_order_id,
                "parent_transaction_id": order.parent_transaction.id
                if order.parent_transaction
                else None,
                "status": order.status,
                "total_amount": str(order.total_amount),
                "amount_fulfilled": str(order.amount_fulfilled),
                "remaining_amount": str(order.remaining_amount),
                "transaction_count": order.transaction_count,
                "created_at": order.created_at,
                "created_by": order.created_by,
            }

        # Also check if this transaction IS the parent of a combined order
        # (The reverse relationship from CombinedOrder.parent_transaction)
        if hasattr(obj, "combined_order_parent"):
            order = obj.combined_order_parent
            return {
                "combined_order_id": order.combined_order_id,
                "parent_transaction_id": obj.id,  # This transaction is the parent
                "status": order.status,
                "total_amount": str(order.total_amount),
                "amount_fulfilled": str(order.amount_fulfilled),
                "remaining_amount": str(order.remaining_amount),
                "transaction_count": order.transaction_count,
                "created_at": order.created_at,
                "created_by": order.created_by,
            }

        return None

    def get_activity_log(self, obj):
        """Generate structured activity log from transaction lifecycle events"""
        activities = []

        # 1. Transaction created (SMS or Manual)
        if obj.manual_payments.exists():
            manual_payment = obj.manual_payments.first()
            # Use created_by_user (ForeignKey) if available, fall back to created_by (legacy string)
            user_display = (
                manual_payment.created_by_user.username
                if manual_payment.created_by_user
                else manual_payment.created_by
            )
            role_display = (
                manual_payment.created_by_user.get_role_display()
                if manual_payment.created_by_user
                else "Processor"
            )
            activities.append(
                {
                    "action": "Manual Payment Created",
                    "timestamp": obj.created_at,
                    "user": user_display,
                    "role": role_display,
                    "details": f"{manual_payment.get_payment_method_display()} payment - {manual_payment.payer_name}",
                }
            )
        else:
            activities.append(
                {
                    "action": "Transaction Created from SMS",
                    "timestamp": obj.created_at,
                    "user": "System",
                    "role": "SMS Parser",
                    "details": f"M-Pesa payment from {obj.sender_name}",
                }
            )

        # 2. Marked for processing
        if obj.processed_by and obj.processed_at:
            activities.append(
                {
                    "action": "Marked for Processing",
                    "timestamp": obj.processed_at,
                    "user": obj.processed_by.username,
                    "role": obj.processed_by.get_role_display(),
                    "details": "Transaction prepared for fulfillment",
                }
            )

        # 3. Activated for issuance (ONLY admin/issuer can do this)
        if obj.activated_by and obj.activated_at:
            activities.append(
                {
                    "action": "Activated for Issuance",
                    "timestamp": obj.activated_at,
                    "user": obj.activated_by.username,
                    "role": obj.activated_by.get_role_display(),
                    "details": "Transaction activated for product scanning",
                }
            )

        # 4. Order fulfilled/Kit issued
        if obj.completed_by and obj.completed_at:
            action = (
                "Registration Kit Issued" if obj.is_registration else "Order Fulfilled"
            )
            details = f"Amount: {obj.amount_fulfilled} KES"
            if obj.status == "PARTIALLY_FULFILLED":
                action = "Partially Fulfilled"
                details = f"Fulfilled: {obj.amount_fulfilled} KES / Expected: {obj.amount_expected} KES"

            activities.append(
                {
                    "action": action,
                    "timestamp": obj.completed_at,
                    "user": obj.completed_by.username,
                    "role": obj.completed_by.get_role_display(),
                    "details": details,
                }
            )

        # 5. Cancelled
        if obj.cancelled_by and obj.cancelled_at:
            activities.append(
                {
                    "action": "Transaction Cancelled",
                    "timestamp": obj.cancelled_at,
                    "user": obj.cancelled_by.username,
                    "role": obj.cancelled_by.get_role_display(),
                    "details": "Transaction cancelled",
                }
            )

        # 6. Time-locked (system/admin)
        if obj.is_time_locked and obj.locked_at and obj.locked_by:
            activities.append(
                {
                    "action": "Time-Locked",
                    "timestamp": obj.locked_at,
                    "user": obj.locked_by,
                    "role": "System" if obj.locked_by == "System" else "Admin",
                    "details": "End-of-day lock applied - transaction is now read-only",
                }
            )

        # Sort by timestamp (earliest first)
        activities.sort(key=lambda x: x["timestamp"])

        return activities

    class Meta:
        model = Transaction
        fields = [
            "id",
            "tx_id",
            "amount",
            "sender_name",
            "sender_phone",
            "timestamp",
            "status",
            "status_display",
            "amount_expected",
            "amount_paid",
            "amount_fulfilled",
            "remaining_amount",
            "is_locked",
            "is_time_locked",
            "locked_at",
            "locked_by",
            "notes",
            "raw_messages",
            "manual_payments",
            "line_items",
            "gateway_type",
            "gateway_name",
            "destination_number",
            "confidence",
            "is_in_combined_order",
            "combined_order_info",
            "activity_log",
            "processed_by_username",
            "activated_by_username",
            "completed_by_username",
            "cancelled_by_username",
            "is_registration",
            "registration_kit_issued",
            "registration_kit_quantity",
            "registration_kit_amount_deducted",
            "total_pv",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tx_id",
            "amount",
            "created_at",
            "updated_at",
            "remaining_amount",
            "is_locked",
            "is_time_locked",
            "locked_at",
            "locked_by",
            "status_display",
            "gateway_name",
            "line_items",
            "amount_fulfilled",
        ]


# ============================================================================
# Merchandise Serializers
# ============================================================================


class MerchandiseCatalogOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchandiseCatalogOption
        fields = ["option_type", "value"]


class MerchandiseCatalogItemSerializer(serializers.ModelSerializer):
    options = MerchandiseCatalogOptionSerializer(many=True, read_only=True)

    class Meta:
        model = MerchandiseCatalogItem
        fields = [
            "id",
            "code",
            "name",
            "item_type",
            "unit_price",
            "is_active",
            "options",
        ]


class MerchandiseCatalogItemOptionInputSerializer(serializers.Serializer):
    option_type = serializers.ChoiceField(choices=MerchandiseCatalogOption.OptionType.choices)
    value = serializers.CharField(max_length=50)


class MerchandiseCatalogItemCreateSerializer(serializers.ModelSerializer):
    options = MerchandiseCatalogItemOptionInputSerializer(many=True, required=False, default=[])

    class Meta:
        model = MerchandiseCatalogItem
        fields = ["code", "name", "item_type", "unit_price", "is_active", "options"]

    def create(self, validated_data):
        options_data = validated_data.pop("options", [])
        item = MerchandiseCatalogItem.objects.create(**validated_data)
        for opt in options_data:
            MerchandiseCatalogOption.objects.create(item=item, **opt)
        return item

    def update(self, instance, validated_data):
        options_data = validated_data.pop("options", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if options_data is not None:
            instance.options.all().delete()
            for opt in options_data:
                MerchandiseCatalogOption.objects.create(item=instance, **opt)
        return instance


class MerchandiseOrderLineSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_type = serializers.CharField(source="item.item_type", read_only=True)

    class Meta:
        model = MerchandiseOrderLine
        fields = [
            "id",
            "item_code",
            "item_name",
            "item_type",
            "quantity",
            "unit_price_snapshot",
            "color",
            "size",
            "line_total",
            "created_at",
        ]


class MerchandiseOrderSerializer(serializers.ModelSerializer):
    transaction_id = serializers.CharField(source="transaction.tx_id", read_only=True)
    amount = serializers.DecimalField(
        source="transaction.amount", max_digits=10, decimal_places=2, read_only=True
    )
    sender_name = serializers.CharField(
        source="transaction.sender_name", read_only=True
    )
    sender_phone = serializers.CharField(
        source="transaction.sender_phone", read_only=True
    )
    transaction_timestamp = serializers.DateTimeField(
        source="transaction.timestamp", read_only=True
    )
    gateway_name = serializers.CharField(source="gateway.name", read_only=True)
    fulfilled_by_username = serializers.CharField(
        source="fulfilled_by.username", read_only=True, allow_null=True
    )
    lines = MerchandiseOrderLineSerializer(many=True, read_only=True)

    class Meta:
        model = MerchandiseOrder
        fields = [
            "id",
            "status",
            "notes",
            "transaction_id",
            "amount",
            "sender_name",
            "sender_phone",
            "transaction_timestamp",
            "gateway_name",
            "fulfilled_by_username",
            "fulfilled_at",
            "lines",
            "created_at",
            "updated_at",
        ]


class MerchandiseFulfillLineInputSerializer(serializers.Serializer):
    item_code = serializers.CharField(max_length=50)
    quantity = serializers.IntegerField(min_value=1)
    color = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    size = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )


class MerchandiseFulfillRequestSerializer(serializers.Serializer):
    lines = MerchandiseFulfillLineInputSerializer(many=True, allow_empty=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class MerchandiseStockSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_type = serializers.CharField(source="item.item_type", read_only=True)
    unit_price = serializers.DecimalField(
        source="item.unit_price", max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = MerchandiseStock
        fields = [
            "id",
            "item_code",
            "item_name",
            "item_type",
            "color",
            "size",
            "quantity",
            "unit_price",
            "updated_at",
        ]


class MerchandiseStockAdjustmentInputSerializer(serializers.Serializer):
    item_code = serializers.CharField(max_length=50)
    quantity_change = serializers.IntegerField()
    color = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    size = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )


class MerchandiseStockAdjustRequestSerializer(serializers.Serializer):
    adjustments = MerchandiseStockAdjustmentInputSerializer(
        many=True, allow_empty=False
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class MerchandiseStockMovementSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="stock.item.code", read_only=True)
    item_name = serializers.CharField(source="stock.item.name", read_only=True)
    color = serializers.CharField(source="stock.color", read_only=True, allow_null=True)
    size = serializers.CharField(source="stock.size", read_only=True, allow_null=True)
    performed_by_username = serializers.CharField(
        source="performed_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = MerchandiseStockMovement
        fields = [
            "id",
            "movement_type",
            "item_code",
            "item_name",
            "color",
            "size",
            "quantity_change",
            "quantity_before",
            "quantity_after",
            "reference",
            "notes",
            "performed_by_username",
            "created_at",
        ]


# ============================================================================
# Product & Inventory Serializers
# ============================================================================


class ProductLineSerializer(serializers.ModelSerializer):
    """Serializer for product lines."""

    subline_count = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductLine
        fields = [
            "id",
            "name",
            "description",
            "parent_line",
            "subline_count",
            "product_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_subline_count(self, obj):
        """Return count of sub-lines."""
        return obj.sublines.count()

    def get_product_count(self, obj):
        """Return count of products in this product line."""
        return obj.products.count()


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for products with inventory details."""

    product_line_name = serializers.CharField(
        source="product_line.name", read_only=True, allow_null=True
    )
    stock_status = serializers.SerializerMethodField()
    sku_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "prod_code",
            "prod_name",
            "sku",
            "sku_name",
            "barcode",
            "current_price",
            "cost_price",
            "current_pv",
            "quantity",
            "reorder_level",
            "stock_status",
            "product_line",
            "product_line_name",
            "description",
            "image_url",
            "image",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "product_line_name"]

    def get_stock_status(self, obj):
        """Return stock status based on quantity and reorder level."""
        if obj.quantity <= 0:
            return "OUT_OF_STOCK"
        elif obj.quantity <= obj.reorder_level:
            return "LOW_STOCK"
        else:
            return "IN_STOCK"

    def validate(self, attrs):
        """sku_name is required on the model; default from prod_name when omitted."""
        sku_name = (attrs.get("sku_name") or "").strip()
        if not sku_name:
            prod_name = (attrs.get("prod_name") or "").strip()
            if not prod_name and self.instance is not None:
                prod_name = (self.instance.prod_name or "").strip()
            attrs["sku_name"] = prod_name or "Unit"
        else:
            attrs["sku_name"] = sku_name
        return attrs

    def update(self, instance, validated_data):
        """Override update to track inventory movements when quantity changes."""
        from .models import InventoryMovement

        old_quantity = instance.quantity
        new_quantity = validated_data.get("quantity", old_quantity)

        # Update the product
        instance = super().update(instance, validated_data)

        # Create inventory movement if quantity changed
        if old_quantity != new_quantity:
            quantity_change = new_quantity - old_quantity

            # Determine movement type and reference based on change
            if quantity_change > 0:
                reference = f"Manual adjustment: +{quantity_change}"
            else:
                reference = f"Manual adjustment: {quantity_change}"

            # Get the user who made the change (if available from context)
            user = (
                self.context.get("request").user
                if self.context.get("request")
                else None
            )

            InventoryMovement.objects.create(
                product=instance,
                movement_type="ADJUSTMENT",
                quantity_before=old_quantity,
                quantity_after=new_quantity,
                quantity_change=quantity_change,
                reference=reference,
                performed_by_user=user if hasattr(user, "role") else None,
            )

        return instance


class ProductListSerializer(serializers.ModelSerializer):
    """Minimal serializer for product list views (faster)."""

    product_line_name = serializers.CharField(
        source="product_line.name", read_only=True, allow_null=True
    )
    stock_status = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "prod_code",
            "prod_name",
            "sku",
            "sku_name",
            "barcode",
            "current_price",
            "cost_price",
            "current_pv",
            "quantity",
            "reorder_level",
            "stock_status",
            "product_line",
            "product_line_name",
            "description",
            "image_url",
            "image",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "product_line_name",
            "stock_status",
        ]

    def get_stock_status(self, obj):
        """Return stock status based on quantity and reorder level."""
        if obj.quantity <= 0:
            return "OUT_OF_STOCK"
        elif obj.quantity <= obj.reorder_level:
            return "LOW_STOCK"
        else:
            return "IN_STOCK"


class TransactionLineItemSerializer(serializers.ModelSerializer):
    """Serializer for transaction line items."""

    product_name = serializers.CharField(source="product.prod_name", read_only=True)

    class Meta:
        model = TransactionLineItem
        fields = [
            "id",
            "transaction",
            "product",
            "product_name",
            "scanned_prod_code",
            "scanned_prod_name",
            "scanned_sku",
            "scanned_sku_name",
            "scanned_price",
            "scanned_pv",
            "quantity",
            "line_total",
            "line_cost",
            "line_pv",
            "scanned_at",
            "scanned_by",
            "is_inventory_deducted",  # Whether inventory was already deducted for this item
        ]
        read_only_fields = [
            "id",
            "line_total",
            "line_cost",
            "line_pv",
            "scanned_at",
            "product_name",
            "is_inventory_deducted",
        ]


class InventoryMovementSerializer(serializers.ModelSerializer):
    """Serializer for inventory movements (audit trail)."""

    movement_type_display = serializers.CharField(
        source="get_movement_type_display", read_only=True
    )
    product_name = serializers.CharField(source="product.prod_name", read_only=True)
    product_code = serializers.CharField(source="product.prod_code", read_only=True)

    class Meta:
        model = InventoryMovement
        fields = [
            "id",
            "movement_type",
            "movement_type_display",
            "product",
            "product_name",
            "product_code",
            "quantity_before",
            "quantity_after",
            "quantity_change",
            "reference",
            "performed_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "movement_type_display",
            "product_name",
            "product_code",
        ]


# ============================================================================
# Transaction Fulfillment Serializers
# ============================================================================


class BarcodeScanSerializer(serializers.Serializer):
    """Serializer for barcode scan input."""

    sku = serializers.CharField(required=False, allow_blank=True)
    prod_code = serializers.CharField(required=False, allow_blank=True)
    barcode = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(default=1, min_value=1)
    scanned_by = serializers.CharField(required=False, default="System")

    def validate(self, data):
        """Ensure either sku, prod_code, or barcode is provided."""
        if (
            not data.get("sku")
            and not data.get("prod_code")
            and not data.get("barcode")
        ):
            raise serializers.ValidationError(
                "Either sku, prod_code, or barcode must be provided"
            )
        return data


class IssuanceCancelSerializer(serializers.Serializer):
    """Serializer for cancelling issuance."""

    reason = serializers.CharField(required=False, allow_blank=True)


class IssuanceCompleteSerializer(serializers.Serializer):
    """Serializer for completing issuance. User automatically from request.user."""

    pass


class CancelFulfilledSerializer(serializers.Serializer):
    """Serializer for admin cancelling fulfilled orders."""

    reason = serializers.CharField(required=True, help_text="Reason for cancellation")


class MarkRegistrationSerializer(serializers.Serializer):
    """Serializer for marking transaction as registration."""

    notes = serializers.CharField(
        required=False, allow_blank=True, help_text="Optional notes"
    )


# ============================================================================
# Combined Order Serializers (Phase 2: Transaction Combination)
# ============================================================================


class CombinedOrderTransactionSerializer(serializers.ModelSerializer):
    """Serializer for transactions within a combined order."""

    tx_id = serializers.CharField(source="transaction.tx_id", read_only=True)
    amount = serializers.DecimalField(
        source="transaction.amount", max_digits=10, decimal_places=2, read_only=True
    )
    sender_name = serializers.CharField(
        source="transaction.sender_name", read_only=True
    )
    sender_phone = serializers.CharField(
        source="transaction.sender_phone", read_only=True
    )
    timestamp = serializers.DateTimeField(
        source="transaction.timestamp", read_only=True
    )

    class Meta:
        model = CombinedOrderTransaction
        fields = [
            "id",
            "tx_id",
            "amount",
            "sender_name",
            "sender_phone",
            "timestamp",
            "sequence",
            "added_at",
            "added_by",
        ]
        read_only_fields = [
            "id",
            "tx_id",
            "amount",
            "sender_name",
            "sender_phone",
            "timestamp",
            "added_at",
        ]


class CombinedOrderLineItemSerializer(serializers.ModelSerializer):
    """Serializer for line items in a combined order."""

    product_name = serializers.CharField(source="product.prod_name", read_only=True)
    copied_from_tx_id = serializers.CharField(
        source="copied_from_transaction.tx_id", read_only=True, allow_null=True
    )

    class Meta:
        model = CombinedOrderLineItem
        fields = [
            "id",
            "product",
            "product_name",
            "scanned_prod_code",
            "scanned_prod_name",
            "scanned_sku",
            "scanned_sku_name",
            "scanned_price",
            "scanned_pv",
            "quantity",
            "line_total",
            "line_cost",
            "line_pv",
            "scanned_at",
            "scanned_by",
            "is_inventory_deducted",  # Whether inventory was already deducted for this item
            "copied_from_tx_id",  # Source transaction ID if this was copied from a child transaction
        ]
        read_only_fields = [
            "id",
            "line_total",
            "line_cost",
            "line_pv",
            "scanned_at",
            "product_name",
            "is_inventory_deducted",
            "copied_from_tx_id",
        ]


class CombinedOrderSerializer(serializers.ModelSerializer):
    """Full serializer for combined orders with transactions and line items."""

    transactions = CombinedOrderTransactionSerializer(many=True, read_only=True)
    line_items = CombinedOrderLineItemSerializer(many=True, read_only=True)
    transaction_count = serializers.IntegerField(read_only=True)
    remaining_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    fulfillment_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    parent_transaction_id = serializers.CharField(
        source="parent_transaction.tx_id", read_only=True
    )

    class Meta:
        model = CombinedOrder
        fields = [
            "id",
            "combined_order_id",
            "parent_transaction_id",
            "status",
            "status_display",
            "total_amount",
            "amount_fulfilled",
            "remaining_amount",
            "fulfillment_percentage",
            "customer_name",
            "customer_phone",
            "notes",
            "transaction_count",
            "transactions",
            "line_items",
            "created_by",
            "created_at",
            "updated_at",
            "fulfilled_at",
            "fulfilled_by",
        ]
        read_only_fields = [
            "id",
            "combined_order_id",
            "parent_transaction_id",
            "transaction_count",
            "remaining_amount",
            "fulfillment_percentage",
            "status_display",
            "created_at",
            "updated_at",
            "fulfilled_at",
            "fulfilled_by",
        ]


class CombinedOrderListSerializer(serializers.ModelSerializer):
    """Minimal serializer for listing combined orders (no nested data)."""

    transaction_count = serializers.IntegerField(read_only=True)
    remaining_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    fulfillment_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = CombinedOrder
        fields = [
            "id",
            "combined_order_id",
            "status",
            "status_display",
            "total_amount",
            "amount_fulfilled",
            "remaining_amount",
            "fulfillment_percentage",
            "transaction_count",
            "customer_name",
            "customer_phone",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "combined_order_id",
            "transaction_count",
            "remaining_amount",
            "fulfillment_percentage",
            "status_display",
            "created_at",
        ]


class CombinedOrderCreateSerializer(serializers.Serializer):
    """Serializer for creating a combined order from transaction IDs."""

    transaction_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=2,
        help_text="List of transaction IDs to combine (minimum 2)",
    )
    customer_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    customer_phone = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    created_by = serializers.CharField(max_length=255)

    def validate_transaction_ids(self, value):
        """Ensure transaction IDs are unique."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Transaction IDs must be unique")
        return value


class CombinedOrderScanSerializer(serializers.Serializer):
    """Serializer for scanning products into a combined order."""

    product_id = serializers.IntegerField(help_text="Product ID to scan")
    quantity = serializers.IntegerField(
        default=1, min_value=1, help_text="Quantity to issue"
    )
    scanned_by = serializers.CharField(max_length=255, required=False, default="System")


class CombinedOrderCancelSerializer(serializers.Serializer):
    """Serializer for cancelling a combined order."""

    cancelled_by = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    reason = serializers.CharField(required=False, allow_blank=True)


# ============================================================================
# Stock Take Serializers
# ============================================================================


class StockTakeItemSerializer(serializers.ModelSerializer):
    """Serializer for stock take items with product details."""

    product_name = serializers.CharField(source="product.prod_name", read_only=True)
    product_code = serializers.CharField(source="product.prod_code", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockTakeItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_code",
            "sku",
            "quantity_before",
            "quantity_scanned",
            "quantity_after",
            "scanned_at",
            "scanned_by",
        ]
        read_only_fields = ["id", "scanned_at"]


class StockTakeSessionSerializer(serializers.ModelSerializer):
    """Serializer for stock take sessions with all items."""

    items = StockTakeItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    total_quantity_added = serializers.SerializerMethodField()

    def get_items_count(self, obj):
        """Return count of items in session"""
        return obj.items.count()

    def get_total_quantity_added(self, obj):
        """Return total quantity added across all items"""
        return sum(item.quantity_scanned for item in obj.items.all())

    class Meta:
        model = StockTakeSession
        fields = [
            "session_id",
            "status",
            "created_by",
            "created_at",
            "completed_at",
            "completed_by",
            "notes",
            "kit_quantity",
            "items",
            "items_count",
            "total_quantity_added",
        ]
        read_only_fields = ["session_id", "created_at", "completed_at"]


# ============================================================================
# Stock Reconciliation Serializers
# ============================================================================


class StockAdjustmentItemSerializer(serializers.ModelSerializer):
    """
    Serializer for individual stock adjustment items.

    Note: quantity_replenished is READ-ONLY and auto-calculated from completed
    stock take sessions for the reconciliation date.

    For initial setup, opening_stock_baseline can be set to override the
    calculated opening stock (which comes from previous day's reconciliation).
    """

    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_code = serializers.CharField(source="product.prod_code", read_only=True)
    product_name = serializers.CharField(source="product.prod_name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    cost_price = serializers.DecimalField(
        source="product.cost_price", max_digits=10, decimal_places=2, read_only=True
    )
    current_price = serializers.DecimalField(
        source="product.current_price", max_digits=10, decimal_places=2, read_only=True
    )
    net_adjustment = serializers.IntegerField(read_only=True)
    calculated_totals = serializers.IntegerField(read_only=True)
    effective_opening_stock = serializers.IntegerField(read_only=True)
    sales = serializers.IntegerField(read_only=True)
    expected_consignment = serializers.IntegerField(read_only=True)
    stock_status = serializers.SerializerMethodField()
    stock_value = serializers.SerializerMethodField()
    has_baseline = serializers.SerializerMethodField()

    def get_stock_status(self, obj):
        """Determine stock status based on closing stock and reorder level"""
        if obj.closing_stock <= 0:
            return "OUT_OF_STOCK"
        elif obj.closing_stock <= obj.product.reorder_level:
            return "LOW_STOCK"
        else:
            return "IN_STOCK"

    def get_stock_value(self, obj):
        """Calculate inventory value: closing_stock × cost_price (buying price)"""
        return float(obj.closing_stock * obj.product.cost_price)

    def get_has_baseline(self, obj):
        """Check if this adjustment has a manual baseline set"""
        return obj.opening_stock_baseline is not None

    class Meta:
        model = StockAdjustmentItem
        fields = [
            "id",
            "product_id",
            "product_code",
            "product_name",
            "sku",
            "opening_stock",
            "opening_stock_baseline",
            "effective_opening_stock",
            "has_baseline",
            "quantity_replenished",
            "quantity_added",
            "quantity_deducted",
            "calculated_totals",
            "closing_stock",
            "sales",
            "expected_consignment",
            "net_adjustment",
            "notes",
            "cost_price",
            "current_price",
            "stock_value",
            "stock_status",
            "created_at",
            "updated_at",
        ]
        # quantity_replenished is now read-only (auto-calculated from stock take sessions)
        read_only_fields = [
            "id",
            "opening_stock",
            "quantity_replenished",
            "closing_stock",
            "calculated_totals",
            "effective_opening_stock",
            "sales",
            "expected_consignment",
            "created_at",
            "updated_at",
        ]


class StockAdjustmentItemUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating adjustment items during reconciliation.

    Note: quantity_replenished is NOT included here as it is read-only
    and auto-calculated from completed stock take sessions.
    Only quantity_added and quantity_deducted can be manually updated.
    """

    product_id = serializers.IntegerField(required=True)
    quantity_added = serializers.IntegerField(required=True, min_value=0)
    quantity_deducted = serializers.IntegerField(required=True, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        """Validate that product exists"""
        from payments.models import Product

        try:
            Product.objects.get(id=data["product_id"])
        except Product.DoesNotExist:
            raise serializers.ValidationError({"product_id": "Product not found"})
        return data


class OpeningStockBaselineSerializer(serializers.Serializer):
    """
    Serializer for setting baseline opening stock values during initial setup.

    Use this when previous reconciliation data is incorrect (e.g., placeholder data)
    and you need to define the actual opening stock for today.
    """

    product_id = serializers.IntegerField(required=True)
    opening_stock_baseline = serializers.IntegerField(required=True, min_value=0)

    def validate(self, data):
        """Validate that product exists"""
        from payments.models import Product

        try:
            Product.objects.get(id=data["product_id"])
        except Product.DoesNotExist:
            raise serializers.ValidationError({"product_id": "Product not found"})
        return data


class BulkOpeningStockBaselineSerializer(serializers.Serializer):
    """
    Serializer for setting baseline opening stock for multiple products at once.

    Use this for initial system setup when you need to set real opening stock
    values for all products, ignoring previous placeholder reconciliation data.
    """

    baselines = OpeningStockBaselineSerializer(many=True)
    use_current_inventory = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, sets baseline to current product.quantity for all products (ignores baselines list)",
    )


class DailyStockReconciliationSerializer(serializers.ModelSerializer):
    """Serializer for daily stock reconciliation"""

    adjustments = StockAdjustmentItemSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True
    )
    confirmed_by_username = serializers.CharField(
        source="confirmed_by.username", read_only=True, allow_null=True
    )
    is_confirmed = serializers.BooleanField(read_only=True)
    total_adjustments = serializers.SerializerMethodField()

    def get_total_adjustments(self, obj):
        """Return count of adjustments with non-zero changes"""
        return (
            obj.adjustments.filter(quantity_added__gt=0).count()
            + obj.adjustments.filter(quantity_deducted__gt=0).count()
        )

    class Meta:
        model = DailyStockReconciliation
        fields = [
            "id",
            "reconciliation_date",
            "status",
            "notes",
            "created_by",
            "created_by_username",
            "confirmed_by",
            "confirmed_by_username",
            "created_at",
            "confirmed_at",
            "is_confirmed",
            "adjustments",
            "total_adjustments",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_by",
            "confirmed_by",
            "created_at",
            "confirmed_at",
        ]


class EndOfDayValueReconciliationSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)
    updated_by_username = serializers.CharField(source="updated_by.username", read_only=True, allow_null=True)
    confirmed_by_username = serializers.CharField(source="confirmed_by.username", read_only=True, allow_null=True)

    class Meta:
        model = EndOfDayValueReconciliation
        fields = [
            "id",
            "reconciliation_date",
            "status",
            "opening_stock_value",
            "replenished_value",
            "sales_value",
            "x_value",
            "stock_value",
            "bk_stock",
            "duplicated",
            "y_value",
            "hq_value",
            "kitengela_value",
            "kitui_value",
            "nakuru_value",
            "z_value",
            "v_value",
            "is_within_threshold",
            "created_by",
            "created_by_username",
            "updated_by",
            "updated_by_username",
            "confirmed_by",
            "confirmed_by_username",
            "confirmed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "opening_stock_value",
            "replenished_value",
            "sales_value",
            "x_value",
            "y_value",
            "z_value",
            "v_value",
            "is_within_threshold",
            "created_by",
            "updated_by",
            "confirmed_by",
            "confirmed_at",
            "created_at",
            "updated_at",
        ]


# ============================================================================
# Promotions Serializers
# ============================================================================


class PromotionProductSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.prod_name", read_only=True)
    product_code = serializers.CharField(source="product.prod_code", read_only=True)

    class Meta:
        model = PromotionProduct
        fields = ["id", "product", "product_name", "product_code", "min_quantity"]


class PromotionSerializer(serializers.ModelSerializer):
    products = PromotionProductSerializer(
        source="promotion_products", many=True, read_only=True
    )
    product_items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="List of {product_id, min_quantity} dicts to set on create/update",
    )
    is_currently_active = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True
    )

    class Meta:
        model = Promotion
        fields = [
            "id",
            "name",
            "discount_type",
            "discount_value",
            "start_date",
            "end_date",
            "is_active",
            "is_currently_active",
            "products",
            "product_items",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def _set_product_items(self, promotion, product_items):
        """Replace all PromotionProduct entries with the provided list."""
        from payments.models import Product as ProductModel

        promotion.promotion_products.all().delete()
        for item in product_items:
            try:
                product = ProductModel.objects.get(id=item["product_id"])
            except ProductModel.DoesNotExist:
                raise serializers.ValidationError(
                    {"product_items": f"Product {item['product_id']} not found"}
                )
            PromotionProduct.objects.create(
                promotion=promotion,
                product=product,
                min_quantity=item.get("min_quantity", 1),
            )

    def create(self, validated_data):
        product_items = validated_data.pop("product_items", [])
        promotion = super().create(validated_data)
        if product_items:
            self._set_product_items(promotion, product_items)
        return promotion

    def update(self, instance, validated_data):
        product_items = validated_data.pop("product_items", None)
        promotion = super().update(instance, validated_data)
        if product_items is not None:
            self._set_product_items(promotion, product_items)
        return promotion


# ─── Inventory API (External Website) Serializers ───────────────────────────

class BranchInfoSerializer(serializers.Serializer):
    """Branch identification info returned by each instance."""
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class StockLevelSerializer(serializers.Serializer):
    """Stock level for a product at a specific branch."""
    branchId = serializers.CharField(read_only=True, source='branch_id')
    branchName = serializers.CharField(read_only=True, source='branch_name')
    quantity = serializers.IntegerField(read_only=True)
    inStock = serializers.BooleanField(read_only=True, source='in_stock')


class ProductWithStockSerializer(serializers.Serializer):
    """Product catalog entry with stock across branches.
    Matches the INVENTORY_API_SPEC.md contract."""
    code = serializers.CharField(read_only=True, source='prod_code')
    name = serializers.CharField(read_only=True, source='prod_name')
    category = serializers.CharField(read_only=True, source='category_name')
    description = serializers.CharField(read_only=True, allow_null=True)
    imageUrl = serializers.SerializerMethodField()
    stock = StockLevelSerializer(many=True, read_only=True)

    def get_imageUrl(self, obj):
        request = self.context.get('request')
        if obj.get('image') and request:
            return request.build_absolute_uri(obj['image'])
        return obj.get('image_url') or None
