package app

import (
	"context"
	"database/sql"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"sort"
	"strings"
	"time"
)

type xmlFeed struct {
	XMLName xml.Name
	Channel struct {
		Title string    `xml:"title"`
		Link  string    `xml:"link"`
		Items []xmlItem `xml:"item"`
	} `xml:"channel"`
	Title   string    `xml:"title"`
	Links   []xmlLink `xml:"link"`
	Entries []xmlItem `xml:"entry"`
	Items   []xmlItem `xml:"item"`
}
type xmlLink struct {
	Href string `xml:"href,attr"`
	Rel  string `xml:"rel,attr"`
	Text string `xml:",chardata"`
}
type xmlText struct {
	Text string `xml:",innerxml"`
}
type xmlItem struct {
	About       string    `xml:"about,attr"`
	ID          string    `xml:"id"`
	GUID        string    `xml:"guid"`
	Title       string    `xml:"title"`
	Links       []xmlLink `xml:"link"`
	Author      string    `xml:"author>name"`
	Creator     string    `xml:"creator"`
	Description xmlText   `xml:"description"`
	Summary     xmlText   `xml:"summary"`
	Content     xmlText   `xml:"content"`
	Encoded     xmlText   `xml:"encoded"`
	PubDate     string    `xml:"pubDate"`
	Published   string    `xml:"published"`
	Updated     string    `xml:"updated"`
	Date        string    `xml:"date"`
}

func fetchDocument(ctx context.Context, url, etag, modified string) (xmlFeed, string, string, error) {
	url = strings.TrimSpace(url)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return xmlFeed{}, "", "", err
	}
	req.Header.Set("User-Agent", "rssx/0.1 (+https://github.com/d-issy/rssx)")
	if etag != "" {
		req.Header.Set("If-None-Match", etag)
	}
	if modified != "" {
		req.Header.Set("If-Modified-Since", modified)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return xmlFeed{}, "", "", err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusNotModified {
		return xmlFeed{}, resp.Header.Get("ETag"), resp.Header.Get("Last-Modified"), sql.ErrNoRows
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return xmlFeed{}, "", "", fmt.Errorf("HTTP %s", resp.Status)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 20<<20))
	if err != nil {
		return xmlFeed{}, "", "", err
	}
	doc, err := parseFeedDocument(data)
	if err != nil {
		return xmlFeed{}, "", "", err
	}
	return doc, resp.Header.Get("ETag"), resp.Header.Get("Last-Modified"), nil
}

func parseFeedDocument(data []byte) (xmlFeed, error) {
	var doc xmlFeed
	err := xml.Unmarshal(data, &doc)
	return doc, err
}
func feedMeta(doc xmlFeed, fallback string) (string, string) {
	title := strings.TrimSpace(doc.Channel.Title)
	site := strings.TrimSpace(doc.Channel.Link)
	if title == "" {
		title = strings.TrimSpace(doc.Title)
		for _, l := range doc.Links {
			if l.Rel == "alternate" || l.Rel == "" {
				site = l.Href
				break
			}
		}
	}
	if title == "" {
		title = fallback
	}
	return title, site
}
func items(doc xmlFeed) []xmlItem {
	if len(doc.Channel.Items) > 0 {
		return doc.Channel.Items
	}
	if len(doc.Items) > 0 {
		return doc.Items
	}
	return doc.Entries
}
func itemURL(v xmlItem) string {
	for _, l := range v.Links {
		if l.Rel == "alternate" || l.Rel == "" {
			if l.Href != "" {
				return l.Href
			}
			return strings.TrimSpace(l.Text)
		}
	}
	return ""
}
func itemGUID(v xmlItem) string {
	for _, x := range []string{v.GUID, v.ID, v.About, itemURL(v)} {
		if strings.TrimSpace(x) != "" {
			return strings.TrimSpace(x)
		}
	}
	return v.Title + v.PubDate + v.Published
}
func itemDate(v xmlItem) any {
	raw := v.PubDate
	if raw == "" {
		raw = v.Published
	}
	if raw == "" {
		raw = v.Updated
	}
	if raw == "" {
		raw = v.Date
	}
	if raw == "" {
		return nil
	}
	for _, layout := range []string{time.RFC1123Z, time.RFC1123, time.RFC3339, time.RFC822Z, time.RFC822} {
		if t, err := time.Parse(layout, strings.TrimSpace(raw)); err == nil {
			return t.UTC().Format("2006-01-02 15:04:05")
		}
	}
	return raw
}

func (s *Store) createFeed(ctx context.Context, url string, folder *string, cfg Config) (string, int, error) {
	doc, etag, modified, err := fetchDocument(ctx, url, "", "")
	if err != nil {
		return "", 0, err
	}
	title, site := feedMeta(doc, url)
	id, err := s.addFeed(url, title, site, folder)
	if err != nil {
		return "", 0, err
	}
	count, err := s.storeFeedDocument(id, doc, etag, modified, cfg, time.Now().UTC())
	if err != nil {
		_ = s.deleteFeed(id)
		return "", 0, err
	}
	return id, count, nil
}

func (s *Store) syncFeed(ctx context.Context, id string, cfg Config) (int, error) {
	var url string
	var etag, modified sql.NullString
	if err := s.db.QueryRow("SELECT url,etag,last_modified FROM feeds WHERE id=:feed_id", sql.Named("feed_id", id)).Scan(&url, &etag, &modified); err != nil {
		return 0, err
	}
	doc, newETag, newModified, err := fetchDocument(ctx, url, etag.String, modified.String)
	now := time.Now().UTC()
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		next := now.Add(time.Duration(cfg.MinIntervalMin) * time.Minute)
		_, _ = s.db.Exec("UPDATE feeds SET last_fetched_at=:last_fetched_at,next_fetch_at=:next_fetch_at,last_error=:last_error WHERE id=:feed_id",
			sql.Named("last_fetched_at", dbTime(now)), sql.Named("next_fetch_at", dbTime(next)), sql.Named("last_error", err.Error()), sql.Named("feed_id", id))
		return 0, err
	}
	return s.storeFeedDocument(id, doc, newETag, newModified, cfg, now)
}

func (s *Store) storeFeedDocument(id string, doc xmlFeed, etag, modified string, cfg Config, now time.Time) (int, error) {
	tx, err := s.db.Begin()
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()
	var previousEmpty int
	if err := tx.QueryRow("SELECT consecutive_empty FROM feeds WHERE id=:feed_id", sql.Named("feed_id", id)).Scan(&previousEmpty); err != nil {
		return 0, err
	}
	count := 0
	for _, v := range items(doc) {
		guid := itemGUID(v)
		if guid == "" {
			continue
		}
		content := v.Content.Text
		if content == "" {
			content = v.Encoded.Text
		}
		if content == "" {
			content = v.Description.Text
		}
		author := v.Author
		if author == "" {
			author = v.Creator
		}
		var res sql.Result
		var e error
		if s.integerPK["entries"] {
			res, e = tx.Exec(`INSERT OR IGNORE INTO entries(feed_id,guid,title,url,author,content,summary,published_at)
 VALUES(:feed_id,:guid,:title,:url,:author,:content,:summary,:published_at)`,
				sql.Named("feed_id", id), sql.Named("guid", guid), sql.Named("title", strings.TrimSpace(v.Title)), sql.Named("url", nullString(itemURL(v))),
				sql.Named("author", nullString(author)), sql.Named("content", content), sql.Named("summary", v.Summary.Text), sql.Named("published_at", itemDate(v)))
		} else {
			res, e = tx.Exec(`INSERT OR IGNORE INTO entries(id,feed_id,guid,title,url,author,content,summary,published_at)
 VALUES(:entry_id,:feed_id,:guid,:title,:url,:author,:content,:summary,:published_at)`,
				sql.Named("entry_id", newID()), sql.Named("feed_id", id), sql.Named("guid", guid), sql.Named("title", strings.TrimSpace(v.Title)),
				sql.Named("url", nullString(itemURL(v))), sql.Named("author", nullString(author)), sql.Named("content", content),
				sql.Named("summary", v.Summary.Text), sql.Named("published_at", itemDate(v)))
		}
		if e != nil {
			return count, e
		}
		if n, _ := res.RowsAffected(); n > 0 {
			count++
		}
	}
	empty := previousEmpty
	if count == 0 {
		empty++
	} else {
		empty = 0
	}
	rows, err := tx.Query("SELECT published_at FROM entries WHERE feed_id=:feed_id AND published_at IS NOT NULL ORDER BY published_at DESC LIMIT 15", sql.Named("feed_id", id))
	if err != nil {
		return count, err
	}
	var published []time.Time
	for rows.Next() {
		var raw string
		if err := rows.Scan(&raw); err != nil {
			_ = rows.Close()
			return count, err
		}
		if parsed, ok := parseStoredTime(raw); ok {
			published = append(published, parsed)
		}
	}
	err = rows.Close()
	if err != nil {
		return count, err
	}
	nextInterval := computeNextInterval(published, empty, cfg)
	_, err = tx.Exec(`UPDATE feeds SET
 etag=COALESCE(NULLIF(:etag,''),etag),last_modified=COALESCE(NULLIF(:last_modified,''),last_modified),
 last_fetched_at=:last_fetched_at,next_fetch_at=:next_fetch_at,fetch_interval_sec=:fetch_interval_sec,
 consecutive_empty=:consecutive_empty,last_error=NULL WHERE id=:feed_id`,
		sql.Named("etag", etag), sql.Named("last_modified", modified), sql.Named("last_fetched_at", dbTime(now)),
		sql.Named("next_fetch_at", dbTime(now.Add(time.Duration(nextInterval)*time.Second))), sql.Named("fetch_interval_sec", nextInterval),
		sql.Named("consecutive_empty", empty), sql.Named("feed_id", id))
	if err != nil {
		return count, err
	}
	return count, tx.Commit()
}

func computeNextInterval(published []time.Time, consecutiveEmpty int, cfg Config) int {
	times := append([]time.Time(nil), published...)
	sort.Slice(times, func(i, j int) bool { return times[i].After(times[j]) })
	if len(times) > 15 {
		times = times[:15]
	}
	base := float64(cfg.InitialIntervalMin * 60)
	if len(times) >= 2 {
		var total float64
		var count int
		for i := 0; i+1 < len(times); i++ {
			delta := times[i].Sub(times[i+1]).Seconds()
			if delta > 0 {
				total += delta
				count++
			}
		}
		if count > 0 {
			base = total / float64(count) * 0.5
		}
	}
	if consecutiveEmpty > 0 {
		base *= math.Pow(1.5, float64(consecutiveEmpty))
	}
	return max(cfg.MinIntervalMin*60, min(cfg.MaxIntervalMin*60, int(base)))
}

func parseStoredTime(raw string) (time.Time, bool) {
	for _, layout := range []string{time.RFC3339, "2006-01-02 15:04:05", time.RFC1123Z, time.RFC1123} {
		if parsed, err := time.Parse(layout, strings.TrimSpace(raw)); err == nil {
			return parsed, true
		}
	}
	return time.Time{}, false
}
func (s *Store) dueFeedIDs(all bool) ([]string, error) {
	q := "SELECT id FROM feeds"
	var args []any
	if !all {
		q += " WHERE next_fetch_at IS NULL OR next_fetch_at<=:now"
		args = append(args, sql.Named("now", dbTime(time.Now().UTC())))
	}
	rows, err := s.db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
func dbTime(t time.Time) string { return t.UTC().Format("2006-01-02 15:04:05") }
func nullString(s string) any {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return strings.TrimSpace(s)
}
