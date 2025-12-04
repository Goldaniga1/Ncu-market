import smtplib
from email.mime.text import MIMEText
from email.header import Header # 👈 新增這個工具來處理中文標題

# 👇 請填入你的資訊
GMAIL_USER = 'jonasliaw999@gmail.com'
GMAIL_PASSWORD = 'tszprjkwaaupwmrb' # ⚠️ 不能有空白鍵

def send_test_email():
    # 👇 修正 1: 明確告訴它我們要用 'utf-8' 編碼
    content = '恭喜！你的 Python 寄信功能是正常的！'
    msg = MIMEText(content, 'plain', 'utf-8')
    
    # 👇 修正 2: 中文標題也要經過 Header 編碼處理
    subject = 'Python 寄信測試'
    msg['Subject'] = Header(subject, 'utf-8')
    
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER

    try:
        # 連接 Gmail 伺服器
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        
        print("正在嘗試登入...")
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        print("✅ 登入成功！")
        
        print("正在寄信...")
        server.send_message(msg)
        print("✅ 信件已發送！請去收信。")
        
        server.quit()
    except Exception as e:
        print("\n❌ 失敗原因：")
        print(e)

if __name__ == '__main__':
    send_test_email()