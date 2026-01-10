import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.messages import GetCommonChatsRequest
from telethon.tl.types import InputPhoneContact

# ================= LOAD ENV =================
load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

if not API_ID or not API_HASH:
    raise RuntimeError("TELEGRAM_API_ID or TELEGRAM_API_HASH not set in .env")

API_ID = int(API_ID)

# ================= CONFIG =================
SESSION_NAME = "session"
PHOTO_DIR = "Telegram_photos"
os.makedirs(PHOTO_DIR, exist_ok=True)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ================= HELPERS =================
def clean_name(value):
    """Remove local contact alias like Temp / Contact"""
    if value in ("Temp", "Contact", "", None):
        return None
    return value


def build_display_name(user):
    """
    Priority:
    1. Username
    2. First + Last name
    3. First name
    4. Fallback
    """
    if user.username:
        return f"@{user.username}"

    first = clean_name(user.first_name)
    last = clean_name(user.last_name)

    if first and last:
        return f"{first} {last}"

    if first:
        return first

    return "Telegram User"


# ================= START / STOP =================
async def start_client():
    if not client.is_connected():
        await client.start()


async def stop_client():
    if client.is_connected():
        await client.disconnect()


# ================= MUTUAL GROUPS =================
async def get_mutual_groups(user_id: int, limit: int = 50):
    """
    Get groups/channels where BOTH you and the user are members
    (Telegram privacy-safe)
    """
    try:
        result = await client(GetCommonChatsRequest(
            user_id=user_id,
            max_id=0,
            limit=limit
        ))

        groups = []
        for chat in result.chats:
            groups.append({
                "id": chat.id,
                "title": chat.title,
                "type": "channel" if getattr(chat, "broadcast", False) else "group"
            })

        return groups

    except Exception:
        # Some users restrict this – return empty safely
        return []


# ================= MAIN FUNCTION =================
async def lookup_telegram_user(phone: str):
    # 1️⃣ Import contact
    contact = InputPhoneContact(
        client_id=0,
        phone=phone,
        first_name="Temp",
        last_name="Contact"
    )

    result = await client(ImportContactsRequest([contact]))

    if not result.users:
        return {"status": "not_found"}

    contact_user = result.users[0]

    # 2️⃣ Full user data
    full = await client(GetFullUserRequest(contact_user.id))
    real_user = full.users[0]

    # 3️⃣ Download profile photos
    photos = await client.get_profile_photos(real_user)
    photo_files = []

    for i, photo in enumerate(photos):
        path = os.path.join(
            PHOTO_DIR,
            f"profile_{real_user.id}_{i}.jpg"
        )
        await client.download_media(photo, file=path)
        photo_files.append(path)

    # 4️⃣ Get mutual groups (privacy-safe)
    mutual_groups = await get_mutual_groups(real_user.id)

    # 5️⃣ Cleanup contact (VERY IMPORTANT)
    await client(DeleteContactsRequest([real_user.id]))

    # 6️⃣ Return clean data
    return {
        "status": "success",
        "user_id": real_user.id,
        "username": real_user.username,
        "first_name": clean_name(real_user.first_name),
        "last_name": clean_name(real_user.last_name),
        "display_name": build_display_name(real_user),
        "bio": full.full_user.about,
        "phone_visible": contact_user.phone,
        "verified": real_user.verified,
        "bot": real_user.bot,
        "photos": photo_files,
        "mutual_groups_count": len(mutual_groups),
        "mutual_groups": mutual_groups
    }
