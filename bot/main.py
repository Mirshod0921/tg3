import asyncio
import logging
import aiohttp
import json
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, InputFile, FSInputFile
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.media_group import MediaGroupBuilder
import os
from datetime import datetime
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import asyncpg
from collections import defaultdict
from asyncio import create_task, sleep
from utils.translations import REGIONS_DATA, TRANSLATIONS, regions_config
from utils.templates import get_listing_template

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
CHANNEL_ID = os.getenv('CHANNEL_ID', '@your_channel')
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'database': os.getenv('DB_NAME', 'real_estate_db')
}

# Admin configuration
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = []

if ADMIN_IDS_STR:
    try:
        raw_ids = [admin_id.strip() for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
        ADMIN_IDS = [int(admin_id) for admin_id in raw_ids]
        logger.info(f"✅ Successfully parsed ADMIN_IDS: {ADMIN_IDS}")
        
        for admin_id in ADMIN_IDS:
            if admin_id <= 0:
                logger.warning(f"⚠️ Invalid admin ID: {admin_id}")
            else:
                logger.info(f"   Admin ID: {admin_id}")
                
    except ValueError as e:
        logger.error(f"❌ Error parsing ADMIN_IDS: {e}")
        logger.error(f"❌ ADMIN_IDS string was: '{ADMIN_IDS_STR}'")
        logger.error("❌ Please check your .env file format: ADMIN_IDS=1234567890,0987654321")
        ADMIN_IDS = []
else:
    logger.warning("⚠️ ADMIN_IDS not set in environment variables")
    logger.warning("⚠️ No admin access will be available!")

if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
    logger.error("❌ Please set BOT_TOKEN in .env file!")
    exit(1)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Database connection pool
db_pool = None


async def init_db_pool():
    """Initialize database connection pool"""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            min_size=10,
            max_size=20,
            command_timeout=60
        )
        logger.info("✅ Database pool initialized")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

async def close_db_pool():
    """Close database connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")

# Database operations with PostgreSQL
async def save_user(user_id: int, username: str, first_name: str, last_name: str, language: str = 'uz'):
    """Save or update user in database"""
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO real_estate_telegramuser (
                telegram_id, username, first_name, last_name, language, 
                is_blocked, balance, created_at, updated_at, is_premium
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW(), $8)
            ON CONFLICT (telegram_id) 
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                updated_at = NOW()
        ''', user_id, username or '', first_name or '', last_name or '', language, False, 0.00, False)

async def get_user_language(user_id: int) -> str:
    """Get user language preference"""
    async with db_pool.acquire() as conn:
        result = await conn.fetchval(
            'SELECT language FROM real_estate_telegramuser WHERE telegram_id = $1', 
            user_id
        )
        return result if result else 'uz'

async def update_user_language(user_id: int, language: str):
    """Update user language"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_telegramuser SET language = $1, updated_at = NOW() WHERE telegram_id = $2',
            language, user_id
        )

async def save_listing_with_makler(user_id: int, data: dict) -> int:
    """Save listing to database with makler information"""
    async with db_pool.acquire() as conn:
        # Get user database ID
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            raise Exception("User not found in database")
        
        # Prepare all required fields with proper defaults
        photo_file_ids = json.dumps(data.get('photo_file_ids', []))
        
        # Ensure title is not None
        title = data.get('title')
        if not title:
            description = data.get('description', 'No description')
            title = description.split('\n')[0][:50] + ('...' if len(description) > 50 else '')
        
        # Get makler status
        is_makler = data.get('is_makler', False)
        
        # Ensure all required fields have proper values
        description = data.get('description', 'No description')
        property_type = data.get('property_type', 'apartment')
        region = data.get('region', '')
        district = data.get('district', '')
        address = data.get('address', '')
        full_address = data.get('full_address', '')
        price = data.get('price', 0)
        area = data.get('area', 0)
        rooms = data.get('rooms', 0)
        condition = data.get('condition', '')
        status = data.get('status', 'sale')
        contact_info = data.get('contact_info', '')
        
        try:
            # Store makler information in admin_notes field
            makler_note = "makler" if is_makler else "maklersiz"
            
            listing_id = await conn.fetchval('''
                INSERT INTO real_estate_property (
                    user_id, title, description, property_type, region, district,
                    address, full_address, price, area, rooms, condition, status, 
                    contact_info, photo_file_ids, is_premium, is_approved, is_active,
                    views_count, admin_notes, approval_status, favorites_count,
                    posted_to_channel, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                    $16, $17, $18, $19, $20, $21, $22, $23, NOW(), NOW()
                )
                RETURNING id
            ''', 
                user_db_id,                           # user_id
                title,                                # title
                description,                          # description
                property_type,                        # property_type
                region,                               # region
                district,                             # district
                address,                              # address
                full_address,                         # full_address
                price,                                # price
                area,                                 # area
                rooms,                                # rooms
                condition,                            # condition
                status,                               # status
                contact_info,                         # contact_info
                photo_file_ids,                       # photo_file_ids
                False,                                # is_premium
                True,                                 # is_approved (auto-approve)
                True,                                 # is_active
                0,                                    # views_count
                makler_note,                          # admin_notes (store makler info)
                'approved',                           # approval_status
                0,                                    # favorites_count
                False                                 # posted_to_channel
            )
            
            logger.info(f"Successfully saved listing {listing_id} for user {user_id} (makler: {is_makler})")
            return listing_id
            
        except Exception as e:
            logger.error(f"Failed to save listing: {e}")
            raise Exception(f"Could not save listing. Database error: {str(e)}")

async def get_listings(limit=10, offset=0):
    """Get approved listings"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.is_approved = true AND p.is_active = true
            ORDER BY p.is_premium DESC, p.created_at DESC 
            LIMIT $1 OFFSET $2
        ''', limit, offset)

async def search_listings(query: str):
    """Search listings by keyword"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE (p.title ILIKE $1 OR p.description ILIKE $1 OR p.full_address ILIKE $1) 
            AND p.is_approved = true AND p.is_active = true
            ORDER BY p.is_premium DESC, p.created_at DESC 
            LIMIT 10
        ''', f'%{query}%')

async def search_listings_by_location(region_key=None, district_key=None, property_type=None):
    """Search listings by region, district and/or property type"""
    async with db_pool.acquire() as conn:
        query = '''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.is_approved = true AND p.is_active = true
        '''
        params = []
        param_count = 0
        
        if region_key:
            param_count += 1
            query += f' AND p.region = ${param_count}'
            params.append(region_key)
        
        if district_key:
            param_count += 1
            query += f' AND p.district = ${param_count}'
            params.append(district_key)
            
        if property_type:
            param_count += 1
            query += f' AND p.property_type = ${param_count}'
            params.append(property_type)
        
        query += ' ORDER BY p.is_premium DESC, p.created_at DESC LIMIT 10'
        
        return await conn.fetch(query, *params)

async def get_listing_by_id(listing_id: int):
    """Get listing by ID with user info"""
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.id = $1
        ''', listing_id)

async def add_to_favorites(user_id: int, listing_id: int):
    """Add listing to user's favorites"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if user_db_id:
            await conn.execute('''
                INSERT INTO real_estate_favorite (user_id, property_id, created_at) 
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id, property_id) DO NOTHING
            ''', user_db_id, listing_id)

async def get_user_favorites(user_id: int):
    """Get user's favorite listings"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            return []
        
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_favorite f
            JOIN real_estate_property p ON f.property_id = p.id
            JOIN real_estate_telegramuser u ON p.user_id = u.id
            WHERE f.user_id = $1 AND p.is_approved = true AND p.is_active = true
            ORDER BY f.created_at DESC
        ''', user_db_id)

async def get_user_postings(user_id: int):
    """Get all postings by user"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            return []
        
        return await conn.fetch('''
            SELECT p.*, 
                   (SELECT COUNT(*) FROM real_estate_favorite f WHERE f.property_id = p.id) as favorite_count
            FROM real_estate_property p 
            WHERE p.user_id = $1
            ORDER BY p.created_at DESC
        ''', user_db_id)

async def update_listing_status(listing_id: int, is_active: bool):
    """Update listing active status"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_property SET is_approved = $1, updated_at = NOW() WHERE id = $2',
            is_active, listing_id
        )

async def delete_listing(listing_id: int) -> dict:
    """Delete listing and return affected users"""
    async with db_pool.acquire() as conn:
        # Get users who favorited this listing
        favorite_users = await conn.fetch(
            'SELECT tu.telegram_id FROM real_estate_favorite f '
            'JOIN real_estate_telegramuser tu ON f.user_id = tu.id '
            'WHERE f.property_id = $1', listing_id
        )
        
        # Delete from favorites
        await conn.execute(
            'DELETE FROM real_estate_favorite WHERE property_id = $1', 
            listing_id
        )
        
        # Delete the listing
        await conn.execute(
            'DELETE FROM real_estate_property WHERE id = $1', 
            listing_id
        )
        
        return {
            'user_ids': [user['telegram_id'] for user in favorite_users]
        }
    
async def delete_listing_completely(listing_id: int) -> dict:
    """Completely delete listing and return affected user IDs and photo file IDs"""
    async with db_pool.acquire() as conn:
        # Get users who favorited this listing
        favorite_users = await conn.fetch(
            'SELECT tu.telegram_id FROM real_estate_favorite f '
            'JOIN real_estate_telegramuser tu ON f.user_id = tu.id '
            'WHERE f.property_id = $1', 
            listing_id
        )
        
        # Get photo file IDs before deleting
        photo_file_ids = await conn.fetchval(
            'SELECT photo_file_ids FROM real_estate_property WHERE id = $1',
            listing_id
        )
        
        # Delete from favorites first
        await conn.execute(
            'DELETE FROM real_estate_favorite WHERE property_id = $1', 
            listing_id
        )
        
        # Then delete the listing itself
        await conn.execute(
            'DELETE FROM real_estate_property WHERE id = $1', 
            listing_id
        )
        
        return {
            'user_ids': [user['telegram_id'] for user in favorite_users],
            'photo_file_ids': json.loads(photo_file_ids) if photo_file_ids else []
        }
# Admin functions
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# FSM States for new listing flow
class ListingStates(StatesGroup):
    property_type = State()      
    status = State()             
    makler_type = State()        # NEW: Ask if user is makler or not
    region = State()             
    district = State()
    price = State()              
    area = State()                           
    description = State()        
    confirmation = State()       
    contact_info = State()       
    photos = State()             

class SearchStates(StatesGroup):
    search_type = State()        
    keyword_query = State()      
    location_region = State()    
    location_district = State()
    property_type_filter = State()  # FIXED: Added missing state

class AdminStates(StatesGroup):
    reviewing_listing = State()
    writing_feedback = State()

# Media group collector for handling multiple photos
class MediaGroupCollector:
    def __init__(self):
        self.groups = defaultdict(list)
        self.timers = {}
    
    async def add_message(self, message: Message, state: FSMContext):
        if not message.media_group_id:
            return await self.process_single_photo(message, state)
        
        self.groups[message.media_group_id].append(message)
        
        if message.media_group_id in self.timers:
            self.timers[message.media_group_id].cancel()
        
        self.timers[message.media_group_id] = create_task(
            self.process_group_after_delay(message.media_group_id, state)
        )
    
    async def process_group_after_delay(self, group_id: str, state: FSMContext):
        await sleep(1.0)
        
        if group_id in self.groups:
            messages = self.groups[group_id]
            await self.process_media_group(messages, state)
            
            del self.groups[group_id]
            if group_id in self.timers:
                del self.timers[group_id]
    
    async def process_single_photo(self, message: Message, state: FSMContext):
        user_lang = await get_user_language(message.from_user.id)
        
        data = await state.get_data()
        photo_file_ids = data.get('photo_file_ids', [])
        photo_file_ids.append(message.photo[-1].file_id)
        await state.update_data(photo_file_ids=photo_file_ids)
        
        await message.answer(
            get_text(user_lang, 'photo_added_count', count=len(photo_file_ids))
        )
    
    async def process_media_group(self, messages: list, state: FSMContext):
        user_lang = await get_user_language(messages[0].from_user.id)
        
        data = await state.get_data()
        photo_file_ids = data.get('photo_file_ids', [])
        
        for msg in messages:
            if msg.photo:
                photo_file_ids.append(msg.photo[-1].file_id)
        
        await state.update_data(photo_file_ids=photo_file_ids)
        
        await messages[0].answer(
            get_text(user_lang, 'media_group_received', count=len(messages))
        )

# Initialize media collector
media_collector = MediaGroupCollector()

# FIXED SEARCH TRANSLATIONS - Combined all search-related translations
SEARCH_TRANSLATIONS = {
    'uz': {
        'choose_search_type': "🔍 Qidiruv turini tanlang:",
        'search_by_keyword': "📝 Kalit so'z bo'yicha qidiruv",
        'search_by_location': "🏘 Hudud bo'yicha qidiruv", 
        'search_prompt': "🔍 Qidirish uchun kalit so'z kiriting:",
        'select_region_for_search': "🗺 Qidiruv uchun viloyatni tanlang:",
        'select_district_or_all': "🏘 Tumanni tanlang yoki butun viloyat bo'yicha qidiring:",
        'all_region': "🌍 Butun viloyat",
        'search_results_count': "🔍 Qidiruv natijalari: {count} ta e'lon topildi",
        'no_search_results': "😔 Hech narsa topilmadi.\n\nBoshqa kalit so'z bilan yoki boshqa hudud bo'yicha qaytadan qidirib ko'ring.",
        'ask_price': "💰 E'lon narxini kiriting:\n\nMasalan: 50000, 50000$, 500 ming, 1.2 mln",
        'ask_area': "📐 Maydonni kiriting (m²):\n\nMasalan: 65, 65.5, 100",
        'invalid_price': "❌ Narx noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 50000, 75000",
        'invalid_area': "❌ Maydon noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 65, 100.5",
        'personalized_template_shown': "✨ Sizning ma'lumotlaringiz bilan tayyor namuna!\n\nQuyidagi namuna asosida e'loningizni yozing:",
        'select_property_type_filter': "🏠 Uy-joy turini tanlang:",
        'all_property_types': "🏢 Barcha turlar",
        'search_with_filters': "🔍 Filtrlangan qidiruv",
    },
    'ru': {
        'choose_search_type': "🔍 Выберите тип поиска:",
        'search_by_keyword': "📝 Поиск по ключевому слову",
        'search_by_location': "🏘 Поиск по местоположению",
        'search_prompt': "🔍 Введите ключевое слово для поиска:",
        'select_region_for_search': "🗺 Выберите область для поиска:",
        'select_district_or_all': "🏘 Выберите район или искать по всей области:",
        'all_region': "🌍 Вся область",
        'search_results_count': "🔍 Результаты поиска: найдено {count} объявлений",
        'no_search_results': "😔 Ничего не найдено.\n\nПопробуйте другое ключевое слово или другой регион.",
        'ask_price': "💰 Введите цену объявления:\n\nНапример: 50000, 50000$, 500 тыс, 1.2 млн",
        'ask_area': "📐 Введите площадь (м²):\n\nНапример: 65, 65.5, 100",
        'invalid_price': "❌ Цена введена неправильно. Пожалуйста, введите только числа.\n\nНапример: 50000, 75000",
        'invalid_area': "❌ Площадь введена неправильно. Пожалуйста, введите только числа.\n\nНапример: 65, 100.5",
        'personalized_template_shown': "✨ Готовый шаблон с вашими данными!\n\nНапишите объявление по образцу ниже:",
        'select_property_type_filter': "🏠 Выберите тип недвижимости:",
        'all_property_types': "🏢 Все типы",
        'search_with_filters': "🔍 Поиск с фильтрами",
    },
    'en': {
        'choose_search_type': "🔍 Choose search type:",
        'search_by_keyword': "📝 Search by keyword", 
        'search_by_location': "🏘 Search by location",
        'search_prompt': "🔍 Enter keyword to search:",
        'select_region_for_search': "🗺 Select region for search:",
        'select_district_or_all': "🏘 Select district or search entire region:",
        'all_region': "🌍 Entire region",
        'search_results_count': "🔍 Search results: found {count} listings",
        'no_search_results': "😔 Nothing found.\n\nTry a different keyword or location.",
        'ask_price': "💰 Enter listing price:\n\nExample: 50000, 50000$, 500k, 1.2M",
        'ask_area': "📐 Enter area (m²):\n\nExample: 65, 65.5, 100",
        'invalid_price': "❌ Price entered incorrectly. Please enter numbers only.\n\nExample: 50000, 75000",
        'invalid_area': "❌ Area entered incorrectly. Please enter numbers only.\n\nExample: 65, 100.5",
        'personalized_template_shown': "✨ Ready template with your data!\n\nWrite your listing based on the template below:",
        'select_property_type_filter': "🏠 Select property type:",
        'all_property_types': "🏢 All types",
        'search_with_filters': "🔍 Filtered search",
    }
}

# Makler translations
MAKLER_TRANSLATIONS = {
    'uz': {
        'ask_makler_type': "👨‍💼 Siz makler (dallol) sifatida e'lon joylashtirmoqchimisiz?\n\n🏢 Makler - professional ko'chmas mulk sotuv xizmati\n👤 Maklersiz - shaxsiy e'lon",
        'makler_yes': "🏢 Ha, makler sifatida",
        'makler_no': "👤 Yo'q, shaxsiy e'lon",
        'makler_selected': "✅ Tanlov qabul qilindi",
    },
    'ru': {
        'ask_makler_type': "👨‍💼 Вы размещаете объявление как риелтор (маклер)?\n\n🏢 Маклер - профессиональная служба продажи недвижимости\n👤 Без маклера - частное объявление",
        'makler_yes': "🏢 Да, как риелтор",
        'makler_no': "👤 Нет, частное объявление",
        'makler_selected': "✅ Выбор принят",
    },
    'en': {
        'ask_makler_type': "👨‍💼 Are you posting as a realtor (makler)?\n\n🏢 Makler - professional real estate sales service\n👤 Without makler - private listing",
        'makler_yes': "🏢 Yes, as realtor",
        'makler_no': "👤 No, private listing",
        'makler_selected': "✅ Selection accepted",
    }
}

# Direct posting translations
DIRECT_POSTING_TRANSLATIONS = {
    'uz': {
        'listing_posted_successfully': "🎉 E'loningiz muvaffaqiyatli kanalga joylashtirildi!",
        'listing_saved_channel_error': "✅ E'lon saqlandi, lekin kanalga yuborishda xatolik yuz berdi.",
        'listing_saved_loading_error': "❌ E'lon saqlandi, lekin yuklab olishda xatolik yuz berdi.",
    },
    'ru': {
        'listing_posted_successfully': "🎉 Ваше объявление успешно размещено в канале!",
        'listing_saved_channel_error': "✅ Объявление сохранено, но произошла ошибка при отправке в канал.",
        'listing_saved_loading_error': "❌ Объявление сохранено, но произошла ошибка при загрузке.",
    },
    'en': {
        'listing_posted_successfully': "🎉 Your listing has been successfully posted to the channel!",
        'listing_saved_channel_error': "✅ Listing saved, but there was an error posting to channel.",
        'listing_saved_loading_error': "❌ Listing saved, but there was an error loading it.",
    }
}

# Approval translations
APPROVAL_TRANSLATIONS = {
    'uz': {
        'listing_submitted_for_review': "✅ E'loningiz muvaffaqiyatli yuborildi!\n\n👨‍💼 Admin ko'rib chiqishidan so'ng kanalda e'lon qilinadi.\n\n⏱ Odatda bu 24 soat ichida amalga oshiriladi.",
        'listing_approved': "🎉 Tabriklaymiz! E'loningiz tasdiqlandi va kanalda e'lon qilindi!",
        'listing_declined': "❌ Afsuski, e'loningiz rad etildi.\n\n📝 Sabab: {feedback}\n\nIltimos, talablarni hisobga olib qaytadan yuboring.",
    },
    'ru': {
        'listing_submitted_for_review': "✅ Ваше объявление успешно отправлено!\n\n👨‍💼 После проверки администратором оно будет опубликовано в канале.\n\n⏱ Обычно это происходит в течение 24 часов.",
        'listing_approved': "🎉 Поздравляем! Ваше объявление одобрено и опубликовано в канале!",
        'listing_declined': "❌ К сожалению, ваше объявление отклонено.\n\n📝 Причина: {feedback}\n\nПожалуйста, учтите требования и отправьте заново.",
    },
    'en': {
        'listing_submitted_for_review': "✅ Your listing has been successfully submitted!\n\n👨‍💼 It will be published in the channel after admin review.\n\n⏱ This usually happens within 24 hours.",
        'listing_approved': "🎉 Congratulations! Your listing has been approved and published in the channel!",
        'listing_declined': "❌ Unfortunately, your listing was declined.\n\n📝 Reason: {feedback}\n\nPlease consider the requirements and resubmit.",
    }
}

# Helper functions
def get_text(user_lang: str, key: str, **kwargs) -> str:
    # Try to get from main TRANSLATIONS first
    text = TRANSLATIONS.get(user_lang, TRANSLATIONS.get('uz', {})).get(key)
    
    # If not found, try from SEARCH_TRANSLATIONS
    if not text:
        text = SEARCH_TRANSLATIONS.get(user_lang, SEARCH_TRANSLATIONS.get('uz', {})).get(key)
    
    # If not found, try from DIRECT_POSTING_TRANSLATIONS
    if not text:
        text = DIRECT_POSTING_TRANSLATIONS.get(user_lang, DIRECT_POSTING_TRANSLATIONS.get('uz', {})).get(key)
    
    # If not found, try from APPROVAL_TRANSLATIONS
    if not text:
        text = APPROVAL_TRANSLATIONS.get(user_lang, APPROVAL_TRANSLATIONS.get('uz', {})).get(key)
    
    # If still not found, return a default message
    if not text:
        if key == 'no_search_results':
            text = "😔 Hech narsa topilmadi."
        elif key == 'search_results_count':
            text = "🔍 Qidiruv natijalari: {count} ta"
        else:
            text = key
    
    if kwargs and text:
        try:
            return text.format(**kwargs)
        except:
            return text
    return text

def get_text_makler(user_lang: str, key: str, **kwargs) -> str:
    # Try makler translations first, then fall back to main translations
    text = MAKLER_TRANSLATIONS.get(user_lang, MAKLER_TRANSLATIONS.get('uz', {})).get(key)
    
    if not text:
        text = get_text(user_lang, key, **kwargs)
    
    if not text:
        text = key
    
    if kwargs and text:
        try:
            return text.format(**kwargs)
        except:
            return text
    return text

def get_personalized_listing_template(user_lang: str, status: str, property_type: str, price: str, area: str, location: str) -> str:
    """Generate personalized template with user's actual data"""
    
    # Special templates for Land and Commercial (regardless of sale/rent)
    if property_type == 'land':
        if user_lang == 'uz':
            return f"""
✨ Sizning ma'lumotlaringiz bilan tayyor namuna:

🧱 Bo'sh yer sotiladi
📍 Hudud: {location}
📐 Maydoni: {area} sotix
💰 Narxi: {price}
📄 Hujjatlari: tayyor/tayyorlanmoqda
🚗 Yo'l: asfalt yo'lga yaqin/uzoq
💧 Kommunikatsiya: suv, svet yaqin/uzoq
(Qo'shimcha ma'lumot kiritish mumkin)

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            return f"""
✨ Готовый шаблон с вашими данными:

🧱 Продается пустой участок
📍 Район: {location}
📐 Площадь: {area} соток
💰 Цена: {price}
📄 Документы: готовы/готовятся
🚗 Дорога: близко/далеко к асфальту
💧 Коммуникации: вода, свет рядом/далеко
(Можно добавить дополнительную информацию)

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            return f"""
✨ Ready template with your data:

🧱 Empty land for sale
📍 Area: {location}
📐 Area: {area} acres
💰 Price: {price}
📄 Documents: ready/being prepared
🚗 Road: close/far to paved road
💧 Communications: water, electricity nearby/far
(Additional information can be added)

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
    
    elif property_type == 'commercial':
        if user_lang == 'uz':
            return f"""
✨ Sizning ma'lumotlaringiz bilan tayyor namuna:

🏢 Tijorat ob'ekti sotiladi
📍 Tuman: {location}
📐 Maydoni: {area} m²
💰 Narxi: {price}
📄 Hujjat: noturar bino/tijorat ob'ekti sifatida
📌 Hozirda faoliyat yuritmoqda/bo'sh
(Qo'shimcha ma'lumot kiritish mumkin)

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            return f"""
✨ Готовый шаблон с вашими данными:

🏢 Продается коммерческий объект
📍 Район: {location}
📐 Площадь: {area} м²
💰 Цена: {price}
📄 Документ: нежилое здание/коммерческий объект
📌 В настоящее время работает/пустует
(Можно добавить дополнительную информацию)

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            return f"""
✨ Ready template with your data:

🏢 Commercial property for sale
📍 District: {location}
📐 Area: {area} m²
💰 Price: {price}
📄 Document: non-residential building/commercial property
📌 Currently operating/vacant
(Additional information can be added)

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
    
    # Regular templates for apartment/house based on sale/rent
    else:
        if user_lang == 'uz':
            if status == 'rent':
                return f"""
✨ Sizning ma'lumotlaringiz bilan tayyor namuna:

🏠 KVARTIRA IJARAGA BERILADI
📍 {location}
💰 Narxi: {price}
📐 Maydon: {area} m²
🛏 Xonalar: __ xonali
♨️ Kommunal: gaz, suv, svet bor
🪚 Holati: yevro remont yoki o'rtacha
🛋 Jihoz: jihozli yoki jihozsiz
🕒 Muddat: qisqa yoki uzoq muddatga
👥 Kimga: Shariy nikohga / oilaga / studentlarga

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
            else:  # sale
                return f"""
✨ Sizning ma'lumotlaringiz bilan tayyor namuna:

🏠 UY-JOY SOTILADI 
📍 {location}
💰 Narxi: {price}
📐 Maydon: {area} m²
🛏 Xonalar: __ xonali
♨️ Kommunal: gaz, suv, svet bor
🪚 Holati: yevro remont yoki o'rtacha
🛋 Jihoz: jihozli yoki jihozsiz
🏢 Qavat: __/__

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            if status == 'rent':
                return f"""
✨ Готовый шаблон с вашими данными:

🏠 КВАРТИРА СДАЕТСЯ В АРЕНДУ
📍 {location}
💰 Цена: {price}
📐 Площадь: {area} м²
🛏 Комнаты: __-комнатная
♨️ Коммунальные: газ, вода, свет есть
🪚 Состояние: евроремонт или среднее
🛋 Мебель: с мебелью или без мебели
🕒 Срок: краткосрочно или долгосрочно
👥 Для кого: для гражданского брака / для семьи / для студентов

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
            else:  # sale
                return f"""
✨ Готовый шаблон с вашими данными:

🏠 ПРОДАЕТСЯ НЕДВИЖИМОСТЬ
📍 {location}
💰 Цена: {price}
📐 Площадь: {area} м²
🛏 Комнаты: __-комнатная
♨️ Коммунальные: газ, вода, свет есть
🪚 Состояние: евроремонт или среднее
🛋 Мебель: с мебелью или без мебели
🏢 Этаж: __/__

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            if status == 'rent':
                return f"""
✨ Ready template with your data:

🏠 APARTMENT FOR RENT
📍 {location}
💰 Price: {price}
📐 Area: {area} m²
🛏 Rooms: __-room
♨️ Utilities: gas, water, electricity available
🪚 Condition: euro renovation or average
🛋 Furniture: furnished or unfurnished
🕒 Period: short-term or long-term
👥 For whom: for civil marriage / for family / for students

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
            else:  # sale
                return f"""
✨ Ready template with your data:

🏠 PROPERTY FOR SALE
📍 {location}
💰 Price: {price}
📐 Area: {area} m²
🛏 Rooms: __-room
♨️ Utilities: gas, water, electricity available
🪚 Condition: euro renovation or average
🛋 Furniture: furnished or unfurnished
🏢 Floor: __/__

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""

def format_listing_for_channel_with_makler(listing) -> str:
    """Format listing for channel with makler hashtag"""
    user_description = listing['description']
    contact_info = listing['contact_info']
    
    channel_text = f"""{user_description}

📞 Aloqa: {contact_info}
\n🗺 Manzil: {listing['full_address']}"""
    
    property_type = listing['property_type']
    status = listing['status']
    
    # Get makler status from admin_notes field
    is_makler = listing.get('admin_notes') == 'makler'
    makler_tag = '#makler' if is_makler else '#maklersiz'
    
    channel_text += f"\n\n#{property_type} #{status} {makler_tag}"
    
    return channel_text

def format_listing_raw_display(listing, user_lang):
    user_description = listing['description']
    location_display = listing['full_address'] if listing['full_address'] else listing['address']
    contact_info = listing['contact_info']
    
    listing_text = f"""{user_description}

📞 Aloqa: {contact_info}"""
    
    if location_display and location_display.strip():
        listing_text += f"\n🗺 Manzil: {location_display}"
    
    return listing_text

def get_main_menu_keyboard(user_lang: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=get_text(user_lang, 'post_listing')))
    # The "View Listings" button has been removed as per your request.
    # builder.add(KeyboardButton(text=get_text(user_lang, 'view_listings')))
    builder.add(KeyboardButton(text=get_text(user_lang, 'my_postings')))
    builder.add(KeyboardButton(text=get_text(user_lang, 'search')))
    builder.add(KeyboardButton(text=get_text(user_lang, 'favorites')))
    builder.add(KeyboardButton(text=get_text(user_lang, 'info')))
    builder.add(KeyboardButton(text=get_text(user_lang, 'language')))
    # Adjusting the layout for 6 buttons for a cleaner look
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_search_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'search_by_keyword'), 
        callback_data="search_keyword"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'search_by_location'), 
        callback_data="search_location"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"))
    builder.add(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"))
    builder.add(InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en"))
    builder.adjust(1)
    return builder.as_markup()

def get_makler_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text_makler(user_lang, 'makler_yes'), 
        callback_data="makler_yes"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text_makler(user_lang, 'makler_no'), 
        callback_data="makler_no"
    ))
    builder.adjust(1)  # Stack vertically for better readability
    return builder.as_markup()

def get_search_property_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    """Property type filter keyboard for search"""
    builder = InlineKeyboardBuilder()
    
    # Add "All types" option first
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'all_property_types'),
        callback_data="search_property_all"
    ))
    
    # Add individual property types
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'apartment'), 
        callback_data="search_property_apartment"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'house'), 
        callback_data="search_property_house"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'commercial'), 
        callback_data="search_property_commercial"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'land'), 
        callback_data="search_property_land"
    ))
    
    # Add back button
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="search_back_to_districts"
    ))
    
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()

def get_regions_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    regions = regions_config.get(user_lang, regions_config['uz'])
    
    for region_key, region_name in regions:
        builder.add(InlineKeyboardButton(
            text=region_name,
            callback_data=f"region_{region_key}"
        ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_search_regions_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    """SEPARATE keyboard for search regions to avoid conflicts"""
    builder = InlineKeyboardBuilder()
    regions = regions_config.get(user_lang, regions_config['uz'])
    
    for region_key, region_name in regions:
        builder.add(InlineKeyboardButton(
            text=region_name,
            callback_data=f"search_region_{region_key}"  # DIFFERENT PREFIX
        ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_districts_keyboard(region_key: str, user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    try:
        districts = REGIONS_DATA[user_lang][region_key]['districts']
        
        for district_key, district_name in districts.items():
            builder.add(InlineKeyboardButton(
                text=district_name,
                callback_data=f"district_{district_key}"
            ))
        
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'back'),
            callback_data="back_to_regions"
        ))
        
        builder.adjust(2, 2, 2, 2, 2, 1)
        return builder.as_markup()
        
    except KeyError:
        return InlineKeyboardMarkup(inline_keyboard=[])

def get_search_districts_keyboard(region_key: str, user_lang: str) -> InlineKeyboardMarkup:
    """SEPARATE keyboard for search districts to avoid conflicts"""
    builder = InlineKeyboardBuilder()
    
    # Add "All region" option first
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'all_region'),
        callback_data=f"search_all_region_{region_key}"
    ))
    
    try:
        districts = REGIONS_DATA[user_lang][region_key]['districts']
        
        for district_key, district_name in districts.items():
            builder.add(InlineKeyboardButton(
                text=district_name,
                callback_data=f"search_district_{district_key}"  # DIFFERENT PREFIX
            ))
    except KeyError:
        pass
    
    # Add back button
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="search_back_to_regions"
    ))
    
    builder.adjust(1, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()

def get_property_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'apartment'), callback_data="type_apartment"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'house'), callback_data="type_house"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'commercial'), callback_data="type_commercial"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'land'), callback_data="type_land"))
    builder.adjust(2)
    return builder.as_markup()

def get_status_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'sale'), callback_data="status_sale"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'rent'), callback_data="status_rent"))
    builder.adjust(2)
    return builder.as_markup()

def get_listing_keyboard(listing_id: int, user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'add_favorite'), callback_data=f"fav_add_{listing_id}"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'contact_seller'), callback_data=f"contact_{listing_id}"))
    builder.adjust(2)
    return builder.as_markup()

def format_my_posting_display(listing, user_lang):
    """Format posting for owner view"""
    location_display = listing['full_address'] if listing['full_address'] else listing['address']
    
    # Status determination based on is_approved
    if listing['is_approved']:
        status_text = get_text(user_lang, 'posting_status_active')
    else:
        status_text = get_text(user_lang, 'posting_status_pending')
    
    favorite_count = listing.get('favorite_count', 0)
    
    listing_text = f"""
🆔 <b>E'lon #{listing['id']}</b>
📊 <b>Status:</b> {status_text}

🏠 <b>{listing['title'] or listing['description'][:50]}...</b>
🗺 <b>Manzil:</b> {location_display}
💰 <b>Narx:</b> {listing['price']:,} so'm
📐 <b>Maydon:</b> {listing['area']} m²

📝 <b>Tavsif:</b> {listing['description'][:100]}{'...' if len(listing['description']) > 100 else ''}
"""
    return listing_text

def get_posting_management_keyboard(listing_id: int, is_active: bool, user_lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Create posting management keyboard"""
    builder = InlineKeyboardBuilder()
    
    # Status toggle button
    if is_active:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'deactivate_posting'), 
            callback_data=f"deactivate_post_{listing_id}"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'activate_posting'), 
            callback_data=f"activate_post_{listing_id}"
        ))
    
    # Management buttons
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'delete_posting'), 
        callback_data=f"delete_post_{listing_id}"
    ))
    
    # Admin-only buttons
    if is_admin:
        builder.add(InlineKeyboardButton(
            text="🔧 Admin Actions", 
            callback_data=f"admin_post_{listing_id}"
        ))
    
    builder.adjust(2)
    return builder.as_markup()

async def post_to_channel_with_makler(listing):
    """Post approved listing to channel with makler hashtag"""
    try:
        channel_text = format_listing_for_channel_with_makler(listing)
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        if photo_file_ids:
            if len(photo_file_ids) == 1:
                message = await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo_file_ids[0],
                    caption=channel_text
                )
            else:
                media_group = MediaGroupBuilder(caption=channel_text)
                for photo_id in photo_file_ids[:10]:
                    media_group.add_photo(media=photo_id)
                
                messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media_group.build())
                message = messages[0]
        else:
            message = await bot.send_message(
                chat_id=CHANNEL_ID,
                text=channel_text
            )
        
        logger.info(f"Posted listing {listing['id']} to channel with makler tag")
        
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")

async def display_search_results(message_or_callback, listings, user_lang, search_term=""):
    """Display search results to user"""
    
    # Determine if this is a Message or CallbackQuery
    is_callback = hasattr(message_or_callback, 'message')
    
    if not listings:
        text = get_text(user_lang, 'no_search_results')
        if is_callback:
            await message_or_callback.message.answer(text)
        else:
            await message_or_callback.answer(text)
        return
    
    # Show search results count
    results_text = get_text(user_lang, 'search_results_count', count=len(listings))
    if is_callback:
        await message_or_callback.message.answer(results_text)
    else:
        await message_or_callback.answer(results_text)
    
    # Display each listing
    for listing in listings:
        listing_text = format_listing_raw_display(listing, user_lang)
        keyboard = get_listing_keyboard(listing['id'], user_lang)
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        try:
            if photo_file_ids:
                if len(photo_file_ids) == 1:
                    # Send single photo
                    if is_callback:
                        await message_or_callback.message.answer_photo(
                            photo=photo_file_ids[0],
                            caption=listing_text,
                            reply_markup=keyboard
                        )
                    else:
                        await message_or_callback.answer_photo(
                            photo=photo_file_ids[0],
                            caption=listing_text,
                            reply_markup=keyboard
                        )
                else:
                    # Send media group
                    media_group = MediaGroupBuilder(caption=listing_text)
                    for photo_id in photo_file_ids[:5]:
                        media_group.add_photo(media=photo_id)
                    
                    if is_callback:
                        await message_or_callback.message.answer_media_group(media=media_group.build())
                        await message_or_callback.message.answer("👆 E'lon", reply_markup=keyboard)
                    else:
                        await message_or_callback.answer_media_group(media=media_group.build())
                        await message_or_callback.answer("👆 E'lon", reply_markup=keyboard)
            else:
                # No photos, send text only
                if is_callback:
                    await message_or_callback.message.answer(listing_text, reply_markup=keyboard)
                else:
                    await message_or_callback.answer(listing_text, reply_markup=keyboard)
        except Exception as e2:
            logger.error(f"Error in fallback display: {e2}")

# MAIN HANDLERS
@dp.message(CommandStart())
async def start_handler(message: Message):
    user = message.from_user
    await save_user(user.id, user.username, user.first_name, user.last_name)
    user_lang = await get_user_language(user.id)
    
    await message.answer(
        get_text(user_lang, 'start'),
        reply_markup=get_main_menu_keyboard(user_lang)
    )

@dp.message(F.text.in_(['🌐 Til', '🌐 Язык', '🌐 Language']))
async def language_handler(message: Message):
    user_lang = await get_user_language(message.from_user.id)
    await message.answer(
        get_text(user_lang, 'choose_language'),
        reply_markup=get_language_keyboard()
    )

@dp.callback_query(F.data.startswith('lang_'))
async def language_callback(callback_query):
    lang = callback_query.data.split('_')[1]
    await update_user_language(callback_query.from_user.id, lang)
    
    await callback_query.answer(f"Language changed!")
    
    await callback_query.message.answer(
        get_text(lang, 'main_menu'),
        reply_markup=get_main_menu_keyboard(lang)
    )

# =============================================
# FIXED SEARCH HANDLERS - COMPLETELY SEPARATE
# =============================================

@dp.message(F.text.in_(['🔍 Qidiruv', '🔍 Поиск', '🔍 Search']))
async def search_handler(message: Message, state: FSMContext):
    """ONLY FOR SEARCHING EXISTING LISTINGS"""
    user_lang = await get_user_language(message.from_user.id)
    await state.set_state(SearchStates.search_type)
    await message.answer(
        get_text(user_lang, 'choose_search_type'),
        reply_markup=get_search_type_keyboard(user_lang)
    )

@dp.callback_query(F.data == 'search_keyword')
async def search_keyword_selected(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.keyword_query)
    await callback_query.message.edit_text(get_text(user_lang, 'search_prompt'))
    await callback_query.answer()

@dp.callback_query(F.data == 'search_location')
async def search_location_selected(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.location_region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region_for_search'),
        reply_markup=get_search_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.message(SearchStates.keyword_query)
async def process_keyword_search(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    query = message.text.strip()
    await state.clear()
    
    listings = await search_listings(query)
    await display_search_results(message, listings, user_lang, query)

# REGION SELECTION FOR SEARCH
@dp.callback_query(F.data.startswith('search_region_'))
async def process_search_region_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    region_key = callback_query.data[14:]  # Remove 'search_region_' prefix
    
    if region_key not in REGIONS_DATA.get(user_lang, {}):
        await callback_query.answer("Region not found!")
        return
    
    await state.update_data(search_region=region_key)
    await state.set_state(SearchStates.location_district)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_district_or_all'),
        reply_markup=get_search_districts_keyboard(region_key, user_lang)
    )
    await callback_query.answer()

# SEARCH BY ENTIRE REGION (asks for property type filter)
@dp.callback_query(F.data.startswith('search_all_region_'))
async def process_search_all_region(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    region_key = callback_query.data[18:]  # Remove 'search_all_region_' prefix
    
    # Store region, clear district, ask for property type
    await state.update_data(search_region=region_key, search_district=None)
    await state.set_state(SearchStates.property_type_filter)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_property_type_filter'),
        reply_markup=get_search_property_type_keyboard(user_lang)
    )
    await callback_query.answer()


# SEARCH BY SPECIFIC DISTRICT (asks for property type filter)
@dp.callback_query(F.data.startswith('search_district_'))
async def process_search_district_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    district_key = callback_query.data[16:]  # Remove 'search_district_' prefix
    
    data = await state.get_data()
    region_key = data.get('search_region')
    
    # Store district and ask for property type
    await state.update_data(search_district=district_key)
    await state.set_state(SearchStates.property_type_filter)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_property_type_filter'),
        reply_markup=get_search_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

# PROPERTY TYPE FILTER SELECTION
@dp.callback_query(F.data == 'search_property_all')
async def process_search_all_property_types(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    region_key = data.get('search_region')
    district_key = data.get('search_district')
    
    await state.clear()
    
    # Search without property type filter
    listings = await search_listings_by_location(
        region_key=region_key, 
        district_key=district_key, 
        property_type=None
    )
    
    # Get location name for display
    try:
        region_name = REGIONS_DATA[user_lang][region_key]['name']
        if district_key:
            district_name = REGIONS_DATA[user_lang][region_key]['districts'][district_key]
            location_name = f"{district_name}, {region_name}"
        else:
            location_name = region_name
    except KeyError:
        location_name = "Selected location"
    
    await display_search_results(
        callback_query, listings, user_lang, 
        f"{location_name} (barcha turlar)"
    )

@dp.callback_query(F.data.startswith('search_property_'))
async def process_search_property_type_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    property_type = callback_query.data[16:]  # Remove 'search_property_' prefix
    
    data = await state.get_data()
    region_key = data.get('search_region')
    district_key = data.get('search_district')
    
    await state.clear()
    
    # Search with property type filter
    listings = await search_listings_by_location(
        region_key=region_key, 
        district_key=district_key, 
        property_type=property_type if property_type != 'all' else None
    )
    
    # Get location and property type names for display
    try:
        region_name = REGIONS_DATA[user_lang][region_key]['name']
        if district_key:
            district_name = REGIONS_DATA[user_lang][region_key]['districts'][district_key]
            location_name = f"{district_name}, {region_name}"
        else:
            location_name = region_name
        
        property_type_name = get_text(user_lang, property_type) if property_type != 'all' else get_text(user_lang, 'all_property_types')
        search_description = f"{location_name} - {property_type_name}"
    except KeyError:
        search_description = f"Selected location - {property_type}"
    
    await display_search_results(callback_query, listings, user_lang, search_description)

# NAVIGATION HANDLERS
@dp.callback_query(F.data == 'search_back_to_regions')
async def search_back_to_regions(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(SearchStates.location_region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region_for_search'),
        reply_markup=get_search_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'search_back_to_districts')
async def search_back_to_districts(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    region_key = data.get('search_region')
    
    await state.set_state(SearchStates.location_district)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_district_or_all'),
        reply_markup=get_search_districts_keyboard(region_key, user_lang)
    )
    await callback_query.answer()

# =============================================
# LISTING CREATION HANDLERS - COMPLETELY SEPARATE
# =============================================

@dp.message(F.text.in_(['📝 E\'lon joylash', '📝 Разместить объявление', '📝 Post listing']))
async def post_listing_handler(message: Message, state: FSMContext):
    """ONLY FOR CREATING NEW LISTINGS"""
    user_lang = await get_user_language(message.from_user.id)
    
    await state.set_state(ListingStates.property_type)
    await message.answer(
        get_text(user_lang, 'property_type'),
        reply_markup=get_property_type_keyboard(user_lang)
    )

@dp.callback_query(F.data.startswith('type_'))
async def process_property_type(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    property_type = callback_query.data.split('_')[1]
    await state.update_data(property_type=property_type)
    
    await state.set_state(ListingStates.status)
    await callback_query.message.edit_text(
        get_text(user_lang, 'status'),
        reply_markup=get_status_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('status_'))
async def process_status(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    status = callback_query.data.split('_')[1]
    await state.update_data(status=status)
    
    # NEW: Go to makler type selection instead of region
    await state.set_state(ListingStates.makler_type)
    await callback_query.message.edit_text(
        get_text_makler(user_lang, 'ask_makler_type'),
        reply_markup=get_makler_type_keyboard(user_lang)
    )
    await callback_query.answer()

# Add makler type selection handlers
@dp.callback_query(F.data == 'makler_yes')
async def process_makler_yes(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.update_data(is_makler=True)
    
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer(get_text_makler(user_lang, 'makler_selected'))

@dp.callback_query(F.data == 'makler_no')
async def process_makler_no(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.update_data(is_makler=False)
    
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer(get_text_makler(user_lang, 'makler_selected'))

# LISTING REGION HANDLERS - NORMAL PREFIX (only works when in ListingStates)
@dp.callback_query(F.data.startswith('region_'), ListingStates.region)
async def process_region_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    region_key = callback_query.data[7:]  # Remove 'region_' prefix
    
    if region_key not in REGIONS_DATA.get(user_lang, {}):
        await callback_query.answer("Region not found!")
        return
    
    await state.update_data(region=region_key)
    await state.set_state(ListingStates.district)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_district'),
        reply_markup=get_districts_keyboard(region_key, user_lang)
    )
    await callback_query.answer(get_text(user_lang, 'region_selected'))

@dp.callback_query(F.data.startswith('district_'))
async def process_district_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    district_key = callback_query.data[9:]
    
    await state.update_data(district=district_key)
    
    # Ask for price first
    await state.set_state(ListingStates.price)
    await callback_query.message.edit_text(get_text(user_lang, 'ask_price'))
    await callback_query.answer(get_text(user_lang, 'district_selected'))

@dp.message(ListingStates.price)
async def process_price(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    # Validate price input
    try:
        price_text = message.text.strip()
        # Remove common separators and extract numbers
        price_clean = ''.join(filter(str.isdigit, price_text))
        
        if not price_clean:
            await message.answer(get_text(user_lang, 'invalid_price'))
            return
        
        price = int(price_clean)
        await state.update_data(price=price, price_text=price_text)
        
        # Ask for area
        await state.set_state(ListingStates.area)
        await message.answer(get_text(user_lang, 'ask_area'))
        
    except ValueError:
        await message.answer(get_text(user_lang, 'invalid_price'))

@dp.message(ListingStates.area)
async def process_area(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    # Validate area input
    try:
        area_text = message.text.strip()
        # Extract numbers (can be decimal)
        area_clean = ''.join(c for c in area_text if c.isdigit() or c == '.')
        
        if not area_clean:
            await message.answer(get_text(user_lang, 'invalid_area'))
            return
        
        area = float(area_clean)
        await state.update_data(area=area, area_text=area_text)
        
        # Now show personalized template
        data = await state.get_data()
        property_type = data.get('property_type')
        status = data.get('status')
        price_text = data.get('price_text', '')
        area_text = data.get('area_text', '')
        region_key = data.get('region')
        district_key = data.get('district')
        
        # Get location names
        region_name = REGIONS_DATA[user_lang][region_key]['name']
        district_name = REGIONS_DATA[user_lang][region_key]['districts'][district_key]
        location = f"{district_name}, {region_name}"
        
        # Get personalized template
        template = get_personalized_listing_template(
            user_lang, status, property_type, price_text, area_text, location
        )
        
        await state.set_state(ListingStates.description)
        await message.answer(template)
        await message.answer(get_text(user_lang, 'personalized_template_shown'))
        
    except ValueError:
        await message.answer(get_text(user_lang, 'invalid_area'))

@dp.callback_query(F.data == 'back_to_regions')
async def back_to_regions(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.message(ListingStates.description)
async def process_description(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    await state.update_data(description=message.text)
    
    # Ask for confirmation with Yes/Add more options
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'yes_complete'), 
        callback_data="desc_complete"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'add_more_info'), 
        callback_data="desc_add_more"
    ))
    builder.adjust(1)
    
    await state.set_state(ListingStates.confirmation)
    await message.answer(
        get_text(user_lang, 'is_description_complete'),
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'desc_complete')
async def description_complete(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.contact_info)
    await callback_query.message.edit_text(get_text(user_lang, 'phone_number_request'))
    await callback_query.answer()

@dp.callback_query(F.data == 'desc_add_more')
async def description_add_more(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.description)
    await callback_query.message.edit_text(get_text(user_lang, 'additional_info'))
    await callback_query.answer()

@dp.message(ListingStates.contact_info)
async def process_contact_info(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    await state.update_data(contact_info=message.text)
    
    await state.set_state(ListingStates.photos)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'photos_done'), callback_data="photos_done"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'skip'), callback_data="photos_skip"))
    
    await message.answer(
        get_text(user_lang, 'add_photos_mediagroup'),
        reply_markup=builder.as_markup()
    )

@dp.message(ListingStates.photos, F.photo)
async def process_photo_with_collector(message: Message, state: FSMContext):
    """Handle both single photos and media groups using collector"""
    await media_collector.add_message(message, state)

@dp.callback_query(F.data.in_(['photos_done', 'photos_skip']))
async def finish_listing_with_makler(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    # Build full address
    region_key = data.get('region')
    district_key = data.get('district')
    
    if region_key and district_key:
        try:
            region_name = REGIONS_DATA[user_lang][region_key]['name']
            district_name = REGIONS_DATA[user_lang][region_key]['districts'][district_key]
            full_address = f"{district_name}, {region_name}"
            data['full_address'] = full_address
            data['address'] = full_address
        except KeyError:
            data['full_address'] = f"{district_key}, {region_key}"
            data['address'] = f"{district_key}, {region_key}"
    
    # Ensure title is properly set from description
    description = data.get('description', 'No description provided')
    if not data.get('title'):
        title = description.split('\n')[0][:50]
        if len(description) > 50:
            title += '...'
        data['title'] = title
    
    # Ensure required fields
    if 'price' not in data or data['price'] is None:
        data['price'] = 0
    if 'area' not in data or data['area'] is None:
        data['area'] = 0
    if 'rooms' not in data:
        data['rooms'] = 0
    if not data.get('condition'):
        data['condition'] = ''
    if not data.get('contact_info'):
        data['contact_info'] = 'Not provided'
    
    # Debug log
    is_makler = data.get('is_makler', False)
    logger.info(f"Saving listing with makler status: {is_makler}")
    
    try:
        # Save listing with makler info
        listing_id = await save_listing_with_makler(callback_query.from_user.id, data)
        
        # Get the saved listing
        listing = await get_listing_by_id(listing_id)
        if listing:
            # Post directly to main channel with makler hashtag
            try:
                await post_to_channel_with_makler(listing)
                makler_status = "makler" if is_makler else "maklersiz"
                channel_status = f"✅ E'loningiz muvaffaqiyatli kanalga joylashtirildi! (#{makler_status})"
            except Exception as channel_error:
                logger.error(f"Error posting to channel: {channel_error}")
                channel_status = "⚠️ E'lon saqlandi, lekin kanalga yuborishda xatolik yuz berdi."
        else:
            channel_status = "❌ E'lon saqlandi, lekin yuklab olishda xatolik yuz berdi."
        
        # Notify user of success
        await callback_query.message.edit_text(
            f"🎉 {channel_status}\n\n📊 E'lon ID: #{listing_id}"
        )
        
        await state.clear()
        await callback_query.answer()
        
    except Exception as e:
        logger.error(f"Error in finish_listing_with_makler: {e}")
        
        error_message = "❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring."
        await callback_query.message.edit_text(error_message)
        await callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)
        await state.clear()

# =============================================
# OTHER HANDLERS
# =============================================

# The 'view_listings_handler' has been removed as per your request.
# @dp.message(F.text.in_(['👀 E\'lonlar', '👀 Объявления', '👀 Listings']))
# async def view_listings_handler(message: Message):
#     user_lang = await get_user_language(message.from_user.id)
#     listings = await get_listings(limit=5)
#     
#     if not listings:
#         await message.answer(get_text(user_lang, 'no_listings'))
#         return
#     
#     for listing in listings:
#         listing_text = format_listing_raw_display(listing, user_lang)
#         keyboard = get_listing_keyboard(listing['id'], user_lang)
#         
#         photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
#         
#         if photo_file_ids:
#             try:
#                 if len(photo_file_ids) == 1:
#                     await message.answer_photo(
#                         photo=photo_file_ids[0],
#                         caption=listing_text,
#                         reply_markup=keyboard
#                     )
#                 else:
#                     media_group = MediaGroupBuilder(caption=listing_text)
#                     for i, photo_id in enumerate(photo_file_ids[:10]):
#                         if i == 0:
#                             media_group.add_photo(media=photo_id)
#                         else:
#                             media_group.add_photo(media=photo_id)
#                     
#                     await message.answer_media_group(media=media_group.build())
#                     await message.answer("👆 E'lon", reply_markup=keyboard)
#                     
#             except Exception as e:
#                 await message.answer(listing_text, reply_markup=keyboard)
#         else:
#             await message.answer(listing_text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith('fav_add_'))
async def add_favorite_callback(callback_query):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Check if listing is still active
    listing = await get_listing_by_id(listing_id)
    if not listing or not listing['is_approved']:  # not active
        await callback_query.answer(get_text(user_lang, 'posting_no_longer_available'), show_alert=True)
        return
    
    await add_to_favorites(callback_query.from_user.id, listing_id)
    await callback_query.answer(get_text(user_lang, 'added_to_favorites'))

@dp.callback_query(F.data.startswith('contact_'))
async def contact_callback(callback_query):
    listing_id = int(callback_query.data.split('_')[1])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    listing = await get_listing_by_id(listing_id)
    
    if listing:
        await callback_query.answer(f"📞 Aloqa: {listing['contact_info']}", show_alert=True)
    else:
        await callback_query.answer("E'lon topilmadi")

@dp.message(F.text.in_(['❤️ Sevimlilar', '❤️ Избранное', '❤️ Favorites']))
async def favorites_handler(message: Message):
    user_lang = await get_user_language(message.from_user.id)
    favorites = await get_user_favorites(message.from_user.id)
    
    if not favorites:
        await message.answer(get_text(user_lang, 'no_favorites'))
        return
    
    await message.answer(f"❤️ Sevimli e'lonlar: {len(favorites)} ta")
    
    for favorite in favorites:
        # Use raw display instead of template
        listing_text = format_listing_raw_display(favorite, user_lang)
        
        photo_file_ids = json.loads(favorite['photo_file_ids']) if favorite['photo_file_ids'] else []
        if photo_file_ids:
            try:
                if len(photo_file_ids) == 1:
                    await message.answer_photo(
                        photo=photo_file_ids[0],
                        caption=listing_text
                    )
                else:
                    media_group = MediaGroupBuilder(caption=listing_text)
                    for photo_id in photo_file_ids[:5]:
                        media_group.add_photo(media=photo_id)
                    
                    await message.answer_media_group(media=media_group.build())
            except:
                await message.answer(listing_text)
        else:
            await message.answer(listing_text)

@dp.message(F.text.in_(['ℹ️ Ma\'lumot', 'ℹ️ Информация', 'ℹ️ Info']))
async def info_handler(message: Message):
    user_lang = await get_user_language(message.from_user.id)
    await message.answer(get_text(user_lang, 'about'))

# Handlers for My Postings
@dp.message(F.text.in_(['👀 Mening e\'lonlarim', '👀 Мои объявления', '👀 My Postings']))
async def my_postings_handler(message: Message):
    user_lang = await get_user_language(message.from_user.id)
    postings = await get_user_postings(message.from_user.id)
    
    if not postings:
        await message.answer(get_text(user_lang, 'no_my_postings'))
        return
    
    await message.answer(f"📝 Sizning e'lonlaringiz: {len(postings)} ta")
    
    for posting in postings:  # Show all postings
        posting_text = format_my_posting_display(posting, user_lang)
        is_active = posting['is_approved']  # is_approved
        keyboard = get_posting_management_keyboard(
            posting['id'], is_active, user_lang, is_admin(message.from_user.id)
        )
        
        # Show with photos if available
        photo_file_ids = json.loads(posting['photo_file_ids']) if posting['photo_file_ids'] else []
        if photo_file_ids:
            try:
                await message.answer_photo(
                    photo=photo_file_ids[0],
                    caption=posting_text,
                    reply_markup=keyboard
                )
            except:
                await message.answer(posting_text, reply_markup=keyboard)
        else:
            await message.answer(posting_text, reply_markup=keyboard)

# Status management callbacks
@dp.callback_query(F.data.startswith('activate_post_'))
async def activate_posting(callback_query):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Check ownership or admin rights
    listing = await get_listing_by_id(listing_id)
    if not listing:
        await callback_query.answer("⛔ E'lon topilmadi!")
        return
    
    # Get user database ID for ownership check
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            callback_query.from_user.id
        )
    
    if listing['user_id'] != user_db_id and not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Ruxsat yo'q!")
        return
    
    # Activate the posting
    await update_listing_status(listing_id, True)
    
    await callback_query.message.edit_reply_markup(
        reply_markup=get_posting_management_keyboard(
            listing_id, True, user_lang, is_admin(callback_query.from_user.id)
        )
    )
    await callback_query.answer(get_text(user_lang, 'posting_activated'))

@dp.callback_query(F.data.startswith('deactivate_post_'))
async def deactivate_posting(callback_query):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Check ownership or admin rights
    listing = await get_listing_by_id(listing_id)
    if not listing:
        await callback_query.answer("⛔ E'lon topilmadi!")
        return
    
    # Get user database ID for ownership check
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            callback_query.from_user.id
        )
    
    if listing['user_id'] != user_db_id and not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Ruxsat yo'q!")
        return
    
    # Deactivate the posting
    await update_listing_status(listing_id, False)
    
    await callback_query.message.edit_reply_markup(
        reply_markup=get_posting_management_keyboard(
            listing_id, False, user_lang, is_admin(callback_query.from_user.id)
        )
    )
    await callback_query.answer(get_text(user_lang, 'posting_deactivated'))

@dp.callback_query(F.data.startswith('delete_post_'))
async def confirm_delete_posting(callback_query: CallbackQuery):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Check ownership or admin rights
    listing = await get_listing_by_id(listing_id)
    if not listing:
        await callback_query.answer("⛔ E'lon topilmadi!", show_alert=True)
        return
    
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            callback_query.from_user.id
        )
    
    if listing['user_id'] != user_db_id and not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    
    # Build confirmation keyboard
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'yes_delete'), 
        callback_data=f"confirm_delete_{listing_id}"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'cancel_action'), 
        callback_data=f"cancel_delete_{listing_id}"
    ))
    builder.adjust(2)
    
    confirmation_text = get_text(user_lang, 'confirm_delete')
    
    # Try to edit the message (caption if photo, text if not)
    try:
        if callback_query.message.photo:
            await callback_query.message.edit_caption(
                caption=confirmation_text,
                reply_markup=builder.as_markup()
            )
        else:
            await callback_query.message.edit_text(
                confirmation_text,
                reply_markup=builder.as_markup()
            )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Could not edit message for delete confirmation, falling back. Error: {e}")
        # Fallback: delete the original message and send a new one with the confirmation
        try:
            await callback_query.message.delete()
        except Exception as del_e:
            logger.warning(f"Could not delete message during fallback: {del_e}")
            
        await callback_query.message.answer(
            confirmation_text,
            reply_markup=builder.as_markup()
        )
        await callback_query.answer()


@dp.callback_query(F.data.startswith('confirm_delete_'))
async def delete_posting_confirmed(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(user_id)
    
    try:
        # 1. Verify listing exists and get basic info
        listing = await get_listing_by_id(listing_id)
        if not listing:
            await callback_query.answer("⛔ Listing not found!", show_alert=True)
            return

        # 2. Check ownership or admin rights
        async with db_pool.acquire() as conn:
            user_db_id = await conn.fetchval(
                'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
                user_id
            )
        
        if listing['user_id'] != user_db_id and not is_admin(user_id):
            await callback_query.answer("⛔ No permission!", show_alert=True)
            return

        # 3. Delete from database and get affected users
        deletion_result = await delete_listing_completely(listing_id)
        
        # 4. Notify users who had this favorited
        for fav_user_id in deletion_result['user_ids']:
            try:
                msg = get_text(user_lang, 'favorite_listing_deleted', 
                             title=listing.get('title', '#'+str(listing_id)))
                await bot.send_message(chat_id=fav_user_id, text=msg)
            except Exception as e:
                logger.warning(f"Couldn't notify user {fav_user_id}: {e}")

        # 5. Handle the response - NEW APPROACH
        try:
            # First try to send a new message
            await callback_query.message.answer(
                get_text(user_lang, 'posting_deleted_success')
            )
            
            # Then try to delete the original message (works for all message types)
            try:
                await callback_query.message.delete()
            except Exception as delete_error:
                logger.warning(f"Couldn't delete original message: {delete_error}")
                
                # If deletion fails, try to edit it (only works for text messages)
                try:
                    await callback_query.message.edit_text(
                        get_text(user_lang, 'posting_deleted_success')
                    )
                except Exception as edit_error:
                    logger.warning(f"Couldn't edit original message: {edit_error}")

        except Exception as e:
            logger.error(f"Failed to handle response: {e}")
            await callback_query.answer(
                get_text(user_lang, 'posting_deleted_success'), 
                show_alert=True
            )

        # 6. Final confirmation
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Critical error deleting listing {listing_id}: {e}")
        try:
            await callback_query.message.answer(
                get_text(user_lang, 'posting_delete_error')
            )
        except:
            pass
        await callback_query.answer(
            get_text(user_lang, 'posting_delete_error'), 
            show_alert=True
        )
@dp.callback_query(F.data.startswith('cancel_delete_'))
async def cancel_delete_posting(callback_query: CallbackQuery):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Get the listing data to restore the original view
    listing = await get_listing_by_id(listing_id)
    if not listing:
        await callback_query.answer("E'lon topilmadi.", show_alert=True)
        try:
            await callback_query.message.edit_text("Bu e'lon topilmadi yoki o'chirilgan.")
        except Exception:
            pass
        return
    
    # Format the original posting text and keyboard
    posting_text = format_my_posting_display(listing, user_lang)
    keyboard = get_posting_management_keyboard(
        listing_id, listing['is_approved'], user_lang, is_admin(callback_query.from_user.id)
    )
    
    try:
        # Check if the message to be edited has a photo
        if callback_query.message.photo:
            await callback_query.message.edit_caption(
                caption=posting_text,
                reply_markup=keyboard
            )
        else:
            await callback_query.message.edit_text(
                posting_text, 
                reply_markup=keyboard
            )
        await callback_query.answer(get_text(user_lang, 'action_cancelled'))
    except Exception as e:
        logger.error(f"Could not restore view on cancel delete: {e}. Falling back.")
        # Fallback: Delete the confirmation and resend the original posting
        try:
            await callback_query.message.delete()
        except Exception as del_e:
            logger.warning(f"Could not delete message on cancel fallback: {del_e}")

        # Re-send the posting as it appears in "My Postings"
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        if photo_file_ids:
            await callback_query.message.answer_photo(
                photo=photo_file_ids[0],
                caption=posting_text,
                reply_markup=keyboard
            )
        else:
            await callback_query.message.answer(posting_text, reply_markup=keyboard)
        await callback_query.answer(get_text(user_lang, 'action_cancelled'))


# ADMIN HANDLERS
@dp.callback_query(F.data.startswith('decline_'))
async def decline_listing(callback_query, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Sizda admin huquqlari yo'q!")
        return
    
    listing_id = int(callback_query.data.split('_')[1])
    
    await state.set_state(AdminStates.writing_feedback)
    await state.update_data(listing_id=listing_id)
    
    await callback_query.message.edit_text(
        f"❌ E'lon #{listing_id} rad etish sababi:\n\nFikr-mulohaza yozing:"
    )
    await callback_query.answer()

# Debug commands for testing
@dp.message(Command("debug"))
async def debug_handler(message: Message):
    """Debug database and search"""
    try:
        async with db_pool.acquire() as conn:
            # Check total listings
            total_count = await conn.fetchval('SELECT COUNT(*) FROM real_estate_property')
            approved_count = await conn.fetchval('SELECT COUNT(*) FROM real_estate_property WHERE is_approved = true')
            pending_count = await conn.fetchval('SELECT COUNT(*) FROM real_estate_property WHERE is_approved = false')
            
            status_counts = await conn.fetch('SELECT is_approved, COUNT(*) FROM real_estate_property GROUP BY is_approved')
        
        debug_text = f"""📊 Database Debug:
        
Total listings: {total_count}
Approved: {approved_count}
Pending: {pending_count}

Status breakdown:
{chr(10).join([f"- {'Approved' if status[0] else 'Pending'}: {status[1]}" for status in status_counts])}

Search test:"""
        
        await message.answer(debug_text)
        
        # Test search
        if approved_count > 0:
            listings = await search_listings("a")  # Search for letter "a"
            await message.answer(f"Search test 'a': Found {len(listings)} results")
            
            if listings:
                listing = listings[0]
                sample_text = f"Sample listing #{listing['id']}:\n{listing['description'][:100]}..."
                await message.answer(sample_text)
        else:
            await message.answer("❌ No approved listings found! Please approve some listings first using /admin")
            
    except Exception as e:
        await message.answer(f"❌ Debug error: {str(e)}")

@dp.message(Command("test_search"))
async def test_search_handler(message: Message):
    """Test search functionality"""
    user_lang = await get_user_language(message.from_user.id)
    
    # Test database connection
    try:
        listings = await search_listings("uy")
        await message.answer(f"✅ Search test: Found {len(listings)} listings with 'uy'")
        
        if listings:
            listing = listings[0]
            text = format_listing_raw_display(listing, user_lang)
            await message.answer(f"Sample listing:\n{text}")
        else:
            await message.answer("❌ No listings found in database")
            
    except Exception as e:
        await message.answer(f"❌ Search error: {str(e)}")

# Error handler
@dp.error()
async def error_handler(event):
    """Handle errors in bot"""
    update = event.update
    exception = event.exception
    
    logger.error(f"Error occurred in update {update.update_id}: {exception}")
    
    # Log full traceback for debugging
    import traceback
    logger.error(f"Full traceback: {traceback.format_exc()}")
    
    # Try to notify user if possible
    try:
        if update.message:
            user_lang = await get_user_language(update.message.from_user.id) if db_pool else 'uz'
            await update.message.answer("❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")
        elif update.callback_query:
            await update.callback_query.answer("❌ Xatolik yuz berdi.", show_alert=True)
    except Exception as notify_error:
        logger.error(f"Could not notify user about error: {notify_error}")
    
    return True

async def main():
    """Main bot function with proper initialization"""
    global db_pool
    
    logger.info("🤖 Starting Real Estate Bot...")
    
    # Check environment variables
    required_vars = ['BOT_TOKEN', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        logger.error("Please check your .env file")
        return
    
    # Initialize database pool
    logger.info("🔌 Connecting to database...")
    if not await init_db_pool():
        logger.error("❌ Failed to initialize database pool")
        logger.error("Please ensure PostgreSQL is running and Django migrations are applied")
        logger.error("Run: cd backend && python manage.py migrate")
        return
    
    # Test database connection
    try:
        async with db_pool.acquire() as conn:
            # Check if tables exist
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'real_estate_telegramuser'
                );
            """)
            
            if not table_exists:
                logger.error("❌ Database tables don't exist!")
                logger.error("Please run Django migrations first:")
                logger.error("   cd backend")
                logger.error("   python manage.py migrate")
                logger.error("   python manage.py populate_regions")
                await close_db_pool()
                return
            
            logger.info("✅ Database connection successful")
            
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        await close_db_pool()
        return
    
    logger.info("🚀 Starting bot polling...")
    
    try:
        # Start polling
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
    finally:
        logger.info("🔌 Closing connections...")
        await bot.session.close()
        await close_db_pool()
        logger.info("👋 Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())