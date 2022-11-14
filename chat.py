import requests
from datetime import datetime, timedelta
from dateutil import tz
import time
import traceback
from threading import Lock
import re
from collections import defaultdict
from typing import DefaultDict, Dict
from elements import Reason, TournType, get_ndjson, delta_s, log
from elements import get_notes, add_note, load_mod_log, get_mod_log, get_highlight_style, add_timeout_msg
from elements import ModActionType, ModAction, UserData
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
    kid_years = re.compile(r"(?:\b|\D)({})(?:\b|\D)".format("|".join(
        [f"{y}\s*(?:г|л|y|j)|{datetime.now().year - y}" for y in range(6, 12)])), re.IGNORECASE)

    def __init__(self):
        self.tournaments = {}
        self.tournament_messages = {}
        self.all_messages = {}
        #self.user_messages = defaultdict(dict)
        self.processing_lock = Lock()
        self.last_api_time: datetime = None
        self.last_refresh: datetime = None
        self.last_tournaments_update: datetime = None
        self.errors = []
        self.warnings = []
        self.i_update_frequency = 2  # len(API_CHAT_REFRESH_PERIOD) - 1
        self.reset_multi_messages = set()
        self.update_count = 0
        self.tournament_groups = {"monitored": True, "started": True, "created": True, "finished": True}
        self.msg_lock = Lock()
        self.tournaments_lock = Lock()
        self.reports_lock = Lock()
        self.multi_messages = {}
        self.to_timeout = {}
        self.recommended_timeouts = {}
        self.state_tournaments = 1
        self.state_reports = 1
        self.state_users = 1
        self.cache_tournaments = {'state_tournaments': 0}
        self.cache_reports = {'state_reports': 0}
        # Mod data
        self.users: DefaultDict[str, Dict[UserData]] = defaultdict(dict)
        self.selected_msg_id: DefaultDict[str, int] = defaultdict(int)
        self.state_selected_msg: DefaultDict[str, int] = defaultdict(int)
        self.cache_selected_data: DefaultDict[str, dict] = defaultdict(lambda: {'state_reports': 0})
        self.selected_user_num_recent_timeouts: DefaultDict[str, int] = defaultdict(int)
        self.selected_user_num_recent_comm_warnings: DefaultDict[str, int] = defaultdict(int)
        self.selected_user_lock: DefaultDict[str, Lock] = defaultdict(Lock)  # = Lock()

    def add_error(self, text, is_critical=True):
        if is_critical:
            self.errors.append(text)
        else:
            self.warnings.append(text)
        log(text, to_print=True, to_save=True)

    def wait_api(self):
        now = datetime.now()
        if self.last_api_time:
            wait_s = API_TOURNEY_PAGE_DELAY - delta_s(now, self.last_api_time)
            if wait_s > 0:
                time.sleep(wait_s)
        self.last_api_time = now

    def wait_refresh(self):
        now = datetime.now()
        if self.last_refresh:
            wait_s = API_CHAT_REFRESH_PERIOD[self.i_update_frequency] - delta_s(now, self.last_refresh)
            if wait_s > 0:
                time.sleep(wait_s)
        self.last_refresh = now

    def update_tournaments(self, non_mod):
        if self.processing_lock.locked() or self.errors:
            return
        if self.i_update_frequency == IDX_NO_PAGE_UPDATE:
            time.sleep(1)
            return
        now_utc = datetime.now(tz=tz.tzutc())
        if self.last_tournaments_update and delta_s(now_utc, self.last_tournaments_update) < PERIOD_UPDATE_TOURNAMENTS:
            return
        with self.processing_lock:
            self.last_tournaments_update = now_utc
            try:
                if self.tournament_groups["monitored"] or self.tournament_groups["started"] \
                        or self.tournament_groups["created"]:
                    active_tournaments = {t.id: t for t in get_current_tournaments(non_mod)}
                    keys = list(self.tournaments.keys())
                    for tourn_id in keys:
                        if tourn_id in active_tournaments:
                            self.tournaments[tourn_id].update(active_tournaments[tourn_id])
                            del active_tournaments[tourn_id]
                        elif (not self.tournaments[tourn_id].is_monitored
                              and not self.tournaments[tourn_id].is_active(now_utc)) \
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
                    self.add_error(f"ERROR at {now_utc:%Y-%m-%d %H:%M} UTC: {exception}")  # only if it doesn't work from the very beginning
            except:
                self.add_error("ERROR at {now_utc:%Y-%m-%d %H:%M} UTC in update_tournaments")

    def run(self, non_mod, auto_mod=None):
        if self.processing_lock.locked() or self.errors or self.i_update_frequency == IDX_NO_PAGE_UPDATE:
            return
        with self.processing_lock:
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
                    new_messages, deleted_messages = tourn.download(self.msg_lock, now_utc, non_mod)
                    with self.msg_lock:
                        if not new_messages and tourn.is_error_404_too_long(now_utc) \
                                and not [msg for msg in tourn.messages if msg.score and not msg.is_hidden()]:
                            del self.tournaments[tourn_id]
                            continue
                        self.tournament_messages.update({msg.id: tourn_id for msg in new_messages})
                        self.all_messages.update({msg.id: msg for msg in new_messages})
                        for del_msg in deleted_messages:
                            del self.tournament_messages[del_msg.id]
                            del self.all_messages[del_msg.id]
                        to_timeout_i = tourn.analyse()
                        for m in to_timeout_i.values():
                            add_timeout_msg(self.to_timeout, m)
                        # Process multiline messages and do timeouts
                        multi_msgs, to_timeout_i = tourn.process_frequent_data(now_utc, self.reset_multi_messages)
                        self.multi_messages.update(multi_msgs)
                        for m in to_timeout_i.values():
                            add_timeout_msg(self.to_timeout, m)
                        for msg in self.to_timeout.values():
                            self.api_timeout(msg, msg.best_ban_reason(), False, auto_mod, is_auto=DO_AUTO_TIMEOUTS)
                        self.to_timeout.clear()
            except Exception as exception:
                traceback.print_exception(type(exception), exception, exception.__traceback__)
                self.add_error(f"ERROR at {now_utc:%Y-%m-%d %H:%M} UTC: {exception}")
            except:
                self.add_error("ERROR at {now_utc:%Y-%m-%d %H:%M} UTC in chat.run")
            self.update_count += 1
            self.state_reports += 1

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
                now_utc = datetime.now(tz=tz.tzutc())
                with self.msg_lock:
                    msg.tournament.update_reports(now_utc, self.reset_multi_messages)
                self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            now_utc = datetime.now(tz=tz.tzutc())
            self.add_error(f"ERROR at {now_utc:%Y-%m-%d %H:%M} UTC: {exception}", False)
            self.state_reports += 1

    def set_multi_msg_ok(self, msg_id):
        try:
            msg_id = int(msg_id[1:])
            self.reset_multi_messages.add(msg_id)
            if msg_id in self.multi_messages:
                now_utc = datetime.now(tz=tz.tzutc())
                with self.msg_lock:
                    self.multi_messages[msg_id][0].tournament.update_reports(now_utc, self.reset_multi_messages)
                del self.multi_messages[msg_id]
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            now_utc = datetime.now(tz=tz.tzutc())
            self.add_error(f"ERROR at {now_utc:%Y-%m-%d %H:%M} UTC: {exception}", False)
            self.state_reports += 1

    def is_user_up_to_date(self, name, mod):
        username = self.get_selected_username(mod)
        if not username:
            return True
        if name != username:
            return True
        user = self.users[mod.id].get(name)
        if not user:
            return True
        # Assuming that actions are sorted
        last_action_time = user.actions[0].date if user.actions else None
        self.update_selected_user(mod)
        updated_user = self.users[mod.id].get(name)
        if not updated_user:
            return True
        is_up_to_date = (not updated_user.actions) or (updated_user.actions[0].date <= last_action_time)
        if not is_up_to_date:
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: Failed to apply your action "
                           f"to @{name}. There are new entries in the mod log. Please check them first.", False)
            self.state_reports += 1
        return is_up_to_date

    def api_timeout(self, msg, reason, is_timeout_manual, mod, is_auto=False):
        reason_tag = Reason.to_tag(reason)
        if reason_tag is None:
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: timeout: Unknown reason", False)
            return
        if msg.tournament.id not in self.tournaments:
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: timeout: "
                           f"Tournament {msg.tournament.id} deleted", False)
            return
        if not self.is_user_up_to_date(msg.username, mod):
            return
        chan = "tournament" if msg.tournament.t_type == TournType.Arena \
            else "swiss" if msg.tournament.t_type == TournType.Swiss \
            else "study" if msg.tournament.t_type == TournType.Study \
            else None
        headers = {'Authorization': f"Bearer {mod.token if mod else ''}"}
        text = f'{msg.text[:MAX_LEN_TEXT-1]}…' if len(msg.text) > MAX_LEN_TEXT else msg.text
        data = {'reason': reason_tag,
                'userId': msg.username.lower(),
                'roomId': msg.tournament.id,
                'chan': chan,
                'text': text}
        if is_timeout_manual or (is_auto and mod and mod.is_mod()):
            mod.wait_api('mod/public-chat/timeout')
            url = "https://lichess.org/mod/public-chat/timeout"
            r = requests.post(url, headers=headers, json=data)
            timeout_tag = ('' if is_timeout_manual else '[AUTO] ') if is_auto else ""
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
                self.update_selected_user(mod)
                self.recommended_timeouts.pop(msg.id, None)
            else:
                status_info = "invalid token?" if r.status_code == 200 else f"status: {r.status_code}"
                self.add_error(f"ERROR: Timeout ({status_info}):<br>{timeout_tag}{reason_tag.upper()} "
                               f"<u>Score</u>: {msg.score} <u>User</u>: {msg.username} "
                               f"<u>RoomId</u>: {msg.tournament.id} <u>Channel</u>: {chan} <u>Text</u>: {text}", False)
        else:
            if msg.id not in self.recommended_timeouts:
                print(f"Recommended to time out: {data}")
                now = datetime.now()
                max_time = timedelta(minutes=int(1.5 * CHAT_TOURNAMENT_FINISHED_AGO))
                self.recommended_timeouts[msg.id] = now
                for msg_id in list(self.recommended_timeouts.keys()):
                    if (msg_id not in self.all_messages.keys()) or (now - max_time > self.recommended_timeouts[msg_id]):
                        self.recommended_timeouts.pop(msg_id, None)

    def timeout(self, msg_id, reason, mod):
        try:
            with self.msg_lock:
                msg = self.all_messages.get(int(msg_id[1:]))
                if msg is not None:
                    reason = int(reason)
                    if reason == 0:
                        reason = msg.best_reason()
                    self.api_timeout(msg, reason, True, mod)
                    now_utc = datetime.now(tz=tz.tzutc())
                    msg.tournament.update_reports(now_utc, self.reset_multi_messages)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at{datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: timeout: {exception}", False)
            self.state_reports += 1

    def timeout_multi(self, mmsg_id, reason, mod):
        try:
            with self.msg_lock:
                msg_id = int(mmsg_id[1:])
                msgs = self.multi_messages.get(msg_id)
                if msgs is not None:
                    reason = int(reason)
                    if reason == 0:
                        reason = Reason.Spam #msgs[0].best_reason()
                    combined_text = f'[multiline] {" | ".join([m.text for m in msgs if not m.is_reset])}'
                    combined_msg = Message({'u': msgs[0].username, 't': combined_text}, msgs[0].tournament, msgs[0].time)
                    combined_msg.evaluate(self.tournaments[self.tournament_messages[msg_id]].re_usernames)
                    self.api_timeout(combined_msg, reason, True, mod)
                    now_utc = datetime.now(tz=tz.tzutc())
                    tournament = self.tournaments[self.tournament_messages[msg_id]]
                    tournament.update_reports(now_utc, self.reset_multi_messages)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: timeout_multi: {exception}", False)
            self.state_reports += 1

    def api_warn(self, username, subject, mod, check_updates=True):
        if subject not in ModAction.warnings.values():
            self.add_error(f"ERROR: Warn: @{username}: <u>Subject</u>: {subject}", False)
            self.state_reports += 1
            return
        if check_updates and not self.is_user_up_to_date(username, mod):
            return
        mod.wait_api('mod/warn')
        headers = {'Authorization': f"Bearer {mod.token}"}
        url = f"https://lichess.org/mod/{username}/warn?subject={subject}"
        r = requests.post(url, headers=headers)
        if r.status_code == 200:
            log(f"WARNING @{username}: {subject}", True)
            self.update_selected_user(mod)
        else:
            self.add_error(f"ERROR: Warn (status: {r.status_code}):<br>@{username}: <u>Subject</u>: {subject}", False)
        self.state_reports += 1

    def api_kidMode(self, username, mod, to_update):
        if not self.is_user_up_to_date(username, mod):
            return False
        mod.wait_api('mod/kid')
        headers = {'Authorization': f"Bearer {mod.token}"}
        url = f"https://lichess.org/mod/{username}/kid"
        r = requests.post(url, headers=headers)
        if r.status_code == 200:
            log(f"ACTION @{username}: kidMode", True)
            if to_update:
                self.update_selected_user(mod)
                self.state_reports += 1
            return True
        else:
            self.add_error(f"ERROR: action (status: {r.status_code}):<br>@{username}: kidMode", False)
            self.state_reports += 1
        return False

    def api_SB(self, username, mod):
        if not self.is_user_up_to_date(username, mod):
            return
        mod.wait_api('mod/troll')
        headers = {'Authorization': f"Bearer {mod.token}"}
        url = f"https://lichess.org/mod/{username}/troll/true"
        r = requests.post(url, headers=headers)
        if r.status_code == 200:
            log(f"SB @{username}", True)
            self.update_selected_user(mod)
        else:
            self.add_error(f"ERROR: SB (status: {r.status_code}):<br>@{username}", False)
        self.state_reports += 1

    def warn(self, username, subject_tag, mod):
        try:
            if subject_tag == "SB":
                self.api_SB(username, mod)
            else:
                warning = ModAction.warnings.get(subject_tag)
                if warning:
                    if subject_tag == "kidMode":
                        # TODO: check if kidMode is set already (after?)
                        is_set = self.api_kidMode(username, mod, False)
                        if is_set:
                            self.api_warn(username, warning, mod, check_updates=False)
                    elif subject_tag in ModAction.warnings:
                        self.api_warn(username, warning, mod)
                    else:
                        print(f"WRONG WARNING @{username}: {warning}")
                else:
                    self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: warn @{username}: "
                                   f"INCORRECT WARNING: {subject_tag}", False)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: warn @{username}: "
                           f"{exception}", False)
            self.state_reports += 1

    def custom_timeout(self, msg_ids, reason, mod):
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
                    now_utc = datetime.now(tz=tz.tzutc())
                    if len(msgs) > 1:
                        combined_text = f'[multiline] {" | ".join([m.text for m in msgs])}'
                        combined_msg = Message({'u': msgs[0].username, 't': combined_text}, msgs[0].tournament, msgs[0].time)
                        first_msg_id = int(msg_ids[0][1:])
                        combined_msg.evaluate(self.tournaments[self.tournament_messages[first_msg_id]].re_usernames)
                        self.api_timeout(combined_msg, reason, True, mod)
                    else:
                        self.api_timeout(msgs[0], reason, True, mod)
                    msgs[0].tournament.update_reports(now_utc, self.reset_multi_messages)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: custom_timeout: {exception}", False)
            self.state_reports += 1

    def set_update(self, i_update_frequency):
        if i_update_frequency is None:
            return
        try:
            self.i_update_frequency = max(0, min(len(API_CHAT_REFRESH_PERIOD), int(i_update_frequency)))
        except:
            return

    def get_selected_username(self, mod):
        if not self.selected_msg_id[mod.id]:
            return None
        msg = self.all_messages.get(self.selected_msg_id[mod.id])
        if not msg:
            return None
        return msg.username

    def update_selected_user(self, mod):
        try:
            username = self.get_selected_username(mod)
            if not username:
                return
            user = UserData(username, mod)
            now_utc = datetime.now(tz=tz.tzutc())
            if mod.to_read_mod_log and (mod.last_mod_log_error is None
                                        or now_utc > mod.last_mod_log_error + timedelta(minutes=DELAY_ERROR_READ_MOD_LOG)):
                with self.selected_user_lock[mod.id]:
                    self.selected_user_num_recent_timeouts[mod.id] = 0
                    self.selected_user_num_recent_comm_warnings[mod.id] = 0
                    mod_log_data = load_mod_log(username, mod)
                    if mod_log_data is None:
                        mod.last_mod_log_error = now_utc
                    else:
                        user.mod_log, user.actions = get_mod_log(mod_log_data, mod, ModActionType.Chat)
                        time_last_SB = None
                        for action in user.actions:
                            dt = action.get_datetime()
                            if action.is_SB() and (time_last_SB is None or dt > time_last_SB):
                                time_last_SB = dt
                        time_last_comm_warning = None
                        for action in user.actions:
                            if action.is_comm_warning() and not action.is_old(now_utc):
                                dt = action.get_datetime()
                                if time_last_SB is None or dt > time_last_SB:
                                    self.selected_user_num_recent_comm_warnings[mod.id] += 1
                                    if time_last_comm_warning is None or dt > time_last_comm_warning:
                                        time_last_comm_warning = dt
                        for action in user.actions:
                            if action.is_timeout() and not action.is_old(now_utc):
                                dt = action.get_datetime()
                                if (time_last_comm_warning is None or dt > time_last_comm_warning) and \
                                   (time_last_SB is None or dt > time_last_SB):
                                    self.selected_user_num_recent_timeouts[mod.id] += 1
                        mod.last_mod_log_error = None
            else:
                mod_log_data = None
            if mod.to_read_notes and (mod.last_notes_error is None
                                      or now_utc > mod.last_notes_error + timedelta(minutes=DELAY_ERROR_READ_MOD_LOG)):
                user.notes = get_notes(username, mod, mod_log_data)
                if user.notes is None:
                    mod.last_notes_error = now_utc
                    user.notes = ""
                else:
                    mod.last_notes_error = None
            for un in list(self.users[mod.id].keys()):
                if delta_s(now_utc, self.users[mod.id][un].time_update) > LIFETIME_USER_CACHE:
                    del self.users[mod.id][un]
            self.users[mod.id][username] = user
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)

    def select_message(self, msg_id, mod):
        def create_info(info):
            state_all = self.state_reports + self.state_users + self.state_selected_msg[mod.id]
            return {'selected-messages': info, 'filtered-messages': info, 'selected-tournament': "", 'selected-user': "",
                    'mod-notes': "", 'mod-log': "", 'user-info': "", 'user-profile': "", 'state_reports': state_all}

        try:
            self.state_selected_msg[mod.id] += 1
            if msg_id == "--":
                self.selected_msg_id[mod.id] = 0
                return create_info("")
            self.selected_msg_id[mod.id] = int(msg_id[1:])
            self.update_selected_user(mod)
            return self.get_messages_nearby(self.selected_msg_id[mod.id], mod)
        except Exception as exception:
            self.selected_msg_id[mod.id] = 0
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return create_info(f'<p class="text-danger">Error: {exception}</p>')
        except:
            self.selected_msg_id[mod.id] = 0
            return create_info(f'<p class="text-danger">Error: get_messages_near()</p>')

    def get_messages_nearby(self, msg_id, mod):
        def get_warn_btn(subject_tag, btn_title, is_highlighted, user_name, is_disabled=False, txt_class=""):
            if is_highlighted:
                btn_title = f'<b class="{txt_class}">{btn_title}</b>' if txt_class and not is_disabled \
                    else f'<b>{btn_title}</b>'
            elif txt_class and not is_disabled:
                btn_title = f'<span class="{txt_class}">{btn_title}</span>'
            btn_class = "btn-secondary disabled" if is_disabled else "btn-primary"
            return f'<button class="dropdown-item {btn_class}" onclick="warn(\'{user_name}\',\'{subject_tag}\');">' \
                   f'{btn_title}</button>'

        def is_recent(times, key, time_now):
            return (times[key] is not None) and (delta_s(time_now, times[key]) <= RECENT_WARNING)

        def add_comm_info(user_data, user_msgs):
            add_info = ""
            with self.selected_user_lock[mod.id]:
                if self.selected_user_num_recent_comm_warnings[mod.id] > 0:
                    text_theme = "text-danger" if self.selected_user_num_recent_comm_warnings[mod.id] > 1 else "text-warning"
                    add_info = f'<span class="{text_theme}"><b>{self.selected_user_num_recent_comm_warnings[mod.id]}</b> ' \
                               f'comm warning{"" if self.selected_user_num_recent_comm_warnings[mod.id] == 1 else "s"}' \
                               f'</span>'
                if self.selected_user_num_recent_timeouts[mod.id] > 0:
                    text_theme = "text-danger" if self.selected_user_num_recent_timeouts[mod.id] >= 5 else "text-warning"
                    add_info = f'{add_info}{" + " if add_info else ""}<span class="{text_theme}">' \
                               f'<b>{self.selected_user_num_recent_timeouts[mod.id]}</b> ' \
                               f'timeout{"" if self.selected_user_num_recent_timeouts[mod.id] == 1 else "s"}</span>'
            if mod.is_mod() and user_msgs:
                user_name = user_data.name
                is_timed_out = False
                is_banable = False
                reasons = [0] * Reason.Size
                for user_msg in user_msgs:
                    if user_msg.is_timed_out:
                        is_timed_out = True
                        i_reason = user_msg.best_reason()
                        if i_reason:
                            reasons[i_reason] += 1
                            is_banable = user_msg.is_banable()
                last_time = {'SB': None, 'timeout': None, 'spam': None, 'insult': None, 'trolling': None,
                             'shaming': None, 'ad': None, 'team_ad': None}
                last_timeout_reason = Reason.No
                is_SBed = False  # workaround as I have no idea how to get this flag any other way
                is_kid = False  # same here
                for action in user_data.actions:
                    dt = action.get_datetime()
                    if (action.action == 'troll' or action.action == 'untroll') \
                            and (last_time['SB'] is None or dt > last_time['SB']):
                        last_time['SB'] = dt
                        is_SBed = action.is_SB()
                    elif action.is_timeout() and (last_time['timeout'] is None or dt > last_time['timeout']):
                        last_time['timeout'] = dt
                        last_timeout_reason = action.get_timeout_reason()
                    elif action.is_kidMode() and (user_msgs[-1].delay is None or dt >= user_msgs[-1].time
                                                  - timedelta(seconds=user_msgs[-1].delay)):
                        is_kid = True
                    elif action.action == 'modMessage':
                        if action.is_spam() and (last_time['spam'] is None or dt > last_time['spam']):
                            last_time['spam'] = dt
                        elif action.is_insult() and (last_time['insult'] is None or dt > last_time['insult']):
                            last_time['insult'] = dt
                        elif action.is_trolling() and (last_time['trolling'] is None or dt > last_time['trolling']):
                            last_time['trolling'] = dt
                        elif action.is_shaming() and (last_time['shaming'] is None or dt > last_time['shaming']):
                            last_time['shaming'] = dt
                        elif action.is_ad() and (last_time['ad'] is None or dt > last_time['ad']):
                            last_time['ad'] = dt
                        elif action.is_team_ad() and (last_time['team_ad'] is None or dt > last_time['team_ad']):
                            last_time['team_ad'] = dt
                now_utc = datetime.now(tz=tz.tzutc())
                is_recent_timeout = last_time['timeout'] and delta_s(now_utc, last_time['timeout']) <= RECENT_TIMEOUT
                if last_timeout_reason != Reason.No and is_recent_timeout:
                    reasons[last_timeout_reason] += 1
                buttons = []
                if is_timed_out or is_recent_timeout:
                    buttons.append(get_warn_btn('spam', "Warn: Spam", reasons[Reason.Spam], user_name,
                                                is_disabled=is_recent(last_time, 'spam', now_utc)))
                    buttons.append(get_warn_btn('insult', "Warn: Insult", reasons[Reason.Offensive], user_name,
                                                is_disabled=is_recent(last_time, 'insult', now_utc)))
                    buttons.append(get_warn_btn('trolling', "Warn: Trolling", reasons[Reason.Other], user_name,
                                                is_disabled=is_recent(last_time, 'trolling', now_utc)))
                    buttons.append(get_warn_btn('shaming', "Warn: Shaming", reasons[Reason.Shaming], user_name,
                                                is_disabled=is_recent(last_time, 'shaming', now_utc)))
                    buttons.append(get_warn_btn('ad', "Warn: Ads", False, user_name,
                                                is_disabled=is_recent(last_time, 'ad', now_utc)))
                    buttons.append(get_warn_btn('team_ad', "Warn: Team Ad", False, user_name,
                                                is_disabled=is_recent(last_time, 'team_ad', now_utc)))
                    buttons.append('<div class="dropdown-divider my-1"></div>')
                    is_SBable = user_data.notes and (is_banable or self.selected_user_num_recent_comm_warnings[mod.id]
                                                     or self.selected_user_num_recent_timeouts[mod.id])
                    buttons.append(get_warn_btn('SB', "Shadowban", True, user_name, txt_class="text-danger",
                                                is_disabled=is_SBed or not is_SBable))
                kid_sus = ChatAnalysis.kid_years.search(user_data.profile.bio)
                if buttons or (not is_kid and not is_SBed):
                    buttons.append(get_warn_btn('kidMode', "Kid Mode", kid_sus, user_name, txt_class="text-warning",
                                                is_disabled=is_kid))
                if buttons:
                    btn_class = "btn-warning" if (kid_sus and not is_kid) or (len(buttons) > 1) else "btn-secondary"
                    button_warn = f'<button class="btn {btn_class} nav-item dropdown-toggle align-baseline mr-1 px-1 py-0" '\
                        f'id="warn-ban" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"' \
                        f'style="cursor:pointer;">Action</button><span class="dropdown-menu" style="">' \
                        f'{"".join(buttons)}</span>'
                    add_info = f'<div class="d-flex justify-content-between">' \
                               f'<span>{add_info}</span><span>{button_warn}</span></div>'
            return add_info

        def create_output(info, tournament, user_data, filtered_info=None, user_msgs=None):
            data = {'selected-messages': info, 'filtered-messages': filtered_info or info,
                    'selected-tournament': tournament}
            if user_data:
                user_info = user_data.get_user_info(CHAT_CREATED_DAYS_AGO, CHAT_NUM_PLAYED_GAMES)
                add_info = add_comm_info(user_data, user_msgs)
                if add_info:
                    user_info = f'{user_info}<div>{add_info}</div>'
                data.update({'selected-user': user_data.name, 'user-profile': user_data.get_profile(),
                             'user-info': user_info, 'mod-notes': user_data.notes, 'mod-log': user_data.mod_log})
            else:
                data.update({'selected-user': "", 'mod-notes': "", 'mod-log': "", 'user-info': "", 'user-profile': ""})
            data['state_reports'] = self.state_reports + self.state_users + self.state_selected_msg[mod.id]
            self.cache_selected_data[mod.id] = data
            return data

        def make_selected(msg_selected):
            return f'<div class="border border-success rounded" style="{get_highlight_style(0.3)}">{msg_selected}</div>'

        tournament_name = ""
        try:
            tourn_id = self.tournament_messages.get(msg_id)
            tournament_name = self.tournaments[tourn_id].get_link(short=False) if tourn_id in self.tournaments else ""
            if not msg_id:
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
                user_msgs = [(msg_i if msg_user.id == msg_id else msg_user)
                             for msg_user in self.tournaments[tourn_id].messages if msg_user.username == msg_i.username]
                list_start = '<hr class="text-primary my-1" style="border:1px solid;">' if i_start == 0 else ""
                list_end = '<hr class="text-primary mt-1 mb-0" style="border:1px solid;">'\
                           if i_end == len(self.tournaments[tourn_id].messages) else ""
                username = msg_i.username
            u = self.users[mod.id].get(username)
            if not u or not u.is_up_to_date():
                self.update_selected_user(mod)
            user = self.users[mod.id].get(username)
            info_selected = f'{list_start}{"".join(msgs_before)} {msg} {"".join(msgs_after)}{list_end}'
            info_filtered = "".join(msgs_user)
            return create_output(info_selected, tournament_name, user, filtered_info=info_filtered, user_msgs=user_msgs)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return create_output(f'<p class="text-danger">Error: {exception}</p>', tournament_name, None)
        except:
            return create_output(f'<p class="text-danger">Error: get_messages_near()</p>', tournament_name, None)

    def update_selected_data(self, mod):
        state_all = self.state_reports + self.state_users + self.state_selected_msg[mod.id]
        if state_all != self.cache_selected_data[mod.id]['state_reports']:
            self.get_messages_nearby(self.selected_msg_id[mod.id], mod)

    def clear_errors(self, tourn_id):
        try:
            if tourn_id == "global":
                self.errors.clear()
                self.warnings.clear()
            else:
                tournament = self.tournaments.get(tourn_id)
                if tournament:
                    tournament.clear_errors()
                    now_utc = datetime.now(tz=tz.tzutc())
                    tournament.update_reports(now_utc, self.reset_multi_messages)
                else:
                    self.add_error(f"ERROR: Failed to clear tournament errors: \"{tourn_id}\"", False)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: clear_errors({tourn_id}): "
                           f"{exception}", False)
        self.state_reports += 1

    def set_tournament(self, tourn_id, checked):
        tournament = self.tournaments.get(tourn_id)
        if not tournament:
            self.add_error(f"ERROR: No tournament \"{tourn_id}\" to set {checked}", False)
            self.state_reports += 1
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

    def add_tournament(self, page, mod):
        # while self.processing_lock.locked():
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
                    headers = {}  # {'Authorization': f"Bearer {mod.token}"}
                    if page.startswith(arena_tournament_page) and i == len(arena_tournament_page) - 1:
                        mod.wait_api('api/tournament/id')
                        r = requests.get(f"https://lichess.org/api/tournament/{tourn_id}", headers=headers)
                        if r.status_code != 200:
                            raise Exception(f"ERROR /api/tournament/{tourn_id}: Status Code {r.status_code}")
                        arena = r.json()
                        if tourn_id != arena['id']:
                            raise Exception(f"ERROR {page}: Wrong ID {tourn_id} != {arena['id']}")
                        self.tournaments[tourn_id] = Tournament(arena, TournType.Arena, is_monitored=True)
                    elif page.startswith(swiss_tournament_page) and i == len(swiss_tournament_page) - 1:
                        mod.wait_api('api/swiss')
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

    def get_all(self, mod):
        with self.reports_lock:
            if self.state_reports != self.cache_reports['state_reports']:
                # Main content
                now_utc = datetime.now(tz=tz.tzutc())
                now = datetime.now()
                active_tournaments = self.get_score_sorted_tournaments(now_utc)
                info = "".join([tourn.reports for tourn in active_tournaments])  # TODO: update time status in the header
                output = []
                for tourn in active_tournaments:
                    if tourn.multiline_reports:
                        output.extend(tourn.multiline_reports)
                output.sort(key=lambda t: t[0], reverse=True)
                info_frequent = "".join([info for score, info in output])
                all_errors = self.errors.copy()
                all_errors.extend(self.warnings)
                if all_errors:
                    btn_clear = f'<div><button class="btn btn-info align-baseline flex-grow-1 py-0 px-1" ' \
                                f'onclick="clear_errors(\'global\');">Clear errors</button></div>'
                    info = f'<div class="text-warning text-break">{"<b>Errors</b>: " if len(all_errors) > 1 else ""}' \
                           f'<div>{"</div><div>".join(all_errors)}</div>{btn_clear}' \
                           f'<div class="text-danger">ABORTED</div></div>{info}'
                str_time = f"{now:%H:%M}"
                self.cache_reports = {'reports': info, 'multiline-reports': info_frequent,
                                      'time': str_time, 'state_reports': self.state_reports}
            self.update_selected_data(mod)
            ret_data = self.cache_reports.copy()
            ret_data.update(self.cache_selected_data[mod.id])
            return ret_data

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

    def send_note(self, note, username, mod):
        try:
            if not note or not username:
                raise Exception(f"Wrong note: [{username}]: {note}")
            if note and username:
                is_ok = add_note(username, note, mod)
                if is_ok:
                    user = self.users[mod.id].get(username)
                    if user and user.is_up_to_date():
                        mod_notes = get_notes(username, mod)
                        user.notes = mod_notes
                        data = {'selected-user': username, 'mod-notes': mod_notes}
                    else:
                        self.update_selected_user(mod)
                        data = {}
                    self.state_users += 1
                    add_data = self.get_messages_nearby(self.selected_msg_id[mod.id], mod)
                    data.update(add_data)
                    return data
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.add_error(f"ERROR at {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M} UTC: send_note: {exception}", False)
            self.state_reports += 1
        return {'selected-user': username, 'mod-notes': "", 'user-profile': "", 'user-info': ""}


def get_current_tournaments(non_mod):
    headers = {}  # {'Authorization': f"Bearer {mod.token}"}
    # Arenas of official teams
    arenas = []
    for teamId in official_teams:
        url = f"https://lichess.org/api/team/{teamId}/arena"
        data = get_ndjson(url, non_mod, "api/team/arena", Accept="application/nd-json")
        arenas.extend(data)
    # Arena
    non_mod.wait_api('api/tournament')
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
        swiss_data = get_ndjson(url, non_mod, "api/team/swiss", Accept="application/nd-json")
        for swiss in swiss_data:
            try:
                tourn = Tournament(swiss, TournType.Swiss)
                if tourn.is_active(now_utc):
                    tournaments.append(tourn)
            except Exception as exception:
                traceback.print_exception(type(exception), exception, exception.__traceback__)
    # Broadcast
    url = f"https://lichess.org/api/broadcast?nb={NUM_RECENT_BROADCASTS_TO_FETCH}"
    broadcast_data = get_ndjson(url, non_mod, "api/broadcast", Accept="application/nd-json")
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
