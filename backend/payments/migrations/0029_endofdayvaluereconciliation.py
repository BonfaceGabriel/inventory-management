from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0028_merchandise_stock_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EndOfDayValueReconciliation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reconciliation_date", models.DateField(db_index=True, unique=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("CONFIRMED", "Confirmed")], db_index=True, default="DRAFT", max_length=20)),
                ("opening_stock_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("replenished_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("sales_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("x_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("stock_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("bk_stock", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("duplicated", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("y_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("hq_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("kitengela_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("kitui_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("nakuru_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("z_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("v_value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("is_within_threshold", models.BooleanField(default=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="eod_value_reconciliations_confirmed", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="eod_value_reconciliations_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="eod_value_reconciliations_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "End of Day Value Reconciliation",
                "verbose_name_plural": "End of Day Value Reconciliations",
                "ordering": ["-reconciliation_date"],
            },
        ),
    ]
