from __future__ import annotations

from html import escape

from crwarbot.db.queries import Link


def mention(player_name: str, link: Link | None) -> str:
    """Render the game nickname itself as a ping for whoever claimed it.

    An inline `tg://user` link is guaranteed to work for members of the chat it
    is posted in, which every debtor is, so the `@handle` is not needed and the
    nickname stays readable. Unlinked players can only be named, not pinged.
    """
    name = escape(player_name)
    if link is None:
        return name
    return f'<a href="tg://user?id={link.tg_user_id}">{name}</a>'
