"""AWS Lambda entry point for the Arevei FastAPI application."""

import asyncio

from mangum import Mangum

from push_notifications import dispatch_due
from server import app, db


# ``server.startup`` normally attaches these values.  With the Lambda lifespan
# disabled, attach the shared Mongo client explicitly without starting local
# scheduler loops or closing the client after every request.
app.state.db = db
app.state.voice_storage_ready = True

asgi_handler = Mangum(app, lifespan="off")


def _run_dispatch_due():
    """Run the scheduled coroutine without closing Lambda's shared event loop.

    Mangum reuses the current thread's event loop for Function URL requests.
    ``asyncio.run`` creates and closes a new loop, which leaves Motor bound to a
    closed loop after a scheduled invocation.  Keeping one loop for both paths
    lets the scheduled push dispatcher and HTTP API safely share the Mongo
    client in a warm Lambda environment.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(dispatch_due(db))


def handler(event, context):
    """Serve HTTP through the Function URL and scheduled push delivery via IAM.

    EventBridge Scheduler invokes this function directly with the small JSON
    action payload below.  It does not need a public HTTP endpoint or a secret.
    All other events are Lambda Function URL (HTTP API v2) events handled by
    Mangum.
    """
    if isinstance(event, dict) and event.get("action") == "dispatch_due_followups":
        return _run_dispatch_due()
    return asgi_handler(event, context)
