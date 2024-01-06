from datetime import datetime
from dateutil import tz
import time
from collections import defaultdict
from api import ApiType
from elements import timestamp_to_ago, flair_to_text, log


API_USERS_MAX_NUM = 300
LB_UPDATE_PERIOD = 5 * 60  # seconds


leaderboard = {}
lb_last_update = defaultdict(lambda: datetime.now().replace(tzinfo=tz.tzutc()))


def update_leaderboard(mod, var):
    global leaderboard, lb_last_update
    now_utc = datetime.now(tz=tz.tzutc())
    variant = "antichess"
    for v in ["ultraBullet", "bullet", "blitz", "rapid", "classical", "chess960", "crazyhouse",
              "antichess", "atomic", "horde", "kingOfTheHill", "racingKings", "threeCheck"]:
        if v.lower() == var.lower():
            variant = v
            break
    variant_name = variant[0].upper() + variant[1:]
    if leaderboard.get(variant):
        delta = now_utc - lb_last_update[variant]
        if delta.total_seconds() < LB_UPDATE_PERIOD:
            return leaderboard[variant], lb_last_update[variant], variant_name
    leaderboard[variant] = []
    url = f"https://lichess.org/player/top/200/{variant}"
    headers = {"Accept": "application/vnd.lichess.v3+json"}
    users = mod.api.get(ApiType.PlayerTop, url, token=None, headers=headers)
    if users.status_code != 200:
        log(f"WARNING: {users.status_code} Status Code for /player/top/200/{variant}", to_print=True, to_save=True)
    users_json = users.json()
    ids = [user['id'] for user in users_json['users']]
    url = "https://lichess.org/api/users"
    user_data = []
    i_end = (len(ids) + API_USERS_MAX_NUM - 1) // API_USERS_MAX_NUM
    for i in range(0, i_end, 1):
        user_data_i = mod.api.post(ApiType.ApiUsers, url,
                                   data=",".join(ids[i * API_USERS_MAX_NUM: min(len(ids), (i + 1) * API_USERS_MAX_NUM)]),
                                   token=mod.token)
        if user_data_i.status_code != 200:
            log(f"WARNING: {user_data_i.status_code} Status Code for /api/users", to_print=True, to_save=True)
        user_data.extend(user_data_i.json())
        if i < i_end - 1:
            time.sleep(1)
    users_active = [user for user in user_data if not user.get('disabled', False)]
    for i, user in enumerate(users_active):
        num_games = sum(perf_variant.get('games', 0)
                        if perf_name != "puzzle" else 0 for perf_name, perf_variant in user['perfs'].items())
        p = user['perfs'][variant]
        num_anti_games = p['games']
        flair = user.get('flair', "")
        flair_name = flair_to_text(flair)
        tosViolation = 1 if user.get('tosViolation', False) else 0
        country = user.get('profile', {}).get('flag', "")
        seenAt = f"{datetime.fromtimestamp(user['seenAt'] // 1000, tz=tz.tzutc()):%Y-%m-%d %H:%M}"
        seenAt_ago = timestamp_to_ago(user['seenAt'], now_utc)
        createdAt = f"{datetime.fromtimestamp(user['createdAt'] // 1000, tz=tz.tzutc()):%Y-%m-%d %H:%M}"
        created_ago = timestamp_to_ago(user['createdAt'], now_utc)
        leaderboard[variant].append([i + 1, user['username'], p['rating'], num_games, flair, seenAt, country,
                                     num_anti_games, created_ago, tosViolation, seenAt_ago, createdAt, flair_name])
    lb_last_update[variant] = now_utc
    return leaderboard[variant], lb_last_update[variant], variant_name
