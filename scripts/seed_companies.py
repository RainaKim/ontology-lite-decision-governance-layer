"""
scripts/seed_companies.py

Inserts the three mock companies into the `companies` DB table.
Uses the same contract-compliant IDs as mock_company*.json so that
`company_id` in pipeline/decisions maps directly to DB rows.

Run from project root:
    source venv/bin/activate
    python scripts/seed_companies.py
"""

import sys
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.models.company import Company


MOCK_COMPANIES = [
    {
        "id": "nexus_dynamics",
        "company_name": "넥서스 다이나믹스",
        "company_name_en": "Nexus Dynamics",
        "domain_url": "nexusdynamics.com",
        "license_tier": "ENTERPRISE",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
    {
        "id": "mayo_central",
        "company_name": "Mayo Central Hospital",
        "company_name_en": "Mayo Central Hospital",
        "domain_url": "mayocentral.org",
        "license_tier": "ENTERPRISE",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
    {
        "id": "sool_sool_icecream",
        "company_name": "Sool Sool Ice Cream",
        "company_name_en": "Sool Sool Ice Cream",
        "domain_url": "soolsoolcream.com",
        "license_tier": "STARTER",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
]


def seed():
    db = SessionLocal()
    try:
        inserted = 0
        skipped = 0
        for data in MOCK_COMPANIES:
            existing = db.get(Company, data["id"])
            if existing:
                print(f"  SKIP  {data['id']} — already exists")
                skipped += 1
                continue

            company = Company(**data)
            db.add(company)
            print(f"  INSERT {data['id']} ({data['company_name']})")
            inserted += 1

        db.commit()
        print(f"\nDone. inserted={inserted}, skipped={skipped}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
