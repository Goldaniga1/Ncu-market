import os
import re
import sqlite3
import google.generativeai as genai
import random
import string
from flask import session # 用來暫存驗證碼
from flask_mail import Mail, Message # 寄信工具
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash # 🔒 密碼加密工具
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user # 👤 會員管理工具
from datetime import datetime, timedelta # 👈 新增 datetime 和 timedelta
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# 👇 修改讀取方式：改成 os.getenv('變數名稱')
app.secret_key = os.getenv('SECRET_KEY')

# ================= 📧 Gmail 設定 =================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
# 👇 補上這一行，明確告訴它不要用 SSL (因為我們用的是 TLS)
app.config['MAIL_USE_SSL'] = False 

# 從環境變數讀取帳密
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('NCU市集管理員', os.getenv('MAIL_USERNAME'))
app.config['MAIL_ASCII_ATTACHMENTS'] = False

mail = Mail(app)
# =================================================

# ================= 設定區 =================
UPLOAD_FOLDER = 'static/uploads'
basedir = os.path.abspath(os.path.dirname(__file__))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash') 
else:
    print("⚠️ 警告：找不到 GOOGLE_API_KEY，AI 功能將無法使用")
DB_NAME = r'D:\Data\ncu_market.db'
# =========================================

# 👇 初始化 SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# 初始化 LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # 沒登入時，自動踢去登入頁

# 定義 User 類別 (Flask-Login 需要)
class User(UserMixin):
    def __init__(self, id, email, name):
        self.id = id
        self.email = email
        self.name = name

# 每次 Request，Flask-Login 會呼叫這個函式來抓使用者
@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_data = c.fetchone()
    conn.close()
    if user_data:
        return User(id=user_data[0], email=user_data[1], name=user_data[3])
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 👇 新增這個工具：計算「多久前」
@app.template_filter('time_since')
def time_since(dt):
    if not dt:
        return ""
    
    # 確保 dt 是 datetime 物件 (有時候資料庫拿出來會是字串)
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S.%f')
        except:
            return "已售出"

    now = datetime.now()
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "不足 1 分鐘前售出"
    elif seconds < 3600:
        return f"{int(seconds // 60)} 分鐘前售出"
    elif seconds < 43200: # 12小時內
        return f"{int(seconds // 3600)} 小時前售出"
    else:
        return "已售出"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # User 表 (不變)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL
    )''')

    # Product 表 (不變)
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        ai_text TEXT,
        image_filename TEXT,
        contact_info TEXT,
        contact_type TEXT,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        sold_at TIMESTAMP
    )''')

    # 👇👇👇 新增：訊息表格 👇👇👇
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read BOOLEAN DEFAULT 0
    )''')

    # 👇👇👇 新增：徵求物品表格 👇👇👇
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        budget TEXT,  -- 預算 (可以是範圍，所以用 TEXT)
        description TEXT,
        contact_info TEXT,
        contact_type TEXT,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'active', -- active, fulfilled
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

def ask_ai_for_marketing(item_name, item_price):
    try:
        prompt = f"""
        你是一個幽默的大學生，請為這個商品寫一句推銷文案。
        商品名稱：{item_name}
        價格：{item_price}元
        要求：
        1. 語氣幽默、有趣，像大學生之間的對話。
        2. 字數嚴格控制在 30 字以內。
        3. **絕對不要**在文案結尾加上字數統計（例如：(25字)、(30字)）。
        4. 直接輸出文案內容即可，不要有任何其他開頭或結尾的解釋。
        """
        
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "（AI 暫時休息中）"

init_db()

# 產生 6 位數驗證碼的小工具
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

# 步驟一：註冊填表 -> 寄送驗證碼
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')

        # 🛑 1. 檢查 Email 格式 (你可以先改成 @gmail.com 方便測試，測完再改回 @cc.ncu.edu.tw)
        if not email.endswith('@cc.ncu.edu.tw') and not email.endswith('@cc.ncu.edu.tw'):
            flash('請使用中央大學信箱 (例如 s112xxxxxx@cc.ncu.edu.tw)！')
            return redirect(url_for('register'))

        # 🛑 2. 密碼強度檢查
        if len(password) < 8:
            flash('密碼長度不足 8 碼')
            return redirect(url_for('register'))
        if not re.search(r"[a-z]", password) or not re.search(r"[A-Z]", password) or not re.search(r"[0-9]", password):
            flash('密碼需包含大小寫英文及數字')
            return redirect(url_for('register'))

        # 🛑 3. 檢查資料庫是否已存在
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        if c.fetchone():
            flash('此信箱已註冊！')
            conn.close()
            return redirect(url_for('register'))
        conn.close()

        # 🚀 4. 產生驗證碼並寄信
        otp_code = generate_otp()
        
        # 把資料暫存在 Server 的 Session 裡 (就像寄物櫃，還沒存進資料庫)
        session['temp_user'] = {
            'email': email,
            'name': name,
            'password': password, 
            'otp': otp_code
        }

        # 發送 Email
        try:
            msg = Message("【NCU市集】您的註冊驗證碼", recipients=[email])
            msg.body = f"嗨 {name}！\n\n歡迎加入 NCU 二手市集。\n您的驗證碼是：{otp_code}\n\n請在網頁上輸入此代碼完成註冊。"
            mail.send(msg)
            flash('驗證碼已寄出，請收信！', 'success')
            return redirect(url_for('verify_otp')) # 跳轉到驗證頁面
        except Exception as e:
            print(f"❌ 寄信失敗: {e}")
            flash('寄信失敗，請檢查 Email 是否正確')
            return redirect(url_for('register'))

    return render_template('register.html')

# 步驟二：輸入驗證碼 -> 寫入資料庫
@app.route('/verify', methods=['GET', 'POST'])
def verify_otp():
    # 如果沒有暫存資料，代表他是偷跑進來的，踢回註冊頁
    if 'temp_user' not in session:
        return redirect(url_for('register'))

    if request.method == 'POST':
        user_input = request.form.get('otp')
        real_otp = session['temp_user']['otp']

        if user_input == real_otp:
            # ✅ 驗證成功！這時候才真正寫入資料庫
            user_data = session['temp_user']
            hashed_pw = generate_password_hash(user_data['password']) # 加密

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)", 
                      (user_data['email'], hashed_pw, user_data['name']))
            conn.commit()
            conn.close()

            # 清除暫存
            session.pop('temp_user', None)
            flash('驗證成功！帳號已建立，請登入。', 'success')
            return redirect(url_for('login'))
        else:
            flash('❌ 驗證碼錯誤，請再試一次。')

    return render_template('verify.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_data = c.fetchone() # (id, email, hash, name)
        conn.close()

        # 比對密碼
        if user_data and check_password_hash(user_data[2], password):
            user = User(id=user_data[0], email=user_data[1], name=user_data[3])
            login_user(user) # 登入成功，建立 Session
            return redirect(url_for('home'))
        else:
            flash('帳號或密碼錯誤')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ================= 主功能區 =================

@app.route('/', methods=['GET', 'POST'])
def home():
    # 建立資料庫連線 (全程只用這一個，避免鎖死)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'POST':
        # 🛑 只有登入的人才能上架
        if not current_user.is_authenticated:
            conn.close() # 記得關閉連線
            return redirect(url_for('login'))

        name = request.form.get('product_name')
        price = request.form.get('product_price')
        contact = request.form.get('contact_info')
        contact_type = request.form.get('contact_type')
        manual_desc = request.form.get('product_desc') 
        use_ai = request.form.get('use_ai') 
        
        # 👇 多圖處理邏輯
        image_filenames_str = None 
        
        files = request.files.getlist('product_image')
        valid_files = [f for f in files if f.filename != '']
        
        # 1. 檢查數量上限
        if len(valid_files) > 10:
            flash('最多只能上傳 10 張照片！', 'error')
            conn.close() # 記得關閉
            return redirect(url_for('home'))

        saved_filenames = []
        # 2. 迴圈存檔
        for file in valid_files:
            if allowed_file(file.filename):
                safe_name = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], safe_name))
                saved_filenames.append(safe_name)

        # 3. 串接檔名
        if saved_filenames:
            image_filenames_str = ",".join(saved_filenames)

        if name and price:
            final_text = ""
            if use_ai == 'on':
                final_text = ask_ai_for_marketing(name, price)
            else:
                final_text = manual_desc if manual_desc else "賣家很懶，什麼都沒寫..."

            # 💾 存檔
            c.execute('''
                INSERT INTO products (name, price, ai_text, image_filename, contact_info, contact_type, user_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, price, final_text, image_filenames_str, contact, contact_type, current_user.id))
            
            conn.commit()
            conn.close() # 成功提交後關閉
            return redirect(url_for('home'))

    # 👇 GET: 讀取商品
    search_query = request.args.get('q')
    time_threshold = datetime.now() - timedelta(minutes=5)

    query = """
        SELECT products.*, users.name as seller_name 
        FROM products 
        LEFT JOIN users ON products.user_id = users.id
        WHERE (status = 'active') 
           OR (status = 'sold' AND sold_at > ?)
    """
    params = [time_threshold]

    if search_query:
        query += " AND (products.name LIKE ?)"
        params.append(f'%{search_query}%')
    
    query += " ORDER BY products.id DESC"

    c.execute(query, params)
    products = c.fetchall()

    # 👇 計算未讀訊息 (直接使用同一個連線 c，不需要重新 connect)
    unread_count = 0
    if current_user.is_authenticated:
        c.execute("SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0", (current_user.id,))
        result = c.fetchone()
        if result:
            unread_count = result[0]

    conn.close() # 最後統一關閉連線
    return render_template('index.html', products=products, search_query=search_query, unread_count=unread_count)

# 📋 徵物公佈欄 (類似首頁，但專門放徵求)
@app.route('/requests', methods=['GET', 'POST'])
def request_board():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 處理發表徵求 (POST)
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        
        title = request.form.get('title')
        budget = request.form.get('budget')
        desc = request.form.get('description')
        contact = request.form.get('contact_info')
        contact_type = request.form.get('contact_type')

        if title:
            c.execute('''
                INSERT INTO requests (title, budget, description, contact_info, contact_type, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (title, budget, desc, contact, contact_type, current_user.id))
            conn.commit()
            flash('✨ 徵求已貼上公佈欄！', 'success')
            conn.close()
            return redirect(url_for('request_board'))

    # 讀取所有徵求 (GET)
    c.execute("""
        SELECT requests.*, users.name as buyer_name 
        FROM requests 
        LEFT JOIN users ON requests.user_id = users.id
        WHERE status = 'active'
        ORDER BY id DESC
    """)
    reqs = c.fetchall()
    conn.close()

    return render_template('requests.html', requests=reqs)

# ✅ 標記徵求已徵到 (結案)
@app.route('/fulfill_request/<int:req_id>', methods=['POST'])
@login_required
def fulfill_request(req_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM requests WHERE id = ?", (req_id,))
    req = c.fetchone()

    if req and req[0] == current_user.id:
        c.execute("UPDATE requests SET status = 'fulfilled' WHERE id = ?", (req_id,))
        conn.commit()
        flash('恭喜徵到！公佈欄已更新 🎉', 'success')
    
    conn.close()
    return redirect(url_for('dashboard'))

# 🗑️ 刪除徵求 (新增這個函式)
@app.route('/delete_request/<int:req_id>', methods=['POST'])
@login_required
def delete_request(req_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM requests WHERE id = ?", (req_id,))
    req = c.fetchone()

    # 檢查權限：只能刪除自己的
    if req and req[0] == current_user.id:
        c.execute("DELETE FROM requests WHERE id = ?", (req_id,))
        conn.commit()
        flash('徵求紀錄已刪除', 'success')
    else:
        flash('你不能刪除別人的徵求！', 'error')
    
    conn.close()
    return redirect(url_for('dashboard'))

# 📂 收件匣：列出我有跟誰聊過天
@app.route('/inbox')
@login_required
def inbox():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 這段 SQL 比較複雜：找出「我傳給別人」或「別人傳給我」的所有對話對象，並抓出最後一句話
    # 這裡先做簡易版：抓出所有跟我有過對話的使用者
    query = """
        SELECT DISTINCT users.id, users.name 
        FROM messages 
        JOIN users ON (messages.sender_id = users.id OR messages.receiver_id = users.id)
        WHERE (messages.sender_id = ? OR messages.receiver_id = ?) AND users.id != ?
    """
    c.execute(query, (current_user.id, current_user.id, current_user.id))
    chat_partners = c.fetchall()
    conn.close()
    
    return render_template('inbox.html', partners=chat_partners)

# 💬 私訊聊天室：跟某人的一對一聊天
@app.route('/chat/<int:target_id>')
@login_required
def chat_room(target_id):
    if target_id == current_user.id:
        flash('不能跟自己聊天喔！', 'error')
        return redirect(url_for('home'))

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. 抓對方名字
    c.execute("SELECT name FROM users WHERE id = ?", (target_id,))
    target_user = c.fetchone()
    
    if not target_user:
        flash('使用者不存在', 'error')
        return redirect(url_for('home'))

    # 👇👇👇 新增這段：標記已讀 (Mark as Read) 👇👇👇
    # 邏輯：把「對方(sender) 傳給 我(receiver)」的所有訊息，is_read 設為 1 (True)
    c.execute("""
        UPDATE messages 
        SET is_read = 1 
        WHERE sender_id = ? AND receiver_id = ?
    """, (target_id, current_user.id))
    conn.commit() # 記得提交變更
    # 👆👆👆 新增結束 👆👆👆

    # 2. 抓歷史訊息
    c.execute("""
        SELECT * FROM messages 
        WHERE (sender_id = ? AND receiver_id = ?) 
           OR (sender_id = ? AND receiver_id = ?)
        ORDER BY timestamp ASC
    """, (current_user.id, target_id, target_id, current_user.id))
    history = c.fetchall()
    conn.close()

    return render_template('chat.html', target_user=target_user, target_id=target_id, history=history)

# 👇 定義一個專門在背景寄信的函式 (請放在 handle_message 上方)
def send_email_background(app, receiver_email, receiver_name, sender_name, content, chat_url):
    # 必須建立 app context，不然背景程式不知道 Gmail 帳號密碼設定在哪
    with app.app_context():
        try:
            msg = Message(f"【NCU市集】{sender_name} 傳了一則訊息給你", recipients=[receiver_email])
            msg.body = f"嗨 {receiver_name}，\n\n{sender_name} 剛剛在市集傳訊息給你：\n\n「{content}」\n\n請回到網站回覆： {chat_url}"
            mail.send(msg)
            print(f"📧 DEBUG: 背景通知信已成功寄給 {receiver_name}")
        except Exception as e:
            print(f"❌ DEBUG: 背景寄信失敗: {e}")

# 🔗 WebSocket 事件：使用者傳送訊息
@socketio.on('send_message')
def handle_message(data):
    sender_id = current_user.id
    receiver_id = data['target_id']
    content = data['message']
    
    if not content:
        return

    # 1. 存入資料庫 (資料庫寫入很快，同步執行即可)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
              (sender_id, receiver_id, content))
    conn.commit()

    # 2. 抓出接收者資料
    c.execute("SELECT email, name FROM users WHERE id = ?", (receiver_id,))
    receiver_data = c.fetchone()
    conn.close()

    # 3. WebSocket 廣播 (這行執行完，對方聊天室就會立刻跳出訊息！⚡)
    room_id = f"chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"
    emit('new_message', {
        'sender_id': sender_id,
        'sender_name': current_user.name,
        'content': content,
        'time': datetime.now().strftime('%H:%M')
    }, room=room_id)

    # 4. 👇👇👇 修改：啟動背景任務去寄信 (不會卡住聊天室) 👇👇👇
    if receiver_data:
        receiver_email = receiver_data[0]
        receiver_name = receiver_data[1]
        
        # 我們先在這裡把網址算好，傳字串進去背景任務比較安全
        chat_url = url_for('chat_room', target_id=sender_id, _external=True)
        
        # 使用 socketio 的背景任務功能，把上面定義的函式丟到背景跑
        socketio.start_background_task(
            send_email_background, 
            app, 
            receiver_email, 
            receiver_name, 
            current_user.name, 
            content, 
            chat_url
        )

# 🔗 WebSocket 事件：使用者進入聊天室
@socketio.on('join_chat')
def on_join(data):
    target_id = data['target_id']
    room_id = f"chat_{min(current_user.id, target_id)}_{max(current_user.id, target_id)}"
    join_room(room_id)
    print(f"DEBUG: User {current_user.name} joined room {room_id}")

@app.route('/delete/<int:product_id>', methods=['POST'])
@login_required # 🛑 必須登入
def delete_product(product_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 檢查這個商品是不是這個人發的
    c.execute("SELECT user_id FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()

    if product and product[0] == current_user.id:
        c.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()
        flash('商品已刪除')
    else:
        flash('你不能刪除別人的商品！')
        
    conn.close()
    return redirect(url_for('dashboard'))

# 👤 會員中心：我的市集
@app.route('/dashboard')
@login_required
def dashboard():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. 抓我賣的東西
    c.execute("SELECT * FROM products WHERE user_id = ? ORDER BY id DESC", (current_user.id,))
    my_products = c.fetchall()

    # 2. 抓我徵的東西 (新增這段)
    c.execute("SELECT * FROM requests WHERE user_id = ? ORDER BY id DESC", (current_user.id,))
    my_requests = c.fetchall()

    conn.close()
    
    return render_template('dashboard.html', products=my_products, requests=my_requests)

# 💰 標記為已售出
@app.route('/mark_sold/<int:product_id>', methods=['POST'])
@login_required
def mark_sold(product_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()

    if product and product[0] == current_user.id:
        # 👇 修改：除了改 status，還要記錄 sold_at (現在時間)
        now = datetime.now()
        c.execute("UPDATE products SET status = 'sold', sold_at = ? WHERE id = ?", (now, product_id))
        conn.commit()
        flash('恭喜成交！商品已標示為售出 🎉')
    
    conn.close()
    return redirect(url_for('dashboard'))

# 🔄 重新上架 (如果不小心按錯)
@app.route('/mark_active/<int:product_id>', methods=['POST'])
@login_required
def mark_active(product_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()

    if product and product[0] == current_user.id:
        c.execute("UPDATE products SET status = 'active' WHERE id = ?", (product_id,))
        conn.commit()
        flash('商品已重新上架！')
    
    conn.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # 👇👇👇 關鍵修改：改成 socketio.run 👇👇👇
    # allow_unsafe_werkzeug=True 是為了解決某些版本搭配問題，開發環境可以用
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)