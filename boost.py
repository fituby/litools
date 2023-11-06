import statistics
from datetime import datetime, timedelta
from dateutil import tz
import time
from collections import defaultdict
import math
from threading import Thread
import pygal
from pygal.style import DarkGreenBlueStyle, BlueStyle
from api import ApiType
from elements import get_user, shorten, delta_s, log, log_exception
from elements import get_notes, add_note, load_mod_log, get_mod_log, add_variant_rating
from elements import ModActionType, WarningStats, User, Games, Variants, PerfType
from elements import warn_sandbagging, warn_boosting, mark_booster
from elements import needs_to_refresh_insights, set_insights_refreshed, render
from consts import *


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


class StatsDesc:
    def __init__(self, abbr, score, median, nums_per_variant, is_sandbagging):
        self.abbr = abbr
        self.score = score
        self.median = median
        self.nums_per_variant = nums_per_variant
        self.is_sandbagging = is_sandbagging

    def info(self):
        if not self.nums_per_variant:
            return ""
        info_rating_diff = ""
        str_against = "opponents" if self.is_sandbagging else "@{username}"
        if self.median >= BOOST_SIGNIFICANT_RATING_DIFF:
            info_rating_diff = f'mostly vs higher rated {str_against} — '
        elif self.median <= -BOOST_SIGNIFICANT_RATING_DIFF:
            info_rating_diff = f'mostly vs lower rated {str_against} — '
        if len(self.nums_per_variant) == 1:
            variant, num = self.nums_per_variant[0]
            str_variants = f"{variant}" if num == 1 else f"all {num} {variant}"
        else:
            str_variants = " + ".join([f"{num} {variant}" for variant, num in self.nums_per_variant])
        return f" ({info_rating_diff}{str_variants})"


class GameAnalysis:
    def __init__(self, max_num_moves, is_sandbagging):
        self.max_num_moves = max_num_moves
        self.streak = StatsData()  # exclude opponent's early resignations?
        self.all_games = StatsData()
        self.bad_games = StatsData()
        self.resign = StatsData()
        self.timeout = StatsData()
        self.out_of_time = StatsData()
        self.opponents = defaultdict(int)
        self.is_sandbagging = is_sandbagging
        self.skip_atomic_streaks = is_sandbagging
        self.score = 0
        self.row = ""
        self.is_best = False

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

    def get_stats_desc(self, stats, *, limits=None, text_classes=None, exclude_variants=None, precision=10):
        if stats.num == 0:
            return StatsDesc('&ndash;', 0, 0, [], self.is_sandbagging)
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
        abbr = f'<abbr title="{str_info}"{color} style="text-decoration:none;">{stats_num:,}</abbr>'
        return StatsDesc(abbr, score, median, nums, self.is_sandbagging)

    def calc(self):
        self.score = 0
        if self.is_empty():
            self.row = ""
            return
        stats_bad_games = self.get_stats_desc(self.bad_games)
        exclude_variants = ['atomic'] if self.skip_atomic_streaks and self.max_num_moves > 1 else None
        stats_streak = self.get_stats_desc(self.streak, limits=[BOOST_SUS_STREAK, BOOST_SUS_STREAK],
                                           exclude_variants=exclude_variants)
        stats_resign = self.get_stats_desc(self.resign)
        stats_timeout = self.get_stats_desc(self.timeout)
        if self.max_num_moves <= 1:
            stats_out_of_time = self.get_stats_desc(self.out_of_time, text_classes=["text-success", "text-success"])
            stats_out_of_time.score = 0
        else:
            stats_out_of_time = self.get_stats_desc(self.out_of_time)
        self.score = stats_bad_games.score + stats_streak.score + stats_resign.score + \
            stats_timeout.score + stats_out_of_time.score
        if self.max_num_moves > 10:
            self.score /= 2
        num_moves = 1 if self.max_num_moves == 0 else self.max_num_moves
        winner_loser = "loser" if self.is_sandbagging else "winner"
        max_date = datetime.now(tz=tz.tzutc()) + timedelta(days=1)
        link = f'https://lichess.org/@/{{username}}/search?dateMax={max_date:%Y-%m-%d}&turnsMax={num_moves}{{perf_index}}' \
               f'&mode=1&players.a={{user_id}}&players.{winner_loser}={{user_id}}&sort.field=d&sort.order=desc'
        link_open = f'<a class="ml-2" href="{link}" target="_blank">open</a>'
        add_info = []
        if self.resign.num >= BOOST_NUM_RESIGN_REPORTABLE:
            add_info.append(f"resigned {self.resign.num} games {stats_resign.info()}")
        if self.timeout.num >= BOOST_NUM_TIMEOUT_REPORTABLE:
            add_info.append(f"left the game in {self.timeout.num} games{stats_timeout.info()}")
        if self.out_of_time.num >= BOOST_NUM_OUT_OF_TIME_REPORTABLE:
            add_info.append(f"out of time in {self.out_of_time.num} games{stats_out_of_time.info()}")
        info = f'{link}'
        if add_info or self.streak.num >= BOOST_STREAK_REPORTABLE or stats_bad_games.score >= 1:
            won_lost = "lost" if self.is_sandbagging else "won"
            info = f"{info}\nIn the only game" if self.all_games.num == 1 else f'{info}\nAmong {self.all_games.num} games'
            info = f"{info}{{info_games_played}}"
            if self.all_games.num == 100 or self.all_games.num < 30:
                info = f'{info}, they {won_lost} {self.bad_games.num} games'
            else:
                perc = int(round(100 * self.bad_games.num / self.all_games.num)) if self.all_games.num else 0
                info = f'{info}, they {won_lost} {perc}% of their games'
            if self.max_num_moves == 0:
                info = f'{info} without making a single move'
            else:
                info = f'{info} in {self.max_num_moves} moves or less'
            if add_info:
                str_opp = ": " if self.is_sandbagging else ": their opponents "
                info = f'{info}{str_opp}{", ".join(add_info)}'
            if self.streak.num >= BOOST_STREAK_REPORTABLE:
                str_incl = "including" if self.streak.num < self.bad_games.num else "i.e."
                info = f'{info}, {str_incl} {self.streak.num} games streak'
            info = f"{info}."
        self.row = f'''<tr>
                    <td class="text-left"><button class="btn btn-primary p-0" style="min-width: 120px;" 
                        onclick="add_to_notes(this)" data-selection=\'{info}\'>{self.max_num_moves}</button>{link_open}</td>
                    <td class="text-right pr-2">{stats_bad_games.abbr}</td>
                    <td class="text-center px-2">{stats_streak.abbr}</td>
                    <td class="text-right pr-2">{stats_resign.abbr}</td>
                    <td class="text-right pr-2">{stats_timeout.abbr}</td>
                    <td class="text-right pr-2">{stats_out_of_time.abbr}</td>
                  </tr>'''

    def set_best_row(self):
        self.is_best = True
        self.row = self.row.replace("btn-primary", "btn-warning")

    def get_frequent_opponents(self):
        if not self.is_best:
            return ""
        game_threshold = max(BOOST_NUM_GAMES_FREQUENT_OPP, int(math.ceil(self.bad_games.num * BOOST_PERCENT_FREQUENT_OPP)))
        opponents = [(opp_name, num_games) for opp_name, num_games in self.opponents.items() if num_games >= game_threshold]
        if not opponents:
            return ""
        opponents.sort(key=lambda name_num: name_num[1], reverse=True)
        num_moves = 1 if self.max_num_moves == 0 else self.max_num_moves
        opps = []
        for opp_name, num_games in opponents:
            winner_loser = "loser" if self.is_sandbagging else "winner"
            link = f'https://lichess.org/@/{{username}}/search?turnsMax={num_moves}&mode=1&players.a={{user_id}}' \
                   f'&players.b={opp_name.lower()}&players.{winner_loser}={{user_id}}&sort.field=d&sort.order=desc'
            btn_class = "btn-warning" if num_games >= 5 else "btn-primary"
            opps.append(f'<span class="d-flex flex-wrap align-items-baseline"><button class="btn {btn_class} py-0 mr-1" '
                        f'onclick="add_to_notes(this)" data-selection=\'{link}\'>{num_games} games</button> '
                        f'<a href="{link}" target="_blank"> vs {opp_name}</a></span>')
        separator = '<span class="mx-1">,</span>'
        return f'<div class="d-flex flex-wrap mt-1"><div>Frequent opponent{"" if len(opps) == 1 else "s"} in games with ' \
               f'&le;{self.max_num_moves} moves:</div>{separator.join(opps)}</div>'

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

    def download(self, mod):
        if self.is_arena:
            url = f"https://lichess.org/api/tournament/{self.tournament_id}"
            r = mod.api.get(ApiType.ApiTournamentId, url, token=mod.token)
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
            arena_res = mod.api.get_ndjson(ApiType.ApiTournamentResults, url, mod.token)
            for player in arena_res:
                if player['username'].lower() == self.user_id:
                    self.place = player['rank']
                    self.score = player['score']
                    self.performance = player['performance']
                    break
        else:
            url = f"https://lichess.org/api/swiss/{self.tournament_id}/results?nb={MAX_NUM_TOURNEY_PLAYERS}"
            swiss_res = mod.api.get_ndjson(ApiType.ApiSwissResults, url, mod.token)
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


class BoostGames(Games):
    def __init__(self, user_id, max_num_games):
        super().__init__(user_id, max_num_games, 182, STATUSES_TO_DISCARD_BOOST, PERCENT_EXTRA_GAMES_TO_DOWNLOAD)
        self.arena_tournaments = {}
        self.swiss_tournaments = {}
        self.median_rating = {}

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
            streak = {}
            best_streak = {}
            analysis.opponents.clear()
            is_last_game_bad = False
            last_game_end = None
            for game in self.games:
                if not game['rated']:
                    raise Exception("Error games: not a rated game")
                status = game['status']
                if status not in STATUSES_TO_DISCARD_BOOST:
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
                            opp_name = game['players'][opp_color]['user']['name']
                            analysis.opponents[opp_name] += 1
                            createdAt = datetime.fromtimestamp(game['createdAt'] // 1000, tz=tz.tzutc())
                            delta = (createdAt - last_game_end) if last_game_end else None
                            if is_last_game_bad and last_game_end and delta.total_seconds() <= BOOST_STREAK_TIME:
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
    def __init__(self, username, num_games, before, perf_type):
        self.user = User(username)
        self.before = before
        self.perf_type = perf_type
        self.errors = []
        self.variants = Variants(add_note_links=True)
        self.games = BoostGames(self.user.id, num_games)
        self.sandbagging = []
        self.boosting = []
        self.tournaments = []
        self.last_update_tournaments: datetime = None
        self.enable_sandbagging = False
        self.enable_boosting = False
        self.prefer_marking = False
        self.perf_charts = ""
        self.perf_thread = None
        self.mod_log: ModLogData = None
        self.mod_log_out = ""
        self.info_games_played = ""
        self.is_ready = False
        self.output: dict = None
        self.output_tournaments: dict = None

    def get_errors(self):
        if not self.errors:
            return ""
        return f'<div class="text-warning"><div>{"</div><div>".join(self.errors)}</div></div>'

    def get_info_1(self, mod):
        main = self.user.get_user_info(BOOST_CREATED_DAYS_AGO, BOOST_NUM_PLAYED_GAMES)
        num_games = self.games.get_num()
        analysis = self.get_analysis()
        if analysis:
            analysis = f'<div class="my-3">{analysis}</div>'
        best_tournaments = f'<a href="https://lichess.org/@/{self.user.name}/tournaments/best" target="_blank" ' \
                           f'class="btn btn-secondary flex-grow-1 py-0 mr-1" role="button">Best tournaments&hellip;</a>'
        games = f'<a href="https://lichess.org/mod/{self.user.name}/games" target="_blank" ' \
                f'class="btn btn-secondary flex-grow-1 py-0" role="button">Games&hellip;</a>'
        if mod.boost_ring_tool:
            class_boost_ring = "btn-warning" if self.enable_sandbagging and self.enable_boosting else "btn-secondary"
            additional_tools = f'<div class="d-flex justify-content-between mb-2 px-1">' \
                               f'<a href="https://{mod.boost_ring_tool}/?user={self.user.name}" target="_blank" ' \
                               f'class="btn {class_boost_ring} flex-grow-1 py-0 mr-1" ' \
                               f'role="button">Boost ring tool&hellip;</a>{best_tournaments}{games}</div>'
        else:
            additional_tools = f'<div class="d-flex justify-content-between mb-2 px-1">{best_tournaments}{games}</div>' \
                               f'<div class="text-warning mb-2">No permissions to work with mod data</div>'
        return f"{main}{num_games}{self.get_errors()}{analysis}{additional_tools}"

    def get_info_2(self):
        variants = self.variants.get_table(len(self.games))
        if variants:
            variants = f'<div class="my-3">{variants.format(username=self.user.name)}</div>'
        profile = self.user.get_profile()
        if profile:
            profile = f'<div class="my-3">{profile}</div>'
        return f"{variants}{profile}"

    def get_mod_notes(self, mod_log_data, mod):
        mod_notes = get_notes(self.user.name, mod, mod_log_data) if mod.is_mod() else ""
        header_notes = "Notes:" if mod_notes else "No notes"
        return {'mod-notes': mod_notes, 'notes-header': header_notes}

    def get_enabled_buttons(self):
        return {'enable-sandbagging': 1 if self.enable_sandbagging and not self.prefer_marking else 0,
                'enable-boosting': 1 if self.enable_boosting and not self.prefer_marking else 0,
                'enable-marking': 1 if self.prefer_marking and (self.enable_sandbagging or self.enable_boosting)
                                       else -1 if self.user.is_titled() else 0}

    def set(self, user, mod):
        self.user.set(user)
        if self.user.disabled:
            self.errors.append('Account closed')
        else:
            perfs = user.get('perfs', {})
            self.variants.set(perfs)
        self.update_mod_log(mod)
        self.analyse_games(mod)
        self.analyse_perf(mod)

    def analyse_games(self, mod):
        exc: Exception = None
        try:
            self.games.download(mod, self.mod_log.time_last_manual_warning, self.before, self.perf_type)
            if self.games.until and delta_s(datetime.now(tz=tz.tzutc()), self.games.until) > 30*60:
                self.info_games_played = f' played before {self.games.until:%Y-%m-%d %H:%M} UTC'
            else:
                self.info_games_played = ""
            if len(self.games) != self.games.max_num_games and self.games.since:
                since = datetime.fromtimestamp(self.games.since // 1000, tz=tz.tzutc())
                self.info_games_played += ' and' if self.info_games_played else ' played'
                self.info_games_played += f' since the previous warning on {since:%Y-%m-%d} at {since:%H:%M} UTC'

        except Exception as e:
            exc = e
        self.sandbagging = self.games.analyse(True)
        self.boosting = self.games.analyse(False)
        self.variants.set_rating_ranges(self.games)
        for sandbag in self.sandbagging:
            sandbag.check_variants(self.variants)
        if exc:
            raise exc

    def analyse_perf(self, mod):
        if self.perf_thread is None:
            self.perf_thread = Thread(name="fetch_performance", target=self.fetch_performance, args=(mod,))
            self.perf_thread.start()

    def fetch_performance(self, mod):
        self.perf_charts = ""
        try:
            now = datetime.now()
            variant, num_games = self.variants.get_most_played_variant()
            if not variant:
                raise Exception("Performance error: No games")
            if needs_to_refresh_insights(self.user.id, now):
                url_refresh = f'https://lichess.org/insights/refresh/{self.user.id}'
                r = mod.api.post(ApiType.InsightsRefresh, url_refresh, token=mod.token)
                if r.status_code != 200:
                    raise Exception("Performance error: Failed to refresh insights")
                set_insights_refreshed(self.user.id, now)
            url = f'https://lichess.org/insights/data/{self.user.id}'
            headers = {'Content-Type': "application/json"}
            data = {'metric': "performance", 'dimension': "date", 'filters': {'variant': [variant]}}
            r = mod.api.post(ApiType.InsightsData, url, token=mod.token, json=data, headers=headers)
            if r.status_code != 200:
                raise Exception("Performance error: Failed to fetch insights")
            chart, sizes, dates = Boost.plot_chart(r.json(), mod)
            title = f"Performance in {variant[0].upper()}{variant[1:]}"
            link = f"https://lichess.org/insights/{self.user.id}/performance/date/variant:{variant}"
            button = f'<button class="btn btn-primary mt-3 py-0" onclick="add_to_notes(this)" ' \
                     f'data-selection=\'{link}\'>{title}</button>'
            self.perf_charts = f'<div class="d-flex align-items-baseline justify-content-center">{button}' \
                               f'<a class="ml-2" href="{link}" target="_blank">open</a></div>{chart}'
            if num_games >= 20 and sum(sizes) > 3 * num_games:
                n = 0
                cumulative_size = 0
                for i in range(len(sizes) - 1, -1, -1):
                    n += 1
                    cumulative_size += sizes[i]
                    if cumulative_size >= num_games:
                        break
                if n < 0.6 * len(sizes):
                    period = (now - datetime.fromtimestamp(dates[-n])).days
                    period = min(int(1.2 * period), period + 14)
                    if 300 < period < 400:
                        period = 365
                    elif 150 < period < 200:
                        period = 182
                    elif period > 60:
                        period = int(math.ceil(period / 30)) * 30
                    elif period > 30:
                        period = int(math.ceil(period / 10)) * 10
                    data['filters']['period'] = [str(period)]
                    r = mod.api.post(ApiType.InsightsData, url, token=mod.token, json=data, headers=headers)
                    if r.status_code != 200:
                        raise Exception("Performance error: Failed to fetch insights with a period")
                    chart, _, _ = Boost.plot_chart(r.json(), mod)
                    link = f"https://lichess.org/insights/{self.user.id}/performance/date/" \
                           f"variant:{variant}/period:{period}"
                    button = f'<button class="btn btn-primary mt-2 py-0" onclick="add_to_notes(this)" ' \
                             f'data-selection=\'{link}\'>The last {period} day{"" if period == 1 else "s"}</button>'
                    self.perf_charts = f'{self.perf_charts}<div class="d-flex align-items-baseline justify-content-center">'\
                                       f'{button}<a class="ml-2" href="{link}" target="_blank">open</a></div>{chart}'
        except:
            pass

    @staticmethod
    def plot_chart(res, mod, title=None):
        sizes = res['sizeSerie']['data']
        dates = res['xAxis']['categories']
        perfs = res['series'][0]['data']
        max_perf = int(math.ceil(max(perfs) / 100)) * 100
        coef = 1.2 * max(sizes) / max_perf
        scaled_sizes = [{'value': s / coef, 'style': f'fill: grey; stroke: grey;'} for s in sizes]
        chart = pygal.Bar(title=title, width=CHART_WIDTH_BOOST, x_label_rotation=315, range=(600, max_perf))
        chart.add("Performance", [int(p) for p in perfs])
        chart.add("Number of games", scaled_sizes, formatter=lambda x: f'{x * coef:0.0f}')
        chart.x_labels = [f"{datetime.fromtimestamp(d, tz=tz.tzutc()):%Y-%m-%d}" for d in dates]
        chart.show_legend = False
        is_dark_mode = not mod.view.theme_color.upper().startswith("#FFF")
        style = DarkGreenBlueStyle if is_dark_mode else BlueStyle
        perf_charts = render(chart, style, mod.view.theme_color)
        return perf_charts, sizes, dates

    def update_mod_log(self, mod):
        mod_log_data = load_mod_log(self.user.name, mod) if mod.is_mod() else None
        self.mod_log = ModLogData(mod_log_data)
        self.mod_log_out = self.mod_log.prepare(mod)

    def analyse_tournaments(self, mod):
        try:
            now = datetime.now()
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
                tourney.download(mod)
                self.tournaments.append(tourney)
                t1 = time.time()
            # Output
            #self.tournaments.sort(key=lambda tourney: tourney.num_games, reverse=True)
            self.last_update_tournaments = now
        except Exception as exception:
            log_exception(exception)
        # Output tournaments
        if not self.prefer_marking and not self.user.is_titled():
            for tourney in self.tournaments:
                if tourney.is_official and tourney.name.startswith('≤') and tourney.place and 1 <= tourney.place <= 3:
                    self.prefer_marking = True
                    break
        output = self.get_enabled_buttons()
        if self.tournaments:
            rows = [tourney.get_table_row() for tourney in self.tournaments]
            link = f'https://lichess.org/@/{self.user.name}/tournaments/recent'
            table = f'''<table id="tournaments_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
                  <thead><tr>
                    <th class="text-left" style="cursor:default;">
                        <button class="btn btn-primary p-0" style="min-width:120px;" 
                            onclick="add_to_notes(this)" data-selection=\'{link}\'>Tournaments</button>
                        <a class="ml-2" href="{link}" target="_blank">open</a>
                    </th>
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
        else:
            output['tournaments'] = '<p class="mt-3">No tournaments</p>'
        if self.perf_thread:
            self.perf_thread.join()
        self.perf_thread = None
        output['performance'] = self.perf_charts
        if self.user.is_error:
            mod.boost_cache.pop(self.user.id, None)
        self.output_tournaments = output

    def get_analysis(self):
        perf_index = f"&perf={PerfType.to_index(self.perf_type)}" if bin(self.perf_type).count("1") == 1 else ""
        tables = [("Sandbagging", self.sandbagging), ("Boosting", self.boosting)]
        output = []
        for table_name, analyses in tables:
            rows = [analysis.row for analysis in analyses if not analysis.is_empty()]
            str_rows = "".join(rows).format(username=self.user.name, user_id=self.user.id,
                                            info_games_played=self.info_games_played, perf_index=perf_index)
            opponents = [analysis.get_frequent_opponents() for analysis in analyses]
            str_opps = "".join(opponents).format(username=self.user.name, user_id=self.user.id)
            if rows:
                table = f'''<table id="{table_name.lower()}_table" class="table table-sm table-striped table-hover 
                            text-center text-nowrap mt-3 mb-0">
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
                    </table>{str_opps}'''
            else:
                table = f'<p class="mt-3">No {table_name.lower()}</p>'
            output.append(table)
        return '\n'.join(output)

    def get_tournaments(self, mod):
        if not self.is_ready:
            return NOT_READY
        if self.output_tournaments:
            now = datetime.now()
            if self.last_update_tournaments:
                if delta_s(now, self.last_update_tournaments) >= BOOST_UPDATE_PERIOD:
                    self.output_tournaments = None
            if self.output_tournaments is not None:
                return self.output_tournaments
        if self.output_tournaments is not None:
            return NOT_READY
        self.output_tournaments = {}
        Thread(name="analyse_tournaments", target=self.analyse_tournaments, args=(mod,)).start()
        return NOT_READY

    @staticmethod
    def calc_badness(value, limits):
        return 1 if value <= limits[0] else 0 if value >= limits[1] else ((limits[1] - value) / (limits[1] - limits[0]))

    def enable_buttons(self, mod_log):
        if mod_log.is_engine or mod_log.is_boost:
            self.prefer_marking = True
            self.disable_buttons()
            return
        if self.user.createdAt is None:
            self.disable_buttons()
            return  # account closed
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
            else:
                for variant in self.variants:
                    if not variant.stable_rating_range:
                        continue
                    rating_diff = variant.stable_rating_range[1] - variant.stable_rating_range[0]
                    if rating_diff >= BOOST_SUS_RATING_DIFF[1]:
                        self.prefer_marking = True
                        break
                    badness = Boost.calc_badness(self.user.num_rated_games, BOOST_NUM_PLAYED_GAMES)
                    badness += Boost.calc_badness(days, BOOST_CREATED_DAYS_AGO)
                    if badness > 1 and rating_diff != 0 and variant.stable_rating_range[1] >= BOOST_MIN_DECENT_RATING:
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

    def get_output(self, mod):
        if not self.is_ready:
            return NOT_READY
        if self.output:
            return self.output
        if self.output is not None:
            return NOT_READY
        self.output = {}
        Thread(name="set_output", target=self.set_output, args=(mod,)).start()
        return NOT_READY

    def set_output(self, mod):
        output = {}
        before = self.get_datetime_before()
        if not self.before:
            self.before = before
        if not self.user.is_error:
            try:
                if not self.mod_log:
                    self.update_mod_log(mod)
                self.enable_buttons(self.mod_log)
                output['mod-log'] = self.mod_log_out
                output.update(self.get_mod_notes(self.mod_log.data, mod))
                output.update(self.get_enabled_buttons())
            except Exception as exception:
                log_exception(exception)
        # After self.enable_buttons():
        output.update({'part-1': self.get_info_1(mod), 'part-2': self.get_info_2(),
                       'num-games': self.games.max_num_games, 'datetime-before': before})
        self.output = output


def get_boost_data(username, mod, num_games=None, before=None, perf_type=None):
    now = datetime.now()
    user_id = username.lower()
    boost, last_update = mod.boost_cache.get(user_id, (None, None))
    if num_games:
        num_games = int(num_games)
    if perf_type:
        perf_type = int(perf_type)
    if boost and (boost.before == before or not before) and (boost.perf_type == perf_type or not perf_type) \
            and (boost.games.max_num_games == num_games or num_games is None):
        if delta_s(now, last_update) < BOOST_UPDATE_PERIOD:
            return boost
    if not num_games:
        num_games = BOOST_NUM_GAMES[0]
    boost = Boost(username, num_games, before, perf_type)
    Thread(name="set_boost", target=set_boost, args=(boost, username, mod)).start()
    mod.boost_cache[user_id] = boost, now
    for user_id in list(mod.boost_cache.keys()):
        if delta_s(now, mod.boost_cache[user_id][1]) >= BOOST_UPDATE_PERIOD:
            del mod.boost_cache[user_id]
    return boost


def set_boost(boost, username, mod):
    user, api_error = get_user(username, mod)
    if api_error:
        boost.user.is_error = True
        boost.errors.append(api_error)
    else:
        boost.set(user, mod)
    boost.is_ready = True


def send_boost_note(note, username, mod):
    user_id = username.lower()
    boost, last_update = mod.boost_cache.get(user_id, (None, None))
    try:
        if not boost or not note or not username:
            raise Exception(f"Wrong note: [{username}]: {note}")
        is_ok = add_note(username, note, mod)
        if is_ok:
            mod_notes = get_notes(username, mod)
            header_notes = "Notes:" if mod_notes else "No notes"
            return {'mod-notes': mod_notes, 'notes-header': header_notes, 'user': username}
    except Exception as exception:
        log_exception(exception)
        try:
            boost.errors.append(str(exception))
        except:
            log("Error: no boost instance", to_print=True, to_save=True)
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

    def process(self, mod):
        self.num_other_actions = 0
        self.time_last_manual_warning = None
        self.mod_log_table, actions = get_mod_log(self.data, mod, ModActionType.Boost)
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

    def prepare(self, mod):
        if self.data is None:
            return "Mod Log is not available"
        self.process(mod)
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


def send_mod_action(action, username, mod):
    output = {'user': username, 'mod-log': "", 'enable-sandbagging': -1, 'enable-boosting': -1, 'enable-marking': -1}
    user_id = username.lower()
    boost, last_update = mod.boost_cache.get(user_id, (None, None))
    if boost:
        try:
            output.update(boost.get_enabled_buttons())
            if action == "warn_sandbagging":
                is_ok = warn_sandbagging(username, mod)
            elif action == "warn_boosting":
                is_ok = warn_boosting(username, mod)
            elif action == "mark_booster":
                is_ok = mark_booster(username, mod)
            else:
                raise Exception(f"Wrong mod action: [{username}]: {action}")
            log(f"{username}: {action} -> {'DONE' if is_ok else 'skipped'}", to_print=True, to_save=True, verbose=2)
            if is_ok:
                boost.update_mod_log(mod)
                return {'user': username, 'mod-log': boost.mod_log_out,
                        'enable-sandbagging': -1, 'enable-boosting': -1, 'enable-marking': -1}
        except Exception as exception:
            log_exception(exception)
            try:
                boost.errors.append(str(exception))
            except:
                log(f"Error: no boost instance for {username}", to_print=True, to_save=True)
    return output
