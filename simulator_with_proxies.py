#!/usr/bin/env python3
"""
simulator_with_proxies.py

Synthetic traffic simulator with proxy rotation + proxy health checks.
Only run against servers you are authorized to test.
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
from queue import Queue

# ---------------- CONFIG ----------------
TARGET_URLS = [
    "https://makegameblog.vercel.app/",
    "https://makegameblog.vercel.app/about",
    "https://makegameblog.vercel.app/posts/devlog-2-can-phong-bat-dau-co-hoi-tho",
    "https://makegameblog.vercel.app/posts/ngay-dau-tien-tai-vai-studio",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
    "python-requests/2.28.1",
    "curl/7.81.0",
]
REFERRERS = [
    "https://www.google.com/",
    "https://www.facebook.com/",
    "https://t.me/example",
    "",
]
DWELL_NORMAL = (4.0, 20.0)
DWELL_BOT = (0.2, 2.0)
BOT_RATIO = 0.0
LOG_CSV = "traffic_log.csv"
CONCURRENT_SESSIONS = 20
PAGEVIEWS_RANGE = (3, 10)
REQUEST_TIMEOUT = 10
PROXY_FILE = "proxies.txt"   # default proxy file name
PROXY_CHECK_TIMEOUT = 6
PROXY_RETRY_LIMIT = 3       # retries per request before skipping
VERBOSE = True
# ----------------------------------------

lock = threading.Lock()

def write_csv_header(path):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp","session_id","seq","url","status_code","user_agent",
                "referrer","proxy","dwell_seconds","note","error"
            ])

def append_csv_row(path, row):
    with lock:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

def load_proxies(proxy_file):
    if not proxy_file or not os.path.exists(proxy_file):
        return []
    proxies = []
    with open(proxy_file, "r", encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if p and not p.startswith("#"):
                proxies.append(p)
    return proxies

def check_proxy(proxy_url):
    """Quick health-check: try a HEAD request to example.com through proxy."""
    test_url = "http://httpbin.org/get"
    try:
        r = requests.get(test_url, proxies={"http": proxy_url, "https": proxy_url}, timeout=PROXY_CHECK_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False

class ProxyPool:
    """Thread-safe rotating proxy pool with basic health state."""
    def __init__(self, proxies):
        self.lock = threading.Lock()
        self.proxies = proxies[:]  # list of proxy strings
        self.dead = {}  # proxy -> recover_time

    def get(self):
        with self.lock:
            # discard dead proxies which are scheduled to revive later
            now = time.time()
            available = [p for p in self.proxies if p not in self.dead or self.dead[p] <= now]
            if not available:
                return None
            # random choice for rotation
            return random.choice(available)

    def mark_dead(self, proxy, backoff_seconds=60):
        with self.lock:
            self.dead[proxy] = time.time() + backoff_seconds

def request_with_retries(url, headers, proxy_pool):
    proxy = proxy_pool.get() if proxy_pool else None
    attempt = 0
    backoff_base = 1.5
    last_error = None
    while attempt < PROXY_RETRY_LIMIT:
        attempt += 1
        if proxy:
            proxies_dict = {"http": proxy, "https": proxy}
        else:
            proxies_dict = None
        try:
            r = requests.get(url, headers=headers, proxies=proxies_dict, timeout=REQUEST_TIMEOUT)
            return r.status_code, None, proxy
        except Exception as e:
            last_error = str(e)
            # mark proxy dead and pick a new one
            if proxy and proxy_pool:
                # increasing backoff
                backoff = int(backoff_base ** attempt) * 5
                proxy_pool.mark_dead(proxy, backoff_seconds=backoff)
                if VERBOSE:
                    print(f"[proxy] marking dead {proxy} for {backoff}s due to error: {e}")
            proxy = proxy_pool.get() if proxy_pool else None
            sleep_t = random.uniform(0.5, 1.5) * attempt
            time.sleep(sleep_t)
    return None, last_error, proxy

def simulate_session(session_idx, config, proxy_pool):
    session_id = str(uuid.uuid4())
    pageviews = random.randint(config["PAGEVIEWS_RANGE"][0], config["PAGEVIEWS_RANGE"][1])
    is_bot = random.random() < config["BOT_RATIO"]
    for seq in range(1, pageviews+1):
        url = random.choice(config["TARGET_URLS"])
        ua = random.choice(config["USER_AGENTS"])
        ref = random.choice(config["REFERRERS"])
        headers = {"User-Agent": ua}
        if ref:
            headers["Referer"] = ref
        timestamp = datetime.utcnow().isoformat()

        status, error, used_proxy = request_with_retries(url, headers, proxy_pool)

        dwell = random.uniform(* (config["DWELL_BOT"] if is_bot else config["DWELL_NORMAL"]))
        note = "bot" if is_bot else "human_like"
        row = [timestamp, session_id, seq, url, status or "", ua, ref, used_proxy or "", round(dwell,3), note, error or ""]
        append_csv_row(config["LOG_CSV"], row)
        if config["VERBOSE"]:
            print(f"[{timestamp}] session={session_id[:8]} seq={seq}/{pageviews} url={url} status={status} proxy={used_proxy} dwell={dwell:.2f} note={note} err={error}")
        time.sleep(dwell)

def run_simulation(config):
    write_csv_header(config["LOG_CSV"])
    proxies = load_proxies(config["PROXY_FILE"])
    # create proxy pool and pre-check proxies
    proxy_pool = None
    if proxies:
        good = []
        if VERBOSE:
            print(f"[proxy] Checking {len(proxies)} proxies (timeout {PROXY_CHECK_TIMEOUT}s each)...")
        for p in proxies:
            ok = check_proxy(p)
            if ok:
                good.append(p)
                if VERBOSE:
                    print(f"[proxy] OK: {p}")
            else:
                if VERBOSE:
                    print(f"[proxy] BAD: {p}")
        if not good:
            print("No healthy proxies found; continuing without proxies.")
            proxy_pool = None
        else:
            proxy_pool = ProxyPool(good)
            if VERBOSE:
                print(f"[proxy] {len(good)} proxies available after check.")
    else:
        if VERBOSE:
            print("[proxy] No proxy file found, running direct requests.")
        proxy_pool = None

    threads = []
    for i in range(config["CONCURRENT_SESSIONS"]):
        t = threading.Thread(target=simulate_session, args=(i, config, proxy_pool))
        threads.append(t)
        t.start()
        time.sleep(random.uniform(0.05, 1.0))

    for t in threads:
        t.join()

# ---------------- CLI ----------------
def parse_args():
    p = argparse.ArgumentParser(description="Simulator with proxy rotation.")
    p.add_argument("--concurrent", type=int, default=CONCURRENT_SESSIONS)
    p.add_argument("--proxy-file", type=str, default=PROXY_FILE)
    p.add_argument("--bot-ratio", type=float, default=BOT_RATIO)
    p.add_argument("--visits-min", type=int, default=PAGEVIEWS_RANGE[0])
    p.add_argument("--visits-max", type=int, default=PAGEVIEWS_RANGE[1])
    p.add_argument("--log", type=str, default=LOG_CSV)
    p.add_argument("--no-verbose", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    config = {
        "TARGET_URLS": TARGET_URLS,
        "USER_AGENTS": USER_AGENTS,
        "REFERRERS": REFERRERS,
        "DWELL_NORMAL": DWELL_NORMAL,
        "DWELL_BOT": DWELL_BOT,
        "BOT_RATIO": args.bot_ratio,
        "LOG_CSV": args.log,
        "CONCURRENT_SESSIONS": args.concurrent,
        "PAGEVIEWS_RANGE": (args.visits_min, args.visits_max),
        "REQUEST_TIMEOUT": REQUEST_TIMEOUT,
        "PROXY_FILE": args.proxy_file,
        "VERBOSE": not args.no_verbose,
    }
    if not config["VERBOSE"]:
        global VERBOSE
        VERBOSE = False

    print("Starting simulation with config:")
    print(f"  concurrent: {config['CONCURRENT_SESSIONS']}, visits range: {config['PAGEVIEWS_RANGE']}, bot_ratio: {config['BOT_RATIO']}")
    print(f"  proxy_file: {config['PROXY_FILE']}, log: {config['LOG_CSV']}")
    run_simulation(config)
    print("Done. Log:", config["LOG_CSV"])

if __name__ == "__main__":
    main()
