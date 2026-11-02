"""Explicit, backed-up cleanup of experimental meetings. Never run at startup."""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3


def cleanup(database, confirm=False):
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError(f'数据库不存在：{database}')
    # mode=rw prevents accidentally creating a new database.
    c = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, isolation_level=None)
    try:
        c.execute('BEGIN IMMEDIATE')
        retained = c.execute('SELECT id,meeting_no FROM meetings WHERE meeting_no IN (359,360)').fetchall()
        if sorted(no for _, no in retained) != [359,360]:
            raise ValueError('必须存在且仅存在一条第359次及第360次会议，已停止，未删除任何数据。')
        targets = c.execute('SELECT id,meeting_no FROM meetings WHERE meeting_no>360 ORDER BY meeting_no,id').fetchall()
        print('即将删除会议 (id, meeting_no)：', targets)
        if not confirm:
            print('预览模式，未修改数据库。真正执行需要 --confirm。')
            c.rollback()
            return
        backup = database.with_name(database.stem + '-before-cleanup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
        # Separate read connection backs up the pre-delete snapshot while this
        # connection holds the write reservation, preventing concurrent writes.
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
        print('备份文件：', backup)
        for table in ('meeting_roles','bookings','participants'):
            c.execute(f'DELETE FROM {table} WHERE meeting_id IN (SELECT id FROM meetings WHERE meeting_no>360)')
        c.execute('DELETE FROM meetings WHERE meeting_no>360')
        c.execute('UPDATE meetings SET is_current=0 WHERE is_current<>0')
        c.execute('UPDATE meetings SET is_current=1 WHERE meeting_no=360')
        c.commit()
        print('删除完成后的会议列表 (id, meeting_no, is_current)：',
              c.execute('SELECT id,meeting_no,is_current FROM meetings ORDER BY meeting_no,id').fetchall())
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parents[1]/'stepup.db')
    parser.add_argument('--confirm', action='store_true', help='自动备份后删除 meeting_no > 360 的会议')
    args = parser.parse_args()
    try:
        cleanup(args.db, args.confirm)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f'清理失败：{error}\n')


if __name__ == '__main__':
    main()
