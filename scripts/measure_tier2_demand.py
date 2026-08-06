import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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
        "SELECT url, resolver, status FROM jobs WHERE discovered_at >= ?",
        (eight_weeks_ago,)
    )
    
    total_tier2_reached = 0
    total_tier2_failed = 0
    
    for row in cursor:
        url = row["url"]
        resolver = row["resolver"]
        status = row["status"]
        
        # Did it reach tier-2?
        # If it succeeded at tier-2, its resolver is 'browser'.
        if resolver == "browser":
            total_tier2_reached += 1
        elif status == "RESOLVE_FAILED":
            # If it failed resolution and it's a generic URL, it reached tier-2 and failed.
            if is_generic(url):
                total_tier2_reached += 1
                total_tier2_failed += 1
                
    print(f"In the last 8 weeks:")
    print(f"Distinct job URLs that reached the tier-2 generic route: {total_tier2_reached}")
    print(f"Of those, failed to produce acceptable content: {total_tier2_failed}")

if __name__ == "__main__":
    main()
