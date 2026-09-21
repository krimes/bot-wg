"""Веб-выдача первого AmneziaWG-конфига по общему паролю."""

from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from bot.access import format_person_label, listed_telegram_ids
from bot.config import Settings
from bot.db import Database
from bot.qrutil import qr_png
from bot.services.awg import AwgError, AwgService
from bot.services.wg_issue import IssueError, issue_first_web_wg

log = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def create_web_app(settings: Settings, db: Database, awg: AwgService) -> Starlette:
    secret = settings.web_secret or hashlib.sha256(
        f"{settings.web_password}|{settings.bot_token}".encode()
    ).hexdigest()

    async def login_get(request: Request) -> Response:
        if request.session.get("authed"):
            return RedirectResponse("/", status_code=303)
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})

    async def login_post(request: Request) -> Response:
        form = await request.form()
        password = str(form.get("password") or "")
        if not _password_ok(password, settings.web_password or ""):
            return TEMPLATES.TemplateResponse(
                request, "login.html",
                {"error": "Неверный пароль."},
                status_code=401,
            )
        request.session["authed"] = True
        return RedirectResponse("/", status_code=303)

    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    async def index(request: Request) -> Response:
        if not request.session.get("authed"):
            return RedirectResponse("/login", status_code=303)
        people = await _people(db, settings)
        return TEMPLATES.TemplateResponse(request, "issue.html", {
            "people": people,
            "error": None,
            "name": "",
            "selected": None,
            "can_generate": any(not p["has_wg"] for p in people),
        })

    async def generate(request: Request) -> Response:
        if not request.session.get("authed"):
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        raw_id = str(form.get("telegram_id") or "").strip()
        name = str(form.get("name") or "").strip()
        people = await _people(db, settings)
        ctx_extra = {
            "people": people,
            "name": name,
            "can_generate": any(not p["has_wg"] for p in people),
        }
        try:
            telegram_id = int(raw_id)
        except ValueError:
            return TEMPLATES.TemplateResponse(request, "issue.html", {
                **ctx_extra,
                "error": "Выберите пользователя из списка.",
                "selected": raw_id,
            }, status_code=400)
        try:
            issued = await issue_first_web_wg(
                db=db,
                awg=awg,
                admin_ids=settings.admin_ids,
                telegram_id=telegram_id,
                display_name=name,
            )
        except IssueError as exc:
            return TEMPLATES.TemplateResponse(request, "issue.html", {
                **ctx_extra,
                "error": exc.message,
                "selected": telegram_id,
            }, status_code=400)
        except AwgError as exc:
            log.exception("web wg issue failed")
            return TEMPLATES.TemplateResponse(request, "issue.html", {
                **ctx_extra,
                "error": f"Ошибка AmneziaWG: {exc}",
                "selected": telegram_id,
            }, status_code=500)

        import base64
        qr_b64 = base64.b64encode(qr_png(issued.conf)).decode()
        request.session["conf"] = issued.conf
        request.session["conf_name"] = issued.display_name
        return TEMPLATES.TemplateResponse(request, "result.html", {
            "name": issued.display_name,
            "telegram_id": telegram_id,
            "conf": issued.conf,
            "qr_b64": qr_b64,
            "filename": f"{issued.display_name}.conf",
        })

    async def download(request: Request) -> Response:
        if not request.session.get("authed"):
            return RedirectResponse("/login", status_code=303)
        conf = request.session.get("conf")
        name = request.session.get("conf_name") or "wg"
        if not conf:
            return RedirectResponse("/", status_code=303)
        filename = f"{name}.conf"
        return Response(
            conf,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    routes = [
        Route("/login", login_get, methods=["GET"]),
        Route("/login", login_post, methods=["POST"]),
        Route("/logout", logout, methods=["POST", "GET"]),
        Route("/", index, methods=["GET"]),
        Route("/generate", generate, methods=["POST"]),
        Route("/download", download, methods=["GET"]),
    ]
    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key=secret,
                session_cookie="awg_web",
                same_site="lax",
                https_only=False,
            ),
        ],
    )


def _password_ok(got: str, expected: str) -> bool:
    left = hashlib.sha256(got.encode()).digest()
    right = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(left, right)


async def _people(db: Database, settings: Settings) -> list[dict]:
    db_users = await db.list_bot_users()
    enabled = [u.telegram_id for u in db_users if u.enabled]
    ids = listed_telegram_ids(settings.admin_ids, enabled)
    rows: list[dict] = []
    for tid in ids:
        prof = await db.get_telegram_profile(tid)
        stored = await db.get_bot_user(tid)
        first = last = uname = None
        if prof:
            first, last, uname = prof.first_name, prof.last_name, prof.username
        elif stored:
            first, uname = stored.name, stored.username
        wg = await db.list_profiles(created_by=tid)
        fio = " ".join(p for p in (first, last) if p) or None
        rows.append({
            "telegram_id": tid,
            "label": format_person_label(
                first_name=first, last_name=last, username=uname, telegram_id=tid,
            ),
            "fio": fio or "—",
            "username": f"@{uname}" if uname else "—",
            "has_wg": bool(wg),
        })
    return rows
