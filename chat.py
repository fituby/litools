import requests
from datetime import datetime, timedelta
from dateutil import tz
import time
import traceback
from multiprocessing import Lock
import yaml
from elements import Reason, TournType, get_token, get_ndjson, deltaseconds, log, config_file
from elements import get_notes, add_note, load_mod_log, get_mod_log, get_highlight_style, add_timeout_msg
from elements import ModActionType, UserData
from chat_message import Message
from chat_tournament import Tournament
from consts import *


official_teams = [
    "lichess-swiss",
    "lichess-antichess",
    "lichess-atomic",
    "lichess-chess960",
    "lichess-crazyhouse",
    "lichess-horde",
    "lichess-king-of-the-hill",
    "lichess-racing-kings",
    "lichess-three-check",
    "team-chessable"
]

arena_tournament_page = "https://lichess.org/tournament/"
swiss_tournament_page = "https://lichess.org/siwss/"


class ChatAnalysis:
    def __init__(self):
        self.tournaments = {}
        self.users = {}
        #self.user_messages = {}
        self.tournament_messages = {}
        self.all_messages = {}
        self.is_processing = False
        self.last_api_time: datetime = None
        self.last_refresh: datetime = None
        self.last_tournaments_update: datetime = None
        self.errors = []
        self.i_update_frequency = 2  # len(API_CHAT_REFRESH_PERIOD) - 1
        self.reset_multi_messages = set()
        self.update_count = 0
        self.tournament_groups = {"monitored": True, "started": True, "created": True, "finished": True}
        self.msg_lock = Lock()
        self.tournaments_lock = Lock()
        self.reports_lock = Lock()
        self.selected_msg_id = None
        self.multi_messages = {}
        self.to_timeout = {}
        self.recommended_timeouts = set()
        self.state_tournaments = 1
        self.state_reports = 1
        self.cache_tournaments = {'state_tournaments': 0}
        self.cache_reports = {'state_reports': 0}
        try:
            with open(config_file) as stream:
                config = yaml.safe_load(stream)
                self.to_read_mod_log = config.get('chat_mod_log', False)
                self.to_read_notes = config.get('chat_notes', True)
        except Exception as e:
            print(f"There appears to be a syntax problem with your {config_file}: {e}")
            self.to_read_mod_log = False
            self.to_read_notes = True
        self.last_mod_log_error = None
        self.last_notes_error = None

    def wait_api(self):
        now = datetime.now()
        if self.last_api_time:
            wait_s = API_TOURNEY_PAGE_DELAY - deltaseconds(now, self.last_api_time)
            if wait_s > 0:
                time.sleep(wait_s)
        self.last_api_time = now

    def wait_refresh(self):
        now = datetime.now()
        if self.last_refresh:
            wait_s = API_CHAT_REFRESH_PERIOD[self.i_update_frequency] - deltaseconds(now, self.last_refresh)
            if wait_s > 0:
                time.sleep(wait_s)
        self.last_refresh = now

    def update_tournaments(self):
        if self.is_processing or self.errors:
            return
        if self.i_update_frequency == IDX_NO_PAGE_UPDATE:
            time.sleep(1)
            return
        now_utc = datetime.now(tz=tz.tzutc())
        if self.last_tournaments_update and deltaseconds(now_utc, self.last_tournaments_update) < PERIOD_UPDATE_TOURNAMENTS:
            return
        self.is_processing = True
        self.last_tournaments_update = now_utc
        try:
            if self.tournament_groups["monitored"] or self.tournament_groups["started"] or self.tournament_groups["created"]:
                active_tournaments = {t.id: t for t in get_current_tournaments()}
                keys = list(self.tournaments.keys())
                for tourn_id in keys:
                    if tourn_id in active_tournaments:
                        self.tournaments[tourn_id].update(active_tournaments[tourn_id])
                        del active_tournaments[tourn_id]
                    elif (not self.tournaments[tourn_id].is_monitored and not self.tournaments[tourn_id].is_active(now_utc))\
                            or not self.tournaments[tourn_id].is_enabled:
                        with self.msg_lock:
                            try:
                                for del_msg in self.tournaments[tourn_id].messages:
                                    del self.tournament_messages[del_msg.id]
                                    del self.all_messages[del_msg.id]
                            except Exception as exception:
                                traceback.print_exception(type(exception), exception, exception.__traceback__)
                        del self.tournaments[tourn_id]
                for tourn_id, tourn in active_tournaments.items():
                    self.tournaments[tourn_id] = tourn
            self.state_tournaments += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            if not self.tournaments:
                self.errors.append(f"{now_utc:%Y-%m-%d %H:%M} UTC: {exception}")  # only if it doesn't work from the very beginning
        except:
            self.errors.append("ERROR at {now_utc:%Y-%m-%d %H:%M} UTC")
        self.is_processing = False

    def run(self):
        if self.is_processing or self.errors or self.i_update_frequency == IDX_NO_PAGE_UPDATE:
            return
        self.is_processing = True
        self.wait_refresh()
        now_utc = datetime.now(tz=tz.tzutc())
        try:
            keys = list(self.tournaments.keys())  # needed as self.tournaments may be changed from add_tournament()
            for tourn_id in keys:
                tourn = self.tournaments[tourn_id]
                if tourn.t_type == TournType.Swiss and not CHAT_UPDATE_SWISS:
                    continue
                if tourn.is_just_added:
                    tourn.is_just_added = False
                else:
                    if not tourn.is_enabled:
                        continue
                    is_ongoing = tourn.is_ongoing(now_utc)
                    if self.update_count == 0 and not is_ongoing:
                        continue
                    if not is_ongoing:
                        hash_num = sum(ord(ch) for ch in tourn_id)
                        update_period = tourn.update_period(now_utc)
                        if self.update_count % update_period != hash_num % update_period:
                            continue
                self.wait_api()
                new_messages, deleted_messages = tourn.download(self.msg_lock, now_utc)
                with self.msg_lock:
                    self.tournament_messages.update({msg.id: tourn_id for msg in new_messages})
                    self.all_messages.update({msg.id: msg for msg in new_messages})
                    for del_msg in deleted_messages:
                        del self.tournament_messages[del_msg.id]
                        del self.all_messages[del_msg.id]
                    to_timeout_i = tourn.analyse()
                    for m in to_timeout_i.values():
                        add_timeout_msg(self.to_timeout, m)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(f"{now_utc:%Y-%m-%d %H:%M} UTC: {exception}")
        except:
            self.errors.append("ERROR at {now_utc:%Y-%m-%d %H:%M} UTC")
        self.update_count += 1
        self.state_reports += 1
        self.is_processing = False

    def set_msg_ok(self, msg_id):
        try:
            msg = self.all_messages.get(int(msg_id[1:]))
            if msg is not None:
                msg.is_reset = True
                if msg.score > 20:
                    reason_tag = Reason.to_tag(msg.best_reason())
                    chan = "tournament" if msg.tournament.t_type == TournType.Arena \
                        else "swiss" if msg.tournament.t_type == TournType.Swiss \
                        else "study" if msg.tournament.t_type == TournType.Study \
                        else None
                    log(f"[reset] {reason_tag.upper()} @{msg.username} score={msg.score} "
                        f"{chan.upper()}={msg.tournament.id}: {msg.text}")
                self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            now_utc = datetime.now(tz=tz.tzutc())
            self.errors.append(f"{now_utc:%Y-%m-%d %H:%M} UTC: {exception}")

    def set_multi_msg_ok(self, msg_id):
        try:
            msg_id = int(msg_id[1:])
            self.reset_multi_messages.add(msg_id)
            if msg_id in self.multi_messages:
                del self.multi_messages[msg_id]
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            now_utc = datetime.now(tz=tz.tzutc())
            self.errors.append(f"{now_utc:%Y-%m-%d %H:%M} UTC: {exception}")

    def api_timeout(self, msg, reason, is_timeout_manual):
        reason_tag = Reason.to_tag(reason)
        if reason_tag is None:
            self.errors.append(f"Error timeout: Unknown reason at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC")
            return
        if msg.tournament.id not in self.tournaments:
            self.errors.append(f"Error timeout: Tournament {msg.tournament.id} deleted "
                               f"as of {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC")
            return
        chan = "tournament" if msg.tournament.t_type == TournType.Arena \
            else "swiss" if msg.tournament.t_type == TournType.Swiss \
            else "study" if msg.tournament.t_type == TournType.Study \
            else None
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = "https://lichess.org/mod/public-chat/timeout"
        text = f'{msg.text[:MAX_LEN_TEXT-1]}…' if len(msg.text) > MAX_LEN_TEXT else msg.text
        data = {'reason': reason_tag,
                'userId': msg.username.lower(),
                'roomId': msg.tournament.id,
                'chan': chan,
                'text': text}
        if is_timeout_manual or DO_AUTO_TIMEOUTS:
            r = requests.post(url, headers=headers, json=data)
            timeout_tag = ('' if is_timeout_manual else '[AUTO] ') if DO_AUTO_TIMEOUTS else ""
            if len(msg.text) > MAX_LEN_TEXT:
                text = f'{text}{msg.text[MAX_LEN_TEXT-1:]}'
            if r.status_code == 200 and r.text == "ok":
                log(f"{timeout_tag}{reason_tag.upper()} @{msg.username} score={msg.score} "
                    f"{chan.upper()}={msg.tournament.id}: {text}", True)
                start_time = msg.time - timedelta(minutes=TIMEOUT_RANGE[0])
                end_time = msg.time + timedelta(minutes=TIMEOUT_RANGE[1])
                for m in self.all_messages.values():
                    if m.username == msg.username and start_time < m.time < end_time:
                        m.is_timed_out = True
                        m.is_reset = False
                for m in msg.tournament.messages:
                    if m.username == msg.username:
                        m.is_timed_out = True
                        m.is_reset = False
                self.update_selected_user()
            else:
                status_info = "invalid token?" if r.status_code == 200 else f"status: {r.status_code}"
                self.errors.append(f"Timeout error ({status_info}):<br>{timeout_tag}{reason_tag.upper()} "
                                   f"<u>Score</u>: {msg.score} <u>User</u>: {msg.username} "
                                   f"<u>RoomId</u>: {msg.tournament.id} <u>Channel</u>: {chan} <u>Text</u>: {text}")
        else:
            if msg.id not in self.recommended_timeouts:
                print(f"Recommended to time out: {data}")
                self.recommended_timeouts.add(msg.id)

    def timeout(self, msg_id, reason):
        try:
            with self.msg_lock:
                msg = self.all_messages.get(int(msg_id[1:]))
                if msg is not None:
                    reason = int(reason)
                    if reason == 0:
                        reason = msg.best_reason()
                    self.api_timeout(msg, reason, True)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(f"{datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: {exception}")

    def timeout_multi(self, mmsg_id, reason):
        try:
            with self.msg_lock:
                msg_id = int(mmsg_id[1:])
                msgs = self.multi_messages.get(msg_id)
                if msgs is not None:
                    reason = int(reason)
                    if reason == 0:
                        reason = Reason.Spam  # msg.best_reason()
                    combined_text = f'[multiline] {" | ".join([m.text for m in msgs if not m.is_reset])}'
                    combined_msg = Message({'u': msgs[0].username, 't': combined_text}, msgs[0].tournament, msgs[0].time)
                    combined_msg.evaluate(self.tournaments[self.tournament_messages[msg_id]].re_usernames)
                    self.api_timeout(combined_msg, reason, True)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(f"{datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: {exception}")

    def custom_timeout(self, msg_ids, reason):
        try:
            with self.msg_lock:
                if msg_ids:
                    username = None
                    msgs = []
                    for msg_id in msg_ids:
                        msg_id = int(msg_id[1:])
                        msg = self.all_messages.get(msg_id)
                        if username is None:
                            username = msg.username
                        elif username != msg.username:
                            raise Exception(f"Messages of different users: {username} != {msg.username}")
                        msgs.append(msg)
                    reason = int(reason)
                    if reason == 0:
                        reason = Reason.Spam  # msg.best_reason()
                    if len(msgs) > 1:
                        combined_text = f'[multiline] {" | ".join([m.text for m in msgs])}'
                        combined_msg = Message({'u': msgs[0].username, 't': combined_text}, msgs[0].tournament, msgs[0].time)
                        first_msg_id = int(msg_ids[0][1:])
                        combined_msg.evaluate(self.tournaments[self.tournament_messages[first_msg_id]].re_usernames)
                        self.api_timeout(combined_msg, reason, True)
                    else:
                        self.api_timeout(msgs[0], reason, True)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(f"{datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: {exception}")

    def set_update(self, i_update_frequency):
        if i_update_frequency is None:
            return
        try:
            self.i_update_frequency = max(0, min(len(API_CHAT_REFRESH_PERIOD), int(i_update_frequency)))
        except:
            return

    def update_selected_user(self):
        try:
            if self.selected_msg_id is None:
                return
            msg = self.all_messages.get(self.selected_msg_id)
            if not msg:
                return
            user = UserData(msg.username)
            now = datetime.now()
            if self.to_read_mod_log and (self.last_mod_log_error is None
                                         or now > self.last_mod_log_error + timedelta(minutes=DELAY_ERROR_READ_MOD_LOG)):
                mod_log_data = load_mod_log(msg.username)
                if mod_log_data is None:
                    self.last_mod_log_error = now
                else:
                    user.mod_log, _ = get_mod_log(mod_log_data, ModActionType.Chat)
                    self.last_mod_log_error = None
            else:
                mod_log_data = None
            if self.to_read_notes and (self.last_notes_error is None
                                       or now > self.last_notes_error + timedelta(minutes=DELAY_ERROR_READ_MOD_LOG)):
                user.notes = get_notes(msg.username, mod_log_data)
                if user.notes is None:
                    self.last_notes_error = now
                    user.notes = ""
                else:
                    self.last_notes_error = None
            self.users[msg.username] = user
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)

    def select_message(self, msg_id):
        def create_info(info):
            return {'selected-messages': info, 'filtered-messages': info, 'selected-tournament': "",
                    'selected-user': "", 'mod-notes': "", 'mod-log': "", 'user-info': "", 'user-profile': ""}

        try:
            if msg_id == "--":
                self.selected_msg_id = None
                return create_info("")
            self.selected_msg_id = int(msg_id[1:])
            self.update_selected_user()
            return self.get_messages_nearby(self.selected_msg_id)
        except Exception as exception:
            self.selected_msg_id = None
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return create_info(f'<p class="text-danger">Error: {exception}</p>')
        except:
            self.selected_msg_id = None
            return create_info(f'<p class="text-danger">Error: get_messages_near()</p>')

    def get_messages_nearby(self, msg_id):
        def create_output(info, tournament, user_data, filtered_info=None):
            data = {'selected-messages': info, 'filtered-messages': filtered_info or info, 'selected-tournament': tournament}
            if user_data:
                data.update({'selected-user': user_data.user.name, 'user-profile': user_data.user.get_profile(),
                             'user-info': user_data.user.get_user_info(CHAT_CREATED_DAYS_AGO, CHAT_NUM_PLAYED_GAMES),
                             'mod-notes': user_data.notes, 'mod-log': user_data.mod_log})
            else:
                data.update({'selected-user': "", 'mod-notes': "", 'mod-log': "", 'user-info': "", 'user-profile': ""})
            return data

        def make_selected(msg_selected):
            return f'<div class="border border-success rounded" style="{get_highlight_style(0.3)}">{msg_selected}</div>'

        tournament_name = ""
        try:
            tourn_id = self.tournament_messages.get(msg_id)
            tournament_name = self.tournaments[tourn_id].get_link(short=False) if tourn_id in self.tournaments else ""
            if msg_id is None:
                return create_output("", tournament_name, None)
            with self.msg_lock:
                i: int = None
                if tourn_id in self.tournaments:
                    for j, msg in enumerate(self.tournaments[tourn_id].messages):
                        if msg.id == msg_id:
                            i = j
                            break
                if i is None:
                    return create_output(f'<p class="text-warning">Warning: Message has been removed</p>',
                                         tournament_name, None)
                i_start = 0
                i_end = len(self.tournaments[tourn_id].messages)
                msg_i = self.tournaments[tourn_id].messages[i]
                msg = make_selected(msg_i.get_info('C', show_hidden=True, highlight_user=True,
                                                   is_selected=True, is_centered=True))
                msg_f = make_selected(msg_i.get_info('F', show_hidden=True, highlight_user=True,
                                                     is_selected=False, is_centered=True, add_selection=True))
                # msg_f is not selected to allow copying to the notes.
                # However, this prevents text from being selected with the mouse
                msgs_before = [self.tournaments[tourn_id].messages[j].get_info('C',
                               base_time=msg_i.time, highlight_user=msg_i.username) for j in range(i_start, i)]
                msgs_after = [self.tournaments[tourn_id].messages[j].get_info('C',
                              base_time=msg_i.time, highlight_user=msg_i.username) for j in range(i + 1, i_end)]
                msgs_user = [(msg_f if msg_user.id == msg_id else msg_user.get_info(
                                'F', base_time=msg_i.time, highlight_user=msg_i.username, add_selection=True))
                             for msg_user in self.tournaments[tourn_id].messages if msg_user.username == msg_i.username]
                list_start = '<hr class="text-primary my-1" style="border:1px solid;">' if i_start == 0 else ""
                list_end = '<hr class="text-primary mt-1 mb-0" style="border:1px solid;">'\
                           if i_end == len(self.tournaments[tourn_id].messages) else ""
                username = msg_i.username
            user = self.users.get(username)
            info_selected = f'{list_start}{"".join(msgs_before)} {msg} {"".join(msgs_after)}{list_end}'
            info_filtered = "".join(msgs_user)
            return create_output(info_selected, tournament_name, user, filtered_info=info_filtered)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return create_output(f'<p class="text-danger">Error: {exception}</p>', tournament_name, None)
        except:
            return create_output(f'<p class="text-danger">Error: get_messages_near()</p>', tournament_name, None)

    def set_tournament(self, tourn_id, checked):
        tournament = self.tournaments.get(tourn_id)
        if not tournament:
            self.errors.append(f"No tournament \"{tourn_id}\" to set {checked}")
            return
        tournament.is_enabled = (not tournament.is_enabled) if checked is None else checked

    def set_tournament_group(self, group, checked):
        if group.endswith("2"):
            group = group[:-1]
        now_utc = datetime.now(tz=tz.tzutc())
        active_tournaments = self.get_time_sorted_tournaments(now_utc, active_only=False)
        if group in self.tournament_groups:
            if checked is None:
                checked = not self.tournament_groups[group]
            self.tournament_groups[group] = checked
            if group == "monitored":
                for tourney in active_tournaments:
                    if tourney.is_monitored:
                        tourney.is_enabled = checked
            if group == "created":
                for tourney in active_tournaments:
                    if tourney.is_created(now_utc):
                        tourney.is_enabled = checked
            elif group == "started":
                for tourney in active_tournaments:
                    if tourney.is_ongoing(now_utc):
                        tourney.is_enabled = checked or tourney.is_monitored
            elif group == "finished":
                for tourney in active_tournaments:
                    if tourney.is_finished(now_utc):
                        tourney.is_enabled = checked
        self.state_tournaments += 1
        return self.get_tournaments(active_tournaments)

    def add_tournament(self, page):
        # while self.is_processing:
        #     time.sleep(0.1)
        str_lichess = "https://lichess.org/"
        if page:
            page = page.strip()
        if page and page.startswith(str_lichess):
            i = page.rfind('/')
            if 0 < i < len(page):
                tourn_id = page[i + 1:]
                if tourn_id in self.tournaments:
                    self.tournaments[tourn_id].is_monitored = True
                else:
                    headers = {}  # {'Authorization': f"Bearer {get_token()}"}
                    if page.startswith(arena_tournament_page) and i == len(arena_tournament_page) - 1:
                        r = requests.get(f"https://lichess.org/api/tournament/{tourn_id}", headers=headers)
                        if r.status_code != 200:
                            raise Exception(f"ERROR /api/tournament/{tourn_id}: Status Code {r.status_code}")
                        arena = r.json()
                        if tourn_id != arena['id']:
                            raise Exception(f"ERROR {page}: Wrong ID {tourn_id} != {arena['id']}")
                        self.tournaments[tourn_id] = Tournament(arena, TournType.Arena, is_monitored=True)
                    elif page.startswith(swiss_tournament_page) and i == len(swiss_tournament_page) - 1:
                        r = requests.get(f"https://lichess.org/api/swiss/{tourn_id}", headers=headers)
                        if r.status_code != 200:
                            raise Exception(f"ERROR /api/swiss/{tourn_id}: Status Code {r.status_code}")
                        swiss = r.json()
                        if tourn_id != swiss['id']:
                            raise Exception(f"ERROR {page}: Wrong ID {tourn_id} != {swiss['id']}")
                        self.tournaments[tourn_id] = Tournament(swiss, TournType.Swiss, is_monitored=True)
                    else:
                        j = page[0:i].rfind('/')
                        name = page[j + 1:i] if j > len(str_lichess) and i > j + 1 else tourn_id
                        data = {'id': tourn_id,
                                'createdBy': "lichess",
                                'nbPlayers': 0,
                                'startsAt': None,
                                'name': name,
                                'status': "started"
                                }
                        self.tournaments[tourn_id] = Tournament(data, TournType.Study, link=page, is_monitored=True)
                self.tournaments[tourn_id].is_just_added = True
        self.state_tournaments += 1
        return self.get_tournaments()

    def get_score_sorted_tournaments(self, now_utc, active_only=True):
        active_tournaments = [tourn for tourn in self.tournaments.values() if not active_only or tourn.is_active(now_utc)]
        active_tournaments.sort(key=lambda tourn: tourn.priority_score(), reverse=True)
        return active_tournaments

    def get_time_sorted_tournaments(self, now_utc, active_only=True):
        active_tournaments = [tourn for tourn in self.tournaments.values() if not active_only or tourn.is_active(now_utc)]
        active_tournaments.sort(key=lambda tourn: tourn.priority_time(now_utc), reverse=True)
        return active_tournaments

    def get_all(self):
        with self.reports_lock:
            if self.state_reports == self.cache_reports['state_reports']:
                return self.cache_reports
            # Main content
            now_utc = datetime.now(tz=tz.tzutc())
            now = datetime.now()
            active_tournaments = self.get_score_sorted_tournaments(now_utc)
            info = "".join([tourn.get_info(now_utc) for tourn in active_tournaments])
            output = []
            for tourn in active_tournaments:
                output_i, multi_msgs, to_timeout_i = tourn.get_frequent_data(now_utc, self.reset_multi_messages)
                if output_i:
                    output.extend(output_i)
                    self.multi_messages.update(multi_msgs)
                for m in to_timeout_i.values():
                    add_timeout_msg(self.to_timeout, m)
            for msg in self.to_timeout.values():
                self.api_timeout(msg, msg.best_ban_reason(), False)
            self.to_timeout.clear()
            output.sort(key=lambda t: t[0], reverse=True)
            info_frequent = "".join([info for score, info in output])
            if self.errors:
                info = f'<div class="text-warning text-break">{"<b>Errors</b>: " if len(self.errors) > 1 else ""}<div>' \
                       f'{"</div><div>".join(self.errors)}</div><div class="text-danger">ABORTED</div></div>{info}'
            messages_nearby = self.get_messages_nearby(self.selected_msg_id)
            str_time = f"{now:%H:%M}"
            self.cache_reports = {'reports': info, 'multiline-reports': info_frequent,
                                  'time': str_time, 'state_reports': self.state_reports}
            self.cache_reports.update(messages_nearby)
            return self.cache_reports

    def get_tournaments(self, active_tournaments=None):
        with self.tournaments_lock:
            if self.state_tournaments == self.cache_tournaments['state_tournaments']:
                return self.cache_tournaments

            # Lists
            def get_group_desc(group, group_name, desc, suffix=""):
                checked = ' checked' if self.tournament_groups[group] else ""
                return f'<div class="form-check">' \
                       f'<input class="form-check-input" type="checkbox" id="t_{group}{suffix}" ' \
                           f'onchange="set_tournament_group(\'{group}{suffix}\')"{checked}>' \
                       f'<label class="form-check-label d-flex justify-content-between" for="t_{group}{suffix}">' \
                           f'<b>{group_name}</b><b>{desc}</b></label>' \
                       f'</div>'

            now_utc = datetime.now(tz=tz.tzutc())
            if active_tournaments is None:
                active_tournaments = self.get_time_sorted_tournaments(now_utc, active_only=False)
            num_monitored = 0
            num_started = 0
            num_created = 0
            num_finished = 0
            num_monitored_enabled = 0
            num_started_enabled = 0
            num_created_enabled = 0
            num_finished_enabled = 0
            for tourney in active_tournaments:
                if tourney.is_monitored:
                    num_monitored += 1
                    if tourney.is_enabled:
                        num_monitored_enabled += 1
                if tourney.is_created(now_utc):
                    num_created += 1
                    if tourney.is_enabled:
                        num_created_enabled += 1
                elif tourney.is_ongoing(now_utc):
                    num_started += 1
                    if tourney.is_enabled:
                        num_started_enabled += 1
                else:
                    num_finished += 1
                    if tourney.is_enabled:
                        num_finished_enabled += 1
            n_monitored = f"{num_monitored}" if num_monitored == num_monitored_enabled \
                else f"{num_monitored_enabled} / {num_monitored}"
            n_started = f"{num_started}" if num_started == num_started_enabled \
                else f"{num_started_enabled} / {num_started}"
            n_created = f"{num_created}" if num_created == num_created_enabled \
                else f"{num_created_enabled} / {num_created}"
            n_finished = f"{num_finished}" if num_finished == num_finished_enabled \
                else f"{num_finished_enabled} / {num_finished}"
            self.cache_tournaments = {
                'tournaments': [
                    get_group_desc("started", "All Ongoing", n_started, suffix="2"),
                    get_group_desc("created", "All Created", n_created, suffix="2"),
                    get_group_desc("finished", "All Finished", n_finished, suffix="2"),
                    '<hr class="mt-1 mb-2">',
                    get_group_desc("monitored", "Added", n_monitored)
                ],
                'started': [get_group_desc("started", f"{n_started} Started", "finishes in:"), '<hr class="my-0">'],
                'created': [get_group_desc("created", f"{n_created} Created", "starts in:"), '<hr class="my-0">'],
                'finished': [get_group_desc("finished", f"{n_finished} Finished", "finished ago:"), '<hr class="my-0">']
            }
            for tournament in active_tournaments:
                state = tournament.get_state(now_utc)
                self.cache_tournaments[state].append(tournament.get_list_item(now_utc))
                if tournament.is_monitored:
                    self.cache_tournaments['tournaments'].append(tournament.get_list_item(now_utc))
            for state, t in self.cache_tournaments.items():
                self.cache_tournaments[state] = "".join(t)
            self.cache_tournaments['state_tournaments'] = self.state_tournaments
            return self.cache_tournaments

    def send_note(self, note, username):
        try:
            if not note or not username:
                raise Exception(f"Wrong note: [{username}]: {note}")
            if note and username:
                print(f"Note [{username}]:\n{note}")
                is_ok = add_note(username, note)
                if is_ok:
                    mod_notes = get_notes(username)
                    return {'selected-user': username, 'mod-notes': mod_notes}
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(f"{datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: {exception}")
        return {'selected-user': username, 'mod-notes': ""}


def get_current_tournaments():
    headers = {}  # {'Authorization': f"Bearer {get_token()}"}
    # Arenas of official teams
    arenas = []
    for teamId in official_teams:
        url = f"https://lichess.org/api/team/{teamId}/arena"
        data = get_ndjson(url, Accept="application/nd-json")
        arenas.extend(data)
    # Arena
    url = "https://lichess.org/api/tournament"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"ERROR /api/tournament: Status Code {r.status_code}")
    data = r.json()
    arenas.extend([*data['created'], *data['started'], *data['finished']])
    tournaments = []
    now_utc = datetime.now(tz=tz.tzutc())
    for arena in arenas:
        tourn = Tournament(arena, TournType.Arena)
        if tourn.is_active(now_utc):
            tournaments.append(tourn)
    # Swiss
    for teamId in official_teams:
        url = f"https://lichess.org/api/team/{teamId}/swiss"
        swiss_data = get_ndjson(url, Accept="application/nd-json")
        for swiss in swiss_data:
            try:
                tourn = Tournament(swiss, TournType.Swiss)
                if tourn.is_active(now_utc):
                    tournaments.append(tourn)
            except Exception as exception:
                traceback.print_exception(type(exception), exception, exception.__traceback__)
    # Broadcast
    url = f"https://lichess.org/api/broadcast?nb={NUM_RECENT_BROADCASTS_TO_FETCH}"
    broadcast_data = get_ndjson(url, Accept="application/nd-json")
    for broadcast in broadcast_data:
        try:
            broadcast_name = broadcast['tour']['name']
            for r in broadcast['rounds']:
                r['createdBy'] = "lichess"
                r['nbPlayers'] = 0
                r['name'] = f"{r['name']} | {broadcast_name}"
                r['status'] = "finished" if r.get('finished') else "unknown"
                tourn = Tournament(r, TournType.Study, r['url'])
                if tourn.is_active(now_utc):
                    tournaments.append(tourn)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
    return tournaments
