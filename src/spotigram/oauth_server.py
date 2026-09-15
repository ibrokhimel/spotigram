from __future__ import annotations

from aiohttp import web
from telegram.ext import Application

from spotigram.oauth import parse_callback_url


async def start_oauth_server(app: Application, host: str, port: int) -> web.AppRunner:
    async def callback(request: web.Request) -> web.Response:
        qs = str(request.rel_url)
        parsed = parse_callback_url("http://127.0.0.1" + qs)
        handler = app.bot_data.get("oauth_complete")
        if parsed and handler:
            code, state = parsed
            try:
                await handler(code, state)
            except Exception as exc:
                return web.Response(text=f"Login failed: {exc}", status=400)
            return web.Response(text="Logged in. You can return to Telegram.")
        return web.Response(text="Missing code/state. Paste the URL into the bot.", status=400)

    webapp = web.Application()
    webapp.router.add_get("/callback", callback)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
