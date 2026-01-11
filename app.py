import sqlite3
import datetime
import requests
import atexit
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from flask import Flask, render_template, jsonify, request, g
import socket
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE = 'data.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        # 创建用户表
        # id: 唯一标识
        # nickname: 昵称
        # device_id: 设备唯一标识 (浏览器生成的UUID)
        # wechat_webhook: 企业微信 Webhook
        # emails: 邮箱列表 (逗号分隔)
        # last_check_in_date: 最后签到日期 (YYYY-MM-DD)
        # check_in_days: 连续签到天数
        # 用户由 (nickname, device_id) 唯一标识
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT,
                device_id TEXT,
                wechat_webhook TEXT,
                emails TEXT,
                last_check_in_date TEXT,
                check_in_days INTEGER DEFAULT 0,
                UNIQUE(nickname, device_id)
            )
        ''')
        # 不需要默认用户了，根据登录创建
        db.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sw.js')
def sw():
    return app.send_static_file('sw.js')

# --- API ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    nickname = data.get('nickname')
    device_id = data.get('device_id')

    if not nickname:
        return jsonify({'status': 'error', 'message': '昵称不能为空'}), 400

    if not device_id:
        return jsonify({'status': 'error', 'message': '设备ID不能为空'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE nickname = ? AND device_id = ?', (nickname, device_id)).fetchone()

    if not user:
        # 创建新用户
        cur = db.execute('INSERT INTO users (nickname, device_id, check_in_days) VALUES (?, ?, 0)', (nickname, device_id))
        db.commit()
        user_id = cur.lastrowid
        return jsonify({
            'status': 'success',
            'user_id': user_id,
            'is_new': True,
            'nickname': nickname
        })
    else:
        return jsonify({
            'status': 'success',
            'user_id': user['id'],
            'is_new': False,
            'nickname': user['nickname']
        })

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    db = get_db()
    
    # 辅助函数：获取 user_id
    user_id = request.args.get('user_id') if request.method == 'GET' else request.json.get('user_id')
    
    if not user_id:
        return jsonify({'status': 'error', 'message': '缺少用户ID'}), 400

    if request.method == 'GET':
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
             return jsonify({'status': 'error', 'message': '用户不存在'}), 404
             
        today = datetime.date.today().isoformat()
        is_checked_in = (user['last_check_in_date'] == today)
        return jsonify({
            'nickname': user['nickname'] or '',
            # 'wechat_webhook': user['wechat_webhook'] or '', # 隐私保护：不返回敏感配置
            # 'emails': user['emails'] or '',                 # 隐私保护：不返回敏感配置
            'check_in_days': user['check_in_days'],
            'is_checked_in': is_checked_in
        })
    
    if request.method == 'POST':
        data = request.json
        
        # 支持部分更新
        if 'wechat_webhook' in data:
            db.execute('UPDATE users SET wechat_webhook = ? WHERE id = ?', (data['wechat_webhook'], user_id))
            
        if 'emails' in data:
            db.execute('UPDATE users SET emails = ? WHERE id = ?', (data['emails'], user_id))
            
        db.commit()
        return jsonify({'status': 'success'})

@app.route('/api/check_in', methods=['POST'])
def check_in():
    db = get_db()
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'status': 'error', 'message': '未登录'}), 400

    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'status': 'error', 'message': '用户不存在'}), 404
    
    # 校验配置：昵称必须有，微信或邮件至少有一个
    if not user['nickname']:
        return jsonify({'status': 'error', 'message': '请先配置昵称'}), 400
        
    if not user['wechat_webhook'] and not user['emails']:
        return jsonify({'status': 'error', 'message': '请至少配置一种通知方式（微信或邮件）'}), 400

    today = datetime.date.today().isoformat()
    last_date = user['last_check_in_date']
    
    if last_date == today:
        return jsonify({'status': 'success', 'message': '今日已签到', 'days': user['check_in_days']})
    
    # 计算连续签到
    new_days = 1
    if last_date:
        last_date_obj = datetime.date.fromisoformat(last_date)
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        if last_date_obj == yesterday:
            new_days = user['check_in_days'] + 1
        else:
            new_days = 1
    else:
        new_days = 1

    db.execute('''
        UPDATE users 
        SET last_check_in_date = ?, check_in_days = ?
        WHERE id = ?
    ''', (today, new_days, user_id))
    db.commit()
    
    return jsonify({'status': 'success', 'days': new_days})

@app.route('/api/delete_user', methods=['POST'])
def delete_user():
    db = get_db()
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'status': 'error', 'message': '未登录'}), 400

    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    
    return jsonify({'status': 'success', 'message': '用户已删除'})

@app.route('/api/test_notification', methods=['POST'])
def test_notification():
    data = request.json
    user_id = data.get('user_id')
    notify_type = data.get('type') # 'wechat' or 'email'
    
    if not user_id:
        return jsonify({'status': 'error', 'message': '未登录'}), 400
        
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'status': 'error', 'message': '用户不存在'}), 404

    try:
        if notify_type == 'wechat':
            if not user['wechat_webhook']:
                 return jsonify({'status': 'error', 'message': '未配置微信 Webhook'}), 400
            send_wechat_notification(user, is_test=True)
        elif notify_type == 'email':
            if not user['emails']:
                 return jsonify({'status': 'error', 'message': '未配置邮箱'}), 400
            send_email_notification(user, is_test=True)
        else:
            return jsonify({'status': 'error', 'message': '未知通知类型'}), 400
            
        return jsonify({'status': 'success', 'message': '测试发送成功'})
    except Exception as e:
        logger.error(f"Test notification failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- 定时任务 ---
def check_activity_job():
    with app.app_context():
        db = get_db()
        # 遍历所有用户
        users = db.execute('SELECT * FROM users').fetchall()
        
        today = datetime.date.today()
        
        for user in users:
            if not user['last_check_in_date']:
                continue

            last_date = datetime.date.fromisoformat(user['last_check_in_date'])
            delta = (today - last_date).days
            
            # 连续4天未签到 -> 删除用户数据且不通知
            if delta >= 4:
                logger.info(f"Deleting user {user['nickname']} due to inactivity ({delta} days)")
                db.execute('DELETE FROM users WHERE id = ?', (user['id'],))
                db.commit()
                continue

            # 连续2天没有签到 -> 发送通知
            if delta >= 2:
                send_wechat_notification(user)
                send_email_notification(user)

def send_email_notification(user, is_test=False):
    emails = user['emails']
    nickname = user['nickname']
    if not emails or not nickname:
        return

    # 获取配置
    mail_user = os.getenv('MAIL_USERNAME')
    mail_pass = os.getenv('MAIL_PASSWORD')
    mail_host = os.getenv('MAIL_SERVER', 'smtp.qq.com')
    mail_port = int(os.getenv('MAIL_PORT', 465))

    if not mail_user or not mail_pass:
        logger.error("未配置邮箱发送账户信息")
        return

    content = f"我是{nickname}我已经连续很多天没有活动了，快来关心一下我。"
    if is_test:
        content = f"【测试】我是{nickname}，这是一条测试通知，证明邮件配置正常！"
    
    # 解析收件人列表
    receivers = [e.strip() for e in emails.split(',') if e.strip()]
    if not receivers:
        return

    message = MIMEText(content, 'plain', 'utf-8')
    # 修复 From 头：使用 formataddr 配合 Header 编码昵称，满足 RFC 标准
    message['From'] = formataddr((Header("活着呢", 'utf-8').encode(), mail_user))
    # 修复 To 头：直接使用逗号连接邮箱，避免 Header 编码导致格式错误
    message['To'] =  ",".join(receivers)
    
    subject = f"{nickname} 签到提醒"
    if is_test:
        subject = f"【测试】{nickname} 签到配置验证"
    message['Subject'] = Header(subject, 'utf-8')

    try:
        if mail_port == 465:
            smtpObj = smtplib.SMTP_SSL(mail_host, mail_port)
        else:
            smtpObj = smtplib.SMTP(mail_host, mail_port)
            smtpObj.starttls()
            
        smtpObj.login(mail_user, mail_pass)
        smtpObj.sendmail(mail_user, receivers, message.as_string())
        smtpObj.quit()
        logger.info(f"发送邮件通知成功: {receivers}")
    except smtplib.SMTPException as e:
        logger.error(f"发送邮件通知失败: {e}")
        raise e

def send_wechat_notification(user, is_test=False):
    webhooks_str = user['wechat_webhook']
    nickname = user['nickname']
    if not webhooks_str or not nickname:
        return

    content = f"我是{nickname}我已经连续很多天没有活动了，快来关心一下我。"
    if is_test:
        content = f"【测试】我是{nickname}，这是一条测试通知，证明企业微信配置正常！"
    
    # 解析 Webhook 列表
    webhooks = [w.strip() for w in webhooks_str.split(',') if w.strip()]
    
    success_count = 0
    errors = []
    
    for webhook in webhooks:
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
            resp = requests.post(webhook, json=data)
            logger.info(f"发送企业微信通知结果 ({webhook[:20]}...): {resp.text}")
            if resp.status_code == 200:
                success_count += 1
            else:
                errors.append(f"Status {resp.status_code}")
        except Exception as e:
            logger.error(f"发送企业微信通知失败 ({webhook[:20]}...): {e}")
            errors.append(str(e))
            
    if is_test:
        if success_count > 0:
            return # 至少有一个成功就算成功
        if errors:
            raise Exception(f"所有 Webhook 发送失败: {'; '.join(errors)}")

# 启动定时任务
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_activity_job, trigger="interval", hours=24) # 每天检查一次
scheduler.start()
atexit.register(lambda: scheduler.shutdown())


def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    else:
        init_db()

    ip = get_ip_address()
    port = 5001
    print(f"\n========================================")
    print(f"该项目由孙田宇宇哥制作并开源，视频号，抖音，小红书可以关注孙田宇宇哥，感谢支持～")
    print(f"http://{ip}:{port}")
    print(f"========================================\n")
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
