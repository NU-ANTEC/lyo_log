import os
import smtplib
import sys
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
# Requires a .env file that contains the following parameters

gmail_user = os.getenv('GMAIL_USER')
gmail_app_password = os.getenv('GMAIL_APP_PASSWORD')
to_email = os.getenv('ALERT_RECIPIENT')

alert_type = sys.argv[1] if len(sys.argv) > 1 else "Unknown"

subject = f'24port Alert: {alert_type}'
body = f"Alert triggered: {alert_type}\nPlease check the 24port system status immediately."

msg = MIMEText(body)
msg['Subject'] = subject
msg['From'] = gmail_user
msg['To'] = to_email

try:
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg)
    print("Email alert sent.")
except Exception as e:
    print(f"Email failed: {e}")
