import asyncio
import logging
import aiohttp
import json
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
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
ADMIN_CHANNEL_ID = os.getenv('ADMIN_CHANNEL_ID', '@your_admin_channel')  # New admin channel
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
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            raise Exception("User not found in database")
        
        photo_file_ids = json.dumps(data.get('photo_file_ids', []))
        
        title = data.get('title')
        if not title:
            description = data.get('description', 'No description')
            title = description.split('\n')[0][:50] + ('...' if len(description) > 50 else '')
        
        is_makler = data.get('is_makler', False)
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
                user_db_id, title, description, property_type, region, district,
                address, full_address, price, area, rooms, condition, status, 
                contact_info, photo_file_ids, False, False, True, 0, makler_note, 
                'pending', 0, False
            )
            
            logger.info(f"Successfully saved listing {listing_id} for user {user_id} (makler: {is_makler})")
            return listing_id
            
        except Exception as e:
            logger.error(f"Failed to save listing: {e}")
            raise Exception(f"Could not save listing. Database error: {str(e)}")

async def get_listings(limit=5, offset=0):
    """Get approved listings with pagination"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.is_approved = true AND p.is_active = true
            ORDER BY p.is_premium DESC, p.created_at DESC 
            LIMIT $1 OFFSET $2
        ''', limit, offset)

async def count_listings():
    """Count total approved listings"""
    async with db_pool.acquire() as conn:
        return await conn.fetchval('''
            SELECT COUNT(*) 
            FROM real_estate_property 
            WHERE is_approved = true AND is_active = true
        ''')

async def get_pending_listings(limit=5, offset=0):
    """Get pending listings for admin review"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.is_approved = false AND p.is_active = true
            ORDER BY p.created_at DESC 
            LIMIT $1 OFFSET $2
        ''', limit, offset)

async def count_pending_listings():
    """Count total pending listings"""
    async with db_pool.acquire() as conn:
        return await conn.fetchval('''
            SELECT COUNT(*) 
            FROM real_estate_property 
            WHERE is_approved = false AND is_active = true
        ''')

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

async def search_listings_by_location(region_key=None, district_key=None, property_type=None, status=None):
    """Search listings by region, district, property type and/or status"""
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
            
        if property_type and property_type != 'all':
            param_count += 1
            query += f' AND p.property_type = ${param_count}'
            params.append(property_type)
        
        if status and status != 'all':
            param_count += 1
            query += f' AND p.status = ${param_count}'
            params.append(status)
        
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

async def get_user_postings(user_id: int, limit=5, offset=0):
    """Get all postings by user with pagination"""
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
            LIMIT $2 OFFSET $3
        ''', user_db_id, limit, offset)

async def count_user_postings(user_id: int):
    """Count total user postings"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            return 0
        
        return await conn.fetchval('''
            SELECT COUNT(*) 
            FROM real_estate_property 
            WHERE user_id = $1
        ''', user_db_id)

async def update_listing_status(listing_id: int, is_approved: bool):
    """Update listing approval status"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_property SET is_approved = $1, approval_status = $2, updated_at = NOW() WHERE id = $3',
            is_approved, 'approved' if is_approved else 'pending', listing_id
        )

async def delete_listing_completely(listing_id: int) -> dict:
    """Completely delete listing and return affected user IDs and photo file IDs"""
    async with db_pool.acquire() as conn:
        favorite_users = await conn.fetch(
            'SELECT tu.telegram_id FROM real_estate_favorite f '
            'JOIN real_estate_telegramuser tu ON f.user_id = tu.id '
            'WHERE f.property_id = $1', 
            listing_id
        )
        
        photo_file_ids = await conn.fetchval(
            'SELECT photo_file_ids FROM real_estate_property WHERE id = $1',
            listing_id
        )
        
        await conn.execute(
            'DELETE FROM real_estate_favorite WHERE property_id = $1', 
            listing_id
        )
        
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

# FSM States
class ListingStates(StatesGroup):
    property_type = State()
    status = State()
    makler_type = State()
    region = State()
    district = State()
    price = State()
    area = State()
    description = State()
    contact_info = State()
    photos = State()
    preview = State()  # New state for post preview

class SearchStates(StatesGroup):
    search_type = State()
    keyword_query = State()
    status_filter = State()
    location_region = State()
    location_district = State()
    property_type_filter = State()

class AdminStates(StatesGroup):
    reviewing_listing = State()
    writing_feedback = State()

# Media group collector
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
            get_text(user_lang, 'photo_added_count', count=len(photo_file_ids)),
            reply_markup=get_photos_keyboard(user_lang)  # Resend buttons after each photo
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
            get_text(user_lang, 'media_group_received', count=len(messages)),
            reply_markup=get_photos_keyboard(user_lang)  # Resend buttons after media group
        )

media_collector = MediaGroupCollector()

# Translations (unchanged from original)
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
        'select_status_for_search': "🔍 Qidiruv turini tanlang:\n\n🏠 Sotuv yoki ijaraga berilganligi bo'yicha filtrlash",
        'all_statuses': "🔘 Barchasi",
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
        'select_status_for_search': "🔍 Выберите тип поиска:\n\n🏠 Фильтр по продаже или аренде",
        'all_statuses': "🔘 Все",
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
        'select_status_for_search': "🔍 Choose search type:\n\n🏠 Filter by sale or rent",
        'all_statuses': "🔘 All",
    }
}

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

DIRECT_POSTING_TRANSLATIONS = {
    'uz': {
        'listing_posted_successfully': "🎉 E'loningiz muvaffaqiyatli kanalga joylashtirildi!",
        'listing_saved_channel_error': "✅ E'lon saqlandi, lekin kanalga yuborishda xatolik yuz berdi.",
        'listing_saved_loading_error': "❌ E'lon saqlandi, lekin yuklab olishda xatolik yuz berdi.",
        'confirm_posting': "🔍 Quyidagi e'lon kanalga yuboriladi. Tasdiqlaysizmi?",
        'edit_posting': "✏️ E'lonni tahrirlash",
        'post_confirmed': "✅ E'lon tasdiqlandi va admin ko'rib chiqish uchun yuborildi!",
    },
    'ru': {
        'listing_posted_successfully': "🎉 Ваше объявление успешно размещено в канале!",
        'listing_saved_channel_error': "✅ Объявление сохранено, но произошла ошибка при отправке в канал.",
        'listing_saved_loading_error': "❌ Объявление сохранено, но произошла ошибка при загрузке.",
        'confirm_posting': "🔍 Это объявление будет отправлено в канал. Подтверждаете?",
        'edit_posting': "✏️ Редактировать объявление",
        'post_confirmed': "✅ Объявление подтверждено и отправлено на проверку администратору!",
    },
    'en': {
        'listing_posted_successfully': "🎉 Your listing has been successfully posted to the channel!",
        'listing_saved_channel_error': "✅ Listing saved, but there was an error posting to channel.",
        'listing_saved_loading_error': "❌ Listing saved, but there was an error loading it.",
        'confirm_posting': "🔍 This listing will be sent to the channel. Confirm?",
        'edit_posting': "✏️ Edit listing",
        'post_confirmed': "✅ Listing confirmed and sent for admin review!",
    }
}

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
    text = TRANSLATIONS.get(user_lang, TRANSLATIONS.get('uz', {})).get(key)
    if not text:
        text = SEARCH_TRANSLATIONS.get(user_lang, SEARCH_TRANSLATIONS.get('uz', {})).get(key)
    if not text:
        text = DIRECT_POSTING_TRANSLATIONS.get(user_lang, DIRECT_POSTING_TRANSLATIONS.get('uz', {})).get(key)
    if not text:
        text = APPROVAL_TRANSLATIONS.get(user_lang, APPROVAL_TRANSLATIONS.get('uz', {})).get(key)
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
        else:
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
        else:
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
            else:
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
            else:
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
        else:
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
            else:
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
    user_description = listing['description']
    contact_info = listing['contact_info']
    
    channel_text = f"""{user_description}

📞 Aloqa: {contact_info}
\n🗺 Manzil: {listing['full_address']}"""
    
    property_type = listing['property_type']
    status = listing['status']
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

def format_my_posting_display(listing, user_lang: str) -> str:
    """Format a user's own posting for display with status and makler information."""
    user_description = listing['description']
    location_display = listing['full_address'] if listing['full_address'] else listing['address']
    contact_info = listing['contact_info']
    
    is_makler = listing.get('admin_notes') == 'makler'
    makler_tag = '#makler' if is_makler else '#maklersiz'
    
    status_text = {
        'uz': {
            'approved': '✅ Tasdiqlangan',
            'pending': '⏳ Ko‘rib chiqilmoqda',
            'inactive': '⛔ Faol emas'
        },
        'ru': {
            'approved': '✅ Одобрено',
            'pending': '⏳ На рассмотрении',
            'inactive': '⛔ Не активно'
        },
        'en': {
            'approved': '✅ Approved',
            'pending': '⏳ Pending',
            'inactive': '⛔ Inactive'
        }
    }
    
    status = 'approved' if listing['is_approved'] else 'pending'
    status = 'inactive' if not listing['is_active'] else status
    
    listing_text = f"🆔 E'lon #{listing['id']}\n"
    listing_text += f"{user_description}\n\n"
    listing_text += f"📞 Aloqa: {contact_info}\n"
    
    if location_display and location_display.strip():
        listing_text += f"🗺 Manzil: {location_display}\n"
    
    listing_text += f"📊 Status: {status_text[user_lang][status]}\n"
    listing_text += f"⭐ Sevimlilar: {listing.get('favorite_count', 0)}\n"
    listing_text += f"\n#{listing['property_type']} #{listing['status']} {makler_tag}"
    
    return listing_text

def get_main_menu_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'post_listing'), callback_data="menu_post"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'my_postings'), callback_data="menu_my_postings"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'search'), callback_data="menu_search"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'favorites'), callback_data="menu_favorites"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'info'), callback_data="menu_info"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'language'), callback_data="menu_language"))
    builder.adjust(2)
    return builder.as_markup()

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
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="back_to_status"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_search_property_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'all_property_types'),
        callback_data="search_property_all"
    ))
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
    
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="back_to_makler"
    ))
    builder.adjust(2)
    return builder.as_markup()

def get_search_regions_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    regions = regions_config.get(user_lang, regions_config['uz'])
    
    for region_key, region_name in regions:
        builder.add(InlineKeyboardButton(
            text=region_name,
            callback_data=f"search_region_{region_key}"
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
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'all_region'),
        callback_data=f"search_all_region_{region_key}"
    ))
    
    try:
        districts = REGIONS_DATA[user_lang][region_key]['districts']
        
        for district_key, district_name in districts.items():
            builder.add(InlineKeyboardButton(
                text=district_name,
                callback_data=f"search_district_{district_key}"
            ))
    except KeyError:
        pass
    
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="search_back_to_regions"
    ))
    
    builder.adjust(1, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()

def get_search_status_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'sale'), 
        callback_data="search_status_sale"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'rent'), 
        callback_data="search_status_rent"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'all_statuses'), 
        callback_data="search_status_all"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="search_back_to_type"
    ))
    builder.adjust(2, 1)
    return builder.as_markup()

def get_property_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'apartment'), callback_data="type_apartment"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'house'), callback_data="type_house"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'commercial'), callback_data="type_commercial"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'land'), callback_data="type_land"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_menu"))
    builder.adjust(2)
    return builder.as_markup()

def get_status_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'sale'), callback_data="status_sale"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'rent'), callback_data="status_rent"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_property_type"))
    builder.adjust(2)
    return builder.as_markup()

def get_photos_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'photos_done'), callback_data="photos_done"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'skip'), callback_data="photos_skip"))
    builder.adjust(2)
    return builder.as_markup()

def get_preview_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Confirm", callback_data="confirm_post"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'edit_posting'), callback_data="edit_post"))
    builder.adjust(2)
    return builder.as_markup()

def get_admin_review_keyboard(listing_id: int, user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{listing_id}"))
    builder.add(InlineKeyboardButton(text="❌ Decline", callback_data=f"decline_{listing_id}"))
    builder.adjust(2)
    return builder.as_markup()

def get_listing_keyboard(listing_id: int, user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'add_favorite'), callback_data=f"fav_add_{listing_id}"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'contact_seller'), callback_data=f"contact_{listing_id}"))
    builder.adjust(2)
    return builder.as_markup()

def get_posting_management_keyboard(listing_id: int, is_approved: bool, user_lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if is_approved:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'deactivate_posting'), 
            callback_data=f"deactivate_post_{listing_id}"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'activate_posting'), 
            callback_data=f"activate_post_{listing_id}"
        ))
    
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'delete_posting'), 
        callback_data=f"delete_post_{listing_id}"
    ))
    
    if is_admin:
        builder.add(InlineKeyboardButton(
            text="🔧 Admin Actions", 
            callback_data=f"admin_post_{listing_id}"
        ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_pagination_keyboard(user_lang: str, offset: int, total_count: int, is_my_postings: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    prefix = "my_postings_page_" if is_my_postings else "listings_page_"
    
    if offset > 0:
        builder.add(InlineKeyboardButton(
            text="⬅️ Previous 5",
            callback_data=f"{prefix}{offset - 5}"
        ))
    
    if offset + 5 < total_count:
        builder.add(InlineKeyboardButton(
            text="Next 5 ➡️",
            callback_data=f"{prefix}{offset + 5}"
        ))
    
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back_to_menu'),
        callback_data="back_to_menu"
    ))
    
    builder.adjust(2)
    return builder.as_markup()

async def post_to_channel_with_makler(listing):
    try:
        channel_text = format_listing_for_channel_with_makler(listing)
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        # Verify CHANNEL_ID
        if not CHANNEL_ID.startswith('@') and not CHANNEL_ID.startswith('-'):
            logger.error(f"Invalid CHANNEL_ID format: {CHANNEL_ID}")
            raise ValueError("Invalid CHANNEL_ID format. Must start with '@' or '-'")
        
        try:
            # Check if bot can access the channel
            chat = await bot.get_chat(CHANNEL_ID)
            if not chat:
                raise ValueError(f"Channel {CHANNEL_ID} not found")
        except Exception as e:
            logger.error(f"Cannot access channel {CHANNEL_ID}: {e}")
            raise ValueError(f"Cannot access channel {CHANNEL_ID}: {e}")
        
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
        
        logger.info(f"Posted listing {listing['id']} to channel {CHANNEL_ID} with makler tag")
        return message
    
    except Exception as e:
        logger.error(f"Error posting to channel {CHANNEL_ID}: {e}")
        raise


async def post_to_admin_channel(listing):
    try:
        channel_text = format_listing_for_channel_with_makler(listing)
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        user_lang = await get_user_language(listing['user_id'])
        keyboard = get_admin_review_keyboard(listing['id'], user_lang)
        
        if photo_file_ids:
            if len(photo_file_ids) == 1:
                message = await bot.send_photo(
                    chat_id=ADMIN_CHANNEL_ID,
                    photo=photo_file_ids[0],
                    caption=f"🆔 Listing #{listing['id']}\n{channel_text}",
                    reply_markup=keyboard
                )
            else:
                media_group = MediaGroupBuilder(caption=f"🆔 Listing #{listing['id']}\n{channel_text}")
                for photo_id in photo_file_ids[:10]:
                    media_group.add_photo(media=photo_id)
                
                messages = await bot.send_media_group(chat_id=ADMIN_CHANNEL_ID, media=media_group.build())
                await bot.send_message(
                    chat_id=ADMIN_CHANNEL_ID,
                    text="👆 Review listing",
                    reply_markup=keyboard
                )
        else:
            message = await bot.send_message(
                chat_id=ADMIN_CHANNEL_ID,
                text=f"🆔 Listing #{listing['id']}\n{channel_text}",
                reply_markup=keyboard
            )
        
        logger.info(f"Posted listing {listing['id']} to admin channel for review")
        
    except Exception as e:
        logger.error(f"Error posting to admin channel: {e}")

async def display_search_results(message_or_callback, listings, user_lang, search_term="", state: FSMContext = None):
    is_callback = hasattr(message_or_callback, 'message')
    
    if not listings:
        text = get_text(user_lang, 'no_search_results')
        if is_callback:
            await message_or_callback.message.answer(text)
        else:
            await message_or_callback.answer(text)
        return
    
    filters_text = ""
    
    if state:
        data = await state.get_data()
        status_filter = data.get('search_status', 'all')
        property_filter = data.get('search_property_type', 'all')
        
        status_text = {
            'sale': get_text(user_lang, 'sale'),
            'rent': get_text(user_lang, 'rent'),
            'all': get_text(user_lang, 'all_statuses')
        }.get(status_filter, 'all')
        
        property_text = get_text(user_lang, property_filter) if property_filter != 'all' else get_text(user_lang, 'all_property_types')
        
        filters_text = (f"\n🔹 {get_text(user_lang, 'status')}: {status_text}"
                       f"\n🔹 {get_text(user_lang, 'property_type')}: {property_text}")
    
    results_text = (f"{get_text(user_lang, 'search_results_count', count=len(listings))}"
                   f"{filters_text}"
                   f"\n🔹 {get_text(user_lang, 'location')}: {search_term}")
    
    if is_callback:
        await message_or_callback.message.answer(results_text)
    else:
        await message_or_callback.answer(results_text)
    
    for listing in listings:
        listing_text = format_listing_raw_display(listing, user_lang)
        keyboard = get_listing_keyboard(listing['id'], user_lang)
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        try:
            if photo_file_ids:
                if len(photo_file_ids) == 1:
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
                if is_callback:
                    await message_or_callback.message.answer(listing_text, reply_markup=keyboard)
                else:
                    await message_or_callback.answer(listing_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error in display_search_results: {e}")

async def display_paginated_listings(callback_query, offset: int, is_my_postings: bool = False):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    if is_my_postings:
        listings = await get_user_postings(callback_query.from_user.id, limit=5, offset=offset)
        total_count = await count_user_postings(callback_query.from_user.id)
        header_text = f"📝 Sizning e'lonlaringiz: {total_count} ta"
    else:
        listings = await get_listings(limit=5, offset=offset)
        total_count = await count_listings()
        header_text = f"📝 E'lonlar: {total_count} ta"
    
    await callback_query.message.edit_text(
        f"{header_text}\n(Showing {offset + 1}-{min(offset + 5, total_count)})",
        reply_markup=get_pagination_keyboard(user_lang, offset, total_count, is_my_postings)
    )
    
    for listing in listings:
        listing_text = format_my_posting_display(listing, user_lang) if is_my_postings else format_listing_raw_display(listing, user_lang)
        keyboard = get_posting_management_keyboard(listing['id'], listing['is_approved'], user_lang, is_admin(callback_query.from_user.id)) if is_my_postings else get_listing_keyboard(listing['id'], user_lang)
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        try:
            if photo_file_ids:
                await callback_query.message.answer_photo(
                    photo=photo_file_ids[0],
                    caption=listing_text,
                    reply_markup=keyboard
                )
            else:
                await callback_query.message.answer(listing_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error displaying listing {listing['id']}: {e}")
            await callback_query.message.answer(listing_text, reply_markup=keyboard)

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

@dp.callback_query(F.data == 'menu_language')
async def language_handler(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    await callback_query.message.edit_text(
        get_text(user_lang, 'choose_language'),
        reply_markup=get_language_keyboard()
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('lang_'))
async def language_callback(callback_query):
    lang = callback_query.data.split('_')[1]
    await update_user_language(callback_query.from_user.id, lang)
    
    await callback_query.answer(f"Language changed!")
    
    await callback_query.message.edit_text(
        get_text(lang, 'main_menu'),
        reply_markup=get_main_menu_keyboard(lang)
    )

# SEARCH HANDLERS
@dp.callback_query(F.data == 'menu_search')
async def search_handler(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.search_type)
    await callback_query.message.edit_text(
        get_text(user_lang, 'choose_search_type'),
        reply_markup=get_search_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'search_keyword')
async def search_keyword_selected(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.keyword_query)
    await callback_query.message.edit_text(get_text(user_lang, 'search_prompt'))
    await callback_query.answer()

@dp.callback_query(F.data == 'search_location')
async def search_location_selected(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.status_filter)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_status_for_search'),
        reply_markup=get_search_status_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.message(SearchStates.keyword_query)
async def process_keyword_search(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    query = message.text.strip()
    await state.clear()
    
    listings = await search_listings(query)
    await display_search_results(message, listings, user_lang, query)

@dp.callback_query(F.data.startswith('search_status_'))
async def process_search_status_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    status = callback_query.data[13:]
    
    if status == 'all':
        await state.update_data(search_status=None)
    else:
        await state.update_data(search_status=status)
    
    await state.set_state(SearchStates.location_region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region_for_search'),
        reply_markup=get_search_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('search_region_'))
async def process_search_region_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    region_key = callback_query.data[14:]
    
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

@dp.callback_query(F.data.startswith('search_all_region_'))
async def process_search_all_region(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    region_key = callback_query.data[18:]
    
    await state.update_data(search_region=region_key, search_district=None)
    await state.set_state(SearchStates.property_type_filter)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_property_type_filter'),
        reply_markup=get_search_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('search_district_'))
async def process_search_district_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    district_key = callback_query.data[16:]
    
    data = await state.get_data()
    region_key = data.get('search_region')
    
    await state.update_data(search_district=district_key)
    await state.set_state(SearchStates.property_type_filter)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_property_type_filter'),
        reply_markup=get_search_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'search_property_all')
async def process_search_all_property_types(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    region_key = data.get('search_region')
    district_key = data.get('search_district')
    
    await state.clear()
    
    listings = await search_listings_by_location(
        region_key=region_key, 
        district_key=district_key, 
        property_type=None
    )
    
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
    property_type = callback_query.data[16:]
    
    data = await state.get_data()
    region_key = data.get('search_region')
    district_key = data.get('search_district')
    
    await state.clear()
    
    listings = await search_listings_by_location(
        region_key=region_key, 
        district_key=district_key, 
        property_type=property_type if property_type != 'all' else None
    )
    
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

# LISTING CREATION HANDLERS
@dp.callback_query(F.data == 'menu_post')
async def post_listing_handler(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.property_type)
    await callback_query.message.edit_text(
        get_text(user_lang, 'property_type'),
        reply_markup=get_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

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
    
    await state.set_state(ListingStates.makler_type)
    await callback_query.message.edit_text(
        get_text_makler(user_lang, 'ask_makler_type'),
        reply_markup=get_makler_type_keyboard(user_lang)
    )
    await callback_query.answer()

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

@dp.callback_query(F.data.startswith('region_'), ListingStates.region)
async def process_region_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    region_key = callback_query.data[7:]
    
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
    
    await state.set_state(ListingStates.price)
    await callback_query.message.edit_text(get_text(user_lang, 'ask_price'))
    await callback_query.answer(get_text(user_lang, 'district_selected'))

@dp.message(ListingStates.price)
async def process_price(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    try:
        price_text = message.text.strip()
        price_clean = ''.join(filter(str.isdigit, price_text))
        
        if not price_clean:
            await message.answer(
                get_text(user_lang, 'invalid_price'),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_district")
                ]])
            )
            return
        
        await state.update_data(price=int(price_clean))
        await state.set_state(ListingStates.area)
        await message.answer(get_text(user_lang, 'ask_area'))
    except ValueError:
        await message.answer(
            get_text(user_lang, 'invalid_price'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_district")
            ]])
        )

@dp.message(ListingStates.area)
async def process_area(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    try:
        area_text = message.text.strip()
        area_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', area_text))
        
        if not area_clean:
            await message.answer(
                get_text(user_lang, 'invalid_area'),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_price")
                ]])
            )
            return
        
        await state.update_data(area=float(area_clean))
        await state.set_state(ListingStates.description)
        
        data = await state.get_data()
        region_key = data.get('region')
        district_key = data.get('district')
        property_type = data.get('property_type')
        status = data.get('status')
        price = data.get('price')
        area = data.get('area')
        
        try:
            region_name = REGIONS_DATA[user_lang][region_key]['name']
            district_name = REGIONS_DATA[user_lang][region_key]['districts'][district_key]
            location = f"{district_name}, {region_name}"
        except KeyError:
            location = "Selected location"
        
        template = get_personalized_listing_template(user_lang, status, property_type, str(price), str(area), location)
        await message.answer(
            get_text(user_lang, 'personalized_template_shown') + "\n\n" + template,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_price")
            ]])
        )
    except ValueError:
        await message.answer(
            get_text(user_lang, 'invalid_area'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_price")
            ]])
        )

@dp.message(ListingStates.description)
async def process_description(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    description = message.text.strip()
    
    if not description:
        await message.answer(
            get_text(user_lang, 'description_empty'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_area")
            ]])
        )
        return
    
    await state.update_data(description=description)
    await state.set_state(ListingStates.contact_info)
    await message.answer(
        get_text(user_lang, 'ask_contact_info'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_area")
        ]])
    )

@dp.message(ListingStates.contact_info)
async def process_contact_info(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    contact_info = message.text.strip()
    
    if not contact_info:
        await message.answer(
            get_text(user_lang, 'contact_info_empty'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_description")
            ]])
        )
        return
    
    await state.update_data(contact_info=contact_info)
    await state.set_state(ListingStates.photos)
    await message.answer(
        get_text(user_lang, 'send_photos'),
        reply_markup=get_photos_keyboard(user_lang)
    )

@dp.message(ListingStates.photos, F.photo)
async def process_photos(message: Message, state: FSMContext):
    await media_collector.add_message(message, state)

@dp.callback_query(F.data == 'photos_done')
async def photos_done(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    if not data.get('photo_file_ids'):
        await state.update_data(photo_file_ids=[])
    
    listing_data = {
        'property_type': data.get('property_type', 'apartment'),
        'status': data.get('status', 'sale'),
        'is_makler': data.get('is_makler', False),
        'region': data.get('region', ''),
        'district': data.get('district', ''),
        'price': data.get('price', 0),
        'area': data.get('area', 0),
        'description': data.get('description', ''),
        'contact_info': data.get('contact_info', ''),
        'photo_file_ids': data.get('photo_file_ids', []),
        'full_address': f"{REGIONS_DATA[user_lang][data['region']]['districts'][data['district']]}, {REGIONS_DATA[user_lang][data['region']]['name']}"
    }
    
    channel_text = format_listing_for_channel_with_makler(listing_data)
    await state.set_state(ListingStates.preview)
    
    photo_file_ids = data.get('photo_file_ids', [])
    if photo_file_ids:
        await callback_query.message.answer_photo(
            photo=photo_file_ids[0],
            caption=get_text(user_lang, 'confirm_posting') + "\n\n" + channel_text,
            reply_markup=get_preview_keyboard(user_lang)
        )
    else:
        await callback_query.message.edit_text(
            get_text(user_lang, 'confirm_posting') + "\n\n" + channel_text,
            reply_markup=get_preview_keyboard(user_lang)
        )
    await callback_query.answer()

@dp.callback_query(F.data == 'photos_skip')
async def skip_photos(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.update_data(photo_file_ids=[])
    
    data = await state.get_data()
    listing_data = {
        'property_type': data.get('property_type', 'apartment'),
        'status': data.get('status', 'sale'),
        'is_makler': data.get('is_makler', False),
        'region': data.get('region', ''),
        'district': data.get('district', ''),
        'price': data.get('price', 0),
        'area': data.get('area', 0),
        'description': data.get('description', ''),
        'contact_info': data.get('contact_info', ''),
        'photo_file_ids': [],
        'full_address': f"{REGIONS_DATA[user_lang][data['region']]['districts'][data['district']]}, {REGIONS_DATA[user_lang][data['region']]['name']}"
    }
    
    channel_text = format_listing_for_channel_with_makler(listing_data)
    await state.set_state(ListingStates.preview)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'confirm_posting') + "\n\n" + channel_text,
        reply_markup=get_preview_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'confirm_post')
async def confirm_posting(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    try:
        listing_id = await save_listing_with_makler(callback_query.from_user.id, data)
        listing = await get_listing_by_id(listing_id)
        await post_to_admin_channel(listing)
        
        # Check if the message is a photo or text
        if callback_query.message.photo:
            await callback_query.message.edit_caption(
                caption=get_text(user_lang, 'listing_submitted_for_review'),
                reply_markup=get_main_menu_keyboard(user_lang)
            )
        else:
            await callback_query.message.edit_text(
                text=get_text(user_lang, 'listing_submitted_for_review'),
                reply_markup=get_main_menu_keyboard(user_lang)
            )
        
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving listing: {e}")
        # Fallback to sending a new message if edit fails
        try:
            await callback_query.message.delete()
        except:
            pass
        await callback_query.message.answer(
            get_text(user_lang, 'listing_saved_channel_error'),
            reply_markup=get_main_menu_keyboard(user_lang)
        )
    await callback_query.answer()


@dp.callback_query(F.data == 'edit_post')
async def edit_posting(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.property_type)
    
    try:
        if callback_query.message.photo:
            await callback_query.message.edit_caption(
                caption=get_text(user_lang, 'property_type'),
                reply_markup=get_property_type_keyboard(user_lang)
            )
        else:
            await callback_query.message.edit_text(
                text=get_text(user_lang, 'property_type'),
                reply_markup=get_property_type_keyboard(user_lang)
            )
    except Exception as e:
        logger.error(f"Error editing message for edit_post: {e}")
        # Fallback to sending a new message
        try:
            await callback_query.message.delete()
        except:
            pass
        await callback_query.message.answer(
            get_text(user_lang, 'property_type'),
            reply_markup=get_property_type_keyboard(user_lang)
        )
    
    await callback_query.answer()

@dp.callback_query(F.data.startswith('approve_'))
async def approve_listing(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Access denied!")
        return
    
    listing_id = int(callback_query.data.split('_')[1])
    await update_listing_status(listing_id, True)
    listing = await get_listing_by_id(listing_id)
    
    try:
        await post_to_channel_with_makler(listing)
        await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.message.answer(
            get_text('uz', 'listing_approved'),
            reply_markup=get_main_menu_keyboard('uz')
        )
        
        user_lang = await get_user_language(listing['user_id'])
        await bot.send_message(
            chat_id=listing['user_id'],
            text=get_text(user_lang, 'listing_approved')
        )
    except Exception as e:
        logger.error(f"Error posting approved listing {listing_id}: {e}")
        await callback_query.message.answer(
            f"Error posting to main channel: {str(e)}",
            reply_markup=get_main_menu_keyboard('uz')
        )
    
    await callback_query.answer()
@dp.callback_query(F.data.startswith('decline_'))
async def decline_listing(callback_query: CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Access denied!")
        return
    
    listing_id = int(callback_query.data.split('_')[1])
    await state.update_data(decline_listing_id=listing_id)
    await state.set_state(AdminStates.writing_feedback)
    
    await callback_query.message.edit_text(
        "📝 Please provide feedback for declining this listing:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Cancel", callback_data="cancel_decline")
        ]])
    )
    await callback_query.answer()

@dp.message(AdminStates.writing_feedback)
async def process_decline_feedback(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    data = await state.get_data()
    listing_id = data.get('decline_listing_id')
    
    feedback = message.text.strip()
    listing = await get_listing_by_id(listing_id)
    
    await update_listing_status(listing_id, False)
    await bot.send_message(
        chat_id=listing['user_id'],
        text=get_text(user_lang, 'listing_declined', feedback=feedback)
    )
    
    await message.answer(
        "Listing declined and feedback sent to user.",
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await state.clear()

@dp.callback_query(F.data == 'cancel_decline')
async def cancel_decline(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.clear()
    await callback_query.message.edit_text(
        "Decline cancelled.",
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'menu_my_postings')
async def my_postings_handler(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    await display_paginated_listings(callback_query, offset=0, is_my_postings=True)
    await callback_query.answer()

@dp.callback_query(F.data.startswith('my_postings_page_'))
async def paginate_my_postings(callback_query: CallbackQuery):
    offset = int(callback_query.data.split('_')[3])
    await display_paginated_listings(callback_query, offset, is_my_postings=True)
    await callback_query.answer()

@dp.callback_query(F.data.startswith('listings_page_'))
async def paginate_listings(callback_query: CallbackQuery):
    offset = int(callback_query.data.split('_')[2])
    await display_paginated_listings(callback_query, offset)
    await callback_query.answer()

@dp.callback_query(F.data.startswith('fav_add_'))
async def add_favorite(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    listing_id = int(callback_query.data.split('_')[2])
    
    await add_to_favorites(callback_query.from_user.id, listing_id)
    await callback_query.answer(get_text(user_lang, 'added_to_favorites'))

@dp.callback_query(F.data == 'menu_favorites')
async def show_favorites(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    favorites = await get_user_favorites(callback_query.from_user.id)
    
    if not favorites:
        await callback_query.message.edit_text(
            get_text(user_lang, 'no_favorites'),
            reply_markup=get_main_menu_keyboard(user_lang)
        )
        await callback_query.answer()
        return
    
    await callback_query.message.edit_text(
        f"⭐ Your favorites ({len(favorites)}):",
        reply_markup=None
    )
    
    for listing in favorites:
        listing_text = format_listing_raw_display(listing, user_lang)
        keyboard = get_listing_keyboard(listing['id'], user_lang)
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        try:
            if photo_file_ids:
                await callback_query.message.answer_photo(
                    photo=photo_file_ids[0],
                    caption=listing_text,
                    reply_markup=keyboard
                )
            else:
                await callback_query.message.answer(listing_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error displaying favorite listing {listing['id']}: {e}")
            await callback_query.message.answer(listing_text, reply_markup=keyboard)
    
    await callback_query.message.answer(
        "🔙 Back to menu",
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('contact_'))
async def contact_seller(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    listing_id = int(callback_query.data.split('_')[1])
    
    listing = await get_listing_by_id(listing_id)
    if listing:
        await callback_query.message.answer(
            f"📞 Contact: {listing['contact_info']}\n\n"
            f"Listing: {listing['title']}"
        )
    else:
        await callback_query.message.answer(
            get_text(user_lang, 'listing_not_found')
        )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('deactivate_post_'))
async def deactivate_posting(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    listing_id = int(callback_query.data.split('_')[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_property SET is_active = false, updated_at = NOW() WHERE id = $1',
            listing_id
        )
    
    await callback_query.message.edit_reply_markup(
        reply_markup=get_posting_management_keyboard(listing_id, False, user_lang, is_admin(callback_query.from_user.id))
    )
    await callback_query.answer("Listing deactivated")

@dp.callback_query(F.data.startswith('activate_post_'))
async def activate_posting(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    listing_id = int(callback_query.data.split('_')[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_property SET is_active = true, updated_at = NOW() WHERE id = $1',
            listing_id
        )
    
    await callback_query.message.edit_reply_markup(
        reply_markup=get_posting_management_keyboard(listing_id, True, user_lang, is_admin(callback_query.from_user.id))
    )
    await callback_query.answer("Listing activated")

@dp.callback_query(F.data.startswith('delete_post_'))
async def delete_posting(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    listing_id = int(callback_query.data.split('_')[2])
    
    deleted_data = await delete_listing_completely(listing_id)
    
    for user_id in deleted_data['user_ids']:
        user_lang = await get_user_language(user_id)
        await bot.send_message(
            chat_id=user_id,
            text=get_text(user_lang, 'listing_removed_from_favorites')
        )
    
    await callback_query.message.delete()
    await callback_query.message.answer(
        get_text(user_lang, 'listing_deleted'),
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_menu')
async def back_to_menu(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.clear()
    await callback_query.message.edit_text(
        get_text(user_lang, 'main_menu'),
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_property_type')
async def back_to_property_type(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.property_type)
    await callback_query.message.edit_text(
        get_text(user_lang, 'property_type'),
        reply_markup=get_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_status')
async def back_to_status(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.status)
    await callback_query.message.edit_text(
        get_text(user_lang, 'status'),
        reply_markup=get_status_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_makler')
async def back_to_makler(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.makler_type)
    await callback_query.message.edit_text(
        get_text_makler(user_lang, 'ask_makler_type'),
        reply_markup=get_makler_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_regions')
async def back_to_regions(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_district')
async def back_to_district(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    region_key = data.get('region')
    
    await state.set_state(ListingStates.district)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_district'),
        reply_markup=get_districts_keyboard(region_key, user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_price')
async def back_to_price(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.price)
    await callback_query.message.edit_text(
        get_text(user_lang, 'ask_price'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_district")
        ]])
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_area')
async def back_to_area(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.area)
    await callback_query.message.edit_text(
        get_text(user_lang, 'ask_area'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_price")
        ]])
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_description')
async def back_to_description(callback_query: CallbackQuery, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(ListingStates.description)
    await callback_query.message.edit_text(
        get_text(user_lang, 'ask_description'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_area")
        ]])
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'menu_info')
async def info_handler(callback_query: CallbackQuery):
    user_lang = await get_user_language(callback_query.from_user.id)
    await callback_query.message.edit_text(
        get_text(user_lang, 'info_text'),
        reply_markup=get_main_menu_keyboard(user_lang)
    )
    await callback_query.answer()

async def main():
    try:
        if not await init_db_pool():
            logger.error("Failed to initialize database pool. Exiting...")
            return
        
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await close_db_pool()
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())