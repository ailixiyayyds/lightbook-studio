PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS works (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  original_title TEXT DEFAULT '',
  author TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  genres TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  language_iso TEXT DEFAULT 'zh',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id INTEGER NOT NULL,
  title TEXT DEFAULT '',
  volume_number INTEGER,
  media_type TEXT DEFAULT 'comic',
  source_type TEXT NOT NULL,
  source_path TEXT NOT NULL,
  page_count INTEGER DEFAULT 0,
  chapter_count INTEGER DEFAULT 0,
  text_length INTEGER DEFAULT 0,
  export_format TEXT DEFAULT '',
  cover_path TEXT DEFAULT '',
  cover_override_path TEXT DEFAULT '',
  translator TEXT DEFAULT '',
  manga_direction TEXT DEFAULT 'rtl',
  status TEXT NOT NULL DEFAULT 'need_review',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(work_id) REFERENCES works(id)
);

CREATE TABLE IF NOT EXISTS export_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL,
  output_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS novel_chapters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_work_id ON books(work_id);
CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
CREATE INDEX IF NOT EXISTS idx_novel_chapters_book_id ON novel_chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_export_jobs_book_id ON export_jobs(book_id);
CREATE INDEX IF NOT EXISTS idx_export_jobs_status ON export_jobs(status);
