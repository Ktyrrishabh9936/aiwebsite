import time
from contextlib import asynccontextmanager


@asynccontextmanager
async def timed(request, name):
    started = time.perf_counter()
    try:
        yield
    finally:
        duration = round((time.perf_counter() - started) * 1000, 1)
        timings = getattr(request.state, "server_timings", [])
        timings.append((str(name).replace(" ", "_"), duration))
        request.state.server_timings = timings
