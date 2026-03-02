from datetime import datetime
from dateutil import tz
import re
from api import ApiType
from elements import timestamp_to_ago, flair_to_text, log


def transform_leet(text: str) -> str:
    """Transform text into a regex that matches common leet substitutions."""
    subs = {
        "e": "e3", "3": "e3", "a": "a4", "4": "a4",
        "i": "i1lI", "1": "i1lI", "l": "i1lI", "I": "i1lI",
        "o": "o0", "0": "o0", "s": "s5$", "5": "s5$", "$": "s5$",
        "t": "t7", "7": "t7", "b": "b8", "8": "b8", "g": "g9", "9": "g9",
    }
    result = ""
    for char in text:
        lower_char = char.lower()
        if lower_char in subs:
            result += f"[{subs[lower_char]}]"
        elif char in r".^$*+?{}[]()|\\ ":
            result += "\\" + char
        else:
            result += char
    return ".*" + result + ".*"


def search_users(query, mod, match_type='regex'):
    """Search Lichess users by regex pattern via GET /mod/search?q=<regex>.

    Returns a dict with 'data' key containing a list of user rows for DataTable rendering.
    Each row: [username, country, flair, flair_name, total_games, seenAt, seenAt_ago,
               createdAt, created_ago, tosViolation, disabled, patron, verified]
    """
    if match_type == 'exact':
        query = f".*{re.escape(query)}.*"
    elif match_type == 'leet':
        query = transform_leet(query)

    url = f"https://lichess.org/mod/search"
    r = mod.api.get(ApiType.ModSearch, url, token=mod.token, params={'q': query})
    if r.status_code != 200:
        log(f"WARNING: {r.status_code} Status Code for /mod/search?q={query}", to_print=True, to_save=True)
        return {'data': [], 'error': f"Status code: {r.status_code}"}
    users = r.json()
    now_utc = datetime.now(tz=tz.tzutc())
    results = []
    for user in users['users']:
        username = user.get('username', user.get('id', ''))
        country = user.get('profile', {}).get('flag', '')
        flair = user.get('flair', '')
        flair_name = flair_to_text(flair)
        num_games = sum(
            perf.get('games', 0)
            for perf_name, perf in user.get('perfs', {}).items()
            if perf_name != 'puzzle'
        )
        seen_at_ms = user.get('seenAt', 0)
        created_at_ms = user.get('createdAt', 0)
        seenAt = f"{datetime.fromtimestamp(seen_at_ms // 1000, tz=tz.tzutc()):%Y-%m-%d %H:%M}" if seen_at_ms else ""
        seenAt_ago = timestamp_to_ago(seen_at_ms, now_utc) if seen_at_ms else ""
        createdAt = f"{datetime.fromtimestamp(created_at_ms // 1000, tz=tz.tzutc()):%Y-%m-%d %H:%M}" if created_at_ms else ""
        created_ago = timestamp_to_ago(created_at_ms, now_utc) if created_at_ms else ""
        tosViolation = 1 if user.get('tosViolation', False) else 0
        disabled = 1 if user.get('disabled', False) else 0
        patron = 1 if user.get('patron', False) else 0
        verified = 1 if user.get('verified', False) else 0
        results.append([username, country, flair, flair_name, num_games,
                        seenAt, seenAt_ago, createdAt, created_ago,
                        tosViolation, disabled, patron, verified])
    return {'data': results}
