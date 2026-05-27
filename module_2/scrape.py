import urllib.request, re, time
from bs4 import BeautifulSoup
import mechanicalsoup

# Necessary for accessing the site from corproate laptop.If you are running 
# this code from a different environment, you may not need to use a proxy.

proxy = "naproxy.gm.com:8080"

proxies = {
    "http": proxy,
    "https": proxy
    }

proxy_handler = urllib.request.ProxyHandler({
    "http": proxy,
    "https": proxy,
})

url = 'http://olympus.realpython.org/profiles'
base_url = 'http://olympus.realpython.org/login'

opener = urllib.request.build_opener(proxy_handler)
response = opener.open(url, timeout=30)
html_bytes = response.read()
html = html_bytes.decode("utf-8")

#Example of using BeautifulSoup to access the site and print all the links on the page.
soup = BeautifulSoup(html, "html.parser")
for a in soup.find_all("a"):
    href = a.get("href")
    print(f"{base_url}{href}")

#Example of using mechanicalsoup to access the same site.
browser = mechanicalsoup.Browser()
for i in range(4):
    page = browser.get("http://olympus.realpython.org/dice", proxies=proxies, timeout=15)
    tag = page.soup.select("#result")[0]
    result = tag.text
    print(f"The result of your dice roll is: {result}")
    
    # Wait 10 seconds if this isn't the last request
    if i < 3:
        time.sleep(5)