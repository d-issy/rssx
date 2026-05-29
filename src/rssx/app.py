import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import repository as repo
from .config import Config
from .db import connect, init_schema
from .domain.errors import DomainError
from .domain.events import DomainEvent
from .domain.value_objects import FolderId
from .dto import EntryListItem
from .lib.env import is_dev_mode
from .lib.feeds.scheduling import FetchConfig
from .lib.htmx import add_trigger, is_htmx
from .lib.templates import create_templates
from .usecases.feed_sync import fetch_all, fetch_due_feeds, fetch_feed
from .usecases.manage_feeds import FeedManagementUseCases
from .usecases.manage_folders import FolderManagementUseCases
from .usecases.results import ApplicationError

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

IndexRenderScope = Literal["all", "starred", "orphan", "folder", "feed", "search"]


@dataclass(frozen=True)
class IndexScope:
    scope: IndexRenderScope
    current_folder_id: str | None
    current_feed_id: str | None
    unread_only: bool
    query: str


def create_app(config: Config | None = None, *, run_startup_fetch: bool = True) -> FastAPI:
    config = config or Config.load()
    templates = create_templates(BASE_DIR, timezone=config.timezone)
    conn = connect(config.db_path)
    init_schema(conn)

    fetch_cfg = FetchConfig(
        min_interval_min=config.min_interval_min,
        max_interval_min=config.max_interval_min,
        initial_interval_min=config.initial_interval_min,
    )

    scheduler = AsyncIOScheduler()
    feed_usecases = FeedManagementUseCases(conn, fetch_cfg)
    folder_usecases = FolderManagementUseCases(conn)

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
        request: Request,
        scope_args: IndexScope,
        entries: list[EntryListItem],
    ) -> HTMLResponse:
        folders = repo.list_folders(conn)
        feeds = repo.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(folders, feeds)
        return templates.TemplateResponse(
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
        scope: Annotated[repo.EntryScope, Query()] = "all",
        folder: str | None = None,
        feed: str | None = None,
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
    def entry_body(request: Request, entry_id: str):
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "_entry_body.html", {"entry": entry})

    @app.post("/entries/{entry_id}/read", response_class=HTMLResponse)
    def entry_read(request: Request, entry_id: str, value: int = 1):
        repo.mark_read(conn, entry_id, bool(value))
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        resp = templates.TemplateResponse(request, "_entry_row.html", {"entry": entry})
        resp.headers["HX-Trigger"] = "rssx:counts-changed"
        return resp

    @app.post("/entries/{entry_id}/star", response_class=HTMLResponse)
    def entry_star(request: Request, entry_id: str):
        repo.toggle_star(conn, entry_id)
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise HTTPException(404)
        resp = templates.TemplateResponse(request, "_entry_row.html", {"entry": entry})
        resp.headers["HX-Trigger"] = "rssx:counts-changed"
        return resp

    @app.post("/entries/read-scope")
    def entries_read_scope(
        scope: Annotated[repo.ReadScope, Query()],
        folder: Annotated[str | None, Query()] = None,
        feed: Annotated[str | None, Query()] = None,
    ):
        if scope == "folder" and folder is None:
            raise HTTPException(400)
        if scope == "feed" and feed is None:
            raise HTTPException(400)
        repo.mark_scope_read(conn, scope=scope, folder_id=folder, feed_id=feed)
        resp = Response(status_code=204)
        add_trigger(resp, DomainEvent.COUNTS_CHANGED)
        return resp

    @app.get("/sidebar", response_class=HTMLResponse)
    def sidebar(
        request: Request,
        scope: Annotated[IndexRenderScope, Query()] = "all",
        folder: str | None = None,
        feed: str | None = None,
    ):
        folders = repo.list_folders(conn)
        feeds = repo.list_feeds(conn)
        folder_tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(folders, feeds)
        return templates.TemplateResponse(
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
    def refresh_one(feed_id: str):
        fetch_feed(conn, feed_id, fetch_cfg)
        return RedirectResponse("/", status_code=303)

    def _render_feed_list(request: Request, feeds, folders):
        return templates.TemplateResponse(
            request,
            "_manage_feed_list.html",
            {"feeds": feeds, "folders": folders},
        )

    def _render_feed_row(request: Request, feed_id: str):
        feed = repo.get_feed(conn, feed_id)
        if not feed:
            raise HTTPException(404)
        return templates.TemplateResponse(
            request,
            "_manage_feed_row.html",
            {"feed": feed, "folders": repo.list_folders(conn)},
        )

    def _render_folder_row(request: Request, folder_id: str):
        folder = repo.get_folder(conn, folder_id)
        if not folder:
            raise HTTPException(404)
        return templates.TemplateResponse(
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
        return templates.TemplateResponse(request, template, ctx)

    @app.get("/manage/folders", response_class=HTMLResponse)
    def manage_folders(request: Request):
        return templates.TemplateResponse(
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
            folder_ids: list[str] = []
            include_orphan = False
            for v in folders:
                if v == "__orphan":
                    include_orphan = True
                    continue
                try:
                    folder_ids.append(FolderId.from_raw(v).value)
                except DomainError:
                    continue
            feeds = repo.list_feeds_filtered(
                conn, query=q_, folder_ids=folder_ids, include_orphan=include_orphan
            )
        return _render_feed_list(request, feeds, repo.list_folders(conn))

    @app.get("/add-feed", response_class=HTMLResponse)
    def add_feed_form(request: Request):
        return templates.TemplateResponse(
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
            result = folder_usecases.create_folder(name)
        except ApplicationError as e:
            raise _http_error(e) from e
        if is_htmx(request):
            resp = templates.TemplateResponse(
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
        folder_id: str,
        name: Annotated[str, Form()],
    ):
        try:
            result = folder_usecases.rename_folder(folder_id, name)
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
        folder_id: str,
        mode: Annotated[str, Form()] = "detach",
    ):
        result = folder_usecases.delete_folder(folder_id, mode)
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
            result = feed_usecases.create_feed(
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
    def feed_delete(request: Request, feed_id: str):
        result = feed_usecases.delete_feed(feed_id)
        if is_htmx(request):
            resp = HTMLResponse("")
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    if is_dev_mode():

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
        feed_id: str,
        title: Annotated[str | None, Form()] = None,
        folder_id: Annotated[str, Form()] = "__unchanged",
    ):
        result = feed_usecases.edit_feed(feed_id, title=title, folder_id=folder_id)
        if is_htmx(request):
            resp = _render_feed_row(request, feed_id)
            add_trigger(resp, *result.events)
            return resp
        return RedirectResponse("/manage", status_code=303)

    return app
