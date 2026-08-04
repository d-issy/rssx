package app

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

const schema = `
CREATE TABLE IF NOT EXISTS folders (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
 position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);
CREATE TABLE IF NOT EXISTS feeds (
 id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, site_url TEXT,
 folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL, etag TEXT, last_modified TEXT,
 last_fetched_at TEXT, next_fetch_at TEXT, fetch_interval_sec INTEGER NOT NULL DEFAULT 1800,
 consecutive_empty INTEGER NOT NULL DEFAULT 0, last_error TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feeds_folder ON feeds(folder_id);
CREATE INDEX IF NOT EXISTS idx_feeds_next_fetch ON feeds(next_fetch_at);
CREATE TABLE IF NOT EXISTS entries (
 id TEXT PRIMARY KEY, feed_id TEXT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
 guid TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', url TEXT, author TEXT,
 content TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', published_at TEXT,
 fetched_at TEXT NOT NULL DEFAULT (datetime('now')), is_read INTEGER NOT NULL DEFAULT 0,
 is_starred INTEGER NOT NULL DEFAULT 0, read_at TEXT, starred_at TEXT, UNIQUE(feed_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_entries_feed_published ON entries(feed_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_entries_is_read ON entries(is_read);
CREATE INDEX IF NOT EXISTS idx_entries_is_starred ON entries(is_starred);
CREATE INDEX IF NOT EXISTS idx_entries_published ON entries(published_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
 entry_id UNINDEXED, title, content, summary, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
 INSERT INTO entries_fts(entry_id,title,content,summary) VALUES(new.id,new.title,new.content,new.summary);
END;
CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
 DELETE FROM entries_fts WHERE entry_id=old.id;
END;
CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
 DELETE FROM entries_fts WHERE entry_id=old.id;
 INSERT INTO entries_fts(entry_id,title,content,summary) VALUES(new.id,new.title,new.content,new.summary);
END;`

type Folder struct {
	ID, Name  string
	ParentID  sql.NullString
	Position  int
	FeedCount int
}

type Feed struct {
	ID, URL, Title                              string
	SiteURL, FolderID, LastFetchedAt, LastError sql.NullString
	Unread                                      int
}

type Entry struct {
	ID, FeedID, Title, FeedTitle string
	URL, Author, PublishedAt     sql.NullString
	Summary                      string
	Read, Starred                bool
}

type EntryDetail struct {
	Entry
	Content string
}

type Store struct {
	db        *sql.DB
	integerPK map[string]bool
}

func openStore(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite3", path+"?_foreign_keys=on&_journal_mode=WAL&_synchronous=NORMAL&_busy_timeout=5000")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if _, err = db.Exec(schema); err != nil {
		_ = db.Close()
		return nil, err
	}
	store := &Store{db: db, integerPK: make(map[string]bool)}
	for _, table := range []string{"folders", "feeds", "entries"} {
		integer, detectErr := hasIntegerPrimaryKey(db, table)
		if detectErr != nil {
			_ = db.Close()
			return nil, detectErr
		}
		store.integerPK[table] = integer
	}
	return store, nil
}

func hasIntegerPrimaryKey(db *sql.DB, table string) (bool, error) {
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return false, err
	}
	defer func() { _ = rows.Close() }()
	for rows.Next() {
		var cid, notNull, primaryKey int
		var name, declaredType string
		var defaultValue sql.NullString
		if err := rows.Scan(&cid, &name, &declaredType, &notNull, &defaultValue, &primaryKey); err != nil {
			return false, err
		}
		if name == "id" && primaryKey > 0 {
			return strings.EqualFold(declaredType, "INTEGER"), nil
		}
	}
	return false, rows.Err()
}

func (s *Store) close() error { return s.db.Close() }

func (s *Store) folders() ([]Folder, error) {
	rows, err := s.db.Query(`SELECT fo.id,fo.name,fo.parent_id,fo.position,
 COALESCE((SELECT count(*) FROM feeds WHERE folder_id=fo.id),0)
 FROM folders fo ORDER BY fo.parent_id,fo.position,lower(fo.name)`)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var out []Folder
	for rows.Next() {
		var v Folder
		if err := rows.Scan(&v.ID, &v.Name, &v.ParentID, &v.Position, &v.FeedCount); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) feeds(query string, folders map[string]bool) ([]Feed, error) {
	where, args := []string{}, []any{}
	if strings.TrimSpace(query) != "" {
		where = append(where, "(lower(f.title) LIKE lower(:query) OR lower(f.url) LIKE lower(:query) OR lower(COALESCE(f.site_url,'')) LIKE lower(:query))")
		q := "%" + strings.TrimSpace(query) + "%"
		args = append(args, sql.Named("query", q))
	}
	if folders != nil {
		clauses := []string{}
		folderIndex := 0
		for id, yes := range folders {
			if yes && id != "__orphan" {
				name := fmt.Sprintf("folder_id_%d", folderIndex)
				clauses = append(clauses, "f.folder_id=:"+name)
				args = append(args, sql.Named(name, id))
				folderIndex++
			}
		}
		if folders["__orphan"] {
			clauses = append(clauses, "f.folder_id IS NULL")
		}
		if len(clauses) == 0 {
			where = append(where, "1=0")
		} else {
			where = append(where, "("+strings.Join(clauses, " OR ")+")")
		}
	}
	w := ""
	if len(where) > 0 {
		w = " WHERE " + strings.Join(where, " AND ")
	}
	rows, err := s.db.Query(`SELECT f.id,f.url,f.title,f.site_url,f.folder_id,f.last_fetched_at,f.last_error,
 COALESCE((SELECT count(*) FROM entries e WHERE e.feed_id=f.id AND e.is_read=0),0)
 FROM feeds f`+w+` ORDER BY lower(f.title)`, args...)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var out []Feed
	for rows.Next() {
		var v Feed
		if err := rows.Scan(&v.ID, &v.URL, &v.Title, &v.SiteURL, &v.FolderID, &v.LastFetchedAt, &v.LastError, &v.Unread); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func (s *Store) descendantIDs(id string) ([]string, error) {
	out, queue := []string{id}, []string{id}
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		rows, err := s.db.Query("SELECT id FROM folders WHERE parent_id=:parent_id", sql.Named("parent_id", cur))
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var child string
			if err := rows.Scan(&child); err != nil {
				_ = rows.Close()
				return nil, err
			}
			out = append(out, child)
			queue = append(queue, child)
		}
		_ = rows.Close()
	}
	return out, nil
}

func (s *Store) entries(scope, id string, unread bool, limit, offset int) ([]Entry, bool, error) {
	where, args := []string{}, []any{}
	switch scope {
	case "starred":
		where = append(where, "e.is_starred=1")
	case "feed":
		where = append(where, "e.feed_id=:feed_id")
		args = append(args, sql.Named("feed_id", id))
	case "folder":
		ids, err := s.descendantIDs(id)
		if err != nil {
			return nil, false, err
		}
		marks := make([]string, len(ids))
		for i, v := range ids {
			name := fmt.Sprintf("folder_id_%d", i)
			marks[i] = ":" + name
			args = append(args, sql.Named(name, v))
		}
		where = append(where, "f.folder_id IN ("+strings.Join(marks, ",")+")")
	}
	if unread && scope != "starred" {
		where = append(where, "e.is_read=0")
	}
	w := ""
	if len(where) > 0 {
		w = " WHERE " + strings.Join(where, " AND ")
	}
	limit = max(1, limit)
	args = append(args, sql.Named("limit", limit+1), sql.Named("offset", max(0, offset)))
	rows, err := s.db.Query(`SELECT e.id,e.feed_id,e.title,e.url,e.author,e.summary,e.published_at,e.is_read,e.is_starred,f.title
 FROM entries e JOIN feeds f ON f.id=e.feed_id`+w+` ORDER BY COALESCE(e.published_at,e.fetched_at) DESC,e.id DESC LIMIT :limit OFFSET :offset`, args...)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = rows.Close() }()
	var out []Entry
	for rows.Next() {
		var v Entry
		var read, star int
		if err := rows.Scan(&v.ID, &v.FeedID, &v.Title, &v.URL, &v.Author, &v.Summary, &v.PublishedAt, &read, &star, &v.FeedTitle); err != nil {
			return nil, false, err
		}
		v.Read = read != 0
		v.Starred = star != 0
		out = append(out, v)
	}
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	more := len(out) > limit
	if more {
		out = out[:limit]
	}
	return out, more, nil
}

func (s *Store) search(q string, limit, offset int) ([]Entry, bool, error) {
	q = strings.TrimSpace(q)
	if q == "" {
		return nil, false, nil
	}
	like := "%" + q + "%"
	limit = max(1, limit)
	rows, err := s.db.Query(`SELECT e.id,e.feed_id,e.title,e.url,e.author,e.summary,e.published_at,e.is_read,e.is_starred,f.title
 FROM entries e JOIN feeds f ON f.id=e.feed_id WHERE e.title LIKE :query OR e.summary LIKE :query OR e.content LIKE :query
 ORDER BY COALESCE(e.published_at,e.fetched_at) DESC,e.id DESC LIMIT :limit OFFSET :offset`,
		sql.Named("query", like), sql.Named("limit", limit+1), sql.Named("offset", max(0, offset)))
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = rows.Close() }()
	var out []Entry
	for rows.Next() {
		var v Entry
		var read, star int
		if err := rows.Scan(&v.ID, &v.FeedID, &v.Title, &v.URL, &v.Author, &v.Summary, &v.PublishedAt, &read, &star, &v.FeedTitle); err != nil {
			return nil, false, err
		}
		v.Read = read != 0
		v.Starred = star != 0
		out = append(out, v)
	}
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	more := len(out) > limit
	if more {
		out = out[:limit]
	}
	return out, more, nil
}

func (s *Store) detail(id string) (EntryDetail, error) {
	var v EntryDetail
	var read, star int
	err := s.db.QueryRow(`SELECT e.id,e.feed_id,e.title,e.url,e.author,e.summary,e.published_at,e.is_read,e.is_starred,f.title,e.content
 FROM entries e JOIN feeds f ON f.id=e.feed_id WHERE e.id=:entry_id`, sql.Named("entry_id", id)).Scan(&v.ID, &v.FeedID, &v.Title, &v.URL, &v.Author, &v.Summary, &v.PublishedAt, &read, &star, &v.FeedTitle, &v.Content)
	v.Read = read != 0
	v.Starred = star != 0
	return v, err
}
func (s *Store) markRead(id string, value bool) error {
	_, err := s.db.Exec("UPDATE entries SET is_read=:is_read,read_at=CASE WHEN :is_read THEN datetime('now') ELSE NULL END WHERE id=:entry_id",
		sql.Named("is_read", value), sql.Named("entry_id", id))
	return err
}
func (s *Store) toggleStar(id string) (bool, error) {
	var old bool
	if err := s.db.QueryRow("SELECT is_starred FROM entries WHERE id=:entry_id", sql.Named("entry_id", id)).Scan(&old); err != nil {
		return false, err
	}
	next := !old
	_, err := s.db.Exec("UPDATE entries SET is_starred=:is_starred,starred_at=CASE WHEN :is_starred THEN datetime('now') ELSE NULL END WHERE id=:entry_id",
		sql.Named("is_starred", next), sql.Named("entry_id", id))
	return next, err
}
func (s *Store) totals() (int, int, error) {
	var unread, star int
	if err := s.db.QueryRow("SELECT count(*) FROM entries WHERE is_read=0").Scan(&unread); err != nil {
		return 0, 0, err
	}
	err := s.db.QueryRow("SELECT count(*) FROM entries WHERE is_starred=1").Scan(&star)
	return unread, star, err
}
func (s *Store) addFolder(name string) (string, error) {
	if s.integerPK["folders"] {
		result, err := s.db.Exec("INSERT INTO folders(name) VALUES(:name)", sql.Named("name", strings.TrimSpace(name)))
		if err != nil {
			return "", err
		}
		id, err := result.LastInsertId()
		return fmt.Sprint(id), err
	}
	id := newID()
	_, err := s.db.Exec("INSERT INTO folders(id,name) VALUES(:folder_id,:name)", sql.Named("folder_id", id), sql.Named("name", strings.TrimSpace(name)))
	return id, err
}
func (s *Store) renameFolder(id, name string) error {
	_, err := s.db.Exec("UPDATE folders SET name=:name WHERE id=:folder_id", sql.Named("name", strings.TrimSpace(name)), sql.Named("folder_id", id))
	return err
}
func (s *Store) deleteFolder(id string, cascade bool) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	if cascade {
		if _, err = tx.Exec("DELETE FROM feeds WHERE folder_id=:folder_id", sql.Named("folder_id", id)); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	if _, err = tx.Exec("DELETE FROM folders WHERE id=:folder_id", sql.Named("folder_id", id)); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}
func (s *Store) addFeed(url, title, site string, folder *string) (string, error) {
	var siteArg any
	if site != "" {
		siteArg = site
	}
	var folderArg any
	if folder != nil && *folder != "" {
		folderArg = *folder
	}
	if s.integerPK["feeds"] {
		result, err := s.db.Exec(`INSERT INTO feeds(url,title,site_url,folder_id,next_fetch_at)
 VALUES(:url,:title,:site_url,:folder_id,datetime('now'))`, sql.Named("url", strings.TrimSpace(url)), sql.Named("title", strings.TrimSpace(title)),
			sql.Named("site_url", siteArg), sql.Named("folder_id", folderArg))
		if err != nil {
			return "", err
		}
		id, err := result.LastInsertId()
		return fmt.Sprint(id), err
	}
	id := newID()
	_, err := s.db.Exec(`INSERT INTO feeds(id,url,title,site_url,folder_id,next_fetch_at)
 VALUES(:feed_id,:url,:title,:site_url,:folder_id,datetime('now'))`, sql.Named("feed_id", id), sql.Named("url", strings.TrimSpace(url)),
		sql.Named("title", strings.TrimSpace(title)), sql.Named("site_url", siteArg), sql.Named("folder_id", folderArg))
	return id, err
}
func (s *Store) updateFeedTitle(id, title string) error {
	_, err := s.db.Exec("UPDATE feeds SET title=:title WHERE id=:feed_id", sql.Named("title", strings.TrimSpace(title)), sql.Named("feed_id", id))
	return err
}
func (s *Store) updateFeedFolder(id string, folder *string) error {
	var v any
	if folder != nil && *folder != "" {
		v = *folder
	}
	_, err := s.db.Exec("UPDATE feeds SET folder_id=:folder_id WHERE id=:feed_id", sql.Named("folder_id", v), sql.Named("feed_id", id))
	return err
}
func (s *Store) deleteFeed(id string) error {
	_, err := s.db.Exec("DELETE FROM feeds WHERE id=:feed_id", sql.Named("feed_id", id))
	return err
}
func newID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return fmt.Sprintf("%x", time.Now().UnixNano())
	}
	return strings.ToUpper(hex.EncodeToString(b[:]))
}
