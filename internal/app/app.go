package app

import (
	"context"
	"database/sql"
	"encoding/base64"
	"fmt"
	"html"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

type sidebarItem struct {
	kind, label, id  string
	unread, depth    int
	expandable, open bool
}
type view int

const (
	mainView view = iota
	navigationView
	helpView
	manageView
	filterView
	choiceView
	errorView
	articleView
)

type syncRequest struct {
	id  string
	all bool
}
type syncEvent struct {
	message string
	err     error
}

const (
	entryPageSize      = 50
	entryLoadThreshold = 5
)

type application struct {
	cfg                            Config
	store                          *Store
	term                           *Terminal
	view, previous                 view
	scope, folderID, feedID, query string
	unreadOnly, running            bool
	sidebar                        []sidebarItem
	sideIndex, sideTop             int
	entries                        []Entry
	entriesMore                    bool
	entryIndex, entryTop           int
	expanded                       string
	expandedAt                     time.Time
	status                         string
	statusErr                      bool
	errorMessage                   string
	errorReturn                    view
	errorLogPath                   string
	article                        EntryDetail
	articleTop                     int
	lastSync                       time.Time
	folderOpen                     map[string]bool
	manageFolders                  bool
	manageIndex                    int
	manageQuery                    string
	manageFilter                   map[string]bool
	filterIndex                    int
	choices                        []choice
	choiceIndex                    int
	choiceTitle                    string
	choiceReturn                   view
	choiceCallback                 func(string)
	requests                       chan syncRequest
	events                         chan syncEvent
	cancel                         context.CancelFunc
	workers                        sync.WaitGroup
}
type choice struct{ label, value string }

func Run() error {
	cfg, err := loadConfig()
	if err != nil {
		return err
	}
	store, err := openStore(cfg.DBPath)
	if err != nil {
		return err
	}
	defer func() { _ = store.close() }()
	ctx, cancel := context.WithCancel(context.Background())
	a := &application{cfg: cfg, store: store, term: newTerminal(), scope: "all", unreadOnly: true, running: true, folderOpen: loadState(cfg.StatePath), requests: make(chan syncRequest, 8), events: make(chan syncEvent, 8), cancel: cancel, entryIndex: -1, choiceIndex: -1}
	a.errorLogPath = filepathDir(cfg.StatePath) + string(os.PathSeparator) + "error.log"
	if err = a.reload(); err != nil {
		return err
	}
	if err = a.term.enter(); err != nil {
		return err
	}
	defer a.term.exit()
	a.startWorker(ctx)
	defer func() { cancel(); a.workers.Wait(); _ = saveState(cfg.StatePath, a.folderOpen) }()
	for a.running {
		a.drainEvents()
		a.autoMarkRead()
		a.render()
		key, readErr := a.term.readKey(150 * time.Millisecond)
		if readErr != nil {
			return readErr
		}
		if key != "" {
			a.handleKey(key)
		}
	}
	return nil
}

func (a *application) startWorker(ctx context.Context) {
	a.workers.Add(1)
	go func() {
		defer a.workers.Done()
		ticker := time.NewTicker(time.Duration(max(1, a.cfg.SchedulerTickMin)) * time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case req := <-a.requests:
				a.sync(ctx, req)
			case <-ticker.C:
				a.sync(ctx, syncRequest{})
			}
		}
	}()
}
func (a *application) sync(ctx context.Context, req syncRequest) {
	ids := []string{req.id}
	if req.id == "" {
		var err error
		ids, err = a.store.dueFeedIDs(req.all)
		if err != nil {
			a.events <- syncEvent{err: err}
			return
		}
	}
	total := 0
	var lastErr error
	for _, id := range ids {
		n, err := a.store.syncFeed(ctx, id, a.cfg)
		total += n
		if err != nil {
			lastErr = err
		}
	}
	msg := fmt.Sprintf("Update complete: %d new entries", total)
	a.events <- syncEvent{message: msg, err: lastErr}
}
func (a *application) drainEvents() {
	for {
		select {
		case e := <-a.events:
			if e.err != nil {
				a.setError(e.err.Error())
			} else {
				a.status = e.message
				a.statusErr = false
			}
			a.lastSync = time.Now()
			_ = a.reload()
		default:
			return
		}
	}
}

func (a *application) reload() error {
	if err := a.reloadSidebar(); err != nil {
		return err
	}
	return a.reloadEntries()
}
func (a *application) reloadSidebar() error {
	folders, err := a.store.folders()
	if err != nil {
		return err
	}
	feeds, err := a.store.feeds("", nil)
	if err != nil {
		return err
	}
	unread, star, err := a.store.totals()
	if err != nil {
		return err
	}
	a.sidebar = []sidebarItem{{kind: "all", label: "All", unread: unread}, {kind: "starred", label: "★ Starred", unread: star}}
	byParent := map[string][]Folder{}
	for _, f := range folders {
		parent := ""
		if f.ParentID.Valid {
			parent = f.ParentID.String
		}
		byParent[parent] = append(byParent[parent], f)
	}
	feedByFolder := map[string][]Feed{}
	for _, f := range feeds {
		key := ""
		if f.FolderID.Valid {
			key = f.FolderID.String
		}
		feedByFolder[key] = append(feedByFolder[key], f)
	}
	var folderUnread func(string) int
	folderUnread = func(id string) int {
		n := 0
		for _, f := range feedByFolder[id] {
			n += f.Unread
		}
		for _, child := range byParent[id] {
			n += folderUnread(child.ID)
		}
		return n
	}
	var add func(string, int)
	add = func(parent string, depth int) {
		for _, f := range byParent[parent] {
			open, ok := a.folderOpen[f.ID]
			if !ok {
				open = true
			}
			a.sidebar = append(a.sidebar, sidebarItem{kind: "folder", label: f.Name, id: f.ID, unread: folderUnread(f.ID), depth: depth, expandable: true, open: open})
			if open {
				add(f.ID, depth+1)
				for _, feed := range feedByFolder[f.ID] {
					a.sidebar = append(a.sidebar, sidebarItem{kind: "feed", label: feed.Title, id: feed.ID, unread: feed.Unread, depth: depth + 1})
				}
			}
		}
	}
	add("", 0)
	for _, feed := range feedByFolder[""] {
		a.sidebar = append(a.sidebar, sidebarItem{kind: "feed", label: feed.Title, id: feed.ID, unread: feed.Unread})
	}
	if a.sideIndex >= len(a.sidebar) {
		a.sideIndex = max(0, len(a.sidebar)-1)
	}
	for i, v := range a.sidebar {
		if v.kind == a.scope && ((v.kind == "all" || v.kind == "starred") || v.id == a.folderID || v.id == a.feedID) {
			a.sideIndex = i
			break
		}
	}
	return nil
}
func (a *application) reloadEntries() error {
	selected := ""
	if e := a.selectedEntry(); e != nil {
		selected = e.ID
	}
	limit := max(entryPageSize, len(a.entries))
	entries, more, err := a.fetchEntries(limit, 0)
	if err != nil {
		return err
	}
	a.entries = entries
	a.entriesMore = more
	if len(entries) == 0 {
		a.entryIndex = -1
		a.expanded = ""
		return nil
	}
	if selected != "" {
		for i, v := range entries {
			if v.ID == selected {
				a.entryIndex = i
				return nil
			}
		}
	}
	if a.entryIndex >= len(entries) {
		a.entryIndex = len(entries) - 1
	}
	return nil
}

func (a *application) fetchEntries(limit, offset int) ([]Entry, bool, error) {
	if a.scope == "search" {
		return a.store.search(a.query, limit, offset)
	}
	id := a.feedID
	if a.scope == "folder" {
		id = a.folderID
	}
	return a.store.entries(a.scope, id, a.unreadOnly, limit, offset)
}

func (a *application) resetEntries() {
	a.entries = nil
	a.entriesMore = false
	a.entryIndex = -1
	a.entryTop = 0
	a.expanded = ""
}

func (a *application) loadMoreEntries() error {
	if !a.entriesMore {
		return nil
	}
	entries, more, err := a.fetchEntries(entryPageSize, len(a.entries))
	if err != nil {
		return err
	}
	a.entries = append(a.entries, entries...)
	a.entriesMore = more
	if len(entries) > 0 {
		a.status = fmt.Sprintf("Loaded %d more entries", len(entries))
		a.statusErr = false
	}
	return nil
}
func (a *application) selectedEntry() *Entry {
	if a.entryIndex >= 0 && a.entryIndex < len(a.entries) {
		return &a.entries[a.entryIndex]
	}
	return nil
}

func (a *application) render() {
	switch a.view {
	case navigationView:
		a.renderNavigation()
	case helpView:
		a.renderHelp()
	case manageView:
		a.renderManage()
	case filterView:
		a.renderFilter()
	case choiceView:
		a.renderChoice()
	case errorView:
		a.renderError()
	case articleView:
		a.renderArticle()
	default:
		a.renderMain()
	}
}
func (a *application) renderMain() {
	rows, cols := a.term.size()
	lines := []string{styled(fit(" rssx  Tab:folders/feeds  j/k or arrows:move  ?:help  q:quit", cols), bold), styled(fit(a.scopeTitle(), cols), bold)}
	available := max(1, rows-3)
	if len(a.entries) == 0 {
		lines = append(lines, "No entries to display.")
	} else {
		selected := a.entryIndex
		if selected < 0 {
			selected = 0
		}
		a.entryTop = ensureVisible(selected, a.entryTop, available)
		for i := a.entryTop; i < len(a.entries) && len(lines) < rows-1; i++ {
			e := a.entries[i]
			unread := " "
			if !e.Read {
				unread = "●"
			}
			star := "☆"
			if e.Starred {
				star = "★"
			}
			if i != a.entryIndex {
				if e.Starred {
					star = styled(star, yellow)
				} else {
					star = styled(star, gray)
				}
			}
			title := e.Title
			if title == "" {
				title = "(Untitled)"
			}
			line := fit(fmt.Sprintf("%s %s %s | %s %s", unread, star, e.FeedTitle, title, formatDate(e.PublishedAt)), cols)
			if i == a.entryIndex {
				line = styled(line, reverse)
			}
			lines = append(lines, line)
			if i == a.entryIndex && a.expanded == e.ID && len(lines) < rows-1 {
				detail, err := a.store.detail(e.ID)
				if err == nil {
					body := htmlToText(firstNonEmpty(detail.Content, detail.Summary))
					meta := strings.TrimSpace(detail.FeedTitle + " · " + detail.Author.String + " · " + formatDate(detail.PublishedAt))
					text := detail.Title + "\n" + meta + "\n" + detail.URL.String + "\n\n" + body
					for _, part := range wrapText(text, max(10, cols-2)) {
						if len(lines) >= rows-1 {
							break
						}
						lines = append(lines, "  "+part)
					}
				}
			}
		}
	}
	for len(lines) < rows-1 {
		lines = append(lines, "")
	}
	lines = append(lines, a.statusLine(cols))
	a.term.render(lines)
}
func (a *application) scopeTitle() string {
	show := "unread only"
	if !a.unreadOnly {
		show = "show all"
	}
	switch a.scope {
	case "search":
		return "Search: " + a.query
	case "all":
		return "All (" + show + ")"
	case "starred":
		return "Starred"
	}
	if a.sideIndex < len(a.sidebar) {
		return a.sidebar[a.sideIndex].label + " (" + show + ")"
	}
	return a.scope
}
func (a *application) renderNavigation() {
	rows, cols := a.term.size()
	lines := []string{styled(fit("Folders/feeds  j/k or arrows:move  Enter:select  X:toggle folder  Tab/Esc:back", cols), bold)}
	available := rows - 2
	a.sideTop = ensureVisible(a.sideIndex, a.sideTop, available)
	for i := a.sideTop; i < len(a.sidebar) && len(lines) < rows-1; i++ {
		v := a.sidebar[i]
		prefix := strings.Repeat("  ", v.depth)
		if v.expandable {
			if v.open {
				prefix += "▾ "
			} else {
				prefix += "▸ "
			}
		} else if v.depth > 0 {
			prefix += "  "
		}
		badge := ""
		if v.unread > 0 {
			badge = fmt.Sprintf(" %d", v.unread)
		}
		line := fit(prefix+v.label+badge, cols)
		if i == a.sideIndex {
			line = styled(line, reverse)
		}
		lines = append(lines, line)
	}
	for len(lines) < rows-1 {
		lines = append(lines, "")
	}
	lines = append(lines, a.statusLine(cols))
	a.term.render(lines)
}
func (a *application) renderHelp() {
	_, cols := a.term.size()
	rows := []string{
		"rssx help",
		"",
		"Main",
		helpRow("Tab", "Select folder/feed"),
		helpRow("j/k, ↑/↓", "Move between entries"),
		helpRow("Enter", "View the full RSS content"),
		helpRow("m / f", "Toggle read / starred"),
		helpRow("v", "Open original article in browser"),
		helpRow("g/G", "First/last entry"),
		helpRow("A", "Mark current feed/folder as read"),
		helpRow("u", "Toggle unread only/show all"),
		helpRow("r/R", "Update current feed/all feeds"),
		helpRow("/", "Search"),
		helpRow("a", "Add feed"),
		helpRow("M", "Manage feeds and folders"),
		"",
		"Navigation",
		helpRow("j/k, ↑/↓", "Select and switch view"),
		helpRow("X", "Expand/collapse folder"),
		"",
		"Manage",
		helpRow("Tab", "Switch feeds/folders"),
		helpRow("a/e/d/Enter", "Add/edit/delete/change folder"),
		helpRow("/ / F / y", "Search/filter/copy URL"),
		"",
		"Esc or q to go back",
	}
	for i := range rows {
		rows[i] = fit(rows[i], cols)
	}
	rows[0] = styled(rows[0], bold)
	a.term.render(rows)
}

func helpRow(key, description string) string {
	const keyWidth = 16
	return "  " + fit(key, keyWidth) + description
}

func (a *application) renderError() {
	rows, cols := a.term.size()
	lines := []string{
		styled(fit(" Error details  y:copy all  Esc/Enter:back", cols), bold+red),
		"",
	}
	for _, line := range wrapText(a.errorMessage, max(10, cols)) {
		if len(lines) >= rows-3 {
			lines = append(lines, styled(fit("… See the log for more details", cols), dim))
			break
		}
		lines = append(lines, line)
	}
	lines = append(lines, "", "Log: "+a.errorLogPath)
	a.term.render(lines)
}

func (a *application) renderArticle() {
	rows, cols := a.term.size()
	lines := articleLines(a.article, max(1, cols-2))
	available := max(1, rows-2)
	maxTop := max(0, len(lines)-available)
	a.articleTop = min(maxTop, max(0, a.articleTop))

	out := []string{styled(fit(" RSS content  j/k or arrows:scroll  g/G:top/bottom  v:browser  Enter/Esc/q:back", cols), bold)}
	end := min(len(lines), a.articleTop+available)
	for _, line := range lines[a.articleTop:end] {
		out = append(out, fit("  "+line, cols))
	}
	for len(out) < rows-1 {
		out = append(out, "")
	}
	position := fmt.Sprintf(" %d-%d / %d", min(len(lines), a.articleTop+1), end, len(lines))
	out = append(out, styled(fit(position, cols), dim))
	a.term.render(out)
}

func articleLines(article EntryDetail, width int) []string {
	title := article.Title
	if title == "" {
		title = "(Untitled)"
	}
	meta := []string{}
	for _, value := range []string{article.FeedTitle, article.Author.String, formatDate(article.PublishedAt)} {
		if value = strings.TrimSpace(value); value != "" {
			meta = append(meta, value)
		}
	}
	body := htmlToText(firstNonEmpty(article.Content, article.Summary))
	if body == "" {
		body = "This RSS entry does not include article content."
	}
	text := title
	if len(meta) > 0 {
		text += "\n" + strings.Join(meta, " · ")
	}
	text += "\n\n" + body
	return wrapText(text, max(1, width))
}
func (a *application) statusLine(cols int) string {
	text := a.status
	if a.statusErr {
		text += " | E: full error"
	}
	if !a.lastSync.IsZero() {
		text += " | Last updated " + a.lastSync.Format("2006-01-02 15:04")
	}
	code := dim
	if a.statusErr {
		code = red
	}
	return styled(fit(text, cols), code)
}

func (a *application) handleKey(key string) {
	if key == "ctrl_c" {
		a.running = false
		return
	}
	if a.view == errorView {
		switch key {
		case "q", "esc", "enter":
			a.view = a.errorReturn
		case "y":
			writeOSC52(base64.StdEncoding.EncodeToString([]byte(a.errorMessage)))
			a.status = "Copied the full error to the clipboard (if supported by your terminal)"
		}
		return
	}
	if a.view == helpView {
		if key == "q" || key == "esc" || key == "?" {
			a.view = a.previous
		}
		return
	}
	if key == "?" {
		a.previous = a.view
		a.view = helpView
		return
	}
	if key == "E" && a.errorMessage != "" {
		a.errorReturn = a.view
		a.view = errorView
		return
	}
	switch a.view {
	case navigationView:
		a.handleNavigation(key)
	case articleView:
		a.handleArticle(key)
	case manageView:
		a.handleManage(key)
	case filterView:
		a.handleFilter(key)
	case choiceView:
		a.handleChoice(key)
	default:
		a.handleMain(key)
	}
}
func (a *application) handleMain(key string) {
	switch key {
	case "q":
		a.running = false
	case "tab", "left", "X":
		a.view = navigationView
	case "j", "down":
		a.moveEntry(1, true)
	case "k", "up":
		a.moveEntry(-1, true)
	case "g":
		a.selectEntry(0, false)
	case "G":
		a.selectEntry(len(a.entries)-1, false)
	case "enter":
		a.openArticle()
	case "m":
		a.toggleRead()
	case "f":
		a.toggleStar()
	case "v":
		a.openOriginal()
	case "u":
		a.unreadOnly = !a.unreadOnly
		a.resetEntries()
		_ = a.reloadEntries()
	case "A":
		a.markScopeRead()
	case "r":
		if a.feedID != "" {
			a.status = "Updating feed…"
			a.requests <- syncRequest{id: a.feedID}
		}
	case "R":
		a.status = "Updating all feeds…"
		a.requests <- syncRequest{all: true}
	case "/":
		if q, ok := a.prompt("Search", a.query); ok {
			a.scope = "search"
			a.query = strings.TrimSpace(q)
			a.feedID = ""
			a.folderID = ""
			a.resetEntries()
			_ = a.reloadEntries()
		}
	case "a":
		a.addFeedFlow()
	case "M":
		a.view = manageView
		a.manageIndex = 0
	case "esc":
		if a.scope == "search" {
			a.scope = "all"
			a.query = ""
			a.resetEntries()
			_ = a.reload()
		}
	}
}

func (a *application) handleArticle(key string) {
	rows, cols := a.term.size()
	available := max(1, rows-2)
	maxTop := max(0, len(articleLines(a.article, max(1, cols-2)))-available)
	switch key {
	case "q", "esc", "enter", "left":
		a.view = mainView
	case "v":
		a.openOriginal()
	case "j", "down":
		a.articleTop = min(maxTop, a.articleTop+1)
	case "k", "up":
		a.articleTop = max(0, a.articleTop-1)
	case "g":
		a.articleTop = 0
	case "G":
		a.articleTop = maxTop
	}
}
func (a *application) handleNavigation(key string) {
	switch key {
	case "q", "esc", "tab", "right", "enter":
		a.view = mainView
	case "j", "down":
		a.moveSidebar(1)
	case "k", "up":
		a.moveSidebar(-1)
	case "g":
		a.moveSidebarTo(0)
	case "G":
		a.moveSidebarTo(len(a.sidebar) - 1)
	case "X":
		a.toggleFolder()
	}
}
func (a *application) moveSidebar(delta int) { a.moveSidebarTo(a.sideIndex + delta) }
func (a *application) moveSidebarTo(index int) {
	if len(a.sidebar) == 0 {
		return
	}
	a.sideIndex = min(len(a.sidebar)-1, max(0, index))
	v := a.sidebar[a.sideIndex]
	a.scope = v.kind
	a.folderID = ""
	a.feedID = ""
	switch v.kind {
	case "folder":
		a.folderID = v.id
	case "feed":
		a.feedID = v.id
	}
	a.query = ""
	a.resetEntries()
	_ = a.reloadEntries()
}
func (a *application) toggleFolder() {
	if len(a.sidebar) == 0 {
		return
	}
	v := a.sidebar[a.sideIndex]
	id := ""
	switch v.kind {
	case "folder":
		id = v.id
	case "feed":
		var folder sql.NullString
		_ = a.store.db.QueryRow("SELECT folder_id FROM feeds WHERE id=:feed_id", sql.Named("feed_id", v.id)).Scan(&folder)
		id = folder.String
	}
	if id != "" {
		current, ok := a.folderOpen[id]
		if !ok {
			current = true
		}
		a.folderOpen[id] = !current
		_ = saveState(a.cfg.StatePath, a.folderOpen)
		_ = a.reloadSidebar()
	}
}
func (a *application) moveEntry(delta int, expand bool) {
	index := 0
	if a.entryIndex >= 0 {
		index = a.entryIndex + delta
	}
	a.selectEntry(index, expand)
}
func (a *application) selectEntry(index int, expand bool) {
	if len(a.entries) == 0 {
		return
	}
	if a.entriesMore && index >= len(a.entries)-entryLoadThreshold {
		if err := a.loadMoreEntries(); err != nil {
			a.setError(err.Error())
			return
		}
	}
	a.entryIndex = min(len(a.entries)-1, max(0, index))
	if expand {
		a.expanded = a.entries[a.entryIndex].ID
		a.expandedAt = time.Now()
	}
}
func (a *application) autoMarkRead() {
	if a.expanded == "" || a.expandedAt.IsZero() || time.Since(a.expandedAt) < time.Second {
		return
	}
	e := a.selectedEntry()
	if e != nil && e.ID == a.expanded && !e.Read {
		if a.store.markRead(e.ID, true) == nil {
			e.Read = true
			_ = a.reloadSidebar()
		}
	}
	a.expandedAt = time.Time{}
}
func (a *application) toggleRead() {
	e := a.selectedEntry()
	if e == nil {
		return
	}
	if a.store.markRead(e.ID, !e.Read) == nil {
		e.Read = !e.Read
		_ = a.reloadSidebar()
	}
}
func (a *application) toggleStar() {
	e := a.selectedEntry()
	if e == nil {
		return
	}
	if value, err := a.store.toggleStar(e.ID); err == nil {
		e.Starred = value
		_ = a.reloadSidebar()
	}
}
func (a *application) markScopeRead() {
	var query string
	var args []any
	if a.scope == "all" {
		query = "UPDATE entries SET is_read=1,read_at=datetime('now') WHERE is_read=0"
	} else if a.scope == "feed" && a.feedID != "" {
		query = "UPDATE entries SET is_read=1,read_at=datetime('now') WHERE is_read=0 AND feed_id=:feed_id"
		args = []any{sql.Named("feed_id", a.feedID)}
	} else if a.scope == "folder" && a.folderID != "" {
		ids, _ := a.store.descendantIDs(a.folderID)
		marks := make([]string, len(ids))
		for i, id := range ids {
			name := fmt.Sprintf("folder_id_%d", i)
			marks[i] = ":" + name
			args = append(args, sql.Named(name, id))
		}
		query = "UPDATE entries SET is_read=1,read_at=datetime('now') WHERE is_read=0 AND feed_id IN (SELECT id FROM feeds WHERE folder_id IN (" + strings.Join(marks, ",") + "))"
	} else {
		a.setError("Mark all as read is only available when All, a feed, or a folder is selected")
		return
	}
	if _, err := a.store.db.Exec(query, args...); err != nil {
		a.setError(err.Error())
		return
	}
	a.status = "Marked all as read"
	a.statusErr = false
	_ = a.reload()
}
func (a *application) openArticle() {
	e := a.selectedEntry()
	if e == nil {
		return
	}
	detail, err := a.store.detail(e.ID)
	if err != nil {
		a.setError(err.Error())
		return
	}
	a.article = detail
	a.articleTop = 0
	a.view = articleView
	if !e.Read && a.store.markRead(e.ID, true) == nil {
		e.Read = true
		_ = a.reloadSidebar()
	}
}

func (a *application) openOriginal() {
	e := a.selectedEntry()
	if e == nil || !e.URL.Valid {
		return
	}
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", e.URL.String)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", e.URL.String)
	default:
		cmd = exec.Command("xdg-open", e.URL.String)
	}
	if err := cmd.Start(); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Opened in browser"
		a.statusErr = false
	}
}

func (a *application) renderManage() {
	rows, cols := a.term.size()
	lines := []string{styled(fit(" Manage  Tab:switch  /:search  F:filter  a:add  e:edit  d:delete  q:back", cols), bold)}
	if a.manageFolders {
		folders, _ := a.store.folders()
		lines = append(lines, styled(fit("[Folders]", cols), cyan))
		a.manageIndex = clampIndex(a.manageIndex, len(folders))
		for i, v := range folders {
			if len(lines) >= rows-1 {
				break
			}
			line := fit(fmt.Sprintf("%s | %d feeds", v.Name, v.FeedCount), cols)
			if i == a.manageIndex {
				line = styled(line, reverse)
			}
			lines = append(lines, line)
		}
	} else {
		feeds, _ := a.store.feeds(a.manageQuery, a.manageFilter)
		lines = append(lines, styled(fit(fmt.Sprintf("[Feeds]  query=%s  filter=%s", dash(a.manageQuery), a.filterLabel()), cols), cyan))
		a.manageIndex = clampIndex(a.manageIndex, len(feeds))
		folderNames := map[string]string{}
		folders, _ := a.store.folders()
		for _, f := range folders {
			folderNames[f.ID] = f.Name
		}
		for i, v := range feeds {
			if len(lines) >= rows-1 {
				break
			}
			folder := "Uncategorized"
			if v.FolderID.Valid {
				folder = folderNames[v.FolderID.String]
			}
			meta := "Never fetched"
			if v.LastFetchedAt.Valid {
				meta = "Fetched " + v.LastFetchedAt.String
			}
			if v.LastError.Valid {
				meta += " Error"
			}
			line := fit(fmt.Sprintf("%s | %s | %s | %d unread | %s", v.Title, v.URL, folder, v.Unread, meta), cols)
			if i == a.manageIndex {
				line = styled(line, reverse)
			}
			lines = append(lines, line)
		}
	}
	for len(lines) < rows-1 {
		lines = append(lines, "")
	}
	lines = append(lines, a.statusLine(cols))
	a.term.render(lines)
}
func (a *application) handleManage(key string) {
	switch key {
	case "q", "esc":
		a.view = mainView
		_ = a.reload()
	case "tab":
		a.manageFolders = !a.manageFolders
		a.manageIndex = 0
	case "j", "down":
		a.manageIndex++
	case "k", "up":
		a.manageIndex = max(0, a.manageIndex-1)
	case "/":
		if !a.manageFolders {
			if q, ok := a.prompt("Search feeds", a.manageQuery); ok {
				a.manageQuery = strings.TrimSpace(q)
				a.manageIndex = 0
			}
		}
	case "F":
		if !a.manageFolders {
			a.view = filterView
			a.filterIndex = 0
		}
	case "a":
		if a.manageFolders {
			a.createFolderFlow()
		} else {
			a.addFeedFlow()
		}
	case "e":
		if a.manageFolders {
			a.renameFolderFlow()
		} else {
			a.renameFeedFlow()
		}
	case "enter":
		if a.manageFolders {
			a.renameFolderFlow()
		} else {
			a.changeFeedFolderFlow()
		}
	case "d":
		if a.manageFolders {
			a.deleteFolderFlow()
		} else {
			a.deleteFeedFlow()
		}
	case "y":
		if !a.manageFolders {
			a.copyFeedURL()
		}
	}
}
func (a *application) renderFilter() {
	_, cols := a.term.size()
	folders, _ := a.store.folders()
	choices := []choice{{"Uncategorized", "__orphan"}}
	for _, f := range folders {
		choices = append(choices, choice{f.Name, f.ID})
	}
	lines := []string{styled(fit("Filter by folder  Space:toggle  a:all  n:none  Enter:apply  Esc:back", cols), bold)}
	for i, v := range choices {
		checked := a.manageFilter == nil || a.manageFilter[v.value]
		mark := "☐"
		if checked {
			mark = "☑"
		}
		line := mark + " " + v.label
		if i == a.filterIndex {
			line = styled(line, reverse)
		}
		lines = append(lines, line)
	}
	a.term.render(lines)
}
func (a *application) handleFilter(key string) {
	folders, _ := a.store.folders()
	values := []string{"__orphan"}
	for _, f := range folders {
		values = append(values, f.ID)
	}
	switch key {
	case "q", "esc":
		a.view = manageView
	case "j", "down":
		a.filterIndex = min(len(values)-1, a.filterIndex+1)
	case "k", "up":
		a.filterIndex = max(0, a.filterIndex-1)
	case "a":
		a.manageFilter = nil
	case "n":
		a.manageFilter = map[string]bool{}
	case " ":
		if a.manageFilter == nil {
			a.manageFilter = map[string]bool{}
			for _, v := range values {
				a.manageFilter[v] = true
			}
		}
		v := values[a.filterIndex]
		a.manageFilter[v] = !a.manageFilter[v]
	case "enter":
		a.manageIndex = 0
		a.view = manageView
	}
}
func (a *application) renderChoice() {
	_, cols := a.term.size()
	lines := []string{styled(fit(a.choiceTitle+"  Enter:select  Esc:cancel", cols), bold)}
	for i, v := range a.choices {
		line := v.label
		if i == a.choiceIndex {
			line = styled(line, reverse)
		}
		lines = append(lines, line)
	}
	a.term.render(lines)
}
func (a *application) handleChoice(key string) {
	switch key {
	case "q", "esc", "tab":
		a.view = a.choiceReturn
	case "j", "down":
		a.choiceIndex = min(len(a.choices)-1, a.choiceIndex+1)
	case "k", "up":
		if a.choiceIndex < 0 {
			a.choiceIndex = len(a.choices) - 1
		} else {
			a.choiceIndex = max(0, a.choiceIndex-1)
		}
	case "enter":
		if a.choiceIndex < 0 || a.choiceIndex >= len(a.choices) {
			a.setError("Select an item")
			return
		}
		v := a.choices[a.choiceIndex].value
		callback := a.choiceCallback
		a.view = a.choiceReturn
		if callback != nil {
			callback(v)
		}
	}
}

func (a *application) addFeedFlow() {
	url, ok := a.prompt("Feed URL", "")
	url = strings.TrimSpace(url)
	if !ok || url == "" {
		return
	}
	folders, _ := a.store.folders()
	a.choices = []choice{{"(Uncategorized)", ""}}
	for _, f := range folders {
		a.choices = append(a.choices, choice{f.Name, f.ID})
	}
	a.choices = append(a.choices, choice{"+ New folder", "__new"})
	a.choiceTitle = "Destination folder"
	a.choiceIndex = -1
	a.choiceReturn = a.view
	a.choiceCallback = func(value string) {
		var folder *string
		if value == "__new" {
			name, ok := a.prompt("New folder name", "")
			if !ok || strings.TrimSpace(name) == "" {
				return
			}
			id, err := a.store.addFolder(name)
			if err != nil {
				a.setError(err.Error())
				return
			}
			folder = &id
		} else if value != "" {
			folder = &value
		}
		a.status = "Fetching feed and entries…"
		_, count, err := a.store.createFeed(context.Background(), url, folder, a.cfg)
		if err != nil {
			a.setError(err.Error())
			return
		}
		a.status = fmt.Sprintf("Feed added: %d new entries", count)
		a.statusErr = false
		_ = a.reload()
	}
	a.view = choiceView
}
func (a *application) createFolderFlow() {
	name, ok := a.prompt("Folder name", "")
	if !ok || strings.TrimSpace(name) == "" {
		return
	}
	if _, err := a.store.addFolder(name); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Folder added"
		a.statusErr = false
		_ = a.reload()
	}
}
func (a *application) selectedManageFeed() (*Feed, bool) {
	feeds, err := a.store.feeds(a.manageQuery, a.manageFilter)
	if err != nil || a.manageIndex < 0 || a.manageIndex >= len(feeds) {
		return nil, false
	}
	return &feeds[a.manageIndex], true
}
func (a *application) selectedManageFolder() (*Folder, bool) {
	folders, err := a.store.folders()
	if err != nil || a.manageIndex < 0 || a.manageIndex >= len(folders) {
		return nil, false
	}
	return &folders[a.manageIndex], true
}
func (a *application) renameFolderFlow() {
	f, ok := a.selectedManageFolder()
	if !ok {
		return
	}
	name, yes := a.prompt("Folder name", f.Name)
	if !yes {
		return
	}
	if strings.TrimSpace(name) == "" {
		a.setError("Folder name is required")
		return
	}
	if err := a.store.renameFolder(f.ID, name); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Folder renamed"
		a.statusErr = false
		_ = a.reload()
	}
}
func (a *application) deleteFolderFlow() {
	f, ok := a.selectedManageFolder()
	if !ok {
		return
	}
	cascade := false
	if f.FeedCount > 0 {
		answer, yes := a.prompt("Delete "+f.Name+": d=move feeds to Uncategorized / c=delete contained feeds", "d")
		if !yes || (answer != "d" && answer != "c") {
			return
		}
		cascade = answer == "c"
	} else if !a.confirm("Delete " + f.Name + "?") {
		return
	}
	if err := a.store.deleteFolder(f.ID, cascade); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Folder deleted"
		a.statusErr = false
		_ = a.reload()
	}
}
func (a *application) renameFeedFlow() {
	f, ok := a.selectedManageFeed()
	if !ok {
		return
	}
	title, yes := a.prompt("Feed name", f.Title)
	if !yes {
		return
	}
	if strings.TrimSpace(title) == "" {
		a.setError("Feed name is required")
		return
	}
	if err := a.store.updateFeedTitle(f.ID, title); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Feed renamed"
		a.statusErr = false
		_ = a.reload()
	}
}
func (a *application) changeFeedFolderFlow() {
	feed, ok := a.selectedManageFeed()
	if !ok {
		return
	}
	folders, _ := a.store.folders()
	a.choices = []choice{{"(Uncategorized)", ""}}
	for _, f := range folders {
		a.choices = append(a.choices, choice{f.Name, f.ID})
	}
	a.choiceTitle = "Folder for " + feed.Title
	a.choiceIndex = -1
	a.choiceReturn = a.view
	a.choiceCallback = func(value string) {
		var folder *string
		if value != "" {
			folder = &value
		}
		if err := a.store.updateFeedFolder(feed.ID, folder); err != nil {
			a.setError(err.Error())
		} else {
			a.status = "Feed folder changed"
			a.statusErr = false
			_ = a.reload()
		}
	}
	a.view = choiceView
}
func (a *application) deleteFeedFlow() {
	f, ok := a.selectedManageFeed()
	if !ok || !a.confirm("Delete "+f.Title+"?") {
		return
	}
	if err := a.store.deleteFeed(f.ID); err != nil {
		a.setError(err.Error())
	} else {
		a.status = "Feed deleted"
		a.statusErr = false
		_ = a.reload()
	}
}
func (a *application) copyFeedURL() {
	f, ok := a.selectedManageFeed()
	if !ok {
		return
	}
	writeOSC52(base64.StdEncoding.EncodeToString([]byte(f.URL)))
	a.status = "Copied URL to the clipboard (if supported by your terminal)"
	a.statusErr = false
}

func (a *application) prompt(label, initial string) (string, bool) {
	value := []rune(initial)
	cursor := len(value)
	a.term.showCursor()
	defer a.term.hideCursor()
	for {
		a.render()
		rows, cols := a.term.size()
		line, cursorColumn := promptLine(label, value, cursor, cols)
		fmt.Printf("\x1b[%d;1H\x1b[K%s\x1b[%d;%dH", rows, line, rows, cursorColumn)
		key, err := a.term.readKey(0)
		if err != nil {
			return "", false
		}
		switch key {
		case "esc", "ctrl_c":
			return "", false
		case "enter":
			return string(value), true
		case "left":
			cursor = max(0, cursor-1)
		case "right":
			cursor = min(len(value), cursor+1)
		case "home":
			cursor = 0
		case "end":
			cursor = len(value)
		case "backspace":
			if cursor > 0 {
				value = append(value[:cursor-1], value[cursor:]...)
				cursor--
			}
		case "delete":
			if cursor < len(value) {
				value = append(value[:cursor], value[cursor+1:]...)
			}
		default:
			if len([]rune(key)) == 1 && key >= " " {
				value = append(value, 0)
				copy(value[cursor+1:], value[cursor:])
				value[cursor] = []rune(key)[0]
				cursor++
			}
		}
	}
}

func promptLine(label string, value []rune, cursor, cols int) (string, int) {
	if cols <= 0 {
		return "", 1
	}
	prefix := label + ": "
	prefixWidth := visibleWidth(prefix)
	if prefixWidth >= cols {
		prefix = clipText(prefix, max(1, cols-1))
		prefixWidth = visibleWidth(prefix)
	}
	available := max(1, cols-prefixWidth)
	cursor = min(max(0, cursor), len(value))

	start, widthBefore := cursor, 0
	for start > 0 {
		width := runeWidth(value[start-1])
		if widthBefore+width > available-1 {
			break
		}
		start--
		widthBefore += width
	}
	end, width := start, 0
	for end < len(value) {
		runeWidth := runeWidth(value[end])
		if width+runeWidth > available {
			break
		}
		width += runeWidth
		end++
	}
	return prefix + string(value[start:end]), min(cols, prefixWidth+widthBefore+1)
}
func (a *application) confirm(label string) bool {
	answer, ok := a.prompt(label+" [y/N]", "")
	return ok && (answer == "y" || answer == "Y")
}
func (a *application) setError(message string) {
	a.status = message
	a.statusErr = true
	a.errorMessage = message
	if a.view != errorView {
		a.errorReturn = a.view
		a.view = errorView
	}
	if err := os.MkdirAll(filepathDir(a.errorLogPath), 0o755); err != nil {
		return
	}
	file, err := os.OpenFile(a.errorLogPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer func() { _ = file.Close() }()
	_, _ = fmt.Fprintf(file, "%s %s\n", time.Now().Format(time.RFC3339), message)
}
func (a *application) filterLabel() string {
	if a.manageFilter == nil {
		return "All"
	}
	n := 0
	for _, yes := range a.manageFilter {
		if yes {
			n++
		}
	}
	if n == 0 {
		return "None"
	}
	return fmt.Sprintf("%d selected", n)
}

var tagRE = regexp.MustCompile(`(?s)<[^>]*>`)
var breakRE = regexp.MustCompile(`(?i)</?(p|div|br|li|h[1-6])[^>]*>`)
var spacesRE = regexp.MustCompile(`[ \t]+`)

func htmlToText(value string) string {
	value = html.UnescapeString(value)
	value = breakRE.ReplaceAllString(value, "\n")
	value = tagRE.ReplaceAllString(value, "")
	lines := strings.Split(value, "\n")
	out := lines[:0]
	for _, line := range lines {
		line = strings.TrimSpace(spacesRE.ReplaceAllString(line, " "))
		if line != "" {
			out = append(out, line)
		}
	}
	return strings.Join(out, "\n")
}
func wrapText(value string, width int) []string {
	var out []string
	for _, line := range strings.Split(value, "\n") {
		if line == "" {
			out = append(out, "")
			continue
		}
		r := []rune(line)
		for len(r) > 0 {
			n := 0
			cells := 0
			for n < len(r) {
				w := runeWidth(r[n])
				if cells+w > width {
					break
				}
				cells += w
				n++
			}
			if n == 0 {
				n = 1
			}
			out = append(out, string(r[:n]))
			r = r[n:]
		}
	}
	return out
}
func formatDate(v sql.NullString) string {
	if !v.Valid || v.String == "" {
		return ""
	}
	for _, layout := range []string{"2006-01-02 15:04:05", time.RFC3339} {
		if t, err := time.Parse(layout, v.String); err == nil {
			return t.Local().Format("2006-01-02 15:04")
		}
	}
	return v.String
}
func ensureVisible(index, top, rows int) int {
	if index < top {
		return index
	}
	if index >= top+rows {
		return index - rows + 1
	}
	return top
}
func clampIndex(index, length int) int {
	if length == 0 {
		return 0
	}
	return min(length-1, max(0, index))
}
func dash(value string) string {
	if value == "" {
		return "-"
	}
	return value
}
func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

func loadState(path string) map[string]bool {
	out := map[string]bool{}
	data, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(data), "\n") {
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.Trim(strings.TrimSpace(parts[0]), `"`)
		value := strings.TrimSpace(parts[1])
		out[key] = value == "true"
	}
	return out
}
func saveState(path string, state map[string]bool) error {
	if err := os.MkdirAll(filepathDir(path), 0o755); err != nil {
		return err
	}
	keys := make([]string, 0, len(state))
	for k := range state {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var b strings.Builder
	b.WriteString("[folders]\n")
	for _, k := range keys {
		fmt.Fprintf(&b, "%q = %t\n", k, state[k])
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}
func filepathDir(path string) string {
	index := strings.LastIndexAny(path, "/\\")
	if index < 0 {
		return "."
	}
	return path[:index]
}
