import os
import django
from django.db import connection
import csv

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "health_dms.settings")  # Adjust if your settings module name is different
django.setup()

from core.models import Region, LocalCouncil, JamatKhana

def import_data():
    regions_file = "regions.csv"
    locals_file = "locals.csv"
    jk_file = "jk.csv"

    print("Clearing existing data and resetting IDs...")
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM core_jamatkhana;")
        cursor.execute("DELETE FROM core_localcouncil;")
        cursor.execute("DELETE FROM core_region;")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('core_jamatkhana', 'core_localcouncil', 'core_region');")
    print("Data cleared and IDs reset successfully.")

    # 1. Import Regions (Col 0: code, Col 1: name)
    if os.path.exists(regions_file):
        print("Importing regions...")
        with open(regions_file, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                code = row[0].strip()
                name = row[1].strip()
                
                Region.objects.create(
                    code=code,
                    name=name,
                )
        print("Regions imported successfully.")

    # 2. Import Local Councils (Col 0: code, Col 1: name, Col 2: region_code)
    if os.path.exists(locals_file):
        print("Importing local councils...")
        with open(locals_file, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 3:
                    continue
                code = row[0].strip()
                name = row[1].strip()
                region_code = row[2].strip()
                
                try:
                    region = Region.objects.get(code=region_code)
                    LocalCouncil.objects.create(
                        code=code,
                        name=name,
                        region=region,
                    )
                except Region.DoesNotExist:
                    print(f"Region code '{region_code}' not found for local council: {name}")
        print("Local councils imported successfully.")

    # 3. Import Jamatkhanas (Col 0: code, Col 1: name, Col 2: local_council_code)
    if os.path.exists(jk_file):
        print("Importing jamatkhanas...")
        with open(jk_file, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 3:
                    continue
                code = row[0].strip()
                name = row[1].strip()
                local_council_code = row[2].strip()
                
                try:
                    local_council = LocalCouncil.objects.get(code=local_council_code)
                    JamatKhana.objects.create(
                        code=code,
                        name=name,
                        local_council=local_council,
                    )
                except LocalCouncil.DoesNotExist:
                    print(f"Local Council code '{local_council_code}' not found for jamatkhana: {name}")
        print("Jamatkhanas imported successfully.")

if __name__ == "__main__":
    import_data()