from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from urllib.parse import urljoin

import urllib3
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# ---------------------------------------------------------------------
# Base site configuration
# ---------------------------------------------------------------------
BASE_URL = "https://www.thegradcafe.com"
SURVEY_URL = f"{BASE_URL}/survey"

# ---------------------------------------------------------------------
# Corporate proxy configuration
# ---------------------------------------------------------------------
PROXY = "http://naproxy.gm.com:8080"

# ---------------------------------------------------------------------
# HTTP client setup for non-browser requests
# ---------------------------------------------------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def build_http_client():
    """Build an urllib3 HTTP client with optional proxy support.

    :returns: Configured ``ProxyManager`` or ``PoolManager`` instance.
    :rtype: urllib3.ProxyManager | urllib3.PoolManager
    """
    if PROXY:
        return urllib3.ProxyManager(
            PROXY,
            cert_reqs="CERT_NONE",
            assert_hostname=False,
            num_pools=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )

    return urllib3.PoolManager(
        cert_reqs="CERT_NONE",
        assert_hostname=False,
        num_pools=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )

http = build_http_client()

# ---------------------------------------------------------------------
# Precompiled regex patterns
# ---------------------------------------------------------------------
RESULT_HREF_RE = re.compile(r"/result/\d+")
TERM_RE = re.compile(r"\b((?:Fall|Spring|Summer|Winter)\s+\d{2,4})\b", re.IGNORECASE)
DATE_ADDED_RE = re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b", re.IGNORECASE)
STATUS_RE = re.compile(r"\b(Accepted|Rejected|Interview|Wait listed)\s+on\b", re.IGNORECASE)
DECISION_SHORT_DATE_RE = re.compile(
    r"\b(?:Accepted|Rejected|Interview|Wait listed)\s+on\s+([A-Z][a-z]{2,8}\s+\d{1,2})\b",
    re.IGNORECASE,
)
STUDENT_TYPE_RE = re.compile(r"\b(International|American|Domestic|US|USA|Other)\b", re.IGNORECASE)
GRE_RE = re.compile(r"\bGRE\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
GRE_V_RE = re.compile(r"\bGRE V\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
GRE_AW_RE = re.compile(r"\bGRE AW\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
GPA_RE = re.compile(r"\bGPA\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)

INSTITUTION_RE = re.compile(r"Institution\s+(.*?)\s+Program", re.IGNORECASE)
PROGRAM_RE = re.compile(r"Program\s+(.*?)\s+Degree Type", re.IGNORECASE)
DEGREE_RE = re.compile(r"Degree Type\s+(.*?)\s+Degree.?s Country of Origin", re.IGNORECASE)
COUNTRY_RE = re.compile(r"Degree.?s Country of Origin\s+(.*?)\s+Decision", re.IGNORECASE)
DETAIL_STATUS_RE = re.compile(r"Decision\s+(.*?)\s+Notification", re.IGNORECASE)
NOTIFICATION_RE = re.compile(r"Notification\s+on\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
UNDERGRAD_GPA_RE = re.compile(r"Undergrad GPA\s+(.*?)\s+GRE General", re.IGNORECASE)
DETAIL_GRE_RE = re.compile(r"GRE General\s+(.*?)\s+GRE Verbal", re.IGNORECASE)
DETAIL_GRE_V_RE = re.compile(r"GRE Verbal\s+(.*?)\s+Analytical Writing", re.IGNORECASE)
DETAIL_GRE_AW_RE = re.compile(
    r"Analytical Writing\s+(.*?)(?:\s+Notes|\s+Institution Statistics|\s+Notification Date|\s+Timeline|$)",
    re.IGNORECASE,
)
COMMENTS_RE = re.compile(
    r"Notes\s+(.*?)(?:Institution Statistics|Notification Date|Timeline|Solutions|Results Submit Yours|$)",
    re.IGNORECASE | re.DOTALL,
)

# ---------------------------------------------------------------------
# Text cleanup helpers
# ---------------------------------------------------------------------
def clean(text: str) -> str:
    """Collapse whitespace and strip leading/trailing space from text.

    :param text: Raw input string.
    :type text: str
    :returns: Normalized single-line string.
    :rtype: str
    """
    return re.sub(r"\s+", " ", text or "").strip()

def extract(pattern, text: str, default="") -> str:
    """Extract and clean the first regex capture group from text.

    :param pattern: Compiled regular expression with a capture group.
    :type pattern: re.Pattern
    :param text: Source text to search.
    :type text: str
    :param default: Value returned when no match is found.
    :type default: str
    :returns: Cleaned captured substring, or ``default``.
    :rtype: str
    """
    match = pattern.search(text or "")
    return clean(match.group(1)) if match else default

def coalesce(*values):
    """Return the first non-empty, non-``"Not provided"`` value.

    :param values: Candidate values tried in order.
    :type values: object
    :returns: First usable value, or an empty string.
    :rtype: object
    """
    for value in values:
        if value not in (None, "", "Not provided"):
            return value
    return ""

def empty_if_not_provided(value: str) -> str:
    """Return an empty string when the value is missing or ``"Not provided"``.

    :param value: Raw field value from a scraped page.
    :type value: str
    :returns: Cleaned value, or ``""`` if not provided.
    :rtype: str
    """
    if not value:
        return ""
    value = clean(value)
    return "" if value.lower() == "not provided" else value

# ---------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------
def normalize_country(value: str) -> str:
    """Normalize student country/type labels to canonical values.

    :param value: Raw country or student-type string.
    :type value: str
    :returns: ``"International"``, ``"American"``, or the original value.
    :rtype: str
    """
    if not value:
        return ""

    value_lower = value.lower()

    if "international" in value_lower:
        return "International"

    if any(x in value_lower for x in ["american", "usa", "u.s.", "domestic", " us ", "us"]):
        return "American"

    return value

def normalize_degree(value: str) -> str:
    """Normalize degree type strings to ``"Masters"`` or ``"PhD"``.

    :param value: Raw degree type string.
    :type value: str
    :returns: Canonical degree label, or the original value.
    :rtype: str
    """
    if not value:
        return ""

    value_lower = value.lower()

    if "master" in value_lower:
        return "Masters"

    if "phd" in value_lower or "doctor" in value_lower:
        return "PhD"

    return value

def normalize_slash_date(date_str: str) -> str:
    """Convert slash-separated dates to ``"%B %d, %Y"`` format.

    :param date_str: Date string such as ``"06/12/2026"`` or ``"12/06/2026"``.
    :type date_str: str
    :returns: Long-form date string, or the original if parsing fails.
    :rtype: str
    """
    if not date_str:
        return ""

    for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%B %d, %Y")
        except ValueError:
            pass

    return date_str

def normalize_month_day_year(date_str: str) -> str:
    """Normalize month/day/year strings to ``"%B %d, %Y"`` format.

    :param date_str: Date string in long or abbreviated month format.
    :type date_str: str
    :returns: Standardized date string, or the original if parsing fails.
    :rtype: str
    """
    if not date_str:
        return ""

    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%B %d, %Y")
        except ValueError:
            pass

    return date_str

def parse_added_on_date(value: str) -> date | None:
    """Parse a Grad Cafe ``added_on`` date string to a ``date`` object.

    :param value: Date string from a survey summary block.
    :type value: str
    :returns: Parsed date, or ``None`` if empty or unparseable.
    :rtype: datetime.date | None
    """
    if not value:
        return None

    normalized = normalize_month_day_year(value)

    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass

    return None

def parse_watermark(value: str | None) -> date | None:
    """Parse an incremental scrape watermark date string.

    :param value: Watermark date in ``YYYY-MM-DD`` or long month format.
    :type value: str | None
    :returns: Parsed date, or ``None`` if ``value`` is empty.
    :rtype: datetime.date | None
    :raises ValueError: If ``value`` is non-empty but not parseable.
    """
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    raise ValueError(
        f"Invalid watermark date: {value}. Use YYYY-MM-DD, e.g. 2026-06-01."
    )

# ---------------------------------------------------------------------
# HTTP fetch helper
# ---------------------------------------------------------------------
def fetch_html(url: str, retries: int = 3, backoff_seconds: float = 1.0) -> str:
    """Fetch HTML from a URL with retries and exponential backoff.

    :param url: Target URL.
    :type url: str
    :param retries: Maximum number of request attempts.
    :type retries: int
    :param backoff_seconds: Base delay multiplied by attempt number.
    :type backoff_seconds: float
    :returns: Decoded UTF-8 HTML content.
    :rtype: str
    :raises RuntimeError: If the server returns a non-200 status.
    :raises Exception: Re-raises the last error after all retries fail.
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = http.request(
                "GET",
                url,
                timeout=urllib3.Timeout(connect=10.0, read=20.0),
            )

            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {url}")

            return response.data.decode("utf-8", errors="ignore")

        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(backoff_seconds * attempt)

    raise last_error

# ---------------------------------------------------------------------
# Selenium browser construction
# ---------------------------------------------------------------------
def build_driver(headless: bool = True) -> webdriver.Chrome:
    """Create a configured Chrome WebDriver for survey pagination.

    :param headless: Run the browser without a visible window.
    :type headless: bool
    :returns: Initialized Chrome WebDriver instance.
    :rtype: selenium.webdriver.Chrome
    """
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--window-size=1600,2200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--user-agent=Mozilla/5.0")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")

    if PROXY:
        options.add_argument(f"--proxy-server={PROXY}")

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)
    options.page_load_strategy = "eager"

    return webdriver.Chrome(options=options)

# ---------------------------------------------------------------------
# Survey-page parsing helpers
# ---------------------------------------------------------------------
def get_anchor_container_text(a_tag) -> str:
    """Return the best ancestor text block for a survey result link.

    Walks upward from a result link and returns the smallest parent block
    that contains both decision text and the term when possible.

    :param a_tag: BeautifulSoup anchor tag for a ``/result/`` link.
    :type a_tag: bs4.element.Tag
    :returns: Cleaned text from the best matching ancestor element.
    :rtype: str
    """
    decision_markers = ("accepted on", "rejected on", "wait listed on", "interview on")

    node = a_tag
    best_text = clean(a_tag.get_text(" ", strip=True))
    best_score = -1

    for _ in range(8):
        if node is None:
            break

        text = clean(node.get_text(" ", strip=True))
        if not text:
            node = node.parent
            continue

        text_lower = text.lower()
        has_decision = any(marker in text_lower for marker in decision_markers)
        has_term = bool(TERM_RE.search(text))

        score = int(has_decision) + int(has_term)

        if score > best_score or (score == best_score and len(text) > len(best_text)):
            best_text = text
            best_score = score

        if has_decision and has_term:
            return text

        node = node.parent

    return best_text

def parse_survey_summary_block(block_text: str, url: str) -> dict:
    """Parse a survey listing block into a summary record dict.

    :param block_text: Raw text surrounding a result link on the survey page.
    :type block_text: str
    :param url: Full URL of the applicant result page.
    :type url: str
    :returns: Partial applicant record with survey-level fields.
    :rtype: dict
    """
    added_on = extract(DATE_ADDED_RE, block_text)
    added_on_normalized = normalize_month_day_year(added_on)

    status = extract(STATUS_RE, block_text)
    decision_short_date = extract(DECISION_SHORT_DATE_RE, block_text)
    term = extract(TERM_RE, block_text)
    student_type = extract(STUDENT_TYPE_RE, block_text)
    gre_score = extract(GRE_RE, block_text)
    gre_v_score = extract(GRE_V_RE, block_text)
    gre_aw = extract(GRE_AW_RE, block_text)
    gpa = extract(GPA_RE, block_text)

    accepted_date = decision_short_date if status.lower() == "accepted" else ""
    rejected_date = decision_short_date if status.lower() == "rejected" else ""

    return {
        "url": url,
        "survey_row_text": block_text,
        "Date of Information Added to Grad Cafe": added_on_normalized,
        "Applicant Status": status,
        "Accepted: Acceptance Date": accepted_date,
        "Rejected: Rejection Date": rejected_date,
        "Semester and Year of Program Start": term,
        "International / American Student": normalize_country(student_type) if student_type else "",
        "GRE Score": gre_score,
        "GRE V Score": gre_v_score,
        "GPA": gpa,
        "GRE AW": gre_aw,
    }

def extract_result_entries_from_page(html: str) -> list[dict]:
    """Extract survey summary entries from a single survey page.

    :param html: Raw HTML of a survey results page.
    :type html: str
    :returns: List of summary dicts keyed by result URL.
    :rtype: list[dict]
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    seen = set()

    for a_tag in soup.select('a[href^="/result/"]'):
        href = a_tag.get("href", "")
        if not RESULT_HREF_RE.fullmatch(href):
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue

        seen.add(full_url)
        block_text = get_anchor_container_text(a_tag)
        entries.append(parse_survey_summary_block(block_text, full_url))

    return entries

def wait_for_results(driver: webdriver.Chrome, timeout: int = 20):
    """Wait until result links appear on the current survey page.

    :param driver: Active Chrome WebDriver instance.
    :type driver: selenium.webdriver.Chrome
    :param timeout: Maximum wait time in seconds.
    :type timeout: int
    :returns: ``WebDriverWait`` instance after results are present.
    :rtype: selenium.webdriver.support.ui.WebDriverWait
    """
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, 'a[href^="/result/"]'))
    return wait

def get_first_result_href(driver: webdriver.Chrome) -> str | None:
    """Return the href of the first result link on the current page.

    :param driver: Active Chrome WebDriver instance.
    :type driver: selenium.webdriver.Chrome
    :returns: Full or relative result URL, or ``None`` if no links found.
    :rtype: str | None
    """
    elements = driver.find_elements(By.CSS_SELECTOR, 'a[href^="/result/"]')
    if not elements:
        return None
    return elements[0].get_attribute("href")

def click_next_page(driver: webdriver.Chrome, timeout: int = 20) -> bool:
    """Click the survey pagination ``Next`` control and wait for new results.

    :param driver: Active Chrome WebDriver instance.
    :type driver: selenium.webdriver.Chrome
    :param timeout: Maximum wait time after clicking Next.
    :type timeout: int
    :returns: ``True`` if pagination succeeded; ``False`` otherwise.
    :rtype: bool
    """
    old_first_href = get_first_result_href(driver)
    wait = WebDriverWait(driver, timeout)

    next_selectors = [
        (By.XPATH, "//a[normalize-space()='Next']"),
        (By.XPATH, "//button[normalize-space()='Next']"),
    ]

    for by, selector in next_selectors:
        elements = driver.find_elements(by, selector)
        for el in elements:
            if not el.is_displayed():
                continue

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                driver.execute_script("arguments[0].click();", el)
                wait.until(lambda d: get_first_result_href(d) != old_first_href)
                return True
            except Exception:
                continue

    return False

# ---------------------------------------------------------------------
# Detail-page parsing
# ---------------------------------------------------------------------
def parse_gradcafe_result_html(html: str, url: str, survey_summary: dict | None = None) -> dict:
    """Parse a Grad Cafe detail page into a full applicant record.

    :param html: Raw HTML of the result detail page.
    :type html: str
    :param url: Full URL of the result page.
    :type url: str
    :param survey_summary: Optional fields parsed from the survey listing.
    :type survey_summary: dict | None
    :returns: Complete applicant record dictionary.
    :rtype: dict
    """
    survey_summary = survey_summary or {}

    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    university = extract(INSTITUTION_RE, text)
    program_name = extract(PROGRAM_RE, text)
    degree_type = extract(DEGREE_RE, text)
    country = extract(COUNTRY_RE, text)
    status = extract(DETAIL_STATUS_RE, text)

    notification_date_raw = extract(NOTIFICATION_RE, text)
    notification_date = normalize_slash_date(notification_date_raw)

    gpa = extract(UNDERGRAD_GPA_RE, text)
    gre_score = extract(DETAIL_GRE_RE, text)
    gre_v_score = extract(DETAIL_GRE_V_RE, text)
    gre_aw = extract(DETAIL_GRE_AW_RE, text)
    comments = extract(COMMENTS_RE, text)

    accepted_date = survey_summary.get("Accepted: Acceptance Date", "")
    rejected_date = survey_summary.get("Rejected: Rejection Date", "")

    if not accepted_date and status.lower().startswith("accept"):
        accepted_date = notification_date

    if not rejected_date and status.lower().startswith("reject"):
        rejected_date = notification_date

    return {
        "Program Name": program_name,
        "University": university,
        "Comments": comments,
        "Date of Information Added to Grad Cafe": survey_summary.get("Date of Information Added to Grad Cafe", ""),
        "URL link to applicant entry": url,
        "Applicant Status": coalesce(status, survey_summary.get("Applicant Status", "")),
        "Accepted: Acceptance Date": accepted_date,
        "Rejected: Rejection Date": rejected_date,
        "Semester and Year of Program Start": survey_summary.get("Semester and Year of Program Start", ""),
        "International / American Student": normalize_country(
            coalesce(country, survey_summary.get("International / American Student", ""))
        ),
        "GRE Score": empty_if_not_provided(coalesce(gre_score, survey_summary.get("GRE Score", ""))),
        "GRE V Score": empty_if_not_provided(coalesce(gre_v_score, survey_summary.get("GRE V Score", ""))),
        "Masters or PhD": normalize_degree(degree_type),
        "GPA": empty_if_not_provided(coalesce(gpa, survey_summary.get("GPA", ""))),
        "GRE AW": empty_if_not_provided(coalesce(gre_aw, survey_summary.get("GRE AW", ""))),
    }

def parse_gradcafe_result(url: str, survey_summary: dict | None = None, retries: int = 3) -> dict:
    """Fetch and parse a single Grad Cafe result detail page.

    :param url: Full URL of the result page.
    :type url: str
    :param survey_summary: Optional fields parsed from the survey listing.
    :type survey_summary: dict | None
    :param retries: Number of HTTP fetch attempts.
    :type retries: int
    :returns: Complete applicant record dictionary.
    :rtype: dict
    """
    html = fetch_html(url, retries=retries)
    return parse_gradcafe_result_html(html, url, survey_summary=survey_summary)

# ---------------------------------------------------------------------
# Multi-page survey scraping with Selenium pagination
# ---------------------------------------------------------------------
def scrape_survey_records(
    start_url: str = SURVEY_URL,
    target_records: int = 100,
    max_pages: int | None = None,
    headless: bool = True,
    pause_seconds: float = 0.0,
    max_workers: int = 8,
    min_added_on: str | None = None,
) -> list[dict]:
    """Scrape applicant records from The Grad Cafe survey with pagination.

    Uses Selenium to paginate the survey listing, then fetches detail pages
    concurrently. Optionally filters records by a minimum ``added_on`` date.

    :param start_url: Survey listing URL to begin scraping.
    :type start_url: str
    :param target_records: Maximum number of records to collect.
    :type target_records: int
    :param max_pages: Optional cap on survey pages to visit.
    :type max_pages: int | None
    :param headless: Run Chrome without a visible window.
    :type headless: bool
    :param pause_seconds: Delay between page turns.
    :type pause_seconds: float
    :param max_workers: Thread pool size for detail-page fetches.
    :type max_workers: int
    :param min_added_on: Only include records added on/after this date
        (``YYYY-MM-DD``).
    :type min_added_on: str | None
    :returns: List of fully parsed applicant record dictionaries.
    :rtype: list[dict]
    """
    if target_records <= 0:
        return []

    watermark_date = parse_watermark(min_added_on)

    driver = build_driver(headless=headless)
    seen_urls = set()
    queued_entries = []
    page_num = 0
    consecutive_pages_with_no_new_urls = 0

    try:
        driver.get(start_url)
        wait_for_results(driver)

        while len(queued_entries) < target_records:
            page_num += 1

            if max_pages is not None and page_num > max_pages:
                print(f"Reached max_pages={max_pages}")
                break

            html = driver.page_source
            page_entries = extract_result_entries_from_page(html)

            if watermark_date is not None:
                page_dates = [
                    parse_added_on_date(entry.get("Date of Information Added to Grad Cafe", ""))
                    for entry in page_entries
                ]
                page_dates = [d for d in page_dates if d is not None]

                if page_dates and max(page_dates) < watermark_date:
                    print(
                        f"Stopping: page {page_num} is entirely older than watermark "
                        f"{watermark_date.isoformat()}"
                    )
                    break

            new_entries = [entry for entry in page_entries if entry["url"] not in seen_urls]

            if watermark_date is not None:
                new_entries = [
                    entry
                    for entry in new_entries
                    if (parse_added_on_date(entry.get("Date of Information Added to Grad Cafe", "")) or date.min)
                    >= watermark_date
                ]

            print(
                f"[page {page_num}] found {len(page_entries)} entries, "
                f"{len(new_entries)} new after watermark, "
                f"{len(queued_entries)}/{target_records} queued"
            )

            if not new_entries:
                consecutive_pages_with_no_new_urls += 1
            else:
                consecutive_pages_with_no_new_urls = 0

            if consecutive_pages_with_no_new_urls >= 3:
                print("Stopping after 3 consecutive pages with no new URLs.")
                break

            for entry in new_entries:
                if len(queued_entries) >= target_records:
                    break

                seen_urls.add(entry["url"])
                queued_entries.append(entry)

            if len(queued_entries) >= target_records:
                break

            moved = click_next_page(driver)
            if not moved:
                print("Next page click failed; refreshing and retrying once...")
                time.sleep(2)

                try:
                    driver.refresh()
                    wait_for_results(driver, timeout=30)
                    moved = click_next_page(driver)
                except TimeoutException:
                    print("Refresh timed out; page did not return to survey results.")
                    print("Current URL:", driver.current_url)
                    print("Title:", driver.title)

                    os.makedirs("debug", exist_ok=True)
                    with open(f"debug/page_{page_num}_timeout.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)

                    break

            if not moved:
                print("Stopping after repeated next-page failures.")
                break

            if pause_seconds:
                time.sleep(pause_seconds)

    finally:
        driver.quit()

    queued_entries = queued_entries[:target_records]
    records_by_url = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_entry = {
            executor.submit(parse_gradcafe_result, entry["url"], survey_summary=entry, retries=3): entry
            for entry in queued_entries
        }

        completed = 0
        for future in as_completed(future_to_entry):
            entry = future_to_entry[future]
            try:
                records_by_url[entry["url"]] = future.result()
                completed += 1
                if completed % 10 == 0 or completed == len(queued_entries):
                    print(f"[{completed}/{len(queued_entries)}] parsed detail pages")
            except Exception as e:
                print(f"[skip] failed {entry['url']}: {e}")

    records = [records_by_url[entry["url"]] for entry in queued_entries if entry["url"] in records_by_url]
    return records

# ---------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="json_files/applicant_data_updated.json")
    parser.add_argument("--target-records", type=int, default=10000)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--headless", type=lambda x: x.lower() == "true", default=True)
    parser.add_argument("--pause-seconds", type=float, default=0.1)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument(
        "--min-added-on",
        default=None,
        help="Only scrape records added on/after this date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    records = scrape_survey_records(
        start_url=SURVEY_URL,
        target_records=args.target_records,
        max_pages=args.max_pages,
        headless=args.headless,
        pause_seconds=args.pause_seconds,
        max_workers=args.max_workers,
        min_added_on=args.min_added_on,
    )

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to {args.output}")