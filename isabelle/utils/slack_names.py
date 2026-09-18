import logging
import time

from isabelle.utils.slack import app

FOUND_TTL = 12 * 60 * 60
MISSING_TTL = 5 * 60
DIRECTORY_TTL = 6 * 60 * 60
DIRECTORY_PAGES = 40

_cache: dict[str, tuple[float, dict | None]] = {}
_directory: dict[str, str] = {}
_directory_at = 0.0


def kind_of(slack_id: str) -> str | None:
    if len(slack_id) < 3 or not slack_id.isalnum() or not slack_id.isupper():
        return None
    if slack_id[0] in "CGD":
        return "channel"
    if slack_id[0] in "UW":
        return "user"
    return None


def _fresh(entry) -> bool:
    if entry is None:
        return False
    at, found = entry
    return (time.time() - at) < (FOUND_TTL if found else MISSING_TTL)


async def _load_directory() -> dict[str, str]:
    global _directory, _directory_at

    if _directory and (time.time() - _directory_at) < DIRECTORY_TTL:
        return _directory

    found: dict[str, str] = {}
    cursor = None

    try:
        for _ in range(DIRECTORY_PAGES):
            response = await app._async_client.conversations_list(
                exclude_archived=True,
                types="public_channel",
                limit=1000,
                cursor=cursor,
            )
            for channel in response.get("channels") or []:
                if channel.get("id") and channel.get("name"):
                    found[channel["id"]] = channel["name"]

            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception:
        logging.warning("Could not list Slack channels", exc_info=True)
        if not found:
            return _directory

    _directory = found
    _directory_at = time.time()
    return _directory


async def search_channels(query: str, limit: int) -> list[dict]:
    directory = await _load_directory()
    needle = (query or "").lstrip("#").strip().lower()

    matches = [
        {"id": channel_id, "name": name}
        for channel_id, name in directory.items()
        if not needle or needle in name
    ]
    matches.sort(key=lambda c: (not c["name"].startswith(needle), len(c["name"]), c["name"]))

    return matches[:limit]


async def _lookup(slack_id: str, kind: str) -> dict | None:
    if kind == "channel":
        known = (await _load_directory()).get(slack_id)
        if known:
            return {"kind": "channel", "name": known}

    try:
        if kind == "channel":
            response = await app._async_client.conversations_info(channel=slack_id)
            name = (response.get("channel") or {}).get("name")
        else:
            response = await app._async_client.users_info(user=slack_id)
            profile = response.get("user") or {}
            name = profile.get("name") or (profile.get("profile") or {}).get(
                "display_name"
            )
    except Exception:
        logging.warning("Could not resolve %s", slack_id, exc_info=True)
        return None

    return {"kind": kind, "name": name} if name else None


async def slack_names(ids) -> dict[str, dict]:
    names: dict[str, dict] = {}

    for slack_id in dict.fromkeys(ids):
        kind = kind_of(slack_id)
        if not kind:
            continue

        entry = _cache.get(slack_id)
        if not _fresh(entry):
            entry = (time.time(), await _lookup(slack_id, kind))
            _cache[slack_id] = entry

        if entry[1]:
            names[slack_id] = entry[1]

    return names


def clear_name_cache() -> None:
    global _directory, _directory_at
    _cache.clear()
    _directory = {}
    _directory_at = 0.0
