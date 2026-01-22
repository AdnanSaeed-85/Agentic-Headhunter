import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from dotenv import load_dotenv
import re
import os

load_dotenv()
MATCH_THRESHOLD = 50

# --- Helper Functions ---
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
    c = country_input.lower().strip()
    mapping = {
        "usa": "indeed.com", "us": "indeed.com", "united states": "indeed.com",
        "canada": "ca.indeed.com",
        "uk": "indeed.co.uk", "united kingdom": "indeed.co.uk",
        "uae": "ae.indeed.com", "dubai": "ae.indeed.com",
        "india": "in.indeed.com",
        "pakistan": "pk.indeed.com",
        "australia": "au.indeed.com"
    }
    return mapping.get(c, "indeed.com")

# --- Main Tool ---
@tool
def run_headhunter_agent(job_title: str, country: str, location: str, job_limit: int):
    """
    Runs the autonomous job search. 
    Use this to find jobs on Indeed.
    """
    if not all([job_title, country, location]):
        return "❌ Error: Missing arguments."
    
    print(f"🚀 AGENT STARTING: {job_title} in {location}, {country}...")
    
    my_resume = _read_my_resume()
    if not my_resume:
        return "❌ Error: 'resume.txt' not found. Please create a resume.txt file in the project directory."

    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    
    # Initialize driver with better options
    options = uc.ChromeOptions()
    # options.add_argument('--headless')  # Uncomment to run without UI
    driver = None

    try:
        driver = uc.Chrome(headless=False, use_subprocess=True, version_main=143)
        wait = WebDriverWait(driver, 10)
        
        domain = _get_smart_domain(country)
        base_url = domain if "http" in domain else f"https://{domain}"
        
        # Build search URL
        url = f"{base_url}/jobs?q={job_title.replace(' ', '+')}&l={location.replace(' ', '+')}"
        print(f"🔍 Searching: {url}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(8)  # Increased wait time for Indeed to load
        
        # Try multiple selectors for job cards
        job_cards = []
        try:
            # Try modern Indeed selector first
            job_cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "h2.jobTitle a")))
        except:
            try:
                # Fallback selector
                job_cards = driver.find_elements(By.CLASS_NAME, "jcs-JobTitle")
            except:
                try:
                    # Another fallback
                    job_cards = driver.find_elements(By.CSS_SELECTOR, "a[data-jk]")
                except Exception as e:
                    print(f"❌ Could not find job cards: {e}")
        
        if not job_cards:
            # Take screenshot for debugging
            driver.save_screenshot("debug_screenshot.png")
            print("❌ No job cards found. Screenshot saved as debug_screenshot.png")
            return f"❌ No jobs found for '{job_title}' in {location}. The page might have a different structure. Check debug_screenshot.png"
        
        print(f"✅ Found {len(job_cards)} job cards")
        
        # Extract job links
        job_links = []
        for job in job_cards[:job_limit * 3]:  # Get more links than needed as backup
            try:
                href = job.get_attribute("href")
                if href and "jk=" in href:
                    job_id = href.split("jk=")[1].split("&")[0]
                    clean_domain = domain.replace("https://", "").replace("/", "")
                    job_links.append(f"https://{clean_domain}/viewjob?jk={job_id}")
                elif href and "/rc/clk" in href:
                    # Alternative Indeed link format
                    job_links.append(href)
            except Exception as e:
                print(f"⚠️ Error extracting link: {e}")
                continue

        job_links = list(set(job_links))[:job_limit]
        
        if not job_links:
            return f"❌ Could not extract job links from {len(job_cards)} cards found."
        
        print(f"📋 Processing {len(job_links)} job links...")
        
        good_matches = 0
        
        # Create report file
        with open("good_jobs.txt", "w", encoding="utf-8") as f:
            f.write(f"=== JOB SEARCH REPORT ===\n")
            f.write(f"Job Title: {job_title}\n")
            f.write(f"Location: {location}, {country}\n")
            f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Process each job
        for i, link in enumerate(job_links):
            print(f"🔍 Analyzing job {i+1}/{len(job_links)}...")
            try:
                driver.get(link)
                time.sleep(3)  # Wait for job page to load
                
                # Extract job description with multiple fallback strategies
                jd = ""
                try:
                    jd = wait.until(EC.presence_of_element_located((By.ID, "jobDescriptionText"))).text
                except:
                    try:
                        jd = driver.find_element(By.CLASS_NAME, "jobsearch-jobDescriptionText").text
                    except:
                        try:
                            jd = driver.find_element(By.TAG_NAME, "body").text[:5000]
                        except:
                            print(f"⚠️ Could not extract job description for {link}")
                            continue
                
                if not jd or len(jd) < 100:
                    print(f"⚠️ Job description too short, skipping...")
                    continue
                
                # Get job title from page
                try:
                    job_title_elem = driver.find_element(By.CSS_SELECTOR, "h1.jobsearch-JobInfoHeader-title")
                    actual_title = job_title_elem.text
                except:
                    actual_title = job_title

                # Score the match using LLM
                prompt = f"""You are a resume matching expert. Score how well this resume matches this job (0-100%).

RESUME:
{my_resume[:3000]}

JOB DESCRIPTION:
{jd[:3000]}

Respond ONLY with: SCORE: X%
Where X is a number between 0-100."""

                response = llm.invoke([HumanMessage(content=prompt)]).content
                score = _extract_score(response)
                
                print(f"   Score: {score}% - {actual_title}")

                if score >= MATCH_THRESHOLD:
                    good_matches += 1
                    with open("good_jobs.txt", "a", encoding="utf-8") as f:
                        f.write(f"\n{'='*60}\n")
                        f.write(f"Job #{good_matches}\n")
                        f.write(f"Title: {actual_title}\n")
                        f.write(f"Match Score: {score}%\n")
                        f.write(f"Link: {link}\n")
                        f.write(f"{'='*60}\n")
                        
            except Exception as e:
                print(f"⚠️ Error processing {link}: {str(e)}")
                continue

        print(f"\n✅ Search complete! Found {good_matches} good matches out of {len(job_links)} jobs analyzed.")
        
    except Exception as e:
        error_msg = f"❌ Agent failed: {str(e)}"
        print(error_msg)
        if driver:
            try:
                driver.save_screenshot("error_screenshot.png")
                print("Error screenshot saved as error_screenshot.png")
            except:
                pass
        return error_msg
        
    finally:
        if driver:
            try:
                print("🛑 Closing browser...")
                time.sleep(2)  # Give user time to see results
                driver.quit()
            except:
                pass

    if good_matches == 0:
        return f"✅ Search completed! Analyzed {len(job_links)} jobs but found no matches above {MATCH_THRESHOLD}% threshold. Try lowering your criteria or broadening the search."
    
    return f"✅ SUCCESS! Found {good_matches} matching job(s) out of {len(job_links)} analyzed. Check 'good_jobs.txt' for details."


@tool
def read_good_jobs_report():
    """Reads the 'good_jobs.txt' file to see found jobs."""
    try:
        with open("good_jobs.txt", "r", encoding="utf-8") as f:
            content = f.read()
            if not content or len(content) < 50:
                return "📄 Report exists but appears empty. No jobs have been found yet."
            return content
    except FileNotFoundError:
        return "❌ No report found. Run a job search first using the run_headhunter_agent tool."