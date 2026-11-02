后浪 Step Up 实时接龙 V0.2

升级内容：
1. 当前会议的主题、日期、时间、地点均可随时修改。
2. 修改会议信息不会清除已有报名。
3. 创建下一次会议时，期数自动 +1。
4. 日期默认取当前会议之后的下一个周六，但可手动修改。
5. 时间默认 19:00–21:00，但可手动修改。
6. 支持“正常 / 休会”状态；休会时首页暂停报名。
7. 创建下一期会保留历史会议数据。
8. 兼容 V0.1 的 stepup.db 数据库升级。

升级建议：
- 先关闭旧服务器（CMD 中 Ctrl+C）。
- 备份原 stepup.db。
- 用本版本 app.py 替换旧 app.py。
- 如果希望保留 V0.1 已测试的数据，把旧 stepup.db 放在新 app.py 同目录。
- 运行 python app.py。

V0.3
- 每期会议独立配置角色：管理 → 编辑角色。支持中英文名称、报名范围、备稿演讲和临时环节。
- PS 数字角色自动要求 Path、Project、Speech Title；其他角色也可选择“备稿演讲”。
- 删除角色不会删除已有报名；仍有报名的已删除角色保留在首页，允许取消，但不接受新报名。
- 历史会议可以设为当前，切换不删除数据；数据库唯一索引保证最多一个当前会议。
- 新一期从历史最大期数递增，复制历史最新一期的有效角色，不复制报名。
- 取消角色或参会先显示确认页，只有确认 POST 才删除数据。
- 首次网页请求（包括 PythonAnywhere WSGI）或运行 python app.py 时自动迁移旧数据库。
- 数据库默认仍为 app.py 同目录的 stepup.db；升级不清空或替换数据库。

测试（仅使用临时数据库）：
python -m unittest discover -s tests -v

PythonAnywhere 更新步骤：
1. 打开 Bash console，进入已有仓库目录，并激活 Web 页面配置的现有 virtualenv（若使用）。
2. 先用 SQLite backup API 备份数据库：
   python - <<'PY'
   import sqlite3
   from pathlib import Path
   from datetime import datetime
   db = Path('stepup.db')
   assert db.is_file(), '请先进入包含线上 stepup.db 的项目目录'
   backup = db.with_name('stepup-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
   with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
       source.backup(target)
   print('Backup:', backup)
   PY
3. 拉取更新、安装依赖、执行迁移及测试：
   git switch main
   git pull --ff-only origin main
   python -m pip install -r requirements.txt
   python -c "from app import init_db; init_db(); print('V0.3 migration OK')"
   python -m unittest discover -s tests -v
4. 在 PythonAnywhere 的 Web 页面点击 Reload。不要删除 stepup.db，不要上传测试数据库覆盖它。
   保持现有 WSGI 配置（from app import app as application）。不要在线上运行 Flask 开发服务器。
