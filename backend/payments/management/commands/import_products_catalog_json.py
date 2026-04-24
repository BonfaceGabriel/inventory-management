import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from payments.models import Product, ProductLine


class Command(BaseCommand):
    help = "Import product lines and products from a JSON catalog seed file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="/app/products_catalog_seed.json",
            help="Input JSON file path (default: /app/products_catalog_seed.json)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing products and product lines before import.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        input_path = Path(options["file"])
        clear = options["clear"]

        if not input_path.exists():
            raise CommandError(f"File not found: {input_path}")

        with input_path.open("r", encoding="utf-8") as input_file:
            payload = json.load(input_file)

        if payload.get("schema_version") != 1:
            raise CommandError("Unsupported schema_version. Expected 1.")

        lines_data = payload.get("product_lines", [])
        products_data = payload.get("products", [])

        if clear:
            Product.objects.all().delete()
            ProductLine.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared existing products and product lines."))

        line_by_name = {}
        created_lines = 0
        updated_lines = 0

        # First pass: ensure all lines exist
        for line in lines_data:
            obj, created = ProductLine.objects.update_or_create(
                name=line["name"],
                defaults={"description": line.get("description", "")},
            )
            line_by_name[obj.name] = obj
            if created:
                created_lines += 1
            else:
                updated_lines += 1

        # Second pass: wire parent-child links
        for line in lines_data:
            parent_name = line.get("parent_line")
            if not parent_name:
                continue
            child = line_by_name.get(line["name"])
            parent = line_by_name.get(parent_name)
            if child and parent and child.parent_line_id != parent.id:
                child.parent_line = parent
                child.save(update_fields=["parent_line"])

        created_products = 0
        updated_products = 0

        for item in products_data:
            product_line_name = item.get("product_line")
            product_line = line_by_name.get(product_line_name) if product_line_name else None

            product, created = Product.objects.update_or_create(
                prod_code=item["prod_code"],
                defaults={
                    "prod_name": item["prod_name"],
                    "sku": item["sku"],
                    "sku_name": item.get("sku_name", item["prod_name"]),
                    "barcode": item.get("barcode"),
                    "current_price": Decimal(str(item["current_price"])),
                    "cost_price": Decimal(str(item["cost_price"])),
                    "current_pv": Decimal(str(item["current_pv"])),
                    "quantity": int(item.get("quantity", 0)),
                    "reorder_level": int(item.get("reorder_level", 10)),
                    "is_active": bool(item.get("is_active", True)),
                    "product_line": product_line,
                },
            )

            if created:
                created_products += 1
            else:
                updated_products += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Import complete: "
                f"{created_lines} product lines created, {updated_lines} updated; "
                f"{created_products} products created, {updated_products} updated."
            )
        )
