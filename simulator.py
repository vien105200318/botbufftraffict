#!/usr/bin/env python3
"""
simulator.py
Mô phỏng user ảo truy cập website (HTTP requests hoặc Selenium headless).
Chỉ dùng cho mục đích thử nghiệm trên site được phép.
"""

import requests
import random
import threading
import time
import csv
import uuid
from datetime import datetime
import argparse
import os

# Optional Selenium support
USE_SELENIUM = False
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    USE_SELENIUM = True
except Exception:
    USE_SELENIUM = False

# --------------------------
# CONFIG - chỉnh tại đây
# --------------------------
CONFIG = {
    "TARGET_URLS": [
        "http://localhost:8000/",
        "http://localhost:8000/article/1",
        "http://localhost:8000/about",
    ],
    # user agents (có thể mở rộng)
    "USER_AGENTS": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
        "python-requests/2.28.1",
        "curl/7.81.0",
    ],
    "REFERRERS": [
        "https://www.google.com/",
        "https://www.facebook.com/",
        "https://t.me/example",
        "",
    ],
    # dwell time distribution (seconds) between pageviews for normal users
    "DWELL_NORMAL": (5.0, 25.0),    # uniform(a, b)
    # dwell time distribution for "bot-like" sessions (short)
    "DWELL_BOT": (0.2, 2.0),
    # ratio of bot-like sessions (if you want mix)
    "BOT_RATIO": 0.0,  # default 0 (all 'normal' browsing)
    # logging
    "LOG_CSV": "traffic_log.csv",
    # concurrency
    "CONCURRENT_SESSIONS": 20,
    # pageviews per session (range)
    "PAGEVIEWS_RANGE": (3, 10),
    # timeout for requests
    "REQUEST_TIMEOUT": 10,
    # proxies list file (one proxy per line, optional)
    "PROXY_FILE": None,  # "proxies.txt"
    # use selenium
    "USE_SELENIUM": False,  # override by CLI flag
    # selenium driver path (if needed). If using chromedriver on PATH, can be None.
    "CHROMEDRIVER_PATH": None,
    # whether to persist console output
    "VERBOSE": True,
}
# --------------------------

lock = threading.Lock()

def load_proxies(proxy_file):
    if not proxy_file or not os.path.exists(proxy_file):
        return []
    proxies = []
    with open(proxy_file, "r") as f:
        for line in f:
            p = line.strip()
            if p:
                proxies.append(p)
    return proxies

def get_proxy_dict(proxy_url):
    # returns requests-compatible proxies dict
    return {"http": proxy_url, "https": proxy_url}

def write_csv_header(path):
    exists = os.path.exists(path)
    if not exists:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp","session_id","seq","url","status_code","user_agent",
                "referrer","proxy","dwell_seconds","note"
            ])

def append_csv_row(path, row):
    with lock:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

def make_request_requests(url, headers, proxy=None, timeout=10):
    try:
        if proxy:
            r = requests.get(url, headers=headers, proxies=get_proxy_dict(proxy), timeout=timeout)
        else:
            r = requests.get(url, headers=headers, timeout=timeout)
        return r.status_code, None
    except Exception as e:
        return None, str(e)

def make_request_selenium(driver, url, headers=None, timeout=15):
    # Selenium will handle headers less directly; we can use navigator override if needed.
    try:
        driver.get(url)
        time.sleep(0.5)  # let page start loading; we simulate user stay separately
        return 200, None
    except Exception as e:
        return None, str(e)

def simulate_session(session_idx, config, proxies):
    session_id = str(uuid.uuid4())
    pageviews = random.randint(config["PAGEVIEWS_RANGE"][0], config["PAGEVIEWS_RANGE"][1])
    is_bot = random.random() < config["BOT_RATIO"]
    for seq in range(1, pageviews+1):
        url = random.choice(config["TARGET_URLS"])
        ua = random.choice(config["USER_AGENTS"])
        ref = random.choice(config["REFERRERS"])
        proxy = random.choice(proxies) if proxies else None

        headers = {"User-Agent": ua}
        if ref:
            headers["Referer"] = ref

        timestamp = datetime.utcnow().isoformat()

        if config["USE_SELENIUM"]:
            # Selenium: create driver per session (or reuse) - here create per session for simplicity
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument(f"user-agent={ua}")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                driver = webdriver.Chrome(executable_path=config["CHROMEDRIVER_PATH"]) if config["CHROMEDRIVER_PATH"] else webdriver.Chrome(options=options)
                status, error = make_request_selenium(driver, url)
                if driver:
                    # do not close immediately to simulate reading; but close for resource control
                    driver.quit()
            except Exception as e:
                status, error = None, str(e)
        else:
            status, error = make_request_requests(url, headers, proxy=proxy, timeout=config["REQUEST_TIMEOUT"])

        # dwell time
        dwell = random.uniform(* (config["DWELL_BOT"] if is_bot else config["DWELL_NORMAL"]))
        # log row
        note = "bot" if is_bot else "human_like"
        row = [timestamp, session_id, seq, url, status or "", ua, ref, proxy or "", round(dwell,3), error or note]
        append_csv_row(config["LOG_CSV"], row)
        if config["VERBOSE"]:
            print(f"[{timestamp}] session={session_id[:8]} seq={seq}/{pageviews} url={url} status={status} proxy={proxy} dwell={dwell:.2f} note={note}")
        time.sleep(dwell)  # simulate time-on-page

def run_simulation(config):
    write_csv_header(config["LOG_CSV"])
    proxies = load_proxies(config["PROXY_FILE"])
    threads = []
    for i in range(config["CONCURRENT_SESSIONS"]):
        t = threading.Thread(target=simulate_session, args=(i, config, proxies))
        threads.append(t)
        t.start()
        # stagger session starts a bit
        time.sleep(random.uniform(0.1, 1.0))
    for t in threads:
        t.join()

# --------------------------
# CLI
# --------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Synthetic traffic simulator (for testing only).")
    p.add_argument("--concurrent", type=int, help="number of concurrent sessions", default=None)
    p.add_argument("--sessions", type=int, help="alias for concurrent", default=None)
    p.add_argument("--visits", type=int, help="max pageviews per session (overrides PAGEVIEWS_RANGE both min,max)", default=None)
    p.add_argument("--proxy-file", type=str, help="file with proxies, one per line", default=None)
    p.add_argument("--bot-ratio", type=float, help="fraction of sessions that behave bot-like (0-1)", default=None)
    p.add_argument("--selenium", action="store_true", help="use Selenium headless mode (requires chromedriver and selenium installed)")
    p.add_argument("--no-verbose", action="store_true", help="disable console prints")
    return p.parse_args()

def main():
    args = parse_args()
    config = CONFIG.copy()
    if args.concurrent:
        config["CONCURRENT_SESSIONS"] = args.concurrent
    if args.sessions:
        config["CONCURRENT_SESSIONS"] = args.sessions
    if args.visits:
        config["PAGEVIEWS_RANGE"] = (1, args.visits)
    if args.proxy_file:
        config["PROXY_FILE"] = args.proxy_file
    if args.bot_ratio is not None:
        config["BOT_RATIO"] = args.bot_ratio
    if args.selenium:
        if not USE_SELENIUM:
            print("Selenium not available in this environment. Install selenium & chromedriver to use this option.")
            return
        config["USE_SELENIUM"] = True
    if args.no_verbose:
        config["VERBOSE"] = False

    print("Starting simulator with config:")
    for k,v in config.items():
        if k != "USER_AGENTS" and k != "REFERRERS":
            print(f"  {k}: {v}")
    print(f"  TARGET_URLS: {config['TARGET_URLS']}")
    run_simulation(config)
    print("Simulation finished. Log written to:", config["LOG_CSV"])

if __name__ == "__main__":
    main()
