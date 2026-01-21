import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from dotenv import load_dotenv
import re
import os
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI

# Load API Keys
load_dotenv()

# Config
MATCH_THRESHOLD = 50

# ------------------- Helper Functions -------------------

def _read_my_resume():
    try:
        with open("resume.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None

def _extract_score(text):
    match = re.search(r"SCORE:\s*(\d+)%", text)
    if not match:
        match = re.search(r"(\d+)%", text)
    if match:
        return int(match.group(1))
    return 0

def _get_smart_domain(country_input: str):
    """
    Intelligently maps any country variation to the correct Indeed domain.
    Handles 'USA', 'us', 'United States' -> indeed.com
    """
    c = country_input.lower().strip()
    
    # 1. Common Synonyms Map
    mapping = {
        # North America
        "usa": "indeed.com", "us": "indeed.com", "united states": "indeed.com", "america": "indeed.com",
        "canada": "ca.indeed.com", "ca": "ca.indeed.com",
        "mexico": "indeed.com.mx", "mx": "indeed.com.mx",
        
        # Europe
        "uk": "indeed.co.uk", "united kingdom": "indeed.co.uk", "britain": "indeed.co.uk",
        "germany": "de.indeed.com", "de": "de.indeed.com", "deutschland": "de.indeed.com",
        "france": "indeed.fr", "fr": "indeed.fr",
        "italy": "it.indeed.com", "it": "it.indeed.com",
        "spain": "indeed.es", "es": "indeed.es",
        "netherlands": "indeed.nl", "nl": "indeed.nl", "holland": "indeed.nl",
        
        # Asia / Middle East
        "uae": "ae.indeed.com", "united arab emirates": "ae.indeed.com", "dubai": "ae.indeed.com",
        "india": "in.indeed.com", "in": "in.indeed.com",
        "pakistan": "pk.indeed.com", "pk": "pk.indeed.com",
        "japan": "jp.indeed.com", "jp": "jp.indeed.com",
        "singapore": "indeed.com.sg", "sg": "indeed.com.sg",
        
        # Oceania
        "australia": "au.indeed.com", "au": "au.indeed.com",
        "new zealand": "indeed.co.nz", "nz": "indeed.co.nz"
    }
    
    # 2. Return match OR Default to Global (indeed.com)
    return mapping.get(c, "indeed.com")

# ------------------- Main Agent Tool -------------------

@tool
def run_headhunter_agent(job_title: str, country: str, location: str, job_limit: int):
    """
    Runs the autonomous job search.
    Mandatory parameters:
    - job_title: e.g. "AI Engineer"
    - country: e.g. "UAE", "USA", "UK" (Critical for correct domain)
    - location: e.g. "Dubai", "London"
    - job_limit: Maximum number of jobs to apply for (must be >0)
    """

    # 1. VALIDATION
    if not all([job_title, country, location]):
        return "❌ Error: Missing arguments. I need Job Title, Country, and Location."
    
    if not isinstance(job_limit, int) or job_limit <= 0:
        return "❌ Error: job_limit must be a positive integer."

    # 2. PAYMENT GATE (HITL)
    cost = job_limit * 2.0
    print(f"\n✋ STOP! Checking Payment Authorization...")
    print(f"   Request: {job_limit} jobs x $2 = ${cost} Total.")

    user_decision = interrupt(f"Please approve the charge of ${cost} for {job_limit} applications. (yes/no)")

    if str(user_decision).lower() not in ['yes', 'y', 'confirm', 'ok']:
        return "❌ Transaction Cancelled. User declined the payment."

    print(f"✅ Payment Approved! Starting Agent for {job_limit} jobs...")

    # 3. SETUP
    my_resume = _read_my_resume()
    if not my_resume:
        return "❌ Error: 'resume.txt' not found."

    # RESTORED GROQ (Unless you really want OpenAI, then swap this line)
    # llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    driver = uc.Chrome(headless=False, use_subprocess=True, version_main=143)

    try:
        # 4. INTELLIGENT DOMAIN SELECTION
        domain = _get_smart_domain(country)
        # Handle full URL if map returned full domain, or construct it
        base_url = domain if "http" in domain else f"https://{domain}"
        
        print(f"🚀 AGENT ACTIVATED: Searching '{job_title}' in '{location}' on {base_url}...")
        
        url = f"{base_url}/jobs?q={job_title.replace(' ', '+')}&l={location}"
        driver.get(url)

        print("\n🛑 MANUAL CHECK: Click Cloudflare if needed. Press ENTER in terminal when jobs are visible.")
        input("✅ Press ENTER to continue...")

        # 5. SCRAPING
        job_cards = driver.find_elements(By.CSS_SELECTOR, "h2.jobTitle a")
        if not job_cards:
            job_cards = driver.find_elements(By.CLASS_NAME, "jcs-JobTitle")
        if not job_cards:
            job_cards = driver.find_elements(By.XPATH, "//a[contains(@href, '/viewjob') or contains(@href, '/rc/clk')]")

        # Clean Links
        job_links = []
        for job in job_cards:
            try:
                href = job.get_attribute("href")
                if href:
                    if "jk=" in href:
                        job_id = href.split("jk=")[1].split("&")[0]
                        # Construct link using the detected domain
                        clean_domain = domain.replace("https://", "").replace("/", "")
                        job_links.append(f"https://{clean_domain}/viewjob?jk={job_id}")
                    else:
                        job_links.append(href)
            except:
                continue

        job_links = list(set(job_links))[:job_limit]

        # 6. ANALYSIS
        good_matches = 0
        with open("good_jobs.txt", "w", encoding="utf-8") as f:
            f.write(f"=== HEADHUNTER REPORT: {job_title} in {location} ({country}) ===\n")
            f.write(f"Domain: {domain}\n\n")

        for i, link in enumerate(job_links):
            print(f"[{i+1}/{len(job_links)}] Checking...")
            try:
                driver.get(link)
                time.sleep(2)

                try:
                    jd = driver.find_element(By.ID, "jobDescriptionText").text
                except:
                    jd = driver.find_element(By.TAG_NAME, "body").text[:4000]

                prompt = f"""
                RESUME: {my_resume[:2000]}
                JOB: {jd[:2000]}
                TASK: Analyze match. Format: "SCORE: 85%" then a summary.
                """
                response = llm.invoke([HumanMessage(content=prompt)]).content
                score = _extract_score(response)

                print(f"   👉 Score: {score}%")

                if score >= MATCH_THRESHOLD:
                    good_matches += 1
                    with open("good_jobs.txt", "a", encoding="utf-8") as f:
                        f.write(f"🔗 JOB LINK: {link}\n🤖 ANALYSIS:\n{response}\n")
                        f.write("-" * 20 + " FULL JOB DESCRIPTION " + "-" * 20 + "\n")
                        f.write(f"{jd}\n")
                        f.write("=" * 50 + "\n\n")
            
            except Exception as e:
                print(f"⚠️ Error checking job: {e}")

    except Exception as e:
        return f"Agent failed: {str(e)}"
    finally:
        try:
            # Force kill the browser process to avoid WinError 6
            driver.quit()
        except OSError:
            pass  # Ignore Windows "Handle Invalid" errors
        except Exception:
            pass

    return f"✅ DONE! Processed {len(job_links)} jobs. Found {good_matches} matches."


@tool
def read_good_jobs_report():
    """Reads the 'good_jobs.txt' file."""
    try:
        if not os.path.exists("good_jobs.txt"):
            return "❌ No job report found."
        with open("good_jobs.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"