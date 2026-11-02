import contextlib
import io
import sqlite3
import subprocess
import sys
from pathlib import Path
import unittest
import test_v04
from scripts.cleanup_experiment_meetings import cleanup


class FormalTests(unittest.TestCase):
    setUp = test_v04.BookingTests.setUp
    tearDown = test_v04.BookingTests.tearDown
    booking = test_v04.BookingTests.booking
    post = test_v04.BookingTests.post

    def test_positions_idempotent_and_names_untouched(self):
        with app_conn() as c:
            c.execute("UPDATE meeting_roles SET position=0,name_en='Custom Name' WHERE code='PS3'")
            original=[tuple(r) for r in c.execute('SELECT * FROM bookings')]
        import app
        app.init_db(); app.init_db()
        with app.conn() as c:
            codes=[r['code'] for r in c.execute('SELECT * FROM meeting_roles WHERE meeting_id=1 ORDER BY position,code')]
            self.assertEqual(codes,[r[0] for r in app.ROLES])
            self.assertEqual(c.execute("SELECT name_en FROM meeting_roles WHERE code='PS3'").fetchone()[0],'Custom Name')
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM bookings')],original)

    def test_edit_all_speakers_and_workshop(self):
        for code in ['PS1','PS2','PS3','PS4','WORKSHOP']:
            fields=(dict(workshop_title='Old Workshop',workshop_content='Content\nLine 2',duration='45 mins',introduction='Bio') if code=='WORKSHOP' else
                    dict(project_no='L2P2',project_intro='Intro\nLine 2',speech_title='Old Title',speech_time='8 mins',ppt='N'))
            self.assertEqual(self.post(code,**fields).status_code,302)
            old=self.booking(code)
            html=self.client.get('/book/'+code+'/edit').get_data(as_text=True)
            for value in fields.values(): self.assertIn(value,html)
            self.assertIn('value="陈孝延"',html)
            if code!='WORKSHOP':
                self.assertIn('value="N" selected',html)
            fields.update(workshop_title='New Workshop') if code=='WORKSHOP' else fields.update(speech_title='New Title')
            self.assertEqual(self.client.post('/book/'+code+'/edit',data=dict(meeting_id=1,booking_id=old['id'],name='New Speaker',**fields)).status_code,302)
            row=self.booking(code)
            self.assertEqual(row['id'],old['id'])
            self.assertEqual(row['name'],'New Speaker')
            for key,value in fields.items(): self.assertEqual(row[key],value)
            with app_conn() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM bookings WHERE meeting_id=1 AND role_code=?',(code,)).fetchone()[0],1)
            html=self.client.get('/').get_data(as_text=True)
            self.assertIn('New Speaker',html)
            self.assertIn('New Workshop' if code=='WORKSHOP' else 'New Title',html)
            self.assertNotIn('8 mins',html)
            self.assertNotIn('45 mins',html)
            self.assertNotIn('L2P2',html)
            self.assertNotIn('PPT:',html)
            self.assertNotIn('Intro\nLine 2',html)
            # Clearing fields must preserve blanks, including Time in the edit form.
            self.client.post('/book/'+code+'/edit',data=dict(meeting_id=1,booking_id=old['id'],name='Name Only'))
            html=self.client.get('/book/'+code+'/edit').get_data(as_text=True)
            if code!='WORKSHOP': self.assertIn('name="speech_time" value=""',html)
            self.assertNotIn('New Title',self.client.get('/').get_data(as_text=True))
        self.assertEqual(self.client.post('/book/PS1/edit',data=dict(meeting_id=1,booking_id=999,name='Bad')).status_code,409)

    def test_cleanup_backup_preview_repeat_and_preservation(self):
        import app
        for _ in range(6):
            self.post('PS1',speech_title='Retained title')
            with app.conn() as c:
                mid=app.current_meeting(c)['id']
                c.execute('INSERT OR IGNORE INTO bookings(meeting_id,role_code,name) VALUES(?,?,?)',(mid,'IE1','Saved'))
                c.execute('INSERT OR IGNORE INTO participants(meeting_id,name) VALUES(?,?)',(mid,'Saved'))
            self.client.post('/admin/new',data=dict(meeting_date='2026-11-07',start_time='19:00',end_time='21:00',address='',status='active'))
        with app.conn() as c:
            originals={table:[tuple(r) for r in c.execute(f'SELECT * FROM {table} WHERE meeting_id IN (1,2) ORDER BY rowid')] for table in ['bookings','participants','meeting_roles']}
        original_bytes=app.DB.read_bytes()
        script=Path(__file__).resolve().parents[1]/'scripts/cleanup_experiment_meetings.py'
        result=subprocess.run([sys.executable,str(script),'--db',str(app.DB)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--confirm',result.stdout)
        self.assertEqual(app.DB.read_bytes(),original_bytes)
        for _ in range(2):
            result=subprocess.run([sys.executable,str(script),'--db',str(app.DB),'--confirm'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('备份文件',result.stdout)
            self.assertIn('删除完成后的会议列表',result.stdout)
            with app.conn() as c:
                self.assertEqual([tuple(r) for r in c.execute('SELECT meeting_no,is_current FROM meetings ORDER BY meeting_no')],[(359,0),(360,1)])
                for table in originals:
                    self.assertEqual([tuple(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY rowid')],originals[table])
        backups=list(app.DB.parent.glob('*before-cleanup*.db'))
        self.assertEqual(len(backups),2)
        # One backup contains the complete database before any deletion.
        counts=[]
        for backup in backups:
            with sqlite3.connect(backup) as c: counts.append(c.execute('SELECT COUNT(*) FROM meetings').fetchone()[0])
        self.assertIn(7,counts)
        with contextlib.redirect_stdout(io.StringIO()):
            self.client.post('/admin/meetings/1/current')
        with app.conn() as c: self.assertEqual(app.current_meeting(c)['meeting_no'],359)

    def test_cleanup_refuses_missing_360(self):
        import app
        before=app.DB.read_bytes()
        with self.assertRaises(ValueError): cleanup(app.DB,True)
        self.assertEqual(app.DB.read_bytes(),before)


def app_conn():
    import app
    return app.conn()
