from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    conn = connect(config.db_path)
    init_schema(conn)

    fetch_cfg = FetchConfig(
        min_interval_sec=config.min_interval_sec,
        max_interval_sec=config.max_interval_sec,
        initial_interval_sec=config.initial_interval_sec,
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
            seconds=config.scheduler_tick_sec,
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
        folder_tree = q.build_folder_tree(folders)
        feeds = q.list_feeds(conn)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "folder_tree": folder_tree,
                "feeds": feeds,
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
    def sidebar(request: Request):
        folders = q.list_folders(conn)
        return TEMPLATES.TemplateResponse(
            request,
            "_sidebar.html",
            {
                "folder_tree": q.build_folder_tree(folders),
                "feeds": q.list_feeds(conn),
                "unread_total": q.get_unread_total(conn),
                "starred_total": q.get_starred_total(conn),
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

    @app.get("/manage", response_class=HTMLResponse)
    def manage(request: Request):
        folders = q.list_folders(conn)
        return TEMPLATES.TemplateResponse(
            request,
            "manage.html",
            {
                "folders": folders,
                "folder_tree": q.build_folder_tree(folders),
                "feeds": q.list_feeds(conn),
            },
        )

    @app.post("/folders")
    def folder_create(
        name: Annotated[str, Form()],
        parent_id: Annotated[int | None, Form()] = None,
    ):
        if not name.strip():
            raise HTTPException(400, "name required")
        q.add_folder(conn, name, parent_id)
        return RedirectResponse("/manage", status_code=303)

    @app.post("/folders/{folder_id}/delete")
    def folder_delete(folder_id: int):
        q.delete_folder(conn, folder_id)
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds")
    def feed_create(
        url: Annotated[str, Form()],
        title: Annotated[str, Form()] = "",
        folder_id: Annotated[int | None, Form()] = None,
    ):
        url = url.strip()
        if not url:
            raise HTTPException(400, "url required")
        site_url: str | None = None
        if not title.strip():
            try:
                title, site_url = probe_feed_title(url)
            except Exception as e:
                raise HTTPException(400, f"could not load feed: {e}") from e
        feed_id = q.add_feed(conn, url=url, title=title, site_url=site_url, folder_id=folder_id)
        try:
            fetch_feed(conn, feed_id, fetch_cfg)
        except Exception:
            log.exception("initial fetch failed for new feed %s", url)
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds/{feed_id}/delete")
    def feed_delete(feed_id: int):
        q.delete_feed(conn, feed_id)
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds/{feed_id}/edit")
    def feed_edit(
        feed_id: int,
        title: Annotated[str | None, Form()] = None,
        folder_id: Annotated[str | None, Form()] = None,
    ):
        if title is not None:
            q.update_feed_title(conn, feed_id, title)
        if folder_id is not None:
            new_folder = int(folder_id) if folder_id != "" else None
            q.update_feed_folder(conn, feed_id, new_folder)
        return RedirectResponse("/manage", status_code=303)

    return app
