import argparse
import time
import logging
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Page
from src.config.database import SessionLocal
from src.models.job import Job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def determine_listing_type(title: str) -> str:
    title_lower = title.lower()
    if "intern" in title_lower or "internship" in title_lower:
        return "internship"
    return "job"

def get_company_name(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split('/') if p]
    if parts:
        return parts[0].capitalize()
    return "Unknown"

def scrape_lever(url: str, mode: str):
    logger.info(f"Starting Lever scrape for {url}")
    company_name = get_company_name(url)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        
        job_links = []
        postings = page.query_selector_all("a.posting-title")
        for posting in postings:
            href = posting.get_attribute("href")
            if href:
                job_links.append(href)
                
        logger.info(f"Found {len(job_links)} job listings.")
        
        db = SessionLocal()
        
        for link in job_links:
            time.sleep(1) # Rate limiting
            try:
                page.goto(link)
                page.wait_for_load_state("domcontentloaded")
                
                title_el = page.query_selector("h2")
                role_title = title_el.inner_text().strip() if title_el else "Unknown Title"
                
                loc_el = page.query_selector(".location")
                location = loc_el.inner_text().strip() if loc_el else None
                
                jd_el = page.query_selector(".content, .section-wrapper, [data-qa='job-description']")
                jd_text = jd_el.inner_text().strip() if jd_el else "No description"
                
                listing_type = determine_listing_type(role_title)
                
                if mode != "all" and listing_type != mode:
                    continue
                
                # Check if job exists
                existing_job = db.query(Job).filter(Job.application_url == link).first()
                if not existing_job:
                    job = Job(
                        company_name=company_name,
                        role_title=role_title,
                        jd_text=jd_text,
                        location=location,
                        application_url=link,
                        listing_type=listing_type,
                        source="lever"
                    )
                    db.add(job)
                    logger.info(f"Saved job: {role_title}")
                else:
                    logger.info(f"Job already exists: {role_title}")
                
                db.commit()
            except Exception as e:
                logger.error(f"Error scraping {link}: {e}")
                db.rollback()
                
        browser.close()
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Lever careers page.")
    parser.add_argument("--url", required=True, help="Lever company careers URL")
    parser.add_argument("--mode", required=True, choices=["job", "internship", "all"], help="Listing mode to fetch")
    args = parser.parse_args()
    
    scrape_lever(args.url, args.mode)
