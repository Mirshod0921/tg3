#!/usr/bin/env python3
"""
Test database connection for Real Estate Bot
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_postgresql():
    """Test PostgreSQL connection"""
    try:
        import psycopg2
        
        print("🔍 Testing PostgreSQL connection...")
        
        conn_params = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'real_estate_db'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', '')
        }
        
        print(f"   Host: {conn_params['host']}")
        print(f"   Port: {conn_params['port']}")
        print(f"   Database: {conn_params['database']}")
        print(f"   User: {conn_params['user']}")
        print(f"   Password: {'*' * len(conn_params['password']) if conn_params['password'] else '(empty)'}")
        
        # Test connection
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()
        
        # Test query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"✅ PostgreSQL connection successful!")
        print(f"   Version: {version}")
        
        # Test if database exists and is accessible
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
        table_count = cursor.fetchone()[0]
        print(f"   Tables in database: {table_count}")
        
        cursor.close()
        conn.close()
        
        return True
        
    except ImportError:
        print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
        return False
        
    except psycopg2.OperationalError as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        
        if "no password supplied" in str(e):
            print("\n🔧 Solution:")
            print("1. Set PostgreSQL password:")
            print("   psql -U postgres")
            print("   ALTER USER postgres PASSWORD 'yourpassword';")
            print("2. Update .env file:")
            print("   DB_PASSWORD=yourpassword")
            
        elif "authentication failed" in str(e):
            print("\n🔧 Solution:")
            print("1. Check password in .env file")
            print("2. Reset PostgreSQL password if needed")
            
        elif "could not connect to server" in str(e):
            print("\n🔧 Solution:")
            print("1. Start PostgreSQL service:")
            print("   Windows: net start postgresql-x64-15")
            print("   Linux: sudo systemctl start postgresql")
            print("   macOS: brew services start postgresql")
            
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_sqlite_fallback():
    """Test SQLite fallback"""
    use_sqlite = os.getenv('USE_SQLITE', 'False').lower() == 'true'
    
    if use_sqlite:
        print("\n🔍 SQLite fallback is enabled")
        try:
            import sqlite3
            conn = sqlite3.connect(':memory:')
            conn.execute("SELECT 1")
            conn.close()
            print("✅ SQLite connection successful!")
            return True
        except Exception as e:
            print(f"❌ SQLite connection failed: {e}")
            return False
    else:
        print("\n⚠️  SQLite fallback is disabled")
        return False

def check_environment():
    """Check environment variables"""
    print("\n🔍 Checking environment variables...")
    
    required_vars = ['BOT_TOKEN', 'DB_NAME', 'DB_USER']
    optional_vars = ['DB_PASSWORD', 'DB_HOST', 'DB_PORT', 'ADMIN_IDS']
    
    missing_required = []
    missing_optional = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            if var == 'BOT_TOKEN':
                display_value = f"{value[:8]}..." if len(value) > 8 else value
            else:
                display_value = value
            print(f"   ✅ {var}: {display_value}")
        else:
            missing_required.append(var)
            print(f"   ❌ {var}: (missing)")
    
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            if var == 'DB_PASSWORD':
                display_value = '*' * len(value)
            else:
                display_value = value
            print(f"   ✅ {var}: {display_value}")
        else:
            missing_optional.append(var)
            print(f"   ⚠️  {var}: (not set)")
    
    if missing_required:
        print(f"\n❌ Missing required variables: {missing_required}")
        return False
    
    if missing_optional:
        print(f"\n⚠️  Missing optional variables: {missing_optional}")
    
    return True

def check_dependencies():
    """Check if required packages are installed"""
    print("\n🔍 Checking dependencies...")
    
    required_packages = [
        ('psycopg2', 'psycopg2-binary'),
        ('django', 'Django'),
        ('dotenv', 'python-dotenv'),
        ('asyncpg', 'asyncpg'),
        
    ]
    
    missing_packages = []
    
    for package, pip_name in required_packages:
        try:
            __import__(package)
            print(f"   ✅ {package}")
        except ImportError:
            missing_packages.append(pip_name)
            print(f"   ❌ {package}")
    
    if missing_packages:
        print(f"\n❌ Missing packages: {missing_packages}")
        print("Install with: pip install " + " ".join(missing_packages))
        return False
    
    return True

def main():
    """Main test function"""
    print("🏠 Real Estate Bot - Database Connection Test")
    print("=" * 50)
    
    # Check .env file
    if not os.path.exists('.env'):
        print("❌ .env file not found!")
        if os.path.exists('.env.example'):
            print("💡 Found .env.example - copy it to .env and configure")
        else:
            print("💡 Create .env file with database configuration")
        return False
    
    # Check dependencies
    if not check_dependencies():
        return False
    
    # Check environment variables
    if not check_environment():
        return False
    
    # Test database connections
    postgresql_success = test_postgresql()
    sqlite_success = test_sqlite_fallback()
    
    print("\n" + "=" * 50)
    
    if postgresql_success:
        print("🎉 PostgreSQL is ready!")
        print("✅ You can run Django migrations and start the bot")
        return True
    elif sqlite_success:
        print("⚠️  Using SQLite fallback")
        print("✅ You can run Django migrations and start the bot")
        return True
    else:
        print("❌ Database connection failed!")
        print("🔧 Please fix the database configuration before continuing")
        return False

if __name__ == "__main__":
    success = main()
    
    if success:
        print("\n🚀 Next steps:")
        print("1. cd backend")
        print("2. python manage.py migrate")
        print("3. python manage.py populate_regions")
        print("4. python manage.py runserver")
        print("5. python bot/main.py")
    else:
        print("\n🔧 Please fix the issues above before continuing")
        
    sys.exit(0 if success else 1)