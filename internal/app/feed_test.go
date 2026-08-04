package app

import (
	"context"
	"database/sql"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

func TestCreateFeedStoresInitialEntriesWithOneRequest(t *testing.T) {
	hits := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		hits++
		_, _ = w.Write([]byte(`<rss><channel><title>Example</title><link>https://example.com</link>
<item><guid>one</guid><title>One</title><link>https://example.com/one</link><pubDate>Tue, 04 Aug 2026 12:00:00 +0000</pubDate></item>
<item><guid>two</guid><title>Two</title><link>https://example.com/two</link><pubDate>Tue, 04 Aug 2026 10:00:00 +0000</pubDate></item>
</channel></rss>`))
	}))
	defer server.Close()
	store, err := openStore(t.TempDir() + "/rssx.db")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()
	cfg := Config{MinIntervalMin: 10, MaxIntervalMin: 1440, InitialIntervalMin: 30}

	id, count, err := store.createFeed(context.Background(), server.URL, nil, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if hits != 1 || count != 2 {
		t.Fatalf("requests = %d, new entries = %d; want 1 request and 2 entries", hits, count)
	}
	var stored, interval int
	if err := store.db.QueryRow("SELECT count(*) FROM entries WHERE feed_id=:feed_id", sql.Named("feed_id", id)).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if err := store.db.QueryRow("SELECT fetch_interval_sec FROM feeds WHERE id=:feed_id", sql.Named("feed_id", id)).Scan(&interval); err != nil {
		t.Fatal(err)
	}
	if stored != 2 || interval != 3600 {
		t.Fatalf("stored entries = %d, interval = %d; want 2 and 3600", stored, interval)
	}
}

func TestComputeNextInterval(t *testing.T) {
	cfg := Config{MinIntervalMin: 10, MaxIntervalMin: 1440, InitialIntervalMin: 30}
	now := time.Date(2026, 8, 5, 0, 0, 0, 0, time.UTC)
	published := []time.Time{now, now.Add(-2 * time.Hour), now.Add(-4 * time.Hour)}
	if got := computeNextInterval(published, 0, cfg); got != 3600 {
		t.Fatalf("interval = %d, want 3600", got)
	}
	if got := computeNextInterval(published, 2, cfg); got != 8100 {
		t.Fatalf("backed-off interval = %d, want 8100", got)
	}
	if got := computeNextInterval([]time.Time{now}, 0, cfg); got != 1800 {
		t.Fatalf("initial interval = %d, want 1800", got)
	}
}

func TestSyncFailureRetriesAtMinimumInterval(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	store, err := openStore(t.TempDir() + "/rssx.db")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.close() }()
	id, err := store.addFeed(server.URL, "Example", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	cfg := Config{MinIntervalMin: 10, MaxIntervalMin: 1440, InitialIntervalMin: 30}
	started := time.Now().UTC()
	if _, err := store.syncFeed(context.Background(), id, cfg); err == nil {
		t.Fatal("sync succeeded, want HTTP error")
	}
	var nextRaw string
	var lastError sql.NullString
	if err := store.db.QueryRow("SELECT next_fetch_at,last_error FROM feeds WHERE id=:feed_id", sql.Named("feed_id", id)).Scan(&nextRaw, &lastError); err != nil {
		t.Fatal(err)
	}
	next, ok := parseStoredTime(nextRaw)
	if !ok || next.Before(started.Add(9*time.Minute+50*time.Second)) || next.After(started.Add(10*time.Minute+10*time.Second)) {
		t.Fatalf("next retry = %q, want about 10 minutes", nextRaw)
	}
	if !lastError.Valid {
		t.Fatal("last_error was not recorded")
	}
}

func TestFetchDocumentTrimsURL(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`<rss><channel><title>Example</title></channel></rss>`))
	}))
	defer server.Close()

	doc, _, _, err := fetchDocument(context.Background(), " \t"+server.URL+"\n", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if title, _ := feedMeta(doc, ""); title != "Example" {
		t.Fatalf("title = %q, want Example", title)
	}
}

func TestParseRSS1RDF(t *testing.T) {
	data := []byte(`<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <channel rdf:about="https://example.com/"><title>Example RDF</title><link>https://example.com/</link></channel>
 <item rdf:about="https://example.com/article">
  <title>An article</title><link>https://example.com/article</link>
  <description>Summary</description><dc:date>2026-08-04T16:24:54Z</dc:date>
  <content:encoded>&lt;p&gt;Body&lt;/p&gt;</content:encoded>
 </item>
</rdf:RDF>`)

	doc, err := parseFeedDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	title, site := feedMeta(doc, "fallback")
	if title != "Example RDF" || site != "https://example.com/" {
		t.Fatalf("feed metadata = (%q, %q)", title, site)
	}
	parsedItems := items(doc)
	if len(parsedItems) != 1 {
		t.Fatalf("item count = %d, want 1", len(parsedItems))
	}
	item := parsedItems[0]
	if itemGUID(item) != "https://example.com/article" {
		t.Fatalf("guid = %q", itemGUID(item))
	}
	if item.Date != "2026-08-04T16:24:54Z" || item.Encoded.Text != "&lt;p&gt;Body&lt;/p&gt;" {
		t.Fatalf("RSS 1.0 fields were not decoded: %#v", item)
	}
}

func TestConfiguredFeedURL(t *testing.T) {
	url := os.Getenv("RSSX_TEST_FEED_URL")
	if url == "" {
		t.Skip("RSSX_TEST_FEED_URL is not set")
	}
	doc, _, _, err := fetchDocument(context.Background(), url, "", "")
	if err != nil {
		t.Fatal(err)
	}
	if title, _ := feedMeta(doc, ""); title == "" {
		t.Fatal("empty feed title")
	}
	if len(items(doc)) == 0 {
		t.Fatal("feed contains no parsed items")
	}
}
