package app

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	_ "github.com/mattn/go-sqlite3"
)

func TestConfiguredDatabaseFeedCreation(t *testing.T) {
	path := os.Getenv("RSSX_TEST_DB_COPY")
	url := os.Getenv("RSSX_TEST_FEED_URL")
	if path == "" || url == "" {
		t.Skip("RSSX_TEST_DB_COPY and RSSX_TEST_FEED_URL are not set")
	}
	cleanPath := filepath.Clean(path)
	tempPrefix := filepath.Clean(os.TempDir()) + string(os.PathSeparator)
	if !strings.HasPrefix(cleanPath, tempPrefix) && !strings.HasPrefix(cleanPath, "/tmp/rssx-debug-") {
		t.Fatalf("refusing to modify a database outside a temporary path")
	}
	store, err := openStore(cleanPath)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()
	cfg := Config{MinIntervalMin: 10, MaxIntervalMin: 1440, InitialIntervalMin: 30}
	_, count, err := store.createFeed(context.Background(), url, nil, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if count == 0 {
		t.Fatal("initial fetch stored no entries")
	}
}

func TestAddFolderWithTextPrimaryKey(t *testing.T) {
	store, err := openStore(filepath.Join(t.TempDir(), "rssx.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()

	id, err := store.addFolder("news")
	if err != nil {
		t.Fatal(err)
	}
	if id == "" {
		t.Fatal("empty folder ID")
	}
	assertFolder(t, store.db, id, "text", "news")
}

func TestAddFolderWithLegacyIntegerPrimaryKey(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rssx.db")
	db, err := sql.Open("sqlite3", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec(`CREATE TABLE folders (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		name TEXT NOT NULL,
		parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
		position INTEGER NOT NULL DEFAULT 0,
		created_at TEXT NOT NULL DEFAULT (datetime('now'))
	);
	CREATE TABLE feeds (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		url TEXT NOT NULL UNIQUE,
		title TEXT NOT NULL,
		site_url TEXT,
		folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
		etag TEXT,
		last_modified TEXT,
		last_fetched_at TEXT,
		next_fetch_at TEXT,
		fetch_interval_sec INTEGER NOT NULL DEFAULT 1800,
		consecutive_empty INTEGER NOT NULL DEFAULT 0,
		last_error TEXT,
		created_at TEXT NOT NULL DEFAULT (datetime('now'))
	)`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := openStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()

	id, err := store.addFolder("legacy")
	if err != nil {
		t.Fatal(err)
	}
	assertFolder(t, store.db, id, "integer", "legacy")

	feedID, err := store.addFeed("https://example.com/feed", "Example", "https://example.com", &id)
	if err != nil {
		t.Fatal(err)
	}
	var idType, folderIDType string
	if err := store.db.QueryRow("SELECT typeof(id), typeof(folder_id) FROM feeds WHERE CAST(id AS TEXT) = :feed_id", sql.Named("feed_id", feedID)).Scan(&idType, &folderIDType); err != nil {
		t.Fatal(err)
	}
	if idType != "integer" || folderIDType != "integer" {
		t.Fatalf("legacy feed types = (%q, %q), want integer IDs", idType, folderIDType)
	}
}

func assertFolder(t *testing.T, db *sql.DB, id, wantType, wantName string) {
	t.Helper()
	var gotType, gotName string
	if err := db.QueryRow("SELECT typeof(id), name FROM folders WHERE CAST(id AS TEXT) = :folder_id", sql.Named("folder_id", id)).Scan(&gotType, &gotName); err != nil {
		t.Fatal(err)
	}
	if gotType != wantType || gotName != wantName {
		t.Fatalf("folder = (%q, %q), want (%q, %q)", gotType, gotName, wantType, wantName)
	}
}
