import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import repository as repo
from .config import Config
from .db import connect, init_schema
from .lib.feeds.scheduling import FetchConfig
from .lib.htmx import add_trigger, is_htmx
from .usecases.feed_sync import fetch_all, fetch_due_feeds, fetch_feed
from .usecases.manage import ManageUseCases
from .usecases.results import ApplicationError

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DEV_MODE = bool(os.environ.get("RSSX_DEV"))
TEMPLATES.env.globals["dev_mode"] = DEV_MODE


@dataclass(frozen=True)
class IndexScope:
    scope: str
    current_folder_id: int | None
    current_feed_id: int | None
    unread_only: bool
    query: str


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


def create_app(config: Config | None = None, *, run_startup_fetch: bool = True) -> FastAPI:
    config = config or Config.load()
    iso_utc, fmt_dt = _make_filters(_resolve_tz(config.timezone))
    TEMPLATES.env.filters["iso_utc"] = iso_utc
    TEMPLATES.env.filters["fmt_dt"] = fmt_dt
    conn = connect(config.db_path)
    init_schema(conn)

    fetch_cfg = FetchConfig(
        min_interval_min=config.min_interval_min,
        max_interval_min=config.max_interval_min,
        initial_interval_min=config.initial_interval_min,
    )

    scheduler = AsyncIOScheduler()
    manage_usecases = ManageUseCases(conn, fetch_cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_startup_fetch:
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

    def render_index(
        request: Request, scope_args: IndexScope, entries: list[sqlite3.Row]
    ) -> HTMLResponse:
        folders = repo.list_folders(conn)
        feeds = repo.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(folders, feeds)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "folder_tree": folder_tree,
                "orphan_feeds": orphan_feeds,
                "orphan_unread": orphan_unread,
                "entries": entries,
                "unread_total": repo.get_unread_total(conn),
                "starred_total": repo.get_starred_total(conn),
                **asdict(scope_args),
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
        entries = repo.list_entries(
            conn,
            scope=scope,
            folder_id=folder,
            feed_id=feed,
            unread_only=bool(unread),
        )
        return render_index(
            request,
            IndexScope(
                scope=scope,
                current_folder_id=folder,
                current_feed_id=feed,
                unread_only=bool(unread),
                query="",
            ),
            entries,
        )

    @app.get("/entries/{entry_id}", response_class=HTMLResponse)
    def entry_body(request: Request, entry_id: int):
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(request, "_entry_body.html", {"entry": entry})

    @app.post("/entries/{entry_id}/read", response_class=HTMLResponse)
    def entry_read(request: Request, entry_id: int, value: int = 1):
        repo.mark_read(conn, entry_id, bool(value))
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        resp = TEMPLATES.TemplateResponse(request, "_entry_row.html", {"entry": entry})
        resp.headers["HX-Trigger"] = "rssx:counts-changed"
        return resp

    @app.post("/entries/{entry_id}/star", response_class=HTMLResponse)
    def entry_star(request: Request, entry_id: int):
        repo.toggle_star(conn, entry_id)
        entry = repo.get_entry(conn, entry_id)
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
        folders = repo.list_folders(conn)
        feeds = repo.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(folders, feeds)
        return TEMPLATES.TemplateResponse(
            request,
            "_sidebar.html",
            {
                "folder_tree": folder_tree,
                "orphan_feeds": orphan_feeds,
                "orphan_unread": orphan_unread,
                "unread_total": repo.get_unread_total(conn),
                "starred_total": repo.get_starred_total(conn),
                "scope": scope,
                "current_folder_id": folder,
                "current_feed_id": feed,
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, query: Annotated[str, Query(alias="q")] = ""):
        query = query.strip()
        rows = repo.search_entries(conn, query) if query else []
        return render_index(
            request,
            IndexScope(
                scope="search",
                current_folder_id=None,
                current_feed_id=None,
                unread_only=False,
                query=query,
            ),
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

    def _render_feed_list(request: Request, feeds, folders):
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_feed_list.html",
            {"feeds": feeds, "folders": folders},
        )

    def _render_feed_row(request: Request, feed_id: int):
        feed = repo.get_feed(conn, feed_id)
        if not feed:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_feed_row.html",
            {"feed": feed, "folders": repo.list_folders(conn)},
        )

    def _render_folder_row(request: Request, folder_id: int):
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_folder_row.html",
            {"f": folder},
        )

    def _http_error(e: ApplicationError) -> HTTPException:
        return HTTPException(e.status_code, e.message)

    @app.get("/manage", response_class=HTMLResponse)
    def manage(request: Request):
        feeds = repo.list_feeds_filtered(conn)
        ctx = {
            "folders": repo.list_folders_with_counts(conn),
            "feeds": feeds,
        }
        template = "_manage_dialog.html" if is_htmx(request) else "manage.html"
        return TEMPLATES.TemplateResponse(request, template, ctx)

    @app.get("/manage/folders", response_class=HTMLResponse)
    def manage_folders(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "_manage_folder_list.html",
            {"folders": repo.list_folders_with_counts(conn)},
        )

    @app.get("/manage/feeds", response_class=HTMLResponse)
    def manage_feeds(
        request: Request,
        q_: Annotated[str, Query(alias="q")] = "",
        folders: Annotated[list[str] | None, Query()] = None,
    ):
        if folders is None:
            feeds = repo.list_feeds_filtered(conn, query=q_)
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
            feeds = repo.list_feeds_filtered(
                conn, query=q_, folder_ids=folder_ids, include_orphan=include_orphan
            )
        return _render_feed_list(request, feeds, repo.list_folders(conn))

    @app.get("/add-feed", response_class=HTMLResponse)
    def add_feed_form(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "_add_feed_dialog.html",
            {"folders": repo.list_folders(conn)},
        )

    @app.post("/folders")
    def folder_create(
        request: Request,
        name: Annotated[str, Form()],
    ):
        try:
            result = manage_usecases.create_folder(name)
        except ApplicationError as e:
            raise _http_error(e) from e
        if is_htmx(request):
            resp = TEMPLATES.TemplateResponse(
                request,
                "_manage_folder_list.html",
                {"folders": repo.list_folders_with_counts(conn)},
            )
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    @app.post("/folders/{folder_id}/rename", response_class=HTMLResponse)
    def folder_rename(
        request: Request,
        folder_id: int,
        name: Annotated[str, Form()],
    ):
        try:
            result = manage_usecases.rename_folder(folder_id, name)
        except ApplicationError as e:
            raise _http_error(e) from e
        if is_htmx(request):
            resp = _render_folder_row(request, folder_id)
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    @app.post("/folders/{folder_id}/delete")
    def folder_delete(
        request: Request,
        folder_id: int,
        mode: Annotated[str, Form()] = "detach",
    ):
        result = manage_usecases.delete_folder(folder_id, mode)
        if is_htmx(request):
            resp = HTMLResponse("")
            add_trigger(resp, *result.events)
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
        try:
            result = manage_usecases.create_feed(
                url=url,
                title=title,
                folder_id=folder_id,
                new_folder_name=new_folder_name,
            )
        except ApplicationError as e:
            raise _http_error(e) from e
        if is_htmx(request):
            resp = HTMLResponse("", status_code=204)
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    @app.post("/feeds/{feed_id}/delete")
    def feed_delete(request: Request, feed_id: int):
        result = manage_usecases.delete_feed(feed_id)
        if is_htmx(request):
            resp = HTMLResponse("")
            add_trigger(resp, *result.events)
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
        result = manage_usecases.edit_feed(feed_id, title=title, folder_id=folder_id)
        if is_htmx(request):
            resp = _render_feed_row(request, feed_id)
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    return app
