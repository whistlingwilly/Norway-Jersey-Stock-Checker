#!/usr/bin/env python3
"""
Jersey Stock Checker (GUI)
==========================
A double-clickable desktop app that watches online stores for a product/size
and alerts you the moment it comes back in stock — so you don't have to keep
refreshing. It can pop up an on-screen alert, ring a bell, and optionally send
you a text or email.

It uses Patchright (a stealth Playwright fork) so anti-bot systems on big
retail sites don't block it.

WHAT TO WATCH lives in config.json (sits next to this file / the .exe). You do
NOT need to edit code to add stores or change your size — just edit that file.
See config.example.json and the README for the format.

Build a standalone .exe with build_exe.bat (Windows). See README.md.
"""

import os
import sys
import json

# When packaged as an .exe, look for the bundled browser sitting next to the
# executable (the build copies it into an ms-playwright folder there).
# This must run BEFORE importing patchright.
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
    _browsers = os.path.join(_base, "ms-playwright")
    if os.path.isdir(_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers

import asyncio
import random
import smtplib
import threading
import queue
from datetime import datetime
from email.message import EmailMessage

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from patchright.async_api import async_playwright


# ============================================================================
# Config loading
# ============================================================================

def _app_dir():
    """Folder where config.json is expected: next to the exe when frozen,
    otherwise next to this script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_app_dir(), "config.json")

# Built-in fallback so the app still runs if config.json is missing.
DEFAULT_CONFIG = {
    "size": "XL",
    "interval_seconds": 180,
    "email": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "from": "youraddress@gmail.com",
        "password": "your-16-char-app-password",
        "to": "youraddress@gmail.com",
    },
    "targets": [
        {
            "name": "Example — Nike Norway Stadium Home",
            "kind": "nike",
            "url": "https://www.nike.com/t/norway-national-team-2026-stadium-home-mens-dri-fit-soccer-jersey-XFHheFPZ/IB5316-673",
        }
    ],
}


def load_config():
    """Read config.json; fall back to DEFAULT_CONFIG if missing/broken.
    Returns (config_dict, warning_message_or_None)."""
    if not os.path.exists(CONFIG_PATH):
        return DEFAULT_CONFIG, (
            f"config.json not found next to the app.\n"
            f"Using a built-in example. To customize what's watched, create:\n"
            f"{CONFIG_PATH}\n(see config.example.json)."
        )
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        return DEFAULT_CONFIG, (
            f"config.json couldn't be read ({e}).\n"
            f"Using a built-in example instead. Fix the file and restart."
        )

    # Merge onto defaults so missing keys don't crash anything.
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update({k: v for k, v in cfg.items() if k != "email"})
    if isinstance(cfg.get("email"), dict):
        merged["email"].update(cfg["email"])
    if not merged.get("targets"):
        merged["targets"] = DEFAULT_CONFIG["targets"]
    return merged, None


_CFG, CONFIG_WARNING = load_config()

# Module-level globals the rest of the app uses.
DEFAULT_SIZE = str(_CFG.get("size", "XL")).upper()
DEFAULT_INTERVAL = int(_CFG.get("interval_seconds", 180))

_e = _CFG.get("email", {})
EMAIL = {
    "ENABLED": bool(_e.get("enabled", False)),
    "SMTP_HOST": _e.get("smtp_host", "smtp.gmail.com"),
    "SMTP_PORT": int(_e.get("smtp_port", 587)),
    "FROM": _e.get("from", ""),
    "PASSWORD": _e.get("password", ""),
    "TO": _e.get("to", ""),
}

TARGETS = _CFG.get("targets", [])


# ============================================================================
# Size helpers
# ============================================================================

def size_matches(a: str, b: str) -> bool:
    norm = lambda s: s.upper().replace(" ", "").replace("XXL", "2XL").replace("XXXL", "3XL")
    return norm(a) == norm(b)


# ============================================================================
# Browser + per-site checkers  (return dict: name,url,in_stock,sizes,note)
# ============================================================================

async def new_context(pw):
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    return browser, context


async def check_shopify(context, target, size):
    page = await context.new_page()
    try:
        js_url = target["url"].split("?")[0] + ".js"
        await page.goto(js_url, wait_until="domcontentloaded", timeout=30000)
        body = await page.evaluate("() => document.body.innerText")
        data = json.loads(body)
        available, hit = [], False
        for v in data.get("variants", []):
            label = str(v.get("option1") or v.get("title") or "")
            if v.get("available"):
                available.append(label)
                if size_matches(label, size):
                    hit = True
        return dict(name=target["name"], url=target["url"], in_stock=hit,
                    sizes=available, note="Shopify .js")
    except Exception as e:
        return dict(name=target["name"], url=target["url"], in_stock=None,
                    sizes=[], note=f"error: {e}")
    finally:
        await page.close()


async def check_fanatics(context, target, size):
    page = await context.new_page()
    try:
        await page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(random.randint(2500, 4500))
        overall = await page.evaluate(
            "() => { const m = document.querySelector('meta[property=\"og:availability\"]');"
            " return m ? m.content : null; }"
        )
        sizes = await page.evaluate(r"""
            () => {
              const out = [];
              const nodes = Array.from(document.querySelectorAll('button, [role=button]'));
              for (const n of nodes) {
                const t = (n.innerText || '').trim();
                if (/^(S|M|L|XL|2XL|3XL|XXL|XXXL)$/i.test(t)) {
                  const disabled = n.disabled
                    || n.getAttribute('aria-disabled') === 'true'
                    || /out of stock|sold out/i.test(n.getAttribute('aria-label') || '')
                    || n.className.toLowerCase().includes('disabled')
                    || n.className.toLowerCase().includes('unavailable');
                  out.push({ size: t, available: !disabled });
                }
              }
              return out;
            }
        """)
        available = [s["size"] for s in sizes if s["available"]]
        hit = any(s["available"] and size_matches(s["size"], size) for s in sizes)
        if not sizes and overall:
            return dict(name=target["name"], url=target["url"],
                        in_stock=("in stock" in overall.lower()),
                        sizes=[], note=f"meta only: {overall}")
        return dict(name=target["name"], url=target["url"], in_stock=hit,
                    sizes=available, note=f"og:availability={overall}")
    except Exception as e:
        return dict(name=target["name"], url=target["url"], in_stock=None,
                    sizes=[], note=f"error: {e}")
    finally:
        await page.close()


async def check_nike(context, target, size):
    page = await context.new_page()
    try:
        await page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(random.randint(3000, 5000))
        sizes = await page.evaluate(r"""
            () => {
              const out = [];
              const labels = Array.from(document.querySelectorAll('label, button'));
              for (const el of labels) {
                const t = (el.innerText || el.textContent || '').trim();
                if (/^(S|M|L|XL|2XL|3XL|XXL|XXXL)$/i.test(t)) {
                  let disabled = false;
                  const input = el.querySelector('input') ||
                    document.getElementById(el.getAttribute('for') || '');
                  if (input) disabled = input.disabled;
                  if (el.tagName === 'BUTTON') disabled = disabled || el.disabled;
                  disabled = disabled
                    || el.getAttribute('aria-disabled') === 'true'
                    || el.className.toLowerCase().includes('disabled');
                  out.push({ size: t, available: !disabled });
                }
              }
              return out;
            }
        """)
        available = [s["size"] for s in sizes if s["available"]]
        hit = any(s["available"] and size_matches(s["size"], size) for s in sizes)
        if not sizes:
            txt = (await page.evaluate("() => document.body.innerText")).lower()
            return dict(name=target["name"], url=target["url"],
                        in_stock=("sold out" not in txt and "coming soon" not in txt),
                        sizes=[], note="text fallback")
        return dict(name=target["name"], url=target["url"], in_stock=hit,
                    sizes=available, note="size grid")
    except Exception as e:
        return dict(name=target["name"], url=target["url"], in_stock=None,
                    sizes=[], note=f"error: {e}")
    finally:
        await page.close()


async def check_generic(context, target, size):
    """
    General-purpose checker for stores without a special strategy (e.g. Scheels).
    Loads the page, waits for it to hydrate, then:
      1. tries to read size buttons/labels and match the wanted size, else
      2. falls back to whole-page text: if it says 'out of stock'/'sold out'
         the product is unavailable, otherwise it's treated as available.
    Note: some of these pages are per-size variant URLs, in which case the
    page-level out-of-stock text is the reliable signal.
    """
    page = await context.new_page()
    try:
        await page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(random.randint(3000, 5000))

        sizes = await page.evaluate(r"""
            () => {
              const out = [];
              const els = Array.from(document.querySelectorAll('button, label, [role=button], a'));
              for (const el of els) {
                const t = (el.innerText || el.textContent || '').trim();
                if (/^(S|M|L|XL|2XL|3XL|XXL|XXXL)$/i.test(t)) {
                  const cls = (el.className || '').toString().toLowerCase();
                  const disabled = el.disabled
                    || el.getAttribute('aria-disabled') === 'true'
                    || /out of stock|sold out|unavailable/i.test(el.getAttribute('aria-label') || '')
                    || cls.includes('disabled') || cls.includes('unavailable')
                    || cls.includes('soldout') || cls.includes('out-of-stock');
                  out.push({ size: t, available: !disabled });
                }
              }
              return out;
            }
        """)

        if sizes:
            available = [s["size"] for s in sizes if s["available"]]
            hit = any(s["available"] and size_matches(s["size"], size) for s in sizes)
            return dict(name=target["name"], url=target["url"], in_stock=hit,
                        sizes=available, note="size grid")

        # Fallback: page-level stock text.
        txt = (await page.evaluate("() => document.body.innerText")).lower()
        out_of_stock = ("out of stock" in txt or "sold out" in txt
                        or "currently unavailable" in txt)
        return dict(name=target["name"], url=target["url"],
                    in_stock=(not out_of_stock), sizes=[],
                    note="page text (no size grid found)")
    except Exception as e:
        return dict(name=target["name"], url=target["url"], in_stock=None,
                    sizes=[], note=f"error: {e}")
    finally:
        await page.close()


async def check_scheels(context, target, size):
    """
    Scheels renders the page showing the product as available for a moment, then
    flips to 'Sold Out' once its JavaScript finishes. To avoid that false
    trigger, we: (1) wait several seconds for the page to fully settle, then
    (2) read stock TWICE a couple seconds apart, and only report 'in stock' if
    BOTH reads agree. Any disagreement or any 'sold out' text = not available.
    """
    page = await context.new_page()

    async def read_state():
        # Try size grid first; fall back to page-level sold-out text.
        sizes = await page.evaluate(r"""
            () => {
              const out = [];
              const els = Array.from(document.querySelectorAll('button, label, [role=button], a'));
              for (const el of els) {
                const t = (el.innerText || el.textContent || '').trim();
                if (/^(S|M|L|XL|2XL|3XL|XXL|XXXL)$/i.test(t)) {
                  const cls = (el.className || '').toString().toLowerCase();
                  const disabled = el.disabled
                    || el.getAttribute('aria-disabled') === 'true'
                    || /out of stock|sold out|unavailable/i.test(el.getAttribute('aria-label') || '')
                    || cls.includes('disabled') || cls.includes('unavailable')
                    || cls.includes('soldout') || cls.includes('out-of-stock');
                  out.push({ size: t, available: !disabled });
                }
              }
              const txt = (document.body.innerText || '').toLowerCase();
              const soldOut = txt.includes('sold out') || txt.includes('out of stock')
                              || txt.includes('currently unavailable');
              return { sizes: out, soldOut: soldOut };
            }
        """)
        return sizes

    try:
        await page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        # Let the available->sold-out flip fully settle before reading anything.
        await page.wait_for_timeout(6000)

        first = await read_state()
        await page.wait_for_timeout(2500)
        second = await read_state()

        def verdict(state):
            if state["soldOut"]:
                return False, []
            if state["sizes"]:
                avail = [s["size"] for s in state["sizes"] if s["available"]]
                hit = any(s["available"] and size_matches(s["size"], size)
                          for s in state["sizes"])
                return hit, avail
            # no size grid and no sold-out text -> treat as unknown-but-available
            return True, []

        v1, avail1 = verdict(first)
        v2, avail2 = verdict(second)

        # Only report available if BOTH reads say available.
        if v1 and v2:
            return dict(name=target["name"], url=target["url"], in_stock=True,
                        sizes=avail2 or avail1, note="double-confirmed")
        return dict(name=target["name"], url=target["url"], in_stock=False,
                    sizes=[], note="settled to sold out")
    except Exception as e:
        return dict(name=target["name"], url=target["url"], in_stock=None,
                    sizes=[], note=f"error: {e}")
    finally:
        await page.close()


CHECKERS = {
    "shopify": check_shopify,
    "fanatics": check_fanatics,
    "nike": check_nike,
    "generic": check_generic,
    "scheels": check_scheels,
}


async def run_once(size, concurrency=3):
    """Check all targets, running up to `concurrency` at a time so a sweep of
    many sites stays reasonably quick. Results are returned in TARGETS order."""
    results = [None] * len(TARGETS)
    async with async_playwright() as pw:
        browser, context = await new_context(pw)
        try:
            sem = asyncio.Semaphore(concurrency)

            async def one(i, target):
                async with sem:
                    # small stagger so we don't hit sites in perfect lockstep
                    await asyncio.sleep(random.uniform(0.2, 1.5))
                    results[i] = await CHECKERS[target["kind"]](context, target, size)

            await asyncio.gather(*(one(i, t) for i, t in enumerate(TARGETS)))
        finally:
            await context.close()
            await browser.close()
    return results


# ============================================================================
# Alerts
# ============================================================================

def send_email(subject, body):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL["FROM"]
        msg["To"] = EMAIL["TO"]
        msg.set_content(body)
        with smtplib.SMTP(EMAIL["SMTP_HOST"], EMAIL["SMTP_PORT"]) as s:
            s.starttls()
            s.login(EMAIL["FROM"], EMAIL["PASSWORD"])
            s.send_message(msg)
        return True
    except Exception:
        return False


# ============================================================================
# Worker thread — runs the async checks without freezing the window
# ============================================================================

class Worker(threading.Thread):
    def __init__(self, size, interval, msg_q):
        super().__init__(daemon=True)
        self.size = size
        self.interval = interval
        self.q = msg_q
        self._stop = threading.Event()
        self.alerted = set()

    def stop(self):
        self._stop.set()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while not self._stop.is_set():
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.q.put(("log", f"\n[{stamp}] checking for size {self.size} ..."))
            try:
                results = loop.run_until_complete(run_once(self.size))
                for r in results:
                    if r["in_stock"] is True:
                        badge = f"✅ {self.size} AVAILABLE"
                    elif r["in_stock"] is False:
                        badge = "❌ not available"
                    else:
                        badge = "⚠️ unknown"
                    extra = f"  (sizes: {', '.join(r['sizes'])})" if r["sizes"] else ""
                    self.q.put(("log", f"   {badge:20} {r['name']}{extra}"))
                    if r["in_stock"] and r["url"] not in self.alerted:
                        self.alerted.add(r["url"])
                        self.q.put(("alert", r))
                        if EMAIL["ENABLED"]:
                            ok = send_email(
                                f"[Jersey] {self.size} in stock — {r['name']}",
                                f"{r['name']}\n{r['url']}")
                            self.q.put(("log", "   ↳ email sent" if ok else "   ↳ email failed"))
                    if not r["in_stock"]:
                        self.alerted.discard(r["url"])
            except Exception as e:
                self.q.put(("log", f"   sweep error: {e}"))
            # sleep in small slices so Stop is responsive
            waited = 0
            total = self.interval + random.uniform(-15, 15)
            while waited < total and not self._stop.is_set():
                self._stop.wait(1)
                waited += 1
        self.q.put(("log", "\nStopped."))
        self.q.put(("stopped", None))


# ============================================================================
# GUI
# ============================================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jersey Stock Checker — Haaland Norway")
        self.geometry("760x620")
        self.minsize(620, 420)
        self.worker = None
        self.q = queue.Queue()

        pad = {"padx": 8, "pady": 6}
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Size:").pack(side="left")
        self.size_var = tk.StringVar(value=DEFAULT_SIZE)
        ttk.Combobox(top, textvariable=self.size_var, width=6, state="readonly",
                     values=["S", "M", "L", "XL", "2XL", "3XL"]).pack(side="left", padx=(4, 16))

        ttk.Label(top, text="Every (sec):").pack(side="left")
        self.interval_var = tk.StringVar(value=str(DEFAULT_INTERVAL))
        ttk.Entry(top, textvariable=self.interval_var, width=7).pack(side="left", padx=(4, 16))

        self.start_btn = ttk.Button(top, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(top, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.test_btn = ttk.Button(top, text="Test Alert", command=self.test_alert)
        self.test_btn.pack(side="left", padx=4)

        self.status = ttk.Label(self, text="Idle. Press Start.", anchor="w",
                                foreground="#555")
        self.status.pack(fill="x", padx=8)

        self.log = scrolledtext.ScrolledText(self, wrap="word", height=20,
                                             font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self.log.configure(state="disabled")

        names = ", ".join(t.get("name", "?") for t in TARGETS) or "(none configured)"
        self._log(f"Watching {len(TARGETS)} item(s): {names}")
        self._log("Set your size and press Start. Leave this window open.\n")
        if CONFIG_WARNING:
            self._log("NOTE: " + CONFIG_WARNING + "\n")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self.poll_queue)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        try:
            interval = max(30, int(self.interval_var.get()))
        except ValueError:
            interval = DEFAULT_INTERVAL
            self.interval_var.set(str(interval))
        size = self.size_var.get().upper()
        self.worker = Worker(size, interval, self.q)
        self.worker.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text=f"Watching for {size} every {interval}s...",
                              foreground="#0a7")

    def stop(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Stopping...", foreground="#a70")

    def test_alert(self):
        """Fire a test alert: always shows the on-screen popup/bell, and if
        email is enabled, also sends the real text so you can confirm it works.
        The email send runs on a background thread so the window never freezes."""
        # on-screen part (instant)
        test_url = TARGETS[0]["url"] if TARGETS else "https://example.com"
        fake = {"name": "TEST ALERT — this is only a test",
                "url": test_url}
        self.raise_alert(fake)

        if not EMAIL["ENABLED"]:
            self._log("Test alert shown. (Email/text is OFF — set EMAIL "
                      "ENABLED=True and rebuild to also get a text.)")
            return

        self._log("Sending test text/email ...")
        self.test_btn.configure(state="disabled")

        def worker():
            ok = send_email("Jersey checker TEST",
                            "Test alert - if you got this, your alerts work.")
            self.q.put(("log", "   ↳ test sent — check your phone in a minute"
                        if ok else
                        "   ↳ test FAILED to send — check the EMAIL settings "
                        "(address / app password / no spaces)"))
            self.q.put(("test_done", None))

        threading.Thread(target=worker, daemon=True).start()

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "alert":
                    self.raise_alert(payload)
                elif kind == "stopped":
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status.configure(text="Idle. Press Start.", foreground="#555")
                elif kind == "test_done":
                    self.test_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(200, self.poll_queue)

    def raise_alert(self, r):
        # bell, bring window to front, popup
        try:
            self.bell()
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(3000, lambda: self.attributes("-topmost", False))

        # Capture the URL NOW (not at click time) so the button always opens
        # the right page even if several popups appear.
        url = r["url"]

        def open_url(event=None):
            import webbrowser, subprocess, sys
            opened = False
            try:
                opened = webbrowser.open(url, new=2)
            except Exception:
                opened = False
            # Fallback for Windows if webbrowser can't resolve a browser.
            if not opened and sys.platform.startswith("win"):
                try:
                    os.startfile(url)  # noqa: E1101 (Windows-only)
                    opened = True
                except Exception:
                    try:
                        subprocess.run(["cmd", "/c", "start", "", url], check=False)
                        opened = True
                    except Exception:
                        opened = False
            if not opened:
                self._log(f"Could not open browser automatically. "
                          f"Copy this link:\n{url}")

        win = tk.Toplevel(self)
        win.title("IN STOCK!")
        win.geometry("500x230")
        ttk.Label(win, text=f"🎉 {self.size_var.get()} is IN STOCK",
                  font=("Segoe UI", 14, "bold")).pack(pady=(16, 4))
        ttk.Label(win, text=r["name"], font=("Segoe UI", 10)).pack()

        # A real button is more reliable to click than a text label.
        ttk.Button(win, text="Open product page ▶", command=open_url).pack(pady=(12, 4))

        # Also show the raw URL so it can always be copied by hand as a backup.
        url_box = tk.Entry(win, width=64)
        url_box.insert(0, url)
        url_box.configure(state="readonly")
        url_box.pack(pady=4)

        def copy_url():
            self.clipboard_clear()
            self.clipboard_append(url)
            self._log("Link copied to clipboard.")

        row = ttk.Frame(win)
        row.pack(pady=8)
        ttk.Button(row, text="Copy link", command=copy_url).pack(side="left", padx=4)
        ttk.Button(row, text="Close", command=win.destroy).pack(side="left", padx=4)

    def on_close(self):
        if self.worker:
            self.worker.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
