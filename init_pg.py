import os
import psycopg2

def init_postgres():
    # 從環境變數讀取 Railway 提供的 DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: 找不到環境變數 DATABASE_URL，請確認已在 Railway Variables 中設定。")
        return

    # 修正可能出現的 postgres:// 為 postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    print(f"Connecting to database...")
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # 讀取 schema.sql
        with open("schema.sql", "r", encoding="utf-8") as f:
            schema_sql = f.read()
            
        print("Executing schema.sql...")
        cursor.execute(schema_sql)
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ PostgreSQL 資料表初始化成功！")
        
    except Exception as e:
        print(f"❌ 初始化失敗: {e}")

if __name__ == "__main__":
    init_postgres()