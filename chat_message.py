import os
import html
from datetime import datetime, timedelta
from enum import IntFlag
from elements import STYLE_WORD_BREAK
from chat_re import list_res, list_res_variety, re_spaces, Lang
from database import Messages
from elements import Reason, deltaseconds, get_user_comm_href, get_highlight_style, get_flair_element, log, log_exception


class AddButtons(IntFlag):
    No = 0
    Ban = 1
    Dismiss = 2
    BanAndDismiss = 3


def load_res():
    timeouts = os.getenv('TIMEOUTS', "Spam En Ru De Hi Es It Fr Tr").lower()
    list_re = []
    list_re_variety = []
    for lang in Lang:
        if lang.name.lower() in timeouts:
            for re in list_res[lang]:
                re.lang = lang
            list_re.extend(list_res[lang])
    for lang in Lang:
        if (lang.name.lower() in timeouts) and (lang in list_res_variety):
            for re in list_res_variety[lang]:
                re.lang = lang
            list_re_variety.extend(list_res_variety[lang])
    return list_re, list_re_variety


class Message:
    global_id = 1  # starting from 1
    list_res, list_res_variety = load_res()

    @staticmethod
    def is_id_multi(id):
        return id is not None and id < 0

    def __init__(self, data, tournament, time=None, delay=None, db_id=None, is_timed_out=False):
        self.id: int = None
        self.db_id = db_id
        self.time: datetime = time
        self.delay: int = delay
        self.username = data['u']
        self.text = data['t']
        self.eval_text = ""
        self.is_official = (self.username == "lichess")
        self.is_deleted = False  # was available before and now isn't on the page
        self.is_removed = data.get('r', False)  # SB'ed, was never visible
        self.is_disabled = data.get('d', False)  # deleted by mods
        self.is_reset = False  # processed as good
        self.is_timed_out = is_timed_out  # processed as bad
        self.tournament = tournament
        self.score: int = None
        self.reasons = [0] * Reason.Size
        self.scores = [0] * Reason.Size
        self.languages = Lang.No

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
        if self.is_removed == msg.is_removed and self.is_disabled == msg.is_disabled:
            return
        self.is_removed = msg.is_removed
        self.is_disabled = msg.is_disabled
        msg_db = Messages.get_or_none(id=self.db_id)
        if msg_db:
            msg_db.removed = self.is_removed
            msg_db.disabled = self.is_disabled
            msg_db.save()

    def set_timed_out(self, flag=True):
        if self.is_timed_out == flag:
            return
        self.is_timed_out = flag
        msg_db = Messages.get_or_none(id=self.db_id)
        if msg_db:
            msg_db.timeout = self.is_timed_out
            msg_db.save()

    def __eq__(self, other):
        return self.username.lower() == other.username.lower() and self.text == other.text \
               and self.tournament.id == other.tournament.id

    def __repr__(self):
        return f"[{self.username}]: {self.text}"

    def dont_evaluate(self):
        self.eval_text = html.escape(self.text)
        self.score = 0

    def evaluate(self, re_usernames):
        if self.is_official:
            self.dont_evaluate()
            return
        try:
            # Remove multiple spaces
            text = re_spaces.sub(" ", self.text)
            # Add usernames and evaluate
            res_all = re_usernames.copy()
            res_all.extend([re_i for re_i in Message.list_res
                            if (re_i.exclude_tournaments is None or self.tournament.t_type not in re_i.exclude_tournaments)])
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
            self.languages = result.languages
            if self.score >= 50:
                self.eval_text.replace('<span class="text-warning"', '<span class="text-danger"')
                if self.score > 60:
                    self.eval_text.replace('<span class="text-warning"', '<span class="text-danger bg-warning"')
        except Exception as exception:
            log(f"ERROR when processing: {self}", to_print=True, to_save=True)
            log_exception(exception)
            self.eval_text = html.escape(self.text)
            self.score = 0

    def is_hidden(self):
        return self.is_removed or self.is_disabled or \
               self.is_reset or self.is_timed_out or self.is_official  # or self.is_deleted

    def is_banable(self):
        if self.best_ban_reason() != Reason.No:
            return True
        return self.best_score_reason() != Reason.No and self.score and self.score >= 50

    def get_info(self, tag, show_hidden=None, add_buttons=None, base_time=None, rename_dismiss=None, add_user=True,
                 add_mscore=False, add_reason=None, highlight_user=None, is_diff_highlight=False,
                 is_selected=False, is_centered=False, add_selection=False):
        if show_hidden is None:
            show_hidden = (base_time is not None)
        if self.is_official or self.is_disabled or self.is_removed or self.is_timed_out:
            add_buttons = AddButtons.No
        else:
            if add_buttons is None:
                add_buttons = AddButtons.BanAndDismiss if base_time is None else AddButtons.No
            if (self.score == 0 and not rename_dismiss) or self.is_reset:
                add_buttons &= ~AddButtons.Dismiss
        if not show_hidden and (self.is_hidden() or not self.score):
            return ""
        if base_time is None:
            str_time = ""
        else:
            ds = deltaseconds(self.time, base_time)
            dt = f"{abs(ds)}s" if abs(ds) < 60 \
                else f"{abs(ds) // 60}m{abs(ds) % 60:02d}s" if abs(ds) < 300 \
                else f"{int(round(abs(ds) / 60))}m"
            str_time = f"&minus;{dt} " if ds < 0 else f'+{dt} ' if ds > 0 else "== "
            time_tz = self.time.replace(tzinfo=None)
            time_interval = f"{time_tz:%H:%M:%S} or before" if self.delay is None \
                else f"{time_tz - timedelta(seconds=self.delay):%H:%M:%S}…{time_tz:%H:%M:%S}"
            str_time = f'<abbr title="{time_interval}" class="user-select-none" ' \
                       f'style="text-decoration:none;">{str_time}</abbr>'
            flair = self.tournament.user_flairs.get(self.username, "")
            if flair:
                str_time = f'{str_time}{get_flair_element(flair, 17)}'
        score_theme = "" if self.score is None else ' text-danger' if self.score > 50 \
            else ' text-warning' if self.score > 10 else ""
        score = f'<span class="user-select-none{score_theme}">{self.score}</span>' if self.score and self.score > 0 else ""
        username = f"<b><u>{self.username}</u></b>" if highlight_user is True or highlight_user == self.username \
            else self.username
        user = f'<a class="text-info user-select-none" href="{get_user_comm_href(self.username)}"' \
               f' target="_blank" onclick="prevent_click(event)">{username}</a>' if add_user else ""
        highlight_style = "" if not highlight_user or highlight_user != self.username \
            else get_highlight_style(0.2, is_diff_highlight)
        name_dismiss = rename_dismiss if rename_dismiss else "Dismiss"
        class_dismiss = "btn-secondary" if rename_dismiss else "btn-primary"
        button_dismiss = f'<button class="btn {class_dismiss} text-nowrap align-baseline flex-grow-0 py-0 px-1 ml-1" ' \
                         f'onclick="set_ok(\'{tag}{self.id}\');">{name_dismiss}</button> ' \
                         if add_buttons & AddButtons.Dismiss else ""
        best_ban_reason = self.best_ban_reason()
        best_reason = best_ban_reason if best_ban_reason != Reason.No else self.best_score_reason()
        if best_reason == Reason.No and add_reason is not None:
            best_reason = int(add_reason)
        class_ban = "btn-warning" if self.score and self.score >= 50 else "btn-secondary"
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
            if best_ban_reason != Reason.No or (best_reason != Reason.No and self.score and self.score >= 50):
                button_ban = f'<button class="btn btn-danger align-baseline flex-grow-0 py-0 px-1" ' \
                             f'onclick="timeout(\'{tag}{self.id}\');">{Reason.to_Tag(best_reason)}</button>{button_ban}'
        class_name = "text-muted" if self.is_deleted or self.is_reset or self.is_disabled or self.is_timed_out \
                     or self.is_official else "text-secondary" if self.is_removed else ""
        text = f'<s style="text-decoration-style:double;">{self.eval_text}</s>' if self.is_removed \
            else f'<s style="text-decoration-style:dotted;"><u style="text-decoration-style:wavy;">' \
                 f'{self.eval_text}</u></s>' if self.is_timed_out \
            else f'<s>{self.eval_text}</s>' if self.is_disabled \
            else f'<small>{self.eval_text}</small>' if self.is_reset \
            else f'<small><i>{self.eval_text}</i></small>' if self.is_official \
            else self.eval_text if self.is_deleted \
            else self.eval_text
        text = f'<span class="{class_name}" style="{STYLE_WORD_BREAK}">{text}</span>'
        mscore = f' data-mscore={self.score}' if add_mscore else ""
        langs = f' data-langs={self.languages}' if add_mscore else ""
        selection = html.escape(self.text).replace("'", "&apos;")
        selection = f' data-selection=\'{self.username}: "{selection}"\'' if add_selection else ""
        onclick = "" if is_selected else f' onclick="select_message(event,\'{tag}{self.id}\')"'
        selectee_class = "selectee selectee-center" if is_centered else "selectee"
        if add_buttons == AddButtons.No:
            div = f'<div id="msg{tag}{self.id}"{mscore}{langs}{selection} ' \
                  f'class="align-items-baseline {selectee_class} px-1" style="{STYLE_WORD_BREAK}"{onclick}>' \
                  f'{str_time}{user} <b>{score}</b> {text}</div>'
        elif add_buttons & AddButtons.Ban:
            div = f'<div id="msg{tag}{self.id}"{mscore}{langs}{selection} ' \
                  f'class="align-items-baseline {selectee_class} px-1" style="{STYLE_WORD_BREAK}"{onclick}>' \
                  f'<div class="d-flex justify-content-between"><span>{button_ban}{str_time}{user} {text}</span> ' \
                  f'<span class="text-nowrap"><b class="pl-2">{score}</b>{button_dismiss}</span></div></div>'
        else:
            div = f'<div id="msg{tag}{self.id}"{mscore}{langs}{selection} class="align-items-baseline {selectee_class} ' \
                  f'px-1" {onclick}>' \
                  f'<div class="d-flex justify-content-between">' \
                  f'<span class="d-flex flex-row">{button_ban}{str_time}{user}</span>' \
                  f'<span class="d-flex flex-row">{score}{button_dismiss}</span></div>' \
                  f'<div class="align-items-baseline" style="{STYLE_WORD_BREAK}">{text}</div></div>'
        return f'<div style="{highlight_style}">{div}</div>' if highlight_style else div
