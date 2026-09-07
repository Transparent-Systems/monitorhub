"""
Check SQLite version and capabilities.
Save as: check_sqlite.py
"""

import json
import sqlite3
import sys


def main():
    print("=" * 60)
    print("SQLite Environment Information")
    print("=" * 60)
    
    # Basic version info
    print(f"\nPython interpreter: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"SQLite version (sqlite3.sqlite_version): {sqlite3.sqlite_version}")
    
    # Detailed version info
    try:
        version_info = sqlite3.sqlite_version_info
        print(f"SQLite version tuple: {version_info}")
        major, minor, patch = version_info
        print(f"Major: {major}, Minor: {minor}, Patch: {patch}")
    except AttributeError:
        print("Version info not available")
    
    # Test JSON support
    print("\n" + "-" * 60)
    print("Testing JSON Support")
    print("-" * 60)
    
    try:
        conn = sqlite3.connect(':memory:')
        
        # Test basic JSON
        cursor = conn.execute("SELECT json('{\"test\": \"value\"}')")
        result = cursor.fetchone()[0]
        print(f"✅ Basic JSON function: {result}")
        
        # Test JSON validation
        try:
            # Valid JSON
            conn.execute("SELECT json_valid('{\"valid\": true}')").fetchone()
            print("✅ JSON validation: works")
            
            # Invalid JSON should raise error
            try:
                conn.execute("SELECT json_valid('invalid json')").fetchone()
                print("   JSON validation: works with invalid too")
            except Exception as e:  # noqa: BLE001
                print(f"❌ JSON validation: invalid JSON correctly raised error: {e}")
        except sqlite3.OperationalError as e:
            print(f"❌ JSON validation test error: {e}")                
        
        # Test JSONB support (SQLite 3.45.0+)
        try:
            cursor = conn.execute("SELECT jsonb('{\"test\": \"value\"}')")
            result = cursor.fetchone()[0]
            print(f"✅ JSONB support: available (version {sqlite3.sqlite_version})")
        except sqlite3.OperationalError as e:
            if "no such function: jsonb" in str(e):
                print(f"ℹ️ JSONB support: requires SQLite 3.45.0+ (you have {sqlite3.sqlite_version})")
            else:
                print(f"⚠️ JSONB test error: {e}")
        
        # Test JSON columns
        try:
            conn.execute("""
                CREATE TABLE test_json (id INTEGER, config JSON)
            """)
            conn.execute(
                "INSERT INTO test_json (id, config) VALUES (?, ?)",
                (1, json.dumps({"test": "data"}))
            )
            result = conn.execute("SELECT config FROM test_json").fetchone()[0]
            print("✅ JSON column type: works")
        except sqlite3.OperationalError as e:
            print(f"ℹ️ JSON column type may not be fully supported: {e}")
        
        # Determine if JSON is built-in
        print("\n📌 Summary:")
        if sqlite3.sqlite_version >= '3.38.0':
            print(f"   ✅ JSON functions are built-in (version {sqlite3.sqlite_version})")
        else:
            print(f"   ⚠️ JSON functions may need the JSON1 extension (version {sqlite3.sqlite_version})")
        
        if sqlite3.sqlite_version >= '3.45.0':
            print(f"   ✅ JSONB binary format is available (version {sqlite3.sqlite_version})")
        
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error testing JSON: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()