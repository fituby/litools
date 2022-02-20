import requests
import statistics
from datetime import datetime, timedelta
from dateutil import tz
import time
import traceback
from elements import get_token, get_ndjson, country_flags, country_names, timestamp_to_ago, shorten


BOOST_UPDATE_PERIOD = 5 * 60  # seconds

BOOST_SUS_PROGRESS = 50
BOOST_SUS_NUM_GAMES = 50
BOOST_SUS_RATING_DIFF = [150, 300]
BOOST_NUM_GAMES = [100, 500]
BOOST_NUM_MOVES = [0, 5, 10, 15]
BOOST_BAD_GAME_PERCENT = {0: [0.05, 0.10], 5: [0.08, 0.15], 10: [0.10, 0.20], 15: [0.15, 0.33]}
BOOST_STREAK_TIME = 10 * 60  # interval between games [s]
BOOST_STREAK_REPORTABLE = 3
BOOST_SUS_STREAK = 3
BOOST_NUM_PLAYED_GAMES = [100, 250]
BOOST_CREATED_DAYS_AGO = [30, 60]
NUM_FIRST_GAMES_TO_EXCLUDE = 6
MAX_NUM_TOURNEY_PLAYERS = 20
STD_NUM_TOURNEYS = 5
MIN_NUM_TOURNEY_GAMES = 4
MAX_LEN_TOURNEY_NAME = 15
API_TOURNEY_DELAY = 0.5  # [s]


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
        if self.num_recent_games > 0:
            link = f'https://lichess.org/@/{{username}}/perf/{self.name}'
            name = f'<button class="btn btn-primary p-0" style="min-width: 120px;" ' \
                   f'onclick="copyTextToClipboard(\'{link}\')">{name}</button>'
        row = f'''<tr{row_class}>
                    <td class="text-left">{name}</td>
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


class Profile:
    def __init__(self):
        self.country = ""
        self.location = ""
        self.bio = ""
        self.firstName = ""
        self.lastName = ""
        self.fideRating = 0
        self.uscfRating = 0
        self.ecfRating = 0

    def set(self, data):
        self.country = data.get('country', "")
        self.location = data.get('location', "")
        self.bio = data.get('bio', "")
        self.firstName = data.get('firstName', "")
        self.lastName = data.get('lastName', "")
        self.fideRating = data.get('fideRating', 0)
        self.uscfRating = data.get('uscfRating', 0)
        self.ecfRating = data.get('ecfRating', 0)

    def get_info(self):
        info = []
        name = f"{self.firstName} {self.lastName}".strip()
        if name:
            info.append(f'<div><span class="text-muted">Name:</span> {name}</div>')
        if self.location:
            info.append(f'<div><span class="text-muted">Location:</span> {self.location}</div>')
        if self.bio:
            info.append(f'<div><span class="text-muted text-break">Bio:</span> {self.bio}</div>')
        ratings = []
        if self.fideRating:
            ratings.append(f"FIDE = {self.fideRating}")
        if self.uscfRating:
            ratings.append(f"USCF = {self.uscfRating}")
        if self.ecfRating:
            ratings.append(f"ECF = {self.ecfRating}")
        str_ratings = ", ".join(ratings)
        if str_ratings:
            info.append(f'<div><span class="text-muted">Ratings:</span> {str_ratings}</div>')
        return "".join(info)


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

    def get_num_and_rating(self, stats, *, limits=None, text_classes=None, exclude_variants=None, precision=10):
        if stats.num == 0:
            return '&ndash;'
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
        return f'<abbr title="{str_info}"{color} style="text-decoration:none;">{stats_num:,}</abbr>'

    def get_table_row(self):
        if self.is_empty():
            return ""
        num_bad_games = self.get_num_and_rating(self.bad_games)
        exclude_variants = ['atomic'] if self.skip_atomic_streaks and self.max_num_moves > 1 else None
        streak = self.get_num_and_rating(self.streak, limits=[BOOST_SUS_STREAK, BOOST_SUS_STREAK],
                                         exclude_variants=exclude_variants)
        resign = self.get_num_and_rating(self.resign)
        timeout = self.get_num_and_rating(self.timeout)
        if self.max_num_moves <= 1:
            out_of_time = self.get_num_and_rating(self.out_of_time, text_classes=["text-success", "text-success"])
        else:
            out_of_time = self.get_num_and_rating(self.out_of_time)
        num_moves = 1 if self.max_num_moves == 0 else self.max_num_moves
        link = f"https://lichess.org/@/{{username}}/search?turnsMax={num_moves}&mode=1&players.a={{user_id}}" \
               f"&players.{{winner_loser}}={{user_id}}&sort.field=d&sort.order=desc"
        if self.streak.num >= BOOST_STREAK_REPORTABLE:
            str_incl = "including" if self.streak.num < self.bad_games.num else "i.e."
            link = f'{link} {str_incl} {self.streak.num} games streak'
        row = f'''<tr>
                    <td class="text-left"><button class="btn btn-primary p-0" style="min-width: 120px;" 
                        onclick="copyTextToClipboard('{link}')">{self.max_num_moves}</button></td>
                    <td class="text-right pr-2">{num_bad_games}</td>
                    <td class="text-center px-2">{streak}</td>
                    <td class="text-right pr-2">{resign}</td>
                    <td class="text-right pr-2">{timeout}</td>
                    <td class="text-right pr-2">{out_of_time}</td>
                  </tr>'''
        return row

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

    def get_name(self):
        name = shorten(self.name, MAX_LEN_TOURNEY_NAME)
        tourney_type = "tournament" if self.is_arena else "swiss"
        class_name = ""
        if self.is_official and self.name.startswith('<') and self.place:
            if self.place <= 5:
                class_name = ' class="text-danger"'
            elif self.place <= 10:
                class_name = ' class="text-warning"'
        name = f'<a href="https://lichess.org/{tourney_type}/{self.tournament_id}" {class_name}target="_blank">{name}</a>'
        if self.date:
            name = f'<abbr title="{self.date}" class="pr-2" style="text-decoration:none;">{name}</abbr>'
        return name

    def get_table_row(self):
        name = f"{self.get_ongoing()}{self.get_official()}{self.get_name()}"
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
                    <td class="text-left">{name}</td>
                    <td class="text-center{place_class}">{place}</td>
                    <td class="text-right">{self.num_games:,}</td>
                    <td class="text-right">{performance}</td>
                    <td class="text-right">{score}</td>
                    <td class="text-right">{self.num_players:,}</td>
                  </tr>'''
        return row


class Games:
    def __init__(self, user_id):
        self.user_id = user_id
        self.games = []
        self.arena_tournaments = {}
        self.swiss_tournaments = {}
        self.median_rating = {}
        self.all_user_ratings = {}

    def download(self):
        ts_6months_ago = int((datetime.now() - timedelta(days=182)).timestamp() * 1000)
        url = f"https://lichess.org/api/games/user/{self.user_id}?rated=true&finished=true&max={BOOST_NUM_GAMES[0]}" \
              f"&since={ts_6months_ago}"
        self.games = get_ndjson(url)

    def get_num(self):
        str_s = "" if len(self.games) == 1 else "s"
        str_num = f'<abbr title="{len(self.games)} latest game{str_s} analyzed (max. {BOOST_NUM_GAMES[0]})" ' \
                  f'style="text-decoration:none;"><b>{len(self.games)} game{str_s}</b></abbr>'
        first_createdAt: datetime = None
        if self.games:
            first_createdAt = datetime.fromtimestamp(self.games[-1]['createdAt'] // 1000, tz=tz.tzutc())
        if len(self.games) > 1:
            last_createdAt = datetime.fromtimestamp(self.games[0]['createdAt'] // 1000, tz=tz.tzutc())
            num_days = (last_createdAt - first_createdAt).days
            str_num = f'{str_num} for <b>{num_days} day{"" if num_days == 1 else "s"}</b>'
        if self.games:
            str_num = f'{str_num} from {first_createdAt:%Y-%m-%d %H:%M}'
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
            analyses.append(analysis)
        return analyses


class Boost:
    def __init__(self, username):
        self.username = username
        self.user_id = username.lower()
        self.errors = []
        self.disabled = False
        self.tosViolation = False
        self.patron = False
        self.verified = False
        self.title = ""
        self.country = ""
        self.createdAt: int = None
        self.num_games = 0
        self.num_rated_games = 0
        self.profile = Profile()
        self.variants = []
        self.storm = Storm()
        self.games = Games(self.user_id)
        self.sandbagging = []
        self.boosting = []
        self.tournaments = []
        self.last_update_tournaments: datetime = None

    def get_name(self):
        if self.title:
            if self.title == "BOT":
                title = f'<span style="color:#cd63d9">{self.title}</span> '
            else:
                title = f'<span class="text-warning">{self.title}</span> '
        else:
            title = ""
        return f'{title}<a href="https://lichess.org/@/{self.user_id}" target="_blank">{self.username}</a>'

    def get_disabled(self):
        if not self.disabled:
            return ""
        return '<abbr title="Closed" class="px-1" style="text-decoration:none;font-size:19px;">' \
               '<i class="fas fa-times text-muted" style="font-size:19px"></i></abbr>'

    def get_patron(self):
        if not self.patron:
            return ""
        return '<abbr title="Lichess Patron" class="text-info px-1" style="text-decoration:none;">' \
               '<i class="fas fa-gem"></i></abbr>'

    def get_verified(self):
        if not self.verified:
            return ""
        return '<abbr title="Verified" class="text-info px-1" style="text-decoration:none;">' \
               '<i class="fas fa-check"></i></abbr>'

    def get_tosViolation(self):
        if not self.tosViolation:
            return ""
        return '<abbr title="TOS Violation" class="px-1" style="text-decoration:none;font-size:19px;' \
               'color:#e74c3c;background-color:#f39c12;"><i class="far fa-angry"></i></abbr>'

    def get_country(self):
        original_country = self.profile.country
        if not original_country:
            return ""
        country_name = country_names.get(original_country, None)
        country = country_flags.get(original_country, None)
        if country_name is None or country is None:
            country_name = original_country.upper()
            if country_name[0] == '_':
                country_name = country_name[1:]
            country = '🏴󠁲󠁵󠁡󠁤󠁿️'
        font_size = "20px"
        if country_name:
            fs = "" if original_country == "_lichess" else f'font-size:{font_size};'
            return f'<abbr class="px-1" title="{country_name}" style="text-decoration:none;{fs}">{country}</abbr>'
        return f'<span class="px-1" style="font-size:{font_size};">{country}</span>'

    def get_name_info(self):
        part1 = f"{self.get_name()}{self.get_disabled()}{self.get_patron()}{self.get_verified()}"
        part2 = f"{self.get_tosViolation()}{self.get_country()} {self.get_created()}"
        return f"<div>{part1}{part2}</div>"

    def get_num_games(self):
        if self.num_games == 0 and self.num_rated_games == 0:
            return ""
        class_games = f' class="text-danger"' if self.num_rated_games <= BOOST_NUM_PLAYED_GAMES[0] \
            else f' class="text-warning"' if self.num_rated_games <= BOOST_NUM_PLAYED_GAMES[1] else ""
        return f'<div><abbr{class_games} title="Number of rated games" style="text-decoration:none;">' \
               f'<b>{self.num_rated_games:,}</b></abbr> / <abbr title="Total number of games" ' \
               f'style="text-decoration:none;">{self.num_games:,}</abbr> games</div>'

    def get_created(self):
        if not self.createdAt:
            return ""
        now = datetime.now()
        created_ago = timestamp_to_ago(self.createdAt, now)
        t = datetime.fromtimestamp(self.createdAt // 1000)
        days = (now - t).days
        class_created = ' class="text-danger"' if days <= BOOST_CREATED_DAYS_AGO[0] \
            else ' class="text-warning"' if days <= BOOST_CREATED_DAYS_AGO[1] else ""
        return f'<abbr{class_created} title="Account created {created_ago}" style="text-decoration:none;">' \
               f'<b>{created_ago}</b></abbr>'

    def get_profile(self):
        return self.profile.get_info()

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
                <th class="text-left" style="cursor:default;">Rating</th>
                <th class="text-center" style="cursor:default;"><abbr title="{str_games}" 
                    style="text-decoration:none;"><i class="fas fa-hashtag"></i></abbr></th>
                <th class="text-center" style="cursor:default;">Range</th>
                <th class="text-right" style="cursor:default;"><abbr title="Total number of rated games played" 
                    style="text-decoration:none;"># games</abbr></th>
              </tr></thead>
              {"".join(rows).format(username=self.username)}
            </table>
          </div>'''
        return f"{table}{self.storm.get_info()}"

    def get_errors(self):
        if not self.errors:
            return ""
        return f'<div class="text-warning"><div>{"</div><div>".join(self.errors)}</div></div>'

    def get_info_1(self):
        main = f'<div class="d-flex justify-content-between align-items-baseline mt-3">' \
               f'{self.get_name_info()}{self.get_num_games()}</div>'
        num_games = self.games.get_num()
        analysis = self.get_analysis()
        if analysis:
            analysis = f'<div class="my-3">{analysis}</div>'
        return f"{main}{num_games}{self.get_errors()}{analysis}"

    def get_info_2(self):
        variants = self.get_variants()
        if variants:
            variants = f'<div class="my-3">{variants}</div>'
        profile = self.get_profile()
        if profile:
            profile = f'<div class="my-3">{profile}</div>'
        return f"{variants}{profile}"

    def set(self, user):
        self.username = user['username']
        self.disabled = user.get('disabled', False)
        if self.disabled:
            self.errors.append('Account closed')
        else:
            self.tosViolation = user.get('tosViolation', False)
            self.patron = user.get('patron', False)
            self.verified = user.get('verified', False)
            self.title = user.get('title', "")
            self.createdAt = user['createdAt']
            self.num_games = user['count']['all']
            self.num_rated_games = user['count']['rated']
            self.profile.set(user.get('profile', {}))
            perfs = user.get('perfs', {})
            self.storm = Storm(perfs)
            for variant_name, perf in perfs.items():
                if variant_name != "strom":
                    self.variants.append(VariantPlayed(variant_name, perf))
            self.variants.sort(key=lambda variant: (-999999 if variant.name == "puzzle" else 0) + variant.num_games,
                               reverse=True)
        self.analyse_games()

    def analyse_games(self):
        exc: Exception = None
        try:
            self.games.download()
        except Exception as e:
            exc = e
        self.sandbagging = self.games.analyse(True)
        self.boosting = self.games.analyse(False)
        self.set_rating_range()
        for sandbag in self.sandbagging:
            sandbag.check_variants(self.variants)
        if exc:
            raise exc

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
                tourney = UserTournament(self.user_id, self.games.median_rating, tourn, is_arena, tourney_info)
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
                    i_start = max(-len(ratings), 1 - num_stable_games)
                    stable_ratings = ratings[i_start:] if i_start < 0 else [ratings[0]]
                    v.stable_rating_range = [min(stable_ratings), max(stable_ratings)]

    def get_analysis(self):
        tables = [("Sandbagging", "loser", self.sandbagging), ("Boosting", "winner", self.boosting)]
        output = []
        for table_name, winner_loser, analyses in tables:
            rows = [analysis.get_table_row() for analysis in analyses if not analysis.is_empty()]
            str_rows = "".join(rows).format(username=self.username, user_id=self.user_id, winner_loser=winner_loser)
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
        if not self.tournaments:
            return '<p class="mt-3">No tournaments</p>'
        rows = [tourney.get_table_row() for tourney in self.tournaments]
        links = f'https://lichess.org/@/{self.username}/tournaments/recent'
        table = f'''<table id="tournaments_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
              <thead><tr>
                <th class="text-left" style="cursor:default;"><button class="btn btn-primary p-0" style="min-width:120px;" 
                    onclick="copyTextToClipboard('{links}')">Tournaments</button></th>
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
        return table


def add_variant_rating(ratings, variant, rating):
    if variant in ratings:
        ratings[variant].append(rating)
    else:
        ratings[variant] = [rating]


def get_boost_data(username):
    global boosts
    now = datetime.now()
    user_id = username.lower()
    boost, last_update = boosts.get(user_id, (None, None))
    if boost:
        delta = now - last_update
        if delta.days*24*60*60 + delta.seconds < BOOST_UPDATE_PERIOD:
            return boost
    boost = Boost(username)
    try:
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = f"https://lichess.org/api/user/{username}"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            user = r.json()
            boost.set(user)
            boosts[user_id] = boost, now
        else:
            boost.errors.append(f"ERROR /api/user/: Status Code {r.status_code}")
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        boost.errors.append(str(exception))
    except:
        boost.errors.append("ERROR")
    return boost
