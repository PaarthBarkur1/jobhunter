import sqlite3
import os

def patch_db():
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'jobs.db')
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(job_postings)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "scan_id" not in columns:
            print("Adding scan_id to job_postings...")
            cursor.execute("ALTER TABLE job_postings ADD COLUMN scan_id INTEGER REFERENCES scan_logs(id)")
            conn.commit()
            print("Migration successful.")
        else:
            print("Column scan_id already exists.")
            
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    patch_db()
