import re
import json
import time
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

from selenium import webdriver
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
http = urllib3.ProxyManager(
    PROXY,
    cert_reqs="CERT_NONE",
    assert_hostname=False
)

# ---------------------------------------------------------------------
# Text cleanup helpers
# ---------------------------------------------------------------------
def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def extract(pattern: str, text: str, flags=0, default=""):
    match = re.search(pattern, text, flags)
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
    value_lower = value.lower()
    if "international" in value_lower:
        return "International"
    if any(x in value_lower for x in ["american", "usa", "u.s.", "domestic", "us"]):
        return "American"
    return value

def normalize_degree(value: str) -> str:
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

    return clean(a_tag.parent.get_text(" ", strip=True)) if a_tag.parent else clean(a_tag.get_text(" ", strip=True))

def parse_survey_summary_block(block_text: str, url: str) -> dict:
    """
    Parse metadata visible directly on the survey listing row/card.

    This is where we get:
    - Date of Information Added to Grad Cafe
    - Accepted / Rejected short decision dates
    - Semester and Year of Program Start
    - International / American Student
    - Sometimes GRE / GPA values
    """
    added_on = extract(
        r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b",
        block_text,
        re.IGNORECASE
    )

    status = extract(
        r"\b(Accepted|Rejected|Interview|Wait listed)\s+on\b",
        block_text,
        re.IGNORECASE
    )

    decision_short_date = extract(
        r"\b(?:Accepted|Rejected|Interview|Wait listed)\s+on\s+([A-Z][a-z]{2,8}\s+\d{1,2})\b",
        block_text,
        re.IGNORECASE
    )

    term = extract(
        r"\b((?:Fall|Spring|Summer|Winter)\s+\d{4})\b",
        block_text,
        re.IGNORECASE
    )

    student_type = extract(
        r"\b(International|American|Domestic|US|USA|Other)\b",
        block_text,
        re.IGNORECASE
    )

    gre_score = extract(
        r"\bGRE\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE
    )

    gre_v_score = extract(
        r"\bGRE V\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE
    )

    gre_aw = extract(
        r"\bGRE AW\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE
    )

    gpa = extract(
        r"\bGPA\s+(\d+(?:\.\d+)?)\b",
        block_text,
        re.IGNORECASE
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
    Extract unique result URLs plus any summary metadata from a rendered survey page.
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

def click_next_page(driver: webdriver.Chrome, timeout: int = 20) -> bool:
    old_html = driver.page_source
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
                wait.until(lambda d: d.page_source != old_html)
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
        re.IGNORECASE
    )
    notification_date = normalize_slash_date(notification_date_raw)

    gpa = extract(
        r"Undergrad GPA\s+(.*?)\s+GRE General",
        text,
        re.IGNORECASE
    )
    gre_score = extract(
        r"GRE General\s+(.*?)\s+GRE Verbal",
        text,
        re.IGNORECASE
    )
    gre_v_score = extract(
        r"GRE Verbal\s+(.*?)\s+Analytical Writing",
        text,
        re.IGNORECASE
    )
    gre_aw = extract(
        r"Analytical Writing\s+(.*?)(?:\s+Notes|\s+Institution Statistics|\s+Notification Date|\s+Timeline|$)",
        text,
        re.IGNORECASE
    )

    comments = extract(
        r"Notes\s+(.*?)(?:Institution Statistics|Notification Date|Timeline|Solutions|Results Submit Yours|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    # If the survey row did not expose accepted/rejected date, we can
    # use the detail-page notification date as a fallback when status matches.
    accepted_date = survey_summary.get("Accepted: Acceptance Date", "")
    rejected_date = survey_summary.get("Rejected: Rejection Date", "")

    if not accepted_date and status.lower().startswith("accept"):
        accepted_date = notification_date
    if not rejected_date and status.lower().startswith("reject"):
        rejected_date = notification_date

    result = {
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

    return result

def parse_gradcafe_result(url: str, survey_summary: dict | None = None) -> dict:
    response = http.request(
        "GET",
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    html = response.data.decode("utf-8", errors="ignore")
    return parse_gradcafe_result_html(html, url, survey_summary=survey_summary)

# ---------------------------------------------------------------------
# Multi-page survey scraping
# ---------------------------------------------------------------------
def scrape_survey_entries(
    start_url: str = SURVEY_URL,
    max_pages: int = 5,
    max_records: int = 100,
    headless: bool = True,
    pause_seconds: float = 0.5,
) -> list[dict]:
    """
    Walk survey pages and collect result URLs + survey-visible metadata.
    """
    driver = build_driver(headless=headless)
    all_entries = []
    seen = set()

    try:
        driver.get(start_url)
        wait_for_results(driver)

        for page_num in range(1, max_pages + 1):
            html = driver.page_source
            page_entries = extract_result_entries_from_page(html)

            for entry in page_entries:
                url = entry["url"]
                if url not in seen:
                    seen.add(url)
                    all_entries.append(entry)

            print(f"[page {page_num}] collected {len(page_entries)} entries ({len(all_entries)} total)")

            if len(all_entries) >= max_records:
                break

            moved = click_next_page(driver)
            if not moved:
                print("No more pages found.")
                break

            time.sleep(pause_seconds)

    finally:
        driver.quit()

    return all_entries[:max_records]

def scrape_survey_records(
    start_url: str = SURVEY_URL,
    max_pages: int = 5,
    max_records: int = 100,
    headless: bool = True,
    pause_seconds: float = 0.5,
) -> list[dict]:
    """
    End-to-end scrape:
    1. Collect summary metadata from survey rows
    2. Visit each detail page
    3. Merge survey-row + detail-page fields
    """
    survey_entries = scrape_survey_entries(
        start_url=start_url,
        max_pages=max_pages,
        max_records=max_records,
        headless=headless,
        pause_seconds=pause_seconds,
    )

    records = []

    for i, entry in enumerate(survey_entries, start=1):
        url = entry["url"]
        try:
            record = parse_gradcafe_result(url, survey_summary=entry)
            records.append(record)
            print(f"[{i}/{len(survey_entries)}] parsed {url}")
        except Exception as e:
            print(f"[{i}/{len(survey_entries)}] failed {url}: {e}")

        time.sleep(pause_seconds)

    return records

# ---------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    records = scrape_survey_records(
        start_url="https://www.thegradcafe.com/survey",
        max_pages=47934,
        max_records=20,
        headless=True,
        pause_seconds=1,
    )

    with open("module_2/applicant_data.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to module_2/applicant_data.json")
    