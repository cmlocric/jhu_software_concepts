import json
import os
import re
import time
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

if PROXY:
    http = urllib3.ProxyManager(
        PROXY,
        cert_reqs="CERT_NONE",
        assert_hostname=False,
    )
else:
    http = urllib3.PoolManager(
        cert_reqs="CERT_NONE",
        assert_hostname=False,
    )

# ---------------------------------------------------------------------
# Text cleanup helpers
# ---------------------------------------------------------------------
def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def extract(pattern: str, text: str, flags=0, default="") -> str:
    match = re.search(pattern, text or "", flags)
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
    """
    Converts dd/mm/yyyy or mm/dd/yyyy -> Month DD, YYYY
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
    """
    Converts strings like 'May 29, 2026' to a normalized format if possible.
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

# ---------------------------------------------------------------------
# HTTP fetch helper
# ---------------------------------------------------------------------
def fetch_html(url: str, retries: int = 3, backoff_seconds: float = 1.5) -> str:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = http.request(
                "GET",
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=urllib3.Timeout(connect=10.0, read=30.0),
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

    if PROXY:
        options.add_argument(f"--proxy-server={PROXY}")

    return webdriver.Chrome(options=options)

# ---------------------------------------------------------------------
# Survey-page parsing helpers
# ---------------------------------------------------------------------
def get_anchor_container_text(a_tag) -> str:
    """
    Walk upward from a result link and grab the smallest parent block that
    looks like a full result row/card.
    """
    decision_markers = ["accepted on", "rejected on", "wait listed on", "interview on"]
    term_pattern = r"(Fall|Spring|Summer|Winter)\s+\d{4}"

    node = a_tag
    for _ in range(6):
        if node is None:
            break

        text = clean(node.get_text(" ", strip=True))
        text_lower = text.lower()

        if any(marker in text_lower for marker in decision_markers) or re.search(term_pattern, text, re.IGNORECASE):
            return text

        node = node.parent

    if a_tag.parent:
        return clean(a_tag.parent.get_text(" ", strip=True))

    return clean(a_tag.get_text(" ", strip=True))

def parse_survey_summary_block(block_text: str, url: str) -> dict:
    added_on = extract(
        r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b",
        block_text,
        re.IGNORECASE,
    )

    status = extract(
        r"\b(Accepted|Rejected|Interview|Wait listed)\s+on\b",
        block_text,
        re.IGNORECASE,
    )

    decision_short_date = extract(
        r"\b(?:Accepted|Rejected|Interview|Wait listed)\s+on\s+([A-Z][a-z]{2,8}\s+\d{1,2})\b",
        block_text,
        re.IGNORECASE,
    )

    term = extract(
        r"\b((?:Fall|Spring|Summer|Winter)\s+\d{4})\b",
        block_text,
        re.IGNORECASE,
    )

    student_type = extract(
        r"\b(International|American|Domestic|US|USA|Other)\b",
        block_text,
        re.IGNORECASE,
    )

    gre_score = extract(
        r"\bGRE\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE,
    )

    gre_v_score = extract(
        r"\bGRE V\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE,
    )

    gre_aw = extract(
        r"\bGRE AW\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE,
    )

    gpa = extract(
        r"\bGPA\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE,
    )

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
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    seen = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if not re.fullmatch(r"/result/\d+", href):
            continue

        full_url = urljoin(BASE_URL, href)

        if full_url in seen:
            continue
        seen.add(full_url)

        block_text = get_anchor_container_text(a_tag)
        summary = parse_survey_summary_block(block_text, full_url)
        entries.append(summary)

    return entries

def wait_for_results(driver: webdriver.Chrome, timeout: int = 20):
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: "Graduate School Admission Results" in d.page_source or "/result/" in d.page_source)
    return wait

def current_result_urls(driver: webdriver.Chrome) -> set[str]:
    html = driver.page_source
    entries = extract_result_entries_from_page(html)
    return {entry["url"] for entry in entries}

def click_next_page(driver: webdriver.Chrome, timeout: int = 20) -> bool:
    old_result_urls = current_result_urls(driver)
    wait = WebDriverWait(driver, timeout)

    next_xpaths = [
        "//a[normalize-space()='Next']",
        "//button[normalize-space()='Next']",
    ]

    for xpath in next_xpaths:
        elements = driver.find_elements(By.XPATH, xpath)

        for el in elements:
            if not el.is_displayed():
                continue

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", el)

                wait.until(lambda d: current_result_urls(d) != old_result_urls)
                return True

            except Exception:
                continue

    return False

# ---------------------------------------------------------------------
# Detail-page parsing
# ---------------------------------------------------------------------
def parse_gradcafe_result_html(html: str, url: str, survey_summary: dict | None = None) -> dict:
    """
    Parse one result detail page and merge in any survey-row metadata.
    """
    survey_summary = survey_summary or {}

    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    university = extract(r"Institution\s+(.*?)\s+Program", text, re.IGNORECASE)
    program_name = extract(r"Program\s+(.*?)\s+Degree Type", text, re.IGNORECASE)
    degree_type = extract(r"Degree Type\s+(.*?)\s+Degree.?s Country of Origin", text, re.IGNORECASE)
    country = extract(r"Degree.?s Country of Origin\s+(.*?)\s+Decision", text, re.IGNORECASE)
    status = extract(r"Decision\s+(.*?)\s+Notification", text, re.IGNORECASE)

    notification_date_raw = extract(
        r"Notification\s+on\s+(\d{2}/\d{2}/\d{4})",
        text,
        re.IGNORECASE,
    )
    notification_date = normalize_slash_date(notification_date_raw)

    gpa = extract(
        r"Undergrad GPA\s+(.*?)\s+GRE General",
        text,
        re.IGNORECASE,
    )
    gre_score = extract(
        r"GRE General\s+(.*?)\s+GRE Verbal",
        text,
        re.IGNORECASE,
    )
    gre_v_score = extract(
        r"GRE Verbal\s+(.*?)\s+Analytical Writing",
        text,
        re.IGNORECASE,
    )
    gre_aw = extract(
        r"Analytical Writing\s+(.*?)(?:\s+Notes|\s+Institution Statistics|\s+Notification Date|\s+Timeline|$)",
        text,
        re.IGNORECASE,
    )

    comments = extract(
        r"Notes\s+(.*?)(?:Institution Statistics|Notification Date|Timeline|Solutions|Results Submit Yours|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

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
        "GRE Score": empty_if_not_provided(
            coalesce(gre_score, survey_summary.get("GRE Score", ""))
        ),
        "GRE V Score": empty_if_not_provided(
            coalesce(gre_v_score, survey_summary.get("GRE V Score", ""))
        ),
        "Masters or PhD": normalize_degree(degree_type),
        "GPA": empty_if_not_provided(
            coalesce(gpa, survey_summary.get("GPA", ""))
        ),
        "GRE AW": empty_if_not_provided(
            coalesce(gre_aw, survey_summary.get("GRE AW", ""))
        ),
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
    pause_seconds: float = 1,
) -> list[dict]:
    if target_records <= 0:
        return []

    driver = build_driver(headless=headless)
    records = []
    seen_urls = set()
    page_num = 0
    consecutive_pages_with_no_new_urls = 0

    try:
        driver.get(start_url)
        wait_for_results(driver)

        while len(records) < target_records:
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
                f"{len(records)}/{target_records} records collected"
            )

            if not new_entries:
                consecutive_pages_with_no_new_urls += 1
            else:
                consecutive_pages_with_no_new_urls = 0

            if consecutive_pages_with_no_new_urls >= 3:
                print("Stopping after 3 consecutive pages with no new URLs.")
                break

            for entry in new_entries:
                if len(records) >= target_records:
                    break

                url = entry["url"]
                seen_urls.add(url)

                try:
                    record = parse_gradcafe_result(url, survey_summary=entry, retries=3)
                    records.append(record)
                    print(f"[{len(records)}/{target_records}] parsed {url}")
                except Exception as e:
                    print(f"[skip] failed {url}: {e}")

                time.sleep(pause_seconds)

            if len(records) >= target_records:
                break

            moved = click_next_page(driver)
            #First full run failed at page 766, adding to handle occasional next-page click failures 
            # by refreshing and retrying once before giving up on pagination.
            if not moved:
                print("Next page click failed; refreshing and retrying once...")
                time.sleep(5)

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

            time.sleep(pause_seconds)

    finally:
        driver.quit()

    return records

# ---------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    records = scrape_survey_records(
        start_url=SURVEY_URL,
        target_records=30000,
        max_pages=None,
        headless=True,
        pause_seconds=1,  
    )

    os.makedirs("json_files", exist_ok=True)

    output_path = "json_files/applicant_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to {output_path}")
