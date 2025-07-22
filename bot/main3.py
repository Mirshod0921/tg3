import asyncio
import logging
import aiohttp
import json
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonCommands,
    CallbackQuery, InputFile, FSInputFile
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
ADMIN_CHANNEL_ID = os.getenv('ADMIN_CHANNEL_ID', '@your_admin_channel')  # NEW: Admin approval channel
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
# Initialize bot with menu button
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(
    parse_mode=ParseMode.HTML
))

# Set menu button
async def set_menu_button():
    await bot.set_chat_menu_button(
        menu_button=MenuButtonCommands()
    )

# Call this in main() before starting polling
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Database connection pool
db_pool = None

# NEW: Pagination constants
POSTINGS_PER_PAGE = 3
SEARCH_RESULTS_PER_PAGE = 5

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
    """Save listing to database with makler information - PENDING APPROVAL"""
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
            
            # NEW: Save as PENDING instead of auto-approving
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
                False,                                # is_approved (CHANGED: pending approval)
                True,                                 # is_active
                0,                                    # views_count
                makler_note,                          # admin_notes (store makler info)
                'pending',                            # approval_status (CHANGED: pending)
                0,                                    # favorites_count
                False                                 # posted_to_channel
            )
            
            logger.info(f"Successfully saved listing {listing_id} for user {user_id} (makler: {is_makler}) - PENDING APPROVAL")
            return listing_id
            
        except Exception as e:
            logger.error(f"Failed to save listing: {e}")
            raise Exception(f"Could not save listing. Database error: {str(e)}")

# NEW: Get pending listings for admin approval
async def get_pending_listings():
    """Get all pending listings for admin approval"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username, u.telegram_id as user_telegram_id
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE p.approval_status = 'pending'
            ORDER BY p.created_at ASC
        ''')

# NEW: Approve/reject listing
async def update_listing_approval(listing_id: int, approved: bool, admin_id: int, feedback: str = None):
    """Update listing approval status"""
    async with db_pool.acquire() as conn:
        if approved:
            await conn.execute('''
                UPDATE real_estate_property 
                SET approval_status = 'approved', is_approved = true, published_at = NOW()
                WHERE id = $1
            ''', listing_id)
        else:
            await conn.execute('''
                UPDATE real_estate_property 
                SET approval_status = 'rejected', is_approved = false
                WHERE id = $1
            ''', listing_id)

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

async def search_listings(query: str, limit=10, offset=0):
    """Search listings by keyword with pagination"""
    async with db_pool.acquire() as conn:
        return await conn.fetch('''
            SELECT p.*, u.first_name, u.username 
            FROM real_estate_property p 
            JOIN real_estate_telegramuser u ON p.user_id = u.id 
            WHERE (p.title ILIKE $1 OR p.description ILIKE $1 OR p.full_address ILIKE $1) 
            AND p.is_approved = true AND p.is_active = true
            ORDER BY p.is_premium DESC, p.created_at DESC 
            LIMIT $2 OFFSET $3
        ''', f'%{query}%', limit, offset)

async def search_listings_by_location(region_key=None, district_key=None, property_type=None, status=None, limit=10, offset=0):
    """Search listings by region, district, property type and/or status with pagination"""
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
        
        # Add pagination
        param_count += 1
        query += f' ORDER BY p.is_premium DESC, p.created_at DESC LIMIT ${param_count}'
        params.append(limit)
        
        param_count += 1
        query += f' OFFSET ${param_count}'
        params.append(offset)
        
        return await conn.fetch(query, *params)

async def get_user_postings(user_id: int, limit=10, offset=0):
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

async def get_user_postings_count(user_id: int) -> int:
    """Get total count of user postings"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            return 0
        
        return await conn.fetchval(
            'SELECT COUNT(*) FROM real_estate_property WHERE user_id = $1',
            user_db_id
        )

async def get_search_results_count(query: str = None, region_key=None, district_key=None, property_type=None, status=None) -> int:
    """Get total count of search results"""
    async with db_pool.acquire() as conn:
        if query:
            return await conn.fetchval('''
                SELECT COUNT(*) FROM real_estate_property p 
                WHERE (p.title ILIKE $1 OR p.description ILIKE $1 OR p.full_address ILIKE $1) 
                AND p.is_approved = true AND p.is_active = true
            ''', f'%{query}%')
        else:
            # Location-based search count
            count_query = '''
                SELECT COUNT(*) FROM real_estate_property p 
                WHERE p.is_approved = true AND p.is_active = true
            '''
            params = []
            param_count = 0
            
            if region_key:
                param_count += 1
                count_query += f' AND p.region = ${param_count}'
                params.append(region_key)
            
            if district_key:
                param_count += 1
                count_query += f' AND p.district = ${param_count}'
                params.append(district_key)
                
            if property_type and property_type != 'all':
                param_count += 1
                count_query += f' AND p.property_type = ${param_count}'
                params.append(property_type)
            
            if status and status != 'all':
                param_count += 1
                count_query += f' AND p.status = ${param_count}'
                params.append(status)
            
            return await conn.fetchval(count_query, *params)

async def get_listing_by_id(listing_id: int):
    """Get listing by ID with user info"""
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('''
            SELECT p.*, u.first_name, u.username, u.telegram_id as user_telegram_id
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

async def get_user_favorites(user_id: int, limit=10, offset=0):
    """Get user's favorite listings with pagination"""
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
            LIMIT $2 OFFSET $3
        ''', user_db_id, limit, offset)

async def get_user_favorites_count(user_id: int) -> int:
    """Get total count of user favorites"""
    async with db_pool.acquire() as conn:
        user_db_id = await conn.fetchval(
            'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
            user_id
        )
        
        if not user_db_id:
            return 0
        
        return await conn.fetchval('''
            SELECT COUNT(*) FROM real_estate_favorite f
            JOIN real_estate_property p ON f.property_id = p.id
            WHERE f.user_id = $1 AND p.is_approved = true AND p.is_active = true
        ''', user_db_id)

async def update_listing_status(listing_id: int, is_active: bool):
    """Update listing active status"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            'UPDATE real_estate_property SET is_approved = $1, updated_at = NOW() WHERE id = $2',
            is_active, listing_id
        )

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
    makler_type = State()        
    region = State()             
    district = State()
    price = State()              
    area = State()                           
    description = State()        
    confirmation = State()       
    contact_info = State()       
    photos = State()
    final_confirmation = State()  # NEW: Final confirmation state

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

# NEW: Pagination states
class PaginationStates(StatesGroup):
    viewing_postings = State()
    viewing_search_results = State()
    viewing_favorites = State()

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
        
        # NEW: Send ready button after each photo
        await self.send_photo_ready_button(message, state)
    
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
        
        # NEW: Send ready button after media group
        await self.send_photo_ready_button(messages[0], state)
    
    async def send_photo_ready_button(self, message: Message, state: FSMContext):
        """Send ready button after photo upload"""
        user_lang = await get_user_language(message.from_user.id)
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'photos_done'), 
            callback_data="photos_done"
        ))
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'skip'), 
            callback_data="photos_skip"
        ))
        builder.adjust(2)
        
        await message.answer(
            get_text(user_lang, 'photos_ready_prompt'),
            reply_markup=builder.as_markup()
        )

# Initialize media collector
media_collector = MediaGroupCollector()

# NEW: Enhanced translations
ENHANCED_TRANSLATIONS = {
    'uz': {
        'photos_ready_prompt': "📸 Rasmlar yuklandi! Davom etasizmi?",
        'listing_preview_title': "👀 E'loningiz quyidagicha ko'rinadi:\n\n<i>Tasdiqlansa, aynan shu formatda kanalga joylanadi:</i>",
        'confirm_posting': "E'lonni yuborish uchun tasdiqlang:",
        'yes_confirm_post': "✅ Ha, yuborish",
        'edit_listing': "✏️ Tahrirlash",
        'cancel_posting': "❌ Bekor qilish",
        'edit_what': "Nimani tahrir qilmoqchisiz?",
        'edit_property_type': "🏠 Uy-joy turi",
        'edit_status': "🎯 Maqsad (sotish/ijara)",
        'edit_makler': "👨‍💼 Makler holati",
        'edit_location': "📍 Joylashuv",
        'edit_price': "💰 Narx",
        'edit_area': "📐 Maydon",
        'edit_description': "📝 Tavsif",
        'edit_contact': "📞 Aloqa",
        'edit_photos': "📸 Rasmlar",
        'page_info': "📄 Sahifa {current} / {total}",
        'next_page': "Keyingi ▶️",
        'prev_page': "◀️ Oldingi",
        'total_results': "Jami: {total} ta",
        'admin_new_listing': "🆕 YANGI E'LON TEKSHIRISH UCHUN",
        'admin_approve': "✅ Tasdiqlash",
        'admin_reject': "❌ Rad etish",
        'admin_approved_notification': "✅ E'loningiz tasdiqlandi va kanalga joylandi!",
        'admin_rejected_notification': "❌ E'loningiz rad etildi.\n\nSabab: {reason}",
        'no_pending_listings': "📭 Tasdiqlanishi kutilayotgan e'lonlar yo'q",
    },
    'ru': {
        'photos_ready_prompt': "📸 Фото загружены! Продолжить?",
        'listing_preview_title': "👀 Ваше объявление будет выглядеть так:\n\n<i>Если одобрено, будет размещено в канале именно в таком формате:</i>",
        'confirm_posting': "Подтвердите отправку объявления:",
        'yes_confirm_post': "✅ Да, отправить",
        'edit_listing': "✏️ Редактировать",
        'cancel_posting': "❌ Отмена",
        'edit_what': "Что вы хотите отредактировать?",
        'edit_property_type': "🏠 Тип недвижимости",
        'edit_status': "🎯 Цель (продажа/аренда)",
        'edit_makler': "👨‍💼 Статус риелтора",
        'edit_location': "📍 Местоположение",
        'edit_price': "💰 Цена",
        'edit_area': "📐 Площадь",
        'edit_description': "📝 Описание",
        'edit_contact': "📞 Контакты",
        'edit_photos': "📸 Фотографии",
        'page_info': "📄 Страница {current} / {total}",
        'next_page': "Далее ▶️",
        'prev_page': "◀️ Назад",
        'total_results': "Всего: {total}",
        'admin_new_listing': "🆕 НОВОЕ ОБЪЯВЛЕНИЕ ДЛЯ ПРОВЕРКИ",
        'admin_approve': "✅ Одобрить",
        'admin_reject': "❌ Отклонить",
        'admin_approved_notification': "✅ Ваше объявление одобрено и размещено в канале!",
        'admin_rejected_notification': "❌ Ваше объявление отклонено.\n\nПричина: {reason}",
        'no_pending_listings': "📭 Нет объявлений ожидающих одобрения",
    },
    'en': {
        'photos_ready_prompt': "📸 Photos uploaded! Continue?",
        'listing_preview_title': "👀 Your listing will look like this:\n\n<i>If approved, it will be posted to the channel in exactly this format:</i>",
        'confirm_posting': "Confirm posting submission:",
        'yes_confirm_post': "✅ Yes, submit",
        'edit_listing': "✏️ Edit",
        'cancel_posting': "❌ Cancel",
        'edit_what': "What would you like to edit?",
        'edit_property_type': "🏠 Property type",
        'edit_status': "🎯 Purpose (sale/rent)",
        'edit_makler': "👨‍💼 Realtor status",
        'edit_location': "📍 Location",
        'edit_price': "💰 Price",
        'edit_area': "📐 Area",
        'edit_description': "📝 Description",
        'edit_contact': "📞 Contact",
        'edit_photos': "📸 Photos",
        'page_info': "📄 Page {current} / {total}",
        'next_page': "Next ▶️",
        'prev_page': "◀️ Previous",
        'total_results': "Total: {total}",
        'admin_new_listing': "🆕 NEW LISTING FOR REVIEW",
        'admin_approve': "✅ Approve",
        'admin_reject': "❌ Reject",
        'admin_approved_notification': "✅ Your listing has been approved and posted to the channel!",
        'admin_rejected_notification': "❌ Your listing has been rejected.\n\nReason: {reason}",
        'no_pending_listings': "📭 No listings pending approval",
    }
}

# Helper functions
def get_text(user_lang: str, key: str, **kwargs) -> str:
    # Try to get from main TRANSLATIONS first
    text = TRANSLATIONS.get(user_lang, TRANSLATIONS.get('uz', {})).get(key)
    
    # If not found, try from ENHANCED_TRANSLATIONS
    if not text:
        text = ENHANCED_TRANSLATIONS.get(user_lang, ENHANCED_TRANSLATIONS.get('uz', {})).get(key)
    
    # If still not found, return a default message
    if not text:
        text = key
    
    if kwargs and text:
        try:
            return text.format(**kwargs)
        except:
            return text
    return text

def get_main_menu_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    """Main menu with inline buttons - 1 per row"""
    builder = InlineKeyboardBuilder()
    buttons = [
        InlineKeyboardButton(text=get_text(user_lang, 'post_listing'), callback_data="main_post_listing"),
        InlineKeyboardButton(text=get_text(user_lang, 'my_postings'), callback_data="main_my_postings"),
        InlineKeyboardButton(text=get_text(user_lang, 'search'), callback_data="main_search"),
        InlineKeyboardButton(text=get_text(user_lang, 'favorites'), callback_data="main_favorites"),
        InlineKeyboardButton(text=get_text(user_lang, 'info'), callback_data="main_info"),
        InlineKeyboardButton(text=get_text(user_lang, 'language'), callback_data="main_language")
    ]
    
    # Add all buttons with 1 per row
    for button in buttons:
        builder.add(button)
    builder.adjust(1)
    
    return builder.as_markup()

def get_admin_main_menu_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    """Admin main menu with additional options"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="🔧 Admin Panel", 
        callback_data="admin_panel"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'post_listing'), 
        callback_data="main_post_listing"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'my_postings'), 
        callback_data="main_my_postings"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'search'), 
        callback_data="main_search"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'favorites'), 
        callback_data="main_favorites"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'info'), 
        callback_data="main_info"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'language'), 
        callback_data="main_language"
    ))
    
    builder.adjust(1, 2, 2, 2, 1)
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
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'), 
        callback_data="back_to_main"
    ))
    builder.adjust(1, 1, 1)
    return builder.as_markup()

def get_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")
    )
    builder.row(
        InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en")
    )
    return builder.as_markup()
def get_makler_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="🏢 Ha, makler sifatida", 
        callback_data="makler_yes"
    ))
    builder.add(InlineKeyboardButton(
        text="👤 Yo'q, shaxsiy e'lon", 
        callback_data="makler_no"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_property_type_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'apartment'), callback_data="type_apartment"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'house'), callback_data="type_house"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'commercial'), callback_data="type_commercial"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'land'), callback_data="type_land"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_main"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_status_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'sale'), callback_data="status_sale"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'rent'), callback_data="status_rent"))
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="edit_property_type"))
    builder.adjust(2, 1)
    return builder.as_markup()

def get_regions_keyboard(user_lang: str, callback_prefix: str = "region") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    regions = regions_config.get(user_lang, regions_config['uz'])
    
    for region_key, region_name in regions:
        builder.add(InlineKeyboardButton(
            text=region_name,
            callback_data=f"{callback_prefix}_{region_key}"
        ))
    
    builder.add(InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="edit_makler"))
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()

def get_districts_keyboard(region_key: str, user_lang: str, callback_prefix: str = "district") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    try:
        districts = REGIONS_DATA[user_lang][region_key]['districts']
        
        for district_key, district_name in districts.items():
            builder.add(InlineKeyboardButton(
                text=district_name,
                callback_data=f"{callback_prefix}_{district_key}"
            ))
        
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'back'),
            callback_data="edit_location"
        ))
        
        builder.adjust(2, 2, 2, 2, 2, 2, 1)
        return builder.as_markup()
        
    except KeyError:
        return InlineKeyboardMarkup(inline_keyboard=[])

def get_edit_keyboard(user_lang: str) -> InlineKeyboardMarkup:
    """Keyboard for editing listing fields"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_property_type'), 
        callback_data="edit_property_type"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_status'), 
        callback_data="edit_status"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_makler'), 
        callback_data="edit_makler"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_location'), 
        callback_data="edit_location"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_price'), 
        callback_data="edit_price"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_area'), 
        callback_data="edit_area"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_description'), 
        callback_data="edit_description"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_contact'), 
        callback_data="edit_contact"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_photos'), 
        callback_data="edit_photos"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'), 
        callback_data="back_to_confirmation"
    ))
    
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()

def get_pagination_keyboard(current_page: int, total_pages: int, callback_prefix: str, user_lang: str, **extra_data) -> InlineKeyboardMarkup:
    """Generate pagination keyboard"""
    builder = InlineKeyboardBuilder()
    
    # Navigation buttons
    if current_page > 1:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'prev_page'),
            callback_data=f"{callback_prefix}_page_{current_page - 1}"
        ))
    
    # Page info
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'page_info', current=current_page, total=total_pages),
        callback_data="page_info"
    ))
    
    if current_page < total_pages:
        builder.add(InlineKeyboardButton(
            text=get_text(user_lang, 'next_page'),
            callback_data=f"{callback_prefix}_page_{current_page + 1}"
        ))
    
    # Back to main menu
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'back'),
        callback_data="back_to_main"
    ))
    
    builder.adjust(3, 1)
    return builder.as_markup()

def get_listing_keyboard(listing_id: int, user_lang: str, show_edit: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for individual listing"""
    builder = InlineKeyboardBuilder()
    
    builder.add(InlineKeyboardButton(
        text="❤️ Sevimlilar", 
        callback_data=f"fav_add_{listing_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="📞 Aloqa", 
        callback_data=f"contact_{listing_id}"
    ))
    
    if show_edit:
        builder.add(InlineKeyboardButton(
            text="⚙️ Boshqarish", 
            callback_data=f"manage_{listing_id}"
        ))
    
    builder.adjust(2)
    return builder.as_markup()

def get_posting_management_keyboard(listing_id: int, is_active: bool, user_lang: str) -> InlineKeyboardMarkup:
    """Management keyboard for user's own postings"""
    builder = InlineKeyboardBuilder()
    
    if is_active:
        builder.add(InlineKeyboardButton(
            text="🔴 Nofaollashtirish", 
            callback_data=f"deactivate_post_{listing_id}"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text="🟢 Faollashtirish", 
            callback_data=f"activate_post_{listing_id}"
        ))
    
    builder.add(InlineKeyboardButton(
        text="🗑 O'chirish", 
        callback_data=f"delete_post_{listing_id}"
    ))
    
    builder.adjust(1, 1)
    return builder.as_markup()

def get_admin_approval_keyboard(listing_id: int, user_lang: str) -> InlineKeyboardMarkup:
    """Admin approval keyboard"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'admin_approve'), 
        callback_data=f"admin_approve_{listing_id}"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'admin_reject'), 
        callback_data=f"admin_reject_{listing_id}"
    ))
    builder.adjust(2)
    return builder.as_markup()

def format_listing_for_channel_with_makler(listing) -> str:
    """Format listing for channel with makler hashtag"""
    user_description = listing['description']
    contact_info = listing['contact_info']
    
    channel_text = f"""{user_description}

📞 Aloqa: {contact_info}

🗺 Manzil: {listing['full_address']}"""
    
    property_type = listing['property_type']
    status = listing['status']
    
    # Get makler status from admin_notes field
    is_makler = listing.get('admin_notes') == 'makler'
    makler_tag = '#makler' if is_makler else '#maklersiz'
    
    channel_text += f"\n\n#{property_type} #{status} {makler_tag}"
    
    return channel_text

def format_listing_raw_display(listing, user_lang):
    """Format listing for display in bot"""
    user_description = listing['description']
    location_display = listing['full_address'] if listing['full_address'] else listing['address']
    contact_info = listing['contact_info']
    
    listing_text = f"""{user_description}

📞 Aloqa: {contact_info}"""
    
    if location_display and location_display.strip():
        listing_text += f"\n🗺 Manzil: {location_display}"
    
    return listing_text

def format_my_posting_display(listing, user_lang):
    """Format posting for owner view"""
    location_display = listing['full_address'] if listing['full_address'] else listing['address']
    
    # Status determination based on approval_status
    status_map = {
        'pending': '🟡 Kutilmoqda',
        'approved': '🟢 Faol',
        'rejected': '🔴 Rad etilgan'
    }
    status_text = status_map.get(listing.get('approval_status', 'pending'), '❓ Noma\'lum')
    
    favorite_count = listing.get('favorite_count', 0)
    
    listing_text = f"""🆔 <b>E'lon #{listing['id']}</b>
📊 <b>Status:</b> {status_text}

🏠 <b>{listing['title'] or listing['description'][:50]}...</b>
🗺 <b>Manzil:</b> {location_display}
💰 <b>Narx:</b> {listing['price']:,} so'm
📐 <b>Maydon:</b> {listing['area']} m²

📝 <b>Tavsif:</b> {listing['description'][:100]}{'...' if len(listing['description']) > 100 else ''}
❤️ <b>Sevimlilar:</b> {favorite_count} ta
"""
    return listing_text

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
        return True
        
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")
        return False

async def send_to_admin_channel(listing):
    """Send listing to admin channel for approval"""
    try:
        admin_text = f"""🆕 <b>YANGI E'LON TEKSHIRISH UCHUN</b>

{format_listing_for_channel_with_makler(listing)}

👤 Foydalanuvchi: {listing.get('first_name', 'Noma\'lum')} (@{listing.get('username', 'username_yoq')})
🆔 E'lon ID: #{listing['id']}"""
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        keyboard = get_admin_approval_keyboard(listing['id'], 'uz')
        
        if photo_file_ids:
            if len(photo_file_ids) == 1:
                await bot.send_photo(
                    chat_id=ADMIN_CHANNEL_ID,
                    photo=photo_file_ids[0],
                    caption=admin_text,
                    reply_markup=keyboard
                )
            else:
                media_group = MediaGroupBuilder(caption=admin_text)
                for photo_id in photo_file_ids[:10]:
                    media_group.add_photo(media=photo_id)
                
                await bot.send_media_group(chat_id=ADMIN_CHANNEL_ID, media=media_group.build())
                await bot.send_message(
                    chat_id=ADMIN_CHANNEL_ID,
                    text="👆 E'lonni tasdiqlang:",
                    reply_markup=keyboard
                )
        else:
            await bot.send_message(
                chat_id=ADMIN_CHANNEL_ID,
                text=admin_text,
                reply_markup=keyboard
            )
        
        logger.info(f"Sent listing {listing['id']} to admin channel for approval")
        return True
        
    except Exception as e:
        logger.error(f"Error sending to admin channel: {e}")
        return False

async def display_search_results_paginated(callback_query, listings, total_count, current_page, total_pages, user_lang, search_data=None):
    """Display search results with pagination"""
    
    if not listings:
        text = get_text(user_lang, 'no_search_results')
        await callback_query.message.edit_text(text)
        return
    
    # Show search summary
    summary_text = f"""🔍 <b>Qidiruv natijalari</b>

{get_text(user_lang, 'total_results', total=total_count)}
{get_text(user_lang, 'page_info', current=current_page, total=total_pages)}

<i>E'lonlar:</i>"""
    
    await callback_query.message.edit_text(summary_text)
    
    # Display each listing
    for i, listing in enumerate(listings):
        listing_text = format_listing_raw_display(listing, user_lang)
        keyboard = get_listing_keyboard(listing['id'], user_lang)
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        
        try:
            if photo_file_ids:
                if len(photo_file_ids) == 1:
                    await callback_query.message.answer_photo(
                        photo=photo_file_ids[0],
                        caption=listing_text,
                        reply_markup=keyboard
                    )
                else:
                    media_group = MediaGroupBuilder(caption=listing_text)
                    for photo_id in photo_file_ids[:5]:
                        media_group.add_photo(media=photo_id)
                    
                    await callback_query.message.answer_media_group(media=media_group.build())
                    await callback_query.message.answer("👆 E'lon", reply_markup=keyboard)
            else:
                await callback_query.message.answer(listing_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error displaying listing {listing['id']}: {e}")
    
    # Send pagination controls
    if total_pages > 1:
        pagination_keyboard = get_pagination_keyboard(
            current_page, total_pages, "search_results", user_lang
        )
        await callback_query.message.answer(
            "📄 Sahifalar:",
            reply_markup=pagination_keyboard
        )

async def display_my_postings_paginated(callback_query, postings, total_count, current_page, total_pages, user_lang):
    """Display user's postings with pagination"""
    
    if not postings:
        text = get_text(user_lang, 'no_my_postings')
        await callback_query.message.edit_text(text, reply_markup=get_main_menu_keyboard(user_lang))
        return
    
    # Show summary
    summary_text = f"""📝 <b>Mening e'lonlarim</b>

{get_text(user_lang, 'total_results', total=total_count)}
{get_text(user_lang, 'page_info', current=current_page, total=total_pages)}"""
    
    await callback_query.message.edit_text(summary_text)
    
    # Display each posting
    for posting in postings:
        posting_text = format_my_posting_display(posting, user_lang)
        is_active = posting.get('approval_status') == 'approved'
        keyboard = get_posting_management_keyboard(posting['id'], is_active, user_lang)
        
        photo_file_ids = json.loads(posting['photo_file_ids']) if posting['photo_file_ids'] else []
        
        try:
            if photo_file_ids:
                await callback_query.message.answer_photo(
                    photo=photo_file_ids[0],
                    caption=posting_text,
                    reply_markup=keyboard
                )
            else:
                await callback_query.message.answer(posting_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error displaying posting {posting['id']}: {e}")
    
    # Send pagination controls
    if total_pages > 1:
        pagination_keyboard = get_pagination_keyboard(
            current_page, total_pages, "my_postings", user_lang
        )
        await callback_query.message.answer(
            "📄 Sahifalar:",
            reply_markup=pagination_keyboard
        )

# MAIN HANDLERS
@dp.message(CommandStart())
async def start_handler(message: Message):
    user = message.from_user
    await save_user(user.id, user.username, user.first_name, user.last_name)
    user_lang = await get_user_language(user.id)
    
    # Check if user is admin
    if is_admin(user.id):
        keyboard = get_admin_main_menu_keyboard(user_lang)
    else:
        keyboard = get_main_menu_keyboard(user_lang)
    
    await message.answer(
        get_text(user_lang, 'start'),
        reply_markup=keyboard
    )

# MAIN MENU CALLBACKS
@dp.callback_query(F.data == 'back_to_main')
async def back_to_main(callback_query, state: FSMContext):
    await state.clear()
    user_lang = await get_user_language(callback_query.from_user.id)
    
    if is_admin(callback_query.from_user.id):
        keyboard = get_admin_main_menu_keyboard(user_lang)
    else:
        keyboard = get_main_menu_keyboard(user_lang)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'main_menu'),
        reply_markup=keyboard
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'main_language')
async def language_callback_handler(callback_query):
    user_lang = await get_user_language(callback_query.from_user.id)
    await callback_query.message.edit_text(
        get_text(user_lang, 'choose_language'),
        reply_markup=get_language_keyboard()
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('lang_'))
async def language_selection_callback(callback_query):
    lang = callback_query.data.split('_')[1]
    await update_user_language(callback_query.from_user.id, lang)
    
    await callback_query.answer(f"✅ Til o'zgartirildi!")
    
    if is_admin(callback_query.from_user.id):
        keyboard = get_admin_main_menu_keyboard(lang)
    else:
        keyboard = get_main_menu_keyboard(lang)
    
    await callback_query.message.edit_text(
        get_text(lang, 'main_menu'),
        reply_markup=keyboard
    )

@dp.callback_query(F.data == 'main_info')
async def info_callback(callback_query):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=get_text(user_lang, 'back'), callback_data="back_to_main")
    ]])
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'about'),
        reply_markup=back_keyboard
    )
    await callback_query.answer()

# POSTING HANDLERS
@dp.callback_query(F.data == 'main_post_listing')
async def post_listing_callback(callback_query, state: FSMContext):
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
        "👨‍💼 Siz makler (dallol) sifatida e'lon joylashtirmoqchimisiz?\n\n🏢 Makler - professional ko'chmas mulk sotuv xizmati\n👤 Maklersiz - shaxsiy e'lon",
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
    await callback_query.answer("✅ Makler sifatida tanlandi")

@dp.callback_query(F.data == 'makler_no')
async def process_makler_no(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.update_data(is_makler=False)
    
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer("✅ Shaxsiy e'lon sifatida tanlandi")

@dp.callback_query(F.data.startswith('region_'), ListingStates.region)
async def process_region_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    region_key = callback_query.data[7:]
    
    if region_key not in REGIONS_DATA.get(user_lang, {}):
        await callback_query.answer("❌ Viloyat topilmadi!")
        return
    
    await state.update_data(region=region_key)
    await state.set_state(ListingStates.district)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_district'),
        reply_markup=get_districts_keyboard(region_key, user_lang)
    )
    await callback_query.answer("✅ Viloyat tanlandi")

@dp.callback_query(F.data.startswith('district_'))
async def process_district_selection(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    district_key = callback_query.data[9:]
    
    await state.update_data(district=district_key)
    await state.set_state(ListingStates.price)
    
    await callback_query.message.edit_text("💰 E'lon narxini kiriting:\n\nMasalan: 50000, 50000$, 500 ming, 1.2 mln")
    await callback_query.answer("✅ Tuman tanlandi")

@dp.message(ListingStates.price)
async def process_price(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    try:
        price_text = message.text.strip()
        price_clean = ''.join(filter(str.isdigit, price_text))
        
        if not price_clean:
            await message.answer("❌ Narx noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 50000, 75000")
            return
        
        price = int(price_clean)
        await state.update_data(price=price, price_text=price_text)
        
        await state.set_state(ListingStates.area)
        await message.answer("📐 Maydonni kiriting (m²):\n\nMasalan: 65, 65.5, 100")
        
    except ValueError:
        await message.answer("❌ Narx noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 50000, 75000")

@dp.message(ListingStates.area)
async def process_area(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    
    try:
        area_text = message.text.strip()
        area_clean = ''.join(c for c in area_text if c.isdigit() or c == '.')
        
        if not area_clean:
            await message.answer("❌ Maydon noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 65, 100.5")
            return
        
        area = float(area_clean)
        await state.update_data(area=area, area_text=area_text)
        
        # Show personalized template
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
        await message.answer("✨ Sizning ma'lumotlaringiz bilan tayyor namuna!\n\nQuyidagi namuna asosida e'loningizni yozing:")
        
    except ValueError:
        await message.answer("❌ Maydon noto'g'ri kiritildi. Iltimos, faqat raqam kiriting.\n\nMasalan: 65, 100.5")

@dp.message(ListingStates.description)
async def process_description(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    await state.update_data(description=message.text)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Ha, tayyor", 
        callback_data="desc_complete"
    ))
    builder.add(InlineKeyboardButton(
        text="➕ Qo'shimcha ma'lumot", 
        callback_data="desc_add_more"
    ))
    builder.adjust(1, 1)
    
    await state.set_state(ListingStates.confirmation)
    await message.answer(
        "E'lon tavsifi tayyor?",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'desc_complete')
async def description_complete(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.contact_info)
    await callback_query.message.edit_text("📞 Telefon raqamingizni kiriting:\n(Masalan: +998901234567)")
    await callback_query.answer()

@dp.callback_query(F.data == 'desc_add_more')
async def description_add_more(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.description)
    await callback_query.message.edit_text("📝 Qo'shimcha ma'lumot kiriting:")
    await callback_query.answer()

@dp.message(ListingStates.contact_info)
async def process_contact_info(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    await state.update_data(contact_info=message.text)
    
    await state.set_state(ListingStates.photos)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Rasmlar tayyor", callback_data="photos_done"))
    builder.add(InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="photos_skip"))
    builder.adjust(2)
    
    await message.answer(
        "📸 Rasmlarni yuklang:\n\n💡 Bir nechta rasmni birga yuborish uchun, ularni media guruh sifatida yuboring (bir vaqtda bir nechta rasmni tanlang)\n\nYoki bitta-bitta yuborishingiz ham mumkin.",
        reply_markup=builder.as_markup()
    )

@dp.message(ListingStates.photos, F.photo)
async def process_photo_with_collector(message: Message, state: FSMContext):
    """Handle both single photos and media groups using collector"""
    await media_collector.add_message(message, state)

@dp.callback_query(F.data.in_(['photos_done', 'photos_skip']))
async def show_final_preview(callback_query, state: FSMContext):
    """Show final preview and confirmation"""
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
    
    # Ensure required fields
    description = data.get('description', 'No description provided')
    if not data.get('title'):
        title = description.split('\n')[0][:50]
        if len(description) > 50:
            title += '...'
        data['title'] = title
    
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
    
    # Create a mock listing object for preview
    mock_listing = {
        'id': 'PREVIEW',
        'description': data.get('description', ''),
        'contact_info': data.get('contact_info', ''),
        'full_address': data.get('full_address', ''),
        'property_type': data.get('property_type', ''),
        'status': data.get('status', ''),
        'admin_notes': 'makler' if data.get('is_makler') else 'maklersiz',
        'photo_file_ids': json.dumps(data.get('photo_file_ids', []))
    }
    
    # Format for channel preview
    channel_preview = format_listing_for_channel_with_makler(mock_listing)
    
    # Show preview
    preview_text = f"""{get_text(user_lang, 'listing_preview_title')}

{channel_preview}"""
    
    # Send preview with photos if available
    photo_file_ids = data.get('photo_file_ids', [])
    
    if photo_file_ids:
        if len(photo_file_ids) == 1:
            await callback_query.message.answer_photo(
                photo=photo_file_ids[0],
                caption=preview_text
            )
        else:
            media_group = MediaGroupBuilder(caption=preview_text)
            for photo_id in photo_file_ids[:10]:
                media_group.add_photo(media=photo_id)
            
            await callback_query.message.answer_media_group(media=media_group.build())
    else:
        await callback_query.message.answer(preview_text)
    
    # Confirmation buttons
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'yes_confirm_post'), 
        callback_data="final_confirm"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'edit_listing'), 
        callback_data="edit_listing"
    ))
    builder.add(InlineKeyboardButton(
        text=get_text(user_lang, 'cancel_posting'), 
        callback_data="back_to_main"
    ))
    builder.adjust(1, 1, 1)
    
    await state.set_state(ListingStates.final_confirmation)
    await callback_query.message.answer(
        get_text(user_lang, 'confirm_posting'),
        reply_markup=builder.as_markup()
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'final_confirm')
async def final_confirm_posting(callback_query, state: FSMContext):
    """Final confirmation and submission"""
    user_lang = await get_user_language(callback_query.from_user.id)
    data = await state.get_data()
    
    try:
        # Save listing as PENDING
        listing_id = await save_listing_with_makler(callback_query.from_user.id, data)
        
        # Get the saved listing
        listing = await get_listing_by_id(listing_id)
        if listing:
            # Send to admin channel for approval
            await send_to_admin_channel(listing)
            
            # Notify user about submission
            await callback_query.message.edit_text(
                f"✅ E'loningiz muvaffaqiyatli yuborildi!\n\n👨‍💼 Admin ko'rib chiqishidan so'ng kanalda e'lon qilinadi.\n\n⏱ Odatda bu 24 soat ichida amalga oshiriladi.\n\n📊 E'lon ID: #{listing_id}"
            )
            
            # Notify admins
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🔔 Yangi e'lon tasdiqlanishi kutilmoqda!\n\nE'lon ID: #{listing_id}\nAdmin kanalini tekshiring."
                    )
                except Exception as e:
                    logger.error(f"Could not notify admin {admin_id}: {e}")
        
        await state.clear()
        await callback_query.answer("✅ E'lon yuborildi!")
        
    except Exception as e:
        logger.error(f"Error in final_confirm_posting: {e}")
        
        await callback_query.message.edit_text("❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")
        await callback_query.answer("❌ Xatolik", show_alert=True)
        await state.clear()

@dp.callback_query(F.data == 'edit_listing')
async def edit_listing_menu(callback_query, state: FSMContext):
    """Show edit options with proper state management"""
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Ensure we're in the right state
    current_state = await state.get_state()
    if current_state != ListingStates.final_confirmation.state:
        await state.set_state(ListingStates.final_confirmation)
    
    await callback_query.message.edit_text(
        get_text(user_lang, 'edit_what'),
        reply_markup=get_edit_keyboard(user_lang)
    )
    await callback_query.answer()
# EDIT HANDLERS
@dp.callback_query(F.data == 'edit_property_type')
async def edit_property_type(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.property_type)
    await callback_query.message.edit_text(
        get_text(user_lang, 'property_type'),
        reply_markup=get_property_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_status')
async def edit_status(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.status)
    await callback_query.message.edit_text(
        get_text(user_lang, 'status'),
        reply_markup=get_status_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_makler')
async def edit_makler(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.makler_type)
    await callback_query.message.edit_text(
        "👨‍💼 Makler holatini tanlang:",
        reply_markup=get_makler_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_location')
async def edit_location(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.region)
    await callback_query.message.edit_text(
        get_text(user_lang, 'select_region'),
        reply_markup=get_regions_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_price')
async def edit_price(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.price)
    await callback_query.message.edit_text("💰 Yangi narxni kiriting:")
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_area')
async def edit_area(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.area)
    await callback_query.message.edit_text("📐 Yangi maydonni kiriting (m²):")
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_description')
async def edit_description(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.description)
    await callback_query.message.edit_text("📝 Yangi tavsif kiriting:")
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_contact')
async def edit_contact(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(ListingStates.contact_info)
    await callback_query.message.edit_text("📞 Yangi telefon raqamini kiriting:")
    await callback_query.answer()

@dp.callback_query(F.data == 'edit_photos')
async def edit_photos(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Clear existing photos
    await state.update_data(photo_file_ids=[])
    await state.set_state(ListingStates.photos)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Rasmlar tayyor", callback_data="photos_done"))
    builder.add(InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="photos_skip"))
    builder.adjust(2)
    
    await callback_query.message.edit_text(
        "📸 Yangi rasmlarni yuklang:",
        reply_markup=builder.as_markup()
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'back_to_confirmation')
async def back_to_confirmation(callback_query, state: FSMContext):
    """Go back to final confirmation"""
    await show_final_preview(callback_query, state)

# MY POSTINGS HANDLERS
@dp.callback_query(F.data == 'main_my_postings')
async def my_postings_callback(callback_query, state: FSMContext):
    await show_my_postings_page(callback_query, 1)

@dp.callback_query(F.data.startswith('my_postings_page_'))
async def my_postings_page_callback(callback_query, state: FSMContext):
    page = int(callback_query.data.split('_')[-1])
    await show_my_postings_page(callback_query, page)

async def show_my_postings_page(callback_query, page: int):
    """Show user's postings with pagination"""
    user_lang = await get_user_language(callback_query.from_user.id)
    user_id = callback_query.from_user.id
    
    # Calculate offset
    offset = (page - 1) * POSTINGS_PER_PAGE
    
    # Get postings and total count
    postings = await get_user_postings(user_id, POSTINGS_PER_PAGE, offset)
    total_count = await get_user_postings_count(user_id)
    total_pages = (total_count + POSTINGS_PER_PAGE - 1) // POSTINGS_PER_PAGE
    
    await display_my_postings_paginated(callback_query, postings, total_count, page, total_pages, user_lang)
    await callback_query.answer()

# SEARCH HANDLERS
@dp.callback_query(F.data == 'main_search')
async def search_callback(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    
    await state.set_state(SearchStates.search_type)
    await callback_query.message.edit_text(
        "🔍 Qidiruv turini tanlang:",
        reply_markup=get_search_type_keyboard(user_lang)
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'search_keyword')
async def search_keyword_selected(callback_query, state: FSMContext):
    user_lang = await get_user_language(callback_query.from_user.id)
    await state.set_state(SearchStates.keyword_query)
    await callback_query.message.edit_text("🔍 Qidirish uchun kalit so'z kiriting:")
    await callback_query.answer()

@dp.message(SearchStates.keyword_query)
async def process_keyword_search(message: Message, state: FSMContext):
    user_lang = await get_user_language(message.from_user.id)
    query = message.text.strip()
    
    await search_and_display_results(message, query, 1, user_lang, search_type='keyword')
    await state.clear()

async def search_and_display_results(message_or_callback, query, page, user_lang, search_type='keyword', **search_params):
    """Search and display results with pagination"""
    offset = (page - 1) * SEARCH_RESULTS_PER_PAGE
    
    if search_type == 'keyword':
        listings = await search_listings(query, SEARCH_RESULTS_PER_PAGE, offset)
        total_count = await get_search_results_count(query=query)
    else:
        # Location-based search
        listings = await search_listings_by_location(
            region_key=search_params.get('region_key'),
            district_key=search_params.get('district_key'),
            property_type=search_params.get('property_type'),
            status=search_params.get('status'),
            limit=SEARCH_RESULTS_PER_PAGE,
            offset=offset
        )
        total_count = await get_search_results_count(
            region_key=search_params.get('region_key'),
            district_key=search_params.get('district_key'),
            property_type=search_params.get('property_type'),
            status=search_params.get('status')
        )
    
    total_pages = (total_count + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE
    
    if hasattr(message_or_callback, 'message'):
        # It's a callback query
        await display_search_results_paginated(message_or_callback, listings, total_count, page, total_pages, user_lang)
    else:
        # It's a message - create a dummy callback for display function
        class DummyCallback:
            def __init__(self, message):
                self.message = message
        
        dummy_callback = DummyCallback(message_or_callback)
        await display_search_results_paginated(dummy_callback, listings, total_count, page, total_pages, user_lang)

# FAVORITES HANDLERS  
@dp.callback_query(F.data == 'main_favorites')
async def favorites_callback(callback_query, state: FSMContext):
    await show_favorites_page(callback_query, 1)

@dp.callback_query(F.data.startswith('favorites_page_'))
async def favorites_page_callback(callback_query, state: FSMContext):
    page = int(callback_query.data.split('_')[-1])
    await show_favorites_page(callback_query, page)

async def show_favorites_page(callback_query, page: int):
    """Show user's favorites with pagination"""
    user_lang = await get_user_language(callback_query.from_user.id)
    user_id = callback_query.from_user.id
    
    # Calculate offset
    offset = (page - 1) * SEARCH_RESULTS_PER_PAGE
    
    # Get favorites and total count
    favorites = await get_user_favorites(user_id, SEARCH_RESULTS_PER_PAGE, offset)
    total_count = await get_user_favorites_count(user_id)
    total_pages = (total_count + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE
    
    if not favorites:
        await callback_query.message.edit_text(
            "😔 Sevimlilar ro'yxati bo'sh",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_main")
            ]])
        )
        await callback_query.answer()
        return
    
    # Show summary
    summary_text = f"""❤️ <b>Sevimlilar</b>

Jami: {total_count} ta
📄 Sahifa {page} / {total_pages}"""
    
    await callback_query.message.edit_text(summary_text)
    
    # Display each favorite
    for favorite in favorites:
        listing_text = format_listing_raw_display(favorite, user_lang)
        keyboard = get_listing_keyboard(favorite['id'], user_lang)
        
        photo_file_ids = json.loads(favorite['photo_file_ids']) if favorite['photo_file_ids'] else []
        
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
            logger.error(f"Error displaying favorite {favorite['id']}: {e}")
    
    # Send pagination controls
    if total_pages > 1:
        pagination_keyboard = get_pagination_keyboard(
            page, total_pages, "favorites", user_lang
        )
        await callback_query.message.answer(
            "📄 Sahifalar:",
            reply_markup=pagination_keyboard
        )
    
    await callback_query.answer()

@dp.callback_query(F.data.startswith('fav_add_'))
async def add_favorite_callback(callback_query):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Check if listing is still active
    listing = await get_listing_by_id(listing_id)
    if not listing or not listing['is_approved']:
        await callback_query.answer("⚠️ Bu e'lon endi mavjud emas!", show_alert=True)
        return
    
    await add_to_favorites(callback_query.from_user.id, listing_id)
    await callback_query.answer("❤️ Sevimlilar ro'yxatiga qo'shildi!")

@dp.callback_query(F.data.startswith('contact_'))
async def contact_callback(callback_query):
    listing_id = int(callback_query.data.split('_')[1])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    listing = await get_listing_by_id(listing_id)
    
    if listing:
        await callback_query.answer(f"📞 Aloqa: {listing['contact_info']}", show_alert=True)
    else:
        await callback_query.answer("❌ E'lon topilmadi")

# POSTING MANAGEMENT HANDLERS
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
    await callback_query.answer("✅ E'lon faollashtirildi!")

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
    await callback_query.answer("🔴 E'lon nofaollashtirildi!")

@dp.callback_query(F.data.startswith('delete_post_'))
async def confirm_delete_posting(callback_query):
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
        text="✅ Ha, o'chirish", 
        callback_data=f"confirm_delete_{listing_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Bekor qilish", 
        callback_data=f"cancel_delete_{listing_id}"
    ))
    builder.adjust(2)
    
    confirmation_text = "❓ Rostdan ham bu e'lonni o'chirmoqchimisiz?"
    
    try:
        await callback_query.message.edit_text(
            confirmation_text,
            reply_markup=builder.as_markup()
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Could not edit message for delete confirmation: {e}")
        await callback_query.message.answer(
            confirmation_text,
            reply_markup=builder.as_markup()
        )
        await callback_query.answer()

@dp.callback_query(F.data.startswith('confirm_delete_'))
async def delete_posting_confirmed(callback_query):
    user_id = callback_query.from_user.id
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(user_id)
    
    try:
        # Verify listing exists and ownership
        listing = await get_listing_by_id(listing_id)
        if not listing:
            await callback_query.answer("⛔ E'lon topilmadi!", show_alert=True)
            return

        async with db_pool.acquire() as conn:
            user_db_id = await conn.fetchval(
                'SELECT id FROM real_estate_telegramuser WHERE telegram_id = $1',
                user_id
            )
        
        if listing['user_id'] != user_db_id and not is_admin(user_id):
            await callback_query.answer("⛔ Ruxsat yo'q!", show_alert=True)
            return

        # Delete from database
        deletion_result = await delete_listing_completely(listing_id)
        
        # Notify users who had this favorited
        for fav_user_id in deletion_result['user_ids']:
            try:
                await bot.send_message(
                    chat_id=fav_user_id, 
                    text=f"💔 Sevimlilaringizdan 1 e'lon o'chirildi"
                )
            except Exception as e:
                logger.warning(f"Couldn't notify user {fav_user_id}: {e}")

        await callback_query.message.edit_text("✅ E'lon muvaffaqiyatli o'chirildi!")
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Critical error deleting listing {listing_id}: {e}")
        await callback_query.message.edit_text("❌ E'lonni o'chirishda xatolik yuz berdi.")
        await callback_query.answer("❌ Xatolik", show_alert=True)

@dp.callback_query(F.data.startswith('cancel_delete_'))
async def cancel_delete_posting(callback_query):
    listing_id = int(callback_query.data.split('_')[2])
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Get the listing data to restore the original view
    listing = await get_listing_by_id(listing_id)
    if not listing:
        await callback_query.message.edit_text("❌ Bu e'lon topilmadi yoki o'chirilgan.")
        await callback_query.answer()
        return
    
    # Format the original posting text and keyboard
    posting_text = format_my_posting_display(listing, user_lang)
    is_active = listing.get('approval_status') == 'approved'
    keyboard = get_posting_management_keyboard(listing_id, is_active, user_lang)
    
    await callback_query.message.edit_text(
        posting_text, 
        reply_markup=keyboard
    )
    await callback_query.answer("❌ Amal bekor qilindi")

# ADMIN HANDLERS
@dp.callback_query(F.data == 'admin_panel')
async def admin_panel_callback(callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Sizda admin huquqlari yo'q!")
        return
    
    user_lang = await get_user_language(callback_query.from_user.id)
    
    # Get pending listings count
    pending_listings = await get_pending_listings()
    pending_count = len(pending_listings)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=f"📋 Kutilayotgan e'lonlar ({pending_count})", 
        callback_data="admin_pending_listings"
    ))
    builder.add(InlineKeyboardButton(
        text="📊 Statistika", 
        callback_data="admin_stats"
    ))
    builder.add(InlineKeyboardButton(
        text="◀️ Orqaga", 
        callback_data="back_to_main"
    ))
    builder.adjust(1, 1, 1)
    
    panel_text = f"""🔧 <b>Admin Panel</b>

📋 Kutilayotgan e'lonlar: {pending_count} ta
📊 Tizim holati: Faol

Kerakli amalni tanlang:"""
    
    await callback_query.message.edit_text(
        panel_text,
        reply_markup=builder.as_markup()
    )
    await callback_query.answer()

@dp.callback_query(F.data == 'admin_pending_listings')
async def admin_pending_listings_callback(callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Sizda admin huquqlari yo'q!")
        return
    
    user_lang = await get_user_language(callback_query.from_user.id)
    pending_listings = await get_pending_listings()
    
    if not pending_listings:
        await callback_query.message.edit_text(
            get_text(user_lang, 'no_pending_listings'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")
            ]])
        )
        await callback_query.answer()
        return
    
    await callback_query.message.edit_text(
        f"📋 Kutilayotgan e'lonlar: {len(pending_listings)} ta\n\nE'lonlar quyida ko'rsatiladi:"
    )
    
    # Display each pending listing
    for listing in pending_listings:
        admin_text = f"""🆕 <b>TEKSHIRISH UCHUN E'LON</b>

{format_listing_for_channel_with_makler(listing)}

👤 Foydalanuvchi: {listing.get('first_name', 'Noma\'lum')} (@{listing.get('username', 'username_yoq')})
🆔 E'lon ID: #{listing['id']}
📅 Yuborilgan: {listing['created_at'].strftime('%d.%m.%Y %H:%M')}"""
        
        photo_file_ids = json.loads(listing['photo_file_ids']) if listing['photo_file_ids'] else []
        keyboard = get_admin_approval_keyboard(listing['id'], user_lang)
        
        try:
            if photo_file_ids:
                if len(photo_file_ids) == 1:
                    await callback_query.message.answer_photo(
                        photo=photo_file_ids[0],
                        caption=admin_text,
                        reply_markup=keyboard
                    )
                else:
                    media_group = MediaGroupBuilder(caption=admin_text)
                    for photo_id in photo_file_ids[:10]:
                        media_group.add_photo(media=photo_id)
                    
                    await callback_query.message.answer_media_group(media=media_group.build())
                    await callback_query.message.answer(
                        "👆 E'lonni tasdiqlang:",
                        reply_markup=keyboard
                    )
            else:
                await callback_query.message.answer(admin_text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error displaying pending listing {listing['id']}: {e}")
    
    await callback_query.answer()

@dp.callback_query(F.data.startswith('admin_approve_'))
async def admin_approve_listing(callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Sizda admin huquqlari yo'q!")
        return
    
    listing_id = int(callback_query.data.split('_')[2])
    admin_id = callback_query.from_user.id
    
    try:
        # Update listing as approved
        await update_listing_approval(listing_id, True, admin_id)
        
        # Get the listing
        listing = await get_listing_by_id(listing_id)
        if listing:
            # Post to main channel
            success = await post_to_channel_with_makler(listing)
            
            # Notify user (without notifying admins)
            try:
                await bot.send_message(
                    listing['user_telegram_id'],
                    get_text('uz', 'admin_approved_notification')
                )
            except Exception as e:
                logger.error(f"Could not notify user {listing['user_telegram_id']}: {e}")
            
            # Update admin message
            await callback_query.message.edit_text(
                f"✅ E'lon #{listing_id} tasdiqlandi va kanalga joylandi!"
            )
        
        await callback_query.answer("✅ E'lon tasdiqlandi!")
        
    except Exception as e:
        logger.error(f"Error approving listing {listing_id}: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@dp.callback_query(F.data.startswith('admin_reject_'))
async def admin_reject_listing(callback_query, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Sizda admin huquqlari yo'q!")
        return
    
    listing_id = int(callback_query.data.split('_')[2])
    
    await state.set_state(AdminStates.writing_feedback)
    await state.update_data(listing_id=listing_id)
    
    await callback_query.message.edit_text(
        f"❌ E'lon #{listing_id} rad etish sababi:\n\nFikr-mulohaza yozing:"
    )
    await callback_query.answer()

@dp.message(AdminStates.writing_feedback)
async def process_admin_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    listing_id = data.get('listing_id')
    feedback = message.text
    admin_id = message.from_user.id
    
    try:
        # Update listing as rejected
        await update_listing_approval(listing_id, False, admin_id, feedback)
        
        # Get the listing to notify user
        listing = await get_listing_by_id(listing_id)
        if listing:
            try:
                await bot.send_message(
                    listing['user_telegram_id'],
                    get_text('uz', 'admin_rejected_notification', reason=feedback)
                )
            except Exception as e:
                logger.error(f"Could not notify user {listing['user_telegram_id']}: {e}")
        
        await message.answer(
            f"❌ E'lon #{listing_id} rad etildi!\n\nSabab: {feedback}\n\nFoydalanuvchi xabardor qilindi."
        )
        
    except Exception as e:
        logger.error(f"Error rejecting listing {listing_id}: {e}")
        await message.answer("❌ Xatolik yuz berdi!")
    
    await state.clear()

# UTILITY FUNCTIONS
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

# ERROR HANDLER
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
    
    logger.info("🤖 Starting Enhanced Real Estate Bot...")
    
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
    
    await set_menu_button()
    
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