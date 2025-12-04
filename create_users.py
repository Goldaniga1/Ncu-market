import sqlite3
from werkzeug.security import generate_password_hash

# 設定資料庫路徑 (跟你 app.py 裡的一樣)
DB_NAME = r'D:\Data\ncu_market.db'

def create_dummy_users():
    print("🚀 正在建立測試帳號...")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 定義要建立的測試帳號 (Email, 密碼, 暱稱)
    # 這裡的 Email 只是當帳號用，不需要真的能收信
    test_users = [
        ('seller@test.com', '123456', '測試賣家(Nig)'),
        ('buyer@test.com',  '123456', '測試買家(ger)'),
        ('admin@test.com',  '123456', '市集管理員')
    ]

    for email, password, name in test_users:
        # 1. 先檢查帳號是否已經存在
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        if c.fetchone():
            print(f"⚠️ 跳過 (已存在): {name} ({email})")
        else:
            # 2. 加密密碼並寫入資料庫
            hashed_pw = generate_password_hash(password)
            c.execute("INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)", 
                      (email, hashed_pw, name))
            print(f"✅ 建立成功: {name} ({email}) / 密碼: {password}")

    conn.commit()
    conn.close()
    print("\n🎉 全部完成！請重新啟動 app.py 並登入測試。")

if __name__ == '__main__':
    create_dummy_users()