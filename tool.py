import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
import re
import os

# Load API Keys
load_dotenv()

# ================= CONFIGURATION =================
MATCH_THRESHOLD = 50   # Save jobs with a score higher than this
MAX_JOBS_TO_CHECK = 15 # How many jobs to scan
# =================================================

def read_my_resume():
    """Reads your resume from the text file"""
    try:
        with open("resume.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None

def extract_score(text):
    """Helper to find the number in the AI response"""
    match = re.search(r"SCORE:\s*(\d+)%", text)
    if not match:
        match = re.search(r"(\d+)%", text) # Fallback if AI forgets "SCORE:"
    
    if match:
        return int(match.group(1))
    return 0

def run_agent():
    print("🤖 AGENT ACTIVATED: 'The Headhunter'")
    print(f"🎯 Goal: Find jobs with > {MATCH_THRESHOLD}% match.")
    
    # 1. Load Resume
    my_resume = read_my_resume()
    if not my_resume:
        print("❌ ERROR: 'resume.txt' not found! Please create it.")
        return

    # 2. Setup Brain (Groq) & Eyes (Browser)
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    
    # NOTE: headless=False is required to bypass Indeed's bot detection
    driver = uc.Chrome(headless=False, use_subprocess=True, version_main=143)
    
    print("\n👀 Phase 1: Scouting Jobs...")
    driver.get("https://ae.indeed.com/jobs?q=AI+Engineer&l=Dubai")
    
    # Wait for Cloudflare/Indeed to settle
    time.sleep(8)
    
    # --- ROBUST SELECTOR STRATEGY (Finds links even if Indeed changes layout) ---
    job_cards = driver.find_elements(By.CSS_SELECTOR, "h2.jobTitle a")
    
    if len(job_cards) == 0:
        print("   ⚠️ Standard selector failed. Trying Backup #1...")
        job_cards = driver.find_elements(By.CLASS_NAME, "jcs-JobTitle")
        
    if len(job_cards) == 0:
        print("   ⚠️ Backup #1 failed. Trying Backup #2 (Deep Scan)...")
        all_links = driver.find_elements(By.TAG_NAME, "a")
        job_cards = [link for link in all_links if "rc/clk" in link.get_attribute("href") or "viewjob" in link.get_attribute("href")]

    print(f"✅ Found {len(job_cards)} jobs. Checking top {MAX_JOBS_TO_CHECK}...")
    
    # Extract and Clean Links
    job_links = []
    for job in job_cards[:MAX_JOBS_TO_CHECK]:
        try:
            link = job.get_attribute("href")
            # Convert messy redirect links to clean 'viewjob' links
            if link and "jk=" in link:
                job_id = link.split("jk=")[1].split("&")[0]
                clean_link = f"https://ae.indeed.com/viewjob?jk={job_id}"
                job_links.append(clean_link)
            elif link:
                job_links.append(link)
        except:
            continue

    # Remove duplicates
    job_links = list(set(job_links))

    print("\n🧠 Phase 2: Analyzing Candidates...")
    
    # Prepare the Report File
    with open("good_jobs.txt", "w", encoding="utf-8") as f:
        f.write("=== MY HEADHUNTER REPORT ===\n\n")

    # 3. Analyze Each Job
    for i, link in enumerate(job_links):
        print(f"\n[{i+1}/{len(job_links)}] Checking Job...")
        
        try:
            driver.get(link)
            time.sleep(4)
            
            # --- CRITICAL FIX: Handle External Links ---
            try:
                # Try to find the description text
                jd_element = driver.find_element(By.ID, "jobDescriptionText")
                jd = jd_element.text
            except:
                # If ID not found, it's likely an external website (Workday, Greenhouse, etc.)
                print("   ⚠️ External Link or different layout. Skipping.")
                continue 
            
            # Ask AI to Analyze
            prompt = f"""
            RESUME: {my_resume[:2000]}
            JOB: {jd[:2000]}
            
            TASK: Analyze this match.
            FORMAT YOUR RESPONSE EXACTLY LIKE THIS:
            SCORE: [Number]%
            SUMMARY: [1 sentence on why I fit]
            MISSING: [1 skill I am missing]
            """
            response = llm.invoke([HumanMessage(content=prompt)]).content
            
            # Extract Score
            score = extract_score(response)
            print(f"   👉 Score: {score}%")
            
            # Save or Skip
            if score >= MATCH_THRESHOLD:
                print("   ✅ MATCH! Saving detailed report...")
                with open("good_jobs.txt", "a", encoding="utf-8") as f:
                    f.write(f"JOB LINK: {link}\n")
                    f.write(f"{response}\n") 
                    f.write("-" * 40 + "\n")
            else:
                print("   ❌ Low match. Skipping.")
                
        except Exception as e:
            print(f"   ⚠️ Unexpected Error: {e}")

    print("\n✅ DONE! Open 'good_jobs.txt' to see your briefing.")
    
    # Safe Exit (Prevents WinError 6 noise)
    try:
        driver.quit()
    except:
        pass

if __name__ == "__main__":
    run_agent()