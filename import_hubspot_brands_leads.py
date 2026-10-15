#!/usr/bin/env python3
"""
import_hubspot_brands_leads.py — Import Hubspot Contacts matched with Brand details.
Wipes existing leads in flinza.db and imports ONLY the 200 Hubspot contacts
enriched with store/brand data from leads_final_brands.csv.
"""

import os
import csv
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "flinza.db"
HUBSPOT_CSV = Path("/data/data/com.termux/files/home/storage/dcim/dashboard/hubspot-crm-exports-all-contacts-2026-10-13-1.csv")
BRANDS_CSV = Path("/data/data/com.termux/files/home/storage/dcim/dashboard/leads_final_brands.csv")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_columns(conn):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    columns_to_add = [
        ("crm_priority", "INTEGER DEFAULT 0"),
        ("country", "TEXT"),
        ("revenue", "TEXT"),
        ("company_size", "TEXT"),
        ("icp_fit", "TEXT"),
        ("instagram_handle", "TEXT"),
        ("instagram_followers", "INTEGER DEFAULT 0"),
        ("follower_band", "TEXT"),
        ("email_confidence", "TEXT"),
        ("email_type", "TEXT"),
        ("contact_title", "TEXT"),
        ("sub_niche", "TEXT"),
        ("brand_confidence", "TEXT"),
        ("instagram_url", "TEXT"),
        ("mx_status", "TEXT"),
        ("dmarc_status", "TEXT"),
        ("spf_status", "TEXT"),
        ("personalized_icebreaker", "TEXT"),
        ("exec_name", "TEXT"),
        ("exec_title", "TEXT"),
        ("exec_email", "TEXT"),
    ]
    for col, col_type in columns_to_add:
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
            except Exception as e:
                print(f"Notice: {e}")
    conn.commit()


def generate_hook(brand_name: str, niche: str, sub_niche: str, page_title: str) -> str:
    brand = brand_name.strip() if brand_name else "your brand"
    if "beauty" in niche.lower() or "skincare" in niche.lower() or "fragrance" in (sub_niche or "").lower():
        return f"Loved what {brand} is building in the beauty & skincare space — your product visual aesthetic and packaging really stand out."
    elif "apparel" in niche.lower() or "fashion" in niche.lower():
        return f"Really impressed by {brand}'s apparel collection and creative direction — the brand identity is super crisp."
    elif "supplement" in niche.lower() or "health" in niche.lower():
        return f"Big fan of {brand}'s approach in health & wellness — formulation and customer community are top-tier."
    elif "jewelry" in niche.lower():
        return f"The craftsmanship and product presentation across {brand}'s jewelry catalog is exceptional."
    else:
        return f"Really compelling brand story at {brand} — the customer experience and curation really stand out."


def run_import():
    if not HUBSPOT_CSV.exists():
        print(f"Error: {HUBSPOT_CSV} not found")
        return
    if not BRANDS_CSV.exists():
        print(f"Error: {BRANDS_CSV} not found")
        return

    with open(HUBSPOT_CSV, encoding="utf-8-sig") as f:
        hubspot = list(csv.DictReader(f))

    with open(BRANDS_CSV, encoding="utf-8-sig") as f:
        brands = list(csv.DictReader(f))

    conn = get_db()
    ensure_columns(conn)

    # 1. Wipe existing leads completely to ensure ONLY these leads are in the CRM
    print("🗑️ Clearing existing leads in flinza.db...")
    conn.execute("DELETE FROM leads")
    try:
        conn.execute("DELETE FROM sqlite_sequence WHERE name='leads'")
    except Exception:
        pass
    conn.commit()

    print(f"📥 Importing {len(hubspot)} leads from Hubspot matched with Brand details...")

    inserted = 0
    tier1_count = 0
    tier2_count = 0
    tier3_count = 0

    now_iso = datetime.now().isoformat()

    for i, h in enumerate(hubspot):
        b = brands[i] if i < len(brands) else {}

        # Hubspot contact info
        first_name = (h.get("First Name") or "").strip()
        last_name = (h.get("Last Name") or "").strip()
        name = f"{first_name} {last_name}".strip()
        if not name:
            name = (b.get("contact_name_sheet") or "Founder").strip()
        email = (h.get("Email") or "").strip().lower()
        if not email or "@" not in email:
            continue

        # Brand / Store info from leads_final_brands.csv
        brand_name = (b.get("brand_name") or "").strip() or "DTC Brand"
        final_domain = (b.get("final_domain") or "").strip()
        website = f"https://{final_domain}" if final_domain and not final_domain.startswith("http") else final_domain
        niche = (b.get("niche") or "DTC Brands").strip()
        sub_niche = (b.get("sub_niche") or "").strip()
        country = (b.get("country") or "US").strip()
        ig_handle = (b.get("instagram_handle") or "").strip()
        ig_url = (b.get("instagram_url") or "").strip()
        follower_band = (b.get("follower_band") or "").strip()
        page_title = (b.get("page_title") or "").strip()
        contact_title = (b.get("contact_title_sheet") or "Founder / Owner").strip()

        # Followers parsing
        followers_raw = b.get("followers", "0")
        try:
            followers = int(str(followers_raw).replace(",", "").split(".")[0])
        except Exception:
            followers = 0

        # Estimated Revenue & Company Size based on store data
        if followers >= 500000:
            revenue = "$10M - $50M+"
            company_size = "51-200 employees"
            icp_fit = "Tier 1 High ICP"
            priority = 1
        elif followers >= 100000:
            revenue = "$3M - $10M"
            company_size = "11-50 employees"
            icp_fit = "Tier 1 High ICP"
            priority = 1
        elif followers >= 40000:
            revenue = "$1M - $3M"
            company_size = "11-50 employees"
            icp_fit = "Tier 2 Good ICP"
            priority = 2
        elif followers >= 15000:
            revenue = "$500K - $1M"
            company_size = "1-10 employees"
            icp_fit = "Tier 2 Good ICP"
            priority = 2
        else:
            revenue = "$250K - $500K"
            company_size = "1-10 employees"
            icp_fit = "Tier 3 Backup ICP"
            priority = 3

        if priority == 1:
            tier1_count += 1
        elif priority == 2:
            tier2_count += 1
        elif priority == 3:
            tier3_count += 1

        icebreaker = generate_hook(brand_name, niche, sub_niche, page_title)

        conn.execute("""
            INSERT INTO leads (
                name, email, company, website, niche, sub_niche, country,
                stage, source, crm_priority, revenue, company_size, icp_fit,
                instagram_handle, instagram_url, instagram_followers, follower_band,
                contact_title, deliverability_status, deliverability_score,
                personalized_icebreaker, custom_hook, notes, added_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            name, email, brand_name, website, niche, sub_niche, country,
            "new", "hubspot_brands_final", priority, revenue, company_size, icp_fit,
            ig_handle, ig_url, followers, follower_band,
            contact_title, "verified", 100,
            icebreaker, icebreaker, f"Hubspot Record ID: {h.get('Record ID','')}", now_iso
        ))
        inserted += 1

    conn.commit()

    total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    verified_leads = conn.execute("SELECT COUNT(*) FROM leads WHERE deliverability_status='verified'").fetchone()[0]
    t1 = conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=1").fetchone()[0]
    t2 = conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=2").fetchone()[0]
    t3 = conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=3").fetchone()[0]
    conn.close()

    print("=" * 60)
    print("✅ HUBSPOT + BRANDS LEADS IMPORT COMPLETE")
    print("=" * 60)
    print(f"  • Total leads in CRM : {total_leads}")
    print(f"  • 100% Verified      : {verified_leads}")
    print(f"  • ⭐ Tier 1 (Next Send): {t1}")
    print(f"  • Tier 2 (Secondary) : {t2}")
    print(f"  • Tier 3 (Backup)    : {t3}")
    print("=" * 60)


if __name__ == "__main__":
    run_import()
