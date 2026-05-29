from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed products catalog from Excel using the standard importer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="/app/products.xlsx",
            help="Path to products Excel file (default: /app/products.xlsx)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing products before seeding.",
        )

    def handle(self, *args, **options):
        excel_file = options["file"]
        clear = options["clear"]

        self.stdout.write(
            self.style.WARNING(
                f"Seeding products catalog from: {excel_file}"
            )
        )

        command_options = {"file": excel_file}
        if clear:
            command_options["clear"] = True

        call_command("import_products_excel", **command_options)

        self.stdout.write(
            self.style.SUCCESS("Products catalog seed completed.")
        )
