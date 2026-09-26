import asyncio

from aiohttp import web


async def _health(request):
    return web.Response(text="OK")


async def run_health_server(port: int):
    """Крошечный HTTP-сервер только для того, чтобы бесплатные хостинги
    типа Render считали сервис "живым" и пинговалки (UptimeRobot и т.п.)
    могли не давать ему засыпать."""
    app = web.Application()
    app.router.add_get("/", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await asyncio.Event().wait()
