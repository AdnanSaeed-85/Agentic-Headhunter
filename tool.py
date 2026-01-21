import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from dotenv import load_dotenv
import re
import os
from langgraph.types import interrupt  # <--- NEW IMPORT

# Load API Keys
load_dotenv()

# Config
MATCH_THRESHOLD = 50

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

@tool
def run_headhunter_agent(job_title: str, location: str, job_limit: int):
    """
    Runs the autonomous job search.
    Requires:
    - job_title: e.g. "AI Engineer"
    - location: e.g. "Dubai"
    - job_limit: The maximum number of jobs to apply for.
    """
    # --- 1. HUMAN IN THE LOOP (PAYMENT GATE) ---
    cost = job_limit * 2
    print(f"\n✋ STOP! Checking Payment Authorization...")
    print(f"   Request: {job_limit} jobs x $2 = ${cost} Total.")
    
    # This PAUSES the entire system until the user answers in main.py
    user_decision = interrupt(f"Please approve the charge of ${cost} for {job_limit} applications. (yes/no)")
    
    if user_decision.lower() not in ['yes', 'y', 'confirm']:
        return "❌ Transaction Cancelled. User declined the payment."
    
    print(f"✅ Payment Approved! Starting Agent for {job_limit} jobs...")

    # --- 2. THE AGENT LOGIC ---
    print(f"🚀 AGENT ACTIVATED: Searching for '{job_title}' in '{location}'...")
    
    my_resume = _read_my_resume()
    if not my_resume:
        return "❌ Error: 'resume.txt' not found."

    # llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    driver = uc.Chrome(headless=False, use_subprocess=True, version_main=143)
    
    try:
        # SCOUTING
        url = f"https://ae.indeed.com/jobs?q={job_title.replace(' ', '+')}&l={location}"
        driver.get(url)
        
        print("\n🛑 MANUAL CHECK: Click Cloudflare if needed. Press ENTER in terminal when jobs are visible.")
        input("✅ Press ENTER to continue...")
        
        # Robust Selectors
        job_cards = driver.find_elements(By.CSS_SELECTOR, "h2.jobTitle a")
        if not job_cards:
            job_cards = driver.find_elements(By.CLASS_NAME, "jcs-JobTitle")
        if not job_cards:
             job_cards = driver.find_elements(By.XPATH, "//a[contains(@href, '/viewjob') or contains(@href, '/rc/clk')]")

        count_found = len(job_cards)
        
        # Clean Links
        job_links = []
        for job in job_cards:
            try:
                href = job.get_attribute("href")
                if href:
                    if "jk=" in href:
                        job_id = href.split("jk=")[1].split("&")[0]
                        job_links.append(f"https://ae.indeed.com/viewjob?jk={job_id}")
                    else:
                        job_links.append(href)
            except:
                continue
        
        job_links = list(set(job_links))
        
        # LIMIT THE JOBS BASED ON USER INPUT
        job_links = job_links[:job_limit] 

        # ANALYZING
        good_matches = 0
        with open("good_jobs.txt", "w", encoding="utf-8") as f:
            f.write(f"=== HEADHUNTER REPORT: {job_title} in {location} (Limit: {job_limit}) ===\n\n")
        
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
                print(f"Skipping job: {e}")

    except Exception as e:
        return f"Agent failed: {str(e)}"
    finally:
        try:
            driver.quit()
        except:
            pass

    return f"✅ DONE! Processed {len(job_links)} jobs (Cost: ${cost}). Found {good_matches} matches."

@tool
def read_good_jobs_report():
    """Please Reads the 'good_jobs.txt' file."""
    try:
        if not os.path.exists("good_jobs.txt"):
            return "❌ No job report found."
        with open("good_jobs.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"