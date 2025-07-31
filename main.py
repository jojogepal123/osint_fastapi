import sys, uuid
import os, requests
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from telegram import check_telegram_number
from typing import List, Dict, Any, Optional
from jinja2 import Template
from openai import OpenAI
from ghunt_runner import GHuntRunner
import pdfkit
from pathlib import Path
import json, tempfile
import httpx

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  
ZEHEF_PATH = os.path.join(BASE_DIR, "Zehef")


# Configure Logging
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)    
logger = logging.getLogger(__name__)

app = FastAPI()

ghunt_runner = GHuntRunner()

if not os.path.exists("profile_photos"):
    os.makedirs("profile_photos", exist_ok=True)

# Mount the folder
app.mount("/profile_photos", StaticFiles(directory="profile_photos"), name="profile_photos")
# Request Model

class EmailRequest(BaseModel):
    email: EmailStr 

class PhoneRequest(BaseModel):
    phone : str

@app.post("/api/zehef/")
async def search_zehef(request: EmailRequest):
    """API Endpoint to check an email using Zehef"""

    email = request.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    sys.path.insert(0, ZEHEF_PATH)

    try:
        from lib.cli import parser  # Import here to avoid conflicts
    except ImportError as e:
        logger.critical(f"Failed to import Zehef parser: {e}")
        return {"status": "error", "message": "Zehef parser not found."}

    py_version = sys.version_info
    py_require = (3, 10)

    if py_version < py_require:
        return {"status": "error", "message": f"Zehef doesn't work with Python versions lower than 3.10."}
    
    result = await parser(email)
    return JSONResponse(status_code=200, content=result)


# 🔹 *Telegram API*
@app.post("/api/telegram/")
async def search_telegram(request: PhoneRequest):
    phone_number = request.phone.strip()
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required.")

    try:
        result = await check_telegram_number(phone_number)
        logger.debug(result)
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        logger.error(f"Telegram check failed for {phone_number}: {e}")
        return {"status": "error", "message": "Failed to check Telegram number."}


# 🔹 **Email Check API**
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    try:
        body = await request.json()
        email = body.get("email", "<no-email-provided>")
    except Exception:
        email = "<could-not-parse-body>"

    logger.error(f"Validation error for email '{email}': {exc.errors()}")

    # Return standard 422 response
    return await request_validation_exception_handler(request, exc)

@app.post("/api/holehe/")
async def check_email(data: EmailRequest):
    try:
        proc = await asyncio.create_subprocess_exec(
            "holehe", data.email,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"Holehe error for email '{data.email}': {stderr.decode().strip()}")
            raise HTTPException(status_code=500, detail=stderr.decode().strip())

        output_lines = stdout.decode().strip().split("\n")
        categories = {
            "used": [],
            "not used": [],
            "rate limited": [],
            "error": []
        }

        statuses = {
            "[+]": "used",
            "[-]": "not used",
            "[x]": "rate limited",
            "[!]": "error"
        }

        for line in output_lines:
            for symbol, status in statuses.items():
                if line.strip().startswith(symbol):
                    service = line.split(symbol)[-1].strip()
            
                    if "gravatar.com" in service:
                        categories[status].append("gravatar.com")
                        break
                    elif "twitter.com" in service:
                        categories[status].append("X (Twitter)")
                        break
                    else:
                        categories[status].append(service)
                        break       


        unwanted_line = "Email used, [-] Email not used, [x] Rate limit"
        if unwanted_line in categories["used"]:
             categories["used"].remove(unwanted_line)

        # Log only email and status code
        logger.info(f"holehe check success for '{data.email}' - Status Code: 200")
        logger.debug(f"Categories: {categories}")
        return JSONResponse(status_code=200, content=categories)

    except Exception as e:
        logger.exception(f"Exception during holehe check for email '{data.email}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/gmail")
async def gmail_search(request: EmailRequest):
    result = await ghunt_runner.run_email_scan(request.email)
    
    if "error" in result:
        logger.error(f"Error in gmail scan {result["error"]}")
        raise HTTPException(status_code=500,detail=result["error"])
    
    person_id = result.get("data", {}).get("PROFILE_CONTAINER", {}).get("profile", {}).get("personId")
    # logger.info(f"Person ID found: {person_id}")
    if person_id:
        maps_result = await google_maps(GoogleMapsRequest(contributor_id=person_id))
        result["maps_result"] = maps_result
        
    return JSONResponse(status_code=200, content=result)

async def email_scan(email):
        # Create a temporary file for JSON output
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            output_path = tmp_file.name
        try:
            cmd = [
                "socialscan",
                email,
                "--available-only",
                "--json",
                output_path
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {"error": stderr.decode().strip()}
            # Load the JSON file result
            with open(output_path, "r") as f:
                data = json.load(f)
            return {"data": data}
        except Exception as e:
            return {"error": str(e)}
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

@app.post("/api/socialscan")
async def handle_socialscan(request: EmailRequest):
    result = await email_scan(request.email)

    if "error" in result:
        logger.error(f"Error in gmail scan {result["error"]}")
        raise HTTPException(status_code=500,detail=result["error"])
    return JSONResponse(status_code=200, content=result)

class PhoneIgRequest(BaseModel):
    phone: str
    country_code: str

@app.post("/api/ignorant")
async def ignorant_search(request: PhoneIgRequest):
    phone = request.phone.strip()
    country_code = request.country_code.strip()

    if not phone or not country_code:
        raise HTTPException(status_code=400, detail="Phone number and country code are required.")

    try:
        from ignorant.modules.shopping.amazon import amazon
        from ignorant.modules.social_media.instagram import instagram
        from ignorant.modules.social_media.snapchat import snapchat

        out = []
        async with httpx.AsyncClient() as client:
            tasks = [
                amazon(phone, country_code, client, out),
                instagram(phone, country_code, client, out),
                snapchat(phone, country_code, client, out),
            ]
            await asyncio.gather(*tasks)
        return JSONResponse(status_code=200, content=out)
    except Exception as e:
        logger.error(f"Error in ignorant search for {phone}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

SERP_API_KEY = os.getenv("SERP_API_KEY")
SERP_API_URL = os.getenv("SERP_API_URL")

class GoogleMapsRequest(BaseModel):
    contributor_id: str

async def google_maps(request: GoogleMapsRequest):
    if not request.contributor_id.strip():
        raise HTTPException(status_code=400, detail="Contributor ID is required.")

    if not SERP_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="SERPAPI_KEY is not configured on the server. Please set the environment variable."
        )

    url = SERP_API_URL
    params = {
        "engine": "google_maps_contributor_reviews",
        "contributor_id": request.contributor_id,
        "api_key": SERP_API_KEY,
        "hl": "en",
        "gl": "in",
        "num": "100"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to fetch data from SerpApi: {e}"
        )

    data = response.json()
    reviews_data = data.get("reviews", [])

    extracted_reviews = []
    for review in reviews_data:
        place = review.get("place_info", {})
        gps_coords = place.get("gps_coordinates", {})
        extracted_reviews.append({
            "name": place.get("title"),
            "address": place.get("address"),
            "latitude": gps_coords.get("latitude"),
            "longitude": gps_coords.get("longitude"),
            "date": review.get("date")
        })
    return {
        "contributor_id": request.contributor_id,
        "reviews": extracted_reviews
    }