# LightBook Studio

LightBook Studio 是一个本地漫画/轻小说整理工具，将用户本地的漫画或轻小说文件，转换为 [Komga](https://komga.org/) 友好的格式（CBZ/EPUB），并写入标准化元数据。

本项目不做爬虫，也不下载内容，只处理用户本地已有文件。

## 功能

### 导入

- **图片文件夹** — 支持 `jpg`、`jpeg`、`png`、`webp`，自然排序，首张作为封面
- **漫画 EPUB** — 解析 `META-INF/container.xml` → OPF manifest/spine/metadata，按 spine 顺序提取图片；解析失败时回退到全部图片自然排序
- **CBZ** — 读取 ZIP 内图片，解析已有 `ComicInfo.xml`；无元数据时从文件名猜测
- **轻小说 TXT** — 自动检测编码（UTF-8/GB18030/GBK/UTF-16），清洗广告行，解析卷/章结构

### 编辑

- 编辑作品名、本卷标题、卷号、作者、译者/汉化组、简介、分类、标签、语言、阅读方向
- 轻小说支持编辑章节标题、预览 EPUB
- 批量管理：状态标记（待审核/就绪/已导出/失败）、删除、重解析

### 导出

- **漫画 → CBZ** — 内含 `ComicInfo.xml`、自然排序的图片（`0001.ext`），同时输出 `poster.jpg`
- **轻小说 → EPUB** — 含章节结构、CSS 样式、元数据
- CBZ 元数据原地重写（保留图片，仅更新 `ComicInfo.xml` 和封面）

### 库管理

- SQLite 持久化：作品、册、章节、导出任务全记录
- 批量导入/导出、右键菜单、快捷键（`Ctrl+A` 全选）
- 输出路径防覆盖（自动追加 `(1)`、`(2)` 后缀）

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

如果 PowerShell 激活脚本被禁用，不需要 Activate.ps1，直接使用 `.\.venv\Scripts\python.exe` 运行即可。

如果使用 editable install：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[dev,all]
```

### 可选依赖组

| 组 | 包 | 说明 |
|----|-----|------|
| `epub` | ebooklib | 轻小说 EPUB 导出 |
| `web` | beautifulsoup4, lxml | Web 元数据搜索 |
| `cjk` | opencc-python-reimplemented | 简繁转换 |
| `all` | 以上全部 | 完整功能 |
| `dev` | pytest, pytest-qt, pytest-cov | 开发与测试 |

## 运行

```powershell
.\.venv\Scripts\python.exe -m app.main
```

或安装后直接运行：

```powershell
lightbook-studio
```

## 统一工作流

v0.4.2 起主界面使用统一的“书库整理”页面：导入文件或文件夹后，条目会进入左侧列表；选中条目后，在右侧完成元数据编辑、章节编辑、AI 建议、封面搜索和导出。单本导入不再维护单独编辑页，导入一个文件和导入多个文件走同一套列表与详情逻辑。

推荐流程：

1. 点击“导入文件”“导入文件夹”或“扫描目录”。
2. 在列表中选中一本或多本书，批量标记状态、删除或导出。
3. 选中单本后在右侧编辑元数据、章节标题、自定义封面。
4. 需要时生成 AI 建议或搜索封面，结果会按 `book_id` 缓存，切换书籍和重启后仍可查看。
5. 标记为 ready 后导出 CBZ/EPUB。

## 日志

日志文件位于 `logs/lightbook.log`，使用日志轮转（单文件最大 5 MB，保留 10 个备份）。

日志记录以下事件：
- 程序启动
- 导入/导出操作
- AI API 请求与响应
- 封面搜索
- 数据库迁移
- 未捕获异常

GUI 中可在 **设置 → 帮助与日志** 区域打开日志文件、日志目录和数据目录。

API key 等敏感信息会被自动脱敏（保留前 6 位 + `***` + 后 4 位），不会完整写入日志。

## 输出路径

漫画：

```text
{output_root}/Manga/{series_title}/{series_title} v{volume:02d}.cbz
```

轻小说：

```text
{output_root}/Novel/{series_title}/{series_title} v{volume:02d}.epub
```

目标文件已存在时自动追加后缀，不会覆盖。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

如果遇到 `PytestCacheWarning`，清理缓存目录后重试：

```powershell
Remove-Item -Recurse -Force .pytest_cache
```

## 技术栈

| 层面 | 技术 |
|------|------|
| 语言 | Python >= 3.11 |
| GUI | PySide6 >= 6.6 |
| 数据库 | SQLite3 |
| 图像处理 | Pillow >= 10.0 |
| EPUB 解析 | beautifulsoup4 + ebooklib |
| 测试 | pytest >= 8.0 |
