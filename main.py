import sys, uuid, secrets
import os, requests
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Request, Security, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, EmailStr
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from typing import List, Dict, Any, Optional
from jinja2 import Template
from openai import OpenAI
from ghunt_runner import GHuntRunner
import pdfkit
from pathlib import Path
import json, tempfile
import httpx
from telegram import start_client, stop_client, lookup_telegram_user

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  
ZEHEF_PATH = os.path.join(BASE_DIR, "Zehef")


# Configure Logging
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)  
logging.getLogger("telethon").setLevel(logging.WARNING)  
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── API Key Auth ──────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(key: str = Security(api_key_header)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API_KEY is not configured on the server.")
    if not key or not secrets.compare_digest(key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    await start_client()
    logger.info("Telegram client started")

@app.on_event("shutdown")
async def shutdown_event():
    await stop_client()
    logger.info("Telegram client stopped")

ghunt_runner = GHuntRunner()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Mount the folder
# Mount Telegram photos folder
if not os.path.exists("Telegram_photos"):
    os.makedirs("Telegram_photos", exist_ok=True)

app.mount(
    "/telegram_photos",
    StaticFiles(directory="Telegram_photos"),
    name="telegram_photos"
)



# Request Model

class EmailRequest(BaseModel):
    email: EmailStr 

class PhoneRequest(BaseModel):
    phone : str

@app.post("/api/zehef/", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def search_zehef(request: Request, body: EmailRequest):
    """API Endpoint to check an email using Zehef"""

    email = body.email.strip()
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



# ================= TELEGRAM API =================
@app.post("/api/telegram", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def telegram_api(request: Request, body: PhoneRequest):
    phone = body.phone.strip()

    if not phone.startswith("+"):
        raise HTTPException(
            status_code=400,
            detail="Phone number must include country code (e.g. +919XXXXXXXXX)"
        )

    try:
        result = await lookup_telegram_user(phone)
        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.exception(f"Telegram lookup failed for {phone}: {e}")
        raise HTTPException(status_code=500, detail="Telegram lookup failed")

# ================= VALIDATION HANDLER =================
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return await request_validation_exception_handler(request, exc)


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

@app.post("/api/holehe/", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def check_email(request: Request, data: EmailRequest):
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


RAPIDAPI_GOOGLE_KEY = os.getenv("RAPIDAPI_GOOGLE_KEY", "")

@app.post("/api/gmail", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def gmail_search(request: Request, body: EmailRequest):
    if not RAPIDAPI_GOOGLE_KEY:
        raise HTTPException(status_code=500, detail="RAPIDAPI_GOOGLE_KEY is not configured.")

    url = f"https://google-data.p.rapidapi.com/email/{body.email}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_GOOGLE_KEY,
        "x-rapidapi-host": "google-data.p.rapidapi.com",
    }
    params = {"noReviews": "true", "cached": "false"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            api_data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"RapidAPI HTTP error for {body.email}: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"RapidAPI error: {e.response.text}")
    except Exception as e:
        logger.exception(f"RapidAPI request failed for {body.email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    result = {"data": api_data}

    # Extract personId from PROFILE_CONTAINER.profile.personId
    person_id = (
        api_data.get("PROFILE_CONTAINER", {}).get("profile", {}).get("personId")
    )
    logger.info(f"Person ID found: {person_id}")

    if person_id:
        try:
            maps_result = await google_maps(GoogleMapsRequest(contributor_id=person_id))
            result["maps_result"] = maps_result
        except Exception as e:
            logger.warning(f"Google Maps lookup failed for contributor {person_id}: {e}")
            result["maps_result"] = None

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

@app.post("/api/socialscan", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def handle_socialscan(request: Request, body: EmailRequest):
    result = await email_scan(body.email)

    if "error" in result:
        logger.error(f"Error in gmail scan {result['error']}")
        raise HTTPException(status_code=500,detail=result["error"])
    return JSONResponse(status_code=200, content=result)

class PhoneIgRequest(BaseModel):
    phone: str
    country_code: str


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