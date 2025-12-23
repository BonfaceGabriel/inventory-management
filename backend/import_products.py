
import pandas as pd
from payments.models import Product, ProductCategory
import sys

def import_products(file_path):
    try:
        df = pd.read_excel(file_path)
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading the Excel file: {e}")
        sys.exit(1)

    for index, row in df.iterrows():
        try:
            # Get or create the category
            category_name = row.get('category')
            category = None
            if category_name:
                category, _ = ProductCategory.objects.get_or_create(name=category_name)

            # Create or update the product
            product, created = Product.objects.update_or_create(
                prod_code=row['prod_code'],
                defaults={
                    'prod_name': row['prod_name'],
                    'sku': row.get('sku'),
                    'sku_name': row.get('sku_name'),
                    'current_price': row.get('current_price'),
                    'cost_price': row.get('cost_price'),
                    'current_pv': row.get('current_pv'),
                    'quantity': row.get('quantity', 0),
                    'reorder_level': row.get('reorder_level', 10),
                    'category': category,
                    'is_active': row.get('is_active', True),
                }
            )

            if created:
                print(f"Created new product: {product.prod_name}")
            else:
                print(f"Updated product: {product.prod_name}")

        except Exception as e:
            print(f"Error processing row {index}: {row.to_dict()}")
            print(f"Error: {e}")
            continue

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python manage.py shell < import_products.py <file_path>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    import_products(file_path)
