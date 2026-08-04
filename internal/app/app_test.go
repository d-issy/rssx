package app

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

func TestHelpRowsAlignDescriptionsByVisibleWidth(t *testing.T) {
	for _, key := range []string{"Tab", "j/k, ↑/↓", "a/e/d/Enter"} {
		prefix := helpRow(key, "")
		if width := visibleWidth(prefix); width != 18 {
			t.Errorf("help row prefix %q has visible width %d, want 18", key, width)
		}
	}
}

func TestArticleLinesDisplayFullRSSContent(t *testing.T) {
	article := EntryDetail{
		Entry: Entry{
			Title:       "Article title",
			FeedTitle:   "Example Feed",
			URL:         sql.NullString{String: "https://example.com/article", Valid: true},
			PublishedAt: sql.NullString{String: "2026-08-05 12:00:00", Valid: true},
		},
		Content: "<p>This is the first paragraph.</p><p>This is the second paragraph.</p>",
	}

	got := strings.Join(articleLines(article, 80), "\n")
	for _, want := range []string{"Article title", "Example Feed", "This is the first paragraph.", "This is the second paragraph."} {
		if !strings.Contains(got, want) {
			t.Errorf("article text does not contain %q: %q", want, got)
		}
	}
	if strings.Contains(got, "<p>") || strings.Contains(got, article.URL.String) {
		t.Errorf("article text contains HTML or the browser URL: %q", got)
	}
}

func TestArticleLinesFallBackToSummary(t *testing.T) {
	article := EntryDetail{Entry: Entry{Title: "Summary only", Summary: "RSS summary"}}
	if got := strings.Join(articleLines(article, 80), "\n"); !strings.Contains(got, "RSS summary") {
		t.Fatalf("article text = %q, want summary", got)
	}
}

func TestEntryListAutoLoadsNextPageNearEnd(t *testing.T) {
	store, err := openStore(filepath.Join(t.TempDir(), "rssx.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()
	feedID, err := store.addFeed("https://example.com/feed", "Example", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < entryPageSize+5; i++ {
		id := fmt.Sprintf("entry-%03d", i)
		published := fmt.Sprintf("2026-08-05 12:00:%02d", i)
		if _, err := store.db.Exec(`INSERT INTO entries(id,feed_id,guid,title,published_at)
 VALUES(:entry_id,:feed_id,:guid,:title,:published_at)`, sql.Named("entry_id", id), sql.Named("feed_id", feedID),
			sql.Named("guid", id), sql.Named("title", id), sql.Named("published_at", published)); err != nil {
			t.Fatal(err)
		}
	}

	a := application{store: store, scope: "all", unreadOnly: false, entryIndex: -1}
	if err := a.reloadEntries(); err != nil {
		t.Fatal(err)
	}
	if len(a.entries) != entryPageSize || !a.entriesMore {
		t.Fatalf("initial load = (%d, more=%t), want (%d, true)", len(a.entries), a.entriesMore, entryPageSize)
	}

	a.selectEntry(entryPageSize-entryLoadThreshold, false)
	if len(a.entries) != entryPageSize+5 || a.entriesMore {
		t.Fatalf("autoload = (%d, more=%t), want (%d, false)", len(a.entries), a.entriesMore, entryPageSize+5)
	}
}

func TestMarkScopeReadMarksAllFeedsWhenAllIsSelected(t *testing.T) {
	store, err := openStore(filepath.Join(t.TempDir(), "rssx.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()

	for i := 0; i < 2; i++ {
		feedID, err := store.addFeed(fmt.Sprintf("https://example.com/feed-%d", i), fmt.Sprintf("Feed %d", i), "", nil)
		if err != nil {
			t.Fatal(err)
		}
		entryID := fmt.Sprintf("entry-%d", i)
		if _, err := store.db.Exec(`INSERT INTO entries(id,feed_id,guid,title) VALUES(:entry_id,:feed_id,:guid,:title)`,
			sql.Named("entry_id", entryID), sql.Named("feed_id", feedID), sql.Named("guid", entryID), sql.Named("title", entryID)); err != nil {
			t.Fatal(err)
		}
	}

	a := application{store: store, scope: "all", unreadOnly: true, entryIndex: -1}
	a.markScopeRead()

	var unread int
	if err := store.db.QueryRow(`SELECT count(*) FROM entries WHERE is_read=0`).Scan(&unread); err != nil {
		t.Fatal(err)
	}
	if unread != 0 {
		t.Fatalf("unread entries = %d, want 0", unread)
	}
	if a.statusErr || a.status != "Marked all as read" {
		t.Fatalf("status = (%q, error=%t), want successful mark-all status", a.status, a.statusErr)
	}
}

func TestPromptLinePlacesCursorAfterText(t *testing.T) {
	line, column := promptLine("Feed name", []rune("Tech News"), 2, 40)
	if line != "Feed name: Tech News" {
		t.Fatalf("line = %q", line)
	}
	if column != 14 {
		t.Fatalf("column = %d, want 14", column)
	}
}

func TestPromptLineKeepsCursorVisibleForLongValue(t *testing.T) {
	line, column := promptLine("Name", []rune("1234567890"), 10, 10)
	if line != "Name: 890" {
		t.Fatalf("line = %q, want %q", line, "Name: 890")
	}
	if column != 10 {
		t.Fatalf("column = %d, want 10", column)
	}
}
