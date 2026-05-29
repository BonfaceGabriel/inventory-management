from django.db import migrations, models


def migrate_merch_gateway_type(apps, schema_editor):
    PaymentGateway = apps.get_model("payments", "PaymentGateway")
    aliases = {"till merchandise", "merchandise"}
    for gateway in PaymentGateway.objects.all():
        if (gateway.name or "").strip().lower() in aliases and gateway.gateway_type != "MERCHANDISE":
            gateway.gateway_type = "MERCHANDISE"
            gateway.save(update_fields=["gateway_type"])


def reverse_merch_gateway_type(apps, schema_editor):
    PaymentGateway = apps.get_model("payments", "PaymentGateway")
    aliases = {"till merchandise", "merchandise"}
    for gateway in PaymentGateway.objects.all():
        if (gateway.name or "").strip().lower() in aliases and gateway.gateway_type == "MERCHANDISE":
            gateway.gateway_type = "MPESA_TILL"
            gateway.save(update_fields=["gateway_type"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0029_endofdayvaluereconciliation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentgateway",
            name="gateway_type",
            field=models.CharField(
                choices=[
                    ("MPESA_TILL", "M-PESA Till Number"),
                    ("MERCHANDISE", "Merchandise Till"),
                    ("MPESA_PAYBILL", "M-PESA Paybill"),
                    ("PDQ", "PDQ/Card Payment"),
                    ("BANK_TRANSFER", "Bank Transfer"),
                    ("CASH", "Cash Payment"),
                    ("OTHER", "Other"),
                ],
                help_text="Type of payment gateway",
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_merch_gateway_type, reverse_merch_gateway_type),
    ]
