import json
from pathlib import Path

from django.core.management.base import BaseCommand

from payments.models import Product, ProductLine


class Command(BaseCommand):
    help = "Export product lines and products to a portable JSON seed file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="/app/products_catalog_seed.json",
            help="Output JSON file path (default: /app/products_catalog_seed.json)",
        )
        parser.add_argument(
            "--include-quantity",
            action="store_true",
            help="Include current quantity values in export (default: quantities exported as 0).",
        )

    def handle(self, *args, **options):
        output_path = Path(options["file"])
        include_quantity = options["include_quantity"]

        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = ProductLine.objects.select_related("parent_line").order_by("name")
        products = Product.objects.select_related("product_line").order_by("prod_name", "prod_code")

        payload = {
            "schema_version": 1,
            "exported_counts": {
                "product_lines": lines.count(),
                "products": products.count(),
            },
            "product_lines": [
                {
                    "name": line.name,
                    "description": line.description or "",
                    "parent_line": line.parent_line.name if line.parent_line else None,
                }
                for line in lines
            ],
            "products": [
                {
                    "prod_code": product.prod_code,
                    "prod_name": product.prod_name,
                    "sku": product.sku,
                    "sku_name": product.sku_name,
                    "barcode": product.barcode,
                    "current_price": str(product.current_price),
                    "cost_price": str(product.cost_price),
                    "current_pv": str(product.current_pv),
                    "quantity": product.quantity if include_quantity else 0,
                    "reorder_level": product.reorder_level,
                    "is_active": product.is_active,
                    "product_line": product.product_line.name if product.product_line else None,
                }
                for product in products
            ],
        }

        with output_path.open("w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"Export complete: {payload['exported_counts']['products']} products -> {output_path}"
            )
        )
