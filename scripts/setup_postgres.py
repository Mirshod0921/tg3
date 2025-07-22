#!/usr/bin/env python3
"""
Migration script to transfer data from SQLite to PostgreSQL
Run this after setting up PostgreSQL database
"""

import os
import sys
import sqlite3
import asyncio
import asyncpg
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configurations
SQLITE_DB_PATH = 'real_estate.db'  # Path to your SQLite database
POSTGRES_URL = os.getenv('DATABASE_URL') or f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', 'password')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'real_estate_db')}"

async def migrate_data():
    """Migrate data from SQLite to PostgreSQL"""
    
    # Check if SQLite database exists
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"❌ SQLite database not found at {SQLITE_DB_PATH}")
        print("Please make sure the SQLite database file exists in the correct location.")
        return
    
    print("🔄 Starting migration from SQLite to PostgreSQL...")
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    try:
        pg_conn = await asyncpg.connect(POSTGRES_URL)
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        print("Please check your PostgreSQL configuration and make sure the database is running.")
        return
    
    try:
        # First, create tables in PostgreSQL (using Django schema)
        await create_postgres_tables(pg_conn)
        
        # Migrate users
        await migrate_users(sqlite_cursor, pg_conn)
        
        # Migrate listings
        await migrate_listings(sqlite_cursor, pg_conn)
        
        # Migrate favorites
        await migrate_favorites(sqlite_cursor, pg_conn)
        
        print("✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        sqlite_conn.close()
        await pg_conn.close()

async def create_postgres_tables(pg_conn):
    """Create PostgreSQL tables based on Django models"""
    print("🔧 Creating PostgreSQL tables...")
    
    # Users table
    await pg_conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username VARCHAR(100),
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            language VARCHAR(2) DEFAULT 'uz',
            is_blocked BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Listings table
    await pg_conn.execute('''
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            title VARCHAR(200),
            description TEXT,
            property_type VARCHAR(20),
            region VARCHAR(50),
            district VARCHAR(50),
            address VARCHAR(300),
            full_address VARCHAR(500),
            price DECIMAL(12,2),
            area INTEGER,
            rooms INTEGER,
            status VARCHAR(10),
            condition VARCHAR(20),
            contact_info VARCHAR(200),
            photo_file_ids JSONB DEFAULT '[]',
            is_premium BOOLEAN DEFAULT FALSE,
            is_approved BOOLEAN DEFAULT TRUE,
            approval_status VARCHAR(20) DEFAULT 'pending',
            admin_feedback TEXT,
            reviewed_by BIGINT,
            channel_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Favorites table
    await pg_conn.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            listing_id INTEGER REFERENCES listings(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, listing_id)
        )
    ''')
    
    # Create indexes
    await pg_conn.execute('CREATE INDEX IF NOT EXISTS idx_listings_approval_status ON listings(approval_status)')
    await pg_conn.execute('CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id)')
    await pg_conn.execute('CREATE INDEX IF NOT EXISTS idx_listings_region_district ON listings(region, district)')
    await pg_conn.execute('CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at DESC)')
    await pg_conn.execute('CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id)')
    
    print("✅ PostgreSQL tables created")

async def migrate_users(sqlite_cursor, pg_conn):
    """Migrate users from SQLite to PostgreSQL"""
    print("👥 Migrating users...")
    
    # Get users from SQLite
    sqlite_cursor.execute("SELECT * FROM users")
    users = sqlite_cursor.fetchall()
    
    migrated_count = 0
    for user in users:
        try:
            await pg_conn.execute('''
                INSERT INTO users (telegram_id, username, first_name, last_name, language, is_blocked, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (telegram_id) DO NOTHING
            ''', 
            user['telegram_id'], 
            user['username'], 
            user['first_name'], 
            user['last_name'], 
            user.get('language', 'uz'),
            user.get('is_blocked', False),
            user.get('created_at', datetime.now())
            )
            migrated_count += 1
        except Exception as e:
            print(f"❌ Failed to migrate user {user['telegram_id']}: {e}")
    
    print(f"✅ Migrated {migrated_count} users")

async def migrate_listings(sqlite_cursor, pg_conn):
    """Migrate listings from SQLite to PostgreSQL"""
    print("📝 Migrating listings...")
    
    # Get listings from SQLite
    sqlite_cursor.execute("SELECT * FROM listings")
    listings = sqlite_cursor.fetchall()
    
    migrated_count = 0
    for listing in listings:
        try:
            # Handle photo_file_ids - convert from JSON string to JSONB
            photo_file_ids = listing.get('photo_file_ids', '[]')
            if isinstance(photo_file_ids, str):
                try:
                    photo_file_ids = json.loads(photo_file_ids)
                except:
                    photo_file_ids = []
            
            # Convert SQLite datetime to PostgreSQL timestamp
            created_at = listing.get('created_at', datetime.now())
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    created_at = datetime.now()
            
            await pg_conn.execute('''
                INSERT INTO listings (
                    user_id, title, description, property_type, region, district,
                    address, full_address, price, area, rooms, status, condition,
                    contact_info, photo_file_ids, is_premium, is_approved,
                    approval_status, admin_feedback, reviewed_by, channel_message_id,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22)
            ''',
            listing['user_id'],
            listing.get('title', ''),
            listing.get('description', ''),
            listing.get('property_type', ''),
            listing.get('region'),
            listing.get('district'),
            listing.get('address', ''),
            listing.get('full_address', ''),
            float(listing.get('price', 0)),
            int(listing.get('area', 0)),
            int(listing.get('rooms', 0)),
            listing.get('status', ''),
            listing.get('condition', ''),
            listing.get('contact_info', ''),
            json.dumps(photo_file_ids),  # Convert to JSON string for JSONB
            listing.get('is_premium', False),
            listing.get('is_approved', True),
            listing.get('approval_status', 'approved'),
            listing.get('admin_feedback'),
            listing.get('reviewed_by'),
            listing.get('channel_message_id'),
            created_at
            )
            migrated_count += 1
        except Exception as e:
            print(f"❌ Failed to migrate listing {listing.get('id', 'unknown')}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"✅ Migrated {migrated_count} listings")

async def migrate_favorites(sqlite_cursor, pg_conn):
    """Migrate favorites from SQLite to PostgreSQL"""
    print("❤️ Migrating favorites...")
    
    # Check if favorites table exists in SQLite
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favorites'")
    if not sqlite_cursor.fetchone():
        print("ℹ️ No favorites table found in SQLite, skipping...")
        return
    
    # Get favorites from SQLite
    sqlite_cursor.execute("SELECT * FROM favorites")
    favorites = sqlite_cursor.fetchall()
    
    migrated_count = 0
    for favorite in favorites:
        try:
            # Convert created_at
            created_at = favorite.get('created_at', datetime.now())
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    created_at = datetime.now()
            
            await pg_conn.execute('''
                INSERT INTO favorites (user_id, listing_id, created_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, listing_id) DO NOTHING
            ''',
            favorite['user_id'],
            favorite['listing_id'],
            created_at
            )
            migrated_count += 1
        except Exception as e:
            print(f"❌ Failed to migrate favorite: {e}")
    
    print(f"✅ Migrated {migrated_count} favorites")

async def verify_migration(pg_conn):
    """Verify that migration was successful"""
    print("🔍 Verifying migration...")
    
    users_count = await pg_conn.fetchval("SELECT COUNT(*) FROM users")
    listings_count = await pg_conn.fetchval("SELECT COUNT(*) FROM listings")
    favorites_count = await pg_conn.fetchval("SELECT COUNT(*) FROM favorites")
    
    print(f"📊 Migration results:")
    print(f"   Users: {users_count}")
    print(f"   Listings: {listings_count}")
    print(f"   Favorites: {favorites_count}")

if __name__ == "__main__":
    print("🚀 Real Estate Bot - SQLite to PostgreSQL Migration")
    print("=" * 50)
    
    # Check if PostgreSQL configuration is available
    if not os.getenv('DB_PASSWORD') and not os.getenv('DATABASE_URL'):
        print("❌ PostgreSQL configuration not found!")
        print("Please set up your .env file with database credentials.")
        sys.exit(1)
    
    # Run migration
    asyncio.run(migrate_data())