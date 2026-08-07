import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from collections import defaultdict

def get_readonly_connection(db_path: str) -> sqlite3.Connection:
    import urllib.parse
    uri = f"file:{urllib.parse.quote(str(db_path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

# Known tier-1 hostnames
_HOSTNAME_ROUTES = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "amazon.jobs",
    "jobright.com",
    "jobright.ai",
)

def is_generic(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    for needle in _HOSTNAME_ROUTES:
        if needle in hostname:
            return False
    return True

def main():
    conn = get_readonly_connection("data/jobs.db")
    
    # 8 weeks ago
    eight_weeks_ago = (datetime.now(timezone.utc) - timedelta(weeks=8)).isoformat()
    
    cursor = conn.execute(
        "SELECT url, resolver, status, discovered_at, jd_resolved_at, date_posted FROM jobs WHERE discovered_at >= ?",
        (eight_weeks_ago,)
    )
    
    tier2_reached = []
    
    for row in cursor:
        url = row["url"]
        resolver = row["resolver"]
        status = row["status"]
        
        # Did it reach tier-2?
        if resolver == "browser":
            tier2_reached.append(dict(row))
        elif status == "RESOLVE_FAILED":
            if is_generic(url):
                tier2_reached.append(dict(row))
                
    total_tier2_reached = len(tier2_reached)
    accepted = sum(1 for r in tier2_reached if r["resolver"] == "browser")
    unresolved = sum(1 for r in tier2_reached if r["status"] == "RESOLVE_FAILED")
    
    host_counts = defaultdict(int)
    for r in tier2_reached:
        host_counts[urlparse(r["url"]).hostname or ""] += 1
        
    ages = []
    for r in tier2_reached:
        disc_ts = datetime.fromisoformat(r["discovered_at"])
        if r["jd_resolved_at"]:
            att_ts = datetime.fromisoformat(r["jd_resolved_at"])
        else:
            att_ts = disc_ts + timedelta(days=3)
            
        age_since_discovery = (att_ts - disc_ts).days
        age_since_posted = None
        if r["date_posted"]:
            try:
                dp = datetime.fromisoformat(r["date_posted"]).replace(tzinfo=timezone.utc)
                age_since_posted = (att_ts - dp).days
            except:
                pass
        ages.append((age_since_discovery, age_since_posted))

    print("TASK 1 - TIER 2 DEMAND REPORT (LAST 8 WEEKS)")
    print(f"1. Distinct job URLs that reached tier-2 generic route: {total_tier2_reached}")
    print(f"2. Produced an ACCEPTED jd_text via tier-2: {accepted}")
    print(f"3. Still unresolved / failed: {unresolved}")
    pct = (accepted / total_tier2_reached * 100) if total_tier2_reached > 0 else 0.0
    print(f"4. Accepted count as percentage of attempts: {pct:.1f}%")
    
    print("5. Breakdown by host (Top 10):")
    for host, count in sorted(host_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"   - {host}: {count}")
        
    print("6. Age distribution at attempt time (days since discovery):")
    disc_ages = [a[0] for a in ages]
    print(f"   - Min: {min(disc_ages)} days")
    print(f"   - Max: {max(disc_ages)} days")
    print(f"   - Avg: {sum(disc_ages)/len(disc_ages):.1f} days")
    
    posted_ages = [a[1] for a in ages if a[1] is not None]
    if posted_ages:
        print("   Age distribution at attempt time (days since posted):")
        print(f"   - Min: {min(posted_ages)} days")
        print(f"   - Max: {max(posted_ages)} days")
        print(f"   - Avg: {sum(posted_ages)/len(posted_ages):.1f} days")

if __name__ == "__main__":
    main()
