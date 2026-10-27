"""The public redirect: a short code in, a 302 to the real address out."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from tinyurl_py.api.dependencies import Database, RedisClient, client_ip, enforce_rate_limit
from tinyurl_py.cache.links import CachedLink, cache_link, get_cached_link
from tinyurl_py.domain.codes import is_valid_code
from tinyurl_py.domain.devices import is_mobile
from tinyurl_py.events.clicks import ClickEvent, publish_click
from tinyurl_py.settings import settings

router = APIRouter(tags=["redirect"])


# HEAD is what link checkers and chat previews send to see where a link leads.
# FastAPI does not add it to a GET route by itself, so without this they get 405.
# Left out of the API docs: the same operation twice would clash there.
@router.head("/{code}", status_code=302, response_class=RedirectResponse, include_in_schema=False)
@router.get(
    "/{code}",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        404: {"description": "No such link"},
        429: {"description": "Too many requests from this address; see Retry-After"},
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

    # Limited per client IP, after the junk check above: a scanner asking for
    # /wp-login.php costs us nothing and need not be counted. Unknown but
    # well-formed codes ARE counted, which is what slows down code guessing.
    await enforce_rate_limit(
        redis,
        f"redirect:ip:{client_ip(request)}",
        limit=settings.redirect_limit,
        window_seconds=settings.redirect_window_seconds,
        detail="Too many requests, please slow down",
    )

    # Cache-aside: ask the cache first; on a miss ask Mongo (the source of
    # truth) and keep the answer for next time.
    link = await get_cached_link(redis, code)
    if link is None:
        document = await db.links.find_one({"code": code, "deleted_at": None})
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

    # Only a GET is a visit. A HEAD only asks where the link leads (a chat app
    # may send several for one pasted link), so it is never counted.
    if request.method == "GET":
        # Runs after the response has been sent, so counting the click never
        # makes the visitor wait.
        event = ClickEvent.new(link_id=link.link_id, device="mobile" if on_mobile else "desktop")
        background_tasks.add_task(publish_click, redis, event)

    # 302 (not 301) so every click comes back through us. "no-store" stops
    # browsers and proxies from remembering the redirect.
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})
