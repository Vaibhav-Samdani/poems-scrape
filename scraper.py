import os
import json
import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://kavitakosh.org"
INDEX_URL = BASE_URL + "/kk/रचनाकारों_की_सूची"
SAVE_DIR = "new/poets"

os.makedirs(SAVE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KavitaKoshScraper/1.0; +https://example.com)"
}

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def sleep_polite():
    time.sleep(random.uniform(1.0, 2.0))


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS)
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


# words/labels you never want to treat as works or parts
SKIP_LINK_WORDS = {
    "पृष्ठ", "स्रोत देखें", "इतिहास", "चर्चा", "लॉग इन", "लॉगिन",
    "कविता कोश खोज", "ई-पत्रिकाएँ", "ई-पुस्तकें", "विधाएँ", "विषय",
    "फ़िल्मी गीत", "फ़िल्मी गीत", "अनुवाद", "श्रेणी", "मुखपृष्ठ", "विदेशी",
    "कविता कोश", "महत्त्वपूर्ण कड़ियाँ", "नए जुड़े पन्नों की सूची",
    "अन्य भाषाएँ", "टाइपिंग टूल्स", "गद्य कोश", "रचनाकारों की सूची"
}

LANG_WORDS = {
    "हिन्दी", "हिन्दी / उर्दू", "उर्दू", "भोजपुरी", "मैथिली", "राजस्थानी",
    "अंगिका", "अवधी", "नेपाली", "हरियाणवी", "ब्रज भाषा", "संस्कृतम्",
    "छत्तीसगढ़ी", "सिन्धी", "मराठी", "गुजराती", "पालि", "गढ़वाली"
}


def is_navigation_text(text: str) -> bool:
    if not text:
        return True
    t = text.strip()
    if t in SKIP_LINK_WORDS or t in LANG_WORDS:
        return True
    # obvious non-work patterns
    if any(sym in t for sym in ["...", "|"]):
        return True
    return False


# -------------------------------------------------
# Step 1: Get first x poets from रचनाकारों_की_सूची
# -------------------------------------------------

def get_poet_list(limit: int = 50):
    print("Scraping poets index page...")
    soup = get_soup(INDEX_URL)

    poets = []
    # only links inside main content
    for a in soup.select("#mw-content-text a"):
        name = (a.get_text() or "").strip()
        href = a.get("href") or ""

        if not href.startswith("/kk/"):
            continue
        if is_navigation_text(name):
            continue
        # avoid category and talk pages
        if href.startswith("/kk/श्रेणी:") or href.startswith("/kk/वार्ता:"):
            continue

        full_url = BASE_URL + href

        poets.append((name, full_url))

        if len(poets) >= limit:
            break

    print(f"Found {len(poets)} poets.\n")
    return poets


# -------------------------------------------------
# Step 2: Extract works for a poet
# -------------------------------------------------

def normalize_poet_name(name: str) -> str:
    return name.replace("“", "\"").replace("”", "\"").replace("''", "\"").strip()


def get_poet_works(poet_name: str, poet_url: str):
    """
    From a poet page, collect links that look like works of that poet.
    Pattern used: link text contains ' / ' and the last part matches poet name (loosely).
    """
    print(f"Scraping poet: {poet_name}")
    soup = get_soup(poet_url)

    norm_poet = normalize_poet_name(poet_name)
    main_name_token = norm_poet.split()[0]

    works = []

    for a in soup.select("#mw-content-text a"):
        text = (a.get_text() or "").strip()
        href = a.get("href") or ""

        if not href.startswith("/kk/"):
            continue
        if is_navigation_text(text):
            continue

        # We treat as work only if it looks like "Title / Poet"
        if " / " not in text:
            continue

        # last part after slash should contain the poet's name (or at least main token)
        last_part = text.split("/")[-1].strip()
        if main_name_token not in last_part and norm_poet not in last_part:
            continue

        full_url = BASE_URL + href
        works.append((text, full_url))

    print(f"→ Found {len(works)} works for {poet_name}")
    return works


# -------------------------------------------------
# Step 3: Scrape a work (single or multipart)
# -------------------------------------------------

def extract_poem_text(soup: BeautifulSoup) -> str:
    # try common poem containers first
    for selector in [".poem", "#poem", "div.mw-content-ltr"]:
        block = soup.select_one(selector)
        if block:
            text = block.get_text("\n", strip=True)
            if text:
                return text
    # fallback, everything from content div
    content = soup.select_one("#mw-content-text")
    if content:
        return content.get_text("\n", strip=True)
    return soup.get_text("\n", strip=True)


def get_work_parts(poet_name: str, work_url: str):
    """
    On a work page, see if there are sub-links that look like parts of same work.
    We use similar "Title / Poet" pattern to identify parts.
    """
    soup = get_soup(work_url)
    norm_poet = normalize_poet_name(poet_name)
    main_name_token = norm_poet.split()[0]

    parts = []

    for a in soup.select("#mw-content-text a"):
        text = (a.get_text() or "").strip()
        href = a.get("href") or ""

        if not href.startswith("/kk/"):
            continue
        if is_navigation_text(text):
            continue
        if " / " not in text:
            continue

        last_part = text.split("/")[-1].strip()
        if main_name_token not in last_part and norm_poet not in last_part:
            continue

        full_url = BASE_URL + href
        parts.append((text, full_url))

    return parts, soup


def scrape_work(poet_name: str, work_title: str, work_url: str):
    print(f"  → Fetching work: {work_title}")
    parts, soup = get_work_parts(poet_name, work_url)

    if parts:
        print(f"    Multipart: Yes ({len(parts)} parts)")
        work_obj = {
            "title": work_title,
            "type": "multipart",
            "parts": []
        }
        for part_title, part_url in parts:
            print(f"      Part: {part_title}")
            psoup = get_soup(part_url)
            content = extract_poem_text(psoup)
            work_obj["parts"].append({
                "title": part_title,
                "content": content
            })
            sleep_polite()
    else:
        print("    Multipart: No (single)")
        # single poem: use the soup we already have
        content = extract_poem_text(soup)
        work_obj = {
            "title": work_title,
            "type": "single",
            "content": content
        }

    return work_obj


# -------------------------------------------------
# Step 4: Scrape one poet → save JSON
# -------------------------------------------------

def scrape_poet(poet_name: str, poet_url: str):
    works_meta = get_poet_works(poet_name, poet_url)

    poet_data = {
        "poet": poet_name,
        "works": []
    }

    for title, url in works_meta:
        work_obj = scrape_work(poet_name, title, url)
        poet_data["works"].append(work_obj)
        sleep_polite()

    out_path = os.path.join(SAVE_DIR, f"{poet_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(poet_data, f, ensure_ascii=False, indent=2)

    print(f"→ Completed: {poet_name}")
    print(f"  Saved: {out_path}\n")


# -------------------------------------------------
# Main
# -------------------------------------------------

def main():
    poets = get_poet_list(limit=3140)  # get all poets

    for poet_name, poet_url in poets:
        scrape_poet(poet_name, poet_url)
        sleep_polite()

    print("All poets scraped and saved.")


if __name__ == "__main__":
    main()
