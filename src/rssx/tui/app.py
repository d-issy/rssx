from __future__ import annotations

import base64
import logging
import textwrap
import time
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import cast

from rssx import repository as repo
from rssx.config import Config
from rssx.db import connect, init_schema
from rssx.dto import EntryListItem, FeedListItem, FolderTreeNode, FolderWithCount
from rssx.lib.feeds.scheduling import FetchConfig
from rssx.lib.time import make_datetime_filters, resolve_tz
from rssx.tui.html_text import html_to_text
from rssx.tui.scheduler import SyncWorker
from rssx.tui.state import TuiState
from rssx.tui.terminal import Key, Terminal, style
from rssx.usecases.manage_feeds import FeedManagementUseCases
from rssx.usecases.manage_folders import FolderManagementUseCases
from rssx.usecases.results import ApplicationError

log = logging.getLogger(__name__)


class Scope(StrEnum):
    ALL = "all"
    STARRED = "starred"
    FOLDER = "folder"
    FEED = "feed"
    SEARCH = "search"


class View(StrEnum):
    MAIN = "main"
    NAVIGATION = "navigation"
    MANAGE = "manage"
    HELP = "help"
    FOLDER_FILTER = "folder_filter"
    CHOOSE_FOLDER = "choose_folder"


class ManageTab(StrEnum):
    FEEDS = "feeds"
    FOLDERS = "folders"


class FocusPane(StrEnum):
    SIDEBAR = "sidebar"
    ENTRIES = "entries"


@dataclass
class SidebarItem:
    kind: Scope | str
    label: str
    id: str | None = None
    unread_count: int = 0
    depth: int = 0
    expandable: bool = False
    open: bool = False


@dataclass
class Choice:
    label: str
    value: str | None


class RssxTui:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.conn = connect(self.config.db_path)
        init_schema(self.conn)
        self.fetch_cfg = FetchConfig(
            min_interval_min=self.config.min_interval_min,
            max_interval_min=self.config.max_interval_min,
            initial_interval_min=self.config.initial_interval_min,
        )
        self.feed_usecases = FeedManagementUseCases(self.conn, self.fetch_cfg)
        self.folder_usecases = FolderManagementUseCases(self.conn)
        self.term = Terminal()
        self.state = TuiState.load(self.config.state_path)
        _, self.fmt_dt = make_datetime_filters(resolve_tz(self.config.timezone))
        self.worker = SyncWorker(self.config, self.fetch_cfg)

        self.view = View.MAIN
        self.previous_view = View.MAIN
        self.scope = Scope.ALL
        self.current_folder_id: str | None = None
        self.current_feed_id: str | None = None
        self.unread_only = True
        self.search_query = ""
        self.focus_pane = FocusPane.ENTRIES
        self.sidebar_flash_until = 0.0
        self.navigation_auto_return_at: float | None = None

        self.sidebar_items: list[SidebarItem] = []
        self.sidebar_index = 0
        self.entries: list[EntryListItem] = []
        self.entry_index = -1
        self.entry_top = 0
        self.sidebar_top = 0
        self.expanded_entry_id: str | None = None
        self.expanded_at: float | None = None
        self.entry_body_cache: dict[str, str] = {}

        self.manage_tab = ManageTab.FEEDS
        self.manage_index = 0
        self.manage_query = ""
        self.manage_folder_filter: set[str] | None = None
        self.folder_filter_index = 0
        self.choice_title = ""
        self.choices: list[Choice] = []
        self.choice_index = -1
        self.choice_callback: object | None = None
        self.choice_return_view = View.MANAGE

        self.status = "起動中"
        self.status_error = False
        self.last_sync_at: datetime | None = None
        self.running = True

    def run(self) -> None:
        logging.basicConfig(level=logging.ERROR)
        self.reload_all()
        with self.term.session():
            self.worker.start()
            try:
                while self.running:
                    self._drain_sync_events()
                    self._auto_mark_read()
                    self._auto_return_navigation()
                    self.render()
                    key = self.term.read_key(0.15)
                    if key:
                        self.handle_key(key)
            finally:
                self.state.save(self.config.state_path)
                self.worker.stop()
                self.conn.close()

    def reload_all(
        self, current_entry_id: str | None = None, *, preserve_entry: bool = True
    ) -> None:
        selected = self.selected_entry()
        if current_entry_id is None and preserve_entry and selected is not None:
            current_entry_id = selected.id
        self.reload_sidebar()
        self.reload_entries(current_entry_id=current_entry_id)

    def reload_sidebar(self) -> None:
        folders = repo.list_folders(self.conn)
        feeds = repo.list_feeds(self.conn)
        tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(folders, feeds)
        items = [
            SidebarItem(Scope.ALL, "すべて", unread_count=repo.get_unread_total(self.conn)),
            SidebarItem(Scope.STARRED, "★ スター", unread_count=repo.get_starred_total(self.conn)),
        ]

        def add_folder(node: FolderTreeNode, depth: int) -> None:
            is_open = self.state.folder_open.get(node.id, True)
            items.append(
                SidebarItem(
                    Scope.FOLDER,
                    node.name,
                    id=node.id,
                    unread_count=node.unread_count,
                    depth=depth,
                    expandable=True,
                    open=is_open,
                )
            )
            if not is_open:
                return
            for child in node.children:
                add_folder(child, depth + 1)
            for feed in node.feeds:
                add_feed(feed, depth + 1)

        def add_feed(feed: FeedListItem, depth: int) -> None:
            items.append(
                SidebarItem(
                    Scope.FEED, feed.title, id=feed.id, unread_count=feed.unread_count, depth=depth
                )
            )

        for node in tree:
            add_folder(node, 0)
        for feed in orphan_feeds:
            add_feed(feed, 0)
        if orphan_unread and not orphan_feeds:
            items.append(SidebarItem("orphan", "未分類", unread_count=orphan_unread))

        self.sidebar_items = items
        self.sidebar_index = max(0, min(self.sidebar_index, len(items) - 1))
        self._sync_sidebar_selection()

    def _sync_sidebar_selection(self) -> None:
        for i, item in enumerate(self.sidebar_items):
            if item.kind == self.scope:
                if self.scope in {Scope.ALL, Scope.STARRED, Scope.SEARCH}:
                    self.sidebar_index = i
                    return
                if self.scope is Scope.FOLDER and item.id == self.current_folder_id:
                    self.sidebar_index = i
                    return
                if self.scope is Scope.FEED and item.id == self.current_feed_id:
                    self.sidebar_index = i
                    return

    def reload_entries(self, *, current_entry_id: str | None = None) -> None:
        if self.scope is Scope.SEARCH:
            self.entries = (
                repo.search_entries(self.conn, self.search_query) if self.search_query else []
            )
        else:
            entry_scope = repo.EntryScope(self.scope.value)
            self.entries = repo.list_entries(
                self.conn,
                scope=entry_scope,
                folder_id=self.current_folder_id,
                feed_id=self.current_feed_id,
                unread_only=self.unread_only,
            )
        if not self.entries:
            self.entry_index = -1
            self.expanded_entry_id = None
            self.expanded_at = None
            return
        if current_entry_id:
            for i, entry in enumerate(self.entries):
                if entry.id == current_entry_id:
                    self.entry_index = i
                    return
        if self.entry_index < 0:
            return
        self.entry_index = min(self.entry_index, len(self.entries) - 1)

    def selected_entry(self) -> EntryListItem | None:
        if 0 <= self.entry_index < len(self.entries):
            return self.entries[self.entry_index]
        return None

    def render(self) -> None:
        if self.view is View.HELP:
            self.term.render(self._render_help())
        elif self.view is View.NAVIGATION:
            self.term.render(self._render_navigation())
        elif self.view is View.MANAGE:
            self.term.render(self._render_manage())
        elif self.view is View.FOLDER_FILTER:
            self.term.render(self._render_folder_filter())
        elif self.view is View.CHOOSE_FOLDER:
            self.term.render(self._render_choice())
        else:
            self.term.render(self._render_main())

    def _render_main(self) -> list[str]:
        size = self.term.size()
        body_rows = max(1, size.rows - 2)
        header = self._fit(
            " rssx  Tab:フォルダ/フィード選択  j/k・矢印で記事移動  ?ヘルプ  q終了",
            size.cols,
        )
        lines = [style(header, "bold")]
        entries = self._entry_lines(body_rows, size.cols)
        lines.extend(self._fit(line, size.cols) for line in entries[:body_rows])
        lines.extend("" for _ in range(body_rows - min(len(entries), body_rows)))
        lines.append(self._status_line(size.cols))
        return lines

    def _render_navigation(self) -> list[str]:
        size = self.term.size()
        body_rows = max(1, size.rows - 2)
        lines = [
            style(
                self._fit(
                    "フォルダ/フィード選択  j/k・矢印で移動  Enterで決定  Xでフォルダ開閉  Tab/Esc戻る",
                    size.cols,
                ),
                "bold",
            )
        ]
        lines.extend(self._sidebar_lines(body_rows, size.cols))
        lines.extend("" for _ in range(body_rows - min(len(lines) - 1, body_rows)))
        lines.append(self._status_line(size.cols))
        return lines

    def _sidebar_lines(self, rows: int, width: int) -> list[str]:
        self.sidebar_top = self._ensure_visible(self.sidebar_index, self.sidebar_top, rows)
        visible = self.sidebar_items[self.sidebar_top : self.sidebar_top + rows]
        out: list[str] = []
        for offset, item in enumerate(visible):
            idx = self.sidebar_top + offset
            prefix = "  " * item.depth
            if item.expandable:
                prefix += "▾ " if item.open else "▸ "
            else:
                prefix += "  " if item.depth else ""
            badge = f" {item.unread_count}" if item.unread_count else ""
            text = self._fit(prefix + item.label + badge, width)
            if idx == self.sidebar_index and self.view is View.NAVIGATION:
                out.append(style(text, "selected"))
            else:
                out.append(text)
        return out

    def _entry_lines(self, rows: int, width: int) -> list[str]:
        title = self._scope_title()
        out = [
            style(
                self._fit(title, width),
                "bold" if self.focus_pane is FocusPane.ENTRIES else "accent",
            )
        ]
        if not self.entries:
            out.append("表示する記事がありません。")
            return out
        selected_idx = self.entry_index if 0 <= self.entry_index < len(self.entries) else None
        selected_line = selected_idx or 0
        available = max(1, rows - 1)
        selected_entry = self.entries[selected_idx] if selected_idx is not None else None
        selected_expanded = (
            selected_entry is not None and selected_entry.id == self.expanded_entry_id
        )
        body_limit = 0
        top_hidden = 0
        bottom_hidden = 0
        hidden_body_lines = 0
        content_available = available
        if selected_expanded:
            self.entry_top = max(0, selected_line - 2)
            top_hidden = self.entry_top
            selected_screen_row = selected_line - self.entry_top
            remaining_items = max(0, len(self.entries) - selected_line - 1)
            reserve_below = min(2, remaining_items)
            bottom_hidden = max(0, remaining_items - reserve_below)
            count_rows = (1 if top_hidden else 0) + (1 if bottom_hidden else 0)
            content_available = max(1, available - count_rows)
            body_limit = max(0, content_available - selected_screen_row - 1 - reserve_below)
        else:
            self.entry_top = self._ensure_visible(selected_line, self.entry_top, available)

        lines: list[tuple[int, str, bool]] = []
        for idx, entry in enumerate(self.entries):
            selected = idx == selected_idx
            row = self._entry_row(entry, width, selected=selected)
            lines.append((idx, row, True))
            if selected and selected_expanded and body_limit > 0:
                body = self._entry_body(entry.id)
                wrapped_body = self._wrap(body or "(本文なし)", width - 2)
                clipped = len(wrapped_body) > body_limit
                body_lines = wrapped_body[: max(0, body_limit - 1)] if clipped else wrapped_body
                hidden_body_lines = max(0, len(wrapped_body) - len(body_lines))
                for wrapped in body_lines:
                    lines.append((idx, "  " + wrapped, False))
                if clipped:
                    marker = self._fit(f"  … 本文残り{hidden_body_lines}行", width)
                    lines.append((idx, style(marker, "body_marker"), False))
        if top_hidden:
            out.append(style(self._fit(f"↑ 残り{top_hidden}件", width), "dim"))
        for entry_idx, line, is_row in lines[self.entry_top : self.entry_top + content_available]:
            if entry_idx == self.entry_index and is_row:
                out.append(style(self._fit(line, width), "selected"))
            else:
                out.append(line)
        if bottom_hidden:
            out.append(style(self._fit(f"↓ 残り{bottom_hidden}件", width), "dim"))
        return out

    def _entry_row(self, entry: EntryListItem, width: int, *, selected: bool) -> str:
        marker = self._star_marker(entry.is_starred, selected=selected)
        unread = "●" if not entry.is_read else " "
        prefix = f"{unread} {marker} "
        prefix_width = self._visible_len(f"{unread} ★ ")
        text = f"{entry.feed_title} | {entry.title or '(無題)'} {self.fmt_dt(entry.published_at)}"
        return prefix + self._fit(text, max(0, width - prefix_width))

    def _star_marker(self, is_starred: bool, *, selected: bool) -> str:
        if not selected:
            return style("★", "star") if is_starred else style("☆", "muted")
        if not is_starred:
            return "☆"
        # Selected rows use reverse-video. In reverse-video, background color
        # attributes are displayed as foreground colors on many terminals.
        return "\x1b[40m★\x1b[0m"

    def _scope_title(self) -> str:
        unread = "未読のみ" if self.unread_only else "すべて表示"
        if self.scope is Scope.SEARCH:
            return f"検索: {self.search_query}"
        if self.scope is Scope.ALL:
            return f"すべて ({unread})"
        if self.scope is Scope.STARRED:
            return "スター"
        item = self.sidebar_items[self.sidebar_index] if self.sidebar_items else None
        return f"{item.label if item else self.scope.value} ({unread})"

    def _entry_body(self, entry_id: str) -> str:
        cached = self.entry_body_cache.get(entry_id)
        if cached is not None:
            return cached
        detail = repo.get_entry(self.conn, entry_id)
        if not detail:
            return ""
        text = html_to_text(detail.content or detail.summary)
        parts = [detail.title or "(無題)"]
        meta = " · ".join(
            p for p in [detail.feed_title, detail.author, self.fmt_dt(detail.published_at)] if p
        )
        if meta:
            parts.append(meta)
        if detail.url:
            parts.append(detail.url)
        if text:
            parts.append(text)
        value = "\n\n".join(parts)
        self.entry_body_cache[entry_id] = value
        return value

    def _render_help(self) -> list[str]:
        size = self.term.size()
        rows = [
            "rssx help",
            "",
            "Main",
            "  Tab             フォルダ/フィード選択",
            "  j/k, ↑/↓       記事を移動",
            "  Enter           記事を開閉",
            "  m               既読/未読を切り替え",
            "  f               スターを切り替え",
            "  v               元記事をブラウザで開く",
            "  g/G             最初/最後の記事へ移動",
            "  J/K             フォルダ/フィード選択を開いて次/前へ移動",
            "  X               フォルダ/フィード選択を開く",
            "  A               現在のフィード/フォルダをすべて既読",
            "  u               未読のみ/すべて表示を切り替え",
            "  r/R             現在フィード更新/全更新",
            "  /               検索",
            "  a               フィード追加",
            "  M               管理ビュー",
            "",
            "Navigation",
            "  j/k, ↑/↓       フォルダ/フィードを移動して表示切替",
            "  Enter           決定して記事へ戻る",
            "  X               フォルダを開閉",
            "  Tab/Esc/q       記事へ戻る",
            "",
            "Manage",
            "  Tab             フィード/フォルダタブ切り替え",
            "  a/e/d/Enter     追加/編集/削除/決定",
            "  /               フィード検索",
            "  F               フォルダ絞り込み",
            "",
            "Esc or q で戻る",
        ]
        return [
            self._fit(style(row, "bold") if i == 0 else row, size.cols)
            for i, row in enumerate(rows)
        ]

    def _render_manage(self) -> list[str]:
        size = self.term.size()
        lines = [
            style(
                self._fit(" 管理  Tab切替  /検索  F絞込  a追加  e編集  d削除  q戻る", size.cols),
                "bold",
            )
        ]
        if self.manage_tab is ManageTab.FEEDS:
            lines.extend(self._render_manage_feeds(size.rows - 2, size.cols))
        else:
            lines.extend(self._render_manage_folders(size.rows - 2, size.cols))
        lines.append(self._status_line(size.cols))
        return lines

    def _render_manage_feeds(self, rows: int, width: int) -> list[str]:
        feeds = self._manage_feeds()
        header = f"[フィード]  query={self.manage_query or '-'}  filter={self._filter_label()}"
        out = [style(self._fit(header, width), "accent")]
        if not feeds:
            out.append("該当するフィードがありません。")
            return out
        self.manage_index = max(0, min(self.manage_index, len(feeds) - 1))
        top = max(0, min(self.manage_index - rows + 2, self.manage_index))
        folders = {f.id: f.name for f in repo.list_folders(self.conn)}
        for idx, feed in enumerate(feeds[top : top + rows - 1], start=top):
            folder = folders.get(feed.folder_id or "", "未分類")
            meta = (
                "未取得"
                if not feed.last_fetched_at
                else f"取得 {self.fmt_dt(feed.last_fetched_at)}"
            )
            if feed.last_error:
                meta += " エラー"
            text = f"{feed.title} | {feed.url} | {folder} | 未読 {feed.unread_count} | {meta}"
            out.append(
                style(self._fit(text, width), "selected")
                if idx == self.manage_index
                else self._fit(text, width)
            )
        return out

    def _render_manage_folders(self, rows: int, width: int) -> list[str]:
        folders = repo.list_folders_with_counts(self.conn)
        out = [style(self._fit("[フォルダ]", width), "accent")]
        if not folders:
            out.append("フォルダがありません。")
            return out
        self.manage_index = max(0, min(self.manage_index, len(folders) - 1))
        top = max(0, min(self.manage_index - rows + 2, self.manage_index))
        for idx, folder in enumerate(folders[top : top + rows - 1], start=top):
            text = f"{folder.name} | フィード {folder.feed_count}"
            out.append(
                style(self._fit(text, width), "selected")
                if idx == self.manage_index
                else self._fit(text, width)
            )
        return out

    def _render_folder_filter(self) -> list[str]:
        size = self.term.size()
        filters = self._folder_filter_choices()
        selected = self.manage_folder_filter
        lines = [
            style(
                self._fit(
                    "フォルダ絞り込み  Space切替  a全選択  n全解除  Enter適用  Esc戻る", size.cols
                ),
                "bold",
            )
        ]
        for i, choice in enumerate(filters):
            checked = selected is None or (
                choice.value in selected if choice.value is not None else False
            )
            text = f"{'☑' if checked else '☐'} {choice.label}"
            lines.append(style(text, "selected") if i == self.folder_filter_index else text)
        return lines

    def _render_choice(self) -> list[str]:
        size = self.term.size()
        lines = [style(self._fit(self.choice_title + "  Enter決定  Esc取消", size.cols), "bold")]
        for i, choice in enumerate(self.choices):
            lines.append(
                style(choice.label, "selected") if i == self.choice_index else choice.label
            )
        return lines

    def _status_line(self, width: int) -> str:
        sync = f"最終更新 {self.fmt_dt(self.last_sync_at)}" if self.last_sync_at else ""
        text = " | ".join(p for p in [self.status, sync] if p)
        return style(self._fit(text, width), "error" if self.status_error else "dim")

    def handle_key(self, key: Key) -> None:
        if key == "ctrl_c":
            self.running = False
            return
        if self.view is View.HELP:
            if key in {"q", "esc", "?"}:
                self.view = self.previous_view
            return
        if key == "?":
            self.previous_view = self.view
            self.view = View.HELP
            return
        if self.view is View.MANAGE:
            self._handle_manage_key(key)
        elif self.view is View.NAVIGATION:
            self._handle_navigation_key(key)
        elif self.view is View.FOLDER_FILTER:
            self._handle_folder_filter_key(key)
        elif self.view is View.CHOOSE_FOLDER:
            self._handle_choice_key(key)
        else:
            self._handle_main_key(key)

    def _toggle_focus_pane(self) -> None:
        self.focus_pane = (
            FocusPane.ENTRIES if self.focus_pane is FocusPane.SIDEBAR else FocusPane.SIDEBAR
        )

    def _handle_main_key(self, key: Key) -> None:
        if key == "q":
            self.running = False
        elif key in {"tab", "left"}:
            self.view = View.NAVIGATION
        elif key == "right":
            self.focus_pane = FocusPane.ENTRIES
        elif key in {"j", "down"}:
            self._move_entry(1, expand=True)
        elif key in {"k", "up"}:
            self._move_entry(-1, expand=True)
        elif key == "g":
            self._select_entry(0, expand=False)
        elif key == "G":
            self._select_entry(len(self.entries) - 1, expand=False)
        elif key == "enter":
            self._toggle_expand()
        elif key == "m":
            self._toggle_read()
        elif key == "f":
            self._toggle_star()
        elif key == "v":
            self._open_original()
        elif key == "J":
            self.view = View.NAVIGATION
            self._move_sidebar(1)
            self._schedule_navigation_auto_return()
        elif key == "K":
            self.view = View.NAVIGATION
            self._move_sidebar(-1)
            self._schedule_navigation_auto_return()
        elif key == "X":
            self.view = View.NAVIGATION
        elif key == "A":
            self._mark_current_scope_read()
        elif key == "u":
            self.unread_only = not self.unread_only
            self.reload_entries()
        elif key == "r":
            if self.current_feed_id:
                self.status = "フィード更新中…"
                self.status_error = False
                self.worker.refresh_feed(self.current_feed_id)
        elif key == "R":
            self.status = "全フィード更新中…"
            self.status_error = False
            self.worker.refresh_all()
        elif key == "/":
            query = self.prompt("検索", self.search_query)
            if query is not None:
                self.scope = Scope.SEARCH
                self.search_query = query.strip()
                self.current_feed_id = None
                self.current_folder_id = None
                self.reload_all(preserve_entry=False)
        elif key == "a":
            self._add_feed_flow()
        elif key == "M":
            self.view = View.MANAGE
            self.manage_index = 0
        elif key == "esc" and self.scope is Scope.SEARCH:
            self.scope = Scope.ALL
            self.search_query = ""
            self.reload_all(preserve_entry=False)

    def _handle_navigation_key(self, key: Key) -> None:
        if key in {"q", "esc", "tab", "right"}:
            self.navigation_auto_return_at = None
            self.view = View.MAIN
        elif key in {"j", "down"}:
            self.navigation_auto_return_at = None
            self._move_sidebar(1)
        elif key in {"k", "up"}:
            self.navigation_auto_return_at = None
            self._move_sidebar(-1)
        elif key == "J":
            self._move_sidebar(1)
            self._schedule_navigation_auto_return()
        elif key == "K":
            self._move_sidebar(-1)
            self._schedule_navigation_auto_return()
        elif key == "enter":
            self.navigation_auto_return_at = None
            self.view = View.MAIN
        elif key == "X":
            self._toggle_current_folder()
        elif key == "g":
            self._move_sidebar_to(0)
        elif key == "G":
            self._move_sidebar_to(len(self.sidebar_items) - 1)

    def _handle_manage_key(self, key: Key) -> None:
        if key in {"q", "esc"}:
            self.view = View.MAIN
            self.reload_all()
        elif key == "tab":
            self.manage_tab = (
                ManageTab.FOLDERS if self.manage_tab is ManageTab.FEEDS else ManageTab.FEEDS
            )
            self.manage_index = 0
        elif key in {"j", "down"}:
            self.manage_index += 1
        elif key in {"k", "up"}:
            self.manage_index = max(0, self.manage_index - 1)
        elif key == "/" and self.manage_tab is ManageTab.FEEDS:
            query = self.prompt("フィード検索", self.manage_query)
            if query is not None:
                self.manage_query = query.strip()
                self.manage_index = 0
        elif key == "F" and self.manage_tab is ManageTab.FEEDS:
            self.view = View.FOLDER_FILTER
            self.folder_filter_index = 0
        elif key == "a":
            if self.manage_tab is ManageTab.FEEDS:
                self._add_feed_flow()
            else:
                self._create_folder_flow()
        elif key in {"e", "enter"}:
            if self.manage_tab is ManageTab.FEEDS:
                if key == "enter":
                    self._change_feed_folder_flow()
                else:
                    self._edit_feed_title_flow()
            else:
                self._rename_folder_flow()
        elif key == "d":
            if self.manage_tab is ManageTab.FEEDS:
                self._delete_feed_flow()
            else:
                self._delete_folder_flow()
        elif key == "y" and self.manage_tab is ManageTab.FEEDS:
            self._copy_feed_url()

    def _handle_folder_filter_key(self, key: Key) -> None:
        choices = self._folder_filter_choices()
        if key in {"q", "esc"}:
            self.view = View.MANAGE
        elif key in {"j", "down"}:
            self.folder_filter_index = min(len(choices) - 1, self.folder_filter_index + 1)
        elif key in {"k", "up"}:
            self.folder_filter_index = max(0, self.folder_filter_index - 1)
        elif key == "a":
            self.manage_folder_filter = None
        elif key == "n":
            self.manage_folder_filter = set()
        elif key == " ":
            value = choices[self.folder_filter_index].value
            if self.manage_folder_filter is None:
                self.manage_folder_filter = {c.value or "__orphan" for c in choices}
            token = value or "__orphan"
            if token in self.manage_folder_filter:
                self.manage_folder_filter.remove(token)
            else:
                self.manage_folder_filter.add(token)
        elif key == "enter":
            self.manage_index = 0
            self.view = View.MANAGE

    def _handle_choice_key(self, key: Key) -> None:
        if key in {"q", "esc", "tab"}:
            self.view = self.choice_return_view
        elif key in {"j", "down"}:
            if self.choices:
                self.choice_index = min(len(self.choices) - 1, self.choice_index + 1)
        elif key in {"k", "up"}:
            if self.choices:
                self.choice_index = (
                    len(self.choices) - 1
                    if self.choice_index < 0
                    else max(0, self.choice_index - 1)
                )
        elif key == "enter":
            if not (0 <= self.choice_index < len(self.choices)):
                self.status = "項目を選択してください"
                self.status_error = True
                return
            choice = self.choices[self.choice_index]
            callback = self.choice_callback
            self.view = self.choice_return_view
            if callable(callback):
                callback(choice.value)

    def _move_entry(self, delta: int, *, expand: bool) -> None:
        if not self.entries:
            return
        idx = 0 if self.entry_index < 0 else self.entry_index + delta
        self._select_entry(idx, expand=expand)

    def _select_entry(self, idx: int, *, expand: bool) -> None:
        if not self.entries:
            return
        self.entry_index = max(0, min(len(self.entries) - 1, idx))
        if expand:
            entry = self.selected_entry()
            self.expanded_entry_id = entry.id if entry else None
            self.expanded_at = time.monotonic()

    def _toggle_expand(self) -> None:
        entry = self.selected_entry()
        if not entry:
            return
        if self.expanded_entry_id == entry.id:
            self.expanded_entry_id = None
            self.expanded_at = None
        else:
            self.expanded_entry_id = entry.id
            self.expanded_at = time.monotonic()

    def _toggle_read(self) -> None:
        entry = self.selected_entry()
        if not entry:
            return
        next_value = not entry.is_read
        repo.mark_read(self.conn, entry.id, next_value)
        self._replace_entry(entry.id, is_read=next_value)
        self.reload_sidebar()

    def _toggle_star(self) -> None:
        entry = self.selected_entry()
        if not entry:
            return
        next_value = repo.toggle_star(self.conn, entry.id)
        self._replace_entry(entry.id, is_starred=next_value)
        self.reload_sidebar()

    def _open_original(self) -> None:
        entry = self.selected_entry()
        if entry and entry.url:
            webbrowser.open(entry.url)
            self.status = "ブラウザで開きました"
            self.status_error = False

    def _replace_entry(
        self,
        entry_id: str,
        *,
        is_read: bool | None = None,
        is_starred: bool | None = None,
    ) -> None:
        for i, entry in enumerate(self.entries):
            if entry.id == entry_id:
                self.entries[i] = replace(
                    entry,
                    is_read=entry.is_read if is_read is None else is_read,
                    is_starred=entry.is_starred if is_starred is None else is_starred,
                )
                return

    def _move_sidebar(self, delta: int) -> None:
        self._move_sidebar_to(self.sidebar_index + delta)

    def _move_sidebar_to(self, index: int) -> None:
        if not self.sidebar_items:
            return
        self.sidebar_index = max(0, min(len(self.sidebar_items) - 1, index))
        item = self.sidebar_items[self.sidebar_index]
        if item.kind in {Scope.ALL, Scope.STARRED, Scope.FOLDER, Scope.FEED}:
            self.scope = cast(Scope, item.kind)
            self.current_folder_id = item.id if item.kind is Scope.FOLDER else None
            self.current_feed_id = item.id if item.kind is Scope.FEED else None
            self.search_query = ""
            self.expanded_entry_id = None
            self.expanded_at = None
            self.entry_index = -1
            self.entry_top = 0
            self.reload_entries()

    def _toggle_current_folder(self) -> None:
        item = self.sidebar_items[self.sidebar_index] if self.sidebar_items else None
        folder_id: str | None = None
        current_open = True
        if item and item.kind is Scope.FOLDER and item.id:
            folder_id = item.id
            current_open = item.open
        elif item and item.kind is Scope.FEED and item.id:
            feed = repo.get_feed(self.conn, item.id)
            folder_id = feed.folder_id if feed else None
            current_open = self.state.folder_open.get(folder_id, True) if folder_id else True
        if folder_id is None:
            return
        self.state.folder_open[folder_id] = not self.state.folder_open.get(folder_id, current_open)
        self.state.save(self.config.state_path)
        self.reload_sidebar()

    def _mark_current_scope_read(self) -> None:
        if self.scope is Scope.FEED and self.current_feed_id:
            repo.mark_scope_read(self.conn, scope=repo.ReadScope.FEED, feed_id=self.current_feed_id)
        elif self.scope is Scope.FOLDER and self.current_folder_id:
            repo.mark_scope_read(
                self.conn, scope=repo.ReadScope.FOLDER, folder_id=self.current_folder_id
            )
        else:
            self.status = "一括既読はフィード/フォルダ選択時のみ使えます"
            self.status_error = True
            return
        self.status = "一括既読にしました"
        self.status_error = False
        self.reload_all(preserve_entry=False)

    def _schedule_navigation_auto_return(self) -> None:
        self.navigation_auto_return_at = time.monotonic() + 0.45

    def _auto_return_navigation(self) -> None:
        if self.view is not View.NAVIGATION or self.navigation_auto_return_at is None:
            return
        if time.monotonic() >= self.navigation_auto_return_at:
            self.navigation_auto_return_at = None
            self.view = View.MAIN

    def _auto_mark_read(self) -> None:
        if not self.expanded_entry_id or self.expanded_at is None:
            return
        if time.monotonic() - self.expanded_at < 1.0:
            return
        entry = self.selected_entry()
        if entry and entry.id == self.expanded_entry_id and not entry.is_read:
            repo.mark_read(self.conn, entry.id, True)
            self._replace_entry(entry.id, is_read=True)
            self.expanded_at = None
            self.reload_sidebar()

    def _drain_sync_events(self) -> None:
        for event in self.worker.poll_events():
            self.status = event.error or event.message
            self.status_error = event.error is not None
            self.last_sync_at = datetime.now().astimezone()
            self.reload_all()

    def _open_folder_selector_flow(self) -> None:
        folders = repo.list_folders(self.conn)
        feeds = repo.list_feeds(self.conn)
        tree, orphan_feeds, _orphan_unread = repo.build_sidebar_tree(folders, feeds)
        choices = [
            Choice("すべて", "all"),
            Choice("★ スター", "starred"),
        ]

        def feed_label(feed: FeedListItem, depth: int) -> str:
            badge = f" {feed.unread_count}" if feed.unread_count else ""
            return f"{'  ' * depth}  {feed.title}{badge}"

        def add_folder(node: FolderTreeNode, depth: int) -> None:
            badge = f" {node.unread_count}" if node.unread_count else ""
            choices.append(Choice(f"{'  ' * depth}▾ {node.name}{badge}", f"folder:{node.id}"))
            for child in node.children:
                add_folder(child, depth + 1)
            for feed in node.feeds:
                choices.append(Choice(feed_label(feed, depth + 1), f"feed:{feed.id}"))

        for node in tree:
            add_folder(node, 0)
        for feed in orphan_feeds:
            choices.append(Choice(feed_label(feed, 0), f"feed:{feed.id}"))

        self.choices = choices
        self.choice_title = "フォルダ/フィード選択"
        self.choice_index = -1

        def finish(value: str | None) -> None:
            if value is None:
                return
            self.current_folder_id = None
            self.current_feed_id = None
            self.search_query = ""
            self.expanded_entry_id = None
            self.expanded_at = None
            self.entry_index = -1
            self.entry_top = 0
            if value == "all":
                self.scope = Scope.ALL
            elif value == "starred":
                self.scope = Scope.STARRED
            elif value.startswith("folder:"):
                self.scope = Scope.FOLDER
                self.current_folder_id = value.removeprefix("folder:")
            elif value.startswith("feed:"):
                self.scope = Scope.FEED
                self.current_feed_id = value.removeprefix("feed:")
            self.reload_all(preserve_entry=False)

        self.choice_callback = finish
        self.choice_return_view = self.view
        self.view = View.CHOOSE_FOLDER

    def _add_feed_flow(self) -> None:
        url = self.prompt("フィードURL")
        if not url:
            return
        folders = repo.list_folders(self.conn)
        self.choices = [
            Choice("(未分類)", ""),
            *[Choice(f.name, f.id) for f in folders],
            Choice("+ 新しいフォルダ", "__new"),
        ]
        self.choice_title = "追加先フォルダ"
        self.choice_index = -1

        def finish(value: str | None) -> None:
            new_folder_name: str | None = None
            folder_id = value or None
            if value == "__new":
                new_folder_name = self.prompt("新しいフォルダ名")
                if not new_folder_name:
                    return
                folder_id = "__new"
            try:
                self.feed_usecases.create_feed(
                    url=url, folder_id=folder_id, new_folder_name=new_folder_name
                )
            except ApplicationError as e:
                self.status = e.message
                self.status_error = True
            else:
                self.status = "フィードを追加しました"
                self.status_error = False
                self.reload_all(preserve_entry=False)

        self.choice_callback = finish
        self.choice_return_view = self.view
        self.view = View.CHOOSE_FOLDER

    def _create_folder_flow(self) -> None:
        name = self.prompt("フォルダ名")
        if not name:
            return
        try:
            self.folder_usecases.create_folder(name)
        except ApplicationError as e:
            self.status = e.message
            self.status_error = True
        else:
            self.status = "フォルダを追加しました"
            self.status_error = False
            self.reload_all(preserve_entry=False)

    def _rename_folder_flow(self) -> None:
        folder = self._selected_manage_folder()
        if not folder:
            return
        name = self.prompt("フォルダ名", folder.name)
        if name is None:
            return
        try:
            self.folder_usecases.rename_folder(folder.id, name)
        except ApplicationError as e:
            self.status = e.message
            self.status_error = True
        else:
            self.status = "フォルダ名を変更しました"
            self.status_error = False
            self.reload_all()

    def _delete_folder_flow(self) -> None:
        folder = self._selected_manage_folder()
        if not folder:
            return
        mode = "detach"
        if folder.feed_count:
            answer = self.prompt(
                f"{folder.name} を削除: d=フィードを未分類へ移動 / c=中のフィードも削除", "d"
            )
            if answer not in {"d", "c"}:
                return
            mode = "cascade" if answer == "c" else "detach"
        elif not self.confirm(f"{folder.name} を削除しますか?"):
            return
        self.folder_usecases.delete_folder(folder.id, mode)
        self.status = "フォルダを削除しました"
        self.status_error = False
        self.reload_all(preserve_entry=False)

    def _edit_feed_title_flow(self) -> None:
        feed = self._selected_manage_feed()
        if not feed:
            return
        title = self.prompt("フィード名", feed.title)
        if title is None:
            return
        self.feed_usecases.edit_feed(feed.id, title=title)
        self.status = "フィード名を変更しました"
        self.status_error = False
        self.reload_all()

    def _change_feed_folder_flow(self) -> None:
        feed = self._selected_manage_feed()
        if not feed:
            return
        folders = repo.list_folders(self.conn)
        self.choices = [Choice("(未分類)", "__none"), *[Choice(f.name, f.id) for f in folders]]
        self.choice_title = f"{feed.title} のフォルダ"
        self.choice_index = -1

        def finish(value: str | None) -> None:
            if value is None:
                return
            self.feed_usecases.edit_feed(feed.id, folder_id=value)
            self.status = "フィードのフォルダを変更しました"
            self.status_error = False
            self.reload_all()

        self.choice_callback = finish
        self.choice_return_view = self.view
        self.view = View.CHOOSE_FOLDER

    def _delete_feed_flow(self) -> None:
        feed = self._selected_manage_feed()
        if not feed:
            return
        if not self.confirm(f"{feed.title} を削除しますか?"):
            return
        self.feed_usecases.delete_feed(feed.id)
        self.status = "フィードを削除しました"
        self.status_error = False
        self.reload_all(preserve_entry=False)

    def _copy_feed_url(self) -> None:
        feed = self._selected_manage_feed()
        if not feed:
            return
        encoded = base64.b64encode(feed.url.encode()).decode()
        self.term.write(f"\x1b]52;c;{encoded}\x07")
        self.status = "URLをクリップボードへコピーしました (端末対応時)"
        self.status_error = False

    def _selected_manage_feed(self) -> FeedListItem | None:
        feeds = self._manage_feeds()
        if 0 <= self.manage_index < len(feeds):
            return feeds[self.manage_index]
        return None

    def _selected_manage_folder(self) -> FolderWithCount | None:
        folders = repo.list_folders_with_counts(self.conn)
        if 0 <= self.manage_index < len(folders):
            return folders[self.manage_index]
        return None

    def _manage_feeds(self) -> list[FeedListItem]:
        folder_ids: list[str] | None = None
        include_orphan = False
        if self.manage_folder_filter is not None:
            folder_ids = [f for f in self.manage_folder_filter if f != "__orphan"]
            include_orphan = "__orphan" in self.manage_folder_filter
        return repo.list_feeds_filtered(
            self.conn,
            query=self.manage_query,
            folder_ids=folder_ids,
            include_orphan=include_orphan,
        )

    def _folder_filter_choices(self) -> list[Choice]:
        return [
            Choice("未分類", "__orphan"),
            *[Choice(f.name, f.id) for f in repo.list_folders(self.conn)],
        ]

    def _filter_label(self) -> str:
        if self.manage_folder_filter is None:
            return "すべて"
        if not self.manage_folder_filter:
            return "なし"
        return f"{len(self.manage_folder_filter)}件"

    def prompt(self, label: str, initial: str = "") -> str | None:
        value = initial
        while True:
            size = self.term.size()
            self.render()
            prompt = f"{label}: {value}"
            self.term.write(f"\x1b[{size.rows};1H\x1b[K{prompt}")
            key = self.term.read_key(None)
            if key in {"esc", "ctrl_c"}:
                return None
            if key == "enter":
                return value
            if key == "backspace":
                value = value[:-1]
            elif key and len(key) == 1 and key >= " ":
                value += key

    def confirm(self, label: str) -> bool:
        answer = self.prompt(label + " [y/N]", "")
        return answer in {"y", "Y"}

    def _wrap(self, text: str, width: int) -> list[str]:
        width = max(10, width)
        lines: list[str] = []
        for para in text.splitlines():
            if not para:
                lines.append("")
                continue
            lines.extend(textwrap.wrap(para, width=width, replace_whitespace=False) or [""])
        return lines

    def _fit(self, text: str, width: int) -> str:
        clean_width = self._visible_len(text)
        if clean_width <= width:
            return text + " " * (width - clean_width)
        # ANSI-aware truncation is intentionally simple: style codes are only used around whole rows.
        plain = self._strip_ansi(text)
        if self._visible_len(plain) <= width:
            return plain
        return self._clip_text(plain, width)

    def _clip_text(self, text: str, width: int) -> str:
        if width <= 0:
            return ""
        if self._visible_len(text) <= width:
            return text
        out = ""
        current = 0
        for ch in text:
            w = 2 if self._is_wide(ch) else 1
            if current + w > max(0, width - 1):
                break
            out += ch
            current += w
        return out + "…"

    def _ensure_visible(self, index: int, top: int, rows: int) -> int:
        if index < top:
            return index
        if index >= top + rows:
            return index - rows + 1
        return top

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @classmethod
    def _visible_len(cls, text: str) -> int:
        return sum(2 if cls._is_wide(ch) else 1 for ch in cls._strip_ansi(text))

    @staticmethod
    def _is_wide(ch: str) -> bool:
        import unicodedata

        return unicodedata.east_asian_width(ch) in {"F", "W"}


def main() -> None:
    RssxTui().run()
