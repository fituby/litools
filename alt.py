import re
from datetime import datetime
from dateutil import tz
from collections import defaultdict
import pygal
from pygal.style import DefaultStyle, DarkStyle, BlueStyle, DarkGreenBlueStyle
from enum import Enum
from threading import Thread
from api import ApiType
from elements import UserData, Games, Variants, ModActionType, PerfType
from elements import get_tc, delta_s, deltainterval, datetime_to_ago, get_user_ids, log, log_exception
from elements import load_mod_log, get_mod_log, get_notes
from elements import needs_to_refresh_insights, set_insights_refreshed, render
from consts import *


class Color(Enum):
    black = "Black"
    white = "White"


class OpeningStage(Enum):
    openingFamily = "Openings"
    openingVariation = "Opening Variations"


def download_openings(user_id, color, opening_stage, mod, to_refresh=False):
    try:
        if to_refresh:
            url_refresh = f'https://lichess.org/insights/refresh/{user_id}'
            r = mod.api.post(ApiType.InsightsRefresh, url_refresh, token=mod.token)
            if r.status_code != 200:
                log(f"Failed to refresh insights for @{user_id}: Status {r.status_code}", to_print=True, to_save=True)
        url = f'https://lichess.org/insights/data/{user_id}'
        headers = {'Content-Type': "application/json"}
        data = {"metric": "opponentRating", "dimension": opening_stage.name, "filters": {"color": [color.name]}}
        # ... "filters":{"variant": ["rapid"], "period": ["60"]}}'
        r = mod.api.post(ApiType.InsightsData, url, token=mod.token, json=data, headers=headers)
        if r.status_code != 200:
            return None
        res = r.json()
        names = res['xAxis']['categories']
        counts = res['sizeSerie']['data']
        if not names or not counts or len(names) != len(counts):
            return None
        num_games = sum(counts)
        if num_games == 0:
            return None
        for i in range(len(counts)):
            counts[i] = counts[i] * 100 / num_games
        output = [(names[i], counts[i]) for i in range(len(names))]
        output.sort(key=lambda p: p[1], reverse=True)
        return output
    except:
        return None


class Alt:
    team_cache = {}  # TODO: based on `alt_cache`s, clear to prevent memory leak?

    def __init__(self, username, num_games, date_begin, date_end, mod):
        if not num_games:
            num_games = MAX_NUM_GAMES_TO_DOWNLOAD
        else:
            try:
                num_games = int(num_games)
            except:
                num_games = MAX_NUM_GAMES_TO_DOWNLOAD
        self.date_begin = date_begin
        self.date_end = date_end
        self.user = UserData(username, mod)
        self.games = Games(self.user.id, min(MAX_NUM_GAMES_TO_DOWNLOAD, num_games), ALT_MAX_PERIOD_FOR_GAMES,
                           STATUSES_TO_DISCARD_ALT, download_moves=False, only_rated=False)
        self.mutual_games = defaultdict(list)
        self.datetime_first_game: datetime = None
        self.datetime_last_move: datetime = None
        self.hist_hours = [0.0] * 12
        self.hist_tcs = defaultdict(float)
        self.hist_days = [0.0] * 7
        self.hist_openings = {}
        for color in Color:
            self.hist_openings[color] = {}
            for opening_stage in OpeningStage:
                self.hist_openings[color][opening_stage] = None
        self.variants = Variants()
        perfs = self.user.data.get('perfs', {}) if self.user.data else {}
        if perfs:
            self.variants.set(perfs)
        self.teams = set()
        self.num_mod_log_items = 0
        self.mod_notes = ""
        self.time_step1: datetime = None
        self.time_step2: datetime = None

    def download(self, alt_ids, mod):
        if self.user.is_error:
            return
        now = datetime.now()
        if not self.time_step2 or delta_s(now, self.time_step2) >= ALT_UPDATE_PERIOD:
            date_begin = f"{self.date_begin}T00:00" if self.date_begin else None
            date_end = f"{self.date_end}T23:59" if self.date_end else None
            since = None
            if date_begin:
                try:
                    since = datetime.strptime(date_begin, '%Y-%m-%dT%H:%M').replace(tzinfo=tz.tzutc())
                except Exception as exception:
                    log_exception(exception)
            self.games.download(mod, since=since, before=date_end, perf_type=PerfType.all_but_correspondence())
            self.time_step2 = now
        self.mutual_games.clear()
        self.hist_hours = [0.0] * 12
        self.hist_tcs = defaultdict(float)
        self.hist_days = [0.0] * 7
        if self.user.disabled and 'Account closed' not in self.user.errors:
            self.user.errors.append('Account closed')
        else:
            self.variants.set_rating_ranges(self.games)
        for game in self.games:
            dt_start = datetime.fromtimestamp(game['createdAt'] // 1000, tz=tz.tzutc())
            if self.datetime_first_game is None or dt_start < self.datetime_first_game:
                self.datetime_first_game = dt_start
            dt_end = datetime.fromtimestamp(game['lastMoveAt'] // 1000, tz=tz.tzutc())
            if self.datetime_last_move is None or dt_end > self.datetime_last_move:
                self.datetime_last_move = dt_end
            dt_mid = dt_start + (dt_end - dt_start) / 2
            self.hist_hours[dt_mid.hour // 2] += 1
            self.hist_days[dt_mid.weekday()] += 1
            white, black = get_user_ids(game)
            opp_name = black if white == self.user.id else white
            if opp_name in alt_ids:
                self.mutual_games[opp_name].append(game)
            self.hist_tcs[get_tc(game)] += 1
        num_games = sum(self.hist_hours)
        if num_games > 0:
            for i in range(len(self.hist_hours)):
                self.hist_hours[i] = self.hist_hours[i] * 100 / num_games
            for i in range(len(self.hist_days)):
                self.hist_days[i] = self.hist_days[i] * 100 / num_games
            for tc in self.hist_tcs.keys():
                self.hist_tcs[tc] = self.hist_tcs[tc] * 100 / num_games

    def download_openings(self, refresh_openings, mod):
        if self.user.is_error:
            return
        now = datetime.now()
        if self.time_step1 and delta_s(now, self.time_step1) < ALT_UPDATE_PERIOD \
                and (not refresh_openings or not needs_to_refresh_insights(self.user.id, now)):
            return
        for color in Color:
            for opening_stage in OpeningStage:
                wait_s = mod.api.get_waiting_time(ApiType.InsightsRefresh)
                to_refresh = needs_to_refresh_insights(self.user.id, now) and (wait_s <= 0)
                self.hist_openings[color][opening_stage] = download_openings(self.user.id, color, opening_stage, mod,
                                                                             to_refresh)
                if to_refresh:
                    set_insights_refreshed(self.user.id, now)
        self.time_step1 = now

    def download_teams(self, mod):
        if self.user.is_error:
            return
        now = datetime.now()
        if self.time_step1 and delta_s(now, self.time_step1) < ALT_UPDATE_PERIOD:
            return
        url = f'https://lichess.org/api/team/of/{self.user.id}'
        headers = {'Content-Type': "application/json"}
        r = mod.api.get(ApiType.ApiTeamOf, url, token=mod.token, headers=headers)
        if r.status_code != 200:
            return None
        teams = r.json()
        self.teams.update([team['id'] for team in teams])
        Alt.team_cache.update({team['id']: team['name'] for team in teams})

    def download_mod_log(self, mod):
        mod_log_data = load_mod_log(self.user.name, mod)
        if mod_log_data:
            self.user.mod_log, actions = get_mod_log(mod_log_data, mod, ModActionType.Alt)
            #                  ^ if necessary, actions can be replaced with self.user.actions
            self.num_mod_log_items = len(actions)
            self.mod_notes = get_notes(self.user.name, mod, mod_log_data)
        return bool(mod_log_data)

    # def download_following(self, mod):
    #     if self.user.is_error:
    #         return
    #     now = datetime.now()
    #     if self.time_step1 and delta_s(now, self.time_step1) < ALT_UPDATE_PERIOD:
    #         return
    #     url = f'https://lichess.org/@/{self.user.id}/following'
    #     headers = {'Content-Type': "application/json"}
    #     r = mod.api.get(ApiType.AtUsernameFollowing, url, token=mod.token, headers=headers)
    #     if r.status_code != 200:
    #         return None
    #     following = r.json()
    #     print(following)

    def get_mutual_teams_row(self, alts):
        team_names = sorted([Alt.team_cache[team] for team in self.teams])
        cells = [f'<td class="text-left">{self.user.get_name("?mod")}</td>'
                 f'<td class="text-center"><abbr title="{", ".join(team_names)}"'
                 f' style="text-decoration:none;">{len(self.teams)}</abbr></td>']
        for alt in alts:
            player_id = alt.user.id
            if player_id == self.user.id:
                cells.append('<td class="text-center">&mdash;</td>')
            else:
                mutual_teams = self.teams.intersection(alt.teams)
                if mutual_teams:
                    team_names = sorted([Alt.team_cache[team] for team in mutual_teams])
                    cells.append(f'<td class="text-center"><abbr title="{", ".join(team_names)}"'
                                 f' style="text-decoration:none;">{len(mutual_teams)}</abbr></td>')
                else:
                    cells.append('<td class="text-center">&mdash;</td>')
        row = f'<tr>{"".join(cells)}</tr>'
        return row

    def get_mutual_games(self, alt_names):
        output = []
        for opp, games in self.mutual_games.items():
            examples = []
            step = max(1, (len(games) - 1) // NUM_EXAMPLE_GAMES)
            for i in range(len(games) - 1, -1, -step):
                game_url = f"https://lichess.org/{games[i]['id']}"
                link = f'<a href="{game_url}" class="mx-1" target="_blank">{len(examples) + 1}</a>'
                examples.append(link)
                if len(examples) >= NUM_EXAMPLE_GAMES:
                    break
            str_examples = " ".join(examples)
            url = f'https://lichess.org/mod/{self.user.id}/games?opponents={opp}'
            output.append(f'<a href="{url}" class="text-danger" target="_blank">{len(games)}'
                          f' game{"" if len(games) == 1 else "s"}</a>'
                          f' vs {alt_names[opp]}: {str_examples}')
        return f'<div><b>{self.user.get_name("?mod")}</b>: <div>{"</div><div>".join(output)}</div></div>'\
            if output else ""

    def get_mutual_games_row(self, alts):
        cells = [f'<td class="text-left">{self.user.get_name("?mod")}</td>']
        for alt in alts:
            player_id = alt.user.id
            if player_id == self.user.id:
                cells.append('<td class="text-center">&mdash;</td>')
            elif player_id in self.mutual_games:
                url = f'https://lichess.org/mod/{self.user.id}/games?opponents={player_id}'
                link = f'<a href="{url}" class="text-danger" target="_blank">{len(self.mutual_games[player_id])}</a>'
                cells.append(f'<td class="text-center">{link}</td>')
            else:
                cells.append('<td class="text-center">&mdash;</td>')
        row = f'<tr>{"".join(cells)}</tr>'
        return row

    def get_errors(self):
        if not self.user.errors:
            return ""
        return f'<div class="text-warning"><div>{"</div><div>".join(self.user.errors)}</div></div>'

    def get_user_info(self):
        main = self.user.get_user_info(CHAT_CREATED_DAYS_AGO, CHAT_NUM_PLAYED_GAMES)
        num_games = self.games.get_num()
        variants = self.variants.get_table(len(self.games))
        if variants:
            variants = f'<div class="my-3">{variants}</div>'
        profile = self.user.get_profile()
        if profile:
            profile = f'<div class="my-3">{profile}</div>'
        header = f'Mod Log: <b>{self.num_mod_log_items}</b> item{"" if self.num_mod_log_items == 1 else "s"}'
        id_collapse = f'collapseModLog_{self.user.id}'
        mod_log = f'<div><div class="card border-0"><div>' \
                  f'<button class="btn btn-secondary col py-0" type="button" data-toggle="collapse" ' \
                  f'data-target="#{id_collapse}" aria-expanded="false" aria-controls="{id_collapse}">{header}</button>' \
                  f'</div><div id="{id_collapse}" class="collapse">' \
                  f'<div class="card card-body p-0">{self.user.mod_log}</div></div></div>' if self.user.mod_log else ""
        return f"{main}{num_games}{profile}{self.mod_notes}{mod_log}{variants}{self.get_errors()}"


class OverlappingGames:
    def __init__(self, my_game, opp_game):
        self.my_game = my_game
        self.opp_game = opp_game
        t1 = max(my_game['createdAt'], opp_game['createdAt'])
        t2 = min(my_game['lastMoveAt'], opp_game['lastMoveAt'])
        self.interval_s = max(0, (t2 - t1) / 1000)


def get_alt(user_id, num_games, date_begin, date_end, mod):
    now = datetime.now()
    alt, last_update = mod.alt_cache.get(user_id, (None, None))
    if num_games:
        num_games = int(num_games)
    if alt and (alt.games.max_num_games == num_games) and (alt.date_begin == date_begin) and (alt.date_end == date_end):
        if delta_s(now, last_update) < ALT_UPDATE_PERIOD:
            return alt
    for user_i in list(mod.alt_cache.keys()):
        if delta_s(now, mod.alt_cache[user_i][1]) >= ALT_UPDATE_PERIOD:
            del mod.alt_cache[user_i]
    alt = Alt(user_id, num_games, date_begin, date_end, mod)
    mod.alt_cache[user_id] = alt, now
    return alt


class Alts:
    @staticmethod
    def get_usernames(names):
        usernames = re.findall(r'\b[-\w]{3,}\b', names)
        unique_usernames = []
        unique_ids = set()
        for name in usernames:
            user_id = name.lower()
            if user_id not in unique_ids:
                unique_usernames.append(user_id)
                unique_ids.add(user_id)
        return unique_usernames

    @staticmethod
    def get_response(step, alt_names, num_games, date_begin, date_end, force_refresh_openings, mod):
        if date_begin:
            date_begin = date_begin[:10]
        if date_end:
            date_end = date_end[:10]
        now = datetime.now()
        usernames = Alts.get_usernames(alt_names)
        alts_key = (",".join(usernames), num_games, date_begin, date_end)
        alts, last_update = mod.alt_group_cache.get(alts_key, (None, None))
        if not alts or delta_s(now, last_update) >= ALT_UPDATE_PERIOD:
            alts = Alts(mod.view.theme_color)
            mod.alt_group_cache[alts_key] = alts, now
            for key_i in list(mod.alt_group_cache.keys()):
                if delta_s(now, mod.alt_group_cache[key_i][1]) >= ALT_UPDATE_PERIOD:
                    del mod.alt_group_cache[key_i]
        if alts.errors:
            return {'part-1': alts.get_errors(), 'part-2': "", 'part-3': ""}
        if not alts.is_step0:
            if alts.is_step0 is None:
                alts.is_step0 = False
                Thread(name="alts_set", target=alts.set, args=(usernames, num_games, date_begin, date_end, mod)).start()
            return NOT_READY
        try:
            step = int(step)
        except:
            step = 0
        if step >= 1:
            if step == 1 and (force_refresh_openings or not alts.is_step1):
                if (alts.is_step1 is None) or (force_refresh_openings and alts.is_step1 is not False):
                    if alts.is_step1 is not True:
                        alts.is_step1 = False
                    Thread(name="alts_process", target=alts.process, args=(step, force_refresh_openings, mod)).start()
                return NOT_READY
            if step == 2 and not alts.is_step2:
                if alts.is_step2 is None:
                    alts.is_step2 = False
                    Thread(name="alts_process", target=alts.process, args=(step, force_refresh_openings, mod)).start()
                return NOT_READY
        return alts.get_output()

    def __init__(self, theme_color):
        self.players = []
        self.alt_names = {}
        self.theme_color = theme_color
        self.is_dark_mode = not theme_color.upper().startswith("#FFF")
        self.hist_switch_intervals = [0.0] * len(ALT_SWITCH_INTERVAL_NAMES)
        self.overlapping_games = {}
        self.is_step0 = None
        self.is_step1 = None
        self.is_step2 = None
        self.is_mod_log = True
        self.errors = []
        self.wait_insights_refresh_s = 0

    def set(self, names, num_games, date_begin, date_end, mod):
        self.players = [get_alt(username, num_games, date_begin, date_end, mod) for username in names]
        self.alt_names = {alt.user.id: alt.user.name for alt in self.players}
        self.overlapping_games = {alt.user.id: defaultdict(list) for alt in self.players}
        self.is_step0 = True

    def process(self, step, force_refresh_openings, mod):
        try:
            if step != 1:
                force_refresh_openings = False
            self.process_step1(force_refresh_openings, mod)
            if step >= 2:
                self.process_step2(mod)
        except Exception as exception:
            self.errors.append(str(exception))
            raise exception

    def process_step1(self, force_refresh_openings, mod):
        for alt in self.players:
            if not self.is_step1:
                alt.download_teams(mod)
                #alt.download_following()
                if self.is_mod_log:
                    self.is_mod_log = alt.download_mod_log(mod)
            alt.download_openings(force_refresh_openings, mod)
        self.wait_insights_refresh_s = mod.api.get_waiting_time(ApiType.InsightsRefresh)
        self.is_step1 = True

    def process_step2(self, mod):
        self.hist_switch_intervals = [0.0] * len(ALT_SWITCH_INTERVAL_NAMES)
        all_games = {}  # dict to not double mutual games
        for alt in self.players:
            alt.download(self.alt_names.keys(), mod)
            all_games.update({game['id']: (alt.user.id, game) for game in alt.games})
        games = list(all_games.values())
        games.sort(key=lambda p: p[1]['createdAt'])
        self.overlapping_games = {alt.user.id: defaultdict(list) for alt in self.players}
        if games:
            curr_player = games[0][0]
            game_end = games[0][1]['lastMoveAt']
            ongoing_games = []
            for player, game in games:
                # Intervals
                if player != curr_player:
                    mins = (game['createdAt'] - game_end) / 1000 / 60
                    if mins >= ALT_SWITCH_INTERVAL_MINS[-1]:
                        self.hist_switch_intervals[-1] += 1
                    else:
                        for i, interval in enumerate(ALT_SWITCH_INTERVAL_MINS):
                            if mins < interval:
                                self.hist_switch_intervals[i] += 1
                                break
                    curr_player = player
                game_end = game['lastMoveAt']
                # Overlapping games
                for i in range(len(ongoing_games) - 1, -1, -1):
                    last_player, last_game = ongoing_games[i]
                    if last_game['lastMoveAt'] <= game['createdAt']:
                        del ongoing_games[i]
                        continue
                    self.overlapping_games[player][last_player].append(OverlappingGames(game, last_game))
                    self.overlapping_games[last_player][player].append(OverlappingGames(last_game, game))
                ongoing_games.append((player, game))
        num_intervals = sum(self.hist_switch_intervals)
        if num_intervals:
            for i in range(len(self.hist_switch_intervals)):
                self.hist_switch_intervals[i] = self.hist_switch_intervals[i] * 100 / num_intervals
        self.is_step2 = True

    def add_hists(self, chart, hist_label_val_player):
        merged_labels = [label for label, _, _ in hist_label_val_player]
        all_labels = []
        existed_labels = set()
        for label in merged_labels:
            if label not in existed_labels:
                all_labels.append(label)
                existed_labels.add(label)
        for alt_id, alt_name in self.alt_names.items():
            labels = {label: val for label, val, name in hist_label_val_player if name == alt_id}
            hist = [None] * len(all_labels)
            for i in range(len(all_labels)):
                label = all_labels[i]
                hist[i] = labels.get(label, None)
            chart.add(alt_name, hist)
        chart.x_labels = [label for label in all_labels]

    def get_hist_hours(self):
        if not self.is_step2:
            return ""
        chart = pygal.Bar(title='Hourly Activity', width=CHART_WIDTH, value_formatter=lambda x: f'{x:0.1f}%')
        for alt in self.players:
            chart.add(alt.user.name, alt.hist_hours)
        chart.x_labels = list(range(0, 24, 2))
        chart.show_legend = True
        chart.human_readable = True
        return render(chart, DarkStyle if self.is_dark_mode else DefaultStyle, self.theme_color)

    def get_hist_days(self):
        if not self.is_step2:
            return ""
        chart = pygal.Bar(title='Daily Activity', width=CHART_WIDTH, value_formatter=lambda x: f'{x:0.1f}%')
        for alt in self.players:
            chart.add(alt.user.name, alt.hist_days)
        chart.x_labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        chart.human_readable = True
        return render(chart, DarkStyle if self.is_dark_mode else DefaultStyle, self.theme_color)

    def get_hist_tcs(self):
        if not self.is_step2:
            return ""
        chart = pygal.Bar(title='Time Controls', width=CHART_WIDTH, value_formatter=lambda x: f'{x:0.1f}%')
        hist_tcs = []
        for alt in self.players:
            hist = [(tc, val, alt.user.id) for tc, val in alt.hist_tcs.items()]
            hist.sort(key=lambda p: p[1], reverse=True)
            if len(hist) > ALT_MAX_NUM_TCS_TO_SHOW:
                hist = hist[:ALT_MAX_NUM_TCS_TO_SHOW]
            hist_tcs.extend(hist)
        if not hist_tcs:
            return ""
        self.add_hists(chart, hist_tcs)
        return render(chart, DarkStyle if self.is_dark_mode else DefaultStyle, self.theme_color)

    def get_hist_switch_intervals(self):
        if not self.is_step2 or len(self.players) <= 1:
            return ""
        chart = pygal.Bar(title="User Switching Intervals", width=CHART_WIDTH, value_formatter=lambda x: f'{x:0.1f}%')
        values = [{'value': self.hist_switch_intervals[0], 'style': f'fill: {BAR_DANGER}; stroke: {BAR_DANGER};'},
                  *self.hist_switch_intervals[1:]]
        chart.add('User Switching Intervals', values)
        chart.show_legend = False
        chart.x_labels = ALT_SWITCH_INTERVAL_NAMES
        return render(chart, DarkGreenBlueStyle if self.is_dark_mode else BlueStyle, self.theme_color)

    def get_hist_openings(self, color, opening_stage):
        if not self.is_step1:
            return ""
        hist_openings = []
        for alt in self.players:
            if not alt.hist_openings[color][opening_stage]:
                continue
            hist = [(opening, val, alt.user.id) for opening, val in alt.hist_openings[color][opening_stage]]
            if len(hist) > ALT_MAX_NUM_OPENINGS_TO_SHOW:
                hist = hist[:ALT_MAX_NUM_OPENINGS_TO_SHOW]
            hist_openings.extend(hist)
        if not hist_openings:
            return None
        chart = pygal.Bar(title=f"{opening_stage.value} as {color.value}", width=CHART_WIDTH,
                          value_formatter=lambda x: f'{x:0.1f}%')
        self.add_hists(chart, hist_openings)
        return render(chart, DarkStyle if self.is_dark_mode else DefaultStyle, self.theme_color)

    def get_mutual_teams(self):
        if not self.is_step1 or len(self.players) <= 1:
            return ""
        header_alts = [f'<th class="text-center">{alt.user.get_short_name(ALT_MAX_LEN_NAME)}</th>' for alt in self.players]
        rows = [alt.get_mutual_teams_row(self.players) for alt in self.players]
        return f'''<div class="column d-flex justify-content-center">
                <table id="mutual_teams_table" class="table table-sm table-striped table-hover text-center
                 w-auto text-nowrap mt-2">
                  <thead><tr>
                    <th></th>
                    <th><abbr title="The total number of teams a player is a member of" style="text-decoration:none;">
                        <i class="fas fa-hashtag"></i></abbr></th>
                    {"".join(header_alts)}
                  </tr></thead>
                  {"".join(rows)}
                </table>
                </div>'''

    def get_mutual_games(self):
        if not self.is_step2 or len(self.players) <= 1:
            return ""
        header_alts = [f'<th class="text-center">{alt.user.get_short_name(ALT_MAX_LEN_NAME)}</th>' for alt in self.players]
        rows = [alt.get_mutual_games_row(self.players) for alt in self.players]
        table = f'''<div class="column d-flex justify-content-center">
                    <table id="mutual_games_table" class="table table-sm table-striped table-hover text-center
                     w-auto text-nowrap mt-2">
                      <thead><tr>
                        <th></th>{"".join(header_alts)}
                      </tr></thead>
                      {"".join(rows)}
                    </table>
                    </div>'''
        info = [alt.get_mutual_games(self.alt_names) for alt in self.players]
        return f'{table}<div class="d-flex flex-column align-content-center flex-wrap">{"".join(info)}</div>'

    def get_overlapping_games(self):
        if not self.is_step2 or len(self.players) <= 1:
            return ""
        header_alts = [f'<th class="text-center">{alt.user.get_short_name(ALT_MAX_LEN_NAME)}</th>' for alt in self.players]
        rows = []
        info = []
        for player in self.players:
            player_id = player.user.id
            cells = [f'<td class="text-left">{player.user.get_name("?mod")}</td>']
            player_info = []
            for alt in self.players:
                alt_id = alt.user.id
                #if alt_id == player_id:
                #    cells.append('<td class="text-center">&mdash;</td>')
                #el
                if alt_id not in self.overlapping_games[player_id]:
                    cells.append(f'<td class="text-center{" text-info" if alt_id == player_id else ""}">&mdash;</td>')
                else:
                    overlapping_games = self.overlapping_games[player_id][alt_id]
                    num_games_class = 'text-info' if alt_id == player_id else 'text-danger' if len(overlapping_games) >= 5\
                        else 'text-warning'
                    cells.append(f'<td class="text-center {num_games_class}">{len(overlapping_games)}</td>')
                    examples = []
                    #step = max(1, (len(overlapping_games) - 1) // NUM_EXAMPLE_GAMES)
                    #for i in range(len(overlapping_games) - 1, -1, -step):
                    for og in sorted(overlapping_games, key=lambda g: g.interval_s, reverse=True):
                        game1_url = f"https://lichess.org/{og.my_game['id']}"
                        game2_url = f"https://lichess.org/{og.opp_game['id']}"
                        link1 = f'<a href="{game1_url}" target="_blank">{len(examples) + 1}</a>'
                        link2 = f'<a href="{game2_url}" target="_blank">{len(examples) + 1}</a>'
                        interval = deltainterval(og.interval_s, show_seconds=True, short=True)
                        examples.append(f'<span class="mx-1">{link1}={link2}={interval}</span>')
                        if len(examples) >= NUM_EXAMPLE_GAMES:
                            break
                    str_examples = ", ".join(examples)
                    total_overlapping_time_s = sum([og.interval_s for og in overlapping_games])
                    interval_short = deltainterval(total_overlapping_time_s, show_seconds=True, short=True)
                    interval_long = deltainterval(total_overlapping_time_s, show_seconds=True)
                    str_with = '<span class="text-info">themself</span>' if alt_id == player_id else alt.user.name
                    player_info.append(f'<span class="{num_games_class}">{len(overlapping_games)}'
                                       f' game{"" if len(overlapping_games) == 1 else "s"}</span>'
                                       f' <abbr title="{interval_long}">{interval_short}</abbr>'
                                       f' w/ {str_with}: {str_examples}')
            rows.append(f'<tr>{"".join(cells)}</tr>')
            if player_info:
                info.append(f'<div><b>{player.user.get_name("?mod")}</b>:'
                            f' <div>{"</div><div>".join(player_info)}</div></div>')
        table = f'''<div class="column d-flex justify-content-center">
                    <table id="overlapping_games_table" class="table table-sm table-striped table-hover text-center
                     w-auto text-nowrap mt-2">
                      <thead><tr>
                        <th></th>{"".join(header_alts)}
                      </tr></thead>
                      {"".join(rows)}
                    </table>
                    </div>'''
        return f'{table}<div class="d-flex flex-column align-content-center flex-wrap">{"".join(info)}</div>'

    def get_info_1(self):
        # User table
        rows = []
        now_utc = datetime.now(tz=tz.tzutc())
        players_sorted = self.players.copy()
        players_sorted.sort(key=lambda alt: alt.user.createdAt if alt.user.createdAt is not None else 0)
        for player in players_sorted:
            createdAt = player.user.get_createdAt()
            if createdAt:
                created_days_ago = (now_utc - createdAt).days
                created_ago = datetime_to_ago(createdAt, now_utc)
                str_created = f'{created_days_ago:,d} day{"" if created_days_ago == 1 else "s"} ago'
                if str_created != created_ago:
                    str_created = f'{str_created} / {created_ago}'
                str_created = f'<abbr title="{str_created}" style="text-decoration:none;">{created_days_ago:,d}</abbr>'
            else:
                str_created = "&mdash;"
            seenAt = player.user.get_seenAt()
            if seenAt:
                seen_days_ago = (now_utc - seenAt).days
                seen_ago = datetime_to_ago(seenAt, now_utc)
                str_seen = f'{seen_days_ago:,d} day{"" if seen_days_ago == 1 else "s"} ago'
                if str_seen != seen_ago:
                    str_seen = f'{str_seen} / {seen_ago}'
                str_seen = f'<abbr title="{str_seen}" style="text-decoration:none;">{seen_days_ago:,d}</abbr>'
            else:
                str_seen = "&mdash;"
            other_alts = [alt.user.name for alt in self.players if alt.user.id != player.user.id]
            class_num_games = " text-danger" if len(player.games) < 25 else " text-warning" if len(player.games) < 60 else ""
            row_num_games = f'<td class="text-right{class_num_games}">{len(player.games)}</td>' if self.is_step2 else ""
            rows.append(f'<tr><td class="text-left">{player.user.get_name("?mod")}</td>'
                        f'{row_num_games}'
                        f'<td class="text-right">{str_created}</td>'
                        f'<td class="text-right">{str_seen}</td>'
                        f'<td class="text-right"><button class="btn btn-primary py-0 px-2"'
                        f' onclick="set_alts(\'{" ".join(other_alts)}\')">Exclude</button></td></tr>')
        th_num_games = f'<th class="text-right"><abbr title="# games analysed" style="text-decoration:none;">' \
                       f'<i class="fas fa-hashtag"></i></abbr></th>' if self.is_step2 else ""
        table = f'''<div class="column">
                    <table id="creation_table" class="table table-sm table-striped table-hover text-center
                     text-nowrap mt-2">
                      <thead><tr>
                        <th></th>{th_num_games}
                        <th class="text-right"><abbr title="Created days ago" style="text-decoration:none;">
                            Created</abbr></th>
                        <th class="text-right"><abbr title="Active days ago" style="text-decoration:none;">
                            Active</abbr></th>
                        <th class="text-left">&larr;days ago</th>
                      </tr></thead>
                      {"".join(rows)}
                    </table>
                    </div>'''
        # Refresh openings button
        if self.is_step2:
            refresh_players = [player.user.name for player in self.players if needs_to_refresh_insights(player.user.id)]
            if refresh_players:
                links = [f'<a href="https://lichess.org/insights/{player_name}/opponentRating/openingFamily/color:black" '
                         f'target="_blank">{player_name}</a>' for player_name in refresh_players]
                if len(links) == 2:
                    player_list = " and ".join(links)
                elif len(links) > 2:
                    player_list = f'{", ".join(links[:-1])}, and {links[-1]}'
                else:
                    player_list = ", ".join(links)
                wait_s = deltainterval(max(1, self.wait_insights_refresh_s), True, True)
                refresh_openings = f'<div id="refresh-openings" class="d-flex align-items-center mt-3">' \
                                   f'<button class="btn btn-warning py-0 px-2 mr-2"' \
                                   f' onclick="refresh_openings()">Refresh openings</button>' \
                                   f'<span>for {player_list} after {wait_s} as Lichess doesn\'t allow' \
                                   f' too frequent requests via API :(</span></div>'
            else:
                refresh_openings = ""
        else:
                refresh_openings = ""
        # User info
        info = "".join([alt.get_user_info() for alt in self.players])
        mod_data_error = "" if self.is_mod_log else '<div class="text-warning mt-3">Failed to load mod logs/notes</div>'
        # All
        return f'{table}{refresh_openings}{mod_data_error}{info}'

    def get_info_2(self):
        hist_tcs = f'<div class="mt-3">{self.get_hist_tcs()}</div>' if self.is_step2 else ""
        return f"{self.get_hist_switch_intervals()}{hist_tcs}{self.get_hist_hours()}{self.get_hist_days()}"

    def get_info_3(self):
        overlapping_games = f'<h6 class="text-center">Overlapping games:</h6>{self.get_overlapping_games()}'\
            if self.is_step2 and len(self.players) > 1 else ""
        if not self.is_step2 or len(self.players) <= 1:
            header = ""
        elif len(self.players) > 1:
            user_ids = [alt.user.id for alt in self.players[1:]]
            url = f'https://lichess.org/mod/{self.players[0].user.id}/games?opponents={"+".join(user_ids)}'
            header = f'<h6 class="text-center mt-3">Mutual <a href="{url}" target="_blank">games</a>:</h6>'
        mutual_teams = f'<h6 class="text-center mt-3">Mutual teams:</h6>{self.get_mutual_teams()}' \
            if self.is_step1 and len(self.players) > 1 else ""
        openings = []
        for opening_stage in OpeningStage:
            for color in Color:
                openings_ij = self.get_hist_openings(color, opening_stage)
                openings.append(f'<div class="mt-3">{openings_ij}</div>' if openings_ij else "")
        return f'{overlapping_games}{header}{self.get_mutual_games()}{mutual_teams}{"".join(openings)}'

    def get_output(self):
        if not self.is_step0:
            return {'part-1': "", 'part-2': "", 'part-3': ""}
        return {'part-1': self.get_info_1(), 'part-2': self.get_info_2(), 'part-3': self.get_info_3()}

    def get_errors(self):
        if not self.errors:
            return ""
        errors = '</p><p>'.join(self.errors)
        return f'<h4 class="text-danger">Error{"" if len(self.errors) == 1 else "s"}:</h4><p>{errors}</p>'
