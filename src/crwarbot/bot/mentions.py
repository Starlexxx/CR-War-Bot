from __future__ import annotations

from html import escape

from crwarbot.db.queries import Link


def mention(player_name: str, link: Link | None) -> str:
    """Render a chat mention for a player, falling back as far as needed.

    A linked user with a username gets a plain `@handle`; without one we build an
    inline `tg://user` link, which still pings. Unlinked players can only be
    named, not pinged.
    """
    game_name = escape(player_name)
    if link is None:
        return game_name
    if link.tg_username:
        return f"@{escape(link.tg_username)}"
    display = escape(link.tg_full_name or player_name)
    return f'<a href="tg://user?id={link.tg_user_id}">{display}</a>'


def mention_with_game_name(player_name: str, link: Link | None) -> str:
    rendered = mention(player_name, link)
    if link is None:
        return rendered
    return f"{rendered} — {escape(player_name)}"
