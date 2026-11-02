import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
import app


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.app.config.update(TESTING=True)
        app.app.config.pop('_MIGRATED_DB', None)
        self.client = app.app.test_client()
        self.client.get('/')

    def tearDown(self):
        app.DB = self.old_db
        app.app.config.pop('_MIGRATED_DB', None)
        self.temp.cleanup()

    def booking(self, code):
        with app.conn() as c:
            return dict(c.execute('SELECT * FROM bookings WHERE meeting_id=1 AND role_code=?',(code,)).fetchone())

    def post(self, code, **fields):
        return self.client.post('/book/'+code, data=dict(meeting_id=1, name='陈孝延', **fields))

    def test_all_speakers_and_evaluators_name_only(self):
        for code in ['PS1','PS2','PS3','PS4','IE1','IE2','IE3','IE4','WORKSHOP']:
            with self.subTest(code=code):
                self.assertEqual(self.post(code).status_code,302)
                self.assertEqual(self.booking(code)['name'],'陈孝延')
        html=self.client.get('/').get_data(as_text=True)
        self.assertNotIn('PPT:',html)
        self.assertNotIn('《》',html)
        self.assertNotIn('<div class="muted"></div>',html)
        self.assertEqual(self.client.post('/book/MM',data=dict(meeting_id=1,name='  ')).status_code,400)

    def test_forms_markup(self):
        for code in ['PS1','PS2','PS3','PS4']:
            html=self.client.get('/book/'+code).get_data(as_text=True)
            self.assertEqual(len(re.findall(r'\brequired\b',html)),1)
            self.assertIn('演讲者 Speaker',html)
            self.assertIn('name="speech_time" value="5-7 mins"',html)
            self.assertIn('<textarea name="project_intro"',html)
            self.assertIn('<option value=""></option>',html)
            self.assertNotIn('选填',html)
            self.assertNotIn('唯一必须填写',html)
        html=self.client.get('/book/WORKSHOP').get_data(as_text=True)
        self.assertEqual(len(re.findall(r'\brequired\b',html)),1)
        self.assertIn('主讲人 Speaker',html)
        for key in ['workshop_content','introduction']:
            self.assertIn('<textarea name="'+key+'"',html)
        self.assertNotIn('选填',html)

    def test_optional_speech_fields_individually_and_partial(self):
        cases=[dict(project_no='L2P2'),dict(project_intro='项目介绍第一行\n完整第二行'),
               dict(speech_title='Token欠费了'),dict(speech_time='8-10 mins'),
               dict(ppt='Y'),dict(ppt='N'),dict(ppt=''),dict(speech_time=''),
               dict(speech_time='5-7 mins'),dict(project_no='L2P2',speech_title='Token欠费了',speech_time='5-7 mins',ppt='Y',project_intro='PRIVATE INTRO')]
        for fields in cases:
            with self.subTest(fields=fields):
                with app.conn() as c:
                    c.execute('DELETE FROM bookings WHERE role_code="PS1"')
                self.assertEqual(self.post('PS1',**fields).status_code,302)
                row=self.booking('PS1')
                for key,value in fields.items(): self.assertEqual(row[key],value)
                html=self.client.get('/').get_data(as_text=True)
                self.assertNotIn('PRIVATE INTRO',html)
                self.assertNotIn('项目介绍第一行',html)
                self.assertNotIn('PPT:',html)
                if fields.get('speech_title'): self.assertIn('《Token欠费了》',html)
                else: self.assertNotIn('《',html)
                self.assertNotIn(' · </div>',html)
        with app.conn() as c: c.execute('DELETE FROM bookings WHERE role_code="PS1"')
        self.assertEqual(self.post('PS1',ppt='invalid').status_code,400)

    def test_workshop_details_saved_but_summary_is_short(self):
        fields=dict(workshop_title='工作坊主题',workshop_content='PRIVATE CONTENT\n第二行',duration='45 mins',introduction='PRIVATE BIO\n完整简介')
        self.assertEqual(self.post('WORKSHOP',**fields).status_code,302)
        row=self.booking('WORKSHOP')
        for key,value in fields.items(): self.assertEqual(row[key],value)
        html=self.client.get('/').get_data(as_text=True)
        self.assertIn('工作坊主题',html)
        self.assertNotIn('45 mins',html)
        self.assertNotIn('PRIVATE CONTENT',html)
        self.assertNotIn('PRIVATE BIO',html)

    def test_new_defaults_copy_custom_roles_and_theme(self):
        self.client.post('/admin/meetings/1/roles',data=dict(code='CUSTOM',action='add',name_en='Custom',name_zh='临时',audience='open',speech='0'))
        self.client.post('/admin/meetings/1/roles',data=dict(code='PS4',action='delete'))
        html=self.client.get('/admin/new').get_data(as_text=True)
        self.assertIn('name="theme" value="待定"',html)
        data=dict(meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='',status='active')
        self.assertEqual(self.client.post('/admin/new',data=data).status_code,302)
        with app.conn() as c:
            self.assertEqual(app.current_meeting(c)['theme'],'待定')
            roles={r['code']:dict(r) for r in c.execute('SELECT * FROM meeting_roles WHERE meeting_id=2')}
            for code in ['PS1','PS2','PS3','PS4','IE1','IE2','IE3','IE4','WORKSHOP']:
                self.assertEqual(roles[code]['audience'],'member')
                self.assertEqual(roles[code]['deleted'],0)
            self.assertIn('CUSTOM',roles)
            self.assertEqual(c.execute("SELECT deleted FROM meeting_roles WHERE meeting_id=1 AND code='PS4'").fetchone()[0],1)
        self.assertIn('主题 Theme：</b>待定',self.client.get('/').get_data(as_text=True))
        data.update(theme='确定的主题')
        self.client.post('/admin/edit',data=data)
        self.assertIn('确定的主题',self.client.get('/').get_data(as_text=True))
        data['theme']=' '
        self.client.post('/admin/edit',data=data)
        self.assertIn('主题 Theme：</b>待定',self.client.get('/').get_data(as_text=True))

    def test_extended_bookings_survive_359_363_359(self):
        self.post('PS3',project_no='L2P2',project_intro='完整项目介绍',speech_title='演讲',speech_time='7 mins',ppt='N')
        self.post('WORKSHOP',workshop_title='工作坊',workshop_content='完整内容',duration='30 mins',introduction='完整简介')
        with app.conn() as c:
            original=[tuple(r) for r in c.execute('SELECT * FROM bookings ORDER BY id')]
            participants=[tuple(r) for r in c.execute('SELECT * FROM participants ORDER BY id')]
        for no in range(360,364):
            self.assertEqual(self.client.post('/admin/new',data=dict(meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='',status='active')).status_code,302)
        with app.conn() as c:
            self.assertEqual(app.current_meeting(c)['meeting_no'],363)
        self.client.post('/admin/meetings/1/current')
        app.init_db()
        with app.conn() as c:
            self.assertEqual(app.current_meeting(c)['meeting_no'],359)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM meetings WHERE is_current=1').fetchone()[0],1)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM bookings ORDER BY id')],original)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM participants ORDER BY id')],participants)
        html=self.client.get('/').get_data(as_text=True)
        self.assertNotIn('7 mins',html)
        self.assertNotIn('30 mins',html)

    def test_v03_migration_preserves_every_legacy_field(self):
        # Fixture uses the published V0.3 schema, without the new columns.
        legacy_db = Path(self.temp.name)/'v03.db'
        with sqlite3.connect(legacy_db) as c:
            c.executescript("""
            CREATE TABLE meetings(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_no INTEGER NOT NULL,meeting_date TEXT NOT NULL,start_time TEXT NOT NULL DEFAULT '19:00',end_time TEXT NOT NULL DEFAULT '21:00',theme TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',is_current INTEGER NOT NULL DEFAULT 0,roles_initialized INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE bookings(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id INTEGER NOT NULL,role_code TEXT NOT NULL,name TEXT NOT NULL,path TEXT DEFAULT '',project TEXT DEFAULT '',speech_title TEXT DEFAULT '',UNIQUE(meeting_id,role_code));
            CREATE TABLE participants(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id INTEGER NOT NULL,name TEXT NOT NULL,UNIQUE(meeting_id,name));
            CREATE TABLE meeting_roles(meeting_id INTEGER NOT NULL,code TEXT NOT NULL,name_en TEXT NOT NULL,name_zh TEXT NOT NULL,audience TEXT NOT NULL CHECK(audience IN ('member','open')),speech INTEGER NOT NULL DEFAULT 0,position INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(meeting_id,code));
            INSERT INTO meetings VALUES(1,359,'2026-10-31','19:00','21:00','Old theme','Old address','active',1,1);
            INSERT INTO meeting_roles VALUES(1,'PS1','Custom title','旧备稿','member',1,0,0);
            INSERT INTO meeting_roles VALUES(1,'REMOVED','Removed','已删除','open',0,1,1);
            INSERT INTO bookings VALUES(1,1,'PS1','Old','Old Path','L1P2','Old Title');
            INSERT INTO participants VALUES(1,1,'Old');
            """)
            before={table:c.execute('SELECT * FROM '+table).fetchall() for table in ['meetings','meeting_roles','participants','bookings']}
        app.DB=legacy_db
        app.init_db(); app.init_db()
        with app.conn() as c:
            for table in ['meetings','participants']:
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM '+table)],before[table])
            roles=[tuple(r) for r in c.execute('SELECT * FROM meeting_roles')]
            self.assertEqual([r[:6]+r[7:] for r in roles],[r[:6]+r[7:] for r in before['meeting_roles']])
            row=c.execute('SELECT * FROM bookings').fetchone()
            self.assertEqual(tuple(row)[:7],before['bookings'][0])
            self.assertEqual(row['project_no'],'L1P2')
            self.assertEqual(row['project_intro'],'')
        self.assertIn('Old Title',self.client.get('/').get_data(as_text=True))


if __name__ == '__main__': unittest.main()
