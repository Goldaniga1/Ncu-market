import smtplib
from email.mime.text import MIMEText

# 👇 請填入你的資訊
GMAIL_USER = 'jonasliaw999@gmail.com'
GMAIL_PASSWORD = 'tszprjkwaaupwmrb' # ⚠️ 不能有空白鍵，純文字

def send_test_email():
    msg = MIMEText('恭喜！你的 Python 寄信功能是正常的！')
    msg['Subject'] = 'Python 寄信測試'
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER # 寄給自己測試

    try:
        # 連接 Gmail 伺服器
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls() # 啟動加密傳輸
        
        # 登入
        print("正在嘗試登入...")
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        print("✅ 登入成功！")
        
        # 寄信
        print("正在寄信...")
        server.send_message(msg)
        print("✅ 信件已發送！請去收信。")
        
        server.quit()
    except Exception as e:
        print("\n❌ 失敗原因：")
        print(e)

if __name__ == '__main__':
    send_test_email()