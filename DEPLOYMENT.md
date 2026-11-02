# 正式版更新与一次性清理

在 PythonAnywhere Bash console 中进入已有项目目录，激活 Web 页面配置的 virtualenv。更新期间暂停管理员创建、编辑会议及报名操作。

## Reload 前

先备份现有数据库（不替换原文件）：

```bash
python - <<'PY'
import sqlite3
from pathlib import Path
from datetime import datetime
assert Path('stepup.db').is_file(), '请进入包含线上 stepup.db 的项目目录'
backup = 'stepup-before-update-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'
with sqlite3.connect('stepup.db') as source, sqlite3.connect(backup) as target:
    source.backup(target)
print('备份：', backup)
PY

git switch main
git pull --ff-only origin main
python -m pip install -r requirements.txt
```

单独执行可重复的迁移（只补结构和修正当前会议角色 position；不删除会议或报名，不覆盖角色名称）：

```bash
python -c "from app import init_db; init_db(); print('Migration OK')"
python -m unittest discover -s tests -v
```

清理实验会议先预览，核对将删除的会议：

```bash
python scripts/cleanup_experiment_meetings.py --db stepup.db
```

确认列表后，执行一次性清理：

```bash
python scripts/cleanup_experiment_meetings.py --db stepup.db --confirm
```

该脚本与 init_db/启动流程完全独立。只有带 --confirm 才会修改数据；会先自动生成带时间戳的 SQLite 备份，再在同一事务中删除 meeting_no > 360 的 meeting_roles、bookings、participants 和 meetings。要求 359、360 各存在且只有一条，否则停止；保留所有 <=360 的会议、角色与报名，仅更新当前标识为 360。打印删除计划、备份路径和最终会议列表。重复执行不会删除 <=360 的数据。备份失败时不执行删除。

清理后再运行一次迁移，为刚设为当前的 360 安全修正角色顺序：

```bash
python -c "from app import init_db; init_db(); print('Migration OK')"
```

然后在 PythonAnywhere 的 **Web 页面点击 Reload**。保持原有 WSGI 导入方式 `from app import app as application`，不要在线上运行 Flask 开发服务器。

## Reload 后

- 检查首页为第 360 次会议，Admin 列表保留 359、360（若有更早会议也保留）。
- 检查默认会员角色顺序为 MM、TOM、GE、TTM、TTE、PS1、IE1、PS2、IE2、PS3、IE3、PS4、IE4、WORKSHOP。已有会议只修正已有角色位置，不强行补角色或覆盖管理员名称。
- 检查 PS 和 WORKSHOP 的修改页面能回填，首页只显示姓名和已填写题目；取消仍进入确认页。测试报名只在临时数据库中执行，不要为了验证重新创建线上实验会议。
- 如发现问题，查看 PythonAnywhere error log；保留更新前及清理前备份，不要删除或覆盖线上数据库。
