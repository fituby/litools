import requests
from datetime import datetime, timedelta
from dateutil import tz
import time
import json
from fake_useragent import UserAgent
import traceback
from enum import Enum, IntFlag
from multiprocessing import Lock
import yaml
from elements import Reason, get_token, get_ndjson, deltaseconds, deltaperiod, shorten, log, config_file
from elements import STYLE_WORD_BREAK
from chat_re import ReUser, list_res, list_res_variety, re_spaces


CHAT_TOURNAMENT_FINISHED_AGO = 12 * 60  # [min]
CHAT_TOURNAMENT_STARTS_IN = 6 * 60  # [min]
CHAT_SWISS_STARTED_AGO = 6 * 60  # [min]
MAX_LEN_TOURNEY_NAME_SHORT = 25
MAX_LEN_TOURNEY_NAME_LONG = 40
NUM_RECENT_BROADCASTS_TO_FETCH = 20

API_TOURNEY_PAGE_DELAY = 1.0  # [s]
IDX_NO_PAGE_UPDATE = 0
API_CHAT_REFRESH_PERIOD = [1, 5, 25, 60]  # [s]
PERIOD_UPDATE_TOURNAMENTS = 60  # [s]
TIME_FREQUENT_MESSAGES = 5  # [s]
MAX_TIME_FREQUENT_MESSAGES = 60  # [s]
NUM_FREQUENT_MESSAGES = 9
NUM_MSGS_BEFORE = 10
NUM_MSGS_AFTER = 10
TIMEOUT_RANGE = [25, 25]  # [min]

CHAT_NUM_VISIBLE_MSGS = 450
CHAT_MAX_NUM_MSGS = 500
CHAT_FREQUENT_MSGS_MIN_SCORE = 10
CHAT_BEGINNING_MESSAGES_TEXT = '"name":"Chat room","lines":['
CHAT_END_MESSAGES_TEXT = '],"userId":'
TOURNEY_STANDING_BEGINNING_TEXT = '"standing":{"page":1,"players":['
TOURNEY_STANDING_ENDING_TEXT = ']},"socketVersion":'
HR = '<hr class="my-0" style="border-top:dotted 2px;"/>'
CHAT_UPDATE_SWISS = False  # loading messages from swiss tourneys doesn't work at the moment anyway
DO_AUTO_TIMEOUTS = False
MULTI_MSG_MIN_TIMEOUT_SCORE = 300
MAX_LEN_TEXT = 140


def get_highlight_style(opacity):
    return f"background-color:rgba(0,160,119,{opacity});"


class AddButtons(IntFlag):
    No = 0
    Ban = 1
    Dismiss = 2
    BanAndDismiss = 3


def load_res():
    try:
        with open(config_file) as stream:
            config = yaml.safe_load(stream)
            timeouts = config.get('timeouts', "En, Spam").lower()
            list_re = []
            for group in ['En', 'Ru', 'De', 'Es', 'It', 'Hi', 'Fr', 'Tr', 'Spam']:
                if group.lower() in timeouts:
                    list_re.extend(list_res[group])
            list_re_variety = list_res_variety if 'spam' in timeouts else []
    except Exception as e:
        print(f"There appears to be a syntax problem with your config.yml: {e}")
        list_re = [list_res['En']]
        list_re.extend(list_res['Spam'])
        list_re_variety = list_res_variety
    return list_re, list_re_variety


class Message:
    global_id = 0
    list_res, list_res_variety = load_res()

    def __init__(self, data, tournament, now=None):
        self.id: int = None
        self.time: datetime = now
        self.username = data['u']
        self.text = data['t']
        self.eval_text = ""
        self.is_official = (self.username == "lichess")
        self.is_deleted = False  # was available before and now isn't on the page
        self.is_removed = data.get('r', False)  # SB'ed, was never visible
        self.is_disabled = data.get('d', False)  # deleted by mods
        self.is_reset = False  # processed as good
        self.is_timed_out = False  # processed as bad
        self.tournament = tournament
        self.score: int = None
        self.reasons = [0] * Reason.Size
        self.scores = [0] * Reason.Size

    def best_ban_reason(self):
        ban_sum = sum(self.reasons)
        if ban_sum < 1:
            return int(Reason.No)
        arg_max = max(range(len(self.reasons)), key=self.reasons.__getitem__)
        return arg_max

    def best_score_reason(self):
        if max(self.scores) == 0:
            return int(Reason.No)
        arg_max = max(range(len(self.scores)), key=self.scores.__getitem__)
        return arg_max

    def best_reason(self):
        reason = self.best_ban_reason()
        if reason != Reason.No:
            return reason
        return self.best_score_reason()

    def format_reason(self, i_reason, text, add_reason, best_reason):
        if self.scores[i_reason] == 0 and i_reason != add_reason:
            return text
        if i_reason == best_reason:
            return f'<b class="text-warning">{text}</b>'
        return f'<b>{text}</b>'

    def update(self, msg):
        self.is_removed = msg.is_removed
        self.is_disabled = msg.is_disabled

    def __eq__(self, other):
        return self.username.lower() == other.username.lower() and self.text == other.text \
               and self.tournament == other.tournament

    def __repr__(self):
        return f"[{self.username}]: {self.text}"

    def evaluate(self, re_usernames):
        if self.is_official:
            self.eval_text = self.text
            self.score = 0
            return
        try:
            # Remove multiple spaces
            text = re_spaces.sub(" ", self.text)
            # Add usernames and evaluate
            res_all = re_usernames.copy()
            res_all.extend(Message.list_res)
            result_all = res_all[0].eval(text, res_all, 0)
            result_variety = Message.list_res_variety[0].eval(text, Message.list_res_variety, 0)
            ban_points_all = sum(result_all.ban_points)
            ban_points_variety = sum(result_variety.ban_points)
            result = result_all if ban_points_all > ban_points_variety else result_variety \
                if ban_points_all < ban_points_variety or result_all.total_score() < result_variety.total_score() \
                else result_all
            self.eval_text = result.element
            self.scores = result.scores
            self.score = result.total_score()
            self.reasons = result.ban_points
            if self.score >= 50:
                self.eval_text.replace('<span class="text-warning"', '<span class="text-danger"')
                if self.score > 60:
                    self.eval_text.replace('<span class="text-warning"', '<span class="text-danger bg-warning"')
        except Exception as exception:
            print(f"ERROR when processing: {self}")
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.eval_text = self.text
            self.score = 0

    def is_hidden(self):
        return self.is_deleted or self.is_removed or self.is_disabled or \
               self.is_reset or self.is_timed_out or self.is_official

    def get_info(self, tag, show_hidden=None, add_buttons=None, base_time=None, rename_dismiss=None,
                 add_user=True, add_mscore=False, add_reason=None, highlight_user=None, allow_selection=True):
        if show_hidden is None:
            show_hidden = (base_time is not None)
        if add_buttons is None:
            add_buttons = AddButtons.BanAndDismiss if base_time is None else AddButtons.No
        if self.is_official or self.is_disabled or self.is_removed:
            add_buttons = AddButtons.No
        elif (self.score == 0 and not rename_dismiss) or self.is_reset or self.is_timed_out:
            add_buttons &= ~AddButtons.Dismiss
        if not show_hidden and (self.is_hidden() or not self.score):
            return ""
        if base_time is None:
            str_time = ""
        else:
            ds = deltaseconds(self.time, base_time)
            dt = f"{abs(ds)}s" if abs(ds) < 60 \
                else f"{abs(ds // 60)}m{abs(ds % 60):02d}s" if abs(ds) < 300 \
                else f"{abs(int(round(ds / 60)))}m"
            str_time = f"&minus;{dt} " if ds < 0 else f'+{dt} ' if ds > 0 else "== "
            str_time = f'<span class="user-select-none">{str_time}</span>'
        score_theme = "" if self.score is None else ' text-danger' if self.score > 50 \
            else ' text-warning' if self.score > 10 else ""
        score = f'<span class="user-select-none{score_theme}">{self.score}</span>' if self.score > 0 else ""
        username = f"<b><u>{self.username}</u></b>" if highlight_user is True or highlight_user == self.username \
            else self.username
        user = f'<a class="text-info user-select-none" href="https://lichess.org/@/{self.username.lower()}" target="_blank" ' \
               f'onclick="prevent_click(event)">{username}</a>' if add_user else ""
        highlight_style = "" if not highlight_user or highlight_user != self.username else get_highlight_style(0.2)
        name_dismiss = rename_dismiss if rename_dismiss else "Dismiss"
        class_dismiss = "btn-secondary" if rename_dismiss else "btn-primary"
        button_dismiss = f'<button class="btn {class_dismiss} text-nowrap align-baseline flex-grow-0 py-0 px-1 ml-1" ' \
                         f'onclick="set_ok(\'{tag}{self.id}\');">{name_dismiss}</button> ' \
                         if add_buttons & AddButtons.Dismiss else ""
        best_ban_reason = self.best_ban_reason()
        best_reason = best_ban_reason if best_ban_reason != Reason.No else self.best_score_reason()
        if best_reason == Reason.No and add_reason is not None:
            best_reason = int(add_reason)
        r = Reason.to_Tag(best_reason)
        class_ban = "btn-warning" if self.score >= 50 else "btn-secondary"
        button_ban = f'<button class="btn {class_ban} nav-item dropdown-toggle align-baseline mr-1 px-1 py-0" ' \
                     f'data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="cursor:pointer;">' \
                     f'Ban</button><span class="dropdown-menu" style="">' \
                     f'<button class="dropdown-item btn-primary" onclick="timeout(\'{tag}{self.id}\', 1);">' \
                        f'{self.format_reason(Reason.Shaming, "Public Shaming", add_reason, best_reason)}</button>' \
                     f'<button class="dropdown-item btn-primary" onclick="timeout(\'{tag}{self.id}\', 2);">' \
                        f'{self.format_reason(Reason.Offensive, "Offensive Language", add_reason, best_reason)}</button>' \
                     f'<button class="dropdown-item btn-primary" onclick="timeout(\'{tag}{self.id}\', 3);">' \
                        f'{self.format_reason(Reason.Spam, "Spamming", add_reason, best_reason)}</button>' \
                     f'<button class="dropdown-item btn-primary" onclick="timeout(\'{tag}{self.id}\', 4);">' \
                        f'{self.format_reason(Reason.Other, "Inappropriate Behaviour", add_reason, best_reason)}</button>' \
                     f'</span>' if add_buttons & AddButtons.Ban else ""
        if add_buttons & AddButtons.Ban:
            if best_ban_reason != Reason.No or (best_reason != Reason.No and self.score >= 50):
                button_ban = f'<button class="btn btn-danger align-baseline flex-grow-0 py-0 px-1" ' \
                             f'onclick="timeout(\'{tag}{self.id}\');">{r}</button>{button_ban}'
        class_name = "text-muted" if self.is_deleted or self.is_reset \
            else "text-secondary" if self.is_removed or self.is_disabled or self.is_timed_out or self.is_official else ""
        text = f'<s style="text-decoration-style:double;">{self.eval_text}</s>' if self.is_removed \
            else f'<s style="text-decoration-style:dotted;"><u style="text-decoration-style:wavy;">{self.eval_text}</u></s>' if self.is_timed_out \
            else f'<s>{self.eval_text}</s>' if self.is_disabled \
            else f'<small>{self.eval_text}</small>' if self.is_reset \
            else f'<small><i>{self.eval_text}</i></small>' if self.is_official \
            else f'<s style="text-decoration-style:wavy;">{self.eval_text}</s>' if self.is_deleted \
            else self.eval_text
        text = f'<span class="{class_name}" style="{STYLE_WORD_BREAK}">{text}</span>'
        mscore = f' data-mscore={self.score}' if add_mscore else ""
        onclick = f' onclick="select_message(event,\'{tag}{self.id}\')"' if allow_selection else ""
        if add_buttons == AddButtons.No:
            return f'<div id="msg{tag}{self.id}"{mscore} class="align-items-baseline selectee px-1" ' \
                   f'style="{STYLE_WORD_BREAK}{highlight_style}"{onclick}>' \
                   f'{str_time}{user} <b>{score}</b> {text}</div>'
        elif add_buttons & AddButtons.Ban:
            return f'<div id="msg{tag}{self.id}"{mscore} class="align-items-baseline selectee px-1" ' \
                   f'style="{STYLE_WORD_BREAK}{highlight_style}"{onclick}>' \
                   f'<div class="d-flex justify-content-between"><span>{button_ban}{str_time}{user} {text}</span> ' \
                   f'<span class="text-nowrap"><b class="pl-2">{score}</b>{button_dismiss}</span></div></div>'
        else:
            return f'<div id="msg{tag}{self.id}"{mscore} class="align-items-baseline selectee px-1" ' \
                   f'style="{highlight_style}"{onclick}>' \
                   f'<div class="d-flex justify-content-between">' \
                   f'<span class="d-flex flex-row">{button_ban}{str_time}{user}</span>' \
                   f'<span class="d-flex flex-row">{score}{button_dismiss}</span></div>' \
                   f'<div class="align-items-baseline" style="{STYLE_WORD_BREAK}">{text}</div></div>'


class Type(Enum):
    Unknown = 0
    Arena = 1
    Swiss = 2
    Study = 3


def add_timeout_msg(timeouts, msg):
    user_msg = timeouts.get(msg.username)
    if user_msg is None or msg.score > user_msg.score:
        timeouts[msg.username] = msg


class Tournament:
    def __init__(self, tourney, t_type, link="", is_monitored=False):
        self.t_type = t_type
        self.id = tourney['id']
        self.is_official = (tourney['createdBy'] == "lichess")
        self.num_players = tourney['nbPlayers']
        if t_type == Type.Arena:
            self.startsAt = datetime.fromtimestamp(tourney['startsAt'] // 1000, tz=tz.tzutc())
            self.name = tourney['fullName'].rstrip('Arena').strip()
            self.finishesAt = datetime.fromtimestamp(tourney['finishesAt'] // 1000, tz=tz.tzutc())
        else:
            self.startsAt = tourney['startsAt']
            self.name = f"Swiss {tourney['name']}" if t_type == Type.Swiss else tourney['name']
            self.finishesAt = (tourney['status'] == 'finished')
        self.messages = []
        self.user_names = set()
        self.re_usernames = []
        self.errors = []
        self.max_score = 0
        self.total_score = 0
        self.is_monitored = is_monitored
        self.is_enabled = True
        self.link = link
        self.last_update: datetime = None

    def update(self, tourn):
        self.startsAt = tourn.startsAt
        self.finishesAt = tourn.finishesAt
        self.num_players = tourn.num_players

    def finish_time_estimated(self):
        if self.t_type == Type.Arena:
            return self.finishesAt
        elif self.t_type == Type.Swiss:
            minutes = 300 if "Classical" in self.name else 120 if "Rapid" in self.name else \
                100 if "SuperBlitz" in self.name else 120 if "Blitz" in self.name else \
                20 if "HyperBullet" in self.name else 40 if "Bullet" in self.name else None
            if minutes is None:
                return None
            return self.startsAt + timedelta(minutes=minutes)
        return None

    def is_active(self, now_utc):
        if not self.is_enabled:
            return False
        if deltaseconds(self.startsAt, now_utc) >= CHAT_TOURNAMENT_STARTS_IN * 60:
            return False
        finishes_at = self.finish_time_estimated()
        if finishes_at is not None:
            return deltaseconds(now_utc, finishes_at) < CHAT_TOURNAMENT_FINISHED_AGO * 60
        if not self.finishesAt:
            return True
        return deltaseconds(now_utc, self.startsAt) < CHAT_SWISS_STARTED_AGO * 60

    def get_state(self, now_utc):
        if self.is_created(now_utc):
            return "created"
        if self.is_finished(now_utc):
            return "finished"
        return "started"

    def is_ongoing(self, now_utc):
        return now_utc >= self.startsAt and not self.is_finished(now_utc)

    def is_created(self, now_utc):
        return now_utc < self.startsAt

    def is_finished(self, now_utc):
        return (self.t_type == Type.Arena and now_utc >= self.finishesAt) \
               or (self.t_type != Type.Arena and self.finishesAt)

    def priority_score(self):
        return self.max_score * 9999 + self.total_score

    def priority_time(self, now_utc):
        monitored = 9999999 if self.is_monitored else 0
        if self.is_ongoing(now_utc):
            return monitored + 999999 + 10 * self.num_players + len(self.messages)
        if self.is_finished(now_utc):
            finishes_at = self.finish_time_estimated()
            if finishes_at is not None:
                return monitored + 99999 + min(0, deltaseconds(finishes_at, now_utc))
            return monitored + 99999 + deltaseconds(self.startsAt, now_utc)
        return monitored + deltaseconds(now_utc, self.startsAt)

    def update_period(self, now_utc):
        if self.is_monitored:
            return 1
        if self.is_ongoing(now_utc):
            if self.t_type != Type.Study or len(self.messages) > 5:
                return 1
            delta_min = deltaseconds(now_utc, self.startsAt) // 60
            return max(2, delta_min // 15)
        finishes_at = self.finish_time_estimated()
        if finishes_at is not None and now_utc >= finishes_at:
            delta_min = deltaseconds(now_utc, finishes_at) // 60
            return max(2, delta_min // 30)
        if finishes_at is None and self.finishesAt:
            delta_min = deltaseconds(now_utc, self.startsAt) // 60
            return max(2, -2 + delta_min // 30)
        delta_min = deltaseconds(self.startsAt, now_utc) // 60
        return max(2, (delta_min - len(self.messages)) // 10)

    def get_type(self):
        return "tournament" if self.t_type == Type.Arena else "swiss" if self.t_type == Type.Swiss else None

    def download(self, msg_lock, now_utc):
        new_messages = []
        deleted_messages = []
        if self.errors:
            return new_messages, deleted_messages
        try:
            ua = UserAgent()
            headers = {'User-Agent': str(ua.chrome)}
            #if not self.is_arena:
            #   headers['Authorization'] = f"Bearer {get_token()}"  # otherwise it doesn't load messages
            url = self.link if self.link else f"https://lichess.org/{self.get_type()}/{self.id}"
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                raise Exception(f"Failed to download {url}<br>Status Code {r.status_code}")
            with msg_lock:
                new_messages, deleted_messages = self.process_messages(r.text, now_utc)
            #self.process_usernames(r.text)  # doesn't work with token
            self.last_update = now_utc
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(str(exception))
        except:
            self.errors.append("ERROR")
        self.re_usernames = []  # TODO: initialize with user names of tournament players (fetch once?)
        for user in self.user_names:
            re_user = r"(https?:\/\/)?(lichess\.org\/)?@?\/?" + user
            self.re_usernames.append(ReUser(re_user, 0, info=user, class_name="text-muted"))
        return new_messages, deleted_messages

    def process_messages(self, text, now_utc):
        new_messages = []
        deleted_messages = []
        i1 = text.find(CHAT_BEGINNING_MESSAGES_TEXT)
        if i1 < 0:
            return new_messages, deleted_messages
        i1 = i1 + len(CHAT_BEGINNING_MESSAGES_TEXT) - 1
        i2 = text.find(CHAT_END_MESSAGES_TEXT, i1)
        if i2 < 0:
            raise Exception("ERROR /tournament messages: No ']'")
        if len(self.messages) > CHAT_MAX_NUM_MSGS:
            i_cut = len(self.messages) - CHAT_MAX_NUM_MSGS
            deleted_messages = self.messages[:i_cut]
            self.messages = self.messages[i_cut:]
        text_json = text[i1:i2 + 1]
        data = json.loads(text_json)
        do_detect_deleted = (len(data) < CHAT_NUM_VISIBLE_MSGS)
        i_msg = 0
        can_be_old = True
        is_new = True
        for d in data:
            msg = Message(d, self.id, now_utc)
            if can_be_old:
                is_new = True
                for i in range(i_msg, len(self.messages)):
                    if msg == self.messages[i]:
                        i_msg = i + 1
                        is_new = False
                        self.messages[i].update(msg)
                        if do_detect_deleted:
                            for j in range(max(0, i - 1 - CHAT_NUM_VISIBLE_MSGS + len(data)), i - 1):
                                self.messages[j].is_deleted = True
                            do_detect_deleted = False
                        break
            if is_new:
                msg.id = Message.global_id
                Message.global_id += 1
                self.messages.append(msg)
                new_messages.append(msg)
                if not msg.is_official:
                    self.user_names.add(msg.username)
                can_be_old = False
        return new_messages, deleted_messages

    def process_usernames(self, text):
        i1 = text.find(TOURNEY_STANDING_BEGINNING_TEXT)
        if i1 < 0:
            return
        i1 = i1 + len(TOURNEY_STANDING_BEGINNING_TEXT) - 1
        i2 = text.find(TOURNEY_STANDING_ENDING_TEXT, i1)
        if i2 < 0:
            raise Exception("ERROR /tournament standing: No ']'")
        text_json = text[i1:i2 + 1]
        data = json.loads(text_json)
        for d in data:
            self.user_names.add(d['name'])

    def analyse(self):
        self.max_score = 0
        self.total_score = 0
        to_timeout = {}
        for msg in self.messages:
            if msg.score is None:
                msg.evaluate(self.re_usernames)
            is_msg_visible = not msg.is_reset and not msg.is_deleted and not msg.is_removed \
                             and not msg.is_disabled and not msg.is_official  # if not msg.is_hidden(): # w/o is_timed_out
            if is_msg_visible:
                if msg.score > self.max_score:
                    self.max_score = msg.score
                self.total_score += msg.score
                if not msg.is_hidden():
                    if msg.best_ban_reason() != Reason.No:
                        add_timeout_msg(to_timeout, msg)
        return to_timeout

    def get_link(self, short=True):
        name = shorten(self.name, MAX_LEN_TOURNEY_NAME_SHORT if short else MAX_LEN_TOURNEY_NAME_LONG)
        link = self.link if self.link else f'https://lichess.org/{self.get_type()}/{self.id}'
        tournament = f'<a href="{link}" target="_blank">{name}</a>'
        return tournament

    def get_status(self, now_utc):
        if now_utc < self.startsAt:
            return f'<abbr title="Starts in {deltaperiod(self.startsAt, now_utc)}" class="text-info">Created</abbr>'
        if self.t_type == Type.Arena and now_utc < self.finishesAt:
            return f'<abbr title="Finishes in {deltaperiod(self.finishesAt, now_utc)}" class="text-success">Started</abbr>'
        if self.t_type != Type.Arena and not self.finishesAt:
            return f'<abbr title="Started {deltaperiod(now_utc, self.startsAt)} ago" class="text-success">Started</abbr>'
        if self.t_type == Type.Arena:
            return f'<abbr title="Finished {deltaperiod(now_utc, self.finishesAt)} ago" class="text-muted">Finished</abbr>'
        return f'<abbr title="Started {deltaperiod(now_utc, self.startsAt)} ago" class="text-muted">Finished</abbr>'

    def get_info(self, now_utc):
        msgs = [msg.get_info('A', add_mscore=True) for msg in self.messages if msg.score and not msg.is_hidden()]
        if not msgs and not self.errors:
            return ""
        header = f'<div class="d-flex user-select-none justify-content-between px-1 mb-1" ' \
                 f'style="background-color:rgba(128,128,128,0.2);">' \
                 f'{self.get_link(short=False)}{self.get_status(now_utc)}</div>'
        errors = f'<div class="text-warning px-1"><div>{"</div><div>".join(self.errors)}</div></div>' if self.errors else ""
        return f'<div class="col rounded m-1 px-0" style="background-color:rgba(128,128,128,0.2);min-width:350px">' \
               f'{header}{errors}{"".join(msgs)}</div>'

    def get_frequent_data(self, now_utc, reset_multi_messages):
        if not self.messages:
            return [], [], {}
        output = []
        multi_messages = {}
        user_msgs = {}
        to_timeout = {}
        first_msg_time = self.messages[0].time  # time of the first message in the tournament

        def process_user(user_name):
            nonlocal output, multi_messages, user_msgs, to_timeout, first_msg_time
            msgs = user_msgs[user_name]
            num_not_reset_messages = len([um for um in msgs if um is not None and not um.is_reset])
            if num_not_reset_messages <= 1:
                return
            # Detect messages with unknown time (received at startup)
            i = 0
            num_first_messages = 0
            for um in msgs:
                if um is not None:
                    if deltaseconds(um.time, first_msg_time) >= max(1.0, API_TOURNEY_PAGE_DELAY):
                        break
                    num_first_messages += 1
                i += 1
            if i > 0 and num_first_messages < NUM_FREQUENT_MESSAGES:
                msgs = msgs[i:]
                j = 0
                for um in msgs:
                    if um is not None:
                        break
                    j += 1
                if j > 0:
                    msgs = msgs[j:]
            real_msgs = [um for um in msgs if um is not None]
            if not real_msgs:
                return
            num_msgs = len(real_msgs)
            if num_msgs < NUM_FREQUENT_MESSAGES and deltaseconds(now_utc, self.last_update) > MAX_TIME_FREQUENT_MESSAGES:
                return
            # Process messages
            msgs_id = real_msgs[-1].id
            if num_msgs <= 1 or msgs_id in reset_multi_messages:
                return
            # Check how short the messages are and how many
            score_int = max(0, (num_msgs - 3) * 5) if num_msgs <= 8 else num_msgs * 5
            if len(real_msgs) >= 3:
                lengths = [len(um.text) for um in real_msgs]
                mean_len = (sum(lengths) - max(lengths)) / (len(lengths) - 1)
                len_real_msgs = len(real_msgs) if self.t_type == Type.Study else (2 * len(real_msgs) - len(msgs))
                if len_real_msgs >= 8:
                    coef = 20 if mean_len < 3 else 15 if mean_len < 4 else 10 if mean_len < 5 else 5 if mean_len < 6 \
                              else 2 if mean_len < 10 else 1.5 if mean_len < 15 else 1
                elif len_real_msgs >= 5:
                    coef = 5 if mean_len < 3 else 4 if mean_len < 4 else 2 if mean_len < 5 else 1.5 if mean_len < 10 else 1
                else:
                    coef = 1
                score_int = int(score_int * coef)
            combined_text = " ".join([m.text for m in real_msgs])
            combined_msg = Message({'u': user_name, 't': combined_text}, real_msgs[-1].tournament, real_msgs[-1].time)
            max_score = max([(0 if m.score is None else m.score) for m in real_msgs])
            combined_msg.evaluate(self.re_usernames)
            best_ban_reason = combined_msg.best_ban_reason()
            if best_ban_reason != Reason.No or score_int > MULTI_MSG_MIN_TIMEOUT_SCORE:
                str_tag = "spam"
                combined_msg.text = f'[multi-line {str_tag}] {" | ".join([m.text for m in real_msgs])}'
                if score_int > MULTI_MSG_MIN_TIMEOUT_SCORE:
                    combined_msg.reasons[Reason.Spam] = score_int / MULTI_MSG_MIN_TIMEOUT_SCORE
                    combined_msg.score = score_int
                else:
                    sum_len = sum([len(m.text) for m in real_msgs]) + len(real_msgs) - 1
                    if sum_len > MAX_LEN_TEXT:
                        enumerated_msgs = [(i, m) for i, m in enumerate(real_msgs)]
                        enumerated_msgs.sort(key=lambda im: im[1].score * 999 - len(im[1].text), reverse=True)
                        reported_msgs = [False] * len(real_msgs)
                        total_len = 0
                        last_msg = ""
                        for i, um in enumerated_msgs:
                            total_len += len(um.text)
                            if total_len > MAX_LEN_TEXT and total_len != len(um.text):
                                last_msg = um.text
                                break
                            reported_msgs[i] = True
                            total_len += 1  # whitespace
                        combined_msg.text = f'[multi-line {str_tag}] ' \
                                            f'{" | ".join([m.text for i, m in enumerate(real_msgs) if reported_msgs[i]])}'
                        if last_msg:
                            combined_msg.text = f"{combined_msg.text} | {last_msg}"  # add to the end to further shorten it
                add_timeout_msg(to_timeout, combined_msg)
                if DO_AUTO_TIMEOUTS:
                    return
            # Add scores
            best_reason = best_ban_reason if best_ban_reason != Reason.No else combined_msg.best_score_reason()
            final_score = f'<abbr title="{num_msgs} messages in a row or in a short period of time">{score_int}</abbr>'
            if combined_msg.score > max_score:
                prev = final_score if score_int > 0 else ""
                if best_reason != Reason.No:
                    final_score = f'{prev}+<abbr title="{Reason.to_text(best_reason)}">{combined_msg.score}</abbr>'
                else:
                    final_score = f'{prev}+{combined_msg.score}'
                score_int += combined_msg.score
            if score_int < CHAT_FREQUENT_MSGS_MIN_SCORE and num_msgs < 5:
                return
            tag = 'B'
            score_theme = ' class="text-danger"' if score_int > 50 else ' class="text-warning"' if score_int > 10 else ""
            score = f'<span{score_theme}>{final_score}</span>'
            user = f'<a class="text-info" href="https://lichess.org/@/{user_name.lower()}" target="_blank">{user_name}</a>'
            button_dismiss = f'<button class="btn btn-primary align-baseline flex-grow-0 px-1 py-0" ' \
                             f'onclick="set_multi_ok(\'{tag}{msgs_id}\')">Dismiss</button>'
            if best_reason == Reason.No:
                best_reason = int(Reason.Spam)
            r = Reason.to_Tag(best_reason)
            class_ban = "btn-warning" if combined_msg.score >= 50 else "btn-success"
            button_ban = f'<button class="btn {class_ban} nav-item dropdown-toggle align-baseline mr-1 px-1 py-0" ' \
                         f'data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="cursor:pointer;">' \
                         f'Ban</button><span class="dropdown-menu" style="">' \
                         f'<button class="dropdown-item btn-primary" onclick="timeout_multi(\'{tag}{msgs_id}\', 1);">' \
                         f'{combined_msg.format_reason(Reason.Shaming, "Public Shaming", Reason.Spam, best_reason)}</button>' \
                         f'<button class="dropdown-item btn-primary" onclick="timeout_multi(\'{tag}{msgs_id}\', 2);">' \
                         f'{combined_msg.format_reason(Reason.Offensive, "Offensive Language", Reason.Spam, best_reason)}</button>' \
                         f'<button class="dropdown-item btn-primary" onclick="timeout_multi(\'{tag}{msgs_id}\', 3);">' \
                         f'{combined_msg.format_reason(Reason.Spam, "Spamming", Reason.Spam, best_reason)}</button>' \
                         f'<button class="dropdown-item btn-primary" onclick="timeout_multi(\'{tag}{msgs_id}\', 4);">' \
                         f'{combined_msg.format_reason(Reason.Other, "Inappropriate Behaviour", Reason.Spam, best_reason)}</button>' \
                         f'</span>'
            if best_ban_reason != Reason.No or combined_msg.score >= 50:
                button_ban = f'<button class="btn btn-danger align-baseline flex-grow-0 py-0 px-1" ' \
                             f'onclick="timeout_multi(\'{tag}{msgs_id}\');">{r}</button>{button_ban}'
            header_1 = f'<div class="d-flex justify-content-between">{self.get_link()}' \
                       f'<span class="ml-1">{self.get_status(now_utc)}</span></div>'
            header_2 = f'<div class="d-flex justify-content-between mb-1"><span>{button_ban}{user}</span>' \
                       f'<span class="align-items-baseline ml-1">{score} {button_dismiss}</span></div>'
            header = f'<div class="user-select-none px-1" style="background-color:rgba(128,128,128,0.2);">' \
                     f'{header_1}{header_2}</div>'
            msgs_info = [HR if m is None else m.get_info(tag, show_hidden=True, add_user=False, rename_dismiss="Exclude",
                                                         add_reason=Reason.Spam) for m in msgs]
            info = f'<div id="mmsg{tag}{msgs_id}" data-mscore={score_int} class="col rounded m-1 px-0 pb-1" ' \
                   f'style="background-color:rgba(128,128,128,0.2);min-width:350px;">{header}{"".join(msgs_info)}</div>'
            output.append((score_int, info))
            multi_messages[msgs_id] = [m for m in real_msgs]

        def get_last_time(user_name):
            for um in reversed(user_msgs[user_name]):
                if um is not None:
                    return um.time
            return first_msg_time - timedelta(seconds=TIME_FREQUENT_MESSAGES + 999)

        last_user = ""
        for msg in self.messages:
            if msg.is_removed or msg.is_official:
                continue
            is_to_be_processed = not msg.is_deleted and not msg.is_disabled and not msg.is_timed_out
            is_among_first_messages = deltaseconds(msg.time, first_msg_time) < max(1.0, API_TOURNEY_PAGE_DELAY)
            keys = list(user_msgs.keys())
            for username in keys:
                if not is_to_be_processed or username != last_user:
                    if not is_among_first_messages \
                            and deltaseconds(msg.time, get_last_time(username)) < TIME_FREQUENT_MESSAGES:
                        if user_msgs[username][-1] is not None:
                            user_msgs[username].append(None)
                    else:
                        process_user(username)
                        del user_msgs[username]
            if is_to_be_processed:
                if msg.username in user_msgs:
                    user_msgs[msg.username].append(msg)
                else:
                    user_msgs[msg.username] = [msg]
                last_user = msg.username
            else:
                last_user = ""
        for username in user_msgs.keys():
            process_user(username)
        return output, multi_messages, to_timeout

    def get_list_item(self, now_utc):
        checked = ' checked=""' if (self.t_type != Type.Swiss or CHAT_UPDATE_SWISS) and self.is_active(now_utc) else ""
        disabled = "" if self.t_type != Type.Swiss or CHAT_UPDATE_SWISS else ' disabled'
        if now_utc < self.startsAt:
            info = f'{deltaperiod(self.startsAt, now_utc, short=True)}'
        elif self.t_type == Type.Arena and now_utc < self.finishesAt:
            info = f'{deltaperiod(self.finishesAt, now_utc, short=True)}'
        elif self.t_type == Type.Arena:
            info = f'{deltaperiod(now_utc, self.finishesAt, short=True)}'
        else:
            info = f'started {deltaperiod(now_utc, self.startsAt, short=True)} ago'
        num_messages = f'{len(self.messages):03d}' if self.t_type != Type.Swiss or CHAT_UPDATE_SWISS \
                       else "&minus;&minus;&minus;"
        if len(self.messages) > 0:
            tag = 'T'
            i = max(0, len(self.messages) - NUM_MSGS_BEFORE)
            num_messages = f'<button class="brt btn-secondary align-baseline flex-grow-0 px-1 py-0"  ' \
                           f'onclick="select_message(event,\'{tag}{self.messages[i].id}\')">{num_messages}</button>'
        else:
            num_messages = f'<span class="px-1">{num_messages}</span>'
        text_class = " text-info" if self.is_monitored else ""
        return f"""<div class="form-check form-switch">
          <input class="form-check-input" type="checkbox" id="t_{self.id}" onchange="set_tournament('{self.id}')"
          {checked}{disabled}>
          <label class="form-check-label d-flex justify-content-between{text_class}" for="t_{self.id}">
          <span>{num_messages} {self.get_link()}</span><span>{info}</span></label>
        </div>"""


class ChatAnalysis:
    def __init__(self):
        self.tournaments = {}
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
        self.cache_tournaments = {'state': 0}
        self.cache_reports = {'state': 0}

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
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(str(exception))
        except:
            self.errors.append("ERROR")
        self.state_tournaments += 1
        self.is_processing = False

    def run(self):
        if self.is_processing or self.errors or self.i_update_frequency == IDX_NO_PAGE_UPDATE:
            return
        self.is_processing = True
        self.wait_refresh()
        try:
            now_utc = datetime.now(tz=tz.tzutc())
            keys = list(self.tournaments.keys())  # needed as self.tournaments may be changed from add_tournament()
            for tourn_id in keys:
                tourn = self.tournaments[tourn_id]
                if not tourn.is_enabled:
                    continue
                if tourn.t_type == Type.Swiss and not CHAT_UPDATE_SWISS:
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
            self.errors.append(str(exception))
        except:
            self.errors.append("ERROR")
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
                    chan = "tournament" if self.tournaments[msg.tournament].t_type == Type.Arena \
                        else "swiss" if self.tournaments[msg.tournament].t_type == Type.Swiss \
                        else "study" if self.tournaments[msg.tournament].t_type == Type.Study \
                        else None
                    log(f"[reset] {reason_tag.upper()} score: {msg.score} "
                        f"user: {msg.username} roomId: {msg.tournament} chan: {chan} text: {msg.text}")
                self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(str(exception))

    def set_multi_msg_ok(self, msg_id):
        try:
            msg_id = int(msg_id[1:])
            self.reset_multi_messages.add(msg_id)
            if msg_id in self.multi_messages:
                del self.multi_messages[msg_id]
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(str(exception))

    def api_timeout(self, msg, reason, is_timeout_manual):
        reason_tag = Reason.to_tag(reason)
        if reason_tag is None:
            self.errors.append("Error timeout: Unknown reason")
            return
        if msg.tournament not in self.tournaments:
            self.errors.append(f"Error timeout: Tournament {msg.tournament} deleted")
            return
        chan = "tournament" if self.tournaments[msg.tournament].t_type == Type.Arena \
            else "swiss" if self.tournaments[msg.tournament].t_type == Type.Swiss \
            else "study" if self.tournaments[msg.tournament].t_type == Type.Study \
            else None
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = "https://lichess.org/mod/public-chat/timeout"
        text = f'{msg.text[:MAX_LEN_TEXT-1]}…' if len(msg.text) > MAX_LEN_TEXT else msg.text
        data = {'reason': reason_tag,
                'userId': msg.username.lower(),
                'roomId': msg.tournament,
                'chan': chan,
                'text': text}
        if is_timeout_manual or DO_AUTO_TIMEOUTS:
            r = requests.post(url, headers=headers, json=data)
            timeout_tag = ('[MANUAL] ' if is_timeout_manual else '[AUTO] ') if DO_AUTO_TIMEOUTS else ""
            if len(msg.text) > MAX_LEN_TEXT:
                text = f'{text}{msg.text[MAX_LEN_TEXT-1:]}'
            if r.status_code == 200 and r.text == "ok":
                log(f"{timeout_tag}{reason_tag.upper()} score: {msg.score} user: {msg.username} "
                    f"roomId: {msg.tournament} chan: {chan} text: {text}", True)
                start_time = msg.time - timedelta(minutes=TIMEOUT_RANGE[0])
                end_time = msg.time + timedelta(minutes=TIMEOUT_RANGE[1])
                for m in self.all_messages.values():
                    if m.username == msg.username and start_time < m.time < end_time:
                        m.is_timed_out = True
                        m.is_reset = False
            else:
                status_info = "invalid token?" if r.status_code == 200 else f"status: {r.status_code}"
                self.errors.append(f"Timeout error ({status_info}):<br>{timeout_tag}{reason_tag.upper()} "
                                   f"<u>Score</u>: {msg.score} <u>User</u>: {msg.username} "
                                   f"<u>RoomId</u>: {msg.tournament} <u>Channel</u>: {chan} <u>Text</u>: {text}")
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
            self.errors.append(str(exception))

    def timeout_multi(self, mmsg_id, reason):
        try:
            with self.msg_lock:
                msg_id = int(mmsg_id[1:])
                msgs = self.multi_messages.get(msg_id)
                if msgs is not None:
                    reason = int(reason)
                    if reason == 0:
                        reason = Reason.Spam  # msg.best_reason()
                    str_tag = "spam"
                    combined_text = f'[multi-line {str_tag}] {" | ".join([m.text for m in msgs if not m.is_reset])}'
                    combined_msg = Message({'u': msgs[0].username, 't': combined_text}, msgs[0].tournament, msgs[0].time)
                    combined_msg.evaluate(self.tournaments[self.tournament_messages[msg_id]].re_usernames)
                    self.api_timeout(combined_msg, reason, True)
                    self.state_reports += 1
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.errors.append(str(exception))

    def set_update(self, i_update_frequency):
        if i_update_frequency is None:
            return
        try:
            self.i_update_frequency = max(0, min(len(API_CHAT_REFRESH_PERIOD), int(i_update_frequency)))
        except:
            return

    def select_message(self, msg_id):
        try:
            if msg_id == "--":
                self.selected_msg_id = None
                return ""
            self.selected_msg_id = int(msg_id[1:])
            return self.get_messages_nearby(self.selected_msg_id)
        except Exception as exception:
            self.selected_msg_id = None
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return f'<p class="text-danger">Error: {exception}</p>'
        except:
            self.selected_msg_id = None
            return f'<p class="text-danger">Error: get_messages_near()</p>'

    def get_messages_nearby(self, msg_id):
        try:
            if msg_id is None:
                return ""
            with self.msg_lock:
                tourn_id = self.tournament_messages.get(msg_id)
                i: int = None
                if tourn_id in self.tournaments:
                    for j, msg in enumerate(self.tournaments[tourn_id].messages):
                        if msg.id == msg_id:
                            i = j
                            break
                if i is None:
                    return f'<p class="text-warning">Warning: Message has been removed</p>'
                i_start = max(0, i - NUM_MSGS_BEFORE)
                n_rest = max(0, NUM_MSGS_BEFORE - i + i_start)
                i_end = min(len(self.tournaments[tourn_id].messages), i + NUM_MSGS_AFTER + n_rest)
                n_rest = max(0, NUM_MSGS_AFTER - i_end + i)
                i_start = max(0, i_start - n_rest)
                msg_i = self.tournaments[tourn_id].messages[i]
                msgs_before = [self.tournaments[tourn_id].messages[j].get_info('C',
                               base_time=msg_i.time, highlight_user=msg_i.username) for j in range(i_start, i)]
                msgs_after = [self.tournaments[tourn_id].messages[j].get_info('C',
                              base_time=msg_i.time, highlight_user=msg_i.username) for j in range(i + 1, i_end)]
                list_start = '<hr class="text-primary my-1" style="border:1px solid;">' if i_start == 0 else ""
                list_end = '<hr class="text-primary mt-1 mb-0" style="border:1px solid;">'\
                           if i_end == len(self.tournaments[tourn_id].messages) else ""
                msg = msg_i.get_info('C', show_hidden=True, highlight_user=True, allow_selection=False)
            header = f'<div class="d-flex user-select-none justify-content-between px-1 py-1" ' \
                     f'style="background-color:rgba(128,128,128,0.2);">' \
                     f'<span><b>Messages</b> in {self.tournaments[tourn_id].get_link(short=False)}:</span>' \
                     f'<button class="btn btn-primary align-baseline flex-grow-0 py-0" ' \
                     f'onclick="select_message(event,\'--\')">Close</button></div>'
            return f'{header}{list_start}{"".join(msgs_before)}' \
                   f'<div class="border border-success rounded" style="{get_highlight_style(0.3)}">{msg}</div>' \
                   f'{"".join(msgs_after)}{list_end}'
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            return f'<p class="text-danger">Error: {exception}</p>'
        except:
            return f'<p class="text-danger">Error: get_messages_near()</p>'

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
            # arena_tournament_page = "https://lichess.org/tournament/"
            # swiss_tournament_page = "https://lichess.org/siwss/"
            # if page.startswith(arena_tournament_page):
            #     tourn_id = page[len(arena_tournament_page):]
            # elif page.startswith(swiss_tournament_page):
            #     tourn_id = page[len(swiss_tournament_page):]
            i = page.rfind('/')
            if 0 < i < len(page):
                tourn_id = page[i + 1:]
                if tourn_id in self.tournaments:
                    self.tournaments[tourn_id].is_monitored = True
                else:
                    j = page[0:i].rfind('/')
                    name = page[j + 1:i] if j > len(str_lichess) and i > j + 1 else tourn_id
                    data = {'id': tourn_id,
                            'createdBy': "lichess",
                            'nbPlayers': 0,
                            'startsAt': datetime.now(tz=tz.tzutc()),
                            'name': name,
                            'status': "started"
                            }
                    self.tournaments[tourn_id] = Tournament(data, Type.Study, link=page, is_monitored=True)
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
            if self.state_reports == self.cache_reports['state']:
                return self.cache_reports
            # Main content
            now_utc = datetime.now(tz=tz.tzutc())
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
            info_selected = self.get_messages_nearby(self.selected_msg_id)
            str_time = f"{now_utc:%H:%M}"
            self.cache_reports = {'reports': info, 'multiline-reports': info_frequent, 'selected-messages': info_selected,
                                  'time': str_time, 'state': self.state_reports}
            return self.cache_reports

    def get_tournaments(self, active_tournaments=None):
        with self.tournaments_lock:
            if self.state_tournaments == self.cache_tournaments['state']:
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
            self.cache_tournaments['state'] = self.state_tournaments
            return self.cache_tournaments


def get_current_tournaments():
    # Arena
    headers = {}  # {'Authorization': f"Bearer {get_token()}"}
    url = "https://lichess.org/api/tournament"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"ERROR /api/tournament: Status Code {r.status_code}")
    data = r.json()
    arenas = [*data['created'], *data['started'], *data['finished']]
    tournaments = []
    now_utc = datetime.now(tz=tz.tzutc())
    for arena in arenas:
        tourn = Tournament(arena, Type.Arena)
        if tourn.is_active(now_utc):
            tournaments.append(tourn)
    # Swiss
    url = "https://lichess.org/api/team/lichess-swiss/swiss"
    swiss_data = get_ndjson(url, Accept="application/nd-json")
    for swiss in swiss_data:
        try:
            i = swiss['startsAt'].rfind('.')
            if i < 0:
                print(f"Error swiss: {swiss}")
                continue
            swiss['startsAt'] = datetime.strptime(swiss['startsAt'][:i], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=tz.tzutc())
            tourn = Tournament(swiss, Type.Swiss)
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
                r['startsAt'] = datetime.fromtimestamp(r['startsAt'] // 1000, tz=tz.tzutc())
                r['name'] = f"{r['name']} | {broadcast_name}"
                r['status'] = "finished" if r.get('finished') else "unknown"
                tourn = Tournament(r, Type.Study, r['url'])
                if tourn.is_active(now_utc):
                    tournaments.append(tourn)
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
    return tournaments