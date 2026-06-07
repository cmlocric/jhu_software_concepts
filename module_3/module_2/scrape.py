import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin

import urllib3
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

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
    return re.sub(r"\s+", " ", text or "").strip()

def extract(pattern, text: str, default="") -> str:
    match = pattern.search(text or "")
    return clean(match.group(1)) if match else default

def coalesce(*values):
    for value in values:
        if value not in (None, "", "Not provided"):
            return value
    return ""

def empty_if_not_provided(value: str) -> str:
    if not value:
        return ""
    value = clean(value)
    return "" if value.lower() == "not provided" else value

# ---------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------
def normalize_country(value: str) -> str:
    if not value:
        return ""

    value_lower = value.lower()

    if "international" in value_lower:
        return "International"

    if any(x in value_lower for x in ["american", "usa", "u.s.", "domestic", " us ", "us"]):
        return "American"

    return value

def normalize_degree(value: str) -> str:
    if not value:
        return ""

    value_lower = value.lower()

    if "master" in value_lower:
        return "Masters"

    if "phd" in value_lower or "doctor" in value_lower:
        return "PhD"

    return value

def normalize_slash_date(date_str: str) -> str:
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
    if not date_str:
        return ""

    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%B %d, %Y")
        except ValueError:
            pass

    return date_str

# ---------------------------------------------------------------------
# HTTP fetch helper
# ---------------------------------------------------------------------
def fetch_html(url: str, retries: int = 3, backoff_seconds: float = 1.0) -> str:
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
    """
    Walk upward from a result link and return the smallest parent block that
    contains BOTH decision text and the term when possible. This fixes the
    missing term issue caused by returning too early on a partial ancestor.
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
    added_on = extract(DATE_ADDED_RE, block_text)
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
        "Date of Information Added to Grad Cafe": normalize_month_day_year(added_on),
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
    """
    Extract unique result URLs plus summary metadata from a rendered survey page.
    Faster than scanning every anchor on the page.
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
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, 'a[href^="/result/"]'))
    return wait

def get_first_result_href(driver: webdriver.Chrome) -> str | None:
    elements = driver.find_elements(By.CSS_SELECTOR, 'a[href^="/result/"]')
    if not elements:
        return None
    return elements[0].get_attribute("href")

def click_next_page(driver: webdriver.Chrome, timeout: int = 20) -> bool:
    """
    Avoid reparsing the entire page during wait polling. Just wait for the first
    result link to change after clicking Next.
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
) -> list[dict]:
    if target_records <= 0:
        return []

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
            new_entries = [entry for entry in page_entries if entry["url"] not in seen_urls]

            print(
                f"[page {page_num}] found {len(page_entries)} entries, "
                f"{len(new_entries)} new, "
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
    records = scrape_survey_records(
        start_url=SURVEY_URL,
        target_records=100,
        max_pages=None,
        headless=True,
        pause_seconds=0.1,
        max_workers=8,
    )

    os.makedirs("json_files", exist_ok=True)

    output_path = "json_files/applicant_data_updated.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to {output_path}")