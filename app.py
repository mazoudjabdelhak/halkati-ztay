# -*- coding: utf-8 -*-
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'qU8xL9pK2mN5vB7cXzW4fR6tY3jH0sE1')

app.jinja_env.globals.update(datetime=datetime)
app.jinja_env.globals.update(timedelta=timedelta)

# === إعدادات PostgreSQL (من Render أو البيئة المحلية) ===
# Render يعطيك DATABASE_URL تلقائياً عند ربط PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Render يعطي الرابط بصيغة postgres:// لكن psycopg2 يحتاج postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    import urllib.parse
    parsed = urllib.parse.urlparse(DATABASE_URL)
    DB_CONFIG = {
        'dbname': parsed.path[1:],
        'user': parsed.username,
        'password': parsed.password,
        'host': parsed.hostname,
        'port': parsed.port or '5432'
    }
else:
    DB_CONFIG = {
        'dbname': os.environ.get('DB_NAME', 'quran_halaqa'),
        'user': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', 'postgres'),
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432')
    }

def get_db():
    """الحصول على اتصال بقاعدة البيانات PostgreSQL"""
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def query_one(conn, sql, params=()):
    """تنفيذ استعلام وإرجاع صف واحد كـ dict"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row

def query_all(conn, sql, params=()):
    """تنفيذ استعلام وإرجاع جميع الصفوف كـ list of dicts"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows

def execute_sql(conn, sql, params=()):
    """تنفيذ استعلام INSERT/UPDATE/DELETE"""
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()

def init_db():
    """تهيئة قاعدة البيانات PostgreSQL"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        name VARCHAR(255) NOT NULL,
        email VARCHAR(255),
        phone VARCHAR(50),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        phone VARCHAR(50),
        parent_phone VARCHAR(50),
        address TEXT,
        rank INTEGER DEFAULT 0,
        join_date DATE DEFAULT CURRENT_DATE,
        status VARCHAR(50) DEFAULT 'active',
        payment_status VARCHAR(50) DEFAULT 'pending',
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS registration_requests (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        phone VARCHAR(50),
        parent_phone VARCHAR(50),
        address TEXT,
        status VARCHAR(50) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS competitions (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        max_grade NUMERIC DEFAULT 10,
        date DATE DEFAULT CURRENT_DATE,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS competition_grades (
        student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
        competition_id INTEGER REFERENCES competitions(id) ON DELETE CASCADE,
        grade NUMERIC DEFAULT 0,
        notes TEXT,
        updated_at TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (student_id, competition_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_evaluations (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        curr_save VARCHAR(255),
        score_save NUMERIC DEFAULT 0,
        curr_rev VARCHAR(255),
        score_rev NUMERIC DEFAULT 0,
        homework_score NUMERIC DEFAULT 0,
        notes TEXT,
        sent BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(student_id, date)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS homework (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        details TEXT,
        notes TEXT,
        sent BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(student_id, date)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER NOT NULL,
        sender_type VARCHAR(50) NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_read BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)

    # إضافة مشرف افتراضي
    cur.execute("SELECT * FROM admins WHERE username = %s", ('الشيخ',))
    if not cur.fetchone():
        hashed_pw = generate_password_hash('بومسلة العيد')
        cur.execute(
            "INSERT INTO admins (username, password, name, email) VALUES (%s, %s, %s, %s)",
            ('الشيخ', hashed_pw, ' أبو عمر بومسلة العيد', 'admin@quran.com')
        )

    # إضافة طالب افتراضي للتجربة
    cur.execute("SELECT * FROM students WHERE email = %s", ('yacinezaoui2010@gmail.com',))
    if not cur.fetchone():
        hashed_pw = generate_password_hash('*yacinezaoui2010#')
        cur.execute("""
            INSERT INTO students (name, email, password, phone, rank, status, payment_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (' yacine yasine', 'yacinezaoui2010@gmail.com', hashed_pw, '0665450555', 1, 'active', 'paid'))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ قاعدة البيانات PostgreSQL جاهزة!")

def parse_nested_form(prefix):
    """تحليل النماذج المتداخلة مثل evaluations[1][field]"""
    data = {}
    pattern = re.compile(rf'{re.escape(prefix)}\[(\d+)\]\[([^\]]+)\]')
    for key, value in request.form.items():
        match = pattern.match(key)
        if match:
            sid, field = match.groups()
            if sid not in data:
                data[sid] = {}
            data[sid][field] = value
    return data

def get_students(status=None):
    conn = get_db()
    if status:
        students = query_all(conn,
            "SELECT * FROM students WHERE status = %s ORDER BY rank ASC, name ASC", 
            (status,))
    else:
        students = query_all(conn,
            "SELECT * FROM students ORDER BY rank ASC, name ASC")
    conn.close()
    return students

def get_active_students():
    return get_students('active')

def format_date(date_str):
    if not date_str:
        return ''
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return d.strftime('%Y-%m-%d')
    except:
        return date_str

def flash_message(message, category='info'):
    flash(message, category)

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>دخول المشرف</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a2a6c, #b21f1f, #fdbb2d);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(255,255,255,0.95);
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
        }
        .login-container h1 {
            text-align: center;
            color: #1a2a6c;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .login-container .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 16px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #333;
            font-weight: 600;
        }
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 16px;
            transition: 0.3s;
        }
        .form-group input:focus {
            border-color: #1a2a6c;
            outline: none;
            box-shadow: 0 0 0 3px rgba(26,42,108,0.1);
        }
        .btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: 0.3s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }
        .links {
            text-align: center;
            margin-top: 20px;
        }
        .links a {
            color: #1a2a6c;
            text-decoration: none;
            font-weight: 600;
        }
        .links a:hover {
            text-decoration: underline;
        }
        .alert {
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .logo {
            text-align: center;
            font-size: 60px;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">🕌</div>
        <h1>دخول المشرف</h1>
        <p class="subtitle">نظام إدارة الحلقة القرآنية</p>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST">
            <div class="form-group">
                <label>اسم المستخدم</label>
                <input type="text" name="username" required placeholder="أدخل اسم المستخدم">
            </div>
            <div class="form-group">
                <label>كلمة المرور</label>
                <input type="password" name="password" required placeholder="أدخل كلمة المرور">
            </div>
            <button type="submit" class="btn">دخول</button>
        </form>
        <div class="links">
            <a href="{{ url_for('student_login') }}">دخول الطالب</a> | 
            <a href="{{ url_for('student_register') }}">تسجيل جديد</a>
        </div>
    </div>
</body>
</html>
'''

STUDENT_LOGIN_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>دخول الطالب</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #134e5e, #71b280);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(255,255,255,0.95);
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
        }
        .login-container h1 {
            text-align: center;
            color: #134e5e;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .login-container .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 16px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #333;
            font-weight: 600;
        }
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 16px;
            transition: 0.3s;
        }
        .form-group input:focus {
            border-color: #134e5e;
            outline: none;
            box-shadow: 0 0 0 3px rgba(19,78,94,0.1);
        }
        .btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: 0.3s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }
        .links {
            text-align: center;
            margin-top: 20px;
        }
        .links a {
            color: #134e5e;
            text-decoration: none;
            font-weight: 600;
        }
        .links a:hover {
            text-decoration: underline;
        }
        .alert {
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .logo {
            text-align: center;
            font-size: 60px;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">📖</div>
        <h1>دخول الطالب</h1>
        <p class="subtitle">نظام إدارة الحلقة القرآنية</p>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST">
            <div class="form-group">
                <label>البريد الإلكتروني</label>
                <input type="email" name="email" required placeholder="أدخل البريد الإلكتروني">
            </div>
            <div class="form-group">
                <label>كلمة المرور</label>
                <input type="password" name="password" required placeholder="أدخل كلمة المرور">
            </div>
            <button type="submit" class="btn">دخول</button>
        </form>
        <div class="links">
            <a href="{{ url_for('admin_login') }}">دخول المشرف</a> | 
            <a href="{{ url_for('student_register') }}">تسجيل جديد</a>
        </div>
    </div>
</body>
</html>
'''

STUDENT_REGISTER_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل طالب جديد</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #2c3e50, #3498db);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .register-container {
            background: rgba(255,255,255,0.95);
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 500px;
        }
        .register-container h1 {
            text-align: center;
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .register-container .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 16px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #333;
            font-weight: 600;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 15px;
            transition: 0.3s;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            border-color: #3498db;
            outline: none;
            box-shadow: 0 0 0 3px rgba(52,152,219,0.1);
        }
        .form-group textarea {
            min-height: 60px;
            resize: vertical;
        }
        .btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #2c3e50, #3498db);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: 0.3s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }
        .links {
            text-align: center;
            margin-top: 20px;
        }
        .links a {
            color: #3498db;
            text-decoration: none;
            font-weight: 600;
        }
        .links a:hover {
            text-decoration: underline;
        }
        .alert {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
        }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .logo {
            text-align: center;
            font-size: 50px;
            margin-bottom: 10px;
        }
        .note {
            font-size: 13px;
            color: #666;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="register-container">
        <div class="logo">📝</div>
        <h1>تسجيل جديد</h1>
        <p class="subtitle">املأ البيانات للتسجيل في الحلقة القرآنية</p>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST">
            <div class="form-group">
                <label>الاسم الكامل</label>
                <input type="text" name="name" required placeholder="أدخل الاسم الكامل">
            </div>
            <div class="form-group">
                <label>البريد الإلكتروني</label>
                <input type="email" name="email" required placeholder="أدخل البريد الإلكتروني">
            </div>
            <div class="form-group">
                <label>كلمة المرور</label>
                <input type="password" name="password" required placeholder="أدخل كلمة المرور (6 أحرف على الأقل)">
            </div>
            <div class="form-group">
                <label>رقم الهاتف</label>
                <input type="text" name="phone" placeholder="أدخل رقم الهاتف">
            </div>
            <div class="form-group">
                <label>هاتف ولي الأمر</label>
                <input type="text" name="parent_phone" placeholder="أدخل هاتف ولي الأمر">
            </div>
            <div class="form-group">
                <label>العنوان</label>
                <textarea name="address" placeholder="أدخل العنوان"></textarea>
            </div>
            <button type="submit" class="btn">تقديم طلب التسجيل</button>
        </form>
        <div class="links">
            <a href="{{ url_for('student_login') }}">لديك حساب؟ سجل دخول</a> | 
            <a href="{{ url_for('admin_login') }}">دخول المشرف</a>
        </div>
    </div>
</body>
</html>
'''

ADMIN_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة التحكم</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .header .user-info { display: flex; align-items: center; gap: 15px; }
        .header .user-info .name { font-weight: 600; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        .btn-lg { padding: 12px 24px; font-size: 16px; }
        
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            text-align: center;
        }
        .card .number {
            font-size: 32px;
            font-weight: 700;
            color: #1a2a6c;
        }
        .card .label {
            color: #666;
            font-size: 14px;
            margin-top: 5px;
        }
        .card .icon { font-size: 30px; margin-bottom: 5px; }
        .card.highlight { background: linear-gradient(135deg, #1a2a6c, #2980b9); color: white; }
        .card.highlight .number { color: white; }
        .card.highlight .label { color: rgba(255,255,255,0.8); }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: right;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }
        table tr:hover { background: #f8f9fa; }
        .status-badge {
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-active { background: #d4edda; color: #155724; }
        .status-inactive { background: #f8d7da; color: #721c24; }
        .status-pending { background: #fff3cd; color: #856404; }
        .status-paid { background: #d4edda; color: #155724; }
        .status-unpaid { background: #f8d7da; color: #721c24; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .gap-5 { gap: 5px; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            .cards { grid-template-columns: repeat(2, 1fr); }
            .nav-links { justify-content: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>🕌 لوحة تحكم المشرف</h1>
                <div style="font-size: 14px; opacity: 0.8;">{{ datetime.now().strftime('%A, %d %B %Y') }}</div>
            </div>
            <div class="user-info">
                <span class="name">{{ admin.name }}</span>
                <a href="{{ url_for('admin_profile') }}" class="btn btn-info btn-sm">👤 الملف</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="cards">
            <div class="card highlight">
                <div class="icon">👨‍🎓</div>
                <div class="number">{{ students_count }}</div>
                <div class="label">إجمالي الطلاب</div>
            </div>
            <div class="card">
                <div class="icon">✅</div>
                <div class="number">{{ active_students }}</div>
                <div class="label">طلاب نشطين</div>
            </div>
            <div class="card">
                <div class="icon">📊</div>
                <div class="number">{{ today_evaluations }}</div>
                <div class="label">تقييمات اليوم</div>
            </div>
            <div class="card">
                <div class="icon">📝</div>
                <div class="number">{{ unsent_evaluations }}</div>
                <div class="label">تقييمات غير مرسلة</div>
            </div>
            <div class="card">
                <div class="icon">📚</div>
                <div class="number">{{ unsent_homework }}</div>
                <div class="label">واجبات غير مرسلة</div>
            </div>
            <div class="card">
                <div class="icon">💬</div>
                <div class="number">{{ messages_count }}</div>
                <div class="label">رسائل غير مقروءة</div>
            </div>
            <div class="card">
                <div class="icon">⏳</div>
                <div class="number">{{ pending_requests }}</div>
                <div class="label">طلبات تسجيل</div>
            </div>
        </div>
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}" class="active">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('registration_requests') }}">📝 طلبات التسجيل</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
            <a href="{{ url_for('admin_profile') }}">👤 الملف</a>
        </div>
        
        <div class="section">
            <div class="flex flex-between">
                <h2>📋 آخر التقييمات</h2>
                <a href="{{ url_for('evaluation') }}" class="btn btn-primary btn-sm">➕ تقييم جديد</a>
            </div>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>الطالب</th>
                            <th>التاريخ</th>
                            <th>الجزء المحفوظ</th>
                            <th>درجة الحفظ</th>
                            <th>المراجعة</th>
                            <th>درجة المراجعة</th>
                            <th>الواجب</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for ev in recent_evaluations %}
                        <tr>
                            <td>{{ ev.student_name }}</td>
                            <td>{{ ev.date }}</td>
                            <td>{{ ev.curr_save or '-' }}</td>
                            <td>{{ ev.score_save or 0 }}</td>
                            <td>{{ ev.curr_rev or '-' }}</td>
                            <td>{{ ev.score_rev or 0 }}</td>
                            <td>{{ ev.homework_score or 0 }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7" class="text-center text-muted">لا توجد تقييمات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

MANAGE_STUDENTS_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>إدارة الطلاب</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        table th {
            background: #f8f9fa;
            padding: 8px 10px;
            text-align: right;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
            white-space: nowrap;
        }
        table td {
            padding: 8px 10px;
            border-bottom: 1px solid #e9ecef;
            vertical-align: middle;
        }
        table tr:hover { background: #f8f9fa; }
        .status-badge {
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .status-active { background: #d4edda; color: #155724; }
        .status-inactive { background: #f8d7da; color: #721c24; }
        .status-pending { background: #fff3cd; color: #856404; }
        .status-paid { background: #d4edda; color: #155724; }
        .status-unpaid { background: #f8d7da; color: #721c24; }
        
        .form-inline { display: inline; }
        .form-inline input, .form-inline select {
            padding: 4px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            width: 100%;
            min-width: 60px;
        }
        .form-inline input:focus, .form-inline select:focus {
            border-color: #3498db;
            outline: none;
        }
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            table { font-size: 11px; }
            table th, table td { padding: 4px 6px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👨‍🎓 إدارة الطلاب</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}" class="active">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('registration_requests') }}">📝 طلبات التسجيل</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
        </div>
        
        <div class="section">
            <div class="flex flex-between">
                <h2>📋 قائمة الطلاب</h2>
                <div class="flex gap-5">
                    <a href="?status=active" class="btn btn-success btn-sm">نشط</a>
                    <a href="?status=inactive" class="btn btn-danger btn-sm">غير نشط</a>
                    <a href="?status=all" class="btn btn-secondary btn-sm">الكل</a>
                </div>
            </div>
            
            <form method="POST" class="mt-10">
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>الاسم</th>
                                <th>البريد</th>
                                <th>الهاتف</th>
                                <th>الترتيب</th>
                                <th>الحالة</th>
                                <th>الدفع</th>
                                <th>إجراءات</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for student in students %}
                            <tr>
                                <td>{{ student.id }}</td>
                                <td>
                                    <input type="text" name="name_{{ student.id }}" value="{{ student.name }}" 
                                           style="width:100%;min-width:80px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>{{ student.email }}</td>
                                <td>
                                    <input type="text" name="phone_{{ student.id }}" value="{{ student.phone or '' }}"
                                           style="width:100%;min-width:80px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>
                                    <input type="number" name="rank_{{ student.id }}" value="{{ student.rank }}"
                                           style="width:50px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;" min="0">
                                </td>
                                <td>
                                    <select name="status_{{ student.id }}" style="padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                        <option value="active" {% if student.status == 'active' %}selected{% endif %}>نشط</option>
                                        <option value="inactive" {% if student.status == 'inactive' %}selected{% endif %}>غير نشط</option>
                                    </select>
                                </td>
                                <td>
                                    <select name="payment_{{ student.id }}" style="padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                        <option value="paid" {% if student.payment_status == 'paid' %}selected{% endif %}>مدفوع</option>
                                        <option value="pending" {% if student.payment_status == 'pending' %}selected{% endif %}>معلق</option>
                                        <option value="unpaid" {% if student.payment_status == 'unpaid' %}selected{% endif %}>غير مدفوع</option>
                                    </select>
                                </td>
                                <td>
                                    <div class="flex gap-5" style="flex-wrap:nowrap;">
                                        <button type="submit" name="update_student" value="{{ student.id }}" 
                                                class="btn btn-primary btn-sm">💾 حفظ</button>
                                        <a href="?delete={{ student.id }}" class="btn btn-danger btn-sm" 
                                           onclick="return confirm('هل أنت متأكد من حذف الطالب؟')">🗑️</a>
                                        <a href="?activate={{ student.id }}" class="btn btn-success btn-sm">🔄</a>
                                    </div>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="8" class="text-center text-muted">لا يوجد طلاب</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
'''

REGISTRATION_REQUESTS_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>طلبات التسجيل</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        .btn-warning { background: #f39c12; color: white; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: right;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }
        table tr:hover { background: #f8f9fa; }
        .status-badge {
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-pending { background: #fff3cd; color: #856404; }
        .status-accepted { background: #d4edda; color: #155724; }
        .status-rejected { background: #f8d7da; color: #721c24; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .mt-10 { margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📝 طلبات التسجيل</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('registration_requests') }}" class="active">📝 طلبات التسجيل</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
        </div>
        
        <div class="section">
            <h2>📋 الطلبات المعلقة</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>الاسم</th>
                            <th>البريد</th>
                            <th>الهاتف</th>
                            <th>هاتف ولي الأمر</th>
                            <th>العنوان</th>
                            <th>تاريخ الطلب</th>
                            <th>الحالة</th>
                            <th>إجراءات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for req in requests %}
                        <tr>
                            <td>{{ req.id }}</td>
                            <td>{{ req.name }}</td>
                            <td>{{ req.email }}</td>
                            <td>{{ req.phone or '-' }}</td>
                            <td>{{ req.parent_phone or '-' }}</td>
                            <td>{{ req.address or '-' }}</td>
                            <td>{{ req.created_at[:10] }}</td>
                            <td>
                                <span class="status-badge status-{{ req.status }}">
                                    {% if req.status == 'pending' %}⏳ معلق
                                    {% elif req.status == 'accepted' %}✅ مقبول
                                    {% else %}❌ مرفوض{% endif %}
                                </span>
                            </td>
                            <td>
                                {% if req.status == 'pending' %}
                                <div class="flex" style="gap:5px;">
                                    <a href="?accept={{ req.id }}" class="btn btn-success btn-sm">✅ قبول</a>
                                    <a href="?reject={{ req.id }}" class="btn btn-danger btn-sm">❌ رفض</a>
                                </div>
                                {% else %}
                                <span class="text-muted">تم المعالجة</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="9" class="text-center text-muted">لا توجد طلبات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

EVALUATION_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>التقييم اليومي</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        table th {
            background: #f8f9fa;
            padding: 8px 10px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
            white-space: nowrap;
        }
        table td {
            padding: 6px 8px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
            vertical-align: middle;
        }
        table tr:hover { background: #f8f9fa; }
        table tr.sent { background: #e8f5e9; }
        
        .form-inline input, .form-inline select, .form-inline textarea {
            padding: 4px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            width: 100%;
            font-family: inherit;
        }
        .form-inline input:focus, .form-inline select:focus, .form-inline textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-inline textarea { min-height: 35px; resize: vertical; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        .badge { 
            padding: 2px 10px; 
            border-radius: 20px; 
            font-size: 11px; 
            font-weight: 600;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            table { font-size: 11px; }
            table th, table td { padding: 4px 4px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📊 التقييم اليومي</h1>
                <div style="font-size: 14px; opacity: 0.8;">{{ datetime.now().strftime('%Y-%m-%d') }}</div>
            </div>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('evaluation') }}" class="active">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
        </div>
        
        <div class="section">
            <div class="flex flex-between">
                <h2>📋 تقييم اليوم ({{ datetime.now().strftime('%Y-%m-%d') }})</h2>
                <div class="flex gap-5">
                    <span class="badge badge-warning">⏳ غير مرسل: {{ unsent_count }}</span>
                    <form method="POST" style="display:inline;">
                        <input type="hidden" name="send_evaluations" value="1">
                        <button type="submit" class="btn btn-success btn-sm" 
                                onclick="return confirm('هل أنت متأكد من إرسال التقييمات؟')">
                            📨 إرسال التقييمات
                        </button>
                    </form>
                </div>
            </div>
            
            <form method="POST">
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>الطالب</th>
                                <th>الجزء المحفوظ</th>
                                <th>درجة الحفظ</th>
                                <th>المراجعة</th>
                                <th>درجة المراجعة</th>
                                <th>درجة الواجب</th>
                                <th>ملاحظات</th>
                                <th>الحالة</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for student in students %}
                            {% set ev = evaluations[student.id|string] if student.id|string in evaluations else None %}
                            <tr class="{% if ev and ev.sent %}sent{% endif %}">
                                <td>{{ student.id }}</td>
                                <td style="text-align:right;white-space:nowrap;">
                                    <strong>{{ student.name }}</strong>
                                    <input type="hidden" name="evaluations[{{ student.id }}][student_id]" value="{{ student.id }}">
                                    <input type="hidden" name="evaluations[{{ student.id }}][date]" value="{{ datetime.now().strftime('%Y-%m-%d') }}">
                                </td>
                                <td>
                                    <input type="text" name="evaluations[{{ student.id }}][curr_save]" 
                                           value="{{ ev.curr_save if ev else '' }}" 
                                           style="width:80px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>
                                    <input type="number" name="evaluations[{{ student.id }}][score_save]" 
                                           value="{{ ev.score_save if ev else 0 }}" 
                                           style="width:60px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;" 
                                           min="0" max="10" step="0.5">
                                </td>
                                <td>
                                    <input type="text" name="evaluations[{{ student.id }}][curr_rev]" 
                                           value="{{ ev.curr_rev if ev else '' }}" 
                                           style="width:80px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>
                                    <input type="number" name="evaluations[{{ student.id }}][score_rev]" 
                                           value="{{ ev.score_rev if ev else 0 }}" 
                                           style="width:60px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;" 
                                           min="0" max="10" step="0.5">
                                </td>
                                <td>
                                    <input type="number" name="evaluations[{{ student.id }}][homework_score]" 
                                           value="{{ ev.homework_score if ev else 0 }}" 
                                           style="width:60px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;" 
                                           min="0" max="10" step="0.5">
                                </td>
                                <td>
                                    <textarea name="evaluations[{{ student.id }}][notes]" 
                                              style="width:100px;min-height:30px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">{{ ev.notes if ev else '' }}</textarea>
                                </td>
                                <td>
                                    {% if ev and ev.sent %}
                                    <span class="badge badge-success">✅ مرسل</span>
                                    {% else %}
                                    <span class="badge badge-warning">⏳ غير مرسل</span>
                                    {% endif %}
                                    {% if ev and ev.id %}
                                    <input type="hidden" name="evaluations[{{ student.id }}][id]" value="{{ ev.id }}">
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="9" class="text-center text-muted">لا يوجد طلاب</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="flex mt-10">
                    <button type="submit" name="save_evaluations" value="1" class="btn btn-primary">💾 حفظ التقييمات</button>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
'''

HOMEWORK_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الواجبات</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        table th {
            background: #f8f9fa;
            padding: 8px 10px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
            white-space: nowrap;
        }
        table td {
            padding: 6px 8px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
            vertical-align: middle;
        }
        table tr:hover { background: #f8f9fa; }
        table tr.sent { background: #e8f5e9; }
        
        .form-inline input, .form-inline textarea {
            padding: 4px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            width: 100%;
            font-family: inherit;
        }
        .form-inline textarea { min-height: 35px; resize: vertical; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        .badge { 
            padding: 2px 10px; 
            border-radius: 20px; 
            font-size: 11px; 
            font-weight: 600;
        }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-warning { background: #fff3cd; color: #856404; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            table { font-size: 11px; }
            table th, table td { padding: 4px 4px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📚 إدارة الواجبات</h1>
                <div style="font-size: 14px; opacity: 0.8;">{{ datetime.now().strftime('%Y-%m-%d') }}</div>
            </div>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}" class="active">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
        </div>
        
        <div class="section">
            <div class="flex flex-between">
                <h2>📋 الواجبات</h2>
                <div class="flex gap-5">
                    <span class="badge badge-warning">⏳ غير مرسل: {{ unsent_count }}</span>
                    <form method="POST" style="display:inline;">
                        <input type="hidden" name="send_homework" value="1">
                        <button type="submit" class="btn btn-success btn-sm" 
                                onclick="return confirm('هل أنت متأكد من إرسال الواجبات؟')">
                            📨 إرسال الواجبات
                        </button>
                    </form>
                </div>
            </div>
            
            <form method="POST">
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>الطالب</th>
                                <th>التاريخ</th>
                                <th>التفاصيل</th>
                                <th>ملاحظات</th>
                                <th>الحالة</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for student in students %}
                            {% set hw = homework_data[student.id|string] if student.id|string in homework_data else None %}
                            <tr class="{% if hw and hw.sent %}sent{% endif %}">
                                <td>{{ student.id }}</td>
                                <td style="text-align:right;white-space:nowrap;">
                                    <strong>{{ student.name }}</strong>
                                    <input type="hidden" name="homework[{{ student.id }}][student_id]" value="{{ student.id }}">
                                    <input type="hidden" name="homework[{{ student.id }}][date]" value="{{ datetime.now().strftime('%Y-%m-%d') }}">
                                </td>
                                <td>{{ datetime.now().strftime('%Y-%m-%d') }}</td>
                                <td>
                                    <input type="text" name="homework[{{ student.id }}][details]" 
                                           value="{{ hw.details if hw else '' }}" 
                                           style="width:150px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>
                                    <input type="text" name="homework[{{ student.id }}][notes]" 
                                           value="{{ hw.notes if hw else '' }}" 
                                           style="width:150px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                                <td>
                                    {% if hw and hw.sent %}
                                    <span class="badge badge-success">✅ مرسل</span>
                                    {% else %}
                                    <span class="badge badge-warning">⏳ غير مرسل</span>
                                    {% endif %}
                                    {% if hw and hw.id %}
                                    <input type="hidden" name="homework[{{ student.id }}][id]" value="{{ hw.id }}">
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="text-center text-muted">لا يوجد طلاب</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="flex mt-10">
                    <button type="submit" name="save_homework" value="1" class="btn btn-primary">💾 حفظ الواجبات</button>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
'''

COMPETITIONS_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>المسابقات</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        .btn-lg { padding: 10px 20px; font-size: 16px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: right;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }
        table tr:hover { background: #f8f9fa; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; margin-bottom: 4px; font-weight: 600; color: #333; }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏆 إدارة المسابقات</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}" class="active">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
        </div>
        
        <div class="section">
            <h2>➕ إضافة مسابقة جديدة</h2>
            <form method="POST">
                <input type="hidden" name="action" value="add_competition">
                <div class="flex" style="align-items: end;">
                    <div class="form-group" style="flex:2;">
                        <label>اسم المسابقة</label>
                        <input type="text" name="name" required placeholder="أدخل اسم المسابقة">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>الدرجة القصوى</label>
                        <input type="number" name="max_grade" value="10" min="1" step="0.5">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>التاريخ</label>
                        <input type="date" name="date" value="{{ datetime.now().strftime('%Y-%m-%d') }}">
                    </div>
                    <div class="form-group" style="flex:2;">
                        <label>الوصف</label>
                        <input type="text" name="description" placeholder="وصف المسابقة">
                    </div>
                    <button type="submit" class="btn btn-success">➕ إضافة</button>
                </div>
            </form>
        </div>
        
        <div class="section">
            <h2>📋 قائمة المسابقات</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>الاسم</th>
                            <th>الوصف</th>
                            <th>الدرجة القصوى</th>
                            <th>التاريخ</th>
                            <th>الحالة</th>
                            <th>إجراءات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for comp in competitions %}
                        <tr>
                            <td>{{ comp.id }}</td>
                            <td><strong>{{ comp.name }}</strong></td>
                            <td>{{ comp.description or '-' }}</td>
                            <td>{{ comp.max_grade }}</td>
                            <td>{{ comp.date }}</td>
                            <td>
                                <span class="badge {% if comp.active %}badge-success{% else %}badge-warning{% endif %}">
                                    {% if comp.active %}✅ نشط{% else %}⏸️ غير نشط{% endif %}
                                </span>
                            </td>
                            <td>
                                <div class="flex gap-5">
                                    <a href="?toggle_active={{ comp.id }}" class="btn btn-warning btn-sm">
                                        {% if comp.active %}⏸️{% else %}▶️{% endif %}
                                    </a>
                                    <a href="{{ url_for('competition_grades') }}?competition_id={{ comp.id }}" class="btn btn-info btn-sm">📊 درجات</a>
                                    <a href="?delete={{ comp.id }}" class="btn btn-danger btn-sm" 
                                       onclick="return confirm('هل أنت متأكد من حذف المسابقة؟')">🗑️</a>
                                </div>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7" class="text-center text-muted">لا توجد مسابقات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

COMPETITION_GRADES_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>درجات المسابقات</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 8px 10px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
            vertical-align: middle;
        }
        table tr:hover { background: #f8f9fa; }
        
        .form-inline input, .form-inline textarea {
            padding: 4px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            width: 100%;
            font-family: inherit;
        }
        .form-inline input:focus, .form-inline textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-inline textarea { min-height: 30px; resize: vertical; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        .badge { 
            padding: 2px 10px; 
            border-radius: 20px; 
            font-size: 12px; 
            font-weight: 600;
        }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            table { font-size: 12px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 درجات المسابقات</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}" class="active">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}">💬 رسائل</a>
        </div>
        
        <div class="section">
            <div class="flex flex-between">
                <h2>📋 درجات المسابقة: <span class="badge badge-info">{{ competition.name }}</span></h2>
                <div class="flex gap-5">
                    <a href="{{ url_for('competitions') }}" class="btn btn-secondary btn-sm">⬅️ رجوع</a>
                </div>
            </div>
            
            <form method="POST">
                <input type="hidden" name="competition_id" value="{{ competition.id }}">
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>الطالب</th>
                                <th>الدرجة</th>
                                <th>ملاحظات</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for student in students %}
                            {% set grade = grades[student.id] if student.id in grades else None %}
                            <tr>
                                <td>{{ student.id }}</td>
                                <td style="text-align:right;"><strong>{{ student.name }}</strong></td>
                                <td>
                                    <input type="number" name="grades[{{ student.id }}]" 
                                           value="{{ grade.grade if grade else 0 }}" 
                                           style="width:70px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;" 
                                           min="0" max="{{ competition.max_grade }}" step="0.5">
                                    <input type="hidden" name="grade_ids[{{ student.id }}]" value="{{ grade.id if grade else '' }}">
                                </td>
                                <td>
                                    <input type="text" name="grade_notes[{{ student.id }}]" 
                                           value="{{ grade.notes if grade else '' }}" 
                                           style="width:150px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="4" class="text-center text-muted">لا يوجد طلاب</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="flex mt-10">
                    <button type="submit" name="save_grades" value="1" class="btn btn-primary">💾 حفظ الدرجات</button>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
'''

MESSAGES_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الرسائل</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #1a2a6c; }
        .nav-links a.active { background: #1a2a6c; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 20px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 10px;
        }
        
        .messages-list {
            max-height: 500px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 10px 0;
        }
        .message-item {
            padding: 10px 15px;
            border-radius: 10px;
            background: #f8f9fa;
            border-right: 4px solid #3498db;
        }
        .message-item.admin {
            border-right-color: #e74c3c;
            background: #fef9f9;
        }
        .message-item.student {
            border-right-color: #2ecc71;
            background: #f9fef9;
        }
        .message-item .sender {
            font-weight: 600;
            color: #333;
            font-size: 14px;
        }
        .message-item .time {
            color: #999;
            font-size: 12px;
            margin-right: 10px;
        }
        .message-item .content {
            margin-top: 5px;
            color: #444;
            font-size: 15px;
            line-height: 1.5;
        }
        .message-item .badge {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            background: #e8f0fe;
            color: #1a2a6c;
        }
        .message-item.unread {
            background: #e8f0fe;
        }
        
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; margin-bottom: 4px; font-weight: 600; color: #333; }
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-group textarea { min-height: 80px; resize: vertical; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💬 الرسائل</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('manage_students') }}">👨‍🎓 إدارة الطلاب</a>
            <a href="{{ url_for('evaluation') }}">📊 تقييم يومي</a>
            <a href="{{ url_for('homework') }}">📚 واجبات</a>
            <a href="{{ url_for('competitions') }}">🏆 مسابقات</a>
            <a href="{{ url_for('competition_grades') }}">📈 درجات المسابقات</a>
            <a href="{{ url_for('messages') }}" class="active">💬 رسائل</a>
        </div>
        
        <div class="section">
            <h2>📨 كتابة رسالة جديدة</h2>
            <form method="POST">
                <input type="hidden" name="send_message" value="1">
                <div class="flex">
                    <div class="form-group" style="flex:1;">
                        <label>الطالب</label>
                        <select name="receiver_id" required>
                            <option value="">اختر الطالب</option>
                            {% for student in students %}
                            <option value="{{ student.id }}">{{ student.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group" style="flex:2;">
                        <label>الرسالة</label>
                        <input type="text" name="message" required placeholder="أدخل نص الرسالة">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top:22px;">📨 إرسال</button>
                </div>
            </form>
        </div>
        
        <div class="section">
            <h2>📋 محادثات الطلاب</h2>
            <div class="flex gap-5 mb-10">
                {% for s in students %}
                <a href="?student_id={{ s.id }}" class="btn btn-secondary btn-sm">
                    {{ s.name }}
                </a>
                {% endfor %}
            </div>
            
            {% if selected_student %}
            <h3 style="margin:10px 0;color:#1a2a6c;">🗨️ محادثة مع: {{ selected_student.name }}</h3>
            <div class="messages-list">
                {% for msg in messages %}
                <div class="message-item {% if msg.sender_type == 'admin' %}admin{% else %}student{% endif %} {% if not msg.is_read and msg.sender_type != 'admin' %}unread{% endif %}">
                    <div class="sender">
                        {% if msg.sender_type == 'admin' %}
                        👤 المشرف
                        {% else %}
                        👨‍🎓 {{ msg.sender_name or 'طالب' }}
                        {% endif %}
                        <span class="time">{{ msg.created_at[11:16] if msg.created_at else '' }}</span>
                        {% if not msg.is_read and msg.sender_type != 'admin' %}
                        <span class="badge">جديد</span>
                        {% endif %}
                    </div>
                    <div class="content">{{ msg.message }}</div>
                </div>
                {% else %}
                <div class="text-center text-muted">لا توجد رسائل</div>
                {% endfor %}
            </div>
            {% else %}
            <div class="text-center text-muted">اختر طالباً لعرض المحادثة</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''

STUDENT_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة الطالب</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .header .user-info { display: flex; align-items: center; gap: 15px; }
        .header .user-info .name { font-weight: 600; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        .card {
            background: white;
            padding: 15px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            text-align: center;
        }
        .card .number {
            font-size: 28px;
            font-weight: 700;
            color: #134e5e;
        }
        .card .label {
            color: #666;
            font-size: 13px;
            margin-top: 3px;
        }
        .card .icon { font-size: 28px; margin-bottom: 3px; }
        .card.highlight { background: linear-gradient(135deg, #134e5e, #71b280); color: white; }
        .card.highlight .number { color: white; }
        .card.highlight .label { color: rgba(255,255,255,0.85); }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        table th {
            background: #f8f9fa;
            padding: 8px 10px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 8px 10px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
        }
        table tr:hover { background: #f8f9fa; }
        .status-badge {
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .status-done { background: #d4edda; color: #155724; }
        .status-pending { background: #fff3cd; color: #856404; }
        .status-missed { background: #f8d7da; color: #721c24; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            .cards { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📖 لوحة الطالب</h1>
                <div style="font-size: 14px; opacity: 0.8;">{{ datetime.now().strftime('%A, %d %B %Y') }}</div>
            </div>
            <div class="user-info">
                <span class="name">{{ student.name }}</span>
                <a href="{{ url_for('student_profile') }}" class="btn btn-info btn-sm">👤 الملف</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}" class="active">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}">💬 رسائلي</a>
            <a href="{{ url_for('student_profile') }}">👤 ملفي</a>
        </div>
        
        <div class="cards">
            <div class="card highlight">
                <div class="icon">⭐</div>
                <div class="number">{{ total_grade }}</div>
                <div class="label">مجموع الدرجات</div>
            </div>
            <div class="card">
                <div class="icon">📊</div>
                <div class="number">{{ avg_score }}</div>
                <div class="label">متوسط الدرجات</div>
            </div>
            <div class="card">
                <div class="icon">📚</div>
                <div class="number">{{ homework_count }}</div>
                <div class="label">الواجبات</div>
            </div>
            <div class="card">
                <div class="icon">🏆</div>
                <div class="number">{{ competitions_count }}</div>
                <div class="label">المسابقات</div>
            </div>
            <div class="card">
                <div class="icon">💬</div>
                <div class="number">{{ messages_count }}</div>
                <div class="label">رسائل غير مقروءة</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📋 تقييم اليوم</h2>
            {% if today_evaluation %}
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;">
                <div><strong>الجزء المحفوظ:</strong> {{ today_evaluation.curr_save or '-' }}</div>
                <div><strong>درجة الحفظ:</strong> {{ today_evaluation.score_save or 0 }}</div>
                <div><strong>المراجعة:</strong> {{ today_evaluation.curr_rev or '-' }}</div>
                <div><strong>درجة المراجعة:</strong> {{ today_evaluation.score_rev or 0 }}</div>
                <div><strong>درجة الواجب:</strong> {{ today_evaluation.homework_score or 0 }}</div>
                <div><strong>ملاحظات:</strong> {{ today_evaluation.notes or '-' }}</div>
            </div>
            {% else %}
            <div class="text-center text-muted">لا يوجد تقييم لليوم</div>
            {% endif %}
        </div>
        
        <div class="section">
            <h2>📚 آخر الواجبات</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>التاريخ</th>
                            <th>التفاصيل</th>
                            <th>ملاحظات</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for hw in recent_homework %}
                        <tr>
                            <td>{{ hw.date }}</td>
                            <td>{{ hw.details or '-' }}</td>
                            <td>{{ hw.notes or '-' }}</td>
                            <td>
                                <span class="status-badge {% if hw.sent %}status-done{% else %}status-pending{% endif %}">
                                    {% if hw.sent %}✅ مرسل{% else %}⏳ غير مرسل{% endif %}
                                </span>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" class="text-center text-muted">لا توجد واجبات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

STUDENT_HOMEWORK_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>واجباتي</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-info { background: #1abc9c; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
        }
        table tr:hover { background: #f8f9fa; }
        .status-badge {
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-done { background: #d4edda; color: #155724; }
        .status-pending { background: #fff3cd; color: #856404; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .mt-10 { margin-top: 10px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📚 واجباتي</h1>
            <div>
                <a href="{{ url_for('student_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}" class="active">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}">💬 رسائلي</a>
        </div>
        
        <div class="section">
            <h2>📋 قائمة الواجبات</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>التاريخ</th>
                            <th>التفاصيل</th>
                            <th>ملاحظات</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for hw in homework %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td>{{ hw.date }}</td>
                            <td>{{ hw.details or '-' }}</td>
                            <td>{{ hw.notes or '-' }}</td>
                            <td>
                                <span class="status-badge {% if hw.sent %}status-done{% else %}status-pending{% endif %}">
                                    {% if hw.sent %}✅ مرسل{% else %}⏳ غير مرسل{% endif %}
                                </span>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" class="text-center text-muted">لا توجد واجبات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

STUDENT_REPORT_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تقريري</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-info { background: #1abc9c; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-card .number {
            font-size: 24px;
            font-weight: 700;
            color: #134e5e;
        }
        .stat-card .label {
            color: #666;
            font-size: 13px;
            margin-top: 3px;
        }
        
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        table th {
            background: #f8f9fa;
            padding: 8px 10px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 8px 10px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
        }
        table tr:hover { background: #f8f9fa; }
        
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .mt-10 { margin-top: 10px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 تقريري</h1>
            <div>
                <a href="{{ url_for('student_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}" class="active">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}">💬 رسائلي</a>
        </div>
        
        <div class="section">
            <h2>📈 إحصائيات عامة</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="number">{{ total_evaluations }}</div>
                    <div class="label">عدد التقييمات</div>
                </div>
                <div class="stat-card">
                    <div class="number">{{ avg_save }}</div>
                    <div class="label">متوسط درجة الحفظ</div>
                </div>
                <div class="stat-card">
                    <div class="number">{{ avg_rev }}</div>
                    <div class="label">متوسط درجة المراجعة</div>
                </div>
                <div class="stat-card">
                    <div class="number">{{ avg_homework }}</div>
                    <div class="label">متوسط درجة الواجب</div>
                </div>
                <div class="stat-card">
                    <div class="number">{{ total_score }}</div>
                    <div class="label">مجموع الدرجات</div>
                </div>
                <div class="stat-card">
                    <div class="number">{{ competitions_grade or 0 }}</div>
                    <div class="label">درجات المسابقات</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📋 تفاصيل التقييمات</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>التاريخ</th>
                            <th>الجزء المحفوظ</th>
                            <th>درجة الحفظ</th>
                            <th>المراجعة</th>
                            <th>درجة المراجعة</th>
                            <th>درجة الواجب</th>
                            <th>ملاحظات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for ev in evaluations %}
                        <tr>
                            <td>{{ ev.date }}</td>
                            <td>{{ ev.curr_save or '-' }}</td>
                            <td>{{ ev.score_save or 0 }}</td>
                            <td>{{ ev.curr_rev or '-' }}</td>
                            <td>{{ ev.score_rev or 0 }}</td>
                            <td>{{ ev.homework_score or 0 }}</td>
                            <td>{{ ev.notes or '-' }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7" class="text-center text-muted">لا توجد تقييمات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

STUDENT_COMPETITIONS_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مسابقاتي</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-info { background: #1abc9c; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        .table-responsive { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        table th {
            background: #f8f9fa;
            padding: 10px 12px;
            text-align: center;
            border-bottom: 2px solid #dee2e6;
            font-weight: 600;
            color: #333;
        }
        table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
            text-align: center;
        }
        table tr:hover { background: #f8f9fa; }
        
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .mt-10 { margin-top: 10px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏆 مسابقاتي</h1>
            <div>
                <a href="{{ url_for('student_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}" class="active">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}">💬 رسائلي</a>
        </div>
        
        <div class="section">
            <h2>📋 قائمة المسابقات</h2>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>المسابقة</th>
                            <th>التاريخ</th>
                            <th>الدرجة القصوى</th>
                            <th>درجتي</th>
                            <th>ملاحظات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for comp in competitions %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td><strong>{{ comp.name }}</strong></td>
                            <td>{{ comp.date }}</td>
                            <td>{{ comp.max_grade }}</td>
                            <td>
                                {% set grade = grades[comp.id] if comp.id in grades else None %}
                                {% if grade %}
                                <strong style="color:#134e5e;">{{ grade.grade or 0 }}</strong>
                                {% else %}
                                <span class="text-muted">-</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if grade %}
                                {{ grade.notes or '-' }}
                                {% else %}
                                <span class="text-muted">-</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" class="text-center text-muted">لا توجد مسابقات</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

STUDENT_MESSAGES_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>رسائلي</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .section {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 12px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        
        .messages-list {
            max-height: 400px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 10px 0;
        }
        .message-item {
            padding: 10px 15px;
            border-radius: 10px;
            background: #f8f9fa;
            border-right: 4px solid #2ecc71;
        }
        .message-item.admin {
            border-right-color: #e74c3c;
            background: #fef9f9;
        }
        .message-item.self {
            border-right-color: #3498db;
            background: #e8f0fe;
        }
        .message-item .sender {
            font-weight: 600;
            color: #333;
            font-size: 14px;
        }
        .message-item .time {
            color: #999;
            font-size: 12px;
            margin-right: 10px;
        }
        .message-item .content {
            margin-top: 5px;
            color: #444;
            font-size: 15px;
            line-height: 1.5;
        }
        .message-item .badge {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            background: #e8f0fe;
            color: #134e5e;
        }
        .message-item.unread {
            background: #e8f0fe;
        }
        
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; margin-bottom: 4px; font-weight: 600; color: #333; }
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-group textarea { min-height: 80px; resize: vertical; }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .mb-10 { margin-bottom: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        .gap-5 { gap: 5px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💬 رسائلي</h1>
            <div>
                <a href="{{ url_for('student_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}" class="active">💬 رسائلي</a>
        </div>
        
        <div class="section">
            <h2>📨 كتابة رسالة جديدة</h2>
            <form method="POST">
                <input type="hidden" name="send_message" value="1">
                <div class="flex">
                    <div class="form-group" style="flex:1;">
                        <label>إلى</label>
                        <select name="receiver_type" required onchange="toggleReceiver(this)">
                            <option value="admin">المشرف</option>
                            <option value="student">طالب آخر</option>
                        </select>
                    </div>
                    <div class="form-group" style="flex:1;" id="student_select">
                        <label>الطالب</label>
                        <select name="receiver_id">
                            <option value="">اختر الطالب</option>
                            {% for s in other_students %}
                            <option value="{{ s.id }}">{{ s.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group" style="flex:2;">
                        <label>الرسالة</label>
                        <input type="text" name="message" required placeholder="أدخل نص الرسالة">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top:22px;">📨 إرسال</button>
                </div>
            </form>
        </div>
        
        <div class="section">
            <h2>📋 محادثاتي</h2>
            <div class="flex gap-5 mb-10">
                <a href="?type=admin" class="btn btn-secondary btn-sm">👤 المشرف</a>
                {% for s in other_students %}
                <a href="?type=student&id={{ s.id }}" class="btn btn-secondary btn-sm">
                    👨‍🎓 {{ s.name }}
                </a>
                {% endfor %}
            </div>
            
            {% if selected_other %}
            <h3 style="margin:10px 0;color:#134e5e;">🗨️ محادثة مع: 
                {% if selected_other.type == 'admin' %}المشرف{% else %}{{ selected_other.name }}{% endif %}
            </h3>
            <div class="messages-list">
                {% for msg in messages %}
                <div class="message-item {% if msg.sender_type == 'admin' %}admin{% elif msg.sender_id == student_id %}self{% endif %} {% if not msg.is_read and msg.sender_id != student_id %}unread{% endif %}">
                    <div class="sender">
                        {% if msg.sender_type == 'admin' %}
                        👤 المشرف
                        {% elif msg.sender_id == student_id %}
                        أنت
                        {% else %}
                        👨‍🎓 {{ msg.sender_name or 'طالب' }}
                        {% endif %}
                        <span class="time">{{ msg.created_at[11:16] if msg.created_at else '' }}</span>
                        {% if not msg.is_read and msg.sender_id != student_id %}
                        <span class="badge">جديد</span>
                        {% endif %}
                    </div>
                    <div class="content">{{ msg.message }}</div>
                </div>
                {% else %}
                <div class="text-center text-muted">لا توجد رسائل</div>
                {% endfor %}
            </div>
            {% else %}
            <div class="text-center text-muted">اختر محادثة لعرضها</div>
            {% endif %}
        </div>
    </div>
    
    <script>
    function toggleReceiver(select) {
        var studentSelect = document.getElementById('student_select');
        if (select.value === 'admin') {
            studentSelect.style.display = 'none';
            document.querySelector('select[name="receiver_id"]').value = '';
        } else {
            studentSelect.style.display = 'block';
        }
    }
    // تهيئة
    toggleReceiver(document.querySelector('select[name="receiver_type"]'));
    </script>
</body>
</html>
'''

STUDENT_PROFILE_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ملفي الشخصي</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 600px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #134e5e, #71b280);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .nav-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
            background: white;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .nav-links a {
            color: #333;
            text-decoration: none;
            padding: 5px 15px;
            border-radius: 6px;
            transition: 0.3s;
            font-weight: 500;
        }
        .nav-links a:hover { background: #e8f0fe; color: #134e5e; }
        .nav-links a.active { background: #134e5e; color: white; }
        
        .section {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #134e5e;
            font-size: 18px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 4px; font-weight: 600; color: #333; }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-group textarea { min-height: 60px; resize: vertical; }
        .form-group .readonly {
            background: #f8f9fa;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            color: #666;
        }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        .text-center { text-align: center; }
        .text-muted { color: #6c757d; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👤 ملفي الشخصي</h1>
            <div>
                <a href="{{ url_for('student_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <a href="{{ url_for('student_dashboard') }}">📊 الرئيسية</a>
            <a href="{{ url_for('student_homework') }}">📚 واجباتي</a>
            <a href="{{ url_for('student_report') }}">📊 تقريري</a>
            <a href="{{ url_for('student_competitions') }}">🏆 مسابقاتي</a>
            <a href="{{ url_for('student_messages') }}">💬 رسائلي</a>
            <a href="{{ url_for('student_profile') }}" class="active">👤 ملفي</a>
        </div>
        
        <div class="section">
            <h2>📋 معلوماتي الشخصية</h2>
            <form method="POST">
                <div class="form-group">
                    <label>الاسم الكامل</label>
                    <input type="text" name="name" value="{{ student.name }}" required>
                </div>
                <div class="form-group">
                    <label>البريد الإلكتروني</label>
                    <div class="readonly">{{ student.email }}</div>
                    <input type="hidden" name="email" value="{{ student.email }}">
                </div>
                <div class="form-group">
                    <label>رقم الهاتف</label>
                    <input type="text" name="phone" value="{{ student.phone or '' }}">
                </div>
                <div class="form-group">
                    <label>هاتف ولي الأمر</label>
                    <input type="text" name="parent_phone" value="{{ student.parent_phone or '' }}">
                </div>
                <div class="form-group">
                    <label>العنوان</label>
                    <textarea name="address">{{ student.address or '' }}</textarea>
                </div>
                <div class="form-group">
                    <label>كلمة المرور الجديدة (اتركها فارغة إذا لم ترغب في التغيير)</label>
                    <input type="password" name="password" placeholder="أدخل كلمة المرور الجديدة">
                </div>
                <button type="submit" class="btn btn-primary">💾 تحديث الملف</button>
            </form>
        </div>
        
        <div class="section">
            <h2>📊 معلومات إضافية</h2>
            <div class="form-group">
                <label>الترتيب</label>
                <div class="readonly">{{ student.rank or 0 }}</div>
            </div>
            <div class="form-group">
                <label>حالة الدفع</label>
                <div class="readonly">
                    <span class="status-badge {% if student.payment_status == 'paid' %}status-paid{% else %}status-unpaid{% endif %}">
                        {{ 'مدفوع' if student.payment_status == 'paid' else 'غير مدفوع' }}
                    </span>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''

ADMIN_PROFILE_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <link rel="icon" href="/static/2.png" type="image/png">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ملف المشرف</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }
        .container { max-width: 600px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #1a2a6c, #2980b9);
            color: white;
            padding: 20px 30px;
            border-radius: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 24px; }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.3s;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .btn-primary { background: #3498db; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-info { background: #1abc9c; color: white; }
        .btn-sm { padding: 5px 12px; font-size: 12px; }
        
        .section {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 20px;
        }
        .section h2 {
            color: #1a2a6c;
            font-size: 18px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e8f0fe;
            padding-bottom: 8px;
        }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 4px; font-weight: 600; color: #333; }
        .form-group input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
        }
        .form-group input:focus {
            border-color: #3498db;
            outline: none;
        }
        .form-group .readonly {
            background: #f8f9fa;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            color: #666;
        }
        
        .alert {
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        
        .flex { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .flex-between { justify-content: space-between; }
        .mt-10 { margin-top: 10px; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👤 ملف المشرف</h1>
            <div>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-info btn-sm">📊 الرئيسية</a>
                <a href="{{ url_for('logout') }}" class="btn btn-danger btn-sm">🚪 خروج</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="section">
            <h2>📋 معلوماتي</h2>
            <form method="POST">
                <div class="form-group">
                    <label>الاسم</label>
                    <input type="text" name="name" value="{{ admin.name }}" required>
                </div>
                <div class="form-group">
                    <label>اسم المستخدم</label>
                    <div class="readonly">{{ admin.username }}</div>
                    <input type="hidden" name="username" value="{{ admin.username }}">
                </div>
                <div class="form-group">
                    <label>البريد الإلكتروني</label>
                    <input type="email" name="email" value="{{ admin.email or '' }}">
                </div>
                <div class="form-group">
                    <label>رقم الهاتف</label>
                    <input type="text" name="phone" value="{{ admin.phone or '' }}">
                </div>
                <div class="form-group">
                    <label>كلمة المرور الجديدة (اتركها فارغة إذا لم ترغب في التغيير)</label>
                    <input type="password" name="password" placeholder="أدخل كلمة المرور الجديدة">
                </div>
                <button type="submit" class="btn btn-primary">💾 تحديث الملف</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

# === Routes ===

@app.route('/')
def home():
    """الصفحة الرئيسية"""
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))
    elif 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """دخول المشرف"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('الرجاء إدخال اسم المستخدم وكلمة المرور', 'danger')
            return render_template_string(ADMIN_LOGIN_HTML)

        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT * FROM admins WHERE username = %s",
                (username,)
            )
            admin = cur.fetchone()
            cur.close()

            if admin and check_password_hash(admin['password'], password):
                session['admin_id'] = admin['id']
                session['admin_username'] = admin['username']
                session['admin_name'] = admin['name']
                session['user_type'] = 'admin'
                flash(f'مرحباً {admin["name"]}', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
        finally:
            conn.close()

    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    """دخول الطالب"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('الرجاء إدخال البريد الإلكتروني وكلمة المرور', 'danger')
            return render_template_string(STUDENT_LOGIN_HTML)

        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT * FROM students WHERE email = %s AND status = 'active'",
                (email,)
            )
            student = cur.fetchone()
            cur.close()

            if student and check_password_hash(student['password'], password):
                session['student_id'] = student['id']
                session['student_name'] = student['name']
                session['student_email'] = student['email']
                session['user_type'] = 'student'
                flash(f'مرحباً {student["name"]}', 'success')
                return redirect(url_for('student_dashboard'))
            else:
                flash('البريد الإلكتروني أو كلمة المرور غير صحيحة', 'danger')
        finally:
            conn.close()

    return render_template_string(STUDENT_LOGIN_HTML)

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    """تسجيل طالب جديد"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        address = request.form.get('address', '').strip()

        if not name or not email or not password:
            flash('الرجاء ملء جميع الحقول المطلوبة', 'danger')
            return render_template_string(STUDENT_REGISTER_HTML)

        if len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل', 'danger')
            return render_template_string(STUDENT_REGISTER_HTML)

        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # التحقق من وجود طالب بنفس البريد
            cur.execute(
                "SELECT id FROM students WHERE email = %s",
                (email,)
            )
            existing = cur.fetchone()

            if existing:
                cur.close()
                flash('هذا البريد الإلكتروني مسجل بالفعل', 'danger')
                return render_template_string(STUDENT_REGISTER_HTML)

            # التحقق من وجود طلب سابق
            cur.execute(
                "SELECT id, status FROM registration_requests WHERE email = %s",
                (email,)
            )
            existing_req = cur.fetchone()

            if existing_req:
                if existing_req['status'] == 'pending':
                    cur.close()
                    flash('لديك طلب تسجيل قيد الانتظار، يرجى الانتظار للموافقة', 'info')
                elif existing_req['status'] == 'accepted':
                    cur.close()
                    flash('تم قبول طلبك السابق، يمكنك تسجيل الدخول', 'info')
                else:
                    # مرفوض، يمكن إعادة التقديم
                    cur2 = conn.cursor()
                    cur2.execute(
                        "UPDATE registration_requests SET name = %s, password = %s, phone = %s, parent_phone = %s, address = %s, status = 'pending', created_at = CURRENT_TIMESTAMP WHERE email = %s",
                        (name, generate_password_hash(password), phone, parent_phone, address, email)
                    )
                    cur2.close()
                    conn.commit()
                    flash('تم تحديث طلبك وإعادة إرساله، يرجى انتظار الموافقة', 'success')
                return render_template_string(STUDENT_REGISTER_HTML)

            # إنشاء طلب جديد
            cur2 = conn.cursor()
            cur2.execute("""
                INSERT INTO registration_requests (name, email, password, phone, parent_phone, address, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """, (name, email, generate_password_hash(password), phone, parent_phone, address))
            cur2.close()
            conn.commit()

            flash('تم إرسال طلب التسجيل بنجاح، سيتم مراجعة طلبك قريباً', 'success')
            return redirect(url_for('student_login'))
        finally:
            conn.close()

    return render_template_string(STUDENT_REGISTER_HTML)

@app.route('/logout')
def logout():
    """تسجيل الخروج"""
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('home'))


# === Routes للمشرف ===

@app.route('/admin/dashboard')
def admin_dashboard():
    """لوحة تحكم المشرف"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']
    today = date.today().isoformat()

    conn = get_db()
    try:
        # إحصائيات
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as total FROM students")
        students_count = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) as total FROM students WHERE status = 'active'")
        active_students = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(DISTINCT student_id) as total FROM daily_evaluations WHERE date = %s",
            (today,)
        )
        today_evaluations = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM daily_evaluations WHERE date = %s AND sent = FALSE",
            (today,)
        )
        unsent_evaluations = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM homework WHERE sent = FALSE"
        )
        unsent_homework = cur.fetchone()['total']

        # الرسائل غير المقروءة من الطلاب للمشرف
        cur.execute(
            "SELECT COUNT(*) as total FROM messages WHERE receiver_id = %s AND sender_type = 'student' AND is_read = FALSE",
            (admin_id,)
        )
        messages_count = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM registration_requests WHERE status = 'pending'"
        )
        pending_requests = cur.fetchone()['total']

        # آخر التقييمات
        cur.execute("""
            SELECT e.*, s.name as student_name 
            FROM daily_evaluations e
            JOIN students s ON e.student_id = s.id
            ORDER BY e.date DESC, e.id DESC
            LIMIT 10
        """)
        recent_evaluations = cur.fetchall()

        # معلومات المشرف
        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()
        cur.close()

        return render_template_string(
            ADMIN_DASHBOARD_HTML,
            admin=admin,
            students_count=students_count,
            active_students=active_students,
            today_evaluations=today_evaluations,
            unsent_evaluations=unsent_evaluations,
            unsent_homework=unsent_homework,
            messages_count=messages_count,
            pending_requests=pending_requests,
            recent_evaluations=recent_evaluations,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/students', methods=['GET', 'POST'])
def manage_students():
    """إدارة الطلاب"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    # معالجة GET actions
    delete_id = request.args.get('delete')
    if delete_id:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM students WHERE id = %s", (delete_id,))
            conn.commit()
            cur.close()
            flash('تم حذف الطالب بنجاح', 'success')
        except Exception as e:
            flash(f'خطأ في حذف الطالب: {str(e)}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('manage_students'))

    activate_id = request.args.get('activate')
    if activate_id:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT status FROM students WHERE id = %s", (activate_id,))
            student = cur.fetchone()
            cur.close()
            if student:
                new_status = 'inactive' if student['status'] == 'active' else 'active'
                cur2 = conn.cursor()
                cur2.execute("UPDATE students SET status = %s WHERE id = %s", (new_status, activate_id))
                conn.commit()
                cur2.close()
                flash(f'تم تغيير حالة الطالب إلى {"نشط" if new_status == "active" else "غير نشط"}', 'success')
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('manage_students'))

    # معالجة POST (تحديث)
    if request.method == 'POST':
        student_id = request.form.get('update_student')
        if student_id:
            student_id = int(student_id)
            name = request.form.get(f'name_{student_id}', '').strip()
            phone = request.form.get(f'phone_{student_id}', '').strip()
            rank = request.form.get(f'rank_{student_id}', 0)
            status = request.form.get(f'status_{student_id}', 'active')
            payment = request.form.get(f'payment_{student_id}', 'pending')

            if not name:
                flash('الاسم مطلوب', 'danger')
                return redirect(url_for('manage_students'))

            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE students 
                    SET name = %s, phone = %s, rank = %s, status = %s, payment_status = %s
                    WHERE id = %s
                """, (name, phone, rank, status, payment, student_id))
                conn.commit()
                cur.close()
                flash('تم تحديث بيانات الطالب بنجاح', 'success')
            except Exception as e:
                flash(f'خطأ في التحديث: {str(e)}', 'danger')
            finally:
                conn.close()
            return redirect(url_for('manage_students'))

    # عرض القائمة
    status_filter = request.args.get('status', 'all')
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if status_filter == 'all':
            cur.execute("SELECT * FROM students ORDER BY rank ASC, name ASC")
        else:
            cur.execute(
                "SELECT * FROM students WHERE status = %s ORDER BY rank ASC, name ASC",
                (status_filter,)
            )
        students = cur.fetchall()

        # معلومات المشرف للقائمة
        cur.execute("SELECT * FROM admins WHERE id = %s", (session['admin_id'],))
        admin = cur.fetchone()
        cur.close()

        return render_template_string(
            MANAGE_STUDENTS_HTML,
            students=students,
            admin=admin,
            status_filter=status_filter,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/requests')
def registration_requests():
    """طلبات التسجيل"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    # معالجة القبول والرفض
    accept_id = request.args.get('accept')
    if accept_id:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # جلب الطلب
            cur.execute(
                "SELECT * FROM registration_requests WHERE id = %s AND status = 'pending'",
                (accept_id,)
            )
            req = cur.fetchone()

            if req:
                # حساب الترتيب
                cur.execute(
                    "SELECT COUNT(*) as total FROM students WHERE status = 'active'"
                )
                rank_result = cur.fetchone()
                rank = rank_result['total'] + 1

                # إضافة الطالب
                cur2 = conn.cursor()
                cur2.execute("""
                    INSERT INTO students (name, email, password, phone, parent_phone, address, rank, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
                """, (req['name'], req['email'], req['password'], req['phone'], 
                      req['parent_phone'], req['address'], rank))

                # تحديث حالة الطلب
                cur2.execute(
                    "UPDATE registration_requests SET status = 'accepted' WHERE id = %s",
                    (accept_id,)
                )
                conn.commit()
                cur2.close()
                flash('تم قبول الطلب وإضافة الطالب بنجاح', 'success')
            else:
                flash('الطلب غير موجود أو تمت معالجته مسبقاً', 'warning')
            cur.close()
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('registration_requests'))

    reject_id = request.args.get('reject')
    if reject_id:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE registration_requests SET status = 'rejected' WHERE id = %s",
                (reject_id,)
            )
            conn.commit()
            cur.close()
            flash('تم رفض الطلب', 'success')
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('registration_requests'))

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM registration_requests ORDER BY created_at DESC"
        )
        requests = cur.fetchall()

        cur.execute("SELECT * FROM admins WHERE id = %s", (session['admin_id'],))
        admin = cur.fetchone()
        cur.close()

        return render_template_string(
            REGISTRATION_REQUESTS_HTML,
            requests=requests,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()


@app.route('/admin/evaluation', methods=['GET', 'POST'])
def evaluation():
    """التقييم اليومي"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']
    today = date.today().isoformat()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM students WHERE status = 'active' ORDER BY rank ASC, name ASC"
        )
        students = cur.fetchall()

        # جلب التقييمات الحالية لليوم
        cur.execute(
            "SELECT * FROM daily_evaluations WHERE date = %s",
            (today,)
        )
        existing = cur.fetchall()

        evaluations = {}
        for ev in existing:
            evaluations[str(ev['student_id'])] = dict(ev)

        # عدد التقييمات غير المرسلة
        cur.execute(
            "SELECT COUNT(*) as total FROM daily_evaluations WHERE date = %s AND sent = FALSE",
            (today,)
        )
        unsent_count = cur.fetchone()['total']

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        # معالجة POST
        if request.method == 'POST':
            # حفظ التقييمات
            if request.form.get('save_evaluations'):
                ev_data = parse_nested_form('evaluations')

                for student_id_str, fields in ev_data.items():
                    student_id = int(student_id_str)
                    curr_save = fields.get('curr_save', '').strip()
                    score_save = float(fields.get('score_save', 0) or 0)
                    curr_rev = fields.get('curr_rev', '').strip()
                    score_rev = float(fields.get('score_rev', 0) or 0)
                    homework_score = float(fields.get('homework_score', 0) or 0)
                    notes = fields.get('notes', '').strip()
                    ev_id = fields.get('id')

                    cur2 = conn.cursor()
                    if ev_id:
                        # تحديث
                        cur2.execute("""
                            UPDATE daily_evaluations 
                            SET curr_save = %s, score_save = %s, curr_rev = %s, score_rev = %s, 
                                homework_score = %s, notes = %s, sent = FALSE
                            WHERE id = %s AND student_id = %s
                        """, (curr_save, score_save, curr_rev, score_rev, homework_score, notes, ev_id, student_id))
                    else:
                        # إدراج جديد
                        cur2.execute("""
                            INSERT INTO daily_evaluations (student_id, date, curr_save, score_save, curr_rev, score_rev, homework_score, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (student_id, today, curr_save, score_save, curr_rev, score_rev, homework_score, notes))
                    cur2.close()

                conn.commit()
                flash('تم حفظ التقييمات بنجاح', 'success')
                cur.close()
                return redirect(url_for('evaluation'))

            # إرسال التقييمات
            elif request.form.get('send_evaluations'):
                cur.execute("""
                    SELECT e.*, s.name as student_name 
                    FROM daily_evaluations e
                    JOIN students s ON e.student_id = s.id
                    WHERE e.date = %s AND e.sent = FALSE
                    AND (e.curr_save IS NOT NULL AND e.curr_save != '' 
                         OR e.curr_rev IS NOT NULL AND e.curr_rev != '' 
                         OR e.homework_score > 0 
                         OR e.notes IS NOT NULL AND e.notes != '')
                """, (today,))
                unsent = cur.fetchall()

                sent_count = 0
                for ev in unsent:
                    # إنشاء رسالة
                    msg_lines = []
                    msg_lines.append(f"📊 تقييم اليوم {today}")
                    msg_lines.append("")
                    msg_lines.append(f"👨‍🎓 {ev['student_name']}")
                    if ev['curr_save']:
                        msg_lines.append(f"📖 الجزء المحفوظ: {ev['curr_save']}")
                    if ev['score_save']:
                        msg_lines.append(f"⭐ درجة الحفظ: {ev['score_save']}")
                    if ev['curr_rev']:
                        msg_lines.append(f"📖 المراجعة: {ev['curr_rev']}")
                    if ev['score_rev']:
                        msg_lines.append(f"⭐ درجة المراجعة: {ev['score_rev']}")
                    if ev['homework_score']:
                        msg_lines.append(f"📝 درجة الواجب: {ev['homework_score']}")
                    if ev['notes']:
                        msg_lines.append(f"📝 ملاحظات: {ev['notes']}")

                    message = "\n".join(msg_lines)

                    # إرسال الرسالة
                    cur2 = conn.cursor()
                    cur2.execute("""
                        INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                        VALUES (%s, 'admin', %s, %s)
                    """, (admin_id, ev['student_id'], message))

                    # تحديث حالة التقييم
                    cur2.execute(
                        "UPDATE daily_evaluations SET sent = TRUE WHERE id = %s",
                        (ev['id'],)
                    )
                    cur2.close()
                    sent_count += 1

                conn.commit()
                flash(f'تم إرسال {sent_count} تقييم بنجاح', 'success')
                cur.close()
                return redirect(url_for('evaluation'))

        cur.close()
        return render_template_string(
            EVALUATION_HTML,
            students=students,
            evaluations=evaluations,
            unsent_count=unsent_count,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/homework', methods=['GET', 'POST'])
def homework():
    """إدارة الواجبات"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']
    today = date.today().isoformat()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM students WHERE status = 'active' ORDER BY rank ASC, name ASC"
        )
        students = cur.fetchall()

        # جلب الواجبات الحالية لليوم
        cur.execute(
            "SELECT * FROM homework WHERE date = %s",
            (today,)
        )
        existing = cur.fetchall()

        homework_data = {}
        for hw in existing:
            homework_data[str(hw['student_id'])] = dict(hw)

        # عدد الواجبات غير المرسلة
        cur.execute(
            "SELECT COUNT(*) as total FROM homework WHERE sent = FALSE"
        )
        unsent_count = cur.fetchone()['total']

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        if request.method == 'POST':
            # حفظ الواجبات
            if request.form.get('save_homework'):
                hw_data = parse_nested_form('homework')

                for student_id_str, fields in hw_data.items():
                    student_id = int(student_id_str)
                    details = fields.get('details', '').strip()
                    notes = fields.get('notes', '').strip()
                    hw_id = fields.get('id')
                    hw_date = fields.get('date', today)

                    cur2 = conn.cursor()
                    if hw_id:
                        cur2.execute("""
                            UPDATE homework 
                            SET details = %s, notes = %s, sent = FALSE
                            WHERE id = %s AND student_id = %s
                        """, (details, notes, hw_id, student_id))
                    else:
                        cur2.execute("""
                            INSERT INTO homework (student_id, date, details, notes)
                            VALUES (%s, %s, %s, %s)
                        """, (student_id, hw_date, details, notes))
                    cur2.close()

                conn.commit()
                flash('تم حفظ الواجبات بنجاح', 'success')
                cur.close()
                return redirect(url_for('homework'))

            # إرسال الواجبات
            elif request.form.get('send_homework'):
                cur.execute("""
                    SELECT h.*, s.name as student_name 
                    FROM homework h
                    JOIN students s ON h.student_id = s.id
                    WHERE h.sent = FALSE 
                    AND (h.details IS NOT NULL AND h.details != '' 
                         OR h.notes IS NOT NULL AND h.notes != '')
                    ORDER BY h.date DESC
                """)
                unsent = cur.fetchall()

                sent_count = 0
                for hw in unsent:
                    msg_lines = []
                    msg_lines.append(f"📚 واجب جديد {hw['date']}")
                    msg_lines.append("")
                    msg_lines.append(f"👨‍🎓 {hw['student_name']}")
                    if hw['details']:
                        msg_lines.append(f"📝 التفاصيل: {hw['details']}")
                    if hw['notes']:
                        msg_lines.append(f"📝 ملاحظات: {hw['notes']}")

                    message = "\n".join(msg_lines)

                    cur2 = conn.cursor()
                    cur2.execute("""
                        INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                        VALUES (%s, 'admin', %s, %s)
                    """, (admin_id, hw['student_id'], message))

                    cur2.execute(
                        "UPDATE homework SET sent = TRUE WHERE id = %s",
                        (hw['id'],)
                    )
                    cur2.close()
                    sent_count += 1

                conn.commit()
                flash(f'تم إرسال {sent_count} واجب بنجاح', 'success')
                cur.close()
                return redirect(url_for('homework'))

        cur.close()
        return render_template_string(
            HOMEWORK_HTML,
            students=students,
            homework_data=homework_data,
            unsent_count=unsent_count,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/competitions', methods=['GET', 'POST'])
def competitions():
    """إدارة المسابقات"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # معالجة GET actions
        delete_id = request.args.get('delete')
        if delete_id:
            cur2 = conn.cursor()
            cur2.execute("DELETE FROM competitions WHERE id = %s", (delete_id,))
            cur2.execute("DELETE FROM competition_grades WHERE competition_id = %s", (delete_id,))
            conn.commit()
            cur2.close()
            flash('تم حذف المسابقة', 'success')
            cur.close()
            return redirect(url_for('competitions'))

        toggle_id = request.args.get('toggle_active')
        if toggle_id:
            cur.execute("SELECT active FROM competitions WHERE id = %s", (toggle_id,))
            comp = cur.fetchone()
            if comp:
                new_active = 1 if comp['active'] == 0 else 0
                cur2 = conn.cursor()
                cur2.execute("UPDATE competitions SET active = %s WHERE id = %s", (new_active, toggle_id))
                conn.commit()
                cur2.close()
                flash('تم تغيير حالة المسابقة', 'success')
            cur.close()
            return redirect(url_for('competitions'))

        # معالجة POST - إضافة مسابقة
        if request.method == 'POST' and request.form.get('action') == 'add_competition':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            max_grade = float(request.form.get('max_grade', 10) or 10)
            date_val = request.form.get('date', date.today().isoformat())

            if not name:
                flash('الرجاء إدخال اسم المسابقة', 'danger')
            else:
                cur2 = conn.cursor()
                cur2.execute("""
                    INSERT INTO competitions (name, description, max_grade, date)
                    VALUES (%s, %s, %s, %s)
                """, (name, description, max_grade, date_val))
                conn.commit()
                cur2.close()
                flash('تم إضافة المسابقة بنجاح', 'success')
            cur.close()
            return redirect(url_for('competitions'))

        cur.execute(
            "SELECT * FROM competitions ORDER BY date DESC, id DESC"
        )
        competitions_list = cur.fetchall()

        cur.execute("SELECT * FROM admins WHERE id = %s", (session['admin_id'],))
        admin = cur.fetchone()
        cur.close()

        return render_template_string(
            COMPETITIONS_HTML,
            competitions=competitions_list,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()


@app.route('/admin/competition_grades', methods=['GET', 'POST'])
def competition_grades():
    """درجات المسابقات"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    competition_id = request.args.get('competition_id')
    if not competition_id:
        flash('الرجاء اختيار مسابقة', 'warning')
        return redirect(url_for('competitions'))

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM competitions WHERE id = %s",
            (competition_id,)
        )
        competition = cur.fetchone()

        if not competition:
            cur.close()
            flash('المسابقة غير موجودة', 'danger')
            return redirect(url_for('competitions'))

        cur.execute(
            "SELECT * FROM students WHERE status = 'active' ORDER BY rank ASC, name ASC"
        )
        students = cur.fetchall()

        # جلب الدرجات الحالية
        grades = {}
        cur.execute(
            "SELECT * FROM competition_grades WHERE competition_id = %s",
            (competition_id,)
        )
        existing = cur.fetchall()
        for g in existing:
            grades[g['student_id']] = dict(g)

        cur.execute("SELECT * FROM admins WHERE id = %s", (session['admin_id'],))
        admin = cur.fetchone()

        # معالجة POST - حفظ الدرجات
        if request.method == 'POST':
            pattern = re.compile(r'grades\[(\d+)\]')
            for key, value in request.form.items():
                match = pattern.match(key)
                if match:
                    student_id = int(match.group(1))
                    grade_val = float(value) if value else 0
                    notes = request.form.get(f'grade_notes[{student_id}]', '').strip()
                    grade_id = request.form.get(f'grade_ids[{student_id}]', '')

                    cur2 = conn.cursor()
                    if grade_id:
                        cur2.execute("""
                            UPDATE competition_grades 
                            SET grade = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s AND student_id = %s AND competition_id = %s
                        """, (grade_val, notes, grade_id, student_id, competition_id))
                    else:
                        cur2.execute("""
                            INSERT INTO competition_grades (student_id, competition_id, grade, notes)
                            VALUES (%s, %s, %s, %s)
                        """, (student_id, competition_id, grade_val, notes))
                    cur2.close()

            conn.commit()
            flash('تم حفظ الدرجات بنجاح', 'success')
            cur.close()
            return redirect(url_for('competition_grades', competition_id=competition_id))

        cur.close()
        return render_template_string(
            COMPETITION_GRADES_HTML,
            competition=competition,
            students=students,
            grades=grades,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/messages', methods=['GET', 'POST'])
def messages():
    """صفحة الرسائل للمشرف"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']
    student_id = request.args.get('student_id')

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM students WHERE status = 'active' ORDER BY name ASC"
        )
        students = cur.fetchall()

        selected_student = None
        messages_list = []

        if student_id:
            student_id = int(student_id)
            cur.execute(
                "SELECT * FROM students WHERE id = %s",
                (student_id,)
            )
            selected_student = cur.fetchone()

            if selected_student:
                # جلب الرسائل بين المشرف وهذا الطالب
                cur.execute("""
                    SELECT m.*, 
                           CASE 
                               WHEN m.sender_type = 'admin' THEN (SELECT name FROM admins WHERE id = m.sender_id)
                               ELSE (SELECT name FROM students WHERE id = m.sender_id)
                           END as sender_name
                    FROM messages m
                    WHERE (m.sender_id = %s AND m.sender_type = 'admin' AND m.receiver_id = %s)
                       OR (m.sender_id = %s AND m.sender_type = 'student' AND m.receiver_id = %s)
                    ORDER BY m.created_at ASC
                """, (admin_id, student_id, student_id, admin_id))
                messages_list = cur.fetchall()

                # تحديث حالة الرسائل غير المقروءة من الطالب
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE messages SET is_read = 1 WHERE sender_id = %s AND sender_type = 'student' AND receiver_id = %s AND is_read = FALSE",
                    (student_id, admin_id)
                )
                conn.commit()
                cur2.close()

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        # معالجة POST - إرسال رسالة
        if request.method == 'POST' and request.form.get('send_message'):
            receiver_id = request.form.get('receiver_id')
            message_text = request.form.get('message', '').strip()

            if receiver_id and message_text:
                cur2 = conn.cursor()
                cur2.execute("""
                    INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                    VALUES (%s, 'admin', %s, %s)
                """, (admin_id, receiver_id, message_text))
                conn.commit()
                cur2.close()
                flash('تم إرسال الرسالة بنجاح', 'success')
                cur.close()
                return redirect(url_for('messages', student_id=receiver_id))
            else:
                flash('الرجاء اختيار طالب وإدخال نص الرسالة', 'danger')

        cur.close()
        return render_template_string(
            MESSAGES_HTML,
            students=students,
            selected_student=selected_student,
            messages=messages_list,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    """ملف المشرف"""
    if 'admin_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            password = request.form.get('password', '')

            if not name:
                flash('الاسم مطلوب', 'danger')
            else:
                cur2 = conn.cursor()
                if password:
                    hashed = generate_password_hash(password)
                    cur2.execute("""
                        UPDATE admins 
                        SET name = %s, email = %s, phone = %s, password = %s
                        WHERE id = %s
                    """, (name, email, phone, hashed, admin_id))
                else:
                    cur2.execute("""
                        UPDATE admins 
                        SET name = %s, email = %s, phone = %s
                        WHERE id = %s
                    """, (name, email, phone, admin_id))

                conn.commit()
                cur2.close()
                session['admin_name'] = name
                flash('تم تحديث الملف بنجاح', 'success')
                cur.close()
                return redirect(url_for('admin_profile'))

        cur.close()
        return render_template_string(
            ADMIN_PROFILE_HTML,
            admin=admin,
            datetime=datetime
        )
    finally:
        conn.close()


# === Routes للطالب ===

@app.route('/student/dashboard')
def student_dashboard():
    """لوحة تحكم الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    today = date.today().isoformat()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()
        if not student:
            cur.close()
            flash('الطالب غير موجود', 'danger')
            return redirect(url_for('logout'))

        # تقييم اليوم
        cur.execute(
            "SELECT * FROM daily_evaluations WHERE student_id = %s AND date = %s AND sent = TRUE",
            (student_id, today)
        )
        today_evaluation = cur.fetchone()

        # عدد الواجبات غير المرسلة للطالب
        cur.execute(
            "SELECT COUNT(*) as total FROM homework WHERE student_id = %s AND sent = FALSE",
            (student_id,)
        )
        homework_count = cur.fetchone()['total']

        # عدد المسابقات
        cur.execute(
            "SELECT COUNT(*) as total FROM competitions WHERE active = 1"
        )
        competitions_count = cur.fetchone()['total']

        # الرسائل غير المقروءة
        cur.execute(
            "SELECT COUNT(*) as total FROM messages WHERE receiver_id = %s AND is_read = FALSE AND sender_type = 'admin'",
            (student_id,)
        )
        messages_count = cur.fetchone()['total']

        # آخر الواجبات
        cur.execute(
            "SELECT * FROM homework WHERE student_id = %s ORDER BY date DESC LIMIT 5",
            (student_id,)
        )
        recent_homework = cur.fetchall()

        # إحصائيات الدرجات
        cur.execute(
            "SELECT * FROM daily_evaluations WHERE student_id = %s AND sent = TRUE",
            (student_id,)
        )
        all_eval = cur.fetchall()

        total_eval = len(all_eval)
        total_grade = 0
        avg_score = 0

        if total_eval > 0:
            for ev in all_eval:
                total_grade += (ev['score_save'] or 0) + (ev['score_rev'] or 0) + (ev['homework_score'] or 0)
            avg_score = round(total_grade / total_eval, 1)

        cur.close()
        return render_template_string(
            STUDENT_DASHBOARD_HTML,
            student=student,
            today_evaluation=today_evaluation,
            homework_count=homework_count,
            competitions_count=competitions_count,
            messages_count=messages_count,
            recent_homework=recent_homework,
            total_grade=total_grade,
            avg_score=avg_score,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/student/homework')
def student_homework():
    """واجبات الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()
        cur.execute(
            "SELECT * FROM homework WHERE student_id = %s ORDER BY date DESC",
            (student_id,)
        )
        homework = cur.fetchall()
        cur.close()

        return render_template_string(
            STUDENT_HOMEWORK_HTML,
            student=student,
            homework=homework,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/student/report')
def student_report():
    """تقرير الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()

        # جميع التقييمات
        cur.execute(
            "SELECT * FROM daily_evaluations WHERE student_id = %s AND sent = TRUE ORDER BY date DESC",
            (student_id,)
        )
        evaluations = cur.fetchall()

        total_evaluations = len(evaluations)
        total_save = 0
        total_rev = 0
        total_hw = 0
        total_score = 0

        for ev in evaluations:
            total_save += ev['score_save'] or 0
            total_rev += ev['score_rev'] or 0
            total_hw += ev['homework_score'] or 0
            total_score += (ev['score_save'] or 0) + (ev['score_rev'] or 0) + (ev['homework_score'] or 0)

        avg_save = round(total_save / total_evaluations, 1) if total_evaluations > 0 else 0
        avg_rev = round(total_rev / total_evaluations, 1) if total_evaluations > 0 else 0
        avg_homework = round(total_hw / total_evaluations, 1) if total_evaluations > 0 else 0

        # درجات المسابقات
        cur.execute("""
            SELECT SUM(cg.grade) as total 
            FROM competition_grades cg
            JOIN competitions c ON c.id = cg.competition_id
            WHERE cg.student_id = %s AND c.active = 1
        """, (student_id,))
        comp_grades = cur.fetchone()
        competitions_grade = comp_grades['total'] or 0
        cur.close()

        return render_template_string(
            STUDENT_REPORT_HTML,
            student=student,
            evaluations=evaluations,
            total_evaluations=total_evaluations,
            avg_save=avg_save,
            avg_rev=avg_rev,
            avg_homework=avg_homework,
            total_score=total_score,
            competitions_grade=competitions_grade,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/student/competitions')
def student_competitions():
    """مسابقات الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()

        cur.execute(
            "SELECT * FROM competitions WHERE active = 1 ORDER BY date DESC"
        )
        competitions = cur.fetchall()

        # جلب درجات الطالب
        grades = {}
        for comp in competitions:
            cur.execute(
                "SELECT * FROM competition_grades WHERE student_id = %s AND competition_id = %s",
                (student_id, comp['id'])
            )
            grade = cur.fetchone()
            if grade:
                grades[comp['id']] = dict(grade)
        cur.close()

        return render_template_string(
            STUDENT_COMPETITIONS_HTML,
            student=student,
            competitions=competitions,
            grades=grades,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/student/messages', methods=['GET', 'POST'])
def student_messages():
    """رسائل الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    admin_id = 1  # المشرف الرئيسي

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()

        # قائمة الطلاب الآخرين للتواصل
        cur.execute(
            "SELECT * FROM students WHERE id != %s AND status = 'active' ORDER BY name ASC",
            (student_id,)
        )
        other_students = cur.fetchall()

        # معالجة عرض المحادثة
        selected_type = request.args.get('type', 'admin')
        selected_id = request.args.get('id')
        selected_other = None
        messages_list = []

        if selected_type == 'admin':
            # محادثة مع المشرف
            selected_other = {'type': 'admin', 'name': 'المشرف'}
            cur.execute("""
                SELECT m.*, 
                       CASE 
                           WHEN m.sender_type = 'admin' THEN (SELECT name FROM admins WHERE id = m.sender_id)
                           ELSE 'أنت'
                       END as sender_name
                FROM messages m
                WHERE (m.sender_id = %s AND m.sender_type = 'student' AND m.receiver_id = %s)
                   OR (m.sender_id = %s AND m.sender_type = 'admin' AND m.receiver_id = %s)
                ORDER BY m.created_at ASC
            """, (student_id, admin_id, admin_id, student_id))
            messages_list = cur.fetchall()

            # تحديث حالة الرسائل المقروءة
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE messages SET is_read = 1 WHERE sender_id = %s AND sender_type = 'admin' AND receiver_id = %s AND is_read = FALSE",
                (admin_id, student_id)
            )
            conn.commit()
            cur2.close()

        elif selected_id:
            # محادثة مع طالب آخر
            selected_id = int(selected_id)
            cur.execute(
                "SELECT * FROM students WHERE id = %s AND status = 'active'",
                (selected_id,)
            )
            other = cur.fetchone()

            if other:
                selected_other = {'type': 'student', 'name': other['name'], 'id': other['id']}
                cur.execute("""
                    SELECT m.*, 
                           CASE 
                               WHEN m.sender_id = %s THEN 'أنت'
                               ELSE (SELECT name FROM students WHERE id = m.sender_id)
                           END as sender_name
                    FROM messages m
                    WHERE (m.sender_id = %s AND m.sender_type = 'student' AND m.receiver_id = %s)
                       OR (m.sender_id = %s AND m.sender_type = 'student' AND m.receiver_id = %s)
                    ORDER BY m.created_at ASC
                """, (student_id, student_id, selected_id, selected_id, student_id))
                messages_list = cur.fetchall()

                # تحديث حالة الرسائل المقروءة
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE messages SET is_read = 1 WHERE sender_id = %s AND sender_type = 'student' AND receiver_id = %s AND is_read = FALSE",
                    (selected_id, student_id)
                )
                conn.commit()
                cur2.close()

        # معالجة POST - إرسال رسالة
        if request.method == 'POST' and request.form.get('send_message'):
            receiver_type = request.form.get('receiver_type')
            receiver_id = request.form.get('receiver_id')
            message_text = request.form.get('message', '').strip()

            if not message_text:
                flash('الرجاء إدخال نص الرسالة', 'danger')
                cur.close()
                return redirect(url_for('student_messages'))

            cur2 = conn.cursor()
            if receiver_type == 'admin':
                # إرسال للمشرف
                cur2.execute("""
                    INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                    VALUES (%s, 'student', %s, %s)
                """, (student_id, admin_id, message_text))
                flash('تم إرسال الرسالة للمشرف', 'success')

            elif receiver_type == 'student' and receiver_id:
                # إرسال لطالب آخر
                receiver_id = int(receiver_id)
                if receiver_id != student_id:
                    cur2.execute("""
                        INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                        VALUES (%s, 'student', %s, %s)
                    """, (student_id, receiver_id, message_text))
                    flash('تم إرسال الرسالة', 'success')
                else:
                    flash('لا يمكنك إرسال رسالة لنفسك', 'danger')

            conn.commit()
            cur2.close()
            cur.close()
            return redirect(url_for('student_messages', type=receiver_type, id=receiver_id if receiver_type == 'student' else None))

        cur.close()
        return render_template_string(
            STUDENT_MESSAGES_HTML,
            student=student,
            student_id=student_id,
            other_students=other_students,
            selected_other=selected_other,
            messages=messages_list,
            datetime=datetime
        )
    finally:
        conn.close()

@app.route('/student/profile', methods=['GET', 'POST'])
def student_profile():
    """ملف الطالب"""
    if 'student_id' not in session:
        flash('الرجاء تسجيل الدخول أولاً', 'danger')
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            parent_phone = request.form.get('parent_phone', '').strip()
            address = request.form.get('address', '').strip()
            password = request.form.get('password', '')

            if not name:
                flash('الاسم مطلوب', 'danger')
            else:
                cur2 = conn.cursor()
                if password:
                    hashed = generate_password_hash(password)
                    cur2.execute("""
                        UPDATE students 
                        SET name = %s, phone = %s, parent_phone = %s, address = %s, password = %s
                        WHERE id = %s
                    """, (name, phone, parent_phone, address, hashed, student_id))
                else:
                    cur2.execute("""
                        UPDATE students 
                        SET name = %s, phone = %s, parent_phone = %s, address = %s
                        WHERE id = %s
                    """, (name, phone, parent_phone, address, student_id))

                conn.commit()
                cur2.close()
                session['student_name'] = name
                flash('تم تحديث الملف بنجاح', 'success')
                cur.close()
                return redirect(url_for('student_profile'))

        cur.close()
        return render_template_string(
            STUDENT_PROFILE_HTML,
            student=student,
            datetime=datetime
        )
    finally:
        conn.close()


# تهيئة قاعدة البيانات عند بدء التشغيل (للإنتاج أيضاً)
try:
    init_db()
    print("✅ تم إنشاء/تحديث قاعدة البيانات PostgreSQL بنجاح!")
except Exception as e:
    print(f"⚠️ خطأ في تهيئة قاعدة البيانات: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
