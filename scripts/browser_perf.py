#!/usr/bin/env python3
"""Measure ten cold Mini App loads; requires Playwright and a running dev server."""
import statistics
import sys
import time
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/app/mvp.html"
samples = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for _ in range(10):
        page = browser.new_page(); started = time.perf_counter(); page.goto(url)
        page.wait_for_selector('body[data-load="ready"]', timeout=10_000)
        samples.append((time.perf_counter() - started) * 1000); page.close()
    browser.close()
p95 = sorted(samples)[9]
print(f"cold ready p50={statistics.median(samples):.1f}ms p95={p95:.1f}ms (10 runs)")
raise SystemExit(1 if p95 > 2500 else 0)
