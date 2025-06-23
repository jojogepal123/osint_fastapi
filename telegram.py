# telegram.py
from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.tl.functions.users import GetFullUserRequest
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv() 

api_id = os.getenv("TELEGRAM_ID")
api_hash = os.getenv("TELEGRAM_HASH")

client = TelegramClient('session', api_id, api_hash)

async def check_telegram_number(phone_number: str):
    await client.start()
    contact = InputPhoneContact(client_id=0, phone=phone_number, first_name='Check', last_name='User')
    result = await client(ImportContactsRequest([contact]))
    
    if result.users:
        user = result.users[0]
        full = await client(GetFullUserRequest(user.id))
        status = user.status.__class__.__name__ if user.status else "Unknown"

        profile_photo_path = None
        if user.photo:
            os.makedirs("profile_photos", exist_ok=True)
            file_name = f"{user.id}.jpg"
            profile_photo_path = f"profile_photos/{user.id}.jpg"
            await client.download_profile_photo(user, file=profile_photo_path)

        return {
            "found": True,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "user_id": user.id,
            "status": status,
            "profile_photo": file_name if profile_photo_path else None,
        }
    else:
        return {"found": False}
