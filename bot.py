# fake_traffic_simulator.py
import requests
import random
import threading
import time
from datetime import datetime

URLS = [
    "https://example.com/",
    "https://example.com/blog",
    "https://example.com/about",
    "https://example.com/contact",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/119.0",
    "curl/7.81.0",
    "python-requests/2.28.1"
]
REFERRERS = [
    "https://google.com",
    "https://facebook.com",
    "https://twitter.com",
    "https://linkedin.com",
    ""
]

def visit_website(session_id: int, n_visits: int = 5):
    for i in range(n_visits):
        url = random.choice(URLS)
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": random.choice(REFERRERS)
        }
        try:
            r = requests.get(url, headers=headers, timeout=5)
            print(f"[{datetime.now().isoformat()}] Session {session_id} -> {url} ({r.status_code})")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Session {session_id} ERROR: {e}")
        # random “dwell time” to simulate real browsing
        time.sleep(random.uniform(2, 10))

def simulate_users(total_users: int = 20, visits_per_user: int = 5):
    threads = []
    for i in range(total_users):
        t = threading.Thread(target=visit_website, args=(i, visits_per_user))
        threads.append(t)
        t.start()
        time.sleep(random.uniform(0.2, 1.5))  # stagger starts

    for t in threads:
        t.join()

if __name__ == "__main__":
    simulate_users(total_users=50, visits_per_user=8)
