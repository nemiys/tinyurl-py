"""The public redirect: a short code in, a 302 to the real address out."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from tinyurl_py.api.dependencies import Database, RedisClient
from tinyurl_py.cache.links import CachedLink, cache_link, get_cached_link
from tinyurl_py.domain.codes import is_valid_code
from tinyurl_py.domain.devices import is_mobile
from tinyurl_py.events.clicks import ClickEvent, publish_click

router = APIRouter(tags=["redirect"])


@router.get(
    "/{code}",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        404: {"description": "No such link"},
        410: {"description": "The link has expired"},
    },
)
async def redirect(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Database,
    redis: RedisClient,
) -> RedirectResponse:
    # Scanners hit paths like /favicon.ico or /wp-login.php all day. Anything
    # that cannot be one of our codes is dismissed before any lookup.
    if not is_valid_code(code):
        raise HTTPException(status_code=404, detail="Link not found")

    # Cache-aside: ask the cache first; on a miss ask Mongo (the source of
    # truth) and keep the answer for next time.
    link = await get_cached_link(redis, code)
    if link is None:
        document = await db.links.find_one({"code": code})
        if document is None:
            raise HTTPException(status_code=404, detail="Link not found")
        link = CachedLink(
            link_id=str(document["_id"]),
            url=document["url"],
            mobile_url=document.get("mobile_url"),
            expires_at=document.get("expires_at"),
        )
        await cache_link(redis, code, link)

    # Checked on every request, cached or not: the cache's time limit already
    # keeps dead links out, this is the second lock on the same door.
    if link.expires_at is not None and link.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="Link has expired")

    on_mobile = is_mobile(request.headers.get("user-agent"))
    wants_mobile = link.mobile_url is not None and on_mobile
    target = link.mobile_url if wants_mobile and link.mobile_url else link.url

    # Runs after the response has been sent, so counting the click never makes
    # the visitor wait.
    event = ClickEvent.new(link_id=link.link_id, device="mobile" if on_mobile else "desktop")
    background_tasks.add_task(publish_click, redis, event)

    # 302 (not 301) so every click comes back through us. "no-store" stops
    # browsers and proxies from remembering the redirect.
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})
