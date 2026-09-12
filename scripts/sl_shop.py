#!/usr/bin/env python3
"""
sl_shop.py — Second Life Marketplace shopping, productionalized for Caia & Lyra.

Choosing a skin / hair / outfit is VISUAL, and doing it by hand (fetch → parse →
download → look at images one at a time) is artisanal and slow. This makes it a
one-command capability:

    search  → fetch a category page, parse every listing, download the thumbnails,
              and composite them into ONE numbered CONTACT SHEET (a grid you Read
              at a glance, like a human scanning the storefront) + a manifest that
              maps each tile-number to {name, price L$, brand/store, rating,
              product URL, local image}.
    harvest → take a settled search URL (e.g. one Playwright navigated to after
              setting a store / sort / filters in a real browser) and paginate it
              + the next n-1 pages into per-page contact sheets with continuous
              numbering. Browser navigates → headless harvester bulk-scans; this
              is how you browse a specific maker's storefront cheaply.
    view    → hand back the full images + product URLs for the tile-numbers you like.

Why a contact sheet: reading 48 images one-by-one is expensive and blind to the
gestalt. One labelled grid = scan everything, then drill into the few that pull.

CACHE  ~/.claude/sl_shop_cache/  — SHARED family infra (like light.py /
notify.py), NOT entity-private: it's just the marketplace mirrored locally, so if
Lyra shops after Caia it's instant. Your *taste* (what you pick) lives in your own
memory, never here. Session cookie is persisted (the site 302-loops without one);
pages cached with a TTL; images are content-addressed by asset-id and cached
forever (their URLs are already cache-busted, so an id → bytes is immutable).

RUN with the pps venv (needs Pillow + curl):
    P=pps/venv/bin/python3
    $P scripts/sl_shop.py search skins
    $P scripts/sl_shop.py search skins --maturity M --query "porcelain evox"
    $P scripts/sl_shop.py view <search_id> 7 22 40
    $P scripts/sl_shop.py categories
"""
import argparse, hashlib, html, json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qsl, urlencode, urlunparse

CACHE   = Path(os.environ.get("SL_SHOP_CACHE", Path.home() / ".claude/sl_shop_cache"))
PAGES   = CACHE / "pages"
ASSETS  = CACHE / "assets"
OUT     = CACHE / "out"
COOKIES = CACHE / "cookies.txt"
UA   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
BASE = "https://marketplace.secondlife.com"
PAGE_TTL = 24 * 3600

# Seed category map. Each category's id is the `search[category_id]` in its browse
# URL; add a name→id line as you discover one. `skins` verified empirically.
CATEGORIES = {
    "skins": 106,
    # TODO (v2, one fetch each to read the id): hair, clothing, makeup, jewelry,
    # shoes, eyes, tattoos, ...  — pass a raw numeric id meanwhile.
}
MATURITY = {"G", "M", "A"}


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def fetch(url, dest, ttl=PAGE_TTL, binary=False, fresh=False):
    """Cache-aware curl with a persistent cookie jar. Returns bytes or None.
    Immutable assets (binary=True) always serve from cache when present."""
    if dest.exists() and not fresh and (binary or (time.time() - dest.stat().st_mtime) < ttl):
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + f".tmp{os.getpid()}")
    r = _run(["curl", "-sSL", "--max-redirs", "10", "-c", str(COOKIES), "-b", str(COOKIES),
              "-A", UA, "-H", "Accept-Language: en-US,en;q=0.9",
              "-o", str(tmp), "-w", "%{http_code}", url])
    code = (r.stdout or "").strip()[-3:]
    if code != "200" or not tmp.exists():
        if tmp.exists():
            tmp.unlink()
        return None
    os.replace(tmp, dest)
    return dest.read_bytes()


def _asset_id(url):
    m = re.search(r"/assets/(\d+)/", url)
    return m.group(1) if m else hashlib.sha1(url.encode()).hexdigest()[:12]


def parse_listings(text):
    """Parse the main results grid into structured rows, using each listing's
    embedded `product_dl_data` analytics object (clean name/id/price/brand)."""
    start = text.find("product-listing gallery")          # skip the featured carousel
    region = text[start:] if start >= 0 else text
    blocks = re.split(r'class="column gallery-item ', region)[1:]
    items = []
    for b in blocks:
        dl = re.search(r"product_dl_data_\d+\s*=\s*\{(.*?)\};", b, re.S)
        if not dl:
            continue
        d = dl.group(1)

        def f(k):
            m = re.search(r"'%s'\s*:\s*'(.*?)'" % k, d, re.S)
            return html.unescape(m.group(1)).strip() if m else None

        href = re.search(r'class="product-image" href="([^"]+)"', b)
        img  = re.search(r'class="product-image"[^>]*>.*?src="([^"]+)"', b, re.S)
        store = re.search(r'class="store-item">\s*(.*?)\s*</span>', b, re.S)
        rate  = re.search(r'title="([\d.]+) stars review rating"', b)
        image = img.group(1) if img else None
        if image and "Ad%20Finished" in image:            # lazy-load placeholder
            image = None
        link = href.group(1) if href else None
        items.append({
            "name": f("name"), "listing_id": f("id"), "price": f("price"),
            "brand": f("brand"), "category": f("category"),
            "store": html.unescape(store.group(1)).strip() if store else None,
            "rating": rate.group(1) if rate else None,
            "url": (BASE + link) if link and link.startswith("/") else link,
            "image": image,
        })
    return items


def contact_sheet(items, path, cols=6, tile=210, pad=8, labelh=36, start_index=0):
    from PIL import Image, ImageDraw, ImageFont
    n = max(len(items), 1)
    rows = (n + cols - 1) // cols
    cw, ch = tile + pad, tile + labelh + pad
    W, H = cols * cw + pad, rows * ch + pad
    sheet = Image.new("RGB", (W, H), (18, 16, 20))        # Hearth --bg-deep
    draw = ImageDraw.Draw(sheet)
    try:
        font  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
        fontb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except Exception:
        try:
            font = ImageFont.load_default(size=13); fontb = ImageFont.load_default(size=15)
        except TypeError:
            font = fontb = ImageFont.load_default()
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        x, y = pad + c * cw, pad + r * ch
        local = it.get("local")
        if local and Path(local).exists():
            try:
                im = Image.open(local).convert("RGB")
                im.thumbnail((tile, tile))
                sheet.paste(im, (x + (tile - im.width) // 2, y + (tile - im.height) // 2))
            except Exception:
                draw.rectangle([x, y, x + tile, y + tile], outline=(80, 70, 80))
        else:
            draw.rectangle([x, y, x + tile, y + tile], outline=(80, 70, 80))
            draw.text((x + 6, y + 6), "(no image)", fill=(120, 110, 115), font=font)
        ly = y + tile + 3
        draw.text((x + 2, ly), str(start_index + i + 1), fill=(212, 165, 116), font=fontb)  # gold number
        draw.text((x + 26, ly), (it.get("name") or "?")[:24], fill=(232, 224, 212), font=font)
        price = it.get("price")
        draw.text((x + 2, ly + 17),
                  ("L$" + price) if price else "—", fill=(126, 196, 158), font=font)  # green price
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def cmd_search(a):
    key = a.category.lower()
    cid = CATEGORIES.get(key)
    if cid is None:
        if a.category.isdigit():
            cid = int(a.category)
        else:
            sys.exit(f"unknown category {a.category!r}. known: {', '.join(CATEGORIES)} "
                     f"(or pass a numeric category id)")
    if a.maturity not in MATURITY:
        sys.exit(f"maturity must be one of {sorted(MATURITY)}")
    params = (f"search%5Bcategory_id%5D={cid}"
              f"&search%5Bmaturity_level%5D={a.maturity}"
              f"&search%5Bper_page%5D={a.per_page}"
              f"&search%5Bsort%5D={a.sort}")
    if a.query:
        params += "&search%5Bkeywords%5D=" + quote(a.query)
    if a.page > 1:
        params += f"&page={a.page}"
    url = f"{BASE}/products/search?{params}"
    sid = hashlib.sha1(url.encode()).hexdigest()[:10]

    body = fetch(url, PAGES / f"{sid}.html", ttl=PAGE_TTL, fresh=a.fresh)
    if not body:
        sys.exit("page fetch failed — retry with --fresh (the session cookie may need refreshing).")
    items = parse_listings(body.decode("utf-8", "replace"))
    if not items:
        sys.exit("parsed 0 listings — the page markup may have changed; check the cached HTML.")

    for it in items:                                       # download thumbnails (cached forever)
        if it.get("image"):
            dest = ASSETS / f"{_asset_id(it['image'])}.jpg"
            if fetch(it["image"], dest, binary=True):
                it["local"] = str(dest)

    outdir = OUT / sid
    sheet = outdir / "sheet.png"
    contact_sheet(items, sheet)
    manifest = {"search_id": sid, "url": url, "category": a.category, "maturity": a.maturity,
                "query": a.query, "fetched": time.strftime("%Y-%m-%d %H:%M"),
                "count": len(items), "sheet": str(sheet), "items": items}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1))

    print(f"search_id={sid}  {len(items)} items  category={a.category} maturity={a.maturity}"
          + (f" query={a.query!r}" if a.query else ""))
    print(f"CONTACT SHEET → {sheet}")
    print(f"manifest      → {outdir/'manifest.json'}")
    print(f"next: view {sid} <numbers>   (after Reading the sheet)")
    for i, it in enumerate(items[:12]):
        print(f"  {i+1:2}  L${(it.get('price') or '—'):>5}  {(it.get('brand') or '')[:16]:16}  "
              f"{(it.get('name') or '')[:46]}")
    if len(items) > 12:
        print(f"  … +{len(items)-12} more on the sheet")


def _set_page(url, page):
    """Return `url` with its top-level `page` query param forced to `page`
    (SL paginates search results with `&page=N`). Other params preserved."""
    parts = urlparse(url)
    q = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
    q.append(("page", str(page)))
    return urlunparse(parts._replace(query=urlencode(q)))


def cmd_harvest(a):
    """Take a settled search URL (e.g. one Playwright navigated to after setting
    store/sort/filters) and harvest it + the next n-1 pages into per-page contact
    sheets with continuous global numbering + one combined manifest. This is the
    'browser navigates → headless harvester bulk-scans' half: it closes the
    store-browse gap because it paginates whatever search URL it's handed."""
    parts = urlparse(a.url)
    if "/products/search" not in parts.path:
        print("warning: URL is not a /products/search endpoint; a store *landing* page "
              "has different markup and will likely parse to 0. Set a search/filter in "
              "the browser first, then hand over that URL.")
    start = 1
    for k, v in parse_qsl(parts.query):
        if k == "page" and v.isdigit():
            start = int(v)

    sid = hashlib.sha1(f"{a.url}|{start}|{a.pages}".encode()).hexdigest()[:10]
    outdir = OUT / sid
    all_items, sheets = [], []
    for p in range(start, start + a.pages):
        purl = _set_page(a.url, p)
        body = fetch(purl, PAGES / f"{hashlib.sha1(purl.encode()).hexdigest()[:10]}.html",
                     ttl=PAGE_TTL, fresh=a.fresh)
        if not body:
            print(f"  page {p}: fetch failed — stopping (retry with --fresh?).")
            break
        items = parse_listings(body.decode("utf-8", "replace"))
        if not items:
            print(f"  page {p}: parsed 0 listings — stopping (end of results, or not a search URL).")
            break
        for it in items:
            it["page"] = p
            if it.get("image"):
                dest = ASSETS / f"{_asset_id(it['image'])}.jpg"
                if fetch(it["image"], dest, binary=True):
                    it["local"] = str(dest)
        sheet = outdir / f"sheet_p{p}.png"
        contact_sheet(items, sheet, start_index=len(all_items))
        sheets.append(str(sheet))
        all_items.extend(items)
        print(f"  page {p}: {len(items)} items → {sheet}")

    if not all_items:
        sys.exit("harvested 0 listings — see the warning above.")

    manifest = {"search_id": sid, "url": a.url, "start_page": start, "pages": len(sheets),
                "fetched": time.strftime("%Y-%m-%d %H:%M"), "count": len(all_items),
                "sheets": sheets, "items": all_items}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1))

    print(f"\nsearch_id={sid}  {len(all_items)} items across {len(sheets)} page(s)  "
          f"(pages {start}..{start + len(sheets) - 1})")
    for s in sheets:
        print(f"CONTACT SHEET → {s}")
    print(f"manifest      → {outdir/'manifest.json'}")
    print(f"next: view {sid} <global-numbers>   (numbering is continuous across the sheets)")


def cmd_view(a):
    man = OUT / a.search_id / "manifest.json"
    if not man.exists():
        sys.exit(f"no such search_id {a.search_id} (run a search first)")
    items = json.loads(man.read_text())["items"]
    for num in a.numbers:
        i = int(num) - 1
        if not (0 <= i < len(items)):
            print(f"[{num}] out of range (1..{len(items)})"); continue
        it = items[i]
        print(f"[{num}] {it.get('name')}   L${it.get('price') or '—'}   by {it.get('brand')}"
              f"   ★{it.get('rating') or '—'}")
        print(f"     {it.get('url')}")
        print(f"     IMAGE: {it.get('local') or '(no image)'}")


def cmd_categories(a):
    print("known category names → id (extend CATEGORIES in the script):")
    for k, v in CATEGORIES.items():
        print(f"  {k:10} {v}")
    print("pass any numeric category id directly if it's not named yet.")


def main():
    ap = argparse.ArgumentParser(description="Second Life Marketplace shopping for Caia & Lyra.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="fetch a category, build a numbered contact sheet + manifest")
    s.add_argument("category", help="a known name (e.g. skins) or a numeric category id")
    s.add_argument("--maturity", default="G", help="G | M | A (default G)")
    s.add_argument("--query", default=None, help="keyword filter within the category")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--per-page", dest="per_page", type=int, default=48)
    s.add_argument("--sort", default="_score_desc")
    s.add_argument("--fresh", action="store_true", help="bypass the page cache")
    s.set_defaults(func=cmd_search)

    h = sub.add_parser("harvest", help="paginate a settled search URL (from the browser) into contact sheets")
    h.add_argument("url", help="a marketplace /products/search URL; pagination is added automatically")
    h.add_argument("--pages", type=int, default=3, help="how many consecutive pages to harvest (default 3)")
    h.add_argument("--fresh", action="store_true", help="bypass the page cache")
    h.set_defaults(func=cmd_harvest)

    v = sub.add_parser("view", help="print full images + product URLs for tile numbers")
    v.add_argument("search_id")
    v.add_argument("numbers", nargs="+")
    v.set_defaults(func=cmd_view)

    c = sub.add_parser("categories", help="list the known category name→id map")
    c.set_defaults(func=cmd_categories)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
