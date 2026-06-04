import os
import sys
import django
from django.utils import timezone

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from payments.models import RawMessage

def cleanup_junk():
    now = timezone.now()
    print(f"--- Junk Message Cleanup Started at {now} ---")
    
    # Find all messages that are not processed and were created before this moment
    junk_qs = RawMessage.objects.filter(processed=False, created_at__lt=now)
    total_count = junk_qs.count()
    
    if total_count == 0:
        print("No junk messages found. Your queue is already clean!")
        return

    print(f"Found {total_count} unprocessed messages from the past.")
    
    # Update in batches for safety
    updated_count = junk_qs.update(processed=True)
    
    print(f"Successfully marked {updated_count} messages as PROCESSED.")
    print("Celery will no longer attempt to reprocess these old messages.")
    print("--- Cleanup Complete ---")

if __name__ == "__main__":
    cleanup_junk()
