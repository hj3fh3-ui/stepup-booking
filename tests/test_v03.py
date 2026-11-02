import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
import app


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'legacy.db'
        # V0.1 fixture lacks address, status and role configuration.
        with sqlite3.connect(app.DB) as c:
            c.executescript("""
            CREATE TABLE meetings(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_no INTEGER NOT NULL,meeting_date TEXT NOT NULL,start_time TEXT NOT NULL DEFAULT '19:00',end_time TEXT NOT NULL DEFAULT '21:00',theme TEXT NOT NULL DEFAULT '',is_current INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE bookings(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id INTEGER NOT NULL,role_code TEXT NOT NULL,name TEXT NOT NULL,path TEXT DEFAULT '',project TEXT DEFAULT '',speech_title TEXT DEFAULT '',UNIQUE(meeting_id,role_code));
            CREATE TABLE participants(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id INTEGER NOT NULL,name TEXT NOT NULL,UNIQUE(meeting_id,name));
            INSERT INTO meetings VALUES(1,359,'2026-10-31','19:00','21:00','Legacy',1);
            INSERT INTO bookings VALUES(1,1,'PS1','Original','Path','L1','Original Speech');
            INSERT INTO participants VALUES(1,1,'Original');
            """)
        app.app.config.update(TESTING=True)
        app.app.config.pop('_MIGRATED_DB', None)
        self.client = app.app.test_client()
        self.assertEqual(self.client.get('/').status_code,200)

    def tearDown(self):
        app.DB = self.old_db
        app.app.config.pop('_MIGRATED_DB', None)
        self.temp.cleanup()

    def rows(self, sql, args=()):
        with app.conn() as c:
            return [tuple(r) for r in c.execute(sql,args)]

    def role(self, code, action='add', **kw):
        data=dict(code=code,action=action,name_en=code,name_zh='测试角色',audience='member',speech='0')
        data.update(kw)
        return self.client.post('/admin/meetings/1/roles',data=data)

    def token(self, path):
        r=self.client.get(path)
        self.assertEqual(r.status_code,200)
        return re.search(r'name="token" value="([^"]+)"',r.get_data(as_text=True))[1]

    def test_migration_and_switch_359_363_359(self):
        app.init_db(); app.init_db()
        original=self.rows('SELECT * FROM bookings')
        for no in range(360,364):
            r=self.client.post('/admin/new',data=dict(theme=str(no),meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='Room',status='active'))
            self.assertEqual(r.status_code,302)
        self.assertEqual(self.rows('SELECT meeting_no FROM meetings WHERE is_current=1'),[(363,)])
        self.assertEqual(self.client.post('/admin/meetings/1/current').status_code,302)
        self.assertEqual(self.rows('SELECT meeting_no FROM meetings WHERE is_current=1'),[(359,)])
        self.assertEqual(self.rows('SELECT * FROM bookings'),original)
        self.assertEqual(self.rows('SELECT name FROM participants'),[('Original',)])
        self.assertEqual(len(self.rows('SELECT * FROM meetings')),5)
        self.assertIn('当前会议 / Current',self.client.get('/admin').get_data(as_text=True))
        self.client.post('/admin/new',data=dict(theme='364',meeting_date='2026-11-14',start_time='19:00',end_time='21:00',address='',status='active'))
        self.assertEqual(self.rows('SELECT meeting_no FROM meetings WHERE is_current=1'),[(364,)])
        with app.conn() as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('UPDATE meetings SET is_current=1 WHERE id=1')

    def test_roles_speech_workshop_and_independence(self):
        for code in ['PS3','PS4','IE3','IE4']:
            self.assertEqual(self.role(code, 'save').status_code,302)
        self.assertEqual(self.role('WORKSHOP','save',name_en='Workshop',name_zh='工作坊',audience='open').status_code,302)
        self.assertEqual(self.client.get('/book/PS3').status_code,200)
        self.assertEqual(self.client.post('/book/PS3',data=dict(meeting_id=1,name='')).status_code,400)
        self.assertEqual(self.client.post('/book/PS3',data=dict(meeting_id=1,name='Speaker',path='Path',project='L2P2',speech_title='PS3 talk')).status_code,302)
        self.assertEqual(self.client.post('/book/WORKSHOP',data=dict(meeting_id=1,name='Host')).status_code,302)
        self.assertIn('PS3 talk',self.client.get('/').get_data(as_text=True))
        self.assertEqual(self.role('WORKSHOP','save',name_en='New Workshop',name_zh='新工作坊').status_code,302)
        self.client.post('/admin/new',data=dict(theme='',meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='',status='active'))
        self.assertEqual(self.rows("SELECT name_en FROM meeting_roles WHERE meeting_id=2 AND code='WORKSHOP'"),[('New Workshop',)])
        self.assertEqual(self.role('WORKSHOP','delete').status_code,302)
        app.init_db()
        self.assertEqual(self.rows("SELECT deleted FROM meeting_roles WHERE meeting_id=1 AND code='WORKSHOP'"),[(1,)])
        self.assertEqual(self.rows("SELECT deleted FROM meeting_roles WHERE meeting_id=2 AND code='WORKSHOP'"),[(0,)])
        self.assertEqual(len(self.rows('SELECT * FROM bookings WHERE meeting_id=1')),3)
        self.client.post('/admin/meetings/1/current')
        self.assertEqual(self.client.get('/book/WORKSHOP').status_code,404)
        self.assertIn('Host',self.client.get('/').get_data(as_text=True))

    def test_cancellation_requires_confirmation(self):
        token=self.token('/cancel-role/PS1')
        self.assertEqual(len(self.rows('SELECT * FROM bookings')),1)
        self.assertEqual(self.client.post('/cancel-role/PS1').status_code,400)
        self.assertEqual(self.client.post('/cancel-role/PS1',data={'token':token}).status_code,302)
        self.assertEqual(self.rows('SELECT * FROM bookings'),[])
        self.client.post('/book/PS1',data=dict(meeting_id=1,name='Original',path='Path',project='L1',speech_title='Talk'))
        token=self.token('/cancel-participant/1')
        self.assertEqual(len(self.rows('SELECT * FROM participants')),1)
        self.assertEqual(self.client.post('/cancel-participant/1').status_code,400)
        self.assertEqual(self.client.post('/cancel-participant/1',data={'token':token}).status_code,302)
        self.assertEqual(self.rows('SELECT * FROM bookings'),[])
        self.assertEqual(self.rows('SELECT * FROM participants'),[])

    def test_stale_forms_and_recess(self):
        token=self.token('/cancel-role/PS1')
        self.client.post('/admin/new',data=dict(theme='',meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='',status='active'))
        self.assertEqual(self.client.post('/join',data=dict(meeting_id=1,name='Stale')).status_code,409)
        self.assertEqual(self.client.post('/cancel-role/PS1',data=dict(token=token)).status_code,404)
        self.assertEqual(len(self.rows('SELECT * FROM bookings')),1)
        with app.conn() as c:
            c.execute("UPDATE meetings SET status='recess' WHERE is_current=1")
        self.assertEqual(self.client.post('/join',data=dict(meeting_id=2,name='Guest')).status_code,409)


if __name__ == '__main__':
    unittest.main()
