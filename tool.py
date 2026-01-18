import undetected_chromedriver as uc
import time

def run():
    print("Launching Stealth Browser...")
    
    # This launches a REAL Chrome instance that bypasses bot detection
    driver = uc.Chrome(headless=False, use_subprocess=True)
    
    # Go to Indeed Dubai
    url = "https://ae.indeed.com/jobs?q=AI+Engineer&l=Dubai"
    driver.get(url)

    print("Browser open. If the checkbox appears, click it once (it should work now).")
    
    # Keep the browser open so you can see the result
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Closing...")
        driver.quit()

if __name__ == "__main__":
    run()