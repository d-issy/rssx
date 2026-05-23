import asyncio
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import queries as q
from .config import Config
from .db import connect, init_schema
from .fetcher import (
    FetchConfig,
    fetch_all,
    fetch_due_feeds,
    fetch_feed,
    probe_feed_title,
)

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DEV_MODE = bool(os.environ.get("RSSX_DEV"))
TEMPLATES.env.globals["dev_mode"] = DEV_MODE


def _resolve_tz(name: str):
    if name == "local":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning("unknown timezone %r, falling back to system local", name)
        return datetime.now().astimezone().tzinfo


def _parse_stored(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def _make_filters(tz):
    def iso_utc(value: str | None) -> str:
        dt = _parse_stored(value)
        if dt is None:
            return ""
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def fmt_dt(value: str | None) -> str:
        dt = _parse_stored(value)
        if dt is None:
            return ""
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    return iso_utc, fmt_dt


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    iso_utc, fmt_dt = _make_filters(_resolve_tz(config.timezone))
    TEMPLATES.env.filters["iso_utc"] = iso_utc
    TEMPLATES.env.filters["fmt_dt"] = fmt_dt
    conn = connect(config.db_path)
    init_schema(conn)

    fetch_cfg = FetchConfig(
        min_interval_sec=config.min_interval_min * 60,
        max_interval_sec=config.max_interval_min * 60,
        initial_interval_sec=config.initial_interval_min * 60,
    )

    scheduler = AsyncIOScheduler()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            fetch_all(conn, fetch_cfg)
        except Exception:
            log.exception("startup fetch failed")
        scheduler.add_job(
            lambda: fetch_due_feeds(conn, fetch_cfg),
            "interval",
            seconds=config.scheduler_tick_min * 60,
            id="rssx-poll",
        )
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            conn.close()

    app = FastAPI(lifespan=lifespan, title="rssx")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def render_index(request: Request, scope_args: dict, entries):
        folders = q.list_folders(conn)
        feeds = q.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = q.build_sidebar_tree(folders, feeds)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "folder_tree": folder_tree,
                "orphan_feeds": orphan_feeds,
                "orphan_unread": orphan_unread,
                "entries": entries,
                "unread_total": q.get_unread_total(conn),
                "starred_total": q.get_starred_total(conn),
                **scope_args,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        scope: str = "all",
        folder: int | None = None,
        feed: int | None = None,
        unread: int = 1,
    ):
        entries = q.list_entries(
            conn,
            scope=scope,
            folder_id=folder,
            feed_id=feed,
            unread_only=bool(unread),
        )
        return render_index(
            request,
            {
                "scope": scope,
                "current_folder_id": folder,
                "current_feed_id": feed,
                "unread_only": bool(unread),
                "query": "",
            },
            entries,
        )

    @app.get("/entries/{entry_id}", response_class=HTMLResponse)
    def entry_body(request: Request, entry_id: int):
        entry = q.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(request, "_entry_body.html", {"entry": entry})

    @app.post("/entries/{entry_id}/read", response_class=HTMLResponse)
    def entry_read(request: Request, entry_id: int, value: int = 1):
        q.mark_read(conn, entry_id, bool(value))
        entry = q.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        resp = TEMPLATES.TemplateResponse(request, "_entry_row.html", {"entry": entry})
        resp.headers["HX-Trigger"] = "rssx:counts-changed"
        return resp

    @app.post("/entries/{entry_id}/star", response_class=HTMLResponse)
    def entry_star(request: Request, entry_id: int):
        q.toggle_star(conn, entry_id)
        entry = q.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        resp = TEMPLATES.TemplateResponse(request, "_entry_row.html", {"entry": entry})
        resp.headers["HX-Trigger"] = "rssx:counts-changed"
        return resp

    @app.get("/sidebar", response_class=HTMLResponse)
    def sidebar(
        request: Request,
        scope: str = "all",
        folder: int | None = None,
        feed: int | None = None,
    ):
        folders = q.list_folders(conn)
        feeds = q.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = q.build_sidebar_tree(folders, feeds)
        return TEMPLATES.TemplateResponse(
            request,
            "_sidebar.html",
            {
                "folder_tree": folder_tree,
                "orphan_feeds": orphan_feeds,
                "orphan_unread": orphan_unread,
                "unread_total": q.get_unread_total(conn),
                "starred_total": q.get_starred_total(conn),
                "scope": scope,
                "current_folder_id": folder,
                "current_feed_id": feed,
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, query: Annotated[str, Query(alias="q")] = ""):
        query = query.strip()
        rows = q.search_entries(conn, query) if query else []
        return render_index(
            request,
            {
                "scope": "search",
                "current_folder_id": None,
                "current_feed_id": None,
                "unread_only": False,
                "query": query,
            },
            rows,
        )

    @app.post("/refresh")
    def refresh_all():
        fetch_all(conn, fetch_cfg)
        return RedirectResponse("/", status_code=303)

    @app.post("/refresh/feed/{feed_id}")
    def refresh_one(feed_id: int):
        fetch_feed(conn, feed_id, fetch_cfg)
        return RedirectResponse("/", status_code=303)

    def _is_htmx(request: Request) -> bool:
        return request.headers.get("HX-Request") == "true"

    def _render_feed_list(request: Request, feeds, folders):
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_feed_list.html",
            {"feeds": feeds, "folders": folders},
        )

    def _render_feed_row(request: Request, feed_id: int):
        feed = q.get_feed(conn, feed_id)
        if not feed:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_feed_row.html",
            {"feed": feed, "folders": q.list_folders(conn)},
        )

    def _render_folder_row(request: Request, folder_id: int):
        folder = q.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_folder_row.html",
            {"f": folder},
        )

    def _trigger(resp, *events: str):
        # Use JSON object form so multiple events with colons in names (eg.
        # "rssx:counts-changed") are parsed unambiguously by HTMX. Merges with
        # any existing HX-Trigger header (also assumed JSON).
        merged: dict[str, None] = {}
        existing = resp.headers.get("HX-Trigger")
        if existing:
            try:
                parsed = json.loads(existing)
                if isinstance(parsed, dict):
                    for k in parsed:
                        merged[k] = None
            except json.JSONDecodeError:
                for name in existing.split(","):
                    name = name.strip()
                    if name:
                        merged[name] = None
        for e in events:
            merged[e] = None
        resp.headers["HX-Trigger"] = json.dumps(merged)
        return resp

    def _trigger_sidebar(resp):
        return _trigger(resp, "rssx:counts-changed")

    @app.get("/manage", response_class=HTMLResponse)
    def manage(request: Request):
        feeds = q.list_feeds_filtered(conn)
        ctx = {
            "folders": q.list_folders_with_counts(conn),
            "feeds": feeds,
        }
        template = "_manage_dialog.html" if _is_htmx(request) else "manage.html"
        return TEMPLATES.TemplateResponse(request, template, ctx)

    @app.get("/manage/folders", response_class=HTMLResponse)
    def manage_folders(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_folder_list.html",
            {"folders": q.list_folders_with_counts(conn)},
        )

    @app.get("/manage/feeds", response_class=HTMLResponse)
    def manage_feeds(
        request: Request,
        q_: Annotated[str, Query(alias="q")] = "",
        folders: Annotated[list[str] | None, Query()] = None,
    ):
        if folders is None:
            feeds = q.list_feeds_filtered(conn, query=q_)
        else:
            folder_ids: list[int] = []
            include_orphan = False
            for v in folders:
                if v == "__orphan":
                    include_orphan = True
                else:
                    try:
                        folder_ids.append(int(v))
                    except ValueError:
                        continue
            feeds = q.list_feeds_filtered(
                conn, query=q_, folder_ids=folder_ids, include_orphan=include_orphan
            )
        return _render_feed_list(request, feeds, q.list_folders(conn))

    @app.get("/add-feed", response_class=HTMLResponse)
    def add_feed_form(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "_add_feed_dialog.html",
            {"folders": q.list_folders(conn)},
        )

    @app.post("/folders")
    def folder_create(
        request: Request,
        name: Annotated[str, Form()],
    ):
        if not name.strip():
            raise HTTPException(400, "name required")
        q.add_folder(conn, name, None)
        if _is_htmx(request):
            return _trigger_sidebar(
                TEMPLATES.TemplateResponse(
                    request,
                    "_manage_folder_list.html",
                    {"folders": q.list_folders_with_counts(conn)},
                )
            )
        return RedirectResponse("/manage", status_code=303)

    @app.post("/folders/{folder_id}/rename", response_class=HTMLResponse)
    def folder_rename(
        request: Request,
        folder_id: int,
        name: Annotated[str, Form()],
    ):
        if not name.strip():
            raise HTTPException(400, "name required")
        q.rename_folder(conn, folder_id, name)
        if _is_htmx(request):
            return _trigger_sidebar(_render_folder_row(request, folder_id))
        return RedirectResponse("/manage", status_code=303)

    @app.post("/folders/{folder_id}/delete")
    def folder_delete(
        request: Request,
        folder_id: int,
        mode: Annotated[str, Form()] = "detach",
    ):
        if mode == "cascade":
            q.delete_folder_cascade(conn, folder_id)
        else:
            q.delete_folder(conn, folder_id)
        if _is_htmx(request):
            resp = HTMLResponse("")
            _trigger(resp, "rssx:counts-changed", "rssx:folder-changed")
            return resp
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds")
    def feed_create(
        request: Request,
        url: Annotated[str, Form()],
        title: Annotated[str, Form()] = "",
        folder_id: Annotated[str | None, Form()] = None,
        new_folder_name: Annotated[str | None, Form()] = None,
    ):
        url = url.strip()
        if not url:
            raise HTTPException(400, "URL を入力してください")

        existing = conn.execute("SELECT id, title FROM feeds WHERE url = ?", (url,)).fetchone()
        if existing:
            raise HTTPException(400, f"このURLは既に登録されています: {existing['title']}")

        site_url: str | None = None
        if not title.strip():
            try:
                title, site_url = probe_feed_title(url)
            except Exception as e:
                raise HTTPException(400, f"フィードを読み込めませんでした: {e}") from e

        # Resolve target folder. If __new, defer creation until *after* the
        # feed insert succeeds so a duplicate-URL failure cannot leave behind
        # an orphan empty folder.
        new_folder_request: str | None = None
        target_folder_id: int | None = None
        if folder_id == "__new":
            new_folder_request = (new_folder_name or "").strip()
            if not new_folder_request:
                raise HTTPException(400, "新しいフォルダ名を入力してください")
        elif folder_id and folder_id != "":
            try:
                target_folder_id = int(folder_id)
            except ValueError:
                target_folder_id = None

        try:
            feed_id = q.add_feed(
                conn, url=url, title=title, site_url=site_url, folder_id=target_folder_id
            )
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, "このURLは既に登録されています") from e

        if new_folder_request is not None:
            target_folder_id = q.add_folder(conn, new_folder_request, None)
            q.update_feed_folder(conn, feed_id, target_folder_id)
        try:
            fetch_feed(conn, feed_id, fetch_cfg)
        except Exception:
            log.exception("initial fetch failed for new feed %s", url)
        if _is_htmx(request):
            resp = HTMLResponse("", status_code=204)
            _trigger(
                resp,
                "rssx:feed-added",
                "rssx:counts-changed",
                "rssx:feed-folder-changed",
            )
            return resp
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds/{feed_id}/delete")
    def feed_delete(request: Request, feed_id: int):
        q.delete_feed(conn, feed_id)
        if _is_htmx(request):
            resp = HTMLResponse("")
            _trigger(resp, "rssx:counts-changed", "rssx:feed-folder-changed")
            return resp
        return RedirectResponse("/manage", status_code=303)

    if DEV_MODE:

        @app.get("/__dev/ping")
        async def dev_ping():
            async def gen():
                yield ": connected\n\n"
                while True:
                    await asyncio.sleep(15)
                    yield ": ping\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/feeds/{feed_id}/edit", response_class=HTMLResponse)
    def feed_edit(
        request: Request,
        feed_id: int,
        title: Annotated[str | None, Form()] = None,
        folder_id: Annotated[str, Form()] = "__unchanged",
    ):
        folder_changed = False
        if title is not None:
            q.update_feed_title(conn, feed_id, title)
        if folder_id != "__unchanged":
            new_folder = None if folder_id == "__none" else int(folder_id)
            q.update_feed_folder(conn, feed_id, new_folder)
            folder_changed = True
        if _is_htmx(request):
            resp = _render_feed_row(request, feed_id)
            _trigger(resp, "rssx:counts-changed")
            if folder_changed:
                _trigger(resp, "rssx:feed-folder-changed")
            return resp
        return RedirectResponse("/manage", status_code=303)

    return app
