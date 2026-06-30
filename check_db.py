import sqlite3

def check_db():
    conn = sqlite3.connect('data/jobs.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM companies;")
    companies = cursor.fetchall()
    print("Companies:", companies)
    
    cursor.execute("SELECT * FROM scan_logs ORDER BY run_time DESC LIMIT 1;")
    scan_logs = cursor.fetchall()
    print("Last Scan Log:", scan_logs)
    
    conn.close()

if __name__ == '__main__':
    check_db()
