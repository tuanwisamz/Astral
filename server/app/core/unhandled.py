"""Turns an unexpected exception into the standard error envelope (spec-api §1).

Starlette's own 500 handler sits outside every middleware, so its response never gets CORS
headers: the browser blocks it and the app shows "Can't reach the server". Installed inside
CORSMiddleware, this catches the exception first, so the 500 reaches the page as JSON.
"""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body

log = logging.getLogger(__name__)

MESSAGE = "Something went wrong on our side. Try again in a moment."


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception:
            log.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if started:  # part of a response already went out; nothing sensible to add
                raise
            await JSONResponse(error_body("INTERNAL_ERROR", MESSAGE), status_code=500)(scope, receive, send)
