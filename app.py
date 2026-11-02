from flask import Flask, request, redirect, url_for, render_template_string, flash, abort
import sqlite3
from itsdangerous import URLSafeSerializer, BadSignature
from datetime import date, datetime, timedelta
from pathlib import Path

app = Flask(__name__)
app.secret_key = "stepup-v02-local"
DB = Path(__file__).with_name("stepup.db")

ROLES = [
    ("MM", "Meeting Manager", "会议经理", "member"),
    ("TOM", "Toastmaster of the Meeting", "总主持", "member"),
    ("GE", "General Evaluator", "总点评", "member"),
    ("TTM", "Table Topics Master", "即兴主持", "member"),
    ("TTE", "Table Topics Evaluator", "即兴点评", "member"),
    ("PS1", "Prepared Speaker 1", "备稿演讲1", "member"),
    ("IE1", "Individual Evaluator 1", "备稿点评1", "member"),
    ("PS2", "Prepared Speaker 2", "备稿演讲2", "member"),
    ("IE2", "Individual Evaluator 2", "备稿点评2", "member"),
    ("PS3", "Prepared Speaker 3", "备稿演讲3", "member"),
    ("IE3", "Individual Evaluator 3", "备稿点评3", "member"),
    ("PS4", "Prepared Speaker 4", "备稿演讲4", "member"),
    ("IE4", "Individual Evaluator 4", "备稿点评4", "member"),
    ("WORKSHOP", "Workshop Speaker", "工作坊主讲人", "member"),
    ("PHOTO", "Photographer", "摄影", "open"),
    ("SAA", "Sergeant at Arms", "礼宾官", "open"),
    ("TIMER", "Timer", "时间官", "open"),
    ("GRAMMARIAN", "Grammarian", "语法官", "open"),
    ("AH COUNTER", "Ah-Counter", "哼哈官", "open"),
    ("ICE BREAKER", "Ice Breaker", "破冰师", "open"),
]

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def ensure_column(c, table, column, definition):
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS meetings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_no INTEGER NOT NULL,
        meeting_date TEXT NOT NULL,
        start_time TEXT NOT NULL DEFAULT '19:00',
        end_time TEXT NOT NULL DEFAULT '21:00',
        theme TEXT NOT NULL DEFAULT '',
        address TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        is_current INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id INTEGER NOT NULL,
        role_code TEXT NOT NULL,
        name TEXT NOT NULL,
        path TEXT DEFAULT '',
        project TEXT DEFAULT '',
        speech_title TEXT DEFAULT '',
        UNIQUE(meeting_id, role_code)
    );
    CREATE TABLE IF NOT EXISTS participants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        UNIQUE(meeting_id, name)
    );
    """)
    # Serialize migrations across WSGI workers without replacing existing data.
    c.execute("BEGIN IMMEDIATE")
    # Upgrade V0.1 databases safely.
    ensure_column(c, "meetings", "address", "TEXT NOT NULL DEFAULT ''")
    ensure_column(c, "meetings", "status", "TEXT NOT NULL DEFAULT 'active'")
    old_booking_columns = {r['name'] for r in c.execute('PRAGMA table_info(bookings)')}
    for column in ('project_no', 'project_intro', 'speech_time', 'ppt',
                   'workshop_title', 'workshop_content', 'duration', 'introduction'):
        ensure_column(c, 'bookings', column, "TEXT NOT NULL DEFAULT ''")
    if 'project_no' not in old_booking_columns:
        c.execute("UPDATE bookings SET project_no=COALESCE(project,'')")
    row = c.execute("SELECT COUNT(*) n FROM meetings").fetchone()
    if row["n"] == 0:
        c.execute("""INSERT INTO meetings
            (meeting_no, meeting_date, start_time, end_time, theme, address, status, is_current)
            VALUES (359,'2026-10-31','19:00','21:00',
            '即学即练，打造自己的“冠军演讲”',
            '珠江新城地铁站B1出口 星辰大厦西塔1904','active',1)""")
    ensure_column(c, "meetings", "roles_initialized", "INTEGER NOT NULL DEFAULT 0")
    c.execute("""CREATE TABLE IF NOT EXISTS meeting_roles(
        meeting_id INTEGER NOT NULL, code TEXT NOT NULL,
        name_en TEXT NOT NULL, name_zh TEXT NOT NULL,
        audience TEXT NOT NULL CHECK(audience IN ('member','open')),
        speech INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(meeting_id, code))""")
    for meeting in c.execute("SELECT id FROM meetings WHERE roles_initialized=0").fetchall():
        for position, role in enumerate(ROLES):
            c.execute("INSERT OR IGNORE INTO meeting_roles VALUES(?,?,?,?,?,?,?,0)",
                      (meeting["id"], *role[:3], role[3], int(role[0].startswith('PS')), position))
        # Retain any nonstandard legacy booking as a visible role.
        for booking in c.execute("SELECT DISTINCT role_code FROM bookings WHERE meeting_id=?", (meeting['id'],)).fetchall():
            code = booking['role_code']
            c.execute("INSERT OR IGNORE INTO meeting_roles VALUES(?,?,?,?,?,?,999,0)",
                      (meeting['id'], code, code, code, 'open', int(code.startswith('PS'))))
        c.execute("UPDATE meetings SET roles_initialized=1 WHERE id=?", (meeting['id'],))
    chosen = c.execute("SELECT id FROM meetings ORDER BY is_current DESC, id DESC LIMIT 1").fetchone()['id']
    c.execute("UPDATE meetings SET is_current=0 WHERE id<>?", (chosen,))
    c.execute("UPDATE meetings SET is_current=1 WHERE id=?", (chosen,))
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_current_meeting ON meetings(is_current) WHERE is_current=1")
    normalize_role_positions(c, chosen)
    c.commit()
    c.close()

def normalize_role_positions(c, meeting_id):
    defaults = {role[0]: position for position, role in enumerate(ROLES)}
    rows = c.execute('SELECT code FROM meeting_roles WHERE meeting_id=? ORDER BY position,code', (meeting_id,)).fetchall()
    custom_position = len(defaults)
    for row in rows:
        position = defaults.get(row['code'])
        if position is None:
            position = custom_position
            custom_position += 1
        c.execute('UPDATE meeting_roles SET position=? WHERE meeting_id=? AND code=?',
                  (position, meeting_id, row['code']))

def meeting_roles(c, meeting_id):
    return c.execute("SELECT code,name_en,name_zh,audience,speech,deleted FROM meeting_roles WHERE meeting_id=? AND (deleted=0 OR EXISTS (SELECT 1 FROM bookings b WHERE b.meeting_id=meeting_roles.meeting_id AND b.role_code=meeting_roles.code)) ORDER BY position,code", (meeting_id,)).fetchall()

def current_meeting(c):
    return c.execute("SELECT * FROM meetings WHERE is_current=1 ORDER BY id DESC LIMIT 1").fetchone()

STYLE = """
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;background:#f6f7fb;margin:0;color:#1f2937}
.wrap{max-width:820px;margin:auto;padding:18px}
.card{background:white;border-radius:18px;padding:20px;margin:14px 0;box-shadow:0 5px 20px rgba(0,0,0,.06)}
h1,h2,h3{margin-top:0}.muted{color:#6b7280}.meta{line-height:1.8}
.role{display:flex;justify-content:space-between;gap:12px;align-items:center;border-top:1px solid #eee;padding:12px 0}
.role:first-of-type{border-top:0}.who{font-weight:700}
button,.btn{border:0;border-radius:10px;padding:9px 13px;background:#111827;color:#fff;text-decoration:none;display:inline-block;cursor:pointer}
.btn2{background:#e5e7eb;color:#111827}.danger{background:#b91c1c}.green{background:#047857}
input,select,textarea{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d1d5db;border-radius:9px;margin:6px 0 14px;font:inherit}
label{font-weight:650}.notice{background:#fff7ed;border:1px solid #fed7aa;padding:14px;border-radius:12px}
.flash{background:#ecfdf5;border:1px solid #a7f3d0;padding:10px;border-radius:10px;margin:10px 0}
.actions{display:flex;flex-wrap:wrap;gap:8px}.pill{font-size:13px;padding:3px 8px;border-radius:999px;background:#f3f4f6}
</style>
"""

BOOKING_DETAILS = """{% macro booking_details(b, r) -%}
{% if r[0]=='WORKSHOP' %}
{% if b.workshop_title %}<div class="muted">{{b.workshop_title}}</div>{% endif %}
{% elif r[4] or r[0] in ['PS1','PS2','PS3','PS4'] %}
{% if b.speech_title %}<div class="muted">《{{b.speech_title}}》</div>{% endif %}
{% endif %}
{%- endmacro %}"""

HOME = BOOKING_DETAILS + """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap">
<div class="card">
<h1>后浪 Step Up</h1>
<h2>第 {{m.meeting_no}} 次中文会议</h2>
<div class="meta">
<b>主题 Theme：</b>{{m.theme or '待定'}}<br>
<b>时间 Time：</b>{{m.meeting_date}} {{weekday}} · {{m.start_time}}–{{m.end_time}}<br>
{% if m.address %}<b>地点 Address：</b>{{m.address}}<br>{% endif %}
</div>
{% if m.status == 'recess' %}<div class="notice"><b>本周休会 / Meeting Recess</b><br>本次会议暂停报名。管理员可随时恢复或编辑会议。</div>{% endif %}
<div class="actions" style="margin-top:14px"><a class="btn btn2" href="{{url_for('admin')}}">会议管理 Admin</a></div>
</div>
{% for msg in get_flashed_messages() %}<div class="flash">{{msg}}</div>{% endfor %}
{% if m.status != 'recess' %}
<div class="card"><h2>☀️ 会员角色 <span class="pill">Members Only</span></h2>
{% for r in member_roles %}
<div class="role"><div><b>{{r[0]}}</b> · {{r[1]}} / {{r[2]}}<br>{% if booked.get(r[0]) %}<span class="who">{{booked[r[0]]['name']}}</span>{{ booking_details(booked[r[0]], r) }}{% else %}<span class="muted">空缺 / Available</span>{% endif %}</div>
<div>{% if booked.get(r[0]) %}{% if r[0] in ['PS1','PS2','PS3','PS4','WORKSHOP'] %}<a class="btn btn2" href="{{url_for('edit_booking',code=r[0])}}">修改</a> {% endif %}<a class="btn danger" href="{{url_for('cancel_role',code=r[0])}}">取消</a>{% elif not r[5] %}<a class="btn" href="{{url_for('book_role',code=r[0])}}">报名</a>{% endif %}</div></div>{% endfor %}
</div>
<div class="card"><h2>🌹 通用角色 <span class="pill">Guests & Members</span></h2>
{% for r in open_roles %}
<div class="role"><div><b>{{r[0]}}</b> · {{r[1]}} / {{r[2]}}<br>{% if booked.get(r[0]) %}<span class="who">{{booked[r[0]]['name']}}</span>{{ booking_details(booked[r[0]], r) }}{% else %}<span class="muted">空缺 / Available</span>{% endif %}</div>
<div>{% if booked.get(r[0]) %}{% if r[0] in ['PS1','PS2','PS3','PS4','WORKSHOP'] %}<a class="btn btn2" href="{{url_for('edit_booking',code=r[0])}}">修改</a> {% endif %}<a class="btn danger" href="{{url_for('cancel_role',code=r[0])}}">取消</a>{% elif not r[5] %}<a class="btn" href="{{url_for('book_role',code=r[0])}}">报名</a>{% endif %}</div></div>{% endfor %}
</div>
<div class="card"><h2>👥 Participants / 参会名单</h2>
<ol>{% for p in participants %}<li>{{p['name']}} <a href="{{url_for('cancel_participant',pid=p['id'])}}">取消参会</a></li>{% else %}<span class="muted">暂时还没有人接龙。</span>{% endfor %}</ol>
<a class="btn green" href="{{url_for('join')}}">＋ 我要参加 / Join</a></div>
{% endif %}
</div></body></html>"""

FORM = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap"><div class="card">
<h2>{{title}}</h2><form method="post"><input type="hidden" name="meeting_id" value="{{meeting_id}}">{% if booking %}<input type="hidden" name="booking_id" value="{{booking.id}}">{% endif %}
{% if workshop %}
<label>主讲人 Speaker <span class="pill">必填</span></label><input value="{{booking.name if booking else ''}}" name="name" required>
<label>工作坊题目 Workshop Title</label><input value="{{booking.workshop_title if booking else ''}}" name="workshop_title">
<label>工作坊内容 Workshop Content</label><textarea name="workshop_content" rows="5">{{booking.workshop_content if booking else ''}}</textarea>
<label>时长 Duration</label><input value="{{booking.duration if booking else ''}}" name="duration">
<label>简介 Introduction</label><textarea name="introduction" rows="4">{{booking.introduction if booking else ''}}</textarea>
{% elif speech %}
<label>演讲者 Speaker <span class="pill">必填</span></label><input value="{{booking.name if booking else ''}}" name="name" required>
<label>项目编号 Project No.</label><input value="{{booking.project_no if booking else ''}}" name="project_no">
<label>项目介绍 Project Intro.</label><textarea name="project_intro" rows="5">{{booking.project_intro if booking else ''}}</textarea>
<label>演讲题目 Speech Title</label><input value="{{booking.speech_title if booking else ''}}" name="speech_title">
<label>时长 Time</label><input name="speech_time" value="{{booking.speech_time if booking else '5-7 mins'}}">
<label>PPT</label><select name="ppt"><option value=""></option><option value="Y" {% if booking and booking.ppt=='Y' %}selected{% endif %}>Y</option><option value="N" {% if booking and booking.ppt=='N' %}selected{% endif %}>N</option></select>
{% else %}
<label>姓名 Name</label><input value="{{booking.name if booking else ''}}" name="name" required>
{% endif %}
<button type="submit">确认提交</button> <a class="btn btn2" href="/">返回</a>
</form></div></div></body></html>"""

ADMIN = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap">
<div class="card"><h1>会议管理 Admin</h1>
<p>当前：第 {{m.meeting_no}} 次中文会议 · {{m.meeting_date}} · {{m.start_time}}–{{m.end_time}}</p>
<div class="actions"><a class="btn" href="{{url_for('roles_admin',mid=m.id)}}">编辑本期角色</a><a class="btn" href="{{url_for('edit_meeting')}}">编辑本次会议</a><a class="btn green" href="{{url_for('new_meeting')}}">创建下一次会议</a><a class="btn btn2" href="/">返回接龙</a></div>
</div>
<div class="card"><h2>历史会议</h2>
{% for x in history %}<div class="role"><div>第 {{x.meeting_no}} 次 · {{x.meeting_date}}<br><span class="muted">{{x.theme or '未填写主题'}} · {{'休会' if x.status=='recess' else '正常'}}</span>{% if x.is_current %}<p class="pill green">当前会议 / Current</p>{% endif %}</div><div>{% if not x.is_current %}<form method="post" action="{{url_for('set_current',mid=x.id)}}"><button>设为当前</button></form>{% endif %}<a class="btn btn2" href="{{url_for('roles_admin',mid=x.id)}}">编辑角色</a></div></div>{% endfor %}
</div></div></body></html>"""

EDIT = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap"><div class="card">
<h2>编辑第 {{m.meeting_no}} 次会议</h2>
<p class="muted">修改这些信息不会清除已经报名的角色或参会名单。</p>
<form method="post">
<label>主题 Theme</label><input name="theme" value="{{m.theme}}">
<label>日期 Date</label><input type="date" name="meeting_date" value="{{m.meeting_date}}" required>
<label>开始时间 Start</label><input type="time" name="start_time" value="{{m.start_time}}" required>
<label>结束时间 End</label><input type="time" name="end_time" value="{{m.end_time}}" required>
<label>地点 Address</label><textarea name="address">{{m.address}}</textarea>
<label>会议状态 Status</label><select name="status"><option value="active" {% if m.status=='active' %}selected{% endif %}>正常 / Active</option><option value="recess" {% if m.status=='recess' %}selected{% endif %}>休会 / Recess</option></select>
<button>保存修改</button> <a class="btn btn2" href="{{url_for('admin')}}">取消</a>
</form></div></div></body></html>"""

NEW = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap"><div class="card">
<h2>创建第 {{next_no}} 次中文会议</h2>
<p class="muted">默认日期为下一周六、时间 19:00–21:00；都可以手动修改。创建后上一期数据会保留。</p>
<form method="post">
<label>主题 Theme</label><input name="theme" value="待定">
<label>日期 Date</label><input type="date" name="meeting_date" value="{{next_date}}" required>
<label>开始时间 Start</label><input type="time" name="start_time" value="19:00" required>
<label>结束时间 End</label><input type="time" name="end_time" value="21:00" required>
<label>地点 Address</label><textarea name="address">{{m.address}}</textarea>
<label>会议状态 Status</label><select name="status"><option value="active">正常 / Active</option><option value="recess">休会 / Recess</option></select>
<button>确认创建</button> <a class="btn btn2" href="{{url_for('admin')}}">取消</a>
</form></div></div></body></html>"""

@app.route("/")
def home():
    c=conn(); m=current_meeting(c)
    bookings=c.execute("SELECT * FROM bookings WHERE meeting_id=?",(m["id"],)).fetchall()
    booked={x["role_code"]:x for x in bookings}
    participants=c.execute("SELECT * FROM participants WHERE meeting_id=? ORDER BY id",(m["id"],)).fetchall()
    roles=meeting_roles(c,m["id"])
    c.close()
    d=datetime.strptime(m["meeting_date"],"%Y-%m-%d")
    wd=["周一","周二","周三","周四","周五","周六","周日"][d.weekday()]
    return render_template_string(HOME,m=m,weekday=wd,booked=booked,participants=participants,
        member_roles=[r for r in roles if r[3]=="member"],open_roles=[r for r in roles if r[3]=="open"])

def form_meeting(c):
    m = current_meeting(c)
    if request.method == 'POST' and request.form.get('meeting_id') != str(m['id']):
        abort(409, '会议已切换，请返回首页重新操作。')
    if m['status'] == 'recess':
        abort(409, '本次会议休会，暂停报名。')
    return m

@app.route('/join', methods=['GET','POST'])
def join():
    with conn() as c:
        m = form_meeting(c)
        if request.method == 'POST':
            name = request.form.get('name','').strip()
            if not name: abort(400, '请填写姓名。')
            c.execute('INSERT OR IGNORE INTO participants(meeting_id,name) VALUES (?,?)',(m['id'],name))
            flash(f'{name} 已加入本次参会名单。')
            return redirect('/')
        return render_template_string(FORM,title='我要参加 / Join Meeting',speech=False,meeting_id=m['id'])

@app.route('/book/<code>', methods=['GET','POST'])
def book_role(code, editing=False):
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        m = form_meeting(c)
        booking = None
        if editing:
            if code not in ('PS1','PS2','PS3','PS4','WORKSHOP'): abort(404)
            booking = c.execute('SELECT * FROM bookings WHERE meeting_id=? AND role_code=?', (m['id'],code)).fetchone()
            if booking is None: abort(404)
            if request.method == 'POST' and request.form.get('booking_id') != str(booking['id']):
                abort(409, '报名已变化，请重新打开修改页面。')
        role = c.execute('SELECT * FROM meeting_roles WHERE meeting_id=? AND code=? AND (deleted=0 OR ?)',(m['id'],code,editing)).fetchone()
        if role is None: abort(404)
        if request.method == 'POST':
            name = request.form.get('name','').strip()
            if not name:
                abort(400, '请填写姓名。')
            columns = ('path', 'project', 'speech_title', 'project_no', 'project_intro',
                       'speech_time', 'ppt', 'workshop_title', 'workshop_content',
                       'duration', 'introduction')
            values = {key: request.form.get(key, '').strip() for key in columns}
            if editing:
                for key in ('path', 'project'):
                    if key not in request.form:
                        values[key] = booking[key]
            # Accept V0.3 form submissions without discarding their legacy fields.
            if 'project_no' not in request.form:
                values['project_no'] = values['project']
            if values['ppt'] not in ('', 'Y', 'N'):
                abort(400, 'PPT 请选择 Y 或 N。')
            try:
                if editing:
                    assignments = ','.join(key+'=?' for key in columns)
                    c.execute('UPDATE bookings SET name=?,' + assignments + ' WHERE id=? AND meeting_id=?',
                              (name, *(values[key] for key in columns), booking['id'], m['id']))
                else:
                    c.execute('INSERT INTO bookings(meeting_id,role_code,name,' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in range(3+len(columns))) + ')',
                              (m['id'], code, name, *(values[key] for key in columns)))
                c.execute('INSERT OR IGNORE INTO participants(meeting_id,name) VALUES (?,?)',(m['id'],name))
                flash('修改已保存。' if editing else '报名成功。')
            except sqlite3.IntegrityError:
                flash('这个角色已经被报名了，请刷新查看。')
            return redirect('/')
        return render_template_string(FORM,title=f"{'修改' if editing else '报名'} {code} · {role['name_en']} / {role['name_zh']}",speech=role['speech'] or (code.startswith('PS') and code[2:].isdigit()),workshop=code=='WORKSHOP',meeting_id=m['id'],booking=booking)

@app.route('/book/<code>/edit', methods=['GET','POST'])
def edit_booking(code):
    return book_role(code, editing=True)

CONFIRM = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """<div class="wrap"><div class="card"><h2>确认取消</h2><p>{{message}}</p><form method="post"><input type="hidden" name="token" value="{{token}}"><button class="danger">确认取消</button> <a class="btn btn2" href="/">返回，保留报名</a></form></div></div>"""

@app.route('/cancel-role/<code>', methods=['GET','POST'])
def cancel_role(code):
    return cancel_booking(code=code)

@app.route('/cancel-participant/<int:pid>', methods=['GET','POST'])
def cancel_participant(pid):
    return cancel_booking(pid=pid)

def cancel_booking(code=None, pid=None):
    signer = URLSafeSerializer(app.secret_key, salt='cancel-v03')
    with conn() as c:
        m = current_meeting(c)
        if code is not None:
            row = c.execute('SELECT * FROM bookings WHERE meeting_id=? AND role_code=?',(m['id'],code)).fetchone()
            kind = 'role'
        else:
            row = c.execute('SELECT * FROM participants WHERE meeting_id=? AND id=?',(m['id'],pid)).fetchone()
            kind = 'participant'
        if row is None: abort(404)
        target = [kind, m['id'], row['id'], row['name']]
        if request.method == 'POST':
            try:
                if signer.loads(request.form.get('token','')) != target: abort(409)
            except BadSignature:
                abort(400, '请先打开确认页面。')
            if code is not None:
                c.execute('DELETE FROM bookings WHERE id=?',(row['id'],))
            else:
                c.execute('DELETE FROM bookings WHERE meeting_id=? AND name=?',(m['id'],row['name']))
                c.execute('DELETE FROM participants WHERE id=?',(row['id'],))
            flash('已取消报名。')
            return redirect('/')
        message = f"确认取消第 {m['meeting_no']} 次会议中 {row['name']} 的" + (f'{code} 角色报名？' if code is not None else '参会？该成员本期所有角色也会释放。')
        return render_template_string(CONFIRM,message=message,token=signer.dumps(target))

@app.route("/admin")
def admin():
    c=conn(); m=current_meeting(c); history=c.execute("SELECT * FROM meetings ORDER BY meeting_no DESC").fetchall(); c.close()
    return render_template_string(ADMIN,m=m,history=history)

@app.route("/admin/edit",methods=["GET","POST"])
def edit_meeting():
    c=conn(); m=current_meeting(c)
    if request.method=="POST":
        c.execute("""UPDATE meetings SET theme=?,meeting_date=?,start_time=?,end_time=?,address=?,status=? WHERE id=?""",
        ((request.form.get("theme", "").strip() or "待定"),request.form["meeting_date"],request.form["start_time"],request.form["end_time"],
         request.form["address"].strip(),request.form["status"],m["id"]))
        c.commit(); c.close(); flash("本次会议信息已更新，原有报名没有被清除。"); return redirect("/")
    c.close(); return render_template_string(EDIT,m=m)

@app.route("/admin/new",methods=["GET","POST"])
def new_meeting():
    c=conn()
    c.execute("BEGIN IMMEDIATE")
    m=c.execute("SELECT * FROM meetings ORDER BY meeting_no DESC,id DESC LIMIT 1").fetchone()
    d=datetime.strptime(m["meeting_date"],"%Y-%m-%d").date()
    # First Saturday strictly after the current meeting date.
    delta=(5-d.weekday())%7
    if delta==0: delta=7
    nd=d+timedelta(days=delta)
    next_no=m["meeting_no"]+1
    if request.method=="POST":
        c.execute("UPDATE meetings SET is_current=0 WHERE is_current=1")
        c.execute("""INSERT INTO meetings(meeting_no,meeting_date,start_time,end_time,theme,address,status,is_current)
        VALUES(?,?,?,?,?,?,?,1)""",(next_no,request.form["meeting_date"],request.form["start_time"],request.form["end_time"],
        (request.form.get("theme", "").strip() or "待定"),request.form["address"].strip(),request.form["status"]))
        new_id=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO meeting_roles SELECT ?,code,name_en,name_zh,audience,speech,position,0 FROM meeting_roles WHERE meeting_id=? AND deleted=0", (new_id,m['id']))
        # Complete the default roster only for the new meeting; history is untouched.
        for position, role in enumerate(ROLES):
            c.execute("INSERT OR IGNORE INTO meeting_roles VALUES(?,?,?,?,?,?,?,0)",
                      (new_id, *role[:3], role[3], int(role[0].startswith('PS')), position))
        normalize_role_positions(c, new_id)
        c.execute("UPDATE meetings SET roles_initialized=1 WHERE id=?", (new_id,))
        c.commit(); c.close(); flash(f"第 {next_no} 次会议已创建。上一期记录已保留。"); return redirect("/")
    c.close(); return render_template_string(NEW,m=m,next_no=next_no,next_date=nd.isoformat())

ROLE_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """<div class="wrap"><div class="card"><h2>第 {{m.meeting_no}} 次会议角色</h2><p>仅修改本期。删除角色保留已有报名；已有报名仍可取消。</p><a class="btn btn2" href="/admin">返回管理</a></div>
{% for r in roles %}<div class="card"><form method="post"><input type="hidden" name="code" value="{{r.code}}"><b>{{r.code}}</b>
<label>English Name</label><input name="name_en" value="{{r.name_en}}" required>
<label>中文名称</label><input name="name_zh" value="{{r.name_zh}}" required>
<label>报名范围</label><select name="audience"><option value="member" {% if r.audience=='member' %}selected{% endif %}>Member Only</option><option value="open" {% if r.audience=='open' %}selected{% endif %}>Guests & Members</option></select>
<label>环节类型</label><select name="speech"><option value="0">普通角色 / 临时环节</option><option value="1" {% if r.speech %}selected{% endif %}>备稿演讲</option></select>
<button name="action" value="save">保存修改</button> <button class="danger" name="action" value="delete" onclick="return confirm('确认删除本期角色？已有报名仍会保留。')">删除角色</button></form></div>{% endfor %}
<div class="card"><h3>新增角色</h3><form method="post"><label>角色代码（如 PS3、IE3、WORKSHOP）</label><input name="code" required><label>English Name</label><input name="name_en" required><label>中文名称</label><input name="name_zh" required><label>报名范围</label><select name="audience"><option value="member">Member Only</option><option value="open">Guests & Members</option></select><label>环节类型</label><select name="speech"><option value="0">普通角色 / 临时环节</option><option value="1">备稿演讲</option></select><button name="action" value="add">新增角色</button></form></div></div>"""

@app.route('/admin/meetings/<int:mid>/current', methods=['POST'])
def set_current(mid):
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT id FROM meetings WHERE id=?',(mid,)).fetchone() is None:
            abort(404)
        c.execute('UPDATE meetings SET is_current=0 WHERE is_current=1')
        c.execute('UPDATE meetings SET is_current=1 WHERE id=?',(mid,))
        normalize_role_positions(c, mid)
    flash('已切换当前会议，所有历史与报名均保留。')
    return redirect('/admin')

@app.route('/admin/meetings/<int:mid>/roles', methods=['GET','POST'])
def roles_admin(mid):
    with conn() as c:
        m = c.execute('SELECT * FROM meetings WHERE id=?',(mid,)).fetchone()
        if m is None: abort(404)
        if request.method == 'POST':
            code = request.form.get('code','').strip().upper()
            action = request.form.get('action')
            if not code or '/' in code or len(code)>50: abort(400, '角色代码无效。')
            existing = c.execute('SELECT * FROM meeting_roles WHERE meeting_id=? AND code=?',(mid,code)).fetchone()
            if action == 'delete':
                if existing is None: abort(404)
                c.execute('UPDATE meeting_roles SET deleted=1 WHERE meeting_id=? AND code=?',(mid,code))
            else:
                en = request.form.get('name_en','').strip()
                zh = request.form.get('name_zh','').strip()
                audience = request.form.get('audience')
                speech = int(request.form.get('speech')=='1' or (code.startswith('PS') and code[2:].isdigit()))
                if not en or not zh or audience not in ('member','open'): abort(400, '请填写角色名称和报名范围。')
                if action == 'add':
                    if existing is not None: abort(409, '角色代码已使用，请修改已有角色或使用新代码。')
                    position = c.execute('SELECT COALESCE(MAX(position),-1)+1 FROM meeting_roles WHERE meeting_id=?',(mid,)).fetchone()[0]
                    c.execute('INSERT INTO meeting_roles VALUES(?,?,?,?,?,?,?,0)',(mid,code,en,zh,audience,speech,position))
                elif action == 'save':
                    if existing is None: abort(404)
                    c.execute('UPDATE meeting_roles SET name_en=?,name_zh=?,audience=?,speech=? WHERE meeting_id=? AND code=?',(en,zh,audience,speech,mid,code))
                else: abort(400)
            return redirect(url_for('roles_admin',mid=mid))
        roles = c.execute('SELECT * FROM meeting_roles WHERE meeting_id=? AND deleted=0 ORDER BY position,code',(mid,)).fetchall()
        return render_template_string(ROLE_PAGE,m=m,roles=roles)


@app.before_request
def migrate_database():
    if app.config.get('_MIGRATED_DB') != str(DB):
        init_db()
        app.config['_MIGRATED_DB'] = str(DB)

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=5000,debug=True)
