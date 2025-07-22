# bot/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
DJANGO_DATABASE_URL = os.getenv('DJANGO_DATABASE_URL', 'sqlite:///backend/db.sqlite3')
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')

# Choose connection method
USE_DJANGO_ORM = True  # Set to False to use API instead