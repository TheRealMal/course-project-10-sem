#!/usr/bin/env python3
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def execute_sql_script(script_path):
    db_connect_url = os.getenv("DB_CONNECT_URL")
    
    if not db_connect_url:
        raise ValueError("environment variable needed: DB_CONNECT_URL")
    
    try:
        conn = psycopg2.connect(db_connect_url)
        conn.autocommit = True
        
        with conn.cursor() as cursor, open(script_path, "r", encoding="utf-8") as file:
            sql_script = file.read()
            cursor.execute(sql_script)
        
        print("database tables dropped")
    except Exception as e:
        print(f"database tables drop failed {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    execute_sql_script("/scripts/001_drop_tables.down.sql")
