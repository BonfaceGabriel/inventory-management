"""
Opening Stock Baseline Setup Script

Run this in the Django shell on production:
    docker exec -it <container-name> python manage.py shell

Then copy and paste the entire script below.
"""

from payments.models import DailyStockReconciliation, StockAdjustmentItem, Product, User
from payments.services.reconciliation_workflow_service import ReconciliationWorkflowService
from datetime import date

# ============================================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================================
RECONCILIATION_DATE = date.today()  # Uses today's date automatically
USERNAME = 'admin'  # Change to your admin username

print(f"Setting up reconciliation for: {RECONCILIATION_DATE}")

# ============================================================
# BASELINE DATA FROM products.xlsx
# ============================================================
BASELINE_DATA = {
    "4 in 1 Reishi Coffee": 102,
    "4 in 1 Ginseng Coffee": 68,
    "4 in 1 Cordyceps Coffee": 83,
    "Pure & Broken Ganoderma Spores (30's)": 92,
    "Pure & Broken Ganoderma Spores (60's)": 65,
    "Pure & Broken Ganoderma Oil (60's)": 19,
    "Refined Yunzhi Capsules": 35,
    "Quad Reishi Capsules": 18,
    "YOUTH EVER": 6,
    "NMN coffee": 12,
    "NMN-Sharp Mind": 16,
    "NMN DUO release": 19,
    "GluzoJoint-F Capsules": 0,
    "ArthroXtra Tablets": 106,
    "Zaminocal Plus": 65,
    "GluzoJoint-Ultra Pro Tablets": 0,
    "MicrO2 Cycle Tablets": 89,
    "CereBrain Tablets": 67,
    "Relivin Tea": 32,
    "GymEffect Capsule": 30,
    "Detoxilive Capsules pro": 27,
    "ConstiRelax Solution": 45,
    "Ntdiarr Pills (1 Dozen)": 132,
    "Elements": 25,
    "Novel Depile Capsules": 52,
    "Probio 3": 63,
    "Veggie Veggie": 75,
    "Ez-Xlim Capsule": 0,
    "ProstatRelax Capsules": 74,
    "X Power Man Capsules": 15,
    "Xpower Coffee for Men": 9,
    "Feminergy Capsules": 44,
    "FemiCalcium D3": 18,
    "Femibiotics": 19,
    "Youth Refreshing Facial Cleanser": 10,
    "Youth Essence Lotion": 0,
    "Youth Essence Toner": 7,
    "Youth Essence Facial Mask": 8,
    "Youth Essence Cream": 0,
    "Calcium and Vitamin D3": 13,
    "Sharp Vision": 23,
    "Vitamin C Chewable": 31,
    "AnaticTM Herbal Essence Soap": 259,
    "FemiCare Feminine Cleanser": 19,
    "Dr.Ts Toothpaste": 155,
    "Cool Roll (1 Dozen)": 253,
    "Registration Fee": 66,
}

# ============================================================
# STEP 1: Get or Create Reconciliation
# ============================================================
print("=" * 60)
print("STEP 1: Getting/Creating Reconciliation")
print("=" * 60)

user = User.objects.get(username=USERNAME)
recon = ReconciliationWorkflowService.get_or_create_reconciliation(RECONCILIATION_DATE, user)
print(f"Reconciliation ID: {recon.id}")
print(f"Status: {recon.status}")
print(f"Date: {recon.reconciliation_date}")

# ============================================================
# STEP 2: Match Products and Set Baselines
# ============================================================
print("\n" + "=" * 60)
print("STEP 2: Matching Products and Setting Baselines")
print("=" * 60)

matched = 0
not_found_excel = []
not_found_db = []

# Get all products from database
db_products = {p.prod_name: p for p in Product.objects.filter(is_active=True)}

# Match and set baselines
for excel_name, stock in BASELINE_DATA.items():
    # Try exact match first
    if excel_name in db_products:
        product = db_products[excel_name]
        try:
            ReconciliationWorkflowService.set_opening_stock_baseline(
                str(recon.id),
                product_id=product.id,
                baseline_value=int(stock)
            )
            print(f"  [OK] {excel_name}: {stock}")
            matched += 1
        except Exception as e:
            print(f"  [ERROR] {excel_name}: {e}")
    else:
        # Try case-insensitive match
        found = False
        for db_name, product in db_products.items():
            if db_name.lower() == excel_name.lower():
                try:
                    ReconciliationWorkflowService.set_opening_stock_baseline(
                        str(recon.id),
                        product_id=product.id,
                        baseline_value=int(stock)
                    )
                    print(f"  [OK] {excel_name} -> {db_name}: {stock}")
                    matched += 1
                    found = True
                    break
                except Exception as e:
                    print(f"  [ERROR] {excel_name}: {e}")
                    found = True
                    break

        if not found:
            not_found_excel.append(excel_name)
            print(f"  [NOT FOUND] {excel_name}")

# Check for DB products not in Excel
for db_name in db_products.keys():
    if db_name not in BASELINE_DATA:
        # Check case-insensitive
        found = any(db_name.lower() == excel_name.lower() for excel_name in BASELINE_DATA.keys())
        if not found:
            not_found_db.append(db_name)

# ============================================================
# STEP 3: Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Matched and set: {matched}")
print(f"Not found in DB: {len(not_found_excel)}")
if not_found_excel:
    print(f"  Products in Excel but not in DB:")
    for name in not_found_excel:
        print(f"    - {name}")

print(f"\nProducts in DB but not in Excel: {len(not_found_db)}")
if not_found_db:
    for name in not_found_db:
        print(f"    - {name}")

# ============================================================
# STEP 4: Verify Results
# ============================================================
print("\n" + "=" * 60)
print("VERIFICATION - Current State")
print("=" * 60)
print(f"{'Product':<40} | {'Baseline':>10} | {'Closing':>10}")
print("-" * 65)

adjustments = recon.adjustments.select_related('product').order_by('product__prod_name')
for a in adjustments:
    baseline = str(a.opening_stock_baseline) if a.opening_stock_baseline is not None else '-'
    print(f"{a.product.prod_name[:39]:<40} | {baseline:>10} | {a.closing_stock:>10}")

print("\n" + "=" * 60)
print("DONE!")
print("=" * 60)
print(f"\nReconciliation ID: {recon.id}")
print(f"Status: {recon.status}")
print("\nTo confirm this reconciliation (LOCKS IT - cannot undo):")
print(f"  ReconciliationWorkflowService.confirm_reconciliation('{recon.id}', user)")


# Update opening stock for products not found in Excel

# Registration Kit = 66
for a in recon.adjustments.select_related('product').all():
    if "registration" in a.product.prod_name.lower() and "kit" in a.product.prod_name.lower():
        a.opening_stock = 66
        a.save()
        print(f"Updated {a.product.prod_name}: opening_stock = 66")

# Detoxilive Pro Oil Capsules = 27
for a in recon.adjustments.select_related('product').all():
    if "detox" in a.product.prod_name.lower() and "pro" in a.product.prod_name.lower():
        a.opening_stock = 27
        a.save()
        print(f"Updated {a.product.prod_name}: opening_stock = 27")

print("\nDone!")