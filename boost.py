import requests
import statistics
from datetime import datetime, timedelta
from dateutil import tz
import time
import traceback
from elements import get_token, get_user, get_ndjson, shorten
from elements import get_notes, add_note, load_mod_log, get_mod_log
from elements import ModActionType, WarningStats, User
from elements import warn_sandbagging, warn_boosting, mark_booster, decode_string


BOOST_UPDATE_PERIOD = 5 * 60  # seconds

BOOST_SUS_PROGRESS = 50
BOOST_SUS_NUM_GAMES = 50
BOOST_SUS_RATING_DIFF = [150, 300]
BOOST_NUM_GAMES = [100, 200, 500]
BOOST_NUM_MOVES = [0, 5, 10, 15]
BOOST_BAD_GAME_PERCENT = {0: [0.05, 0.10], 5: [0.08, 0.15], 10: [0.10, 0.20], 15: [0.15, 0.33]}
BOOST_STREAK_TIME = 10 * 60  # interval between games [s]
BOOST_STREAK_REPORTABLE = 3
BOOST_SUS_STREAK = 3
BOOST_NUM_PLAYED_GAMES = [100, 250]
BOOST_CREATED_DAYS_AGO = [30, 60]
BOOST_ANALYSIS_SCORE = 2
NUM_FIRST_GAMES_TO_EXCLUDE = 15
MAX_NUM_TOURNEY_PLAYERS = 20
STD_NUM_TOURNEYS = 5
MIN_NUM_TOURNEY_GAMES = 4
MAX_LEN_TOURNEY_NAME = 22
API_TOURNEY_DELAY = 0.5  # [s]
BOOST_RING_TOOL = b'iSfVR3ICd3lHqSQf2ucEkLvyvCf0'


boosts = {}


class VariantPlayed:
    def __init__(self, variant_name, perf):
        self.name = variant_name
        self.rd = perf.get('rd', 0)
        self.prov = perf.get('prov', False)
        self.rating = perf.get('rating', 0)
        self.num_games = perf.get('games', 0)
        self.progress = perf.get('prog', 0)
        self.min_rating: int = None
        self.max_rating: int = None
        self.stable_rating_range = []  # [self.rating, self.rating]
        # ^  pre-initialization might have been needed for check_variants(), see below
        self.detailed_progress = []
        self.num_recent_games = 0

    def get_rating(self):
        if self.rating == 0:
            rating = "?"
        else:
            rating = str(self.rating)
            if self.prov:
                if self.num_recent_games == 0:
                    rating += '?'
                else:
                    rating += '<span class="text-warning">?</span>'
            progress = f"&plusmn;{self.rd} " if self.rd > 60 else ""
            class_rating = ""
            if abs(self.progress) > BOOST_SUS_PROGRESS:
                progress = f"{progress}progress: +{self.progress}" if self.progress > 0 \
                    else f"{progress}progress: &minus;{abs(self.progress)}"
                class_rating = "" if self.num_recent_games == 0 else ' class="text-danger" style="text-decoration:none;"' \
                    if self.num_games >= BOOST_SUS_NUM_GAMES else ' class="text-warning" style="text-decoration:none;"'
            if progress:
                rating = f'<abbr title="{progress}"{class_rating}>{rating}</abbr>'
        return rating

    def get_info(self):
        if self.num_games == 0:
            return ""
        if self.name:
            name = f"{self.name[0].upper()}{self.name[1:]}"
        else:
            name = "Unknown Variant"
        if abs(self.progress) > BOOST_SUS_PROGRESS:
            progress = f"+{self.progress}" if self.progress > 0 else f"&minus;{abs(self.progress)}"
            prog = f'<span class="text-danger px-1">{progress}</span>'
        else:
            prog = ""
        return f'<div><span class="text-success">{name}</span>: {self.get_rating()} ' \
               f'over {self.num_games:,} game{"" if self.num_games == 1 else "s"}{prog}</div>'

    def get_table_row(self):
        if self.num_games == 0:
            return ""
        if self.name:
            name = f"{self.name[0].upper()}{self.name[1:]}"
        else:
            name = "Unknown Variant"
        if self.min_rating is None or self.max_rating is None or self.num_recent_games <= 1:
            str_range = ""
        else:
            rating_diff = self.stable_rating_range[1] - self.stable_rating_range[0]
            color = ' class="text-danger"' if rating_diff >= BOOST_SUS_RATING_DIFF[1] else ' class="text-warning"' \
                if rating_diff >= BOOST_SUS_RATING_DIFF[0] else ""
            str_detailed_progress = "&Delta;{}: {}".format(rating_diff, " &rarr; ".join(reversed(self.detailed_progress)))
            if rating_diff == 0:
                str_range = f"{self.stable_rating_range[0]}?"
            else:
                str_range = f'<span{color}>{self.stable_rating_range[0]}</span>&hellip;' \
                            f'<span{color}>{self.stable_rating_range[1]}</span>'
            is_min_stable = self.stable_rating_range[0] == self.min_rating
            is_max_stable = self.stable_rating_range[1] == self.max_rating
            if not is_min_stable or not is_max_stable:
                str_detailed_progress = f'{self.min_rating}{"" if is_min_stable else "?"}&hellip;' \
                                        f'{self.max_rating}{"" if is_max_stable else "?"} {str_detailed_progress}'
            str_range = f'<abbr title="{str_detailed_progress}" style="text-decoration:none;">{str_range}</abbr>'
        str_num_recent_games = "&ndash;" if self.num_recent_games == 0 else f"{self.num_recent_games:,}"
        row_class = ' class="text-muted"' if self.num_recent_games == 0 else ""
        perf_link = ""
        if self.num_recent_games > 0:
            link = f'https://lichess.org/@/{{username}}/perf/{self.name}'
            perf_link = f'<a href="{link}" target="_blank">open</a>'
            name = f'<button class="btn btn-primary w-100 py-0" ' \
                   f'onclick="add_to_notes(this)" data-selection=\'{link}\'>{name}</button>'
        row = f'''<tr{row_class}>
                    <td class="text-left">{name}</td>
                    <td class="text-left">{perf_link}</td>
                    <td class="text-left">{self.get_rating()}</td>
                    <td class="text-center">{str_num_recent_games}</td>
                    <td class="text-center">{str_range}</td>
                    <td class="text-right">{self.num_games:,}</td>
                  </tr>'''
        return row


class Storm:
    def __init__(self, perfs=None):
        perf = perfs.get('storm', {}) if perfs else {}
        self.runs = perf.get('runs', 0)
        self.score = perf.get('score', 0)

    def is_ok(self):
        return self.runs > 0 and self.score > 0

    def get_info(self):
        if not self.is_ok():
            return ""
        return f'<div class="mb-3 px-2">Strom: {self.score} over {self.runs} runs</div>'


class StatsData:
    def __init__(self):
        self.num = 0
        self.variant_num = {}
        self.mean = 0
        self.median = 0
        self.dev_mean = 0
        self.dev_median = 0

    @staticmethod
    def get_robust_set(data):
        if len(data) >= 10:
            sorted_data = sorted(data)
            num_outliers = max(1, int(round(len(sorted_data) / 20)))
            robust_set = sorted_data[num_outliers:-num_outliers]
            return robust_set
        else:
            return data

    def calc(self, variant_ratings, user_ratings):
        if not variant_ratings:
            return
        mean = {}
        median = {}
        self.num = 0
        self.variant_num = {}
        # Variant nums
        for variant, ratings in variant_ratings.items():
            self.variant_num[variant] = len(ratings)
        # Difference
        relative_ratings = []
        for variant, ratings in variant_ratings.items():
            for rating in ratings:
                relative_ratings.append(rating - user_ratings[variant])
        relative_ratings = StatsData.get_robust_set(relative_ratings)
        self.mean = statistics.mean(relative_ratings)
        self.median = statistics.median(relative_ratings)
        # Absolute deviation
        for variant, ratings in variant_ratings.items():
            self.num += len(ratings)
            mean[variant] = statistics.mean(ratings)
            median[variant] = statistics.median(ratings)
        diff_mean = []
        diff_median = []
        for variant, ratings in variant_ratings.items():
            for rating in ratings:
                diff_mean.append(abs(rating - mean[variant]))
                diff_median.append(abs(rating - median[variant]))
        diff_mean = StatsData.get_robust_set(diff_mean)
        diff_median = StatsData.get_robust_set(diff_median)
        self.dev_mean = statistics.mean(diff_mean)
        self.dev_median = statistics.median(diff_median)


class GameAnalysis:
    def __init__(self, max_num_moves, is_sandbagging):
        self.max_num_moves = max_num_moves
        self.streak = StatsData()  # exclude opponent's early resignations?
        self.all_games = StatsData()
        self.bad_games = StatsData()
        self.resign = StatsData()
        self.timeout = StatsData()
        self.out_of_time = StatsData()
        self.is_sandbagging = is_sandbagging
        self.skip_atomic_streaks = is_sandbagging
        self.score = 0
        self.row = ""

    def check_variants(self, variants):
        if not self.skip_atomic_streaks:
            return
        for variant in variants:
            if variant.name == 'atomic':
                if not variant.stable_rating_range:
                    # variant might have been played before but not in the 100 latest games
                    return
                self.skip_atomic_streaks = variant.stable_rating_range[0] < 1800 and variant.stable_rating_range[1] < 2000
                return

    def get_num_and_score(self, stats, *, limits=None, text_classes=None, exclude_variants=None, precision=10):
        if stats.num == 0:
            return '&ndash;', 0
        mean = int(round(stats.mean / precision)) * precision
        median = int(round(stats.median / precision)) * precision
        str_mean = f"+{mean}" if mean > 0 else f"&minus;{abs(mean)}" if mean < 0 else "0"
        str_median = f"+{median}" if median > 0 else f"&minus;{abs(median)}" if median < 0 else "0"
        nums = [(variant, num) for variant, num in stats.variant_num.items()]
        nums.sort(key=lambda variant_num: variant_num[1], reverse=True)
        str_variants = " ".join([f"{variant}={num}" for variant, num in nums])
        str_info = f"mean={str_mean}, median={str_median}: {str_variants}"
        if not limits:
            limits = [self.all_games.num * percent for percent in BOOST_BAD_GAME_PERCENT[self.max_num_moves]]
        stats_num = sum([num for variant, num in stats.variant_num.items() if variant not in exclude_variants]) \
            if exclude_variants else stats.num
        if text_classes:
            color = f' class="{text_classes[1]}"' if stats_num >= limits[1] else f' class="{text_classes[0]}"' \
                if stats_num >= limits[0] else ""
        else:
            color = ' class="text-danger"' if stats_num >= limits[1] else ' class="text-warning"' \
                if stats_num >= limits[0] else ""
        score = (10 * stats_num / limits[1]) if stats_num >= limits[1] \
            else 1 + (stats_num - limits[0]) / (limits[1] - limits[0]) if stats_num >= limits[0] else 0
        return f'<abbr title="{str_info}"{color} style="text-decoration:none;">{stats_num:,}</abbr>', score

    def calc(self):
        self.score = 0
        if self.is_empty():
            self.row = ""
            return
        num_bad_games, s_bad_games = self.get_num_and_score(self.bad_games)
        exclude_variants = ['atomic'] if self.skip_atomic_streaks and self.max_num_moves > 1 else None
        streak, s_streak = self.get_num_and_score(self.streak, limits=[BOOST_SUS_STREAK, BOOST_SUS_STREAK],
                                         exclude_variants=exclude_variants)
        resign, s_resign = self.get_num_and_score(self.resign)
        timeout, s_timeout = self.get_num_and_score(self.timeout)
        if self.max_num_moves <= 1:
            out_of_time, _ = self.get_num_and_score(self.out_of_time, text_classes=["text-success", "text-success"])
            s_out_of_time = 0
        else:
            out_of_time, s_out_of_time = self.get_num_and_score(self.out_of_time)
        self.score = s_bad_games + s_streak + s_resign + s_timeout + s_out_of_time
        if self.max_num_moves > 10:
            self.score /= 2
        num_moves = 1 if self.max_num_moves == 0 else self.max_num_moves
        link = f"https://lichess.org/@/{{username}}/search?turnsMax={num_moves}&mode=1&players.a={{user_id}}" \
               f"&players.{{winner_loser}}={{user_id}}&sort.field=d&sort.order=desc"
        link_open = f'<a class="ml-2" href="{link}" target="_blank">open</a>'
        if self.streak.num >= BOOST_STREAK_REPORTABLE:
            str_incl = "including" if self.streak.num < self.bad_games.num else "i.e."
            link = f'{link} {str_incl} {self.streak.num} games streak'
        self.row = f'''<tr>
                    <td class="text-left"><button class="btn btn-primary p-0" style="min-width: 120px;" 
                        onclick="add_to_notes(this)" data-selection=\'{link}\'>{self.max_num_moves}</button>{link_open}</td>
                    <td class="text-right pr-2">{num_bad_games}</td>
                    <td class="text-center px-2">{streak}</td>
                    <td class="text-right pr-2">{resign}</td>
                    <td class="text-right pr-2">{timeout}</td>
                    <td class="text-right pr-2">{out_of_time}</td>
                  </tr>'''

    def set_best_row(self):
        self.row = self.row.replace("btn-primary", "btn-warning")

    def is_empty(self):
        return sum((self.bad_games.num, self.streak.num, self.resign.num, self.timeout.num, self.out_of_time.num)) == 0


class TourneyInfo:
    def __init__(self, variant):
        self.variant = variant
        self.num_games = 0


class UserTournament:
    def __init__(self, user_id, user_rating, tournament_id, is_arena, tourney_info):
        self.user_id = user_id
        self.user_rating = user_rating
        self.tournament_id = tournament_id
        self.is_arena = is_arena
        self.variant = tourney_info.variant
        self.num_games = tourney_info.num_games
        self.is_official = False
        self.num_players = 0
        self.is_finished = True  # default True for swiss tournaments
        self.name = ""
        self.date = ""
        self.place: int = None
        self.score: int = None
        self.performance: int = None

    def download(self):
        headers = {'Authorization': f"Bearer {get_token()}"}
        if self.is_arena:
            url = f"https://lichess.org/api/tournament/{self.tournament_id}"
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                raise Exception(f"ERROR /api/tournament/: Status Code {r.status_code}")
            arena = r.json()
            self.name = arena['fullName']
            self.date = arena['startsAt']
            i = self.date.rfind(':')
            if i > 0:
                self.date = self.date[:i].replace('T', ' ')
            self.is_official = (arena['createdBy'] == "lichess")
            self.num_players = arena['nbPlayers']
            self.is_finished = arena.get('isFinished', False)
            if arena['standing']['page'] != 1:
                raise Exception(f"ERROR /api/tournament/: Page {arena['standing']['page']}")
            for player in arena['standing']['players']:
                if player['name'].lower() == self.user_id:
                    self.place = player['rank']
                    self.score = player['score']
                    break
            url = f"https://lichess.org/api/tournament/{self.tournament_id}/results?nb={MAX_NUM_TOURNEY_PLAYERS}"
            arena_res = get_ndjson(url)
            for player in arena_res:
                if player['username'].lower() == self.user_id:
                    self.place = player['rank']
                    self.score = player['score']
                    self.performance = player['performance']
                    break
        else:
            url = f"https://lichess.org/api/swiss/{self.tournament_id}/results?nb={MAX_NUM_TOURNEY_PLAYERS}"
            swiss_res = get_ndjson(url)
            self.num_players = len(swiss_res)
            self.name = f"Swiss/{self.tournament_id}"
            for player in swiss_res:
                if player['username'].lower() == self.user_id:
                    self.place = player['rank']
                    self.score = player['points']
                    self.performance = player['performance']
                    break

    def get_official(self):
        if not self.is_official:
            return ""
        return '<abbr title="Official" class="text-info pr-2" style="text-decoration:none;">' \
               '<i class="fas fa-chess-knight"></i></abbr>'

    def get_ongoing(self):
        if self.is_finished:
            return ""
        return '<abbr title="Not finished" class="text-info pr-2" style="text-decoration:none;">' \
               '<i class="fas fa-running"></i></abbr>'

    def get_performance(self):
        if self.performance is None:
            performance = "&ndash;"
        else:
            diff = int(round(self.performance - self.user_rating[self.variant]))
            str_diff = f"+{diff}" if diff > 0 else f"&minus;{abs(diff)}" if diff < 0 else "0"
            if abs(diff) > BOOST_SUS_RATING_DIFF[1]:
                performance = f'<span class="text-danger">{str_diff}</span>'
            elif abs(diff) > BOOST_SUS_RATING_DIFF[0]:
                performance = f'<span class="text-warning">{str_diff}</span>'
            else:
                performance = f"{str_diff}"
        return performance

    def get_name_link(self):
        name = shorten(self.name, MAX_LEN_TOURNEY_NAME)
        tourney_type = "tournament" if self.is_arena else "swiss"
        class_name = ""
        if self.is_official and self.name.startswith('≤') and self.place:
            if self.place <= 5:
                class_name = ' class="text-danger"'
            elif self.place <= 10:
                class_name = ' class="text-warning"'
        url = f'https://lichess.org/{tourney_type}/{self.tournament_id}'
        name_link = f'<a href="{url}"{class_name} target="_blank">{name}</a>'
        if self.date:
            name_link = f'<abbr title="{self.date} UTC" class="pr-2" style="text-decoration:none;">{name_link}</abbr>'
        return url, name_link

    def get_table_row(self):
        tournament_url, name_link = self.get_name_link()
        name = f"{self.get_ongoing()}{self.get_official()}{name_link}"
        if self.place is None:
            place = f"{MAX_NUM_TOURNEY_PLAYERS + 1}+" if self.name else "&ndash;"
            place_class = ""
        else:
            place = '<i class="fas fa-trophy"></i>' if self.place == 1 else f"{self.place:,}"
            place_class = " text-warning pt-2 pb-1" if self.place == 1 else " text-warning" if 2 <= self.place <= 3 else ""
        performance = self.get_performance()
        if self.score is None:
            score = "&ndash;"
        else:
            score = f"{self.score:,}" if self.is_arena else f"<b>{self.score:,}</b>"
        row = f'''<tr>
                    <td class="text-left"><button class="btn btn-primary py-0 mr-2" onclick="add_to_notes(this)" 
                        data-selection=\'{tournament_url}\'><i class="fas fa-plus"></i></button>{name}</td>
                    <td class="text-center{place_class}">{place}</td>
                    <td class="text-right">{self.num_games:,}</td>
                    <td class="text-right">{performance}</td>
                    <td class="text-right">{score}</td>
                    <td class="text-right">{self.num_players:,}</td>
                  </tr>'''
        return row


class Games:
    def __init__(self, user_id, max_num_games):
        self.user_id = user_id
        self.games = []
        self.arena_tournaments = {}
        self.swiss_tournaments = {}
        self.median_rating = {}
        self.all_user_ratings = {}
        self.since: int = None
        self.until: datetime = None
        self.max_num_games: int = max_num_games

    def download(self, since=None, before=None):
        now_utc = datetime.now(tz=tz.tzutc())
        ts_6months_ago = int((now_utc - timedelta(days=182)).timestamp() * 1000)
        if since is None:
            since = ts_6months_ago
        else:
            since = max(ts_6months_ago, int(since.timestamp() * 1000))
        self.until = None
        if before:
            try:
                self.until = datetime.strptime(before, '%Y-%m-%dT%H:%M').replace(tzinfo=tz.tzutc())
            except Exception as exception:
                before = None
                traceback.print_exception(type(exception), exception, exception.__traceback__)
        if before:
            str_until = f"&until={int(self.until.timestamp() * 1000)}"
        else:
            str_until = ""
            self.until = now_utc
        url = f"https://lichess.org/api/games/user/{self.user_id}?rated=true&finished=true&max={self.max_num_games}" \
              f"&since={since}{str_until}"
        self.since = None if since == ts_6months_ago else since
        self.games = get_ndjson(url)

    def get_num(self):
        str_s = "" if len(self.games) == 1 else "s"
        str_num = f'<abbr title="{len(self.games)} latest game{str_s} analyzed ({self.max_num_games} requested)" ' \
                  f'style="text-decoration:none;"><b>{len(self.games)} game{str_s}</b></abbr>'
        first_createdAt: datetime = None
        if self.games:
            first_createdAt = datetime.fromtimestamp(self.games[-1]['createdAt'] // 1000, tz=tz.tzutc())
        if len(self.games) > 1:
            last_createdAt = datetime.fromtimestamp(self.games[0]['createdAt'] // 1000, tz=tz.tzutc())
            num_days = (last_createdAt - first_createdAt).days
            str_num = f'{str_num} for <b>{num_days} day{"" if num_days == 1 else "s"}</b>'
        if self.since:
            since = datetime.fromtimestamp(self.since // 1000, tz=tz.tzutc())
            str_num = f'{str_num} from <abbr title="Date/Time of the last manual warning">{since:%Y-%m-%d %H:%M} UTC</abbr>'
        elif self.games:
            str_num = f'{str_num} from {first_createdAt:%Y-%m-%d %H:%M} UTC'
        return f'<div class="mb-3">{str_num}</div>'

    def analyse(self, is_sandbagging=True):
        analyses = []
        for max_num_moves in BOOST_NUM_MOVES:
            to_process_once = is_sandbagging and max_num_moves == BOOST_NUM_MOVES[0]
            analysis = GameAnalysis(max_num_moves, is_sandbagging)
            all_games = {}
            bad_games = {}
            resign = {}
            timeout = {}
            out_of_time = {}
            self.all_user_ratings = {}
            streak = {}
            best_streak = {}
            is_last_game_bad = False
            last_game_end = None
            for game in self.games:
                if not game['rated']:
                    raise Exception("Error games: not a rated game")
                status = game['status']
                if status not in ["created", "started", "aborted", "unknownFinish", "draw", "cheat"]:
                    black_id = game['players']['black']['user']['id']
                    white_id = game['players']['white']['user']['id']
                    if white_id == self.user_id:
                        opp_color = 'black'
                        user_color = 'white'
                    elif black_id == self.user_id:
                        opp_color = 'white'
                        user_color = 'black'
                    else:
                        raise Exception("Error games: no player")
                    variant = game['variant']
                    if variant == "standard":
                        variant = game['speed']
                    user_rating = game['players'][user_color]['rating']
                    add_variant_rating(self.all_user_ratings, variant, user_rating)
                    opp_rating = game['players'][opp_color]['rating']
                    add_variant_rating(all_games, variant, opp_rating)
                    if to_process_once:
                        arena = game.get('tournament', "")
                        if arena:
                            saved_tourney_info = self.arena_tournaments.get(arena)
                            if saved_tourney_info is None:
                                self.arena_tournaments[arena] = TourneyInfo(variant)
                            elif saved_tourney_info.variant != variant:
                                self.arena_tournaments[arena].variant = "multi"
                            self.arena_tournaments[arena].num_games += 1
                        swiss = game.get('swiss', "")
                        if swiss:
                            saved_tourney_info = self.swiss_tournaments.get(swiss)
                            if saved_tourney_info is None:
                                self.swiss_tournaments[swiss] = TourneyInfo(variant)
                            elif saved_tourney_info.variant != variant:
                                self.swiss_tournaments[swiss].variant = "multi"
                            self.swiss_tournaments[swiss].num_games += 1
                    num_moves = (len(game['moves'].split()) + (user_color == 'white')) // 2
                    if num_moves <= max_num_moves:
                        winner = game.get('winner', None)
                        if winner is not None and is_sandbagging == (winner == opp_color):
                            # Status: "mate"  "stalemate" "noStart"  "variantEnd"
                            add_variant_rating(bad_games, variant, opp_rating)
                            if status == "timeout":
                                add_variant_rating(timeout, variant, opp_rating)
                            elif status == "outoftime":
                                add_variant_rating(out_of_time, variant, opp_rating)
                            elif status == "resign":
                                add_variant_rating(resign, variant, opp_rating)
                            createdAt = datetime.fromtimestamp(game['createdAt'] // 1000, tz=tz.tzutc())
                            delta = (createdAt - last_game_end) if last_game_end else None
                            if is_last_game_bad and last_game_end \
                                    and delta.days*24*60*60 + delta.seconds <= BOOST_STREAK_TIME:
                                add_variant_rating(streak, variant, opp_rating)
                            else:
                                streak = {variant: [opp_rating]}
                            if sum([len(ratings) for ratings in streak.values()]) \
                                    > sum([len(ratings) for ratings in best_streak.values()]):
                                best_streak = streak
                            is_last_game_bad = True
                            last_game_end = datetime.fromtimestamp(game['lastMoveAt'] // 1000, tz=tz.tzutc())
                            continue
                    is_last_game_bad = False
            for variant, ratings in self.all_user_ratings.items():
                self.median_rating[variant] = statistics.median(ratings)
            analysis.all_games.calc(all_games, self.median_rating)
            analysis.bad_games.calc(bad_games, self.median_rating)
            analysis.timeout.calc(timeout, self.median_rating)
            analysis.out_of_time.calc(out_of_time, self.median_rating)
            analysis.resign.calc(resign, self.median_rating)
            analysis.streak.calc(best_streak, self.median_rating)
            analysis.calc()
            analyses.append(analysis)
        best_row_analysis = None
        for analysis in analyses:
            if analysis.score > BOOST_ANALYSIS_SCORE \
                    and (best_row_analysis is None or analysis.score > best_row_analysis.score):
                best_row_analysis = analysis
        if best_row_analysis is not None:
            best_row_analysis.set_best_row()
        return analyses


class Boost:
    ring_tool: str = None

    @staticmethod
    def is_mod():
        return not not Boost.ring_tool

    def __init__(self, username, num_games, before):
        self.user = User(username)
        self.before = before
        self.errors = []
        self.variants = []
        self.storm = Storm()
        self.games = Games(self.user.id, num_games)
        self.sandbagging = []
        self.boosting = []
        self.tournaments = []
        self.last_update_tournaments: datetime = None
        self.enable_sandbagging = False
        self.enable_boosting = False
        self.prefer_marking = False
        self.mod_log: ModLogData = None
        self.mod_log_out = ""
        if Boost.ring_tool is None:
            Boost.ring_tool = decode_string(BOOST_RING_TOOL)  # returns "" (not None) if not available

    def get_variants(self):
        rows = [variant.get_table_row() for variant in self.variants]
        if not rows:
            return ""
        str_games = f'Number of games played among the last ' \
                    f'{len(self.games.games)} game{"" if len(self.games.games) == 1 else "s"} analyzed'
        table = f'''<div class="column">
            <table id="variants_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
              <thead><tr>
                <th class="text-left" style="cursor:default;">Variant</th>
                <th></th>
                <th class="text-left" style="cursor:default;">Rating</th>
                <th class="text-center" style="cursor:default;"><abbr title="{str_games}" 
                    style="text-decoration:none;"><i class="fas fa-hashtag"></i></abbr></th>
                <th class="text-center" style="cursor:default;">Range</th>
                <th class="text-right" style="cursor:default;"><abbr title="Total number of rated games played" 
                    style="text-decoration:none;"># games</abbr></th>
              </tr></thead>
              {"".join(rows).format(username=self.user.name)}
            </table>
          </div>'''
        return f"{table}{self.storm.get_info()}"

    def get_errors(self):
        if not self.errors:
            return ""
        return f'<div class="text-warning"><div>{"</div><div>".join(self.errors)}</div></div>'

    def get_info_1(self):
        main = self.user.get_user_info(BOOST_CREATED_DAYS_AGO, BOOST_NUM_PLAYED_GAMES)
        num_games = self.games.get_num()
        analysis = self.get_analysis()
        if analysis:
            analysis = f'<div class="my-3">{analysis}</div>'
        best_tournaments = f'<a href="https://lichess.org/@/{self.user.name}/tournaments/best" target="_blank" ' \
                           f'class="btn btn-secondary flex-grow-1 py-0" role="button">Best tournaments&hellip;</a>'
        if Boost.ring_tool:
            class_boost_ring = "btn-warning" if self.enable_sandbagging and self.enable_boosting else "btn-secondary"
            additional_tools = f'<div class="d-flex justify-content-between mb-2 px-1">' \
                               f'<a href="https://{Boost.ring_tool}/?user={self.user.name}" target="_blank" ' \
                               f'class="btn {class_boost_ring} flex-grow-1 py-0 mr-2" ' \
                               f'role="button">Boost ring tool&hellip;</a>{best_tournaments}</div>'
        else:
            additional_tools = f'<div>{best_tournaments}' \
                               f'<div class="text-warning mb-2">No permissions to work with mod data</div></div>'
        return f"{main}{num_games}{self.get_errors()}{analysis}{additional_tools}"

    def get_info_2(self):
        variants = self.get_variants()
        if variants:
            variants = f'<div class="my-3">{variants}</div>'
        profile = self.user.get_profile()
        if profile:
            profile = f'<div class="my-3">{profile}</div>'
        return f"{variants}{profile}"

    def get_mod_notes(self, mod_log_data):
        mod_notes = get_notes(self.user.name, mod_log_data) if Boost.is_mod() else ""
        header_notes = "Notes:" if mod_notes else "No notes"
        return {'mod-notes': mod_notes, 'notes-header': header_notes}

    def get_enabled_buttons(self):
        return {'enable-sandbagging': 1 if self.enable_sandbagging and not self.prefer_marking else 0,
                'enable-boosting': 1 if self.enable_boosting and not self.prefer_marking else 0,
                'enable-marking': 1 if self.prefer_marking and (self.enable_sandbagging or self.enable_boosting)
                                       else -1 if self.user.is_titled() else 0}

    def set(self, user):
        self.user.set(user)
        if self.user.disabled:
            self.errors.append('Account closed')
        else:
            perfs = user.get('perfs', {})
            self.storm = Storm(perfs)
            for variant_name, perf in perfs.items():
                if variant_name != "strom":
                    self.variants.append(VariantPlayed(variant_name, perf))
            self.variants.sort(key=lambda variant: (-999999 if variant.name == "puzzle" else 0) + variant.num_games,
                               reverse=True)
        self.update_mod_log()
        self.analyse_games()

    def analyse_games(self):
        exc: Exception = None
        try:
            self.games.download(self.mod_log.time_last_manual_warning, self.before)
        except Exception as e:
            exc = e
        self.sandbagging = self.games.analyse(True)
        self.boosting = self.games.analyse(False)
        self.set_rating_range()
        for sandbag in self.sandbagging:
            sandbag.check_variants(self.variants)
        if exc:
            raise exc

    def update_mod_log(self):
        mod_log_data = load_mod_log(self.user.name) if Boost.is_mod() else None
        self.mod_log = ModLogData(mod_log_data)
        self.mod_log_out = self.mod_log.prepare()

    def analyse_tournaments(self):
        try:
            now = datetime.now()
            if self.last_update_tournaments:
                delta = now - self.last_update_tournaments
                if delta.days*24*60*60 + delta.seconds < BOOST_UPDATE_PERIOD:
                    return
            # Select tournaments
            selected_tournaments = [(arena, tourney_info, True)
                                    for arena, tourney_info in self.games.arena_tournaments.items()]
            selected_tournaments.extend([(swiss, tourney_info, False)
                                         for swiss, tourney_info in self.games.swiss_tournaments.items()])
            for tourn, tourney_info, is_arena in selected_tournaments:
                if tourney_info.variant == "multi":
                    self.errors.append(f"Skipping multi-variant {'arena' if is_arena else 'swiss'} tournament {tourn}")
                    continue
            selected_tournaments.sort(key=lambda tt: tt[1].num_games, reverse=True)
            for i in range(STD_NUM_TOURNEYS, len(selected_tournaments)):
                tourn, tourney_info, is_arena = selected_tournaments[i]
                if tourney_info.num_games < MIN_NUM_TOURNEY_GAMES:
                    selected_tournaments = selected_tournaments[:i]
                    break
            # Analyse tournaments
            self.tournaments = []
            t1: datetime = None
            for tourn, tourney_info, is_arena in selected_tournaments:
                if t1 is not None:
                    t2 = time.time()
                    delay = API_TOURNEY_DELAY - (t2 - t1)
                    assert delay <= API_TOURNEY_DELAY
                    if delay > 0:
                        time.sleep(delay)
                tourney = UserTournament(self.user.id, self.games.median_rating, tourn, is_arena, tourney_info)
                tourney.download()
                self.tournaments.append(tourney)
                t1 = time.time()
            # Output
            #self.tournaments.sort(key=lambda tourney: tourney.num_games, reverse=True)
            self.last_update_tournaments = now
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)

    def set_rating_range(self):
        for variant, ratings in self.games.all_user_ratings.items():
            for v in self.variants:
                if v.name == variant:
                    v.min_rating = min(ratings)
                    v.max_rating = max(ratings)
                    if len(ratings) <= 10:
                        v.detailed_progress = [str(rating) for rating in ratings]
                    else:
                        step = len(ratings) / 10
                        v.detailed_progress = [str(ratings[int(round(i * step))]) for i in range(10)]
                    v.num_recent_games = len(ratings)
                    num_stable_games = v.num_games - NUM_FIRST_GAMES_TO_EXCLUDE
                    # Ratings are in reverse order
                    i_end = min(len(ratings), num_stable_games)
                    stable_ratings = ratings[:i_end] if i_end > 0 else [ratings[0]]
                    v.stable_rating_range = [min(stable_ratings), max(stable_ratings)]

    def get_analysis(self):
        tables = [("Sandbagging", "loser", self.sandbagging), ("Boosting", "winner", self.boosting)]
        output = []
        for table_name, winner_loser, analyses in tables:
            rows = [analysis.row for analysis in analyses if not analysis.is_empty()]
            str_rows = "".join(rows).format(username=self.user.name, user_id=self.user.id, winner_loser=winner_loser)
            if rows:
                table = f'''<table id="{table_name.lower()}_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
                      <thead><tr>
                        <th class="text-left" style="cursor:default;">{table_name}</th>
                        <th class="text-right pr-2" style="cursor:default;">
                            <abbr title="# games" style="text-decoration:none;"><i class="fas fa-hashtag"></i></abbr></th>
                        <th class="text-center" style="cursor:default;">Streak</th>
                        <th class="text-right pr-2" style="cursor:default;">
                            <abbr title="Resigned" style="text-decoration:none;"><i class="fas fa-pray"></i></abbr></th>
                        <th class="text-right pr-2" style="cursor:default;"><abbr title="Left the game" 
                            style="text-decoration:none;"><i class="far fa-hourglass"></i></abbr></th>
                        <th class="text-right pr-2" style="cursor:default;"><abbr title="Out of time" 
                            style="text-decoration:none;"><i class="far fa-clock"></i></i></abbr></th>
                      </tr></thead>
                      {str_rows}
                    </table>'''
            else:
                table = f'<p class="mt-3">No {table_name.lower()}</p>'
            output.append(table)
        return '\n'.join(output)

    def get_tournaments(self):
        if not self.prefer_marking and not self.user.is_titled():
            for tourney in self.tournaments:
                if tourney.is_official and tourney.name.startswith('≤') and 1 <= tourney.place <= 3:
                    self.prefer_marking = True
                    break
        output = self.get_enabled_buttons()
        if not self.tournaments:
            output['tournaments'] = '<p class="mt-3">No tournaments</p>'
            return output
        rows = [tourney.get_table_row() for tourney in self.tournaments]
        link = f'https://lichess.org/@/{self.user.name}/tournaments/recent'
        table = f'''<table id="tournaments_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
              <thead><tr>
                <th class="text-left" style="cursor:default;"><button class="btn btn-primary p-0" style="min-width:120px;" 
                    onclick="add_to_notes(this)" data-selection=\'{link}\'>Tournaments</button></th>
                <th class="text-center" style="cursor:default;">
                    <abbr title="Place" style="text-decoration:none;"><i class="fas fa-trophy"></i></abbr></th>
                <th class="text-right" style="cursor:default;">
                    <abbr title="# games" style="text-decoration:none;"><i class="fas fa-hashtag"></i></abbr></th>
                <th class="text-right" style="cursor:default;">
                    <abbr title="Performance" style="text-decoration:none;"><i class="fas fa-chart-line"></i></abbr></th>
                <th class="text-right" style="cursor:default;">
                    <abbr title="Score" style="text-decoration:none;"><i class="fas fa-plus"></i></abbr></th>
                <th class="text-right" style="cursor:default;">
                    <abbr title="# players" style="text-decoration:none;"><i class="fas fa-users"></i></abbr></th>
              </tr></thead>
              {"".join(rows)}
            </table>'''
        output['tournaments'] = table
        return output

    def enable_buttons(self, mod_log):
        if mod_log.is_engine or mod_log.is_boost:
            self.prefer_marking = True
            self.disable_buttons()
            return
        self.enable_sandbagging = False
        now_utc = datetime.now(tz=tz.tzutc())
        if self.user.is_error:
            days = 0
        else:
            t = datetime.fromtimestamp(self.user.createdAt // 1000, tz=tz.tzutc())
            days = (now_utc - t).days
        for sandbag in self.sandbagging:
            if sandbag.score >= BOOST_ANALYSIS_SCORE:
                self.enable_sandbagging = True
                break
        self.enable_boosting = False
        for boost in self.boosting:
            if boost.score >= BOOST_ANALYSIS_SCORE:
                self.enable_boosting = True
                break
        if not self.user.title or self.user.title == "BOT":
            if mod_log.sandbag_manual.active > 0 or mod_log.boost_manual.active \
               or (mod_log.sandbag_auto.active >= 5 and mod_log.sandbag_auto.total >= 10)\
               or (mod_log.boost_auto.active >= 5 and mod_log.boost_auto.total >= 10):
                self.prefer_marking = True
            elif self.user.num_rated_games <= BOOST_NUM_PLAYED_GAMES[0] or days <= BOOST_CREATED_DAYS_AGO[0]:
                self.prefer_marking = True
            else:
                for variant in self.variants:
                    if not variant.stable_rating_range:
                        continue
                    rating_diff = variant.stable_rating_range[1] - variant.stable_rating_range[0]
                    if rating_diff >= BOOST_SUS_RATING_DIFF[1]:
                        self.prefer_marking = True
                        break
        if self.enable_sandbagging and not self.prefer_marking \
           and mod_log.sandbag_manual.total == 0 and mod_log.sandbag_auto.active == 1 and mod_log.sandbag_auto.total == 1:
            self.enable_sandbagging = False
        if self.enable_boosting and not self.prefer_marking \
           and mod_log.boost_manual.total == 0 and mod_log.boost_auto.active == 1 and mod_log.boost_auto.total == 1:
            self.enable_boosting = False

    def disable_buttons(self):
        self.enable_sandbagging = False
        self.enable_boosting = False

    def get_datetime_before(self):
        until = self.games.until or datetime.now(tz=tz.tzutc())
        return f"{until:%Y-%m-%dT%H:%M}"

    def get_output(self):
        before = self.get_datetime_before()
        if not self.before:
            self.before = before
        output = {}
        if not self.user.is_error:
            try:
                if not self.mod_log:
                    self.update_mod_log()
                self.enable_buttons(self.mod_log)
                output['mod-log'] = self.mod_log_out
                output.update(self.get_mod_notes(self.mod_log.data))
                output.update(self.get_enabled_buttons())
            except Exception as exception:
                traceback.print_exception(type(exception), exception, exception.__traceback__)
        # After self.enable_buttons():
        output.update({'part-1': self.get_info_1(), 'part-2': self.get_info_2(),
                       'num-games': self.games.max_num_games, 'datetime-before': before})
        return output


def add_variant_rating(ratings, variant, rating):
    if variant in ratings:
        ratings[variant].append(rating)
    else:
        ratings[variant] = [rating]


def get_boost_data(username, num_games=None, before=None):
    global boosts
    now = datetime.now()
    user_id = username.lower()
    boost, last_update = boosts.get(user_id, (None, None))
    if num_games:
        num_games = int(num_games)
    if boost and (boost.before == before or before is None) \
            and (boost.games.max_num_games == num_games or num_games is None):
        delta = now - last_update
        if delta.days*24*60*60 + delta.seconds < BOOST_UPDATE_PERIOD:
            return boost
    if not num_games:
        num_games = BOOST_NUM_GAMES[0]
    boost = Boost(username, num_games, before)
    user, api_error = get_user(username)
    if api_error:
        boost.user.is_error = True
        boost.errors.append(api_error)
    else:
        boost.set(user)
        boosts[user_id] = boost, now
    return boost


def send_boost_note(note, username):
    global boosts
    user_id = username.lower()
    boost, last_update = boosts.get(user_id, (None, None))
    try:
        if not boost or not note or not username:
            raise Exception(f"Wrong note: [{username}]: {note}")
        is_ok = add_note(username, note)
        if is_ok:
            mod_notes = get_notes(username)
            header_notes = "Notes:" if mod_notes else "No notes"
            return {'mod-notes': mod_notes, 'notes-header': header_notes, 'user': username}
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        try:
            boost.errors.append(str(exception))
        except:
            print("Error: no boost instance")
    return {'user': username, 'mod-notes': "", "notes-header": "No notes (ERROR)"}


class ModLogData:
    def __init__(self, mod_log_data):
        self.data = mod_log_data
        self.mod_log_table = ""
        self.sandbag_manual = WarningStats()
        self.boost_manual = WarningStats()
        self.sandbag_auto = WarningStats()
        self.boost_auto = WarningStats()
        self.num_total = 0
        self.num_other_actions = 0
        self.time_last_manual_warning: datetime = None
        self.is_boost = False
        self.is_engine = False

    def process(self):
        self.num_other_actions = 0
        self.time_last_manual_warning = None
        self.mod_log_table, actions = get_mod_log(self.data, ModActionType.Boost)
        now_utc = datetime.now(tz=tz.tzutc())
        for action in actions:
            if action.is_warning():
                if action.mod_id == "lichess" and action.details == "Warning: possible sandbagging":
                    self.sandbag_auto.add(action, now_utc)
                elif action.details == "Warning: Sandbagging":
                    self.sandbag_manual.add(action, now_utc)
                    self.update_manual_warning(action)
                elif action.mod_id == "lichess" and action.details == "Warning: possible boosting":
                    self.boost_auto.add(action, now_utc)
                elif action.details == "Warning: Boosting":
                    self.boost_manual.add(action, now_utc)
                    self.update_manual_warning(action)
                elif not action.is_old(now_utc):
                    self.num_other_actions += 1
            else:
                if action.action in ['engine', 'booster', 'alt', 'closeAccount',
                                     'cheatDetected', 'troll', 'permissions', 'setTitle',
                                     'unengine', 'unbooster', 'unalt', 'reopenAccount']:
                    self.num_other_actions += 1
        for action in reversed(actions):
            if action.action == 'engine':
                self.is_engine = True
            elif action.action == 'unengine':
                self.is_engine = False
            elif action.action == 'booster':
                self.is_boost = True
            elif action.action == 'unbooster':
                self.is_boost = False
        self.num_total = len(actions)

    def update_manual_warning(self, action):
        if self.time_last_manual_warning is None:
            self.time_last_manual_warning = action.get_datetime()
        else:
            dt = action.get_datetime()
            if dt > self.time_last_manual_warning:
                self.time_last_manual_warning = dt

    def prepare(self):
        if self.data is None:
            return "Mod Log is not available"
        self.process()
        class_sandbag_manual_active = "text-danger" if self.sandbag_manual.active else ""
        class_boost_manual_active = "text-danger" if self.boost_manual.active else ""
        class_sandbag_manual_total = "text-warning" if self.sandbag_manual.total else "text-muted"
        class_boost_manual_total = "text-warning" if self.boost_manual.total else "text-muted"
        class_sandbag_auto_active = "text-danger" if self.sandbag_auto.active >= 10 \
            else "text-warning" if self.sandbag_auto.active > 1 else ""
        class_boost_auto_active = "text-danger" if self.boost_auto.active >= 10 \
            else "text-warning" if self.boost_auto.active > 1 else ""
        class_sandbag_auto_total = "text-danger" if self.sandbag_auto.total >= 10 \
            else "text-warning" if self.sandbag_auto.total >= 5 else "text-muted"
        class_boost_auto_total = "text-danger" if self.boost_auto.total >= 10 \
            else "text-warning" if self.boost_auto.total >= 5 else "text-muted"
        header = "Warnings"
        if self.is_boost and self.is_engine:
            header += '<br><span class="text-danger">marked: boost/engine</span>'
        elif self.is_boost:
            header += '<br><span class="text-danger">marked: boost</span>'
        elif self.is_engine:
            header += '<br><span class="text-danger">marked: engine</span>'
        mod_log_summary = \
            f'<table class="table table-sm table-hover text-center border">' \
            f'<col>' \
            f'<colgroup span="2"></colgroup>' \
            f'<colgroup span="2"></colgroup>' \
            f'<tr>' \
                f'<td rowspan="2" class="align-middle">{header}</td>' \
                f'<th colspan="2" scope="colgroup">6 months</th>' \
                f'<th colspan="2" scope="colgroup">Total</th>' \
            f'</tr>' \
            f'<tr>' \
                f'<th scope="col">Manual</th>' \
                f'<th scope="col">Auto</th>' \
                f'<th scope="col">Manual</th>' \
                f'<th scope="col">Auto</th>' \
            f'</tr>' \
            f'<tr>' \
                f'<th scope="row" class="text-left">Sandbagging</th>' \
                f'<td class="{class_sandbag_manual_active}">{self.sandbag_manual.get_active()}</td>' \
                f'<td class="{class_sandbag_auto_active}">{self.sandbag_auto.get_active()}</td>' \
                f'<td class="{class_sandbag_manual_total}">{self.sandbag_manual.get_total()}</td>' \
                f'<td class="{class_sandbag_auto_total}">{self.sandbag_auto.get_total()}</td>' \
            f'</tr>' \
            f'<tr>' \
                f'<th scope="row" class="text-left">Boosting</th>' \
                f'<td class="{class_boost_manual_active}">{self.boost_manual.get_active()}</td>' \
                f'<td class="{class_boost_auto_active}">{self.boost_auto.get_active()}</td>' \
                f'<td class="{class_boost_manual_total}">{self.boost_manual.get_total()}</td>' \
                f'<td class="{class_boost_auto_total}">{self.boost_auto.get_total()}</td>' \
            f'</tr>' \
            f'</table>'
        if self.num_other_actions == 0:
            expanded = "false"
            show = ""
        else:
            expanded = "true"
            show = " show"
        header = f'Mod Log: <b>{self.num_total}</b> item{"" if self.num_total == 1 else "s"}'
        mod_log_table = f'<div><div class="card border-0"><div>' \
            f'<button class="btn btn-secondary col py-0" type="button" data-toggle="collapse" ' \
            f'data-target="#collapseModLog" aria-expanded="{expanded}" aria-controls="collapseModLog">{header}</button>' \
            f'</div><div id="collapseModLog" class="collapse{show}">' \
            f'<div class="card card-body p-0">{self.mod_log_table}</div></div></div>' if self.mod_log_table else ""
        return f'{mod_log_summary}{mod_log_table}'


def send_mod_action(action, username):
    global boosts
    output = {'user': username, 'mod-log': "", 'enable-sandbagging': -1, 'enable-boosting': -1, 'enable-marking': -1}
    user_id = username.lower()
    boost, last_update = boosts.get(user_id, (None, None))
    if boost:
        try:
            output.update(boost.get_enabled_buttons())
            if action == "warn_sandbagging":
                is_ok = warn_sandbagging(username)
            elif action == "warn_boosting":
                is_ok = warn_boosting(username)
            elif action == "mark_booster":
                is_ok = mark_booster(username)
            else:
                raise Exception(f"Wrong mod action: [{username}]: {action}")
            print(f"{username}: {action} -> {'DONE' if is_ok else 'skipped'}")
            if is_ok:
                boost.update_mod_log()
                return {'user': username, 'mod-log': boost.mod_log_out,
                        'enable-sandbagging': -1, 'enable-boosting': -1, 'enable-marking': -1}
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            try:
                boost.errors.append(str(exception))
            except:
                print(f"Error: no boost instance for {username}")
    return output
