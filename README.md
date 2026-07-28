# Jersey Stock Checker

A simple desktop app that watches online stores for a product and **alerts you
the moment your size comes back in stock** — so you don't have to sit there
refreshing pages. It pops up an on-screen alert with a link to buy, rings a
bell, and can optionally **text or email you** when you're away from the
computer.

It was built to chase a sold-out World Cup jersey across a dozen sites, but it
works for anything — just point it at the product pages you care about.

Under the hood it uses [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)
(a stealth [Playwright](https://playwright.dev/) fork) so anti-bot systems on
big retail sites don't block it.

![status: personal-use tool](https://img.shields.io/badge/use-personal-blue)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

---

## Get it running

There are two ways: download a prebuilt app (easiest), or run from source.

### Option A — Download the app (Windows, no Python needed)

1. Go to the [**Releases**](../../releases) page and download
   `JerseyChecker-Windows.zip`.
2. Unzip it anywhere (Desktop is fine).
3. Open `config.json` in Notepad and set what you want to watch (see
   [Configuration](#configuration)).
4. Double-click `JerseyChecker.exe`.

> Windows may show a SmartScreen warning because the app isn't code-signed.
> Click **More info → Run anyway**. (It's an open-source app you can inspect and
> build yourself.) Some antivirus tools flag PyInstaller apps as a false
> positive; if that happens, build from source instead.

### Option B — Build the app yourself (Windows)

1. Install [Python](https://www.python.org/downloads/). On the first installer
   screen, **check "Add python.exe to PATH."**
2. Download this repo (green **Code** button → Download ZIP) and unzip it.
3. Double-click **`build_exe.bat`**. It installs everything, downloads the
   browser, and builds the app. When it says **DONE**, your app is in
   `dist\JerseyChecker\`.
4. Double-click `dist\JerseyChecker\JerseyChecker.exe`.

### Option C — Run from source (Windows / macOS / Linux)

```bash
pip install -r requirements.txt
patchright install chromium
python jersey_checker.py
```

On macOS/Linux you can instead run `./run.sh`.

---

## Using the app

1. Set your **Size** and how often to check (**Every N sec**).
2. Press **Start**. Leave the window open (minimizing is fine).
3. Each pass logs every site as ✅ available / ❌ not available / ⚠️ unknown.
4. When your size appears, you get a bell, a pop-up with a **buy link**, and (if
   configured) a text/email.

Press **Test Alert** any time to confirm the pop-up and text/email work without
waiting for a real restock.

---

## Configuration

Everything the app watches lives in **`config.json`** (next to the app / exe).
You don't edit code. Copy `config.example.json` to `config.json` and adjust.

```json
{
  "size": "XL",
  "interval_seconds": 180,
  "email": {
    "enabled": false,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "from": "youraddress@gmail.com",
    "password": "your-16-char-app-password",
    "to": "youraddress@gmail.com"
  },
  "targets": [
    {
      "name": "Nike — Stadium Home",
      "kind": "nike",
      "url": "https://www.nike.com/t/....../IB5316-673"
    }
  ]
}
```

### Fields

- **size** — the size to hunt for: `S`, `M`, `L`, `XL`, `2XL`, `3XL`.
  (`XXL`/`2XL` are treated the same.)
- **interval_seconds** — seconds between checks. `180` (3 min) is a good,
  polite default. Don't go much below `60` — hammering sites can get your IP
  temporarily blocked.
- **email** — optional alerts (see below).
- **targets** — the list of things to watch. Each has a `name` (anything you
  like), a `url`, and a `kind` that selects how it's checked.

### `kind` — how each site is checked

| kind       | use for                                                                 |
|------------|-------------------------------------------------------------------------|
| `shopify`  | Any Shopify store. **Most reliable** — reads the store's JSON feed.      |
| `nike`     | Nike.com product pages.                                                  |
| `fanatics` | Fanatics and Fanatics-owned sites (e.g. FansEdge).                       |
| `scheels`  | Scheels — waits and double-confirms to avoid a load-time flicker.        |
| `generic`  | Anything else (incl. WooCommerce). Best-effort: reads size buttons, else the page's in/out-of-stock text. |

Not sure? Try `shopify` if the URL has `?variant=` or `/products/` in it;
otherwise use `generic`. If a site reports ⚠️ unknown, it may need a dedicated
checker — [open an issue](../../issues).

---

## Text / email alerts (optional)

So you're notified even away from the keyboard.

1. In `config.json`, set `email.enabled` to `true`.
2. **Gmail:** create an **App Password** (a normal password won't work over
   SMTP): https://myaccount.google.com/apppasswords — put it in `password`.
3. Set `from` to your Gmail and `to` to where alerts should go.

**Want a text instead of an email?** Set `to` to your carrier's email-to-SMS
gateway:

| Carrier   | Address (use your number) |
|-----------|---------------------------|
| Verizon / Visible | `5551234567@vtext.com` |
| T-Mobile  | `5551234567@tmomail.net`  |
| AT&T      | `5551234567@txt.att.net`  |
| Google Fi | `5551234567@msg.fi.google.com` |

> Carrier SMS gateways can be flaky (some carriers throttle them). If texts
> don't arrive reliably, a push service like [ntfy](https://ntfy.sh/) or
> Pushover is more dependable — PRs welcome to add that.

⚠️ **Security:** `config.json` holds your app password. Don't commit a
`config.json` with real credentials to a public repo. Keep it local, or keep
your fork private.

---

## How it works

The app opens each product page (or, for Shopify, its JSON feed) on a timer in a
stealth browser, decides whether your size is purchasable, and fires an alert
when it flips to available. Checks run a few at a time so watching many sites
stays quick. See `jersey_checker.py` — it's a single readable file.

---

## Contributing

Issues and PRs welcome — especially new `kind` checkers for stores that don't
work with the existing ones, or a push-notification alert option. Please keep it
friendly and personal-use focused.

---

## Please use this responsibly

This checks **publicly visible** product pages for **personal use** — the same
info you'd see refreshing the page yourself, just automated. Keep the interval
reasonable, don't run many copies in parallel, and **don't use it to bulk-buy or
resell**. Respect each site's Terms of Service. This tool is provided as-is,
with no warranty (see [LICENSE](LICENSE)).

---

## License

MIT — see [LICENSE](LICENSE).
