from flask import Flask, request, redirect, url_for, render_template_string, flash
import sqlite3
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
    # Upgrade V0.1 databases safely.
    ensure_column(c, "meetings", "address", "TEXT NOT NULL DEFAULT ''")
    ensure_column(c, "meetings", "status", "TEXT NOT NULL DEFAULT 'active'")
    row = c.execute("SELECT COUNT(*) n FROM meetings").fetchone()
    if row["n"] == 0:
        c.execute("""INSERT INTO meetings
            (meeting_no, meeting_date, start_time, end_time, theme, address, status, is_current)
            VALUES (359,'2026-10-31','19:00','21:00',
            '即学即练，打造自己的“冠军演讲”',
            '珠江新城地铁站B1出口 星辰大厦西塔1904','active',1)""")
    c.commit()
    c.close()

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

HOME = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap">
<div class="card">
<h1>后浪 Step Up</h1>
<h2>第 {{m.meeting_no}} 次中文会议</h2>
<div class="meta">
{% if m.theme %}<b>主题 Theme：</b>{{m.theme}}<br>{% endif %}
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
<div class="role"><div><b>{{r[0]}}</b> · {{r[1]}} / {{r[2]}}<br>{% if booked.get(r[0]) %}<span class="who">{{booked[r[0]]['name']}}</span>{% if r[0] in ['PS1','PS2'] %}<div class="muted">{{booked[r[0]]['path']}} {{booked[r[0]]['project']}} {{booked[r[0]]['speech_title']}}</div>{% endif %}{% else %}<span class="muted">空缺 / Available</span>{% endif %}</div>
<div>{% if booked.get(r[0]) %}<a class="btn danger" href="{{url_for('cancel_role',code=r[0])}}">取消</a>{% else %}<a class="btn" href="{{url_for('book_role',code=r[0])}}">报名</a>{% endif %}</div></div>{% endfor %}
</div>
<div class="card"><h2>🌹 通用角色 <span class="pill">Guests & Members</span></h2>
{% for r in open_roles %}
<div class="role"><div><b>{{r[0]}}</b> · {{r[1]}} / {{r[2]}}<br>{% if booked.get(r[0]) %}<span class="who">{{booked[r[0]]['name']}}</span>{% else %}<span class="muted">空缺 / Available</span>{% endif %}</div>
<div>{% if booked.get(r[0]) %}<a class="btn danger" href="{{url_for('cancel_role',code=r[0])}}">取消</a>{% else %}<a class="btn" href="{{url_for('book_role',code=r[0])}}">报名</a>{% endif %}</div></div>{% endfor %}
</div>
<div class="card"><h2>👥 Participants / 参会名单</h2>
<ol>{% for p in participants %}<li>{{p['name']}} <a href="{{url_for('cancel_participant',pid=p['id'])}}">取消参会</a></li>{% else %}<span class="muted">暂时还没有人接龙。</span>{% endfor %}</ol>
<a class="btn green" href="{{url_for('join')}}">＋ 我要参加 / Join</a></div>
{% endif %}
</div></body></html>"""

FORM = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap"><div class="card">
<h2>{{title}}</h2><form method="post">
<label>姓名 Name</label><input name="name" required>
{% if speech %}
<label>演讲路径 Path</label><input name="path" placeholder="例如：应用幽默">
<label>项目进度 Project</label><input name="project" placeholder="例如：L2P2">
<label>演讲题目 Speech Title</label><input name="speech_title">
{% endif %}
<button type="submit">确认提交</button> <a class="btn btn2" href="/">返回</a>
</form></div></div></body></html>"""

ADMIN = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + STYLE + """</head><body><div class="wrap">
<div class="card"><h1>会议管理 Admin</h1>
<p>当前：第 {{m.meeting_no}} 次中文会议 · {{m.meeting_date}} · {{m.start_time}}–{{m.end_time}}</p>
<div class="actions"><a class="btn" href="{{url_for('edit_meeting')}}">编辑本次会议</a><a class="btn green" href="{{url_for('new_meeting')}}">创建下一次会议</a><a class="btn btn2" href="/">返回接龙</a></div>
</div>
<div class="card"><h2>历史会议</h2>
{% for x in history %}<div class="role"><div>第 {{x.meeting_no}} 次 · {{x.meeting_date}}<br><span class="muted">{{x.theme or '未填写主题'}} · {{'休会' if x.status=='recess' else '正常'}}</span></div></div>{% endfor %}
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
<label>主题 Theme</label><input name="theme" placeholder="本周会议主题">
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
    c.close()
    d=datetime.strptime(m["meeting_date"],"%Y-%m-%d")
    wd=["周一","周二","周三","周四","周五","周六","周日"][d.weekday()]
    return render_template_string(HOME,m=m,weekday=wd,booked=booked,participants=participants,
        member_roles=[r for r in ROLES if r[3]=="member"],open_roles=[r for r in ROLES if r[3]=="open"])

@app.route("/join",methods=["GET","POST"])
def join():
    if request.method=="POST":
        name=request.form["name"].strip()
        c=conn(); m=current_meeting(c)
        c.execute("INSERT OR IGNORE INTO participants(meeting_id,name) VALUES (?,?)",(m["id"],name))
        c.commit(); c.close(); flash(f"{name} 已加入本次参会名单。"); return redirect("/")
    return render_template_string(FORM,title="我要参加 / Join Meeting",speech=False)

@app.route("/book/<code>",methods=["GET","POST"])
def book_role(code):
    role=next((r for r in ROLES if r[0]==code),None)
    if not role: return "Unknown role",404
    if request.method=="POST":
        name=request.form["name"].strip()
        c=conn(); m=current_meeting(c)
        try:
            c.execute("""INSERT INTO bookings(meeting_id,role_code,name,path,project,speech_title)
            VALUES(?,?,?,?,?,?)""",(m["id"],code,name,request.form.get("path","").strip(),
            request.form.get("project","").strip(),request.form.get("speech_title","").strip()))
            c.execute("INSERT OR IGNORE INTO participants(meeting_id,name) VALUES (?,?)",(m["id"],name))
            c.commit(); flash(f"{name} 已报名 {role[1]} / {role[2]}。")
        except sqlite3.IntegrityError:
            flash("这个角色刚刚已经被其他人报名了，请刷新查看。")
        c.close(); return redirect("/")
    return render_template_string(FORM,title=f"报名 {role[0]} · {role[1]} / {role[2]}",speech=code in ("PS1","PS2"))

@app.route("/cancel-role/<code>")
def cancel_role(code):
    c=conn(); m=current_meeting(c); c.execute("DELETE FROM bookings WHERE meeting_id=? AND role_code=?",(m["id"],code)); c.commit(); c.close()
    flash(f"{code} 已取消报名。"); return redirect("/")

@app.route("/cancel-participant/<int:pid>")
def cancel_participant(pid):
    c=conn(); p=c.execute("SELECT * FROM participants WHERE id=?",(pid,)).fetchone()
    if p:
        # Cancelling attendance also clears that person's roles for this meeting to avoid ghost bookings.
        c.execute("DELETE FROM bookings WHERE meeting_id=? AND name=?",(p["meeting_id"],p["name"]))
        c.execute("DELETE FROM participants WHERE id=?",(pid,)); c.commit()
    c.close(); flash("已取消参会；该成员本次会议的角色也已释放。"); return redirect("/")

@app.route("/admin")
def admin():
    c=conn(); m=current_meeting(c); history=c.execute("SELECT * FROM meetings ORDER BY meeting_no DESC").fetchall(); c.close()
    return render_template_string(ADMIN,m=m,history=history)

@app.route("/admin/edit",methods=["GET","POST"])
def edit_meeting():
    c=conn(); m=current_meeting(c)
    if request.method=="POST":
        c.execute("""UPDATE meetings SET theme=?,meeting_date=?,start_time=?,end_time=?,address=?,status=? WHERE id=?""",
        (request.form["theme"].strip(),request.form["meeting_date"],request.form["start_time"],request.form["end_time"],
         request.form["address"].strip(),request.form["status"],m["id"]))
        c.commit(); c.close(); flash("本次会议信息已更新，原有报名没有被清除。"); return redirect("/")
    c.close(); return render_template_string(EDIT,m=m)

@app.route("/admin/new",methods=["GET","POST"])
def new_meeting():
    c=conn(); m=current_meeting(c)
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
        request.form["theme"].strip(),request.form["address"].strip(),request.form["status"]))
        c.commit(); c.close(); flash(f"第 {next_no} 次会议已创建。上一期记录已保留。"); return redirect("/")
    c.close(); return render_template_string(NEW,m=m,next_no=next_no,next_date=nd.isoformat())

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=5000,debug=True)
