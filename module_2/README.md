## Chris Locricchio F0B0B2

## Module 2 - Web Scraping - 5/31/2026

## Approach

This scraper uses a hybrid urllib3 + Selenium + BeautifulSoup workflow.

The implementation splits the scraping task into two stages.

First, Selenium is used to load the GradCafe survey page, wait for the page to render, and paginate through the results by clicking the Next button. This handles the dynamic listing page and collects the `/result/<id>` URLs for applicant entries.

Second, once those applicant-entry URLs are collected, the scraper switches to urllib3 for the individual result pages. This is more efficient than using Selenium for every detail page. Each applicant page is fetched with urllib3, parsed with BeautifulSoup, and then processed with regex-based extraction.

BeautifulSoup is used in both stages:
- to parse rendered survey-page HTML
- to parse applicant detail-page HTML

So the overall workflow is:
- Selenium for dynamic survey-page rendering and pagination
- urllib3 for direct requests to applicant detail pages
- BeautifulSoup for HTML parsing throughout

## Browser and Driver Setup

Selenium was configured with Chrome using `webdriver.Chrome(options=options)`.

The code does not manually specify a separate ChromeDriver path. Because of that, it relies on Selenium's default Chrome driver resolution behavior, which in modern Selenium is typically handled by Selenium Manager if Chrome and a compatible driver are available.

The browser configuration includes:
- Chrome
- optional headless mode using `--headless=new`
- a custom browser window size
- a browser-like user agent
- proxy support using `--proxy-server=http://naproxy.gm.com:8080`
- Chrome stability flags such as `--no-sandbox` and `--disable-dev-shm-usage`

In short, the Selenium setup is:
- Browser: Chrome
- Driver resolution: default Selenium Chrome resolution, typically Selenium Manager
- Mode: headless by default, configurable

## Detailed Implementation

### 1. Base configuration

The scraper defines:
- `BASE_URL = "https://www.thegradcafe.com"`
- `SURVEY_URL = "https://www.thegradcafe.com/survey"`

It also defines a GM corporate proxy:
- `PROXY = "http://naproxy.gm.com:8080"`

That proxy is used by both urllib3 and Selenium.

### 2. HTTP client for applicant detail pages

The code creates a `urllib3.ProxyManager` object for direct HTTP requests to applicant detail pages.

This means Selenium is only used where browser interaction is necessary. Once result URLs are discovered, the scraper uses urllib3 for faster, lighter detail-page retrieval.

### 3. Text cleanup and normalization

Several helper functions standardize scraped values before output:
- `clean()` collapses whitespace
- `extract()` runs regex extraction and returns the first cleaned capture group
- `coalesce()` selects the first usable value
- `empty_if_not_provided()` converts `Not provided` into an empty string

Additional normalization functions standardize:
- country labels into `International` or `American`
- degree labels into `Masters` or `PhD`
- dates into a consistent readable format

### 4. Selenium survey-page workflow

The function `build_driver()` constructs a Chrome Selenium driver.

The survey scraping process is:
1. Open the survey page
2. Wait for results to load
3. Capture rendered HTML from `driver.page_source`
4. Parse all applicant entry links
5. Extract visible metadata from each survey row
6. Click Next
7. Repeat until the page or record limit is reached

Key helper functions:
- `wait_for_results()`
- `click_next_page()`
- `extract_result_entries_from_page()`

### 5. Survey-row metadata extraction

The scraper extracts useful metadata directly from the survey listing rows, including:
- Date of Information Added to Grad Cafe
- Applicant Status
- Accepted date
- Rejected date
- Semester and Year of Program Start
- International / American Student
- GRE Score
- GRE V Score
- GPA
- GRE AW

This is done by finding the result link, identifying the surrounding row/card text, and applying regex patterns to that text.

### 6. Applicant detail-page parsing

After collecting survey entries, the scraper visits each applicant result URL with urllib3.

For each detail page it:
1. downloads the HTML
2. parses it with BeautifulSoup
3. flattens visible text into one string
4. extracts fields with regex
5. merges detail-page fields with survey-row fields

The detail page is used to capture:
- Program Name
- University
- Comments
- Applicant Status
- International / American Student
- GRE Score
- GRE V Score
- Masters or PhD
- GPA
- GRE AW
- notification-based acceptance or rejection fallback dates

### 7. Merge strategy

The scraper combines survey-page metadata and detail-page metadata.

Examples:
- if the survey row contains an acceptance or rejection date, that value is used
- if it does not, the scraper falls back to the detail-page notification date when the status is accepted or rejected
- if GRE or GPA values appear in both places, the first usable value is kept

This makes the scraper more robust than relying on only one page type.

### 8. Final output

The top-level function `scrape_survey_records()` runs the full pipeline:
1. collect survey entries with Selenium
2. fetch applicant detail pages with urllib3
3. parse and merge the results
4. return a list of dictionaries

The `__main__` block saves the output to:
- `module_2/applicant_data.json`

## Summary of Technical Approach

This scraper is not urllib-only.

It is also not Selenium-only.

It uses a hybrid urllib3 + Selenium + BeautifulSoup workflow:
- Selenium-rendered pages for the dynamic survey listing
- urllib3 direct requests for applicant detail pages
- BeautifulSoup for HTML parsing across both stages

This design balances reliability and efficiency:
- Selenium handles dynamic pagination
- urllib3 keeps detail-page scraping lighter and faster
- BeautifulSoup provides flexible HTML parsing

## Output Fields

The scraper is designed to output the following fields when available:
- Program Name
- University
- Comments
- Date of Information Added to Grad Cafe
- URL link to applicant entry
- Applicant Status
- Accepted: Acceptance Date
- Rejected: Rejection Date
- Semester and Year of Program Start
- International / American Student
- GRE Score
- GRE V Score
- Masters or PhD
- GPA
- GRE AW

## Notes

The implementation is designed to run behind a GM corporate proxy and may require that proxy in a corporate environment.

Chrome runs in headless mode by default, but this can be changed by setting `headless=False`.

Although the pagination limit is set very high, the number of saved records is still controlled by `max_records`, which makes testing safer and faster.