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
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
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
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def query_one(conn, sql, params=()):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row

def query_all(conn, sql, params=()):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


# === دالة مساعدة لتحويل القيم المنطقية لـ PostgreSQL ===
def pg_bool(val):
    """تحويل قيمة Python إلى قيمة PostgreSQL boolean"""
    if isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    if isinstance(val, int):
        return 'TRUE' if val else 'FALSE'
    if isinstance(val, str):
        return 'TRUE' if val.lower() in ('1', 'true', 'yes', 'on') else 'FALSE'
    return 'FALSE'

def execute_sql(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()

def init_db():
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

    cur.execute("SELECT * FROM admins WHERE username = %s", ('الشيخ',))
    if not cur.fetchone():
        hashed_pw = generate_password_hash('بومسلة العيد')
        cur.execute(
            "INSERT INTO admins (username, password, name, email) VALUES (%s, %s, %s, %s)",
            ('الشيخ', hashed_pw, ' أبو عمر بومسلة العيد', 'admin@quran.com')
        )

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

# === الصفحة الرئيسية المدمجة ===
HOME_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>حلقتي زتاي — نظام إدارة الحلقة القرآنية</title>
    <link rel="icon" href="data:image/png;base64,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" type="image/png">
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800;900&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --primary: #1a5f4a;
            --primary-light: #2d8a6e;
            --accent: #c9a227;
            --accent-light: #e8c84a;
            --dark: #0d1f1a;
            --glass: rgba(255,255,255,0.06);
            --glass-border: rgba(255,255,255,0.12);
        }

        body {
            font-family: 'Tajawal', sans-serif;
            background: var(--dark);
            min-height: 100vh;
            color: #fff;
            overflow-x: hidden;
            position: relative;
        }

        .bg-layer {
            position: fixed;
            inset: 0;
            z-index: 0;
        }
        .bg-layer::before {
            content: '';
            position: absolute;
            inset: 0;
            background:
                radial-gradient(ellipse 80% 50% at 50% -20%, rgba(45,138,110,0.15), transparent),
                radial-gradient(ellipse 60% 40% at 80% 100%, rgba(201,162,39,0.08), transparent);
        }
        .bg-pattern {
            position: absolute;
            inset: 0;
            background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.02'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
            opacity: 0.5;
        }

        .orb {
            position: fixed;
            border-radius: 50%;
            filter: blur(80px);
            z-index: 0;
            pointer-events: none;
        }
        .orb-1 {
            width: 400px; height: 400px;
            background: rgba(45,138,110,0.12);
            top: -100px; right: -100px;
            animation: orbFloat 20s ease-in-out infinite;
        }
        .orb-2 {
            width: 300px; height: 300px;
            background: rgba(201,162,39,0.08);
            bottom: -50px; left: -50px;
            animation: orbFloat 25s ease-in-out infinite reverse;
        }
        @keyframes orbFloat {
            0%, 100% { transform: translate(0, 0) scale(1); }
            33% { transform: translate(30px, -30px) scale(1.1); }
            66% { transform: translate(-20px, 20px) scale(0.95); }
        }

        .container {
            position: relative;
            z-index: 1;
            max-width: 1100px;
            margin: 0 auto;
            padding: 30px 20px;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }

        .header-section {
            text-align: center;
            margin-bottom: 35px;
            animation: fadeInDown 0.8s ease-out;
        }
        .logo-wrap {
            position: relative;
            display: inline-block;
            margin-bottom: 20px;
        }
        .logo-wrap::before {
            content: '';
            position: absolute;
            inset: -8px;
            border-radius: 50%;
            border: 2px solid var(--accent);
            opacity: 0.3;
            animation: pulseRing 3s ease-in-out infinite;
        }
        @keyframes pulseRing {
            0%, 100% { transform: scale(1); opacity: 0.3; }
            50% { transform: scale(1.08); opacity: 0.15; }
        }
        .logo-img {
            width: 100px; height: 100px;
            border-radius: 50%;
            object-fit: cover;
            border: 3px solid rgba(255,255,255,0.15);
            background: var(--glass);
            padding: 6px;
            position: relative;
        }
        .site-name {
            font-size: 38px;
            font-weight: 900;
            background: linear-gradient(135deg, var(--accent-light), var(--primary-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: 1px;
            margin-bottom: 6px;
        }
        .site-tagline {
            font-size: 16px;
            color: rgba(255,255,255,0.45);
            font-weight: 400;
        }

        .motto-box {
            max-width: 600px;
            margin: 0 auto 30px;
            padding: 22px 28px;
            background: var(--glass);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            text-align: center;
            position: relative;
            animation: fadeInUp 0.8s ease-out 0.15s both;
        }
        .motto-box::before, .motto-box::after {
            content: '﴿';
            position: absolute;
            color: var(--accent);
            opacity: 0.4;
            font-size: 24px;
            font-family: 'Amiri', serif;
        }
        .motto-box::before { right: 12px; top: 8px; }
        .motto-box::after { content: '﴾'; left: 12px; top: 8px; }
        .motto-text {
            font-family: 'Amiri', serif;
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-light);
            line-height: 2;
            text-shadow: 0 0 30px rgba(201,162,39,0.15);
        }
        .motto-ref {
            font-size: 13px;
            color: rgba(255,255,255,0.35);
            margin-top: 6px;
        }

        .welcome-text {
            text-align: center;
            max-width: 560px;
            margin: 0 auto 35px;
            animation: fadeInUp 0.8s ease-out 0.3s both;
        }
        .welcome-text .greeting {
            font-size: 22px;
            font-weight: 800;
            color: #fff;
            margin-bottom: 10px;
        }
        .welcome-text p {
            font-size: 15px;
            color: rgba(255,255,255,0.55);
            line-height: 1.9;
        }

        .divider {
            width: 60px;
            height: 3px;
            background: linear-gradient(90deg, transparent, var(--accent), transparent);
            border-radius: 2px;
            margin: 0 auto 35px;
            animation: fadeIn 1s ease-out 0.4s both;
        }

        .cards-row {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            align-items: stretch;
            gap: 20px;
            width: 100%;
            max-width: 900px;
            animation: fadeInUp 0.8s ease-out 0.5s both;
        }
        .card {
            flex: 0 0 260px;
            background: var(--glass);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 32px 24px;
            text-align: center;
            text-decoration: none;
            color: inherit;
            display: flex;
            flex-direction: column;
            align-items: center;
            transition: all 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
            position: relative;
            overflow: hidden;
        }
        .card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, transparent, var(--primary-light), transparent);
            opacity: 0;
            transition: opacity 0.3s;
        }
        .card:hover {
            transform: translateY(-8px);
            background: rgba(255,255,255,0.1);
            border-color: rgba(255,255,255,0.2);
            box-shadow: 0 20px 50px rgba(0,0,0,0.35);
        }
        .card:hover::before {
            opacity: 1;
        }

        .card-center {
            transform: scale(1.04);
            border-color: rgba(45,138,110,0.3);
            background: rgba(45,138,110,0.08);
        }
        .card-center:hover {
            transform: translateY(-8px) scale(1.04);
            border-color: rgba(45,138,110,0.5);
            background: rgba(45,138,110,0.12);
        }
        .card-center::before {
            opacity: 1;
            background: linear-gradient(90deg, transparent, var(--primary-light), transparent);
        }

        .card-icon {
            width: 72px;
            height: 72px;
            border-radius: 50%;
            background: rgba(45,138,110,0.12);
            border: 2px solid rgba(45,138,110,0.25);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
            margin-bottom: 18px;
            transition: all 0.3s ease;
        }
        .card:hover .card-icon {
            background: rgba(45,138,110,0.2);
            border-color: rgba(45,138,110,0.4);
            transform: scale(1.08);
        }

        .card h3 {
            font-size: 19px;
            font-weight: 700;
            margin-bottom: 8px;
            color: #fff;
        }
        .card p {
            font-size: 13.5px;
            color: rgba(255,255,255,0.45);
            line-height: 1.7;
            margin-bottom: 20px;
            flex: 1;
        }
        .card-btn {
            display: inline-block;
            padding: 10px 28px;
            border-radius: 50px;
            font-weight: 700;
            font-size: 14px;
            background: linear-gradient(135deg, var(--primary), var(--primary-light));
            color: #fff;
            border: 2px solid transparent;
            transition: all 0.3s ease;
            white-space: nowrap;
        }
        .card:hover .card-btn {
            background: transparent;
            border-color: var(--primary-light);
            color: var(--primary-light);
        }

        .features-bar {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 35px;
            margin-top: 40px;
            animation: fadeInUp 0.8s ease-out 0.7s both;
        }
        .feat-item {
            text-align: center;
            color: rgba(255,255,255,0.35);
            font-size: 13px;
        }
        .feat-item span {
            display: block;
            font-size: 22px;
            margin-bottom: 5px;
        }

        .footer {
            margin-top: 40px;
            text-align: center;
            color: rgba(255,255,255,0.2);
            font-size: 12px;
            line-height: 1.8;
            animation: fadeIn 1s ease-out 0.9s both;
        }
        .footer .creator {
            color: rgba(255,255,255,0.3);
            margin-top: 4px;
        }

        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-25px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(25px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        @media (max-width: 600px) {
            .site-name { font-size: 28px; }
            .motto-text { font-size: 16px; }
            .welcome-text .greeting { font-size: 18px; }
            .welcome-text p { font-size: 14px; }
            .cards-row { flex-direction: column; align-items: center; gap: 15px; }
            .card { flex: 0 0 auto; width: 100%; max-width: 320px; padding: 28px 20px; }
            .card-center { transform: scale(1); }
            .card-center:hover { transform: translateY(-8px) scale(1); }
            .features-bar { gap: 20px; }
            .container { padding: 25px 16px; }
        }

        .logo-container {
            text-align: center;
            margin: 20px 0 10px;
            animation: fadeInDown 1s ease;
        }
        .logo-img {
            width: 140px;
            height: 140px;
            border-radius: 50%;
            object-fit: cover;
            border: 4px solid rgba(212, 175, 55, 0.6);
            box-shadow: 0 8px 32px rgba(0,0,0,0.4), 0 0 40px rgba(212, 175, 55, 0.15);
            transition: all 0.4s ease;
            background: #1a2e1a;
        }
        .logo-img:hover {
            transform: scale(1.08) rotate(3deg);
            box-shadow: 0 12px 40px rgba(0,0,0,0.5), 0 0 60px rgba(212, 175, 55, 0.25);
            border-color: rgba(212, 175, 55, 0.9);
        }
        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-30px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <div class="bg-layer"><div class="bg-pattern"></div></div>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>

    <div class="container">
        <div class="header-section">
            <div class="logo-wrap">
                <img src="/static/2.png" alt="شعار الحلقة" class="logo-img" onerror="this.style.display='none'">
            </div>
            <h1 class="site-name">حلقتي زتاي</h1>
            <p class="site-tagline">نظام إدارة الحلقة القرآنية الذكي</p>
        </div>

        <div class="motto-box">
            <div class="motto-text">
                خُذِ الْعَفْوَ وَأْمُرْ بِالْعُرْفِ وَأَعْرِضْ عَنِ الْجَاهِلِينَ
            </div>
            <div class="motto-ref">سورة الأعراف — الآية ١٩٩</div>
        </div>

        <div class="welcome-text">
            <div class="greeting">أهلاً وسهلاً بكم في حلقتنا زتاي</div>
            <p>
                نرحب بكم في بيت القرآن، حيث نسعى معاً لحفظ كتاب الله وتجويده وتطبيق أخلاقه.
                منبرٌ لتعليم القرآن الكريم وتربية النشء على منهج النبوة،
                نُرَتِّلُ القرآنَ ترتيلاً في ظل إشراف فضيلة الشيخ أبو عمر بومسلة العيد.
                بارك الله فيكم وجعل القرآن ربيع قلوبكم.
            </p>
        </div>

        <div class="divider"></div>


        <div class="logo-container">
            <img src="data:image/png;base64,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" alt="شعار حلقتي زتاي" class="logo-img">
        </div>
        <div class="cards-row">
            <a href="{{ url_for('admin_login') }}" class="card">
                <div class="card-icon">🕌</div>
                <h3>دخول المشرف</h3>
                <p>لوحة التحكم الشاملة لإدارة الطلاب والتقييمات والواجبات</p>
                <span class="card-btn">تسجيل الدخول</span>
            </a>

            <a href="{{ url_for('student_login') }}" class="card card-center">
                <div class="card-icon">📖</div>
                <h3>دخول الطالب</h3>
                <p>متابعة التقييمات والواجبات والمسابقات والتواصل مع المشرف</p>
                <span class="card-btn">تسجيل الدخول</span>
            </a>

            <a href="{{ url_for('student_register') }}" class="card">
                <div class="card-icon">📝</div>
                <h3>تسجيل جديد</h3>
                <p>انضم إلى الحلقة القرآنية وسجل بياناتك الآن بخطوات بسيطة</p>
                <span class="card-btn">إنشاء حساب</span>
            </a>
        </div>

        <div class="features-bar">
            <div class="feat-item"><span>📊</span>تقييم يومي</div>
            <div class="feat-item"><span>📚</span>واجبات</div>
            <div class="feat-item"><span>🏆</span>مسابقات</div>
            <div class="feat-item"><span>💬</span>رسائل</div>
            <div class="feat-item"><span>📈</span>تقارير</div>
        </div>

        <div class="footer">
            <p>© 2026 حلقتي زتاي — جميع الحقوق محفوظة</p>
            <p class="creator">تصميم وتطوير: زاوي طه أحمد ياسين</p>
            <p style="margin-top:4px;">بإشراف الشيخ أبو عمر بومسلة العيد</p>
        </div>
    </div>
</body>
</html>
"""

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAABg5UlEQVR42s29d5xk11nn/T3npspVnfPM9OSgkUbSSCNpFKxkyREbR7CBxcSFFxsw7C5rFrzAsmDSsiSDYcHGNg6ysY2DbMuWZEVLI40m5+k0nXPluum8f9xKXV3dMyPLmO5PzVT1vXXuvec558nP7xGpHYMKASiCH8HqH9Xkb83O+4H+iIabbfZQV3vslRznB/Sj1rlNAbpqJLC6ioG/T2R8edOtVn1W1fNUw22ruuuphsdSqx5UrPltVXdfjftIrfscV/pcr9ieqFykgdY6ouEG1OVpLa7y+NWM0YwRNZuUyjOJNa6h/p2ZlGgg5vfjXq923lWTjd24JnTR+OUmMy8uc7fiClbA5c75DzvGy7jOf9gxRI1+QlQ4QJl51VioaLJq1IpBVMOVRMOVlFo985c7p56FizXGqF25zGDVyvUsGoWAajzWZOf467Nb0fTzSj6llFqxt0STvaYUa4qW4DbXmQ+xxpyJJs8r1p7z4DLlu1MB3XV1BTLncvJIrTtr5QlolHSikSWJK5DzYtX74BlFg0Su/75oeq9SgK6BLkHK4LMUonp9X4GvFL4Prg+uC37dNZotveZahWCVmG04r/kzN86HKj+sWENbUbWVchU01QXiCtT6y0moK/2ueFlnifXei8uPXtl9mgamDpYOpi7QNdBEQHwhG2S0Cojg++CVF0HJVdgu2A54fjDh4ipmQ3xPzyxehhl2ebro1W2kxDpaYBN1csX2FE2upZqoPWLVe7WGCGjcIdRp2vU7T62z9ypnGzqEDQhZAkur7XgF+D44PiiPlSKjvDA0CaYBFhA2gwVRcqFgQ9EBx1NNOIJqKrxEgy1xGQG2aj6u3jwTTcxA1WgGriEE6oVPVRkQqwkr1tJHxVUJk/UsUXUV59WzUEMqIiFBxBSYRkW3UNiuwHYVtgeeF+xwv8IplKquZ00Ei0XTwNQCrmHqioglCFsC24GcDfmiwvXFZa1/9T09s7pCO6Bh0zXV8lWVlroQ4gp40OXY+PfKjl65MZQCKRVRC2KWxCoT3nGh6CgKdrBrPT/Y/avntEZCp+6aUoImFaYGYUth6QLLAFMThA1Btqgo2ArfFwjxH2c+Lme06q+Ih0msc/zf0+mlFIYGiYggYgk0GRA+X1LkS2B7qqZJi1U6U3PFomIsKPDdYLyCE1wnYhFwAzPgDrkSZPIKx6O6CJRa4zrfT89fM/qvQQ9dqZfpcxJN3IzrSYDvkzep/vIRS5AIQ6gsq9MFRa4YKG81+7cmA9WV3Ee9iiNqi6HkBAphoQSREMQsQSIkMDVYLkChpKqLTKlXYD54eRKgqYu1fgGI72V5in8HbnWZc5QCKRSxsCARFugSirYiXYCiHZhyQoimIk68zPuoXwxFJ9ApSrYiEQkURV3CsoRscR0O8IOQAM04QE1vbbRwX6ntq9bxhn+P0kcppIRkWBAPB5p7pqBYLihcr/w032f+K4TAV5ArBUplMgyxkKAlKtCkz3K+sgjE9ygVryRacDVsJLgbXTVEg9QVhSGu1jWkrvL7VyZ9pBSkIpAIB2x5MafIFgPnTcVLpv4dAnKVNea4sJBVOH6wKJORYFEu58H31SsUH/xeXHar7QtdiLV8UaxrZP0g48Gq7MlLRQWJUOCkWcwFip5SYgXL/fdUwIQIFmI6r/C88v2Fg2PL+eDYDz6KvlJ71wOzV9X8OWr1XdZ2kWrig2bVLhOiSbC24aRG1ny54/XnCRGw2nhI4HqKuWxg3ol6pasyRsO6VQ1OLFGvDChQ9Y6Sqq6wchxVmSO1+l5FOVaSLSp8pWiNBsqhUqosDkT5Hq9uPpqfs5IOYk26rY4fBGJJBWZgPX3VFXASddnjl2f5l7M+1jueCAc7y6snfv39N46hrtBUEnU6kGh0w6g1PTdr3WuuFBxri0MyUrNMmp1+JdZY/TniZdCl8RylKuHgFbtmtcKgVENo4nJLTYh1r6ya7fArGEMpRSwUyFZfwXxOUbQDcbC2Pbq2DFRK4fsKpcqvei5XvsfgJRvu98qUYoGgYCsWsoq2uCQZBU9Brli2TOo5yZVv35pbXLH+nK05Rtn1L1QQDRRrreyyv1oKUQ6OlBeCUuvbAGssRdXAymoLa40xxErOZBmCVCSIAMxnA5kvRf1CbRQBq+/D92t/MwyDaDiMZYUwDQNN06ocwPNdSrZNsVQiXyjgOE5dnECsWHCrQ9216wsBeVug5aAtqkhFwPUCP0KVa4nVc9ZUfy8vUiEEsiy4V0j0KxyjfgHpV+KTlnVm4ithI4g6nWBdv3l5DfiAIaElCrqmWMwF7FVU/QCiar80sriKkut5HkIILNMiGY+TSiYJWSGklEgpq7u9pjsoPN/D9xW+71MoFlhKL5POZCjZNkr5aJpW5h7rs1shIFcMYgupKKQigrm0wlMNovdK57VsVvoNNLl6G6C8ANayAdQKp4dqDCS9bMteNMtVW8NcVYBUgXs3bEKmEGjZVYWrykXLscHqeAGLC9i8Tywapa2llZZkCl3Xa9ynPqTbQEkpJEIDTUqMWJxEPIHrOswvLbGwtEgulysvnrKiW/m37vr1OudyXqHrgngoeJ7FnFrbSlkrWaDMstUaHpvL0afRg39ZDlAv0S7nI7jSxGJV90KtIb3rFlvMgrgVhF8XcwpflcO5qn48tUKBFSg8z8c0Tbo7OmlNpTAME9/3A+6jFI7nUSwVsW0bX/l45d2uaxqaDNi8aVqEQha61ADQND0YL5lifmmRmdkZbMdBk3JVuLcxD89XsJRVWFqgxJZcyJcuM19q5ZxUQseVxX8F3t51PcP61XoS1RW4di7nf+IKfFqUWb+pQSIa7K7FbODhE41hblE3OULg+z6+UrSkUvR392JZFijwfR/HdSgUCmSyGWzXRZXPXWlmCqQU+L6qigdTN4jHY0TDEUDH0IOFkIonuDQ1wdLycnBuk/mq6HhSBPJ/IafoTATKrO0EjqMr5aDr7eyXE1IXye0blRA1mVx5X3lwVSdMqw9U3kX1ytzlbNq1xgsUs9p41f/LTK4lFuyWxRws5fyqfBZSBsrpSuZbvZfe7m462zqqwsF2XdKZNNlcFttxynpDTR4FRJdNn8f3fVCBXW+ZJrFIjEQ8jqEbZZ+AYnp2lonpqRXPJqVsyhU9pUiGFS1RwXI+4Aor071YRQ8hBKK8wBrZeEXMXakvoX48nQpRRF1GimjIpm/4XDlHrWF+qDWE/lrjUTdebVEFSRexUJB9kymUb5paYmPtfoK/+76PaRhs7B8gEUvg+R5CQDqbYXF5iZJdQgpZJfQqtqlU8wBb+d40IXAch/mlebL5HK2pFLFoDBT0dHYRskKMXBrFcd1AQVxn12YKEDYhHoKiLchXHFnN5rQujqDW2tFCrDnvrHGuALRQW/KDDbbTihVUvzMrr8t6IETzYFB1vIoJU5bFzUSApkFrVGBoMJ8NQq+iSeK78n2EpuH7PoZhsGXjIPFoDN/38TyP2fk5FpaX8PxAa18voFm7v+APvr/6/gJOoeF6Lrl8Dsd1CIfCCASRcIhYNEY6k65aHapuXqucrqwP+H4QOJJa4M9Ql4n9VOes4nb2K58rtuQVeIZqKcbBog61t3xQVOwlIRBKrZJjsvIg5WONr6oPtmEMUVFYGvNkKxpc3XmwMpwdCwkSEUGmAJlioC0LtVIlrlxblVnzlo2DREMhfOVTLBWZmp0hXyigVRw5Va0zMPlkZcspVecU8uvmz0dIgVZnIqLKIk0ET1YslSgUCoQsE01qWKZFPBYlnUnjum7VZl/lUBPgegpdC7ic44Ht1M2HWG0BiDqlUiKhfK+ifFCo9emygr6V98kdmy5rPlZkrXqFQmvrjacIUrW7EgIpYWq5EtpdQ1EsE3/bps2Bsgdkcllm5+fwPQ9Rx+5RQQRRSkGxWKRou+i6iWVa6LpE02pL0VcKx3FxbAfbtrEsnXDIwvfB970V7KhiOXS2tRONxhBArlDg/NAFXM+rKoe+Wu0wMjToSQlcBTPLCvcKFEJRXnx+3WJ9uT/65R3IomZzXfECuEyhpJR149VHZoLrxKwgiXM+q3DcOotX1Nk9MtgBupQMDmwgEg7jeR6ZbIaZhXlQCll21FR3ja5RKOQpFD0G+vrYs2MDB27YyY6NXfS1hUjFwDJcXAfmsz7DUyVOXJjgyOmLnD4zxvDYONGISciy8MqKYSCuAhE0PTdLJxCLxohFImwa2MDF0ZG6UKFPLRMlEK2OFySvtMQEUTPwFaywcZvZYRXO5V9pnsA6lLocBwicK3JNWX3lyQtipZVQcWtWrOYye9cldLdIPB+ml318v8b7hBLlaJ0o7zyPTQMb6Wxrx/c9ltJp5hbmV2m7UghczyWTK7Bnx27e/vqbue/gNnosm6Xhl7AXzpGem2FxMY+ybRIRja7OCImWVoj1U0zsZsxO8syJcT7zpWc5c/488Wg4ILxSVERoZbF1tLWTiMWRUmNmboaR8Uvo5UVSc17VylelVPSkAsY9tezjeTUxsbrgVFCL37wMl1xjUndy+6YrKA9vOCjWH/SKQ1JNwpupKLREBHMZRabYPK4kANfz6OroYKC3H1AsZzLMzM2W5XrZVCzb8+lsno7WDn7hx9/EDz/QRzQ/wZOf/zzzIyeYnM7wzDkYW4SiF9QPuG5QC9Aagp09GjdstejrGWD7Xa/G33Qtn/nmGP/wL19nYXGeeCwSFImsWASKrvYu4rEYACOXRpmbny9bBqsnS/lBtLA1HiSULOeCPXe187du6sYae1Ikt2/8D1DEXtP8u5MSFEwu+3hN5KEQAs/3icdibN20GV1qZAs5JqenqPcPi3J8IJ0tcu/BW/ndX3kDHZzjma9+hW995WmmcvDcRbiUBscVgAb4PHhgJ+dH5zg/OVdVp5KG4MZ+l7u3Ku48uJXr3vgmTpe28b//7ts8/vQLJOKhWs6DEChfIaWgp6uHSCiM67mcG7pILh+4jpsF03QNulMSv8r5rkTMfu+k00JtLR9coXY2U/Mr0a+qNtnkuFjneDONdJVzItD8Y+Ege6ZgizV3gaZpbN6wiZAVwnZKTM7M4PtedXKllOVoHvyXn38Xf/QrtzP61Cf4zN99jH/+4gW+MwTfHZIsFSS+r6MJHV1axKTgPT+8j5ZwmCPn5jA1C6UkBd9naEnw5Kjk7MU5Fk8/x7WJed7xztejJ/t46vnTaLpCk1rZ6RWYfKVSiWgkjGkEesPi8lJ9SLSmmQvK9QQQDxMUrjiBwrry3EZz6TLz3sQKqHNugKj4AVbxiMbXWvnHV3hciOa+gjp2LaWgNRboAgs51XTRBLvfo6ezm7aWVjzPZXpulmKpiNS0qofQcx18TP7vb/0SP/faKA/96e/z5S8/xT8+bnNyWpItSQzNRCmdFjOJZZjkHMVduzp53wfeTEcqwhOPDJOzQwgpMbAQQuD6MLIEzwx5zIyOsUe+wOtfdxt9O27gkSdOIHCRWjnQJCWu6+B6HtFwmFAohOt5pLMZtEYuIAKNwPUgakkMLQghq8b4dnUuxUr/9xXTpdG+FGihttQHf+BZairwiiUigkyxHCBZzfuDqF4kwoa+AaSQLC4vsZxO14gvJJ7ngLT42999Lw/smOOfPvRHfPGbw3zuiGAxL5FoSGGifANTRglpBm4J+uMW/9/P30ymmKe3t5WIr3HseBrPB0uLIHyDECF84VHyPI5PSU6cTzNQfJE3v3YPAzsO8vUnjyFUjRMJKSnZNrqmEw6FCIfCpLMZbMdpmvLmq0AURK0g3dxxv/85hOUFINZZRWsktVdZimiaWrWKJa3OvaqeJwjSqHUpWMgG0b4V36+TlRv7BohFo+QLeWbn52tcrbxAHBf+9vd+mbs3T/DRP/4TPvvYDA+fkdiOwJQhPKUTN6Lc2D/IRDpD0fXY0h7np959DXc8uIPf/m//hO+U+NGfuBt7PsvQSI4ZJ81tG/q5dXsPh8dnMaWOEIKRJY1jQyX6Sid48wPb6N1+kK88ehhdA1G2nIQQFOwS4VCYcCjIP6gEjlbMt6gkokAsFBwr2M1Y9/pkWUGXNQsfarLk+8QB6kMV64sJpRSmLmiJBTs/0PxXCruK4teabKG3qxvPd5mZncVx7WCiEUgBhZLD7/zqL/AjBwr84x9+iH95bIHHzws6TJOuZAvFYiDr8SFEjLlCge1dKX72x/bw4Nuu54sf/Qrn5yVjF0a5dX8ndzxwHSHX56VjC4QNMIXi7HwGAx3QMKTGRNblu6dt9oRP88b7dmJ07OPRp48SMrWyaStQvofrusTCEcJWmHy+QL5YCETBCs+mwPMhpAccMW8HeY9ilfBvtgrEy1IM/0OIgFgoKOtarNbVNblRIdnYP0AoZLGUTrNUYf0odE1jYXmZn37nO/iNHxngM//nf/GJb0zz2HnBzq4Ev/Nrd9KeTPD8qWlcXyGlxWQhTbcV5cffMsiDb93FS48+xW/82XP83Dt3MZ0u8o0vPsWdt/Zy3W27mB/L8OjxcS7OLyMFGIRpETGE0lCay3zB5qVzJbZyine+7S7Gix189/BxopFQ4E4WEtt2MEyDSDiCoeuBQriOCRcPCRxXUXK/v6ntsppUoaiu2EaPXsVpV3MGrlyF6x6v7IL6capujUDzjYYEthskfNSya+p2v+eTSiWJxaKUbJvF5eWqM0lKSSaXYf91N/ObP3kT3/3Un/KZh8f49nlJ3DD5vfffwM5Bna984xy+a2KKEJaIomOwd0eYB9/YzzNf+Tb/7Q+/w87ruxmMe9y2q4VDCxF+/f2fYXr0ND/01q10RAyKlAIOojR+7k3XcvvOHmxPw9AMTkzBf//HOY499Nd84F072btrD7l8vszqA1GwtLyM7TjE43GSiUQQZm7c3SJg/bYHkZCoppnXz2Xl/dXSpf6cyvsVYfEguXF16sBqS0KteK17vDymWGXNBHcUoHUEFbw121dVlgxKKTRN0N7aihCC5fQyjmOXxxK4rkM83sYf/5d3UTr5Kb751cM8fE7g+5IHb27n7gNx/uxvDnN23qXdjJDQQhTcPJYQ3Hl3B5OXJvitP3+RpXiSg4MGff2DXLulh+u3x/nWiMOf/PEXSaVKXLc3BlLDFy4uirDlYkgNHx9NmRhScnhW8vefH8E6/zn+13tfSyiUwPOccr4hlEol0pk0UgjaW9qqvor6lA5RTlwtlGpzg1o5l5X3V0uX+nMq72XD9ddmS2qdc74Hf0TYDL6fs5sf93yfZDxBIhqnWCqSzmaqOoIUglyhyPt+8t3sS57h3z71Jb52VsPxNTRhcO+NKebnchw754IwuGd/G6+/tYuSgIjhsmuLycc/dYhpQ+OmXSn29BmcPLKPYvZGDu4IsX1vJ185WuTYkXNctyeG76uA2JrORz5/kSdPT2OJCJ6v4/g6YUPy5LjGP37sce7sPM/P/ejryeZK1V0mhKgmlSbicRKxWBBYajKd+RJIAs/k1ZtVTd6vkTIkKwUPlby6VcRu8qc1j68TL1rJhsrZvDKopi2V6+7rQtU1xUgI2lvbEVKSyWRxKiFWKcnmstxy40F++rVbeeIzH+H/fbvAkmugKUlLKEzKgtlFyBWCUHAmo0hnHCylc9/BXnLzsxw6v8DO7V3sTSqEKxkY+CEE+0jJAjcNtGOlwhw5OcaGnjCv3bcL4ekY0mK8lCGnXCQaraEwm6Lt+PhEklH+7Bsez/zrJ/mF1/Zy3Z7ryBXy1Yyokm2TyWXQdZ32tvaVllSdi6TkQsmDsCUqoZh151Q1SfhbQZcG2lXey0rpdIWlNlM0V7GRZsdp6uRr6vep/Jhl0KaCHdjAjTkLvu8RCYeJx2LYTjBxsuwQUr6P1EO8/yffhHPuczz0tfM8PQqtCQ3ft4iFNFw7j2ElCBk6YTSePD7HNw9P88O3d/COt2zFsixKElS+wKGzY5w8ZfHNrw/x9UeGGR62efH4BVrbDMYm5rnzjo28/727ufuGftJOhpgRQwgDRznlfAGFrwziEZ3xDPzJp6fQhr/KL//4fSjMsjIYxCYy2Sy2Y5OIxQlb4VVcoJLuXrCD+TG1y8+pWKP8fS3aVd7LZju+KbtQl0kbVlcoRuo+hszgrgsl1eS8wERsT7Wi6zrZXA7bdYI8fhHs/vvvvJvbNxd5+F//jS8cCxJN2ltTJCJxbMfBsUt0tbeytT9OFIMCiv4ejTe+sQNLLvD1b51DGBq9PSl279xI3vd4+vFjHDl6DhGOceuBzbQnNYZninzsHx4lGZvjgVcnaTVDLDtpfF+WzUmb4ewyHbEkiUQMQxN8/Qx89fOPcP/WAnccuJlcLlflXHapRC6XxzQMWlOphqhebRoKdqAThAzRfFqvRDQ3O6fuf6nqat9WlWqoulQkKuVTqokIWPnbXIzUjgUZNRAyKIM11SqOqnehghSvZDKB53mkM5kgHKwUvu9imBF+6q33MffC5/jmU7OMZQNrOYSPIR0cJ8LkdBGKJX78HQeIiCUM5XHDHp2OeI4P/P5jfPSxOfSoxda4z+T5eZbSl9jcV2BDS46T58bQ55bYuaGL8SJ86LPD/N+//Da7tzts6AFXCGxl85Z9m9jR2olCInCwlItCkXMFH/tWjrnnv8hP/dB+hBYG5VdL0NKZNJ7vkyrXKaD8lbozQYaQ6ylCRqAPKKWuat5Vk1/UyoRRWamOrSRcNgs61GrkRFMxcbnj9edUvIJ6mf0XHYFfKemuG8P3/TKLDJEvFCjZJYQUZbMvy7133MuB3jTfffxRzixKhAxk5eBgG5GIyaLjMLpsMHzsEA88MMjP/vQBbt6m8/q7Ujz95AUOjbskB0zu2N3PiQvLnJrOYoSK7O4+wab+44ioxVeenyTmhblp32ZISj735CIXz4+xe7uOUDqmNDgxnmYx76KJMEbYZOuWdqQWgA6eW9b40sPPc+fGDHccOEAml69WIhVLJQrFQiDiojE8X62Yu6DUXFB0guQYTbIqWHe1dFk5fvBe1u/KFauongPUJYQ2rsIrOV45p6KNBN6/IPGl4Kz8e62EW5CMJxBSkMvnqulUvu9jWTHe85Z7yZz7Gl98ZolFTwcJ23rDbOzZw/03d+H6Di+c0hkameXM45/knW+I84f/cy8D7T5feWEBs1Vj24YW0lPLpEWRgzcnOTbhY/Y/yUjxPHkP7runhUPnzrIpIunZECNnCA6fmGP31gS3belF8yVHZ2eYLebwlM+917WyqX03+7a1AopITOdTTxWZP/k4P/PmW5FaiIqt6/ke2XJ4OBFP1Hhww5wVHIUmwDKacICrpEv9OZX3ssL+69w+NXbRIFzE9yx8aiImZAT2ru2oBrwBVU3yTMTj2LZDvpBHluVnPp9l397ruXmT5PjTj/LUEMQiFkoqeq04SxO3Mj6xyJbOGBcmdf7pW4JjJ0bxl4+zd5uJaYW5tFjEiBnEPYfeDsmd+7sZWnCwUlGOLnsUwlGSHTGWPcWDB9sJk6UzqkNIMbtY4i1v2MiP/0gH23tSKCBiauzqjzI6mmF+8iYSMgQaGKEQx+fg8Uee4NZB2LNrF7liPkhNF5J8Po/jOKSSCUzTrMuRrNnqthPERkyjaV3Vy1LGatD2KhABlSTDCu+psQtRDdaIuhzfVWHaht+m2ah1qqeUAksXlFyB59eOBfciy1G/KJZpkivksR236g/3leBtr301pZHH+MKj08wUJd1tETQpcX3J2WcPkyvluGlvCBny+O5wiIePpEirfh5/6hIf+sgxNBP6WqIkZIGxqTn8osP1m3sY6Ghly9YuOjqS9LX009/WwaHTy4xdmqAnYtDakeTFM8v87d8/xTXbS7zxdS206gkkGjfvjeMpuPjUSUolD6HDlp4IrjD5/LM55NRT/PB9d+CWzV0hBbbjkC8WsUyLaDhSK+6omzPXC7ykIUOU8wOufN6b/SJq1c1CiIoIqFcSmvkPGxWJla8av6hnY6sVlsr/hhaEPUtOXZ1BucqzkjKViMcRUpIvFMrxdYFdKtHXN8g9+7o58/w3+copKNkQkS6WBtdsVURbn+XuvSb9bSHyJY2UqXPtvi6GR+d5/4de5JPPpMkrjQ/915/hR3/219Cibdj5IkOjRb5yeJxHDl3ka4dH+fIzF5idlCRMRfvmvfzWB36T9777NZyd9/iTz4/xz594njtvkVy7I0LecelrM7j7+jCh5DPs2yIxDUlUczE1j+9cFBx+9ilef1M7HZ292HapbMoq8hUxUE4faxTDvlKUHIUhFZpcCVTRXAmsE6lNz6nRDKUqImB95q2uiNGoBiaz8uLVvyswdIUUwYPVvlGTWYauEY9GcRybYrFY9VEUSgXuvOVWOv2zPPfCGYaX4MYtgne84XpaYxaffWqKXGKcp4/McPHiFCEEmzeZHLg2zN9++gyHJ1x6Nob5tR+9mR967UE2dhb53Q+8j9aeG3n85CVaeixOzdr4IZOSWeRbhy/yjre/i/f+3JtIRZb5tV/4Ed7x+p2YCY2PfH2W08dHues2SVIKRocneOboKMttI3zmiQlaw4ofes2t7N/RwlJB8fWnhunRhjm4/wYKxVJVCSuWiriuSzweRysnk9AwbyUnQEMzdVWFhWmeUl8vuJuLgUYVT9YYez2Tb3z/yv2CwNIEvi9wvDp2VP71fZ9QKIRlWRSLJRzXQQpZTrUyefDgPqbPPMu3XwpKaaStGD91HhybjG+wfXATi7bFmSmDnO9y181hTpya4RvHcvRsCPPe1/Tz8++4nbn5LMMvfAW1eJhf+NV383u/9etIpQi1xFjM22zo6+Fv/+a3ufHAFsTiEYZPPUUonOC3f/ZO3nxrN7YUfO6RYQb7FakW+NYRjzwptm7sJ6eFsEuKkRNnUfk8EsEzZ10Wzr/Aa27bS4DMo5DlKGHJLmFZFiHLLANYrJwzxwssJVNbWW7zSvzKmjpQ8yGqBlzuWmFnc/6wis00e5UDGVIowqaG64vA9Kkbo5IbGI1E0DSdfLEQePykoFQqsnnTNm7c0sLpl57l+Eww8mC3xuZtUbpaBKWiz+MvnGd//yAD+iaSEZstPfDVJyfxDcFAR5idA1Hi3ZuZGDlH17a76djxo6RiKX7pp1/Lj73xID1tLbzq+k289637uHtflFhiGwPX/Wc0s4XFuRk6Brazuy9CsifEMxfy2EWb3l6brfFNXNu9lceeO0sh59DbDrt3Rdi8UcdHcXQSRk4f4radLQz0b6JUKlXN3XyhgKHrRMORqsdQVRVBhetX/AFB6litkHUlr70cXVTDsSAYtJJBr2Lk1dPrED1ejg1QUQmEBE1TlNxAu13BksoIYLFIDM/3KJSKVaWlWCxy4MabaPFGOXJ8mEtpuOt6k/vu6mUxuoX3/+wButoUe6/ZTEePz6GxY2zfGCKby3NysgRxnf5UmA197RDp4tLwCUKtWyjSgi824uZz7O9xWJjI4Ns2XdoSRbcXV/TiWj1YkVZmJsdo7dtOKhVjU3uYrA1Dowts2RDi5MwRMCe56+676Ghz+R+/eAvLiX289sGbuP+2KAs5ePLoOD36JW649rpAtMmgzqFQLOIrRSwaW1FPWJkb3wfbDeYtyDZbSSv1Mh2yDSKgGXOp+7xWwnDT1xrsX4EpBZoMNNtGZqdQ6LpOJBzGdR3skl0uI1NITefg9XuwJ57m+LiLKwXX9UhmF13m0x7xkOSOPTqFxQLzjsTVQ0QMH9txmC56tCbD7OkN0943QNE2sfOLJFt70aSD5xUpFWOcHvUwvQKnjo2T1QdBT+F7eXzPpbV7NwvTQ8iWLvoGN9Ae0cAQTC0W2dARwtYMMgLmJ+Z44HqDEAXOjYwxNrHA7laB1OFrh3yWRw5x5w07UUIr70CJbZdwXZdIJFytHaiffwiCQ7oUGJqoyx9aYZs1eX95OklVTr5Y/aq1NGiIMjc9d2VEWzX1JwT572Uodlet8DuIMpxLyLQwTaOK2gEC13Zoaenkmo1RLhx/gWcuwGCnJOJ5UEizOzaKkZ2iFZcP/9sQjlPiLQ/swbMXyWYKeBL6kyYdKY3OgW3MzEwi9DCa2RqYpbpBLrPI8Pgy0nOJmTojCwWUk0EpcB0bK9pObnEGVXDZfe0uOmImMqyRztnklpf4oYMDoHT+4qHjJPFw56bZJM5h5iYwPZeOpODkJEwOHeOGLXHi8Va8cmTT87yg/tA0sar+ALWisYTjBnOka/Uue0X9mVSBo+ppuBb9KvhP9fy5LlGjUlJVBWRAlB0YoknMWQTZREqUzY9aRk8Q1Al6sgghMA2J7ys8PxivktOHCv4eCoXQdINCoVSW/0Fm7dbBrWyIZTl5ZoRLGdjbq1HI+Qxdcjh1fJ7DLywSMzQiLQZPvDROfvEs99+7k0RXPxiS/oRFZ08roe7tjI2cJRztQjMjQUWw75FJL1B0HQbaw2ztNDhy8iK+GzhtPK9IONZNNp9jcWaKDZu3snmgnZglEeEk1998LYY7wfOnp4i1asQFnD2b58jxJU6cy5FZdNnWrrFQEpw9P8ZgS4nBDZso2XYViaRYLKHrJiErhPID0qBqm8z1Bb6SmHoNaEOUHUqB2Kif8xpdVr1qIAGBc61pXYFYu65gxbErrAup/E2TAlMXeCrAy5OydqyihIZDYVBgO3b5JiUlx+H6PbsgM8Lh00vYNpwcsZlYVuQKHt+9sMR0Os2zZ10cD44PZ0lnsszMFXnq6DyRkEFHMsS27f1gppgeH6OttadcPRys/1xmgUzeob8zyu7BdoaHRpibmUKpEgqJYRho0mTowjnCHf1sGexiS0eC02NZDh+fo+jB8aE0jg+HL/rMZ4sMzRXJFG2GF3wuTLu4nuLQsUWi9iWu3bWTUslGiABIwrZtQBEKhaupcvVz7ZVrUQ1drJ73qohWl60LaaSvVKv9B6z6W+Or0c+z6ngDC1J1LEcEyR+N51fiUOFQCN/3sG0HhMRXPoZusnf7ZtzZ05wf9+nsSFLyNURIoogxM9VNa3eC5ZIg7/kMbmnnums2cOzEMC+dHiOqGezYlGTbjq2U0gUyk+doy5xD2ctoRhQpPPLpJUqewjB0dm3uwfGDRFNdBCVqljNPl5piceosWK30DfazuT3KhdElTp88Q1dfJ7v3dOM4PtN5Qaw1Sna+F404ZlygmToDfa2cmlaQO8c12zahaUY1abRo2yilCIdCNQAoVemMJlAVRVDUc916ejRh+5ejXSUW0CxVSPmqjJGnqhp69fPl0shWXK0s5/2gilaTCsdTDeOXHUCajmWauG6QRi0Az/OIRBNs7U2yMHeOzk0t7Oq0cD1FfjmJl+kiVeplajhBzIqB8tjeH2Po0hJIyebBFgZaY+za3oNHHEdG2bn3Rp44/hKzY4cwpYPyCuQKGUaGJrF0xcBAO74PF4cvYZkavr3IS88/zHTBYffeG0hPLNG3eRvd7TG2DaRItkUYHsuzud3C9RWmFmZiNEyo2IO90E4pncRzfG7oj2G2JBkfP8c1G9uwQlF83ys/p4vreoRME71S1l6u/FEicAA5bjB/ouwxrcyf8qsRniszA8r/+75qEAHfxxflAsgKUpZqOKaUQtc1DMPAcWx8gnIxx7Hp7uphQys8/uRFVKnE5NwSOUcRIcYuYzf3xu8hTgqhRdF1wZ3X9aJHY7gSdE3nrn39pFra+PCffpKP/vnfsfWmN3Pbm36WhYkX8HIvYBkei8sFQq0p2tviROMpNnYlmF5eRrpTjJz5POn8FHe89b9yadLn//zqrzB1bozte3bQ32pStG06OhPccf02dA0MEaVDtnMwfjtbrK1EtSRLtmJobJrSgs3TTw6zpVPS3t6N67hVBBbHdTAMs84SqIvOiwBFRJMBgIbilaGLXnXDi7VhZa4KEmiNMSrsX5WrXwQrUb2V8tF1A13XyeXzAfaPEVgDGwY2EnHnOHVujhPnfeaLPpGwTp/ezt27D7Kp5wCPHz3NabNAMjrNztYcR857FDyfa3pSbNnQxb/863Pkzp3Gf/44508c4Sd+9de5753/g8XFs4we/zRzo+dIKRtNeIRjUWKxVr7xtUd54HqD3TfcRyyxlS9/4rN8+6F/RrNzfP2hebzendy0eyPHTp8k7zhsTRWJhqDNSrInup3brnsjQ3MxsifmiUbGmcw5+A48f3KO16kF+nv7mJw4j2mFgjpC1yEUtdA1PUAjbZhYz68jPLU0urVotx5kc0XMyKrToSkAlGpIPlwb6br+nObo4AEHQAUPsrIbbWC8WKYRoGY4ThUB1PU8NvR0I3PjjM3ZeJqOJ8FA44auAfbcvYP2H+/hxo3baY/ESBo+R4+MkgpH6UpoUCoxfmGWbz49xOmciRExmTp7ij/65V/kM//wWUKRWwgl+jl07Ajxrn4SYYM4Gbb1aHimpG3gAIV8D3/yX/4HX/mnD6NRYF5a/OuLc5x68Rx23qErLuiMGRw7Mkxch1Q0wr6ebfS9ZwvX3LmLfe2bMaSG0gS+ZnFuvIRRmGCgpwvHcavw8U6ZG1imWcVPqnekemXxq8tGSNxG2q2kaTOAr2pGUKVJYq0Mq55FiDo0qlpGwGr2vrKYpPK9xpcmA8XFdlfWG1Rgy3TDLFsATvU5NE1nQ08HhbnzjMwFAEKpqE7J87iUmWTi5CiZpye5ODnCZGYJAZy4mOfwC2fAURwdmuGjD7/IQDJBuhjlkSFFwQgRkUW+/JE/4U9+9T8hZC8HbrmFmQvnkKUcY0Nn2T6go7wQjz98iL/49f/M0EtPE0lYHF3QeGbYIKanmJrN8JnHj1CyBSfOTPPSuXkMCYv5DGenhsk8f56x4xc5szCE43mkYhquUqRLoAqX2NDTgRBaFfvXLqdGG4axAgirksBZEZ2aVumFxBq0W0nTFa6fuu8I0ax7+DqIP1d0XDRHqBBl8KcqmEbjGAosI2jy57k1iDVNN+lti1HIT9PTb9DS3sPR8UU0f5F04hhzCx+nfWQn86lnscLjTM8JMlHF4QmHUFTDQTGRdcgXZ7muN0WkpZVnLy2xpd1ie9xl6KWn+bPfOIvb3c+WvT1cGBsl3NXOjn03s5g+zr99/vN06jZ+NMS3R6BYCLGtPcLY/BLDpRKdUZ25jM+z57Mc3GIylxPI9nEyLU+hxnwy3jgzxjEMzaGttYXNbQmWF0fJZ2boa7sBqRlUOlh7roMgWADVyvA6du6roMOpLtUKXMm1mrZeCU1lJURbS/xsZjo0/K53XKnmZmXZAvBUk3PKK6IC4uz5Xtky8JCaQV97mJGReZbS8Ks/8wAH9u2kI6KQ0uGwd5iXzK9zLj2LrhcJRUzMcIh9O1uRhsBzFcKHJRe+O7REp5Xm9oEYIwsmz0zrpHWTwvIcj3z9JXAj3HxgP5t6uvjoP36dubk0SgrO5gy+fUESVmH2dWmcG5/hwlIJzxMBUJPwGdyYQLNChCMGUdNmKLPAE8XHOJQ9hqsKtIYV9xy8hvf+1P2MTirOn59hY1ck8AMohRJBmlgQDtcbRKuqdjX1ygm1NTo0oQtr0G3FOcF7vcJm1Dodale1i7/c8aa4RZU6v+YKihASTdPwPB+/HBHzfJ9oOEFrVHJidplnzjh87KFneXD/Dh575hwvDs3SNuNz/MQ402nBc9OQM2Dn1l5e3a/x9IsznEwvo0Rg7xY9wReOFuiIldiUimLLBM9dytIXstm0pYuJ8SUy/YrTp8Y5f2SEllQLT43liIsIgwmNdCbDC8MOUznADLQox1W0xMO8Y/8ACzMFHj2b5rFzgnQ6x8mLWUquYHROYfT2c8+ONj762e9wfFIxM7vExpt0QqEInl+s1kBWAC0r6CBVVq7AR+ApUXOgVeoo1QrwsTXpshIiqAxn2wykca2K8pVQpk1K/ZuJg7K6X2nXXoeu1oDfJ9E1HV95gc9ASDzPI5FIENEdphdyoMPS3BjtCcHt1/Xz8AWYzAuM9h5Ozypm8tAe9bj9wC5018BwXEquD5rA9yAeUmxoFUws+RweyRBRGa7rjHJ2IczhM7OMnR/lG08NceLUOAs+zMzkaNFCDCYVY1MLnJt26IrDlk4JbsCjXV9RKni0iiz3vupakgmdsTS8NKWIdbex4Bi8MAevOdBHOBbGsW2EhPGZNGHNIRGP43le1RRUvoeu62V8gYZCj7II0GRdG+fKNDcBeBHr0K6yAaXiKn5Vk/dqjfPUylYsQfeMAHC52TlCgKZJ/DIHAIXvBTj/ulfEtXPs6JHMzNmcPDvNa/b30JK06EgIbr2mHV+ANDQ2JDVGzlzk3PAkL11YDNipUghN8sANCbb3SXpbBFFLcGikwOlL87SZihu2tWAkwnztWIFnRhUTaZP27laE5vPSxTRLBcFAm2DHBpO339NNe2cEfIUmJWdHFzh9fpqLR04yEBVoIuhYfsc1HYRDGv1dIV59XYzjp6dYmMuztVNnOZsnrLlEo1F8zy+nf/m4vh9AzwtWzxMVEaCqltMqmjScr9Y7L8gHWDsYLNYILl7t8frgpqeaBZ1rSQ4BMncgEjzfIxqJIL0SC0s5+jraOTzi8Mt/9C2WJobZORDmidMOX3nkNEMZ8DSfcxMuf/XpI8zNp+ltDwWexhLcsCPO3h0pigJ2bzHpb1dcs8Eg7wlSCcGDt2zGFUmUBlnfRLmKTGYZ2/PZsynEvs2KrZtDFK0Iygxx/6394AWmWXfKIJN2+MvPHOPibAkPxfAiPPS18zx/rsC1myyOHz7Pez/0bU6OZehtS5LNZDGFSzgUxlNeuYsKZYQxbVWgtzKPnqqE59cP5IvLBOor7+W/BwCEqAR+yskNzXSIStq3XwVsDtyclhVClw7PnSmSLcG+QcmtB3o4NrJM1M+TURrzKkZfh8U77htkUel4iRSj0zZ52wuwfwXsHIijxcIM7uilr8/i9n0JetvjpEuwpS/KctZDhjV6YwYthmSu4KJFoiwsO7TGI7z59h62DrawbdsAZizFpt4ERAw85ZMveozNu7iJFhaVwTtfs4XWpMWCH8Y1dAyvxIV5wV13bGdPn07GhuMjRQzhErKswJVbCwBUM7AaZWV1/srgra8AShyyPkMUtUYaUdMs4DWOryEW4HLHRA2VvIIhqhSWqYPn4gJPnphhbCbL+95+M7fffRBNOWiawvZLLC+5vGpzL/ff2MPb7urClSaO0onHIqBDe0uI2SWbVEuEHRu7yKRNHj22TN726OuI853vHGF6YpKRZZeLMzk8T+GWXJbzLk+eWmR41GX/7kEGBlKcmUjTnopihHRaYxbSiCF0yTvuaOcNN3ZyY2+SbMGl5NkITaFh88AD1/Led97O8dEcL56bx/EFvu9gGnq56CV47mqv4xqTr+VW1LFuGuf/CujWmP2tUOjl4jCUqPQEEqsRfsX6fgElLuMapha2rMDFr27CJuoQvWtaiq5pCN8JgLGFxPYlv/9/vsk7H9yEp5sUpeLsjE266HHoyEl+4p5dZBem+YoDynPRFWhxi0jYRGGzszPFk0+O8anvzFFUsO/mfkR7kpOXfPSN7Sgy5IsuvVu7kaWg+/NsUfAPj85yZkbxlrdez5buBCjoaImiZZdZzBTQTIutbR57+qN8/tHz5Esew0sCR0rQDF584jBfenIO19BAKlzHRzkOuq7VGliWA2ey4kirw1oXsAJmth43Sol16LIGyGsFXV6ucMiuKBVfWUb8vb4q46zFtSoerHrM/mqnETyKDsRaTe6/aTNZpfHxh0/T32py//V9zOTBarXwNZ+kTHP8+CQxAwa7o4zM23QkDa7dEmF3Z4zvfOs8H/3mBEUFic4wBw5uZNqFWU+xPDpLR28XnYMtxNvCeEiUJdEigiyCh4/O8Q8f/S6b2+NsH2xnsDvB+LzDpg1JTF1x9twSccMDS8NqsVgu+jx442Z6kgYf//Y4mCavuWkLWkQGbWKUF2Q8N7h0Kwkfqok5ptYp0385L4lSdXV7ao16sgY2cjXHqWtqIOrYV/m9EmplbbKonVc5hlJIHVzb5eKFKS4tlUgXFa+9Y4D7b4jjK5833LKRu27o4tS5RWwtzH03D7KchoUlj219CfJLir/+5Gk++fQ8BSkIJXUGt6QYG5njuy+MoukBQmd2fpZQwmDq9AiTEwtoUR10iRYSCEPw3QtpPvThpxk9N8verV2USoJsTvLae3aQlVHG5zQevLWfB27ehF30ue/GVvZs78B2fIZnC8yMTQRII3oF87FubkR5dkRdtnT9/KjaXApWFnisSRdRCSuvPKfyXueKmkd/L+3jKePZ1MCiEOWuIaJOSxS1pk/1FcuVLhshE4o5xb8dTZd3i0D6RW65YTvxxHlefWOS7b0hPnt0gduuHyAb3sQTnz4JSYvR0Qy/f2KGC4suGIJISuParQl8PF48Ocf8bD5oYmHB5HQebT6P8kBGdKQm2dEdZSlXYny+BMLn7JzD7/7VE/Rs6oCowROnZ/mJH7uP3kSIM2fHefd91zFeuMjTpxLs26zz9PN5Zh1BOm3z2UM2mBJZrv5V1Y7SYkXvwpVsWK2G3hP186guTxdBU7RovdF9r66evJc9vsJJpJp5pSo6ol8zccoBEtf3AYmlQyju8bs/dRCz51o+/v8+wcmzSyhrgmu6Dfpjkk987gRPns3wraNZDl43i5kUuJrHRC6DsxjgQetRA90MHDmu45HLFolqHmldInWJwsVzFNKUiLAB0uWX33GAIxdn+YuHXkSL6CjhMpVTpGeXkFGDNtPlm1/4Kt84nGagFdo6W9i1tYvdnTqTY1PMzea5ZluK9/7Sz3Li+Wf43b/7TqDFSw3P92oYQkrUpYWrBlBXVjTGFFcQs7lc97agb6CiARri8n0BLt8/UDVJEKr5ruuvWctDDcy+egdIAJLggpCkwnBga5wud4mD1/QiHxjkhaeOMjS2yB07N+MVC7z6jfcz/cgIX3z4OcSpcd521zZedc39lIoFnjr2KM9dWuDcaI50CV48uciObpMuTbIsfKSlY1g6nqmVExYEwtDwFXzlWyfZuzUJhoZmatieyw/ftZnb999CqreXv/3Yp/nWqSmKsQjv/ulX0+kNI4oFtrbHefyJc2RtyS+87jp2mGlErMSuDWFS0QJCSmzHq4VnK/mRfpPwbX3tXx1wWGMlB1dBO1WGtbg8Uuwr8hIrgAlW+49VFRy5XgTYdomSJ4hGLETO5v/7qxP8yvt/h3BphpCuSHW0ctfBLTx6uIAv+rh3bxJP+ty0dxt7Cq+h5dm3s+Xku3lN+y/xx+94Nz/9wzdz+75utvQliEcSJFyXbMbDxcPzbDzlgynxNIHj+Ti5EtPLDsfOzIImsZXiwVs2c1OXxuc+9kmGH/0qv/DO+xlKK67ZoHHD5jYeebJIxgnzzrfdy2Q+RDwiWRy7xE//yt/wa3/1XZK6Rzxs4Piimhlc76MNxB5rI6+/gnTSrzjmuw4rqUSuVV3XbOq6W9QblpVGy42NT/1y7ztZ1+BJSkmhWKLoaUjdxBeKfbsifP30EuHwHFt6wuzZv4GRUZfHXprioW//Ka+7pY0D17fTY24n444y3f1bFLPtGDO38cJ3u+kYvJ4bb+2m53V9PPzNh/nwyTluPrCR62/ahiY1csvLzC/MMDmTRo+E2bNzM3e0eHzg759FGhb9rRHMbJHf+Odx0CRPf+4kf9pn0bs1BZ7N//yDT/HCuQzXXRdjYryNW27ZyaVTJ/nCkwscXTJ4zXVJxqaX0c0QRVcESOeV2sdymrbneVX3eH1nkYrHVK3Io64V2KzEehBXxBX0l+tNUpdhLSurfuvRLZqIgDLb8zwPwzBquQBSkstlcTFIRKMs5zNc16f4jquYzfq8c183R09O8pdfOkbRFIRMk2eOzXPnXdczOn6OZ86eDgCmUwavufYJNu/bxJJuUBi/gaGpSf7hG+f45ffczM+//UasaIJQIkY4piOwWU6nQXhECzYf+O+fZaIkIKwQeYevXpiFhIZu6rhLJRZmpohLn6PnM3SENPRWg+mhUT76zRf4o/+8DX1rL186MoyueWxMwAtnobM1TsEW5PN5ZKXPgBbAx9i2vaKcviYn62J8dSXgTcXuFRJWv8pt/rK0RLGmRrhSB3A9j1AoVNX+NS0IwdrKpKs9wpGRKY6MQn9/CxsGFCF/mY98bYHZIhAyyeR9/FiIhFXiX4+eZWw5uOC5aYfvXJjhmq4ZHrhmH1HVyyfP/SP33t7LLYNxfvHnP0xMKBKpMB/8i5/juWcvccOgQzZX4n//3VN85sUMZluMnb1JzpydoXdjOyVdMLtUZMPmEBvaIswtLlHUomTDGj/1+h3MXZziYtrjLz93mve/fSvXbE2RHRH8xSNzALSlwuRdjUw2ixYAACGEQNM0XK8cEZVipcZWiwyjmuFDX6kWWKdV6lyJFfgKIIJWGEClIdbKxpgB2/M8r7oLXNdFymCCsjZEwyF0EzwP3nzXIDuSaR4/Ocv//MDrODSc528eehqURldXBLtgM5bxEUkDhEB6CjvrUAzHSPkPcrbwHU4vZPn5m3r4rx/6FiOZ4MEfvDGEvzTFf/nAQ1haAMtyKg1Khw+8Yz/7+6L8xO99jVdt7uIn/tOdfPHbL6GX8nznxBTz80XeeGArb7z9QUZHD/HxR0f5b79wG+2t3Tx19FF+9P5B3CfTfHlqEc2ClkSUjC3I5bKErSAPQkqJ1CSe5+IrHx19JWdVtRjA99TBr24RyBWwkWtAvDVBH1pZfdBYWNAUsIgVrdQb89eV8nHLKVGV0udKt6+ppSLdHSnCUYGK6gwkcqQzeW69aRtdrsfPv+5OdvUnoOih+z6enYWQRLMMMHX8kEWkV+Pd+27DFTYvTj9KOBLhyIU0IxmB1WahGYp7b99IKZtnTknOl3RO5jVUWNK3IcGdOzrpatexfcFXHztNrHCJn3tNH8ePTvPPT02DprEwvcTEcx5/8/kj7N2Z4o03bmFPW4Qbb9rLxNgYWzo9lCFIRKCjPcnUQgHPd6tuYE1KhALHdeuQU1ZuPlFX/LEmnmNjqR9N6EsVJOqqUkLWUUdZd5xaF+21r1FJBg0KIwIt2HNtJhcLtLekiJgSQ9N4/tAIpuZz7MXz/NLvPsxf//k/sKXFAgQLCwU29HayZWs3vpRoQqAk3HVNH23ubdjGS5wcLyI1yeRiFpEw8E0DzxBsH0ywuJDBET5aXGIldURIZ//mFs4eHyVqCeIxyVzR43MPn6Kn3WJkdhFMAy0Km9s3sWhPMmfn2dpu8pt/8BC/+b8/zviFEfJFydnTk0jLJG5Ce2uKS/N5lOdWrR5dCxiy4zirlOTGOMv6PSNFk/fNkeCvKBxcA5F6+SynsqCDdCaxeiEIghRpqGbFSiFx3RLjczkSqXb298P//tl7aO9oZ3gsy+/+6xJ2Rxuz6QKTYzNg6VyaLFHKF/nVe3uJ6BJfSWItcG1oH/mlLM+PPkfW03Hx8QyJCum4QhBLmHSnIhw7PR4k+1g6nqETSUXY0Brm1LkJWuM6IVNH6JJTZ6egkKdvIIXwobfF4sYNg5xbOIlyYXh0kVAyzvFchD/53AjLSzmu2TPI7/z83WxKQaKlk0tzmSqaOCp4bkUwD2th7kq5MvP6e+0pI1eEcNXKsG3V1FA0QaBYC3KgOapxLRu4bBzWjV9hdyXHDtLDdb3q/5bAyNQCsdZuOsKCDV0pdvabzGcFejTEhk6DV920jYllJxjO1Pijh87x1586gqPA9zwObmghvrCd+NYzzLolSIZZKvhcnHfQTR3lK1riOn0tkvMTBbB0NEPDzdtsbbXIp4scH1lCFbJBA+pIiOPDWZbnsxzY14nyPO7a3EOpoHhhdAikIOsavP7WLaSMEn4kTtYW7NuokdBNtvcIwqlOxqbng1T58jzoRpAUW3LsBhrU5lcKVasbrHcNotauAVsTQkIhqYMME6I+f7y+H1CzDJNViX9rsn8hRCXzGU3WtT+t7yZKUBDieS6mbiDKtrFp6FyankFFush7If74L7/A9MQ8126Js7nb5JkjU/zhx55lMmcErf8sjdkinJh02NId51139/KmfZsJ950l0pvn7gN7kdLD1TVKmgwm31NsbAuhu0WODy2AZeEpnx3bu3nfm3aymC+RK+ZxslmU46J0xaUsHD46wYEdrVgpwabIACfGJpkp2hC1eH6owB/+8zNML3ncMBhhY3eMY8dG+KO//SqmEcXWOhmfnsE0ggWoSYGh67iuG4gA0Yx1B42s/fKGXFmTIdZR95u18ClD9l0d8Lx62dUDfrm0SZOq6ihaAUIpBJ7r4jguhmGU08MUhm5waWKctJ9gz2AHZyYKzKddXjw2wW37+njTq69nPAPSKkOPSg0RMhBtYabGl9gqPOYv9LPgXeQDf/Ytpscv0dseJZGIgBZo3bg+G1p1igWb+bwHnse779nBb715J1v6W/mxn/wR7rh1ECVdNnalGOhJ4vjw/NEJ+mM+t+5owc8muJgewvPL/f4Mycgy/MSPHqAtaXLizDSjc4qpZZfBvnZmnRiTU5MYuhEkgUiJoRs4joPvuTUchnp2LRRSlotC1ZX0ChaXpY9Ua4iAlZke5VLFFRdtyPKpDzM2AyxSQUcQWbVjVo4nBDiug+3Y6LqOlLLcLUQnnV5iaN5h97YBpIS5jEsyaXHzxgTFqQmI6TVHk1Qo00BJnbRd4OJwiqmRCM+dGGMoAy9czPMzt23n79/7Ovbv7scpBux2a2+cS+OLHB0rsXNbG9u0HJ/78jE+/JEnOPX0Ed73E/dSchX/633vYnMqAkLyzeM5DD/He/YPknM8zkxPgBUKZs/Q0SKgJia5ZXc3WVuwkPWwdLhmx0YuzJTI5ZbLDa59pNTQdZ2SY+O6Xm3X1tFHlDmA56/sJVjrxL4SAKp5aZhaATMn68uEajnoZRRJLUCgqKJJ1H2u71+zEo9+jURRIVFKYpTz3SrmXnU8KkgZRaTUMA0DUGiaxC7mODE8x/btW+luCcqrEqbOX33mMMenMnT0JMu17kGja2nq4PncvquNTn0HpdALPD+2jIhbKE3y+3//FH/zN//Kj+zfjBU2wPPZ1m2SyTs4KLZG4c8fOk8sZnBsvMBv/t23eOo7LxGKxvnzP/hznn5pBJEKc37WZnx8GeH3cOLSaWYKqlr9qoRiQ38LXzk8yUe/+BKpmEE677KlUzC4eSvHL07j2EW08kK3TBNNSIplwCgh6rI/yiJZkxJdl9XeThXIWdlQCiaalvk10jdQspubgfVx23KsnvrY/RW591b/VFBBpKglflQ7g5dZXr5QRApRxs4NFrqmCY6cGyHRMcDewRSZnIMeMtmxo4v79nZyz54+kB6U692Vq4i3CLbIzTiuy4XZkyw5OqRCnJ4uYocNHj25zPTQEFs6Ipi6T4du88ihWfAkS0t5kp0hdvSFODebx9ckn/jiCcJuFiccwlE6UgqWbHjsxQxHT+W4uDANSKQWPKimK+7b3cYde9vZtq2fsGWwXPC4aXsULdbLsQsjGFpFBxdYpgVSkC8Ua1xWNKbVBfUVrqrsP9Ukzn8F5ruoFRpI1SRTBKVQfgDO4JfVd9/3V3y+mgyhwArwcRwPlI/UVAPgRI0lFYoFfN8jZFogyujghsGpi0Nk/Dg3bG/F9SURS7G8MElo+Tauj76a7l4T3wXh+SjXZU9HlFB+O45+nkPjRQiZCMfHi4XQW8MIQ5LLLdEXskmFBYPtOssFF3xJPufzrvu28OK5pQCJJCw5NZlnYS5DLG4ELkIh0WKC08NJpuZdZuwsGCb4CuX67BmM4y/vwC/1MzMzi25ISkqwc2Mrc06Cs0NDWKaJV24pb5kmnutRLBYaQui1+RHCR/k+ruuXaaLK5WT+FWVuNWZ+BQARVS2fun4BorbTqyFaVnxeCUrc0CKyDqCm+l6B45VrAGUFwKjWdp0yHnCpVMJ2HEIhqyweAvt4dnaGi4sa2zd0YZo6w5NFSmnF1s43E1FbadN8kBJPSKIp2Oj34jhzXMoeI+3oaBEtcAurcl29oSE1D+E5tEVNRqcKPD9sI8I6Z6cyhOwcj55aCsSGobFYVFwYz1Eo+uB5eK6ivTXElpZBJgpjZG3QrHI+vwYtvmJ36l1sSN3J/EKW8TmbmCnYtrGX8wsaC4tzgb9DKTRNw7JMbLuE7djV3sK1ymCBUBULClyvZkqL+mLbhjlvuv/rGlYTpIStVWIq6mr8KskK6zQEWlP3rHXMqgAaaFKghL9yPCGQZW9gsVgkHoth6galslJYyCxxaCjNu/fsoSt1mFyhRNyK829PHsaPnCASLxeU6Aa3bYjR09HP9q4MzrkwqawgXQwqjTRTR9kuytKImgbnxha4eXuMeEyyrHyUDbfvb+fCWJqFtIvWYeF5kryvWM66DHSFQbNBKq7r6MD3Nc7OXQJpVGsa0CW6DQ8/9RwlMU5Hp8lCXtGVEmzadi0fPbOAXcgStVrwPQfLMDF0g6XccoARIFcbZ0oE+IqUq4Try4NXG4BibYSIFbVm1IsAao6FOjZRX6e8Fnu/EhEACs8rg0VrjVhCqi7TRZHN59B0DcuyguQI38fQJc8eO0Osdx+bupNM5zw8R+POyAEimRZmF0uETI1fuKeLB3b14bjDfOWZedrM1/HX/+kNvPbmXnraw3i2ja88rt+aImoEqOR370qSzboc2LOJzt4W3nl7H8oMYySi+ApCIYsHbt5AW9Rn/2CSwU1dmKbNntYNTCwtMpGzQdcwQiahRARsn8XlNBtK/dwkbyJbcvAQXLcphtVzLYeOny7b/+V8R8ssd0LJofwafErjXBqawgsYUJUDqEZaXYUIQKn18QFEXbJGlUBCIJqEolZYpWtUrXi+wPNU0FxZqdUQMuWFks3l8H2fSDjCciaNUoqIFeLUmZOcmr2Dgzft5OTFGYpujkzqm0T1UyykFTv6w+Qm0pyfz7C0XOLa3j6mxi0e+1QXb7t/gJs2HGY8Pc38QpFtyTDffukCdl7ni4/N4nsF8lonP3pLD6dPz3B+zMOMaOzqjDG1WKK47PBnX5gkHEoj8lF2tEXIjiU5N38Iv9zC9v7rerlusJ8P/fPjLBYcQh0vkZUFXAUdEcnBG3Zyclpx7vwZQqFQNQU8Uu4VkMvnyuxe4TdUTgkRwOx7XlAfWK5LD9JFGquIRE2HVKzfUVhXsAKftlmwRpXbnIhGQKGqYVDTRoWqqzpo9EsphePLQAeo10ardTACITUKhQKO7RAOWeh6ECrVdYOl9CJPnJzkbVu209PxEpfmlpnTHkKzcsiSRZt0aGsNc+hsjsdPZdjducQb9s/i+rfz1S/00ta9DSPaRZwZSu4pjo1lmV1WnJZBcGWwa5E3m2F+69PjZB1IbozTaRkcn57ikYteYL74WWLted531wEuvJAjLZZR0sAM61iZeZj12NwbZuJSiUzyMVzpsVGPEjMF/Vuv4ZOnJsnl07QkErjlBBjLClGySxSLxSB4VZc5RV1piK4JbK8GGV+V3qoRLKhWlb1qg1cTUAM6ygpRRT2B1+hIWIs2rq7+XYkM15z1qLIiqMkA5kSt6GtTLgQhAInM5vOYpolpmNXUcEOTPHboOCKxkcH+FopemNniEkPzBbJ5j8GNbWQyPo+fytDeEeL8ssGHH5khn/8auw58h3zxOUanjgNn+cKzY8yVJEarhQJ6+sL84U/v5GvPzZH1BDJpIBH4ro1vaBitIdAV8VaDX3/NVnZ3+vz6e+O87z13EY6HsHMlPv/ENGcvTqK7NiVHcHZ2kqXiMpmcZLAnjBMd5IkXjmEZWlkL97FME9PQyeaC9jFUi2NWJtNqIgCKrmAsiiZofI21GM1Bu2vHUAot1Jr84OVyBxstSnmZ4/XnNXqmdQmxkCBfDDqFywZmIYXA93wMUyeVSOG4DoVCYBoZus7swiK3HLiLbdF5nn5hCF8LY1qCtJIcPjHD6fECoaTOf33nXsansozNFzk85pJNT9Pdt8hycY4nj89yKQdEdHzX49Yb+3n/63v58hMjfOmFDDKuIyyDUrbIG65pQ7a2MDI2w417e/jAW7fy3efH+KNPX2Bhep5ffNf13HbrHiZns2ztibG1VeeRM0t0xnVaIwamFSJXzPGjr93PkHEDn/7q1wiZRnVTpJJJIqEwUzPTQbNpTVs1p0oFLWPiYUGmoLCDROnqObIa2bs8XWTDMS3UmvzglSSQrOfqudzCqVofKnAFx0NBu1jbrVUNU5c8HBSG+rS3tKJpGtlctgw0rZPNLIPVyhtv28nE8GkeO7HE6w5sRuJx8mKWH3vdDm7bHadNFvjkU9P4IQ3lKyYW4fCwy/kZl6wDd+7fxI3X9PKO+3ZwoLvIR/71PI8cK9DSF6Hglvv7lXwWZtP897ft5h1vu58Htro89ugpPv50GlsITlzKkx46z1tftYm33dlPorDM5x4bZjTj8+pr29i3vYdvvDDDvfvi3PXg2/jIoxc4f+5UVf7rmkZHWxtKKcanpspJsSvr/ipAEFFLEDYF6XxgBYgm0f6rzeIA0KwrWACvSIl43VWjoWBV5+3mMSspBK7jEY1GicViFAqFumQRycziMvfdcZB+a4ZPPzFCuujyU6+7Fte06Ilm6bXynDy/wOEFgZKScFgnEjMJRUzCiTDhVITsUgHTKXFpfJovPj3PVN6gsz/GgzftYrFkE4tHCSejLC77nDk7hj93mk984xIPH3ewEiFME3xPcXTMZuj4CV545gyPPDfJvKPz+tu3cmDnAP/0zYsUnSK/+KZrKHbewUc+9zVkObPX932ikSgtqRTLy8vMzs+XofGhmR6dCAfyOpNXa57zcn40qywCrmTVfC8cgTp2FrGCxpHZYvMHqaRGG7pBKpXC831yuRxSCnRNZ35hjmjbRh64JsnszBhDs3k64yGkH2JytoBXytGfEpxOa2RKPq1xk1QkgmnqtETDtMZiREyTdM4hV5Bs3xjn/htbaQ+ZtC/tpK9rif1bEkTNOKbUWM57HL6Qp+hbpFIxdFMS0gWe71J04MwMjM17CAO29LfR39FJrljg0PlZ7t8b44F77+OhowWePfRdouFwVcNvbWkhZFlMzcyQy+WCXINmwVsJqYjA84M5E2sQ/3J0oQk9XnmYuCtIDrUdiIZEgBrmrx6jUhW8nElj2zbRcBjDCGLlSEnYMvnSt57gTTe9i7ffdYJvH3maP/j4YdAE73ltL29481sYe/Fp7rdz/OPTM8xnbGaly617OhieLzF1aQrNc/EA5XqMzMDzJ0Apya3dOZ49Oofv+xSFRtEHTfloUuAu5ejtkXS3RXnhTAYNCcpl/0aDvZsM7n7VDTx9+BJ//YUXkEB3h8Ebbx1kPnItX33s40RCocBZ5AdtcSPhMKVSieVsphr9XGVWl/0muiYolNQKI+x7oYuoDwc3aodrao5rnXO54/VBShW0i5FCYWqw6vpVTCFJoVgkk8lgmiaxaKxqDVhWiImJYb50aJwde/bzrnu3UQwbXLsrzoFtLQjieFYbt+/ZxP6t7XhK41W7k7z//mt49Y4+POVjI9Etk3DUIo9gHoO925K0bZNcsy3FIiZFX6fTSCKFSUloYElef10vv/n2u7hpeyu+gr3bU7z+zq1s7W+jf/P13H19P1v6NQoIXn9TO9uuu4OvHh5ldvoSpmkF2r/yiUdjmKZJOpOhVCyuKAlvCOpiaEEgqOQ2wG1cLV1Uw3cBzWpJfLAhR/tKkgTXZy6iSRli2TdQcVPGwkFcu2CXEatXAAkE2qrv+ygUrakUUtMCR0nFgSElw5Mz3HnwVWwzL3Fy3uHUhVl6RIEPf/JJHnlyFInk1TdsIJtfZiCu8bVvnaEtVOBiGqIhDQvFQHuUmcUiO3tj/KebE7z+1beztU3npQuz5As69/b0MbScJZpQxCyDLRGbR586S1eHRdzweeuBTZw8O8dDj07wxNPHCLkLPHa+yM7BJO+5ZyvFnvv4v//yBYTyqkTWNZ2OtjaElFyaGKdUKqFVIoN1CA6BAzbQ/g0dlnOUm2+skYArGks/L0O7oBKpAkcqqg2kV5f1NTQhbnq8Dqa0WQ+buiYFrg+uJ7AMVuDh1ZfCKUDTgrqAXKFAOBQiGolUuYBpmkxMjPDpp4bp2XmQX3xVP5puUJI+eqKNkRw8dfoSnXGHV+9uZ3J0moIPh84vge/yZ7/yZg7u28jJoQU6O5PcvztJNNnKtz9xI1FrkNfd0EJbS5RvXLjEAwc38Ue/8m4KBZcXLy4zvJBnbnSKN+7vpr8Vnh9aYrwAVixMtlTEQ/CuA51s3PcADz1zjtmZCXTDqNr+0WiUUChELpcjW5b91RjbCmsoMJMtA1xXVPGBVjeEaKSLaE63+nPK7wMOcNUVBc2Kyi8nfWrnKiWwdLBMyJeo9spb6b8UVbBoTWqkkkkQkmw2W3WWWIbJyXPn2Hfz/VzfnsWzbf7h4UukHY+2DoMfu3sz0UQHbgncUpqi4/Ps+RIP7k/yqz/5Dix3nsePDvGqHR28aptibuR2unt+gqQwSaWeJGuHmMtl+eW3b+aBe+7nueef55kTy+zr1xnojNDf2YEKpejrTnFidJrltM3hEZu33NbHm+6+gdPqGv76E58kbJl1hTGSjrY2DMNgcmqKbC5blv/Na+Y1TZCKCgolyNlqjZKtKykQb1b9oyoL4OXYAQ0XFE3YTFOvRHAjmgwUwZJD2bHRHGhIiiBEnIwniYRDQaPFUgnKGTKlYp6h2Qx3H7yTDfoYk2mf4xfnObAjztyUzce+dgYPjY64TnvK5Oiiw66kz/Cxo+jpMeYXXOLCx/XynD91Cze1v5snhx9lfOkb2DmbmOnTrub4zuMvMr+4yETO4/49MaxojKdP5/iXh8+g+zbJmOL0WImbdrTwY/dsILLjDfzBJ7/OwtwUhmFWXerxWJyWZJJCIc/YxESdk2S1oa4UhC1BLCTJ5BW211BdvS57X0sKrBQTgSdwRa/5Zo0FGllJk+M0sBnRREzUgsMoIBaSeD4UnLJHcA1W5TgOhqGTTCQDx1A+V8bLV4Qsi5HRYVRikIO7BtjZbnNqIc/54XkKRY+RpRK//pM30tM3QGGhQEtXJ5NT0zxzaonpZUUyajK1uExS9vHNIz6nT8zw6PC32dNbYCY7hSZMXhjyeP7MDJqpuH7XBnoiGgdu3UtPXx//+vgZEmEYWSrR2xnlva/fwvYbX80/PbvA4089RiwaC6Dqyilwne0dmKbJ1PQ0y5k0Wtnz1+ylECQjAkMKlgsK329o39eMva8QpWId2gXvr1IEvHJOIV9B2AiUm1xRrVvrJkRQR59KJAlZFo7jUigUqsCSIcvixWNH2XnDvWxPFtnSJnnq1BznJ3Ls3xUm4eb51NcvcHqywMHd3XSmElyzs5/777iWsOaRtNJEc9dzYryTUV4gorq5td+ko3+cge5u7rrrVXR2trOpI0ksHOPrz01y6OgkKT2DIsfz50skExa/+oatXH/dDTyzNMCHP/4J4tFaR3DP80glk6QSSQrFQrD71fpFfpqAVFTguJApKF4haMAGR9APYAFU7FtdD1ycBTvAwl/LAKmUTEtNI5lIVLuK+H45JCoF4PPS6QscvPuH6fRGuGZzJ8cn5xmZLTA6kubCssd9N/ewsbVELJlgb7/NNx8/wwunFzE1xcWpJXaE3sqtqXuRTolpvopu2Tx1PEchPcd9t0TJlKLEzSKe1PjG0WkmpxYYzQs6Wk1+4y3XsWdzD7Md9/F7H/k4uDZC6lWSGYZJZ3s7mpRMTE+xnE4HmT/rzE/IECQikkxRUbS/9yqgpgsg1JL8YI2F1LMT0VyLfIVelYyjWFji+lB0qPYpXH1uuXt4oUAiliASDiOFIJvPVUGWDcMgvbzISxcneNU9r6OlNMT123p48eIcF6YLxOM6e7tDdBpZTp6d4MSpKT71dJo337+NLRtamZuY5d7Ue5jORLh+wOQSn+HW27chom3841fP4i1Pszg3y6ZWmFgocWEhz2zaZ6A7wm+8ZTe7NrRhD7yG3/y7h5ifncSywlXUc4COtjZikSiZXI6x8fFq1s968xOLCEKmYDkX9Fn8ftDhB8YBIIA9jVgCXQpyRf+y9Ymu6+L5PqlkEtM0sUs2JbtUFQWWZTEzPcHZ6QJ3veq1xHLnuXFLJ4uuzenxZV48uUy+6IDnYITjdLWHSKgsZ4cXaY+XyDkez56fo2PDYWIdZzk7lkcrZYjFdHTAdRwODRf58osLOKbi9l0tvO8Nu9nc04q36Q38zse+ztDFM0QiUTzfq0LAx2Mx2lKtKBRjly6RL4svtQ77FwJaYhLPUyznFd8X/v+DFAEVPcDQIWpBwVHrioEgl1CjUCwQCYWJRiMYuk42n69m1vi+jxUKMTo2xOnJLPe8+q0Yi8e5Y+8gqZjJC2MzjMy6jMwp7ruhlYVFj28fW6CIDApK1AQDVg/z5te5VChwZsLlxaEMO3qj9LTpfPa7eYbSDioiec+rNvMzD+6lJWzgb3sbv/3//o3TZ44Ti8arxK80f+js6MQwDOYWFpicnirb/eqy7D8VhWxBUbC/L9y/QQSspVmKJvjhV3u8yTn1tYGxsMT3oeRcRmyUmysVS0VSySSWaZX1gVwt8dT3CYciXBof4aWLM9x08HXE/QV2dOhcN9jGYtFhYjnLk0czXFgqMdgbRtc1lKMRtgrcdeMCFxYXmEob6BELzYRnzuZ5bqiAF4J9W9v45dft4O5reoilephO3c7v/OOXuHjxDIlYYgXxAbo6O4mEw9i2zfDoaFUpXG/OQBCPCCxdsJRfh/1fLV2aiPgfqAgQ5XrBkCEwjWC1X47LBa1kbVCQTCYwDQNFgLVTeTBfBZbBzMwkTxw5S8eWWxjs76ZNzXDbjjb2bt9ANrvAbL5E0ZEUSj7ZoktvSmew32Bk3uXweBFPaMzkPVzlcsMmi5/5of286YZONncmCA/cyqOTCf74Y59jYW6SaLjM9isgz76io62NeDwBwKWJibLZtz7rDzgdtEQFtgfpNbX/V0Ym/EAXQNUa0BSxkKRkB1lClwtHaEKSzeewTJNIOIplmXieV0XcqkQUAz2hwBOHXmRBtbNtz0HC7jx94RwP3LGf23Z3kRLz5F3J2ILL0JRNSFd87ViOgpT0t2ncs9PkZ954I2+950Z6QkX0cAfpjjv5f49d4FP/9mU04WMaVqDwlTma7/mkUilaW1qQQjI3P8fk9PRlWX9lPsImxCOSdP77p/1Xl1Fic79aDfHW6FBUa2Wer2hxXvssWB2WUA2OSFEllGEIelKSfEkxl/bXQRGpK4gso2pt37yVaCSC53lMzc6QzWXRpFa9XmVB5PJZWtt7uO/W/dyxJUbSn6Iz4qLhMj07zfDoFMcuLJHO5eltT7B9IEZfbwft7Z04nsZ8QWeBLr5zMcdjzx1maWGGWDRaju7VaOT5Hol4nI72DnQZZDOdvXixDOkh1nDT1pxjoOhISEImTC4qXLcCDaeazKtqmBVxmTmv9QqqgPiJxGC/olkQqe69tqKRQyMpmnuk1zsupQzQMOsQ7zoSkrAJE4s+rnclAcnAuRKNRNm+ZQt6ubZ+Zm42QN6ScsVjSClxHJuS6xGNJbnt+uu4pj9BV8SlPeLSHjWxZAG/mMMIxcj5IWbTRWazMJk3OTGe5rtHjlEsZDF0DV03yn6IeuL7JONxOts7QAgcx+X80AUKpVIwh75/2WJ8S4PuVkmuqJjPrCZNZRlIGTTVajbH6wmHVecmNvdfVpDUE+yV+KmYQKoO9jRiQVdSspRXLGbVlUWlAdf3aUkl2bJxsGxa+szMzpIpB1kake0qClo2n8dH0te3gZ6ODiIGSK+EwEMh8bUQOUcxNTPL+MQYmvCJhsMIIcsNHhpNWp9EPEFne3tVGb0wdJF0NouuaVUE0Mv9pKJB8Gd6ySdfai4OK4rclYx3hSKgOUpc/e5p5ACsy8zWZ+D1C6CWBxgsAE3C5KKPp64UjlDgK0VbSwsb+gfKnU59FhYXWUqnA0iaSgptnaCr1Nk5to3tOOViiwC7P1g4PigfyzCDSmWodVKvE3R++RlaUilakimEDAgzPDbK4tJSuQFUDQJWrBWnK7fW7W6RuB5ML/u19O/G+GsZUTTIl7hy+MYmWRoVsOi1v6REfclY3fF1ZIG63Aqoh48TNWsgV1K0xgVhK0h/vtwTqfLMaZpkfnEB5ftsHNiAlJL2tjZClsX84gK246yst1NBmRoCNMMgYpq1C6hKjoLE9z1Umcs0+/F8D8swaWtrIxqJVDnB8NgIC4tLdWhnlYKZBoyN+jmmliu5lCuDaYg6ODhWdgBRdceUaBibJpF6Ac1ora+1PISsVJBWXLESIVUZnMhfncqr1hduQgqELGe0VNiYrLDPYBflSop4WJAIC/IlVQHtbirEKt+vjKdpGgtLSygUG/s3oGka8VgMywqxmF4ik86UcXVETamqdND0VW28socS/FqFjiq3upGV3n7B+5ZkC6lkotrp03FdhsdGWVpeDnr/UctrQICQEiHUim6p1O3+WEhgO5AvNTH9RI0Gq2nCauuicYAmaRxCSDSrNfFB0SSbS9Y5X2o9CkSNX9WHpRvbwzSmAqwzXrXMWVCGkAnSxVwfSk6tcKQ6idXJCNhg/fWk1Kp5hNFIBNM0kEISi0QIhcJ4rhPAsHp+9V5WjydWZKcFMEqVenoPKTTCoTCdHR0kE/EAZUNK8oU8F0eGyeZygcwvi5L6OalPiVMNhR/xsCAWDsK+Bbv5cwtZh6S+znhr0WXl98rjJTb3qZX8odahQlR2gBA1VDehyhZNHc8RzXhz/WqsjVfpHqJWoISWW6YoMDVBV0qglGByyQu8YPXjKLF6vIZGV54XdN/s7e6lvbV1hTmbL+TJZnPk8vmq4wbR0KmkothVxJ4KcIsjkQjxaIxIOFLnz4bZhTkmpydxXK+KclqB2am/V4UfcJM6+RfkCCp6Uhq+UswsK1yvro1ctWVomWPW5VbWxgs4VvN5byLT68YTicE+tTZYsKomMlRRKJq2B2edz5e3AhrFfCoqaI0K5rKKdF5dxg+iqmjbtQLXisKmaEm10NvdjVXOyA0UWh+7rPwVi0VKpRKe7+OXX7quBb4EAaZpEQ6FMA0TyzSr2rcoZypdmppgaWkZIUU5Mnl1WrtSkIoJWmKChUwQ+LlsuneZfdfGU2uoeGspA7W////L4TZHgJ3HJQAAAABJRU5ErkJggg==" type="image/png">
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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">
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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

    
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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAABg5UlEQVR42s29d5xk11nn/T3npspVnfPM9OSgkUbSSCNpFKxkyREbR7CBxcSFFxsw7C5rFrzAsmDSsiSDYcHGNg6ysY2DbMuWZEVLI40m5+k0nXPluum8f9xKXV3dMyPLmO5PzVT1vXXuvec558nP7xGpHYMKASiCH8HqH9Xkb83O+4H+iIabbfZQV3vslRznB/Sj1rlNAbpqJLC6ioG/T2R8edOtVn1W1fNUw22ruuuphsdSqx5UrPltVXdfjftIrfscV/pcr9ieqFykgdY6ouEG1OVpLa7y+NWM0YwRNZuUyjOJNa6h/p2ZlGgg5vfjXq923lWTjd24JnTR+OUmMy8uc7fiClbA5c75DzvGy7jOf9gxRI1+QlQ4QJl51VioaLJq1IpBVMOVRMOVlFo985c7p56FizXGqF25zGDVyvUsGoWAajzWZOf467Nb0fTzSj6llFqxt0STvaYUa4qW4DbXmQ+xxpyJJs8r1p7z4DLlu1MB3XV1BTLncvJIrTtr5QlolHSikSWJK5DzYtX74BlFg0Su/75oeq9SgK6BLkHK4LMUonp9X4GvFL4Prg+uC37dNZotveZahWCVmG04r/kzN86HKj+sWENbUbWVchU01QXiCtT6y0moK/2ueFlnifXei8uPXtl9mgamDpYOpi7QNdBEQHwhG2S0Cojg++CVF0HJVdgu2A54fjDh4ipmQ3xPzyxehhl2ebro1W2kxDpaYBN1csX2FE2upZqoPWLVe7WGCGjcIdRp2vU7T62z9ypnGzqEDQhZAkur7XgF+D44PiiPlSKjvDA0CaYBFhA2gwVRcqFgQ9EBx1NNOIJqKrxEgy1xGQG2aj6u3jwTTcxA1WgGriEE6oVPVRkQqwkr1tJHxVUJk/UsUXUV59WzUEMqIiFBxBSYRkW3UNiuwHYVtgeeF+xwv8IplKquZ00Ei0XTwNQCrmHqioglCFsC24GcDfmiwvXFZa1/9T09s7pCO6Bh0zXV8lWVlroQ4gp40OXY+PfKjl65MZQCKRVRC2KWxCoT3nGh6CgKdrBrPT/Y/avntEZCp+6aUoImFaYGYUth6QLLAFMThA1Btqgo2ArfFwjxH2c+Lme06q+Ih0msc/zf0+mlFIYGiYggYgk0GRA+X1LkS2B7qqZJi1U6U3PFomIsKPDdYLyCE1wnYhFwAzPgDrkSZPIKx6O6CJRa4zrfT89fM/qvQQ9dqZfpcxJN3IzrSYDvkzep/vIRS5AIQ6gsq9MFRa4YKG81+7cmA9WV3Ee9iiNqi6HkBAphoQSREMQsQSIkMDVYLkChpKqLTKlXYD54eRKgqYu1fgGI72V5in8HbnWZc5QCKRSxsCARFugSirYiXYCiHZhyQoimIk68zPuoXwxFJ9ApSrYiEQkURV3CsoRscR0O8IOQAM04QE1vbbRwX6ntq9bxhn+P0kcppIRkWBAPB5p7pqBYLihcr/w032f+K4TAV5ArBUplMgyxkKAlKtCkz3K+sgjE9ygVryRacDVsJLgbXTVEg9QVhSGu1jWkrvL7VyZ9pBSkIpAIB2x5MafIFgPnTcVLpv4dAnKVNea4sJBVOH6wKJORYFEu58H31SsUH/xeXHar7QtdiLV8UaxrZP0g48Gq7MlLRQWJUOCkWcwFip5SYgXL/fdUwIQIFmI6r/C88v2Fg2PL+eDYDz6KvlJ71wOzV9X8OWr1XdZ2kWrig2bVLhOiSbC24aRG1ny54/XnCRGw2nhI4HqKuWxg3ol6pasyRsO6VQ1OLFGvDChQ9Y6Sqq6wchxVmSO1+l5FOVaSLSp8pWiNBsqhUqosDkT5Hq9uPpqfs5IOYk26rY4fBGJJBWZgPX3VFXASddnjl2f5l7M+1jueCAc7y6snfv39N46hrtBUEnU6kGh0w6g1PTdr3WuuFBxri0MyUrNMmp1+JdZY/TniZdCl8RylKuHgFbtmtcKgVENo4nJLTYh1r6ya7fArGEMpRSwUyFZfwXxOUbQDcbC2Pbq2DFRK4fsKpcqvei5XvsfgJRvu98qUYoGgYCsWsoq2uCQZBU9Brli2TOo5yZVv35pbXLH+nK05Rtn1L1QQDRRrreyyv1oKUQ6OlBeCUuvbAGssRdXAymoLa40xxErOZBmCVCSIAMxnA5kvRf1CbRQBq+/D92t/MwyDaDiMZYUwDQNN06ocwPNdSrZNsVQiXyjgOE5dnECsWHCrQ9216wsBeVug5aAtqkhFwPUCP0KVa4nVc9ZUfy8vUiEEsiy4V0j0KxyjfgHpV+KTlnVm4ithI4g6nWBdv3l5DfiAIaElCrqmWMwF7FVU/QCiar80sriKkut5HkIILNMiGY+TSiYJWSGklEgpq7u9pjsoPN/D9xW+71MoFlhKL5POZCjZNkr5aJpW5h7rs1shIFcMYgupKKQigrm0wlMNovdK57VsVvoNNLl6G6C8ANayAdQKp4dqDCS9bMteNMtVW8NcVYBUgXs3bEKmEGjZVYWrykXLscHqeAGLC9i8Tywapa2llZZkCl3Xa9ynPqTbQEkpJEIDTUqMWJxEPIHrOswvLbGwtEgulysvnrKiW/m37vr1OudyXqHrgngoeJ7FnFrbSlkrWaDMstUaHpvL0afRg39ZDlAv0S7nI7jSxGJV90KtIb3rFlvMgrgVhF8XcwpflcO5qn48tUKBFSg8z8c0Tbo7OmlNpTAME9/3A+6jFI7nUSwVsW0bX/l45d2uaxqaDNi8aVqEQha61ADQND0YL5lifmmRmdkZbMdBk3JVuLcxD89XsJRVWFqgxJZcyJcuM19q5ZxUQseVxX8F3t51PcP61XoS1RW4di7nf+IKfFqUWb+pQSIa7K7FbODhE41hblE3OULg+z6+UrSkUvR392JZFijwfR/HdSgUCmSyGWzXRZXPXWlmCqQU+L6qigdTN4jHY0TDEUDH0IOFkIonuDQ1wdLycnBuk/mq6HhSBPJ/IafoTATKrO0EjqMr5aDr7eyXE1IXye0blRA1mVx5X3lwVSdMqw9U3kX1ytzlbNq1xgsUs9p41f/LTK4lFuyWxRws5fyqfBZSBsrpSuZbvZfe7m462zqqwsF2XdKZNNlcFttxynpDTR4FRJdNn8f3fVCBXW+ZJrFIjEQ8jqEbZZ+AYnp2lonpqRXPJqVsyhU9pUiGFS1RwXI+4Aor071YRQ8hBKK8wBrZeEXMXakvoX48nQpRRF1GimjIpm/4XDlHrWF+qDWE/lrjUTdebVEFSRexUJB9kymUb5paYmPtfoK/+76PaRhs7B8gEUvg+R5CQDqbYXF5iZJdQgpZJfQqtqlU8wBb+d40IXAch/mlebL5HK2pFLFoDBT0dHYRskKMXBrFcd1AQVxn12YKEDYhHoKiLchXHFnN5rQujqDW2tFCrDnvrHGuALRQW/KDDbbTihVUvzMrr8t6IETzYFB1vIoJU5bFzUSApkFrVGBoMJ8NQq+iSeK78n2EpuH7PoZhsGXjIPFoDN/38TyP2fk5FpaX8PxAa18voFm7v+APvr/6/gJOoeF6Lrl8Dsd1CIfCCASRcIhYNEY6k65aHapuXqucrqwP+H4QOJJa4M9Ql4n9VOes4nb2K58rtuQVeIZqKcbBog61t3xQVOwlIRBKrZJjsvIg5WONr6oPtmEMUVFYGvNkKxpc3XmwMpwdCwkSEUGmAJlioC0LtVIlrlxblVnzlo2DREMhfOVTLBWZmp0hXyigVRw5Va0zMPlkZcspVecU8uvmz0dIgVZnIqLKIk0ET1YslSgUCoQsE01qWKZFPBYlnUnjum7VZl/lUBPgegpdC7ic44Ht1M2HWG0BiDqlUiKhfK+ifFCo9emygr6V98kdmy5rPlZkrXqFQmvrjacIUrW7EgIpYWq5EtpdQ1EsE3/bps2Bsgdkcllm5+fwPQ9Rx+5RQQRRSkGxWKRou+i6iWVa6LpE02pL0VcKx3FxbAfbtrEsnXDIwvfB970V7KhiOXS2tRONxhBArlDg/NAFXM+rKoe+Wu0wMjToSQlcBTPLCvcKFEJRXnx+3WJ9uT/65R3IomZzXfECuEyhpJR149VHZoLrxKwgiXM+q3DcOotX1Nk9MtgBupQMDmwgEg7jeR6ZbIaZhXlQCll21FR3ja5RKOQpFD0G+vrYs2MDB27YyY6NXfS1hUjFwDJcXAfmsz7DUyVOXJjgyOmLnD4zxvDYONGISciy8MqKYSCuAhE0PTdLJxCLxohFImwa2MDF0ZG6UKFPLRMlEK2OFySvtMQEUTPwFaywcZvZYRXO5V9pnsA6lLocBwicK3JNWX3lyQtipZVQcWtWrOYye9cldLdIPB+ml318v8b7hBLlaJ0o7zyPTQMb6Wxrx/c9ltJp5hbmV2m7UghczyWTK7Bnx27e/vqbue/gNnosm6Xhl7AXzpGem2FxMY+ybRIRja7OCImWVoj1U0zsZsxO8syJcT7zpWc5c/488Wg4ILxSVERoZbF1tLWTiMWRUmNmboaR8Uvo5UVSc17VylelVPSkAsY9tezjeTUxsbrgVFCL37wMl1xjUndy+6YrKA9vOCjWH/SKQ1JNwpupKLREBHMZRabYPK4kANfz6OroYKC3H1AsZzLMzM2W5XrZVCzb8+lsno7WDn7hx9/EDz/QRzQ/wZOf/zzzIyeYnM7wzDkYW4SiF9QPuG5QC9Aagp09GjdstejrGWD7Xa/G33Qtn/nmGP/wL19nYXGeeCwSFImsWASKrvYu4rEYACOXRpmbny9bBqsnS/lBtLA1HiSULOeCPXe187du6sYae1Ikt2/8D1DEXtP8u5MSFEwu+3hN5KEQAs/3icdibN20GV1qZAs5JqenqPcPi3J8IJ0tcu/BW/ndX3kDHZzjma9+hW995WmmcvDcRbiUBscVgAb4PHhgJ+dH5zg/OVdVp5KG4MZ+l7u3Ku48uJXr3vgmTpe28b//7ts8/vQLJOKhWs6DEChfIaWgp6uHSCiM67mcG7pILh+4jpsF03QNulMSv8r5rkTMfu+k00JtLR9coXY2U/Mr0a+qNtnkuFjneDONdJVzItD8Y+Ege6ZgizV3gaZpbN6wiZAVwnZKTM7M4PtedXKllOVoHvyXn38Xf/QrtzP61Cf4zN99jH/+4gW+MwTfHZIsFSS+r6MJHV1axKTgPT+8j5ZwmCPn5jA1C6UkBd9naEnw5Kjk7MU5Fk8/x7WJed7xztejJ/t46vnTaLpCk1rZ6RWYfKVSiWgkjGkEesPi8lJ9SLSmmQvK9QQQDxMUrjiBwrry3EZz6TLz3sQKqHNugKj4AVbxiMbXWvnHV3hciOa+gjp2LaWgNRboAgs51XTRBLvfo6ezm7aWVjzPZXpulmKpiNS0qofQcx18TP7vb/0SP/faKA/96e/z5S8/xT8+bnNyWpItSQzNRCmdFjOJZZjkHMVduzp53wfeTEcqwhOPDJOzQwgpMbAQQuD6MLIEzwx5zIyOsUe+wOtfdxt9O27gkSdOIHCRWjnQJCWu6+B6HtFwmFAohOt5pLMZtEYuIAKNwPUgakkMLQghq8b4dnUuxUr/9xXTpdG+FGihttQHf+BZairwiiUigkyxHCBZzfuDqF4kwoa+AaSQLC4vsZxO14gvJJ7ngLT42999Lw/smOOfPvRHfPGbw3zuiGAxL5FoSGGifANTRglpBm4J+uMW/9/P30ymmKe3t5WIr3HseBrPB0uLIHyDECF84VHyPI5PSU6cTzNQfJE3v3YPAzsO8vUnjyFUjRMJKSnZNrqmEw6FCIfCpLMZbMdpmvLmq0AURK0g3dxxv/85hOUFINZZRWsktVdZimiaWrWKJa3OvaqeJwjSqHUpWMgG0b4V36+TlRv7BohFo+QLeWbn52tcrbxAHBf+9vd+mbs3T/DRP/4TPvvYDA+fkdiOwJQhPKUTN6Lc2D/IRDpD0fXY0h7np959DXc8uIPf/m//hO+U+NGfuBt7PsvQSI4ZJ81tG/q5dXsPh8dnMaWOEIKRJY1jQyX6Sid48wPb6N1+kK88ehhdA1G2nIQQFOwS4VCYcCjIP6gEjlbMt6gkokAsFBwr2M1Y9/pkWUGXNQsfarLk+8QB6kMV64sJpRSmLmiJBTs/0PxXCruK4teabKG3qxvPd5mZncVx7WCiEUgBhZLD7/zqL/AjBwr84x9+iH95bIHHzws6TJOuZAvFYiDr8SFEjLlCge1dKX72x/bw4Nuu54sf/Qrn5yVjF0a5dX8ndzxwHSHX56VjC4QNMIXi7HwGAx3QMKTGRNblu6dt9oRP88b7dmJ07OPRp48SMrWyaStQvofrusTCEcJWmHy+QL5YCETBCs+mwPMhpAccMW8HeY9ilfBvtgrEy1IM/0OIgFgoKOtarNbVNblRIdnYP0AoZLGUTrNUYf0odE1jYXmZn37nO/iNHxngM//nf/GJb0zz2HnBzq4Ev/Nrd9KeTPD8qWlcXyGlxWQhTbcV5cffMsiDb93FS48+xW/82XP83Dt3MZ0u8o0vPsWdt/Zy3W27mB/L8OjxcS7OLyMFGIRpETGE0lCay3zB5qVzJbZyine+7S7Gix189/BxopFQ4E4WEtt2MEyDSDiCoeuBQriOCRcPCRxXUXK/v6ntsppUoaiu2EaPXsVpV3MGrlyF6x6v7IL6capujUDzjYYEthskfNSya+p2v+eTSiWJxaKUbJvF5eWqM0lKSSaXYf91N/ObP3kT3/3Un/KZh8f49nlJ3DD5vfffwM5Bna984xy+a2KKEJaIomOwd0eYB9/YzzNf+Tb/7Q+/w87ruxmMe9y2q4VDCxF+/f2fYXr0ND/01q10RAyKlAIOojR+7k3XcvvOHmxPw9AMTkzBf//HOY499Nd84F072btrD7l8vszqA1GwtLyM7TjE43GSiUQQZm7c3SJg/bYHkZCoppnXz2Xl/dXSpf6cyvsVYfEguXF16sBqS0KteK17vDymWGXNBHcUoHUEFbw121dVlgxKKTRN0N7aihCC5fQyjmOXxxK4rkM83sYf/5d3UTr5Kb751cM8fE7g+5IHb27n7gNx/uxvDnN23qXdjJDQQhTcPJYQ3Hl3B5OXJvitP3+RpXiSg4MGff2DXLulh+u3x/nWiMOf/PEXSaVKXLc3BlLDFy4uirDlYkgNHx9NmRhScnhW8vefH8E6/zn+13tfSyiUwPOccr4hlEol0pk0UgjaW9qqvor6lA5RTlwtlGpzg1o5l5X3V0uX+nMq72XD9ddmS2qdc74Hf0TYDL6fs5sf93yfZDxBIhqnWCqSzmaqOoIUglyhyPt+8t3sS57h3z71Jb52VsPxNTRhcO+NKebnchw754IwuGd/G6+/tYuSgIjhsmuLycc/dYhpQ+OmXSn29BmcPLKPYvZGDu4IsX1vJ185WuTYkXNctyeG76uA2JrORz5/kSdPT2OJCJ6v4/g6YUPy5LjGP37sce7sPM/P/ejryeZK1V0mhKgmlSbicRKxWBBYajKd+RJIAs/k1ZtVTd6vkTIkKwUPlby6VcRu8qc1j68TL1rJhsrZvDKopi2V6+7rQtU1xUgI2lvbEVKSyWRxKiFWKcnmstxy40F++rVbeeIzH+H/fbvAkmugKUlLKEzKgtlFyBWCUHAmo0hnHCylc9/BXnLzsxw6v8DO7V3sTSqEKxkY+CEE+0jJAjcNtGOlwhw5OcaGnjCv3bcL4ekY0mK8lCGnXCQaraEwm6Lt+PhEklH+7Bsez/zrJ/mF1/Zy3Z7ryBXy1Yyokm2TyWXQdZ32tvaVllSdi6TkQsmDsCUqoZh151Q1SfhbQZcG2lXey0rpdIWlNlM0V7GRZsdp6uRr6vep/Jhl0KaCHdjAjTkLvu8RCYeJx2LYTjBxsuwQUr6P1EO8/yffhHPuczz0tfM8PQqtCQ3ft4iFNFw7j2ElCBk6YTSePD7HNw9P88O3d/COt2zFsixKElS+wKGzY5w8ZfHNrw/x9UeGGR62efH4BVrbDMYm5rnzjo28/727ufuGftJOhpgRQwgDRznlfAGFrwziEZ3xDPzJp6fQhr/KL//4fSjMsjIYxCYy2Sy2Y5OIxQlb4VVcoJLuXrCD+TG1y8+pWKP8fS3aVd7LZju+KbtQl0kbVlcoRuo+hszgrgsl1eS8wERsT7Wi6zrZXA7bdYI8fhHs/vvvvJvbNxd5+F//jS8cCxJN2ltTJCJxbMfBsUt0tbeytT9OFIMCiv4ejTe+sQNLLvD1b51DGBq9PSl279xI3vd4+vFjHDl6DhGOceuBzbQnNYZninzsHx4lGZvjgVcnaTVDLDtpfF+WzUmb4ewyHbEkiUQMQxN8/Qx89fOPcP/WAnccuJlcLlflXHapRC6XxzQMWlOphqhebRoKdqAThAzRfFqvRDQ3O6fuf6nqat9WlWqoulQkKuVTqokIWPnbXIzUjgUZNRAyKIM11SqOqnehghSvZDKB53mkM5kgHKwUvu9imBF+6q33MffC5/jmU7OMZQNrOYSPIR0cJ8LkdBGKJX78HQeIiCUM5XHDHp2OeI4P/P5jfPSxOfSoxda4z+T5eZbSl9jcV2BDS46T58bQ55bYuaGL8SJ86LPD/N+//Da7tzts6AFXCGxl85Z9m9jR2olCInCwlItCkXMFH/tWjrnnv8hP/dB+hBYG5VdL0NKZNJ7vkyrXKaD8lbozQYaQ6ylCRqAPKKWuat5Vk1/UyoRRWamOrSRcNgs61GrkRFMxcbnj9edUvIJ6mf0XHYFfKemuG8P3/TKLDJEvFCjZJYQUZbMvy7133MuB3jTfffxRzixKhAxk5eBgG5GIyaLjMLpsMHzsEA88MMjP/vQBbt6m8/q7Ujz95AUOjbskB0zu2N3PiQvLnJrOYoSK7O4+wab+44ioxVeenyTmhblp32ZISj735CIXz4+xe7uOUDqmNDgxnmYx76KJMEbYZOuWdqQWgA6eW9b40sPPc+fGDHccOEAml69WIhVLJQrFQiDiojE8X62Yu6DUXFB0guQYTbIqWHe1dFk5fvBe1u/KFauongPUJYQ2rsIrOV45p6KNBN6/IPGl4Kz8e62EW5CMJxBSkMvnqulUvu9jWTHe85Z7yZz7Gl98ZolFTwcJ23rDbOzZw/03d+H6Di+c0hkameXM45/knW+I84f/cy8D7T5feWEBs1Vj24YW0lPLpEWRgzcnOTbhY/Y/yUjxPHkP7runhUPnzrIpIunZECNnCA6fmGP31gS3belF8yVHZ2eYLebwlM+917WyqX03+7a1AopITOdTTxWZP/k4P/PmW5FaiIqt6/ke2XJ4OBFP1Hhww5wVHIUmwDKacICrpEv9OZX3ssL+69w+NXbRIFzE9yx8aiImZAT2ru2oBrwBVU3yTMTj2LZDvpBHluVnPp9l397ruXmT5PjTj/LUEMQiFkoqeq04SxO3Mj6xyJbOGBcmdf7pW4JjJ0bxl4+zd5uJaYW5tFjEiBnEPYfeDsmd+7sZWnCwUlGOLnsUwlGSHTGWPcWDB9sJk6UzqkNIMbtY4i1v2MiP/0gH23tSKCBiauzqjzI6mmF+8iYSMgQaGKEQx+fg8Uee4NZB2LNrF7liPkhNF5J8Po/jOKSSCUzTrMuRrNnqthPERkyjaV3Vy1LGatD2KhABlSTDCu+psQtRDdaIuhzfVWHaht+m2ah1qqeUAksXlFyB59eOBfciy1G/KJZpkivksR236g/3leBtr301pZHH+MKj08wUJd1tETQpcX3J2WcPkyvluGlvCBny+O5wiIePpEirfh5/6hIf+sgxNBP6WqIkZIGxqTn8osP1m3sY6Ghly9YuOjqS9LX009/WwaHTy4xdmqAnYtDakeTFM8v87d8/xTXbS7zxdS206gkkGjfvjeMpuPjUSUolD6HDlp4IrjD5/LM55NRT/PB9d+CWzV0hBbbjkC8WsUyLaDhSK+6omzPXC7ykIUOU8wOufN6b/SJq1c1CiIoIqFcSmvkPGxWJla8av6hnY6sVlsr/hhaEPUtOXZ1BucqzkjKViMcRUpIvFMrxdYFdKtHXN8g9+7o58/w3+copKNkQkS6WBtdsVURbn+XuvSb9bSHyJY2UqXPtvi6GR+d5/4de5JPPpMkrjQ/915/hR3/219Cibdj5IkOjRb5yeJxHDl3ka4dH+fIzF5idlCRMRfvmvfzWB36T9777NZyd9/iTz4/xz594njtvkVy7I0LecelrM7j7+jCh5DPs2yIxDUlUczE1j+9cFBx+9ilef1M7HZ292HapbMoq8hUxUE4faxTDvlKUHIUhFZpcCVTRXAmsE6lNz6nRDKUqImB95q2uiNGoBiaz8uLVvyswdIUUwYPVvlGTWYauEY9GcRybYrFY9VEUSgXuvOVWOv2zPPfCGYaX4MYtgne84XpaYxaffWqKXGKcp4/McPHiFCEEmzeZHLg2zN9++gyHJ1x6Nob5tR+9mR967UE2dhb53Q+8j9aeG3n85CVaeixOzdr4IZOSWeRbhy/yjre/i/f+3JtIRZb5tV/4Ed7x+p2YCY2PfH2W08dHues2SVIKRocneOboKMttI3zmiQlaw4ofes2t7N/RwlJB8fWnhunRhjm4/wYKxVJVCSuWiriuSzweRysnk9AwbyUnQEMzdVWFhWmeUl8vuJuLgUYVT9YYez2Tb3z/yv2CwNIEvi9wvDp2VP71fZ9QKIRlWRSLJRzXQQpZTrUyefDgPqbPPMu3XwpKaaStGD91HhybjG+wfXATi7bFmSmDnO9y181hTpya4RvHcvRsCPPe1/Tz8++4nbn5LMMvfAW1eJhf+NV383u/9etIpQi1xFjM22zo6+Fv/+a3ufHAFsTiEYZPPUUonOC3f/ZO3nxrN7YUfO6RYQb7FakW+NYRjzwptm7sJ6eFsEuKkRNnUfk8EsEzZ10Wzr/Aa27bS4DMo5DlKGHJLmFZFiHLLANYrJwzxwssJVNbWW7zSvzKmjpQ8yGqBlzuWmFnc/6wis00e5UDGVIowqaG64vA9Kkbo5IbGI1E0DSdfLEQePykoFQqsnnTNm7c0sLpl57l+Eww8mC3xuZtUbpaBKWiz+MvnGd//yAD+iaSEZstPfDVJyfxDcFAR5idA1Hi3ZuZGDlH17a76djxo6RiKX7pp1/Lj73xID1tLbzq+k289637uHtflFhiGwPX/Wc0s4XFuRk6Brazuy9CsifEMxfy2EWb3l6brfFNXNu9lceeO0sh59DbDrt3Rdi8UcdHcXQSRk4f4radLQz0b6JUKlXN3XyhgKHrRMORqsdQVRVBhetX/AFB6litkHUlr70cXVTDsSAYtJJBr2Lk1dPrED1ejg1QUQmEBE1TlNxAu13BksoIYLFIDM/3KJSKVaWlWCxy4MabaPFGOXJ8mEtpuOt6k/vu6mUxuoX3/+wButoUe6/ZTEePz6GxY2zfGCKby3NysgRxnf5UmA197RDp4tLwCUKtWyjSgi824uZz7O9xWJjI4Ns2XdoSRbcXV/TiWj1YkVZmJsdo7dtOKhVjU3uYrA1Dowts2RDi5MwRMCe56+676Ghz+R+/eAvLiX289sGbuP+2KAs5ePLoOD36JW649rpAtMmgzqFQLOIrRSwaW1FPWJkb3wfbDeYtyDZbSSv1Mh2yDSKgGXOp+7xWwnDT1xrsX4EpBZoMNNtGZqdQ6LpOJBzGdR3skl0uI1NITefg9XuwJ57m+LiLKwXX9UhmF13m0x7xkOSOPTqFxQLzjsTVQ0QMH9txmC56tCbD7OkN0943QNE2sfOLJFt70aSD5xUpFWOcHvUwvQKnjo2T1QdBT+F7eXzPpbV7NwvTQ8iWLvoGN9Ae0cAQTC0W2dARwtYMMgLmJ+Z44HqDEAXOjYwxNrHA7laB1OFrh3yWRw5x5w07UUIr70CJbZdwXZdIJFytHaiffwiCQ7oUGJqoyx9aYZs1eX95OklVTr5Y/aq1NGiIMjc9d2VEWzX1JwT572Uodlet8DuIMpxLyLQwTaOK2gEC13Zoaenkmo1RLhx/gWcuwGCnJOJ5UEizOzaKkZ2iFZcP/9sQjlPiLQ/swbMXyWYKeBL6kyYdKY3OgW3MzEwi9DCa2RqYpbpBLrPI8Pgy0nOJmTojCwWUk0EpcB0bK9pObnEGVXDZfe0uOmImMqyRztnklpf4oYMDoHT+4qHjJPFw56bZJM5h5iYwPZeOpODkJEwOHeOGLXHi8Va8cmTT87yg/tA0sar+ALWisYTjBnOka/Uue0X9mVSBo+ppuBb9KvhP9fy5LlGjUlJVBWRAlB0YoknMWQTZREqUzY9aRk8Q1Al6sgghMA2J7ys8PxivktOHCv4eCoXQdINCoVSW/0Fm7dbBrWyIZTl5ZoRLGdjbq1HI+Qxdcjh1fJ7DLywSMzQiLQZPvDROfvEs99+7k0RXPxiS/oRFZ08roe7tjI2cJRztQjMjQUWw75FJL1B0HQbaw2ztNDhy8iK+GzhtPK9IONZNNp9jcWaKDZu3snmgnZglEeEk1998LYY7wfOnp4i1asQFnD2b58jxJU6cy5FZdNnWrrFQEpw9P8ZgS4nBDZso2XYViaRYLKHrJiErhPID0qBqm8z1Bb6SmHoNaEOUHUqB2Kif8xpdVr1qIAGBc61pXYFYu65gxbErrAup/E2TAlMXeCrAy5OydqyihIZDYVBgO3b5JiUlx+H6PbsgM8Lh00vYNpwcsZlYVuQKHt+9sMR0Os2zZ10cD44PZ0lnsszMFXnq6DyRkEFHMsS27f1gppgeH6OttadcPRys/1xmgUzeob8zyu7BdoaHRpibmUKpEgqJYRho0mTowjnCHf1sGexiS0eC02NZDh+fo+jB8aE0jg+HL/rMZ4sMzRXJFG2GF3wuTLu4nuLQsUWi9iWu3bWTUslGiABIwrZtQBEKhaupcvVz7ZVrUQ1drJ73qohWl60LaaSvVKv9B6z6W+Or0c+z6ngDC1J1LEcEyR+N51fiUOFQCN/3sG0HhMRXPoZusnf7ZtzZ05wf9+nsSFLyNURIoogxM9VNa3eC5ZIg7/kMbmnnums2cOzEMC+dHiOqGezYlGTbjq2U0gUyk+doy5xD2ctoRhQpPPLpJUqewjB0dm3uwfGDRFNdBCVqljNPl5piceosWK30DfazuT3KhdElTp88Q1dfJ7v3dOM4PtN5Qaw1Sna+F404ZlygmToDfa2cmlaQO8c12zahaUY1abRo2yilCIdCNQAoVemMJlAVRVDUc916ejRh+5ejXSUW0CxVSPmqjJGnqhp69fPl0shWXK0s5/2gilaTCsdTDeOXHUCajmWauG6QRi0Az/OIRBNs7U2yMHeOzk0t7Oq0cD1FfjmJl+kiVeplajhBzIqB8tjeH2Po0hJIyebBFgZaY+za3oNHHEdG2bn3Rp44/hKzY4cwpYPyCuQKGUaGJrF0xcBAO74PF4cvYZkavr3IS88/zHTBYffeG0hPLNG3eRvd7TG2DaRItkUYHsuzud3C9RWmFmZiNEyo2IO90E4pncRzfG7oj2G2JBkfP8c1G9uwQlF83ys/p4vreoRME71S1l6u/FEicAA5bjB/ouwxrcyf8qsRniszA8r/+75qEAHfxxflAsgKUpZqOKaUQtc1DMPAcWx8gnIxx7Hp7uphQys8/uRFVKnE5NwSOUcRIcYuYzf3xu8hTgqhRdF1wZ3X9aJHY7gSdE3nrn39pFra+PCffpKP/vnfsfWmN3Pbm36WhYkX8HIvYBkei8sFQq0p2tviROMpNnYlmF5eRrpTjJz5POn8FHe89b9yadLn//zqrzB1bozte3bQ32pStG06OhPccf02dA0MEaVDtnMwfjtbrK1EtSRLtmJobJrSgs3TTw6zpVPS3t6N67hVBBbHdTAMs84SqIvOiwBFRJMBgIbilaGLXnXDi7VhZa4KEmiNMSrsX5WrXwQrUb2V8tF1A13XyeXzAfaPEVgDGwY2EnHnOHVujhPnfeaLPpGwTp/ezt27D7Kp5wCPHz3NabNAMjrNztYcR857FDyfa3pSbNnQxb/863Pkzp3Gf/44508c4Sd+9de5753/g8XFs4we/zRzo+dIKRtNeIRjUWKxVr7xtUd54HqD3TfcRyyxlS9/4rN8+6F/RrNzfP2hebzendy0eyPHTp8k7zhsTRWJhqDNSrInup3brnsjQ3MxsifmiUbGmcw5+A48f3KO16kF+nv7mJw4j2mFgjpC1yEUtdA1PUAjbZhYz68jPLU0urVotx5kc0XMyKrToSkAlGpIPlwb6br+nObo4AEHQAUPsrIbbWC8WKYRoGY4ThUB1PU8NvR0I3PjjM3ZeJqOJ8FA44auAfbcvYP2H+/hxo3baY/ESBo+R4+MkgpH6UpoUCoxfmGWbz49xOmciRExmTp7ij/65V/kM//wWUKRWwgl+jl07Ajxrn4SYYM4Gbb1aHimpG3gAIV8D3/yX/4HX/mnD6NRYF5a/OuLc5x68Rx23qErLuiMGRw7Mkxch1Q0wr6ebfS9ZwvX3LmLfe2bMaSG0gS+ZnFuvIRRmGCgpwvHcavw8U6ZG1imWcVPqnekemXxq8tGSNxG2q2kaTOAr2pGUKVJYq0Mq55FiDo0qlpGwGr2vrKYpPK9xpcmA8XFdlfWG1Rgy3TDLFsATvU5NE1nQ08HhbnzjMwFAEKpqE7J87iUmWTi5CiZpye5ODnCZGYJAZy4mOfwC2fAURwdmuGjD7/IQDJBuhjlkSFFwQgRkUW+/JE/4U9+9T8hZC8HbrmFmQvnkKUcY0Nn2T6go7wQjz98iL/49f/M0EtPE0lYHF3QeGbYIKanmJrN8JnHj1CyBSfOTPPSuXkMCYv5DGenhsk8f56x4xc5szCE43mkYhquUqRLoAqX2NDTgRBaFfvXLqdGG4axAgirksBZEZ2aVumFxBq0W0nTFa6fuu8I0ax7+DqIP1d0XDRHqBBl8KcqmEbjGAosI2jy57k1iDVNN+lti1HIT9PTb9DS3sPR8UU0f5F04hhzCx+nfWQn86lnscLjTM8JMlHF4QmHUFTDQTGRdcgXZ7muN0WkpZVnLy2xpd1ie9xl6KWn+bPfOIvb3c+WvT1cGBsl3NXOjn03s5g+zr99/vN06jZ+NMS3R6BYCLGtPcLY/BLDpRKdUZ25jM+z57Mc3GIylxPI9nEyLU+hxnwy3jgzxjEMzaGttYXNbQmWF0fJZ2boa7sBqRlUOlh7roMgWADVyvA6du6roMOpLtUKXMm1mrZeCU1lJURbS/xsZjo0/K53XKnmZmXZAvBUk3PKK6IC4uz5Xtky8JCaQV97mJGReZbS8Ks/8wAH9u2kI6KQ0uGwd5iXzK9zLj2LrhcJRUzMcIh9O1uRhsBzFcKHJRe+O7REp5Xm9oEYIwsmz0zrpHWTwvIcj3z9JXAj3HxgP5t6uvjoP36dubk0SgrO5gy+fUESVmH2dWmcG5/hwlIJzxMBUJPwGdyYQLNChCMGUdNmKLPAE8XHOJQ9hqsKtIYV9xy8hvf+1P2MTirOn59hY1ck8AMohRJBmlgQDtcbRKuqdjX1ygm1NTo0oQtr0G3FOcF7vcJm1Dodale1i7/c8aa4RZU6v+YKihASTdPwPB+/HBHzfJ9oOEFrVHJidplnzjh87KFneXD/Dh575hwvDs3SNuNz/MQ402nBc9OQM2Dn1l5e3a/x9IsznEwvo0Rg7xY9wReOFuiIldiUimLLBM9dytIXstm0pYuJ8SUy/YrTp8Y5f2SEllQLT43liIsIgwmNdCbDC8MOUznADLQox1W0xMO8Y/8ACzMFHj2b5rFzgnQ6x8mLWUquYHROYfT2c8+ONj762e9wfFIxM7vExpt0QqEInl+s1kBWAC0r6CBVVq7AR+ApUXOgVeoo1QrwsTXpshIiqAxn2wykca2K8pVQpk1K/ZuJg7K6X2nXXoeu1oDfJ9E1HV95gc9ASDzPI5FIENEdphdyoMPS3BjtCcHt1/Xz8AWYzAuM9h5Ozypm8tAe9bj9wC5018BwXEquD5rA9yAeUmxoFUws+RweyRBRGa7rjHJ2IczhM7OMnR/lG08NceLUOAs+zMzkaNFCDCYVY1MLnJt26IrDlk4JbsCjXV9RKni0iiz3vupakgmdsTS8NKWIdbex4Bi8MAevOdBHOBbGsW2EhPGZNGHNIRGP43le1RRUvoeu62V8gYZCj7II0GRdG+fKNDcBeBHr0K6yAaXiKn5Vk/dqjfPUylYsQfeMAHC52TlCgKZJ/DIHAIXvBTj/ulfEtXPs6JHMzNmcPDvNa/b30JK06EgIbr2mHV+ANDQ2JDVGzlzk3PAkL11YDNipUghN8sANCbb3SXpbBFFLcGikwOlL87SZihu2tWAkwnztWIFnRhUTaZP27laE5vPSxTRLBcFAm2DHBpO339NNe2cEfIUmJWdHFzh9fpqLR04yEBVoIuhYfsc1HYRDGv1dIV59XYzjp6dYmMuztVNnOZsnrLlEo1F8zy+nf/m4vh9AzwtWzxMVEaCqltMqmjScr9Y7L8gHWDsYLNYILl7t8frgpqeaBZ1rSQ4BMncgEjzfIxqJIL0SC0s5+jraOTzi8Mt/9C2WJobZORDmidMOX3nkNEMZ8DSfcxMuf/XpI8zNp+ltDwWexhLcsCPO3h0pigJ2bzHpb1dcs8Eg7wlSCcGDt2zGFUmUBlnfRLmKTGYZ2/PZsynEvs2KrZtDFK0Iygxx/6394AWmWXfKIJN2+MvPHOPibAkPxfAiPPS18zx/rsC1myyOHz7Pez/0bU6OZehtS5LNZDGFSzgUxlNeuYsKZYQxbVWgtzKPnqqE59cP5IvLBOor7+W/BwCEqAR+yskNzXSIStq3XwVsDtyclhVClw7PnSmSLcG+QcmtB3o4NrJM1M+TURrzKkZfh8U77htkUel4iRSj0zZ52wuwfwXsHIijxcIM7uilr8/i9n0JetvjpEuwpS/KctZDhjV6YwYthmSu4KJFoiwsO7TGI7z59h62DrawbdsAZizFpt4ERAw85ZMveozNu7iJFhaVwTtfs4XWpMWCH8Y1dAyvxIV5wV13bGdPn07GhuMjRQzhErKswJVbCwBUM7AaZWV1/srgra8AShyyPkMUtUYaUdMs4DWOryEW4HLHRA2VvIIhqhSWqYPn4gJPnphhbCbL+95+M7fffRBNOWiawvZLLC+5vGpzL/ff2MPb7urClSaO0onHIqBDe0uI2SWbVEuEHRu7yKRNHj22TN726OuI853vHGF6YpKRZZeLMzk8T+GWXJbzLk+eWmR41GX/7kEGBlKcmUjTnopihHRaYxbSiCF0yTvuaOcNN3ZyY2+SbMGl5NkITaFh88AD1/Led97O8dEcL56bx/EFvu9gGnq56CV47mqv4xqTr+VW1LFuGuf/CujWmP2tUOjl4jCUqPQEEqsRfsX6fgElLuMapha2rMDFr27CJuoQvWtaiq5pCN8JgLGFxPYlv/9/vsk7H9yEp5sUpeLsjE266HHoyEl+4p5dZBem+YoDynPRFWhxi0jYRGGzszPFk0+O8anvzFFUsO/mfkR7kpOXfPSN7Sgy5IsuvVu7kaWg+/NsUfAPj85yZkbxlrdez5buBCjoaImiZZdZzBTQTIutbR57+qN8/tHz5Esew0sCR0rQDF584jBfenIO19BAKlzHRzkOuq7VGliWA2ey4kirw1oXsAJmth43Sol16LIGyGsFXV6ucMiuKBVfWUb8vb4q46zFtSoerHrM/mqnETyKDsRaTe6/aTNZpfHxh0/T32py//V9zOTBarXwNZ+kTHP8+CQxAwa7o4zM23QkDa7dEmF3Z4zvfOs8H/3mBEUFic4wBw5uZNqFWU+xPDpLR28XnYMtxNvCeEiUJdEigiyCh4/O8Q8f/S6b2+NsH2xnsDvB+LzDpg1JTF1x9twSccMDS8NqsVgu+jx442Z6kgYf//Y4mCavuWkLWkQGbWKUF2Q8N7h0Kwkfqok5ptYp0385L4lSdXV7ao16sgY2cjXHqWtqIOrYV/m9EmplbbKonVc5hlJIHVzb5eKFKS4tlUgXFa+9Y4D7b4jjK5833LKRu27o4tS5RWwtzH03D7KchoUlj219CfJLir/+5Gk++fQ8BSkIJXUGt6QYG5njuy+MoukBQmd2fpZQwmDq9AiTEwtoUR10iRYSCEPw3QtpPvThpxk9N8verV2USoJsTvLae3aQlVHG5zQevLWfB27ehF30ue/GVvZs78B2fIZnC8yMTQRII3oF87FubkR5dkRdtnT9/KjaXApWFnisSRdRCSuvPKfyXueKmkd/L+3jKePZ1MCiEOWuIaJOSxS1pk/1FcuVLhshE4o5xb8dTZd3i0D6RW65YTvxxHlefWOS7b0hPnt0gduuHyAb3sQTnz4JSYvR0Qy/f2KGC4suGIJISuParQl8PF48Ocf8bD5oYmHB5HQebT6P8kBGdKQm2dEdZSlXYny+BMLn7JzD7/7VE/Rs6oCowROnZ/mJH7uP3kSIM2fHefd91zFeuMjTpxLs26zz9PN5Zh1BOm3z2UM2mBJZrv5V1Y7SYkXvwpVsWK2G3hP186guTxdBU7RovdF9r66evJc9vsJJpJp5pSo6ol8zccoBEtf3AYmlQyju8bs/dRCz51o+/v8+wcmzSyhrgmu6Dfpjkk987gRPns3wraNZDl43i5kUuJrHRC6DsxjgQetRA90MHDmu45HLFolqHmldInWJwsVzFNKUiLAB0uWX33GAIxdn+YuHXkSL6CjhMpVTpGeXkFGDNtPlm1/4Kt84nGagFdo6W9i1tYvdnTqTY1PMzea5ZluK9/7Sz3Li+Wf43b/7TqDFSw3P92oYQkrUpYWrBlBXVjTGFFcQs7lc97agb6CiARri8n0BLt8/UDVJEKr5ruuvWctDDcy+egdIAJLggpCkwnBga5wud4mD1/QiHxjkhaeOMjS2yB07N+MVC7z6jfcz/cgIX3z4OcSpcd521zZedc39lIoFnjr2KM9dWuDcaI50CV48uciObpMuTbIsfKSlY1g6nqmVExYEwtDwFXzlWyfZuzUJhoZmatieyw/ftZnb999CqreXv/3Yp/nWqSmKsQjv/ulX0+kNI4oFtrbHefyJc2RtyS+87jp2mGlErMSuDWFS0QJCSmzHq4VnK/mRfpPwbX3tXx1wWGMlB1dBO1WGtbg8Uuwr8hIrgAlW+49VFRy5XgTYdomSJ4hGLETO5v/7qxP8yvt/h3BphpCuSHW0ctfBLTx6uIAv+rh3bxJP+ty0dxt7Cq+h5dm3s+Xku3lN+y/xx+94Nz/9wzdz+75utvQliEcSJFyXbMbDxcPzbDzlgynxNIHj+Ti5EtPLDsfOzIImsZXiwVs2c1OXxuc+9kmGH/0qv/DO+xlKK67ZoHHD5jYeebJIxgnzzrfdy2Q+RDwiWRy7xE//yt/wa3/1XZK6Rzxs4Piimhlc76MNxB5rI6+/gnTSrzjmuw4rqUSuVV3XbOq6W9QblpVGy42NT/1y7ztZ1+BJSkmhWKLoaUjdxBeKfbsifP30EuHwHFt6wuzZv4GRUZfHXprioW//Ka+7pY0D17fTY24n444y3f1bFLPtGDO38cJ3u+kYvJ4bb+2m53V9PPzNh/nwyTluPrCR62/ahiY1csvLzC/MMDmTRo+E2bNzM3e0eHzg759FGhb9rRHMbJHf+Odx0CRPf+4kf9pn0bs1BZ7N//yDT/HCuQzXXRdjYryNW27ZyaVTJ/nCkwscXTJ4zXVJxqaX0c0QRVcESOeV2sdymrbneVX3eH1nkYrHVK3Io64V2KzEehBXxBX0l+tNUpdhLSurfuvRLZqIgDLb8zwPwzBquQBSkstlcTFIRKMs5zNc16f4jquYzfq8c183R09O8pdfOkbRFIRMk2eOzXPnXdczOn6OZ86eDgCmUwavufYJNu/bxJJuUBi/gaGpSf7hG+f45ffczM+//UasaIJQIkY4piOwWU6nQXhECzYf+O+fZaIkIKwQeYevXpiFhIZu6rhLJRZmpohLn6PnM3SENPRWg+mhUT76zRf4o/+8DX1rL186MoyueWxMwAtnobM1TsEW5PN5ZKXPgBbAx9i2vaKcviYn62J8dSXgTcXuFRJWv8pt/rK0RLGmRrhSB3A9j1AoVNX+NS0IwdrKpKs9wpGRKY6MQn9/CxsGFCF/mY98bYHZIhAyyeR9/FiIhFXiX4+eZWw5uOC5aYfvXJjhmq4ZHrhmH1HVyyfP/SP33t7LLYNxfvHnP0xMKBKpMB/8i5/juWcvccOgQzZX4n//3VN85sUMZluMnb1JzpydoXdjOyVdMLtUZMPmEBvaIswtLlHUomTDGj/1+h3MXZziYtrjLz93mve/fSvXbE2RHRH8xSNzALSlwuRdjUw2ixYAACGEQNM0XK8cEZVipcZWiwyjmuFDX6kWWKdV6lyJFfgKIIJWGEClIdbKxpgB2/M8r7oLXNdFymCCsjZEwyF0EzwP3nzXIDuSaR4/Ocv//MDrODSc528eehqURldXBLtgM5bxEUkDhEB6CjvrUAzHSPkPcrbwHU4vZPn5m3r4rx/6FiOZ4MEfvDGEvzTFf/nAQ1haAMtyKg1Khw+8Yz/7+6L8xO99jVdt7uIn/tOdfPHbL6GX8nznxBTz80XeeGArb7z9QUZHD/HxR0f5b79wG+2t3Tx19FF+9P5B3CfTfHlqEc2ClkSUjC3I5bKErSAPQkqJ1CSe5+IrHx19JWdVtRjA99TBr24RyBWwkWtAvDVBH1pZfdBYWNAUsIgVrdQb89eV8nHLKVGV0udKt6+ppSLdHSnCUYGK6gwkcqQzeW69aRtdrsfPv+5OdvUnoOih+z6enYWQRLMMMHX8kEWkV+Pd+27DFTYvTj9KOBLhyIU0IxmB1WahGYp7b99IKZtnTknOl3RO5jVUWNK3IcGdOzrpatexfcFXHztNrHCJn3tNH8ePTvPPT02DprEwvcTEcx5/8/kj7N2Z4o03bmFPW4Qbb9rLxNgYWzo9lCFIRKCjPcnUQgHPd6tuYE1KhALHdeuQU1ZuPlFX/LEmnmNjqR9N6EsVJOqqUkLWUUdZd5xaF+21r1FJBg0KIwIt2HNtJhcLtLekiJgSQ9N4/tAIpuZz7MXz/NLvPsxf//k/sKXFAgQLCwU29HayZWs3vpRoQqAk3HVNH23ubdjGS5wcLyI1yeRiFpEw8E0DzxBsH0ywuJDBET5aXGIldURIZ//mFs4eHyVqCeIxyVzR43MPn6Kn3WJkdhFMAy0Km9s3sWhPMmfn2dpu8pt/8BC/+b8/zviFEfJFydnTk0jLJG5Ce2uKS/N5lOdWrR5dCxiy4zirlOTGOMv6PSNFk/fNkeCvKBxcA5F6+SynsqCDdCaxeiEIghRpqGbFSiFx3RLjczkSqXb298P//tl7aO9oZ3gsy+/+6xJ2Rxuz6QKTYzNg6VyaLFHKF/nVe3uJ6BJfSWItcG1oH/mlLM+PPkfW03Hx8QyJCum4QhBLmHSnIhw7PR4k+1g6nqETSUXY0Brm1LkJWuM6IVNH6JJTZ6egkKdvIIXwobfF4sYNg5xbOIlyYXh0kVAyzvFchD/53AjLSzmu2TPI7/z83WxKQaKlk0tzmSqaOCp4bkUwD2th7kq5MvP6e+0pI1eEcNXKsG3V1FA0QaBYC3KgOapxLRu4bBzWjV9hdyXHDtLDdb3q/5bAyNQCsdZuOsKCDV0pdvabzGcFejTEhk6DV920jYllJxjO1Pijh87x1586gqPA9zwObmghvrCd+NYzzLolSIZZKvhcnHfQTR3lK1riOn0tkvMTBbB0NEPDzdtsbbXIp4scH1lCFbJBA+pIiOPDWZbnsxzY14nyPO7a3EOpoHhhdAikIOsavP7WLaSMEn4kTtYW7NuokdBNtvcIwqlOxqbng1T58jzoRpAUW3LsBhrU5lcKVasbrHcNotauAVsTQkIhqYMME6I+f7y+H1CzDJNViX9rsn8hRCXzGU3WtT+t7yZKUBDieS6mbiDKtrFp6FyankFFush7If74L7/A9MQ8126Js7nb5JkjU/zhx55lMmcErf8sjdkinJh02NId51139/KmfZsJ950l0pvn7gN7kdLD1TVKmgwm31NsbAuhu0WODy2AZeEpnx3bu3nfm3aymC+RK+ZxslmU46J0xaUsHD46wYEdrVgpwabIACfGJpkp2hC1eH6owB/+8zNML3ncMBhhY3eMY8dG+KO//SqmEcXWOhmfnsE0ggWoSYGh67iuG4gA0Yx1B42s/fKGXFmTIdZR95u18ClD9l0d8Lx62dUDfrm0SZOq6ihaAUIpBJ7r4jguhmGU08MUhm5waWKctJ9gz2AHZyYKzKddXjw2wW37+njTq69nPAPSKkOPSg0RMhBtYabGl9gqPOYv9LPgXeQDf/Ytpscv0dseJZGIgBZo3bg+G1p1igWb+bwHnse779nBb715J1v6W/mxn/wR7rh1ECVdNnalGOhJ4vjw/NEJ+mM+t+5owc8muJgewvPL/f4Mycgy/MSPHqAtaXLizDSjc4qpZZfBvnZmnRiTU5MYuhEkgUiJoRs4joPvuTUchnp2LRRSlotC1ZX0ChaXpY9Ua4iAlZke5VLFFRdtyPKpDzM2AyxSQUcQWbVjVo4nBDiug+3Y6LqOlLLcLUQnnV5iaN5h97YBpIS5jEsyaXHzxgTFqQmI6TVHk1Qo00BJnbRd4OJwiqmRCM+dGGMoAy9czPMzt23n79/7Ovbv7scpBux2a2+cS+OLHB0rsXNbG9u0HJ/78jE+/JEnOPX0Ed73E/dSchX/633vYnMqAkLyzeM5DD/He/YPknM8zkxPgBUKZs/Q0SKgJia5ZXc3WVuwkPWwdLhmx0YuzJTI5ZbLDa59pNTQdZ2SY+O6Xm3X1tFHlDmA56/sJVjrxL4SAKp5aZhaATMn68uEajnoZRRJLUCgqKJJ1H2u71+zEo9+jURRIVFKYpTz3SrmXnU8KkgZRaTUMA0DUGiaxC7mODE8x/btW+luCcqrEqbOX33mMMenMnT0JMu17kGja2nq4PncvquNTn0HpdALPD+2jIhbKE3y+3//FH/zN//Kj+zfjBU2wPPZ1m2SyTs4KLZG4c8fOk8sZnBsvMBv/t23eOo7LxGKxvnzP/hznn5pBJEKc37WZnx8GeH3cOLSaWYKqlr9qoRiQ38LXzk8yUe/+BKpmEE677KlUzC4eSvHL07j2EW08kK3TBNNSIplwCgh6rI/yiJZkxJdl9XeThXIWdlQCiaalvk10jdQspubgfVx23KsnvrY/RW591b/VFBBpKglflQ7g5dZXr5QRApRxs4NFrqmCY6cGyHRMcDewRSZnIMeMtmxo4v79nZyz54+kB6U692Vq4i3CLbIzTiuy4XZkyw5OqRCnJ4uYocNHj25zPTQEFs6Ipi6T4du88ihWfAkS0t5kp0hdvSFODebx9ckn/jiCcJuFiccwlE6UgqWbHjsxQxHT+W4uDANSKQWPKimK+7b3cYde9vZtq2fsGWwXPC4aXsULdbLsQsjGFpFBxdYpgVSkC8Ua1xWNKbVBfUVrqrsP9Ukzn8F5ruoFRpI1SRTBKVQfgDO4JfVd9/3V3y+mgyhwArwcRwPlI/UVAPgRI0lFYoFfN8jZFogyujghsGpi0Nk/Dg3bG/F9SURS7G8MElo+Tauj76a7l4T3wXh+SjXZU9HlFB+O45+nkPjRQiZCMfHi4XQW8MIQ5LLLdEXskmFBYPtOssFF3xJPufzrvu28OK5pQCJJCw5NZlnYS5DLG4ELkIh0WKC08NJpuZdZuwsGCb4CuX67BmM4y/vwC/1MzMzi25ISkqwc2Mrc06Cs0NDWKaJV24pb5kmnutRLBYaQui1+RHCR/k+ruuXaaLK5WT+FWVuNWZ+BQARVS2fun4BorbTqyFaVnxeCUrc0CKyDqCm+l6B45VrAGUFwKjWdp0yHnCpVMJ2HEIhqyweAvt4dnaGi4sa2zd0YZo6w5NFSmnF1s43E1FbadN8kBJPSKIp2Oj34jhzXMoeI+3oaBEtcAurcl29oSE1D+E5tEVNRqcKPD9sI8I6Z6cyhOwcj55aCsSGobFYVFwYz1Eo+uB5eK6ivTXElpZBJgpjZG3QrHI+vwYtvmJ36l1sSN3J/EKW8TmbmCnYtrGX8wsaC4tzgb9DKTRNw7JMbLuE7djV3sK1ymCBUBULClyvZkqL+mLbhjlvuv/rGlYTpIStVWIq6mr8KskK6zQEWlP3rHXMqgAaaFKghL9yPCGQZW9gsVgkHoth6galslJYyCxxaCjNu/fsoSt1mFyhRNyK829PHsaPnCASLxeU6Aa3bYjR09HP9q4MzrkwqawgXQwqjTRTR9kuytKImgbnxha4eXuMeEyyrHyUDbfvb+fCWJqFtIvWYeF5kryvWM66DHSFQbNBKq7r6MD3Nc7OXQJpVGsa0CW6DQ8/9RwlMU5Hp8lCXtGVEmzadi0fPbOAXcgStVrwPQfLMDF0g6XccoARIFcbZ0oE+IqUq4Try4NXG4BibYSIFbVm1IsAao6FOjZRX6e8Fnu/EhEACs8rg0VrjVhCqi7TRZHN59B0DcuyguQI38fQJc8eO0Osdx+bupNM5zw8R+POyAEimRZmF0uETI1fuKeLB3b14bjDfOWZedrM1/HX/+kNvPbmXnraw3i2ja88rt+aImoEqOR370qSzboc2LOJzt4W3nl7H8oMYySi+ApCIYsHbt5AW9Rn/2CSwU1dmKbNntYNTCwtMpGzQdcwQiahRARsn8XlNBtK/dwkbyJbcvAQXLcphtVzLYeOny7b/+V8R8ssd0LJofwafErjXBqawgsYUJUDqEZaXYUIQKn18QFEXbJGlUBCIJqEolZYpWtUrXi+wPNU0FxZqdUQMuWFks3l8H2fSDjCciaNUoqIFeLUmZOcmr2Dgzft5OTFGYpujkzqm0T1UyykFTv6w+Qm0pyfz7C0XOLa3j6mxi0e+1QXb7t/gJs2HGY8Pc38QpFtyTDffukCdl7ni4/N4nsF8lonP3pLD6dPz3B+zMOMaOzqjDG1WKK47PBnX5gkHEoj8lF2tEXIjiU5N38Iv9zC9v7rerlusJ8P/fPjLBYcQh0vkZUFXAUdEcnBG3Zyclpx7vwZQqFQNQU8Uu4VkMvnyuxe4TdUTgkRwOx7XlAfWK5LD9JFGquIRE2HVKzfUVhXsAKftlmwRpXbnIhGQKGqYVDTRoWqqzpo9EsphePLQAeo10ardTACITUKhQKO7RAOWeh6ECrVdYOl9CJPnJzkbVu209PxEpfmlpnTHkKzcsiSRZt0aGsNc+hsjsdPZdjducQb9s/i+rfz1S/00ta9DSPaRZwZSu4pjo1lmV1WnJZBcGWwa5E3m2F+69PjZB1IbozTaRkcn57ikYteYL74WWLted531wEuvJAjLZZR0sAM61iZeZj12NwbZuJSiUzyMVzpsVGPEjMF/Vuv4ZOnJsnl07QkErjlBBjLClGySxSLxSB4VZc5RV1piK4JbK8GGV+V3qoRLKhWlb1qg1cTUAM6ygpRRT2B1+hIWIs2rq7+XYkM15z1qLIiqMkA5kSt6GtTLgQhAInM5vOYpolpmNXUcEOTPHboOCKxkcH+FopemNniEkPzBbJ5j8GNbWQyPo+fytDeEeL8ssGHH5khn/8auw58h3zxOUanjgNn+cKzY8yVJEarhQJ6+sL84U/v5GvPzZH1BDJpIBH4ro1vaBitIdAV8VaDX3/NVnZ3+vz6e+O87z13EY6HsHMlPv/ENGcvTqK7NiVHcHZ2kqXiMpmcZLAnjBMd5IkXjmEZWlkL97FME9PQyeaC9jFUi2NWJtNqIgCKrmAsiiZofI21GM1Bu2vHUAot1Jr84OVyBxstSnmZ4/XnNXqmdQmxkCBfDDqFywZmIYXA93wMUyeVSOG4DoVCYBoZus7swiK3HLiLbdF5nn5hCF8LY1qCtJIcPjHD6fECoaTOf33nXsansozNFzk85pJNT9Pdt8hycY4nj89yKQdEdHzX49Yb+3n/63v58hMjfOmFDDKuIyyDUrbIG65pQ7a2MDI2w417e/jAW7fy3efH+KNPX2Bhep5ffNf13HbrHiZns2ztibG1VeeRM0t0xnVaIwamFSJXzPGjr93PkHEDn/7q1wiZRnVTpJJJIqEwUzPTQbNpTVs1p0oFLWPiYUGmoLCDROnqObIa2bs8XWTDMS3UmvzglSSQrOfqudzCqVofKnAFx0NBu1jbrVUNU5c8HBSG+rS3tKJpGtlctgw0rZPNLIPVyhtv28nE8GkeO7HE6w5sRuJx8mKWH3vdDm7bHadNFvjkU9P4IQ3lKyYW4fCwy/kZl6wDd+7fxI3X9PKO+3ZwoLvIR/71PI8cK9DSF6Hglvv7lXwWZtP897ft5h1vu58Htro89ugpPv50GlsITlzKkx46z1tftYm33dlPorDM5x4bZjTj8+pr29i3vYdvvDDDvfvi3PXg2/jIoxc4f+5UVf7rmkZHWxtKKcanpspJsSvr/ipAEFFLEDYF6XxgBYgm0f6rzeIA0KwrWACvSIl43VWjoWBV5+3mMSspBK7jEY1GicViFAqFumQRycziMvfdcZB+a4ZPPzFCuujyU6+7Fte06Ilm6bXynDy/wOEFgZKScFgnEjMJRUzCiTDhVITsUgHTKXFpfJovPj3PVN6gsz/GgzftYrFkE4tHCSejLC77nDk7hj93mk984xIPH3ewEiFME3xPcXTMZuj4CV545gyPPDfJvKPz+tu3cmDnAP/0zYsUnSK/+KZrKHbewUc+9zVkObPX932ikSgtqRTLy8vMzs+XofGhmR6dCAfyOpNXa57zcn40qywCrmTVfC8cgTp2FrGCxpHZYvMHqaRGG7pBKpXC831yuRxSCnRNZ35hjmjbRh64JsnszBhDs3k64yGkH2JytoBXytGfEpxOa2RKPq1xk1QkgmnqtETDtMZiREyTdM4hV5Bs3xjn/htbaQ+ZtC/tpK9rif1bEkTNOKbUWM57HL6Qp+hbpFIxdFMS0gWe71J04MwMjM17CAO29LfR39FJrljg0PlZ7t8b44F77+OhowWePfRdouFwVcNvbWkhZFlMzcyQy+WCXINmwVsJqYjA84M5E2sQ/3J0oQk9XnmYuCtIDrUdiIZEgBrmrx6jUhW8nElj2zbRcBjDCGLlSEnYMvnSt57gTTe9i7ffdYJvH3maP/j4YdAE73ltL29481sYe/Fp7rdz/OPTM8xnbGaly617OhieLzF1aQrNc/EA5XqMzMDzJ0Apya3dOZ49Oofv+xSFRtEHTfloUuAu5ejtkXS3RXnhTAYNCcpl/0aDvZsM7n7VDTx9+BJ//YUXkEB3h8Ebbx1kPnItX33s40RCocBZ5AdtcSPhMKVSieVsphr9XGVWl/0muiYolNQKI+x7oYuoDwc3aodrao5rnXO54/VBShW0i5FCYWqw6vpVTCFJoVgkk8lgmiaxaKxqDVhWiImJYb50aJwde/bzrnu3UQwbXLsrzoFtLQjieFYbt+/ZxP6t7XhK41W7k7z//mt49Y4+POVjI9Etk3DUIo9gHoO925K0bZNcsy3FIiZFX6fTSCKFSUloYElef10vv/n2u7hpeyu+gr3bU7z+zq1s7W+jf/P13H19P1v6NQoIXn9TO9uuu4OvHh5ldvoSpmkF2r/yiUdjmKZJOpOhVCyuKAlvCOpiaEEgqOQ2wG1cLV1Uw3cBzWpJfLAhR/tKkgTXZy6iSRli2TdQcVPGwkFcu2CXEatXAAkE2qrv+ygUrakUUtMCR0nFgSElw5Mz3HnwVWwzL3Fy3uHUhVl6RIEPf/JJHnlyFInk1TdsIJtfZiCu8bVvnaEtVOBiGqIhDQvFQHuUmcUiO3tj/KebE7z+1beztU3npQuz5As69/b0MbScJZpQxCyDLRGbR586S1eHRdzweeuBTZw8O8dDj07wxNPHCLkLPHa+yM7BJO+5ZyvFnvv4v//yBYTyqkTWNZ2OtjaElFyaGKdUKqFVIoN1CA6BAzbQ/g0dlnOUm2+skYArGks/L0O7oBKpAkcqqg2kV5f1NTQhbnq8Dqa0WQ+buiYFrg+uJ7AMVuDh1ZfCKUDTgrqAXKFAOBQiGolUuYBpmkxMjPDpp4bp2XmQX3xVP5puUJI+eqKNkRw8dfoSnXGHV+9uZ3J0moIPh84vge/yZ7/yZg7u28jJoQU6O5PcvztJNNnKtz9xI1FrkNfd0EJbS5RvXLjEAwc38Ue/8m4KBZcXLy4zvJBnbnSKN+7vpr8Vnh9aYrwAVixMtlTEQ/CuA51s3PcADz1zjtmZCXTDqNr+0WiUUChELpcjW5b91RjbCmsoMJMtA1xXVPGBVjeEaKSLaE63+nPK7wMOcNUVBc2Kyi8nfWrnKiWwdLBMyJeo9spb6b8UVbBoTWqkkkkQkmw2W3WWWIbJyXPn2Hfz/VzfnsWzbf7h4UukHY+2DoMfu3sz0UQHbgncUpqi4/Ps+RIP7k/yqz/5Dix3nsePDvGqHR28aptibuR2unt+gqQwSaWeJGuHmMtl+eW3b+aBe+7nueef55kTy+zr1xnojNDf2YEKpejrTnFidJrltM3hEZu33NbHm+6+gdPqGv76E58kbJl1hTGSjrY2DMNgcmqKbC5blv/Na+Y1TZCKCgolyNlqjZKtKykQb1b9oyoL4OXYAQ0XFE3YTFOvRHAjmgwUwZJD2bHRHGhIiiBEnIwniYRDQaPFUgnKGTKlYp6h2Qx3H7yTDfoYk2mf4xfnObAjztyUzce+dgYPjY64TnvK5Oiiw66kz/Cxo+jpMeYXXOLCx/XynD91Cze1v5snhx9lfOkb2DmbmOnTrub4zuMvMr+4yETO4/49MaxojKdP5/iXh8+g+zbJmOL0WImbdrTwY/dsILLjDfzBJ7/OwtwUhmFWXerxWJyWZJJCIc/YxESdk2S1oa4UhC1BLCTJ5BW211BdvS57X0sKrBQTgSdwRa/5Zo0FGllJk+M0sBnRREzUgsMoIBaSeD4UnLJHcA1W5TgOhqGTTCQDx1A+V8bLV4Qsi5HRYVRikIO7BtjZbnNqIc/54XkKRY+RpRK//pM30tM3QGGhQEtXJ5NT0zxzaonpZUUyajK1uExS9vHNIz6nT8zw6PC32dNbYCY7hSZMXhjyeP7MDJqpuH7XBnoiGgdu3UtPXx//+vgZEmEYWSrR2xnlva/fwvYbX80/PbvA4089RiwaC6Dqyilwne0dmKbJ1PQ0y5k0Wtnz1+ylECQjAkMKlgsK329o39eMva8QpWId2gXvr1IEvHJOIV9B2AiUm1xRrVvrJkRQR59KJAlZFo7jUigUqsCSIcvixWNH2XnDvWxPFtnSJnnq1BznJ3Ls3xUm4eb51NcvcHqywMHd3XSmElyzs5/777iWsOaRtNJEc9dzYryTUV4gorq5td+ko3+cge5u7rrrVXR2trOpI0ksHOPrz01y6OgkKT2DIsfz50skExa/+oatXH/dDTyzNMCHP/4J4tFaR3DP80glk6QSSQrFQrD71fpFfpqAVFTguJApKF4haMAGR9APYAFU7FtdD1ycBTvAwl/LAKmUTEtNI5lIVLuK+H45JCoF4PPS6QscvPuH6fRGuGZzJ8cn5xmZLTA6kubCssd9N/ewsbVELJlgb7/NNx8/wwunFzE1xcWpJXaE3sqtqXuRTolpvopu2Tx1PEchPcd9t0TJlKLEzSKe1PjG0WkmpxYYzQs6Wk1+4y3XsWdzD7Md9/F7H/k4uDZC6lWSGYZJZ3s7mpRMTE+xnE4HmT/rzE/IECQikkxRUbS/9yqgpgsg1JL8YI2F1LMT0VyLfIVelYyjWFji+lB0qPYpXH1uuXt4oUAiliASDiOFIJvPVUGWDcMgvbzISxcneNU9r6OlNMT123p48eIcF6YLxOM6e7tDdBpZTp6d4MSpKT71dJo337+NLRtamZuY5d7Ue5jORLh+wOQSn+HW27chom3841fP4i1Pszg3y6ZWmFgocWEhz2zaZ6A7wm+8ZTe7NrRhD7yG3/y7h5ifncSywlXUc4COtjZikSiZXI6x8fFq1s968xOLCEKmYDkX9Fn8ftDhB8YBIIA9jVgCXQpyRf+y9Ymu6+L5PqlkEtM0sUs2JbtUFQWWZTEzPcHZ6QJ3veq1xHLnuXFLJ4uuzenxZV48uUy+6IDnYITjdLWHSKgsZ4cXaY+XyDkez56fo2PDYWIdZzk7lkcrZYjFdHTAdRwODRf58osLOKbi9l0tvO8Nu9nc04q36Q38zse+ztDFM0QiUTzfq0LAx2Mx2lKtKBRjly6RL4svtQ77FwJaYhLPUyznFd8X/v+DFAEVPcDQIWpBwVHrioEgl1CjUCwQCYWJRiMYuk42n69m1vi+jxUKMTo2xOnJLPe8+q0Yi8e5Y+8gqZjJC2MzjMy6jMwp7ruhlYVFj28fW6CIDApK1AQDVg/z5te5VChwZsLlxaEMO3qj9LTpfPa7eYbSDioiec+rNvMzD+6lJWzgb3sbv/3//o3TZ44Ti8arxK80f+js6MQwDOYWFpicnirb/eqy7D8VhWxBUbC/L9y/QQSspVmKJvjhV3u8yTn1tYGxsMT3oeRcRmyUmysVS0VSySSWaZX1gVwt8dT3CYciXBof4aWLM9x08HXE/QV2dOhcN9jGYtFhYjnLk0czXFgqMdgbRtc1lKMRtgrcdeMCFxYXmEob6BELzYRnzuZ5bqiAF4J9W9v45dft4O5reoilephO3c7v/OOXuHjxDIlYYgXxAbo6O4mEw9i2zfDoaFUpXG/OQBCPCCxdsJRfh/1fLV2aiPgfqAgQ5XrBkCEwjWC1X47LBa1kbVCQTCYwDQNFgLVTeTBfBZbBzMwkTxw5S8eWWxjs76ZNzXDbjjb2bt9ANrvAbL5E0ZEUSj7ZoktvSmew32Bk3uXweBFPaMzkPVzlcsMmi5/5of286YZONncmCA/cyqOTCf74Y59jYW6SaLjM9isgz76io62NeDwBwKWJibLZtz7rDzgdtEQFtgfpNbX/V0Ym/EAXQNUa0BSxkKRkB1lClwtHaEKSzeewTJNIOIplmXieV0XcqkQUAz2hwBOHXmRBtbNtz0HC7jx94RwP3LGf23Z3kRLz5F3J2ILL0JRNSFd87ViOgpT0t2ncs9PkZ954I2+950Z6QkX0cAfpjjv5f49d4FP/9mU04WMaVqDwlTma7/mkUilaW1qQQjI3P8fk9PRlWX9lPsImxCOSdP77p/1Xl1Fic79aDfHW6FBUa2Wer2hxXvssWB2WUA2OSFEllGEIelKSfEkxl/bXQRGpK4gso2pt37yVaCSC53lMzc6QzWXRpFa9XmVB5PJZWtt7uO/W/dyxJUbSn6Iz4qLhMj07zfDoFMcuLJHO5eltT7B9IEZfbwft7Z04nsZ8QWeBLr5zMcdjzx1maWGGWDRaju7VaOT5Hol4nI72DnQZZDOdvXixDOkh1nDT1pxjoOhISEImTC4qXLcCDaeazKtqmBVxmTmv9QqqgPiJxGC/olkQqe69tqKRQyMpmnuk1zsupQzQMOsQ7zoSkrAJE4s+rnclAcnAuRKNRNm+ZQt6ubZ+Zm42QN6ScsVjSClxHJuS6xGNJbnt+uu4pj9BV8SlPeLSHjWxZAG/mMMIxcj5IWbTRWazMJk3OTGe5rtHjlEsZDF0DV03yn6IeuL7JONxOts7QAgcx+X80AUKpVIwh75/2WJ8S4PuVkmuqJjPrCZNZRlIGTTVajbH6wmHVecmNvdfVpDUE+yV+KmYQKoO9jRiQVdSspRXLGbVlUWlAdf3aUkl2bJxsGxa+szMzpIpB1kake0qClo2n8dH0te3gZ6ODiIGSK+EwEMh8bUQOUcxNTPL+MQYmvCJhsMIIcsNHhpNWp9EPEFne3tVGb0wdJF0NouuaVUE0Mv9pKJB8Gd6ySdfai4OK4rclYx3hSKgOUpc/e5p5ACsy8zWZ+D1C6CWBxgsAE3C5KKPp64UjlDgK0VbSwsb+gfKnU59FhYXWUqnA0iaSgptnaCr1Nk5to3tOOViiwC7P1g4PigfyzCDSmWodVKvE3R++RlaUilakimEDAgzPDbK4tJSuQFUDQJWrBWnK7fW7W6RuB5ML/u19O/G+GsZUTTIl7hy+MYmWRoVsOi1v6REfclY3fF1ZIG63Aqoh48TNWsgV1K0xgVhK0h/vtwTqfLMaZpkfnEB5ftsHNiAlJL2tjZClsX84gK246yst1NBmRoCNMMgYpq1C6hKjoLE9z1Umcs0+/F8D8swaWtrIxqJVDnB8NgIC4tLdWhnlYKZBoyN+jmmliu5lCuDaYg6ODhWdgBRdceUaBibJpF6Ac1ora+1PISsVJBWXLESIVUZnMhfncqr1hduQgqELGe0VNiYrLDPYBflSop4WJAIC/IlVQHtbirEKt+vjKdpGgtLSygUG/s3oGka8VgMywqxmF4ik86UcXVETamqdND0VW28socS/FqFjiq3upGV3n7B+5ZkC6lkotrp03FdhsdGWVpeDnr/UctrQICQEiHUim6p1O3+WEhgO5AvNTH9RI0Gq2nCauuicYAmaRxCSDSrNfFB0SSbS9Y5X2o9CkSNX9WHpRvbwzSmAqwzXrXMWVCGkAnSxVwfSk6tcKQ6idXJCNhg/fWk1Kp5hNFIBNM0kEISi0QIhcJ4rhPAsHp+9V5WjydWZKcFMEqVenoPKTTCoTCdHR0kE/EAZUNK8oU8F0eGyeZygcwvi5L6OalPiVMNhR/xsCAWDsK+Bbv5cwtZh6S+znhr0WXl98rjJTb3qZX8odahQlR2gBA1VDehyhZNHc8RzXhz/WqsjVfpHqJWoISWW6YoMDVBV0qglGByyQu8YPXjKLF6vIZGV54XdN/s7e6lvbV1hTmbL+TJZnPk8vmq4wbR0KmkothVxJ4KcIsjkQjxaIxIOFLnz4bZhTkmpydxXK+KclqB2am/V4UfcJM6+RfkCCp6Uhq+UswsK1yvro1ctWVomWPW5VbWxgs4VvN5byLT68YTicE+tTZYsKomMlRRKJq2B2edz5e3AhrFfCoqaI0K5rKKdF5dxg+iqmjbtQLXisKmaEm10NvdjVXOyA0UWh+7rPwVi0VKpRKe7+OXX7quBb4EAaZpEQ6FMA0TyzSr2rcoZypdmppgaWkZIUU5Mnl1WrtSkIoJWmKChUwQ+LlsuneZfdfGU2uoeGspA7W////L4TZHgJ3HJQAAAABJRU5ErkJggg==" type="image/png">

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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAABg5UlEQVR42s29d5xk11nn/T3npspVnfPM9OSgkUbSSCNpFKxkyREbR7CBxcSFFxsw7C5rFrzAsmDSsiSDYcHGNg6ysY2DbMuWZEVLI40m5+k0nXPluum8f9xKXV3dMyPLmO5PzVT1vXXuvec558nP7xGpHYMKASiCH8HqH9Xkb83O+4H+iIabbfZQV3vslRznB/Sj1rlNAbpqJLC6ioG/T2R8edOtVn1W1fNUw22ruuuphsdSqx5UrPltVXdfjftIrfscV/pcr9ieqFykgdY6ouEG1OVpLa7y+NWM0YwRNZuUyjOJNa6h/p2ZlGgg5vfjXq923lWTjd24JnTR+OUmMy8uc7fiClbA5c75DzvGy7jOf9gxRI1+QlQ4QJl51VioaLJq1IpBVMOVRMOVlFo985c7p56FizXGqF25zGDVyvUsGoWAajzWZOf467Nb0fTzSj6llFqxt0STvaYUa4qW4DbXmQ+xxpyJJs8r1p7z4DLlu1MB3XV1BTLncvJIrTtr5QlolHSikSWJK5DzYtX74BlFg0Su/75oeq9SgK6BLkHK4LMUonp9X4GvFL4Prg+uC37dNZotveZahWCVmG04r/kzN86HKj+sWENbUbWVchU01QXiCtT6y0moK/2ueFlnifXei8uPXtl9mgamDpYOpi7QNdBEQHwhG2S0Cojg++CVF0HJVdgu2A54fjDh4ipmQ3xPzyxehhl2ebro1W2kxDpaYBN1csX2FE2upZqoPWLVe7WGCGjcIdRp2vU7T62z9ypnGzqEDQhZAkur7XgF+D44PiiPlSKjvDA0CaYBFhA2gwVRcqFgQ9EBx1NNOIJqKrxEgy1xGQG2aj6u3jwTTcxA1WgGriEE6oVPVRkQqwkr1tJHxVUJk/UsUXUV59WzUEMqIiFBxBSYRkW3UNiuwHYVtgeeF+xwv8IplKquZ00Ei0XTwNQCrmHqioglCFsC24GcDfmiwvXFZa1/9T09s7pCO6Bh0zXV8lWVlroQ4gp40OXY+PfKjl65MZQCKRVRC2KWxCoT3nGh6CgKdrBrPT/Y/avntEZCp+6aUoImFaYGYUth6QLLAFMThA1Btqgo2ArfFwjxH2c+Lme06q+Ih0msc/zf0+mlFIYGiYggYgk0GRA+X1LkS2B7qqZJi1U6U3PFomIsKPDdYLyCE1wnYhFwAzPgDrkSZPIKx6O6CJRa4zrfT89fM/qvQQ9dqZfpcxJN3IzrSYDvkzep/vIRS5AIQ6gsq9MFRa4YKG81+7cmA9WV3Ee9iiNqi6HkBAphoQSREMQsQSIkMDVYLkChpKqLTKlXYD54eRKgqYu1fgGI72V5in8HbnWZc5QCKRSxsCARFugSirYiXYCiHZhyQoimIk68zPuoXwxFJ9ApSrYiEQkURV3CsoRscR0O8IOQAM04QE1vbbRwX6ntq9bxhn+P0kcppIRkWBAPB5p7pqBYLihcr/w032f+K4TAV5ArBUplMgyxkKAlKtCkz3K+sgjE9ygVryRacDVsJLgbXTVEg9QVhSGu1jWkrvL7VyZ9pBSkIpAIB2x5MafIFgPnTcVLpv4dAnKVNea4sJBVOH6wKJORYFEu58H31SsUH/xeXHar7QtdiLV8UaxrZP0g48Gq7MlLRQWJUOCkWcwFip5SYgXL/fdUwIQIFmI6r/C88v2Fg2PL+eDYDz6KvlJ71wOzV9X8OWr1XdZ2kWrig2bVLhOiSbC24aRG1ny54/XnCRGw2nhI4HqKuWxg3ol6pasyRsO6VQ1OLFGvDChQ9Y6Sqq6wchxVmSO1+l5FOVaSLSp8pWiNBsqhUqosDkT5Hq9uPpqfs5IOYk26rY4fBGJJBWZgPX3VFXASddnjl2f5l7M+1jueCAc7y6snfv39N46hrtBUEnU6kGh0w6g1PTdr3WuuFBxri0MyUrNMmp1+JdZY/TniZdCl8RylKuHgFbtmtcKgVENo4nJLTYh1r6ya7fArGEMpRSwUyFZfwXxOUbQDcbC2Pbq2DFRK4fsKpcqvei5XvsfgJRvu98qUYoGgYCsWsoq2uCQZBU9Brli2TOo5yZVv35pbXLH+nK05Rtn1L1QQDRRrreyyv1oKUQ6OlBeCUuvbAGssRdXAymoLa40xxErOZBmCVCSIAMxnA5kvRf1CbRQBq+/D92t/MwyDaDiMZYUwDQNN06ocwPNdSrZNsVQiXyjgOE5dnECsWHCrQ9216wsBeVug5aAtqkhFwPUCP0KVa4nVc9ZUfy8vUiEEsiy4V0j0KxyjfgHpV+KTlnVm4ithI4g6nWBdv3l5DfiAIaElCrqmWMwF7FVU/QCiar80sriKkut5HkIILNMiGY+TSiYJWSGklEgpq7u9pjsoPN/D9xW+71MoFlhKL5POZCjZNkr5aJpW5h7rs1shIFcMYgupKKQigrm0wlMNovdK57VsVvoNNLl6G6C8ANayAdQKp4dqDCS9bMteNMtVW8NcVYBUgXs3bEKmEGjZVYWrykXLscHqeAGLC9i8Tywapa2llZZkCl3Xa9ynPqTbQEkpJEIDTUqMWJxEPIHrOswvLbGwtEgulysvnrKiW/m37vr1OudyXqHrgngoeJ7FnFrbSlkrWaDMstUaHpvL0afRg39ZDlAv0S7nI7jSxGJV90KtIb3rFlvMgrgVhF8XcwpflcO5qn48tUKBFSg8z8c0Tbo7OmlNpTAME9/3A+6jFI7nUSwVsW0bX/l45d2uaxqaDNi8aVqEQha61ADQND0YL5lifmmRmdkZbMdBk3JVuLcxD89XsJRVWFqgxJZcyJcuM19q5ZxUQseVxX8F3t51PcP61XoS1RW4di7nf+IKfFqUWb+pQSIa7K7FbODhE41hblE3OULg+z6+UrSkUvR392JZFijwfR/HdSgUCmSyGWzXRZXPXWlmCqQU+L6qigdTN4jHY0TDEUDH0IOFkIonuDQ1wdLycnBuk/mq6HhSBPJ/IafoTATKrO0EjqMr5aDr7eyXE1IXye0blRA1mVx5X3lwVSdMqw9U3kX1ytzlbNq1xgsUs9p41f/LTK4lFuyWxRws5fyqfBZSBsrpSuZbvZfe7m462zqqwsF2XdKZNNlcFttxynpDTR4FRJdNn8f3fVCBXW+ZJrFIjEQ8jqEbZZ+AYnp2lonpqRXPJqVsyhU9pUiGFS1RwXI+4Aor071YRQ8hBKK8wBrZeEXMXakvoX48nQpRRF1GimjIpm/4XDlHrWF+qDWE/lrjUTdebVEFSRexUJB9kymUb5paYmPtfoK/+76PaRhs7B8gEUvg+R5CQDqbYXF5iZJdQgpZJfQqtqlU8wBb+d40IXAch/mlebL5HK2pFLFoDBT0dHYRskKMXBrFcd1AQVxn12YKEDYhHoKiLchXHFnN5rQujqDW2tFCrDnvrHGuALRQW/KDDbbTihVUvzMrr8t6IETzYFB1vIoJU5bFzUSApkFrVGBoMJ8NQq+iSeK78n2EpuH7PoZhsGXjIPFoDN/38TyP2fk5FpaX8PxAa18voFm7v+APvr/6/gJOoeF6Lrl8Dsd1CIfCCASRcIhYNEY6k65aHapuXqucrqwP+H4QOJJa4M9Ql4n9VOes4nb2K58rtuQVeIZqKcbBog61t3xQVOwlIRBKrZJjsvIg5WONr6oPtmEMUVFYGvNkKxpc3XmwMpwdCwkSEUGmAJlioC0LtVIlrlxblVnzlo2DREMhfOVTLBWZmp0hXyigVRw5Va0zMPlkZcspVecU8uvmz0dIgVZnIqLKIk0ET1YslSgUCoQsE01qWKZFPBYlnUnjum7VZl/lUBPgegpdC7ic44Ht1M2HWG0BiDqlUiKhfK+ifFCo9emygr6V98kdmy5rPlZkrXqFQmvrjacIUrW7EgIpYWq5EtpdQ1EsE3/bps2Bsgdkcllm5+fwPQ9Rx+5RQQRRSkGxWKRou+i6iWVa6LpE02pL0VcKx3FxbAfbtrEsnXDIwvfB970V7KhiOXS2tRONxhBArlDg/NAFXM+rKoe+Wu0wMjToSQlcBTPLCvcKFEJRXnx+3WJ9uT/65R3IomZzXfECuEyhpJR149VHZoLrxKwgiXM+q3DcOotX1Nk9MtgBupQMDmwgEg7jeR6ZbIaZhXlQCll21FR3ja5RKOQpFD0G+vrYs2MDB27YyY6NXfS1hUjFwDJcXAfmsz7DUyVOXJjgyOmLnD4zxvDYONGISciy8MqKYSCuAhE0PTdLJxCLxohFImwa2MDF0ZG6UKFPLRMlEK2OFySvtMQEUTPwFaywcZvZYRXO5V9pnsA6lLocBwicK3JNWX3lyQtipZVQcWtWrOYye9cldLdIPB+ml318v8b7hBLlaJ0o7zyPTQMb6Wxrx/c9ltJp5hbmV2m7UghczyWTK7Bnx27e/vqbue/gNnosm6Xhl7AXzpGem2FxMY+ybRIRja7OCImWVoj1U0zsZsxO8syJcT7zpWc5c/488Wg4ILxSVERoZbF1tLWTiMWRUmNmboaR8Uvo5UVSc17VylelVPSkAsY9tezjeTUxsbrgVFCL37wMl1xjUndy+6YrKA9vOCjWH/SKQ1JNwpupKLREBHMZRabYPK4kANfz6OroYKC3H1AsZzLMzM2W5XrZVCzb8+lsno7WDn7hx9/EDz/QRzQ/wZOf/zzzIyeYnM7wzDkYW4SiF9QPuG5QC9Aagp09GjdstejrGWD7Xa/G33Qtn/nmGP/wL19nYXGeeCwSFImsWASKrvYu4rEYACOXRpmbny9bBqsnS/lBtLA1HiSULOeCPXe187du6sYae1Ikt2/8D1DEXtP8u5MSFEwu+3hN5KEQAs/3icdibN20GV1qZAs5JqenqPcPi3J8IJ0tcu/BW/ndX3kDHZzjma9+hW995WmmcvDcRbiUBscVgAb4PHhgJ+dH5zg/OVdVp5KG4MZ+l7u3Ku48uJXr3vgmTpe28b//7ts8/vQLJOKhWs6DEChfIaWgp6uHSCiM67mcG7pILh+4jpsF03QNulMSv8r5rkTMfu+k00JtLR9coXY2U/Mr0a+qNtnkuFjneDONdJVzItD8Y+Ege6ZgizV3gaZpbN6wiZAVwnZKTM7M4PtedXKllOVoHvyXn38Xf/QrtzP61Cf4zN99jH/+4gW+MwTfHZIsFSS+r6MJHV1axKTgPT+8j5ZwmCPn5jA1C6UkBd9naEnw5Kjk7MU5Fk8/x7WJed7xztejJ/t46vnTaLpCk1rZ6RWYfKVSiWgkjGkEesPi8lJ9SLSmmQvK9QQQDxMUrjiBwrry3EZz6TLz3sQKqHNugKj4AVbxiMbXWvnHV3hciOa+gjp2LaWgNRboAgs51XTRBLvfo6ezm7aWVjzPZXpulmKpiNS0qofQcx18TP7vb/0SP/faKA/96e/z5S8/xT8+bnNyWpItSQzNRCmdFjOJZZjkHMVduzp53wfeTEcqwhOPDJOzQwgpMbAQQuD6MLIEzwx5zIyOsUe+wOtfdxt9O27gkSdOIHCRWjnQJCWu6+B6HtFwmFAohOt5pLMZtEYuIAKNwPUgakkMLQghq8b4dnUuxUr/9xXTpdG+FGihttQHf+BZairwiiUigkyxHCBZzfuDqF4kwoa+AaSQLC4vsZxO14gvJJ7ngLT42999Lw/smOOfPvRHfPGbw3zuiGAxL5FoSGGifANTRglpBm4J+uMW/9/P30ymmKe3t5WIr3HseBrPB0uLIHyDECF84VHyPI5PSU6cTzNQfJE3v3YPAzsO8vUnjyFUjRMJKSnZNrqmEw6FCIfCpLMZbMdpmvLmq0AURK0g3dxxv/85hOUFINZZRWsktVdZimiaWrWKJa3OvaqeJwjSqHUpWMgG0b4V36+TlRv7BohFo+QLeWbn52tcrbxAHBf+9vd+mbs3T/DRP/4TPvvYDA+fkdiOwJQhPKUTN6Lc2D/IRDpD0fXY0h7np959DXc8uIPf/m//hO+U+NGfuBt7PsvQSI4ZJ81tG/q5dXsPh8dnMaWOEIKRJY1jQyX6Sid48wPb6N1+kK88ehhdA1G2nIQQFOwS4VCYcCjIP6gEjlbMt6gkokAsFBwr2M1Y9/pkWUGXNQsfarLk+8QB6kMV64sJpRSmLmiJBTs/0PxXCruK4teabKG3qxvPd5mZncVx7WCiEUgBhZLD7/zqL/AjBwr84x9+iH95bIHHzws6TJOuZAvFYiDr8SFEjLlCge1dKX72x/bw4Nuu54sf/Qrn5yVjF0a5dX8ndzxwHSHX56VjC4QNMIXi7HwGAx3QMKTGRNblu6dt9oRP88b7dmJ07OPRp48SMrWyaStQvofrusTCEcJWmHy+QL5YCETBCs+mwPMhpAccMW8HeY9ilfBvtgrEy1IM/0OIgFgoKOtarNbVNblRIdnYP0AoZLGUTrNUYf0odE1jYXmZn37nO/iNHxngM//nf/GJb0zz2HnBzq4Ev/Nrd9KeTPD8qWlcXyGlxWQhTbcV5cffMsiDb93FS48+xW/82XP83Dt3MZ0u8o0vPsWdt/Zy3W27mB/L8OjxcS7OLyMFGIRpETGE0lCay3zB5qVzJbZyine+7S7Gix189/BxopFQ4E4WEtt2MEyDSDiCoeuBQriOCRcPCRxXUXK/v6ntsppUoaiu2EaPXsVpV3MGrlyF6x6v7IL6capujUDzjYYEthskfNSya+p2v+eTSiWJxaKUbJvF5eWqM0lKSSaXYf91N/ObP3kT3/3Un/KZh8f49nlJ3DD5vfffwM5Bna984xy+a2KKEJaIomOwd0eYB9/YzzNf+Tb/7Q+/w87ruxmMe9y2q4VDCxF+/f2fYXr0ND/01q10RAyKlAIOojR+7k3XcvvOHmxPw9AMTkzBf//HOY499Nd84F072btrD7l8vszqA1GwtLyM7TjE43GSiUQQZm7c3SJg/bYHkZCoppnXz2Xl/dXSpf6cyvsVYfEguXF16sBqS0KteK17vDymWGXNBHcUoHUEFbw121dVlgxKKTRN0N7aihCC5fQyjmOXxxK4rkM83sYf/5d3UTr5Kb751cM8fE7g+5IHb27n7gNx/uxvDnN23qXdjJDQQhTcPJYQ3Hl3B5OXJvitP3+RpXiSg4MGff2DXLulh+u3x/nWiMOf/PEXSaVKXLc3BlLDFy4uirDlYkgNHx9NmRhScnhW8vefH8E6/zn+13tfSyiUwPOccr4hlEol0pk0UgjaW9qqvor6lA5RTlwtlGpzg1o5l5X3V0uX+nMq72XD9ddmS2qdc74Hf0TYDL6fs5sf93yfZDxBIhqnWCqSzmaqOoIUglyhyPt+8t3sS57h3z71Jb52VsPxNTRhcO+NKebnchw754IwuGd/G6+/tYuSgIjhsmuLycc/dYhpQ+OmXSn29BmcPLKPYvZGDu4IsX1vJ185WuTYkXNctyeG76uA2JrORz5/kSdPT2OJCJ6v4/g6YUPy5LjGP37sce7sPM/P/ejryeZK1V0mhKgmlSbicRKxWBBYajKd+RJIAs/k1ZtVTd6vkTIkKwUPlby6VcRu8qc1j68TL1rJhsrZvDKopi2V6+7rQtU1xUgI2lvbEVKSyWRxKiFWKcnmstxy40F++rVbeeIzH+H/fbvAkmugKUlLKEzKgtlFyBWCUHAmo0hnHCylc9/BXnLzsxw6v8DO7V3sTSqEKxkY+CEE+0jJAjcNtGOlwhw5OcaGnjCv3bcL4ekY0mK8lCGnXCQaraEwm6Lt+PhEklH+7Bsez/zrJ/mF1/Zy3Z7ryBXy1Yyokm2TyWXQdZ32tvaVllSdi6TkQsmDsCUqoZh151Q1SfhbQZcG2lXey0rpdIWlNlM0V7GRZsdp6uRr6vep/Jhl0KaCHdjAjTkLvu8RCYeJx2LYTjBxsuwQUr6P1EO8/yffhHPuczz0tfM8PQqtCQ3ft4iFNFw7j2ElCBk6YTSePD7HNw9P88O3d/COt2zFsixKElS+wKGzY5w8ZfHNrw/x9UeGGR62efH4BVrbDMYm5rnzjo28/727ufuGftJOhpgRQwgDRznlfAGFrwziEZ3xDPzJp6fQhr/KL//4fSjMsjIYxCYy2Sy2Y5OIxQlb4VVcoJLuXrCD+TG1y8+pWKP8fS3aVd7LZju+KbtQl0kbVlcoRuo+hszgrgsl1eS8wERsT7Wi6zrZXA7bdYI8fhHs/vvvvJvbNxd5+F//jS8cCxJN2ltTJCJxbMfBsUt0tbeytT9OFIMCiv4ejTe+sQNLLvD1b51DGBq9PSl279xI3vd4+vFjHDl6DhGOceuBzbQnNYZninzsHx4lGZvjgVcnaTVDLDtpfF+WzUmb4ewyHbEkiUQMQxN8/Qx89fOPcP/WAnccuJlcLlflXHapRC6XxzQMWlOphqhebRoKdqAThAzRfFqvRDQ3O6fuf6nqat9WlWqoulQkKuVTqokIWPnbXIzUjgUZNRAyKIM11SqOqnehghSvZDKB53mkM5kgHKwUvu9imBF+6q33MffC5/jmU7OMZQNrOYSPIR0cJ8LkdBGKJX78HQeIiCUM5XHDHp2OeI4P/P5jfPSxOfSoxda4z+T5eZbSl9jcV2BDS46T58bQ55bYuaGL8SJ86LPD/N+//Da7tzts6AFXCGxl85Z9m9jR2olCInCwlItCkXMFH/tWjrnnv8hP/dB+hBYG5VdL0NKZNJ7vkyrXKaD8lbozQYaQ6ylCRqAPKKWuat5Vk1/UyoRRWamOrSRcNgs61GrkRFMxcbnj9edUvIJ6mf0XHYFfKemuG8P3/TKLDJEvFCjZJYQUZbMvy7133MuB3jTfffxRzixKhAxk5eBgG5GIyaLjMLpsMHzsEA88MMjP/vQBbt6m8/q7Ujz95AUOjbskB0zu2N3PiQvLnJrOYoSK7O4+wab+44ioxVeenyTmhblp32ZISj735CIXz4+xe7uOUDqmNDgxnmYx76KJMEbYZOuWdqQWgA6eW9b40sPPc+fGDHccOEAml69WIhVLJQrFQiDiojE8X62Yu6DUXFB0guQYTbIqWHe1dFk5fvBe1u/KFauongPUJYQ2rsIrOV45p6KNBN6/IPGl4Kz8e62EW5CMJxBSkMvnqulUvu9jWTHe85Z7yZz7Gl98ZolFTwcJ23rDbOzZw/03d+H6Di+c0hkameXM45/knW+I84f/cy8D7T5feWEBs1Vj24YW0lPLpEWRgzcnOTbhY/Y/yUjxPHkP7runhUPnzrIpIunZECNnCA6fmGP31gS3belF8yVHZ2eYLebwlM+917WyqX03+7a1AopITOdTTxWZP/k4P/PmW5FaiIqt6/ke2XJ4OBFP1Hhww5wVHIUmwDKacICrpEv9OZX3ssL+69w+NXbRIFzE9yx8aiImZAT2ru2oBrwBVU3yTMTj2LZDvpBHluVnPp9l397ruXmT5PjTj/LUEMQiFkoqeq04SxO3Mj6xyJbOGBcmdf7pW4JjJ0bxl4+zd5uJaYW5tFjEiBnEPYfeDsmd+7sZWnCwUlGOLnsUwlGSHTGWPcWDB9sJk6UzqkNIMbtY4i1v2MiP/0gH23tSKCBiauzqjzI6mmF+8iYSMgQaGKEQx+fg8Uee4NZB2LNrF7liPkhNF5J8Po/jOKSSCUzTrMuRrNnqthPERkyjaV3Vy1LGatD2KhABlSTDCu+psQtRDdaIuhzfVWHaht+m2ah1qqeUAksXlFyB59eOBfciy1G/KJZpkivksR236g/3leBtr301pZHH+MKj08wUJd1tETQpcX3J2WcPkyvluGlvCBny+O5wiIePpEirfh5/6hIf+sgxNBP6WqIkZIGxqTn8osP1m3sY6Ghly9YuOjqS9LX009/WwaHTy4xdmqAnYtDakeTFM8v87d8/xTXbS7zxdS206gkkGjfvjeMpuPjUSUolD6HDlp4IrjD5/LM55NRT/PB9d+CWzV0hBbbjkC8WsUyLaDhSK+6omzPXC7ykIUOU8wOufN6b/SJq1c1CiIoIqFcSmvkPGxWJla8av6hnY6sVlsr/hhaEPUtOXZ1BucqzkjKViMcRUpIvFMrxdYFdKtHXN8g9+7o58/w3+copKNkQkS6WBtdsVURbn+XuvSb9bSHyJY2UqXPtvi6GR+d5/4de5JPPpMkrjQ/915/hR3/219Cibdj5IkOjRb5yeJxHDl3ka4dH+fIzF5idlCRMRfvmvfzWB36T9777NZyd9/iTz4/xz594njtvkVy7I0LecelrM7j7+jCh5DPs2yIxDUlUczE1j+9cFBx+9ilef1M7HZ292HapbMoq8hUxUE4faxTDvlKUHIUhFZpcCVTRXAmsE6lNz6nRDKUqImB95q2uiNGoBiaz8uLVvyswdIUUwYPVvlGTWYauEY9GcRybYrFY9VEUSgXuvOVWOv2zPPfCGYaX4MYtgne84XpaYxaffWqKXGKcp4/McPHiFCEEmzeZHLg2zN9++gyHJ1x6Nob5tR+9mR967UE2dhb53Q+8j9aeG3n85CVaeixOzdr4IZOSWeRbhy/yjre/i/f+3JtIRZb5tV/4Ed7x+p2YCY2PfH2W08dHues2SVIKRocneOboKMttI3zmiQlaw4ofes2t7N/RwlJB8fWnhunRhjm4/wYKxVJVCSuWiriuSzweRysnk9AwbyUnQEMzdVWFhWmeUl8vuJuLgUYVT9YYez2Tb3z/yv2CwNIEvi9wvDp2VP71fZ9QKIRlWRSLJRzXQQpZTrUyefDgPqbPPMu3XwpKaaStGD91HhybjG+wfXATi7bFmSmDnO9y181hTpya4RvHcvRsCPPe1/Tz8++4nbn5LMMvfAW1eJhf+NV383u/9etIpQi1xFjM22zo6+Fv/+a3ufHAFsTiEYZPPUUonOC3f/ZO3nxrN7YUfO6RYQb7FakW+NYRjzwptm7sJ6eFsEuKkRNnUfk8EsEzZ10Wzr/Aa27bS4DMo5DlKGHJLmFZFiHLLANYrJwzxwssJVNbWW7zSvzKmjpQ8yGqBlzuWmFnc/6wis00e5UDGVIowqaG64vA9Kkbo5IbGI1E0DSdfLEQePykoFQqsnnTNm7c0sLpl57l+Eww8mC3xuZtUbpaBKWiz+MvnGd//yAD+iaSEZstPfDVJyfxDcFAR5idA1Hi3ZuZGDlH17a76djxo6RiKX7pp1/Lj73xID1tLbzq+k289637uHtflFhiGwPX/Wc0s4XFuRk6Brazuy9CsifEMxfy2EWb3l6brfFNXNu9lceeO0sh59DbDrt3Rdi8UcdHcXQSRk4f4radLQz0b6JUKlXN3XyhgKHrRMORqsdQVRVBhetX/AFB6litkHUlr70cXVTDsSAYtJJBr2Lk1dPrED1ejg1QUQmEBE1TlNxAu13BksoIYLFIDM/3KJSKVaWlWCxy4MabaPFGOXJ8mEtpuOt6k/vu6mUxuoX3/+wButoUe6/ZTEePz6GxY2zfGCKby3NysgRxnf5UmA197RDp4tLwCUKtWyjSgi824uZz7O9xWJjI4Ns2XdoSRbcXV/TiWj1YkVZmJsdo7dtOKhVjU3uYrA1Dowts2RDi5MwRMCe56+676Ghz+R+/eAvLiX289sGbuP+2KAs5ePLoOD36JW649rpAtMmgzqFQLOIrRSwaW1FPWJkb3wfbDeYtyDZbSSv1Mh2yDSKgGXOp+7xWwnDT1xrsX4EpBZoMNNtGZqdQ6LpOJBzGdR3skl0uI1NITefg9XuwJ57m+LiLKwXX9UhmF13m0x7xkOSOPTqFxQLzjsTVQ0QMH9txmC56tCbD7OkN0943QNE2sfOLJFt70aSD5xUpFWOcHvUwvQKnjo2T1QdBT+F7eXzPpbV7NwvTQ8iWLvoGN9Ae0cAQTC0W2dARwtYMMgLmJ+Z44HqDEAXOjYwxNrHA7laB1OFrh3yWRw5x5w07UUIr70CJbZdwXZdIJFytHaiffwiCQ7oUGJqoyx9aYZs1eX95OklVTr5Y/aq1NGiIMjc9d2VEWzX1JwT572Uodlet8DuIMpxLyLQwTaOK2gEC13Zoaenkmo1RLhx/gWcuwGCnJOJ5UEizOzaKkZ2iFZcP/9sQjlPiLQ/swbMXyWYKeBL6kyYdKY3OgW3MzEwi9DCa2RqYpbpBLrPI8Pgy0nOJmTojCwWUk0EpcB0bK9pObnEGVXDZfe0uOmImMqyRztnklpf4oYMDoHT+4qHjJPFw56bZJM5h5iYwPZeOpODkJEwOHeOGLXHi8Va8cmTT87yg/tA0sar+ALWisYTjBnOka/Uue0X9mVSBo+ppuBb9KvhP9fy5LlGjUlJVBWRAlB0YoknMWQTZREqUzY9aRk8Q1Al6sgghMA2J7ys8PxivktOHCv4eCoXQdINCoVSW/0Fm7dbBrWyIZTl5ZoRLGdjbq1HI+Qxdcjh1fJ7DLywSMzQiLQZPvDROfvEs99+7k0RXPxiS/oRFZ08roe7tjI2cJRztQjMjQUWw75FJL1B0HQbaw2ztNDhy8iK+GzhtPK9IONZNNp9jcWaKDZu3snmgnZglEeEk1998LYY7wfOnp4i1asQFnD2b58jxJU6cy5FZdNnWrrFQEpw9P8ZgS4nBDZso2XYViaRYLKHrJiErhPID0qBqm8z1Bb6SmHoNaEOUHUqB2Kif8xpdVr1qIAGBc61pXYFYu65gxbErrAup/E2TAlMXeCrAy5OydqyihIZDYVBgO3b5JiUlx+H6PbsgM8Lh00vYNpwcsZlYVuQKHt+9sMR0Os2zZ10cD44PZ0lnsszMFXnq6DyRkEFHMsS27f1gppgeH6OttadcPRys/1xmgUzeob8zyu7BdoaHRpibmUKpEgqJYRho0mTowjnCHf1sGexiS0eC02NZDh+fo+jB8aE0jg+HL/rMZ4sMzRXJFG2GF3wuTLu4nuLQsUWi9iWu3bWTUslGiABIwrZtQBEKhaupcvVz7ZVrUQ1drJ73qohWl60LaaSvVKv9B6z6W+Or0c+z6ngDC1J1LEcEyR+N51fiUOFQCN/3sG0HhMRXPoZusnf7ZtzZ05wf9+nsSFLyNURIoogxM9VNa3eC5ZIg7/kMbmnnums2cOzEMC+dHiOqGezYlGTbjq2U0gUyk+doy5xD2ctoRhQpPPLpJUqewjB0dm3uwfGDRFNdBCVqljNPl5piceosWK30DfazuT3KhdElTp88Q1dfJ7v3dOM4PtN5Qaw1Sna+F404ZlygmToDfa2cmlaQO8c12zahaUY1abRo2yilCIdCNQAoVemMJlAVRVDUc916ejRh+5ejXSUW0CxVSPmqjJGnqhp69fPl0shWXK0s5/2gilaTCsdTDeOXHUCajmWauG6QRi0Az/OIRBNs7U2yMHeOzk0t7Oq0cD1FfjmJl+kiVeplajhBzIqB8tjeH2Po0hJIyebBFgZaY+za3oNHHEdG2bn3Rp44/hKzY4cwpYPyCuQKGUaGJrF0xcBAO74PF4cvYZkavr3IS88/zHTBYffeG0hPLNG3eRvd7TG2DaRItkUYHsuzud3C9RWmFmZiNEyo2IO90E4pncRzfG7oj2G2JBkfP8c1G9uwQlF83ys/p4vreoRME71S1l6u/FEicAA5bjB/ouwxrcyf8qsRniszA8r/+75qEAHfxxflAsgKUpZqOKaUQtc1DMPAcWx8gnIxx7Hp7uphQys8/uRFVKnE5NwSOUcRIcYuYzf3xu8hTgqhRdF1wZ3X9aJHY7gSdE3nrn39pFra+PCffpKP/vnfsfWmN3Pbm36WhYkX8HIvYBkei8sFQq0p2tviROMpNnYlmF5eRrpTjJz5POn8FHe89b9yadLn//zqrzB1bozte3bQ32pStG06OhPccf02dA0MEaVDtnMwfjtbrK1EtSRLtmJobJrSgs3TTw6zpVPS3t6N67hVBBbHdTAMs84SqIvOiwBFRJMBgIbilaGLXnXDi7VhZa4KEmiNMSrsX5WrXwQrUb2V8tF1A13XyeXzAfaPEVgDGwY2EnHnOHVujhPnfeaLPpGwTp/ezt27D7Kp5wCPHz3NabNAMjrNztYcR857FDyfa3pSbNnQxb/863Pkzp3Gf/44508c4Sd+9de5753/g8XFs4we/zRzo+dIKRtNeIRjUWKxVr7xtUd54HqD3TfcRyyxlS9/4rN8+6F/RrNzfP2hebzendy0eyPHTp8k7zhsTRWJhqDNSrInup3brnsjQ3MxsifmiUbGmcw5+A48f3KO16kF+nv7mJw4j2mFgjpC1yEUtdA1PUAjbZhYz68jPLU0urVotx5kc0XMyKrToSkAlGpIPlwb6br+nObo4AEHQAUPsrIbbWC8WKYRoGY4ThUB1PU8NvR0I3PjjM3ZeJqOJ8FA44auAfbcvYP2H+/hxo3baY/ESBo+R4+MkgpH6UpoUCoxfmGWbz49xOmciRExmTp7ij/65V/kM//wWUKRWwgl+jl07Ajxrn4SYYM4Gbb1aHimpG3gAIV8D3/yX/4HX/mnD6NRYF5a/OuLc5x68Rx23qErLuiMGRw7Mkxch1Q0wr6ebfS9ZwvX3LmLfe2bMaSG0gS+ZnFuvIRRmGCgpwvHcavw8U6ZG1imWcVPqnekemXxq8tGSNxG2q2kaTOAr2pGUKVJYq0Mq55FiDo0qlpGwGr2vrKYpPK9xpcmA8XFdlfWG1Rgy3TDLFsATvU5NE1nQ08HhbnzjMwFAEKpqE7J87iUmWTi5CiZpye5ODnCZGYJAZy4mOfwC2fAURwdmuGjD7/IQDJBuhjlkSFFwQgRkUW+/JE/4U9+9T8hZC8HbrmFmQvnkKUcY0Nn2T6go7wQjz98iL/49f/M0EtPE0lYHF3QeGbYIKanmJrN8JnHj1CyBSfOTPPSuXkMCYv5DGenhsk8f56x4xc5szCE43mkYhquUqRLoAqX2NDTgRBaFfvXLqdGG4axAgirksBZEZ2aVumFxBq0W0nTFa6fuu8I0ax7+DqIP1d0XDRHqBBl8KcqmEbjGAosI2jy57k1iDVNN+lti1HIT9PTb9DS3sPR8UU0f5F04hhzCx+nfWQn86lnscLjTM8JMlHF4QmHUFTDQTGRdcgXZ7muN0WkpZVnLy2xpd1ie9xl6KWn+bPfOIvb3c+WvT1cGBsl3NXOjn03s5g+zr99/vN06jZ+NMS3R6BYCLGtPcLY/BLDpRKdUZ25jM+z57Mc3GIylxPI9nEyLU+hxnwy3jgzxjEMzaGttYXNbQmWF0fJZ2boa7sBqRlUOlh7roMgWADVyvA6du6roMOpLtUKXMm1mrZeCU1lJURbS/xsZjo0/K53XKnmZmXZAvBUk3PKK6IC4uz5Xtky8JCaQV97mJGReZbS8Ks/8wAH9u2kI6KQ0uGwd5iXzK9zLj2LrhcJRUzMcIh9O1uRhsBzFcKHJRe+O7REp5Xm9oEYIwsmz0zrpHWTwvIcj3z9JXAj3HxgP5t6uvjoP36dubk0SgrO5gy+fUESVmH2dWmcG5/hwlIJzxMBUJPwGdyYQLNChCMGUdNmKLPAE8XHOJQ9hqsKtIYV9xy8hvf+1P2MTirOn59hY1ck8AMohRJBmlgQDtcbRKuqdjX1ygm1NTo0oQtr0G3FOcF7vcJm1Dodale1i7/c8aa4RZU6v+YKihASTdPwPB+/HBHzfJ9oOEFrVHJidplnzjh87KFneXD/Dh575hwvDs3SNuNz/MQ402nBc9OQM2Dn1l5e3a/x9IsznEwvo0Rg7xY9wReOFuiIldiUimLLBM9dytIXstm0pYuJ8SUy/YrTp8Y5f2SEllQLT43liIsIgwmNdCbDC8MOUznADLQox1W0xMO8Y/8ACzMFHj2b5rFzgnQ6x8mLWUquYHROYfT2c8+ONj762e9wfFIxM7vExpt0QqEInl+s1kBWAC0r6CBVVq7AR+ApUXOgVeoo1QrwsTXpshIiqAxn2wykca2K8pVQpk1K/ZuJg7K6X2nXXoeu1oDfJ9E1HV95gc9ASDzPI5FIENEdphdyoMPS3BjtCcHt1/Xz8AWYzAuM9h5Ozypm8tAe9bj9wC5018BwXEquD5rA9yAeUmxoFUws+RweyRBRGa7rjHJ2IczhM7OMnR/lG08NceLUOAs+zMzkaNFCDCYVY1MLnJt26IrDlk4JbsCjXV9RKni0iiz3vupakgmdsTS8NKWIdbex4Bi8MAevOdBHOBbGsW2EhPGZNGHNIRGP43le1RRUvoeu62V8gYZCj7II0GRdG+fKNDcBeBHr0K6yAaXiKn5Vk/dqjfPUylYsQfeMAHC52TlCgKZJ/DIHAIXvBTj/ulfEtXPs6JHMzNmcPDvNa/b30JK06EgIbr2mHV+ANDQ2JDVGzlzk3PAkL11YDNipUghN8sANCbb3SXpbBFFLcGikwOlL87SZihu2tWAkwnztWIFnRhUTaZP27laE5vPSxTRLBcFAm2DHBpO339NNe2cEfIUmJWdHFzh9fpqLR04yEBVoIuhYfsc1HYRDGv1dIV59XYzjp6dYmMuztVNnOZsnrLlEo1F8zy+nf/m4vh9AzwtWzxMVEaCqltMqmjScr9Y7L8gHWDsYLNYILl7t8frgpqeaBZ1rSQ4BMncgEjzfIxqJIL0SC0s5+jraOTzi8Mt/9C2WJobZORDmidMOX3nkNEMZ8DSfcxMuf/XpI8zNp+ltDwWexhLcsCPO3h0pigJ2bzHpb1dcs8Eg7wlSCcGDt2zGFUmUBlnfRLmKTGYZ2/PZsynEvs2KrZtDFK0Iygxx/6394AWmWXfKIJN2+MvPHOPibAkPxfAiPPS18zx/rsC1myyOHz7Pez/0bU6OZehtS5LNZDGFSzgUxlNeuYsKZYQxbVWgtzKPnqqE59cP5IvLBOor7+W/BwCEqAR+yskNzXSIStq3XwVsDtyclhVClw7PnSmSLcG+QcmtB3o4NrJM1M+TURrzKkZfh8U77htkUel4iRSj0zZ52wuwfwXsHIijxcIM7uilr8/i9n0JetvjpEuwpS/KctZDhjV6YwYthmSu4KJFoiwsO7TGI7z59h62DrawbdsAZizFpt4ERAw85ZMveozNu7iJFhaVwTtfs4XWpMWCH8Y1dAyvxIV5wV13bGdPn07GhuMjRQzhErKswJVbCwBUM7AaZWV1/srgra8AShyyPkMUtUYaUdMs4DWOryEW4HLHRA2VvIIhqhSWqYPn4gJPnphhbCbL+95+M7fffRBNOWiawvZLLC+5vGpzL/ff2MPb7urClSaO0onHIqBDe0uI2SWbVEuEHRu7yKRNHj22TN726OuI853vHGF6YpKRZZeLMzk8T+GWXJbzLk+eWmR41GX/7kEGBlKcmUjTnopihHRaYxbSiCF0yTvuaOcNN3ZyY2+SbMGl5NkITaFh88AD1/Led97O8dEcL56bx/EFvu9gGnq56CV47mqv4xqTr+VW1LFuGuf/CujWmP2tUOjl4jCUqPQEEqsRfsX6fgElLuMapha2rMDFr27CJuoQvWtaiq5pCN8JgLGFxPYlv/9/vsk7H9yEp5sUpeLsjE266HHoyEl+4p5dZBem+YoDynPRFWhxi0jYRGGzszPFk0+O8anvzFFUsO/mfkR7kpOXfPSN7Sgy5IsuvVu7kaWg+/NsUfAPj85yZkbxlrdez5buBCjoaImiZZdZzBTQTIutbR57+qN8/tHz5Esew0sCR0rQDF584jBfenIO19BAKlzHRzkOuq7VGliWA2ey4kirw1oXsAJmth43Sol16LIGyGsFXV6ucMiuKBVfWUb8vb4q46zFtSoerHrM/mqnETyKDsRaTe6/aTNZpfHxh0/T32py//V9zOTBarXwNZ+kTHP8+CQxAwa7o4zM23QkDa7dEmF3Z4zvfOs8H/3mBEUFic4wBw5uZNqFWU+xPDpLR28XnYMtxNvCeEiUJdEigiyCh4/O8Q8f/S6b2+NsH2xnsDvB+LzDpg1JTF1x9twSccMDS8NqsVgu+jx442Z6kgYf//Y4mCavuWkLWkQGbWKUF2Q8N7h0Kwkfqok5ptYp0385L4lSdXV7ao16sgY2cjXHqWtqIOrYV/m9EmplbbKonVc5hlJIHVzb5eKFKS4tlUgXFa+9Y4D7b4jjK5833LKRu27o4tS5RWwtzH03D7KchoUlj219CfJLir/+5Gk++fQ8BSkIJXUGt6QYG5njuy+MoukBQmd2fpZQwmDq9AiTEwtoUR10iRYSCEPw3QtpPvThpxk9N8verV2USoJsTvLae3aQlVHG5zQevLWfB27ehF30ue/GVvZs78B2fIZnC8yMTQRII3oF87FubkR5dkRdtnT9/KjaXApWFnisSRdRCSuvPKfyXueKmkd/L+3jKePZ1MCiEOWuIaJOSxS1pk/1FcuVLhshE4o5xb8dTZd3i0D6RW65YTvxxHlefWOS7b0hPnt0gduuHyAb3sQTnz4JSYvR0Qy/f2KGC4suGIJISuParQl8PF48Ocf8bD5oYmHB5HQebT6P8kBGdKQm2dEdZSlXYny+BMLn7JzD7/7VE/Rs6oCowROnZ/mJH7uP3kSIM2fHefd91zFeuMjTpxLs26zz9PN5Zh1BOm3z2UM2mBJZrv5V1Y7SYkXvwpVsWK2G3hP186guTxdBU7RovdF9r66evJc9vsJJpJp5pSo6ol8zccoBEtf3AYmlQyju8bs/dRCz51o+/v8+wcmzSyhrgmu6Dfpjkk987gRPns3wraNZDl43i5kUuJrHRC6DsxjgQetRA90MHDmu45HLFolqHmldInWJwsVzFNKUiLAB0uWX33GAIxdn+YuHXkSL6CjhMpVTpGeXkFGDNtPlm1/4Kt84nGagFdo6W9i1tYvdnTqTY1PMzea5ZluK9/7Sz3Li+Wf43b/7TqDFSw3P92oYQkrUpYWrBlBXVjTGFFcQs7lc97agb6CiARri8n0BLt8/UDVJEKr5ruuvWctDDcy+egdIAJLggpCkwnBga5wud4mD1/QiHxjkhaeOMjS2yB07N+MVC7z6jfcz/cgIX3z4OcSpcd521zZedc39lIoFnjr2KM9dWuDcaI50CV48uciObpMuTbIsfKSlY1g6nqmVExYEwtDwFXzlWyfZuzUJhoZmatieyw/ftZnb999CqreXv/3Yp/nWqSmKsQjv/ulX0+kNI4oFtrbHefyJc2RtyS+87jp2mGlErMSuDWFS0QJCSmzHq4VnK/mRfpPwbX3tXx1wWGMlB1dBO1WGtbg8Uuwr8hIrgAlW+49VFRy5XgTYdomSJ4hGLETO5v/7qxP8yvt/h3BphpCuSHW0ctfBLTx6uIAv+rh3bxJP+ty0dxt7Cq+h5dm3s+Xku3lN+y/xx+94Nz/9wzdz+75utvQliEcSJFyXbMbDxcPzbDzlgynxNIHj+Ti5EtPLDsfOzIImsZXiwVs2c1OXxuc+9kmGH/0qv/DO+xlKK67ZoHHD5jYeebJIxgnzzrfdy2Q+RDwiWRy7xE//yt/wa3/1XZK6Rzxs4Piimhlc76MNxB5rI6+/gnTSrzjmuw4rqUSuVV3XbOq6W9QblpVGy42NT/1y7ztZ1+BJSkmhWKLoaUjdxBeKfbsifP30EuHwHFt6wuzZv4GRUZfHXprioW//Ka+7pY0D17fTY24n444y3f1bFLPtGDO38cJ3u+kYvJ4bb+2m53V9PPzNh/nwyTluPrCR62/ahiY1csvLzC/MMDmTRo+E2bNzM3e0eHzg759FGhb9rRHMbJHf+Odx0CRPf+4kf9pn0bs1BZ7N//yDT/HCuQzXXRdjYryNW27ZyaVTJ/nCkwscXTJ4zXVJxqaX0c0QRVcESOeV2sdymrbneVX3eH1nkYrHVK3Io64V2KzEehBXxBX0l+tNUpdhLSurfuvRLZqIgDLb8zwPwzBquQBSkstlcTFIRKMs5zNc16f4jquYzfq8c183R09O8pdfOkbRFIRMk2eOzXPnXdczOn6OZ86eDgCmUwavufYJNu/bxJJuUBi/gaGpSf7hG+f45ffczM+//UasaIJQIkY4piOwWU6nQXhECzYf+O+fZaIkIKwQeYevXpiFhIZu6rhLJRZmpohLn6PnM3SENPRWg+mhUT76zRf4o/+8DX1rL186MoyueWxMwAtnobM1TsEW5PN5ZKXPgBbAx9i2vaKcviYn62J8dSXgTcXuFRJWv8pt/rK0RLGmRrhSB3A9j1AoVNX+NS0IwdrKpKs9wpGRKY6MQn9/CxsGFCF/mY98bYHZIhAyyeR9/FiIhFXiX4+eZWw5uOC5aYfvXJjhmq4ZHrhmH1HVyyfP/SP33t7LLYNxfvHnP0xMKBKpMB/8i5/juWcvccOgQzZX4n//3VN85sUMZluMnb1JzpydoXdjOyVdMLtUZMPmEBvaIswtLlHUomTDGj/1+h3MXZziYtrjLz93mve/fSvXbE2RHRH8xSNzALSlwuRdjUw2ixYAACGEQNM0XK8cEZVipcZWiwyjmuFDX6kWWKdV6lyJFfgKIIJWGEClIdbKxpgB2/M8r7oLXNdFymCCsjZEwyF0EzwP3nzXIDuSaR4/Ocv//MDrODSc528eehqURldXBLtgM5bxEUkDhEB6CjvrUAzHSPkPcrbwHU4vZPn5m3r4rx/6FiOZ4MEfvDGEvzTFf/nAQ1haAMtyKg1Khw+8Yz/7+6L8xO99jVdt7uIn/tOdfPHbL6GX8nznxBTz80XeeGArb7z9QUZHD/HxR0f5b79wG+2t3Tx19FF+9P5B3CfTfHlqEc2ClkSUjC3I5bKErSAPQkqJ1CSe5+IrHx19JWdVtRjA99TBr24RyBWwkWtAvDVBH1pZfdBYWNAUsIgVrdQb89eV8nHLKVGV0udKt6+ppSLdHSnCUYGK6gwkcqQzeW69aRtdrsfPv+5OdvUnoOih+z6enYWQRLMMMHX8kEWkV+Pd+27DFTYvTj9KOBLhyIU0IxmB1WahGYp7b99IKZtnTknOl3RO5jVUWNK3IcGdOzrpatexfcFXHztNrHCJn3tNH8ePTvPPT02DprEwvcTEcx5/8/kj7N2Z4o03bmFPW4Qbb9rLxNgYWzo9lCFIRKCjPcnUQgHPd6tuYE1KhALHdeuQU1ZuPlFX/LEmnmNjqR9N6EsVJOqqUkLWUUdZd5xaF+21r1FJBg0KIwIt2HNtJhcLtLekiJgSQ9N4/tAIpuZz7MXz/NLvPsxf//k/sKXFAgQLCwU29HayZWs3vpRoQqAk3HVNH23ubdjGS5wcLyI1yeRiFpEw8E0DzxBsH0ywuJDBET5aXGIldURIZ//mFs4eHyVqCeIxyVzR43MPn6Kn3WJkdhFMAy0Km9s3sWhPMmfn2dpu8pt/8BC/+b8/zviFEfJFydnTk0jLJG5Ce2uKS/N5lOdWrR5dCxiy4zirlOTGOMv6PSNFk/fNkeCvKBxcA5F6+SynsqCDdCaxeiEIghRpqGbFSiFx3RLjczkSqXb298P//tl7aO9oZ3gsy+/+6xJ2Rxuz6QKTYzNg6VyaLFHKF/nVe3uJ6BJfSWItcG1oH/mlLM+PPkfW03Hx8QyJCum4QhBLmHSnIhw7PR4k+1g6nqETSUXY0Brm1LkJWuM6IVNH6JJTZ6egkKdvIIXwobfF4sYNg5xbOIlyYXh0kVAyzvFchD/53AjLSzmu2TPI7/z83WxKQaKlk0tzmSqaOCp4bkUwD2th7kq5MvP6e+0pI1eEcNXKsG3V1FA0QaBYC3KgOapxLRu4bBzWjV9hdyXHDtLDdb3q/5bAyNQCsdZuOsKCDV0pdvabzGcFejTEhk6DV920jYllJxjO1Pijh87x1586gqPA9zwObmghvrCd+NYzzLolSIZZKvhcnHfQTR3lK1riOn0tkvMTBbB0NEPDzdtsbbXIp4scH1lCFbJBA+pIiOPDWZbnsxzY14nyPO7a3EOpoHhhdAikIOsavP7WLaSMEn4kTtYW7NuokdBNtvcIwqlOxqbng1T58jzoRpAUW3LsBhrU5lcKVasbrHcNotauAVsTQkIhqYMME6I+f7y+H1CzDJNViX9rsn8hRCXzGU3WtT+t7yZKUBDieS6mbiDKtrFp6FyankFFush7If74L7/A9MQ8126Js7nb5JkjU/zhx55lMmcErf8sjdkinJh02NId51139/KmfZsJ950l0pvn7gN7kdLD1TVKmgwm31NsbAuhu0WODy2AZeEpnx3bu3nfm3aymC+RK+ZxslmU46J0xaUsHD46wYEdrVgpwabIACfGJpkp2hC1eH6owB/+8zNML3ncMBhhY3eMY8dG+KO//SqmEcXWOhmfnsE0ggWoSYGh67iuG4gA0Yx1B42s/fKGXFmTIdZR95u18ClD9l0d8Lx62dUDfrm0SZOq6ihaAUIpBJ7r4jguhmGU08MUhm5waWKctJ9gz2AHZyYKzKddXjw2wW37+njTq69nPAPSKkOPSg0RMhBtYabGl9gqPOYv9LPgXeQDf/Ytpscv0dseJZGIgBZo3bg+G1p1igWb+bwHnse779nBb715J1v6W/mxn/wR7rh1ECVdNnalGOhJ4vjw/NEJ+mM+t+5owc8muJgewvPL/f4Mycgy/MSPHqAtaXLizDSjc4qpZZfBvnZmnRiTU5MYuhEkgUiJoRs4joPvuTUchnp2LRRSlotC1ZX0ChaXpY9Ua4iAlZke5VLFFRdtyPKpDzM2AyxSQUcQWbVjVo4nBDiug+3Y6LqOlLLcLUQnnV5iaN5h97YBpIS5jEsyaXHzxgTFqQmI6TVHk1Qo00BJnbRd4OJwiqmRCM+dGGMoAy9czPMzt23n79/7Ovbv7scpBux2a2+cS+OLHB0rsXNbG9u0HJ/78jE+/JEnOPX0Ed73E/dSchX/633vYnMqAkLyzeM5DD/He/YPknM8zkxPgBUKZs/Q0SKgJia5ZXc3WVuwkPWwdLhmx0YuzJTI5ZbLDa59pNTQdZ2SY+O6Xm3X1tFHlDmA56/sJVjrxL4SAKp5aZhaATMn68uEajnoZRRJLUCgqKJJ1H2u71+zEo9+jURRIVFKYpTz3SrmXnU8KkgZRaTUMA0DUGiaxC7mODE8x/btW+luCcqrEqbOX33mMMenMnT0JMu17kGja2nq4PncvquNTn0HpdALPD+2jIhbKE3y+3//FH/zN//Kj+zfjBU2wPPZ1m2SyTs4KLZG4c8fOk8sZnBsvMBv/t23eOo7LxGKxvnzP/hznn5pBJEKc37WZnx8GeH3cOLSaWYKqlr9qoRiQ38LXzk8yUe/+BKpmEE677KlUzC4eSvHL07j2EW08kK3TBNNSIplwCgh6rI/yiJZkxJdl9XeThXIWdlQCiaalvk10jdQspubgfVx23KsnvrY/RW591b/VFBBpKglflQ7g5dZXr5QRApRxs4NFrqmCY6cGyHRMcDewRSZnIMeMtmxo4v79nZyz54+kB6U692Vq4i3CLbIzTiuy4XZkyw5OqRCnJ4uYocNHj25zPTQEFs6Ipi6T4du88ihWfAkS0t5kp0hdvSFODebx9ckn/jiCcJuFiccwlE6UgqWbHjsxQxHT+W4uDANSKQWPKimK+7b3cYde9vZtq2fsGWwXPC4aXsULdbLsQsjGFpFBxdYpgVSkC8Ua1xWNKbVBfUVrqrsP9Ukzn8F5ruoFRpI1SRTBKVQfgDO4JfVd9/3V3y+mgyhwArwcRwPlI/UVAPgRI0lFYoFfN8jZFogyujghsGpi0Nk/Dg3bG/F9SURS7G8MElo+Tauj76a7l4T3wXh+SjXZU9HlFB+O45+nkPjRQiZCMfHi4XQW8MIQ5LLLdEXskmFBYPtOssFF3xJPufzrvu28OK5pQCJJCw5NZlnYS5DLG4ELkIh0WKC08NJpuZdZuwsGCb4CuX67BmM4y/vwC/1MzMzi25ISkqwc2Mrc06Cs0NDWKaJV24pb5kmnutRLBYaQui1+RHCR/k+ruuXaaLK5WT+FWVuNWZ+BQARVS2fun4BorbTqyFaVnxeCUrc0CKyDqCm+l6B45VrAGUFwKjWdp0yHnCpVMJ2HEIhqyweAvt4dnaGi4sa2zd0YZo6w5NFSmnF1s43E1FbadN8kBJPSKIp2Oj34jhzXMoeI+3oaBEtcAurcl29oSE1D+E5tEVNRqcKPD9sI8I6Z6cyhOwcj55aCsSGobFYVFwYz1Eo+uB5eK6ivTXElpZBJgpjZG3QrHI+vwYtvmJ36l1sSN3J/EKW8TmbmCnYtrGX8wsaC4tzgb9DKTRNw7JMbLuE7djV3sK1ymCBUBULClyvZkqL+mLbhjlvuv/rGlYTpIStVWIq6mr8KskK6zQEWlP3rHXMqgAaaFKghL9yPCGQZW9gsVgkHoth6galslJYyCxxaCjNu/fsoSt1mFyhRNyK829PHsaPnCASLxeU6Aa3bYjR09HP9q4MzrkwqawgXQwqjTRTR9kuytKImgbnxha4eXuMeEyyrHyUDbfvb+fCWJqFtIvWYeF5kryvWM66DHSFQbNBKq7r6MD3Nc7OXQJpVGsa0CW6DQ8/9RwlMU5Hp8lCXtGVEmzadi0fPbOAXcgStVrwPQfLMDF0g6XccoARIFcbZ0oE+IqUq4Try4NXG4BibYSIFbVm1IsAao6FOjZRX6e8Fnu/EhEACs8rg0VrjVhCqi7TRZHN59B0DcuyguQI38fQJc8eO0Osdx+bupNM5zw8R+POyAEimRZmF0uETI1fuKeLB3b14bjDfOWZedrM1/HX/+kNvPbmXnraw3i2ja88rt+aImoEqOR370qSzboc2LOJzt4W3nl7H8oMYySi+ApCIYsHbt5AW9Rn/2CSwU1dmKbNntYNTCwtMpGzQdcwQiahRARsn8XlNBtK/dwkbyJbcvAQXLcphtVzLYeOny7b/+V8R8ssd0LJofwafErjXBqawgsYUJUDqEZaXYUIQKn18QFEXbJGlUBCIJqEolZYpWtUrXi+wPNU0FxZqdUQMuWFks3l8H2fSDjCciaNUoqIFeLUmZOcmr2Dgzft5OTFGYpujkzqm0T1UyykFTv6w+Qm0pyfz7C0XOLa3j6mxi0e+1QXb7t/gJs2HGY8Pc38QpFtyTDffukCdl7ni4/N4nsF8lonP3pLD6dPz3B+zMOMaOzqjDG1WKK47PBnX5gkHEoj8lF2tEXIjiU5N38Iv9zC9v7rerlusJ8P/fPjLBYcQh0vkZUFXAUdEcnBG3Zyclpx7vwZQqFQNQU8Uu4VkMvnyuxe4TdUTgkRwOx7XlAfWK5LD9JFGquIRE2HVKzfUVhXsAKftlmwRpXbnIhGQKGqYVDTRoWqqzpo9EsphePLQAeo10ardTACITUKhQKO7RAOWeh6ECrVdYOl9CJPnJzkbVu209PxEpfmlpnTHkKzcsiSRZt0aGsNc+hsjsdPZdjducQb9s/i+rfz1S/00ta9DSPaRZwZSu4pjo1lmV1WnJZBcGWwa5E3m2F+69PjZB1IbozTaRkcn57ikYteYL74WWLted531wEuvJAjLZZR0sAM61iZeZj12NwbZuJSiUzyMVzpsVGPEjMF/Vuv4ZOnJsnl07QkErjlBBjLClGySxSLxSB4VZc5RV1piK4JbK8GGV+V3qoRLKhWlb1qg1cTUAM6ygpRRT2B1+hIWIs2rq7+XYkM15z1qLIiqMkA5kSt6GtTLgQhAInM5vOYpolpmNXUcEOTPHboOCKxkcH+FopemNniEkPzBbJ5j8GNbWQyPo+fytDeEeL8ssGHH5khn/8auw58h3zxOUanjgNn+cKzY8yVJEarhQJ6+sL84U/v5GvPzZH1BDJpIBH4ro1vaBitIdAV8VaDX3/NVnZ3+vz6e+O87z13EY6HsHMlPv/ENGcvTqK7NiVHcHZ2kqXiMpmcZLAnjBMd5IkXjmEZWlkL97FME9PQyeaC9jFUi2NWJtNqIgCKrmAsiiZofI21GM1Bu2vHUAot1Jr84OVyBxstSnmZ4/XnNXqmdQmxkCBfDDqFywZmIYXA93wMUyeVSOG4DoVCYBoZus7swiK3HLiLbdF5nn5hCF8LY1qCtJIcPjHD6fECoaTOf33nXsansozNFzk85pJNT9Pdt8hycY4nj89yKQdEdHzX49Yb+3n/63v58hMjfOmFDDKuIyyDUrbIG65pQ7a2MDI2w417e/jAW7fy3efH+KNPX2Bhep5ffNf13HbrHiZns2ztibG1VeeRM0t0xnVaIwamFSJXzPGjr93PkHEDn/7q1wiZRnVTpJJJIqEwUzPTQbNpTVs1p0oFLWPiYUGmoLCDROnqObIa2bs8XWTDMS3UmvzglSSQrOfqudzCqVofKnAFx0NBu1jbrVUNU5c8HBSG+rS3tKJpGtlctgw0rZPNLIPVyhtv28nE8GkeO7HE6w5sRuJx8mKWH3vdDm7bHadNFvjkU9P4IQ3lKyYW4fCwy/kZl6wDd+7fxI3X9PKO+3ZwoLvIR/71PI8cK9DSF6Hglvv7lXwWZtP897ft5h1vu58Htro89ugpPv50GlsITlzKkx46z1tftYm33dlPorDM5x4bZjTj8+pr29i3vYdvvDDDvfvi3PXg2/jIoxc4f+5UVf7rmkZHWxtKKcanpspJsSvr/ipAEFFLEDYF6XxgBYgm0f6rzeIA0KwrWACvSIl43VWjoWBV5+3mMSspBK7jEY1GicViFAqFumQRycziMvfdcZB+a4ZPPzFCuujyU6+7Fte06Ilm6bXynDy/wOEFgZKScFgnEjMJRUzCiTDhVITsUgHTKXFpfJovPj3PVN6gsz/GgzftYrFkE4tHCSejLC77nDk7hj93mk984xIPH3ewEiFME3xPcXTMZuj4CV545gyPPDfJvKPz+tu3cmDnAP/0zYsUnSK/+KZrKHbewUc+9zVkObPX932ikSgtqRTLy8vMzs+XofGhmR6dCAfyOpNXa57zcn40qywCrmTVfC8cgTp2FrGCxpHZYvMHqaRGG7pBKpXC831yuRxSCnRNZ35hjmjbRh64JsnszBhDs3k64yGkH2JytoBXytGfEpxOa2RKPq1xk1QkgmnqtETDtMZiREyTdM4hV5Bs3xjn/htbaQ+ZtC/tpK9rif1bEkTNOKbUWM57HL6Qp+hbpFIxdFMS0gWe71J04MwMjM17CAO29LfR39FJrljg0PlZ7t8b44F77+OhowWePfRdouFwVcNvbWkhZFlMzcyQy+WCXINmwVsJqYjA84M5E2sQ/3J0oQk9XnmYuCtIDrUdiIZEgBrmrx6jUhW8nElj2zbRcBjDCGLlSEnYMvnSt57gTTe9i7ffdYJvH3maP/j4YdAE73ltL29481sYe/Fp7rdz/OPTM8xnbGaly617OhieLzF1aQrNc/EA5XqMzMDzJ0Apya3dOZ49Oofv+xSFRtEHTfloUuAu5ejtkXS3RXnhTAYNCcpl/0aDvZsM7n7VDTx9+BJ//YUXkEB3h8Ebbx1kPnItX33s40RCocBZ5AdtcSPhMKVSieVsphr9XGVWl/0muiYolNQKI+x7oYuoDwc3aodrao5rnXO54/VBShW0i5FCYWqw6vpVTCFJoVgkk8lgmiaxaKxqDVhWiImJYb50aJwde/bzrnu3UQwbXLsrzoFtLQjieFYbt+/ZxP6t7XhK41W7k7z//mt49Y4+POVjI9Etk3DUIo9gHoO925K0bZNcsy3FIiZFX6fTSCKFSUloYElef10vv/n2u7hpeyu+gr3bU7z+zq1s7W+jf/P13H19P1v6NQoIXn9TO9uuu4OvHh5ldvoSpmkF2r/yiUdjmKZJOpOhVCyuKAlvCOpiaEEgqOQ2wG1cLV1Uw3cBzWpJfLAhR/tKkgTXZy6iSRli2TdQcVPGwkFcu2CXEatXAAkE2qrv+ygUrakUUtMCR0nFgSElw5Mz3HnwVWwzL3Fy3uHUhVl6RIEPf/JJHnlyFInk1TdsIJtfZiCu8bVvnaEtVOBiGqIhDQvFQHuUmcUiO3tj/KebE7z+1beztU3npQuz5As69/b0MbScJZpQxCyDLRGbR586S1eHRdzweeuBTZw8O8dDj07wxNPHCLkLPHa+yM7BJO+5ZyvFnvv4v//yBYTyqkTWNZ2OtjaElFyaGKdUKqFVIoN1CA6BAzbQ/g0dlnOUm2+skYArGks/L0O7oBKpAkcqqg2kV5f1NTQhbnq8Dqa0WQ+buiYFrg+uJ7AMVuDh1ZfCKUDTgrqAXKFAOBQiGolUuYBpmkxMjPDpp4bp2XmQX3xVP5puUJI+eqKNkRw8dfoSnXGHV+9uZ3J0moIPh84vge/yZ7/yZg7u28jJoQU6O5PcvztJNNnKtz9xI1FrkNfd0EJbS5RvXLjEAwc38Ue/8m4KBZcXLy4zvJBnbnSKN+7vpr8Vnh9aYrwAVixMtlTEQ/CuA51s3PcADz1zjtmZCXTDqNr+0WiUUChELpcjW5b91RjbCmsoMJMtA1xXVPGBVjeEaKSLaE63+nPK7wMOcNUVBc2Kyi8nfWrnKiWwdLBMyJeo9spb6b8UVbBoTWqkkkkQkmw2W3WWWIbJyXPn2Hfz/VzfnsWzbf7h4UukHY+2DoMfu3sz0UQHbgncUpqi4/Ps+RIP7k/yqz/5Dix3nsePDvGqHR28aptibuR2unt+gqQwSaWeJGuHmMtl+eW3b+aBe+7nueef55kTy+zr1xnojNDf2YEKpejrTnFidJrltM3hEZu33NbHm+6+gdPqGv76E58kbJl1hTGSjrY2DMNgcmqKbC5blv/Na+Y1TZCKCgolyNlqjZKtKykQb1b9oyoL4OXYAQ0XFE3YTFOvRHAjmgwUwZJD2bHRHGhIiiBEnIwniYRDQaPFUgnKGTKlYp6h2Qx3H7yTDfoYk2mf4xfnObAjztyUzce+dgYPjY64TnvK5Oiiw66kz/Cxo+jpMeYXXOLCx/XynD91Cze1v5snhx9lfOkb2DmbmOnTrub4zuMvMr+4yETO4/49MaxojKdP5/iXh8+g+zbJmOL0WImbdrTwY/dsILLjDfzBJ7/OwtwUhmFWXerxWJyWZJJCIc/YxESdk2S1oa4UhC1BLCTJ5BW211BdvS57X0sKrBQTgSdwRa/5Zo0FGllJk+M0sBnRREzUgsMoIBaSeD4UnLJHcA1W5TgOhqGTTCQDx1A+V8bLV4Qsi5HRYVRikIO7BtjZbnNqIc/54XkKRY+RpRK//pM30tM3QGGhQEtXJ5NT0zxzaonpZUUyajK1uExS9vHNIz6nT8zw6PC32dNbYCY7hSZMXhjyeP7MDJqpuH7XBnoiGgdu3UtPXx//+vgZEmEYWSrR2xnlva/fwvYbX80/PbvA4089RiwaC6Dqyilwne0dmKbJ1PQ0y5k0Wtnz1+ylECQjAkMKlgsK329o39eMva8QpWId2gXvr1IEvHJOIV9B2AiUm1xRrVvrJkRQR59KJAlZFo7jUigUqsCSIcvixWNH2XnDvWxPFtnSJnnq1BznJ3Ls3xUm4eb51NcvcHqywMHd3XSmElyzs5/777iWsOaRtNJEc9dzYryTUV4gorq5td+ko3+cge5u7rrrVXR2trOpI0ksHOPrz01y6OgkKT2DIsfz50skExa/+oatXH/dDTyzNMCHP/4J4tFaR3DP80glk6QSSQrFQrD71fpFfpqAVFTguJApKF4haMAGR9APYAFU7FtdD1ycBTvAwl/LAKmUTEtNI5lIVLuK+H45JCoF4PPS6QscvPuH6fRGuGZzJ8cn5xmZLTA6kubCssd9N/ewsbVELJlgb7/NNx8/wwunFzE1xcWpJXaE3sqtqXuRTolpvopu2Tx1PEchPcd9t0TJlKLEzSKe1PjG0WkmpxYYzQs6Wk1+4y3XsWdzD7Md9/F7H/k4uDZC6lWSGYZJZ3s7mpRMTE+xnE4HmT/rzE/IECQikkxRUbS/9yqgpgsg1JL8YI2F1LMT0VyLfIVelYyjWFji+lB0qPYpXH1uuXt4oUAiliASDiOFIJvPVUGWDcMgvbzISxcneNU9r6OlNMT123p48eIcF6YLxOM6e7tDdBpZTp6d4MSpKT71dJo337+NLRtamZuY5d7Ue5jORLh+wOQSn+HW27chom3841fP4i1Pszg3y6ZWmFgocWEhz2zaZ6A7wm+8ZTe7NrRhD7yG3/y7h5ifncSywlXUc4COtjZikSiZXI6x8fFq1s968xOLCEKmYDkX9Fn8ftDhB8YBIIA9jVgCXQpyRf+y9Ymu6+L5PqlkEtM0sUs2JbtUFQWWZTEzPcHZ6QJ3veq1xHLnuXFLJ4uuzenxZV48uUy+6IDnYITjdLWHSKgsZ4cXaY+XyDkez56fo2PDYWIdZzk7lkcrZYjFdHTAdRwODRf58osLOKbi9l0tvO8Nu9nc04q36Q38zse+ztDFM0QiUTzfq0LAx2Mx2lKtKBRjly6RL4svtQ77FwJaYhLPUyznFd8X/v+DFAEVPcDQIWpBwVHrioEgl1CjUCwQCYWJRiMYuk42n69m1vi+jxUKMTo2xOnJLPe8+q0Yi8e5Y+8gqZjJC2MzjMy6jMwp7ruhlYVFj28fW6CIDApK1AQDVg/z5te5VChwZsLlxaEMO3qj9LTpfPa7eYbSDioiec+rNvMzD+6lJWzgb3sbv/3//o3TZ44Ti8arxK80f+js6MQwDOYWFpicnirb/eqy7D8VhWxBUbC/L9y/QQSspVmKJvjhV3u8yTn1tYGxsMT3oeRcRmyUmysVS0VSySSWaZX1gVwt8dT3CYciXBof4aWLM9x08HXE/QV2dOhcN9jGYtFhYjnLk0czXFgqMdgbRtc1lKMRtgrcdeMCFxYXmEob6BELzYRnzuZ5bqiAF4J9W9v45dft4O5reoilephO3c7v/OOXuHjxDIlYYgXxAbo6O4mEw9i2zfDoaFUpXG/OQBCPCCxdsJRfh/1fLV2aiPgfqAgQ5XrBkCEwjWC1X47LBa1kbVCQTCYwDQNFgLVTeTBfBZbBzMwkTxw5S8eWWxjs76ZNzXDbjjb2bt9ANrvAbL5E0ZEUSj7ZoktvSmew32Bk3uXweBFPaMzkPVzlcsMmi5/5of286YZONncmCA/cyqOTCf74Y59jYW6SaLjM9isgz76io62NeDwBwKWJibLZtz7rDzgdtEQFtgfpNbX/V0Ym/EAXQNUa0BSxkKRkB1lClwtHaEKSzeewTJNIOIplmXieV0XcqkQUAz2hwBOHXmRBtbNtz0HC7jx94RwP3LGf23Z3kRLz5F3J2ILL0JRNSFd87ViOgpT0t2ncs9PkZ954I2+950Z6QkX0cAfpjjv5f49d4FP/9mU04WMaVqDwlTma7/mkUilaW1qQQjI3P8fk9PRlWX9lPsImxCOSdP77p/1Xl1Fic79aDfHW6FBUa2Wer2hxXvssWB2WUA2OSFEllGEIelKSfEkxl/bXQRGpK4gso2pt37yVaCSC53lMzc6QzWXRpFa9XmVB5PJZWtt7uO/W/dyxJUbSn6Iz4qLhMj07zfDoFMcuLJHO5eltT7B9IEZfbwft7Z04nsZ8QWeBLr5zMcdjzx1maWGGWDRaju7VaOT5Hol4nI72DnQZZDOdvXixDOkh1nDT1pxjoOhISEImTC4qXLcCDaeazKtqmBVxmTmv9QqqgPiJxGC/olkQqe69tqKRQyMpmnuk1zsupQzQMOsQ7zoSkrAJE4s+rnclAcnAuRKNRNm+ZQt6ubZ+Zm42QN6ScsVjSClxHJuS6xGNJbnt+uu4pj9BV8SlPeLSHjWxZAG/mMMIxcj5IWbTRWazMJk3OTGe5rtHjlEsZDF0DV03yn6IeuL7JONxOts7QAgcx+X80AUKpVIwh75/2WJ8S4PuVkmuqJjPrCZNZRlIGTTVajbH6wmHVecmNvdfVpDUE+yV+KmYQKoO9jRiQVdSspRXLGbVlUWlAdf3aUkl2bJxsGxa+szMzpIpB1kake0qClo2n8dH0te3gZ6ODiIGSK+EwEMh8bUQOUcxNTPL+MQYmvCJhsMIIcsNHhpNWp9EPEFne3tVGb0wdJF0NouuaVUE0Mv9pKJB8Gd6ySdfai4OK4rclYx3hSKgOUpc/e5p5ACsy8zWZ+D1C6CWBxgsAE3C5KKPp64UjlDgK0VbSwsb+gfKnU59FhYXWUqnA0iaSgptnaCr1Nk5to3tOOViiwC7P1g4PigfyzCDSmWodVKvE3R++RlaUilakimEDAgzPDbK4tJSuQFUDQJWrBWnK7fW7W6RuB5ML/u19O/G+GsZUTTIl7hy+MYmWRoVsOi1v6REfclY3fF1ZIG63Aqoh48TNWsgV1K0xgVhK0h/vtwTqfLMaZpkfnEB5ftsHNiAlJL2tjZClsX84gK246yst1NBmRoCNMMgYpq1C6hKjoLE9z1Umcs0+/F8D8swaWtrIxqJVDnB8NgIC4tLdWhnlYKZBoyN+jmmliu5lCuDaYg6ODhWdgBRdceUaBibJpF6Ac1ora+1PISsVJBWXLESIVUZnMhfncqr1hduQgqELGe0VNiYrLDPYBflSop4WJAIC/IlVQHtbirEKt+vjKdpGgtLSygUG/s3oGka8VgMywqxmF4ik86UcXVETamqdND0VW28socS/FqFjiq3upGV3n7B+5ZkC6lkotrp03FdhsdGWVpeDnr/UctrQICQEiHUim6p1O3+WEhgO5AvNTH9RI0Gq2nCauuicYAmaRxCSDSrNfFB0SSbS9Y5X2o9CkSNX9WHpRvbwzSmAqwzXrXMWVCGkAnSxVwfSk6tcKQ6idXJCNhg/fWk1Kp5hNFIBNM0kEISi0QIhcJ4rhPAsHp+9V5WjydWZKcFMEqVenoPKTTCoTCdHR0kE/EAZUNK8oU8F0eGyeZygcwvi5L6OalPiVMNhR/xsCAWDsK+Bbv5cwtZh6S+znhr0WXl98rjJTb3qZX8odahQlR2gBA1VDehyhZNHc8RzXhz/WqsjVfpHqJWoISWW6YoMDVBV0qglGByyQu8YPXjKLF6vIZGV54XdN/s7e6lvbV1hTmbL+TJZnPk8vmq4wbR0KmkothVxJ4KcIsjkQjxaIxIOFLnz4bZhTkmpydxXK+KclqB2am/V4UfcJM6+RfkCCp6Uhq+UswsK1yvro1ctWVomWPW5VbWxgs4VvN5byLT68YTicE+tTZYsKomMlRRKJq2B2edz5e3AhrFfCoqaI0K5rKKdF5dxg+iqmjbtQLXisKmaEm10NvdjVXOyA0UWh+7rPwVi0VKpRKe7+OXX7quBb4EAaZpEQ6FMA0TyzSr2rcoZypdmppgaWkZIUU5Mnl1WrtSkIoJWmKChUwQ+LlsuneZfdfGU2uoeGspA7W////L4TZHgJ3HJQAAAABJRU5ErkJggg==" type="image/png">

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
    <meta charset="UTF-8">
        <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

    
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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    toggleReceiver(document.querySelector('select[name="receiver_type"]'));
    </script>
</body>
</html>
'''

STUDENT_PROFILE_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">

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
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/png;base64,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" type="image/png">
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
    return render_template_string(HOME_HTML)

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
            cur.execute(
                "SELECT id FROM students WHERE email = %s",
                (email,)
            )
            existing = cur.fetchone()

            if existing:
                cur.close()
                flash('هذا البريد الإلكتروني مسجل بالفعل', 'danger')
                return render_template_string(STUDENT_REGISTER_HTML)

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
                    cur2 = conn.cursor()
                    cur2.execute(
                        "UPDATE registration_requests SET name = %s, password = %s, phone = %s, parent_phone = %s, address = %s, status = 'pending', created_at = CURRENT_TIMESTAMP WHERE email = %s",
                        (name, generate_password_hash(password), phone, parent_phone, address, email)
                    )
                    cur2.close()
                    conn.commit()
                    flash('تم تحديث طلبك وإعادة إرساله، يرجى انتظار الموافقة', 'success')
                return render_template_string(STUDENT_REGISTER_HTML)

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

        cur.execute(
            "SELECT COUNT(*) as total FROM messages WHERE receiver_id = %s AND sender_type = 'student' AND is_read = FALSE",
            (admin_id,)
        )
        messages_count = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM registration_requests WHERE status = 'pending'"
        )
        pending_requests = cur.fetchone()['total']

        cur.execute("""
            SELECT e.*, s.name as student_name 
            FROM daily_evaluations e
            JOIN students s ON e.student_id = s.id
            ORDER BY e.date DESC, e.id DESC
            LIMIT 10
        """)
        recent_evaluations = cur.fetchall()

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

    accept_id = request.args.get('accept')
    if accept_id:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT * FROM registration_requests WHERE id = %s AND status = 'pending'",
                (accept_id,)
            )
            req = cur.fetchone()

            if req:
                cur.execute(
                    "SELECT COUNT(*) as total FROM students WHERE status = 'active'"
                )
                rank_result = cur.fetchone()
                rank = rank_result['total'] + 1

                cur2 = conn.cursor()
                cur2.execute("""
                    INSERT INTO students (name, email, password, phone, parent_phone, address, rank, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
                """, (req['name'], req['email'], req['password'], req['phone'], 
                      req['parent_phone'], req['address'], rank))

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

        cur.execute(
            "SELECT * FROM daily_evaluations WHERE date = %s",
            (today,)
        )
        existing = cur.fetchall()

        evaluations = {}
        for ev in existing:
            evaluations[str(ev['student_id'])] = dict(ev)

        cur.execute(
            "SELECT COUNT(*) as total FROM daily_evaluations WHERE date = %s AND sent = FALSE",
            (today,)
        )
        unsent_count = cur.fetchone()['total']

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        if request.method == 'POST':
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
                        cur2.execute("""
                            UPDATE daily_evaluations 
                            SET curr_save = %s, score_save = %s, curr_rev = %s, score_rev = %s, 
                                homework_score = %s, notes = %s, sent = FALSE
                            WHERE id = %s AND student_id = %s
                        """, (curr_save, score_save, curr_rev, score_rev, homework_score, notes, ev_id, student_id))
                    else:
                        cur2.execute("""
                            INSERT INTO daily_evaluations (student_id, date, curr_save, score_save, curr_rev, score_rev, homework_score, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (student_id, today, curr_save, score_save, curr_rev, score_rev, homework_score, notes))
                    cur2.close()

                conn.commit()
                flash('تم حفظ التقييمات بنجاح', 'success')
                cur.close()
                return redirect(url_for('evaluation'))

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

                    cur2 = conn.cursor()
                    cur2.execute("""
                        INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                        VALUES (%s, 'admin', %s, %s)
                    """, (admin_id, ev['student_id'], message))

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

        cur.execute(
            "SELECT * FROM homework WHERE date = %s",
            (today,)
        )
        existing = cur.fetchall()

        homework_data = {}
        for hw in existing:
            homework_data[str(hw['student_id'])] = dict(hw)

        cur.execute(
            "SELECT COUNT(*) as total FROM homework WHERE sent = FALSE"
        )
        unsent_count = cur.fetchone()['total']

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

        if request.method == 'POST':
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

                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE messages SET is_read = TRUE WHERE sender_id = %s AND sender_type = 'student' AND receiver_id = %s AND is_read = FALSE",
                    (student_id, admin_id)
                )
                conn.commit()
                cur2.close()

        cur.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
        admin = cur.fetchone()

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

        cur.execute(
            "SELECT * FROM daily_evaluations WHERE student_id = %s AND date = %s AND sent = TRUE",
            (student_id, today)
        )
        today_evaluation = cur.fetchone()

        cur.execute(
            "SELECT COUNT(*) as total FROM homework WHERE student_id = %s AND sent = FALSE",
            (student_id,)
        )
        homework_count = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM competitions WHERE active = TRUE"
        )
        competitions_count = cur.fetchone()['total']

        cur.execute(
            "SELECT COUNT(*) as total FROM messages WHERE receiver_id = %s AND is_read = FALSE AND sender_type = 'admin'",
            (student_id,)
        )
        messages_count = cur.fetchone()['total']

        cur.execute(
            "SELECT * FROM homework WHERE student_id = %s ORDER BY date DESC LIMIT 5",
            (student_id,)
        )
        recent_homework = cur.fetchall()

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

        cur.execute("""
            SELECT SUM(cg.grade) as total 
            FROM competition_grades cg
            JOIN competitions c ON c.id = cg.competition_id
            WHERE cg.student_id = %s AND c.active = TRUE
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
            "SELECT * FROM competitions WHERE active = TRUE ORDER BY date DESC"
        )
        competitions = cur.fetchall()

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
    admin_id = 1

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cur.fetchone()

        cur.execute(
            "SELECT * FROM students WHERE id != %s AND status = 'active' ORDER BY name ASC",
            (student_id,)
        )
        other_students = cur.fetchall()

        selected_type = request.args.get('type', 'admin')
        selected_id = request.args.get('id')
        selected_other = None
        messages_list = []

        if selected_type == 'admin':
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

            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE messages SET is_read = TRUE WHERE sender_id = %s AND sender_type = 'admin' AND receiver_id = %s AND is_read = FALSE",
                (admin_id, student_id)
            )
            conn.commit()
            cur2.close()

        elif selected_id:
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

                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE messages SET is_read = TRUE WHERE sender_id = %s AND sender_type = 'student' AND receiver_id = %s AND is_read = FALSE",
                    (selected_id, student_id)
                )
                conn.commit()
                cur2.close()

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
                cur2.execute("""
                    INSERT INTO messages (sender_id, sender_type, receiver_id, message)
                    VALUES (%s, 'student', %s, %s)
                """, (student_id, admin_id, message_text))
                flash('تم إرسال الرسالة للمشرف', 'success')

            elif receiver_type == 'student' and receiver_id:
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


# تهيئة قاعدة البيانات عند بدء التشغيل
try:
    init_db()
    print("✅ تم إنشاء/تحديث قاعدة البيانات PostgreSQL بنجاح!")
except Exception as e:
    print(f"⚠️ خطأ في تهيئة قاعدة البيانات: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
