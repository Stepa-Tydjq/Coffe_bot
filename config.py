import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
WEBAPP_URL = os.getenv('WEBAPP_URL')
PORT = int(os.getenv('PORT', 3000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")
if not ADMIN_BOT_TOKEN:
    raise ValueError("ADMIN_BOT_TOKEN not found in .env file")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID not found in .env file")
if not WEBAPP_URL:
    raise ValueError("WEBAPP_URL not found in .env file")

print(f"✅ Конфигурация загружена:")
print(f"   BOT_TOKEN: {BOT_TOKEN[:10]}...")
print(f"   ADMIN_BOT_TOKEN: {ADMIN_BOT_TOKEN[:10]}...")
print(f"   ADMIN_CHAT_ID: {ADMIN_CHAT_ID}")
print(f"   WEBAPP_URL: {WEBAPP_URL}")
print(f"   PORT: {PORT}")