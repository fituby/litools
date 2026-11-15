import os
from datetime import datetime, timezone
from enum import IntFlag
from chat_re import list_res, list_res_variety, re_spaces, Lang
from database import Messages
from elements import Reason, log, log_exception


class MsgFlag(IntFlag):
    Removed = 1
    Disabled = 2
    Reset = 4
    TimedOut = 8
    Official = 16
    Deleted = 32


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
        self.segments = []
        self.is_official = (self.username in ["lichess", "Lichess"])
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
        self.segments = [self.text]
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
            self.segments = result.element
            self.scores = result.scores
            self.score = result.total_score()
            self.reasons = result.ban_points
            self.languages = result.languages
        except Exception as exception:
            log(f"ERROR when processing: {self}", to_print=True, to_save=True)
            log_exception(exception)
            self.segments = [self.text]
            self.score = 0

    def is_hidden(self):
        return self.is_removed or self.is_disabled or \
               self.is_reset or self.is_timed_out or self.is_official  # or self.is_deleted

    def is_banable(self):
        if self.best_ban_reason() != Reason.No:
            return True
        return self.best_score_reason() != Reason.No and self.score and self.score >= 50

    def to_data(self):
        """Message data for the chat page, which renders it (see chat.html)."""
        data = {'id': self.id, 'u': self.username, 't': self.segments}
        if self.score:
            data['s'] = self.score
        flags = sum(flag for flag, is_set in [(MsgFlag.Removed, self.is_removed), (MsgFlag.Disabled, self.is_disabled),
                                              (MsgFlag.Reset, self.is_reset), (MsgFlag.TimedOut, self.is_timed_out),
                                              (MsgFlag.Official, self.is_official), (MsgFlag.Deleted, self.is_deleted)]
                    if is_set)
        if flags:
            data['f'] = flags
        if self.languages:
            data['l'] = int(self.languages)
        best_ban_reason = self.best_ban_reason()
        if best_ban_reason != Reason.No:
            data['rb'] = best_ban_reason
        best_score_reason = self.best_score_reason()
        if best_score_reason != Reason.No:
            data['rs'] = best_score_reason
        reasons_mask = sum(1 << i for i in range(Reason.Size) if self.scores[i])
        if reasons_mask:
            data['rm'] = reasons_mask
        if self.time is not None:
            time_utc = self.time if self.time.tzinfo else self.time.replace(tzinfo=timezone.utc)
            data['tm'] = int(round(time_utc.timestamp() * 1000))
        if self.delay is not None:
            data['d'] = self.delay
        flair = self.tournament.user_flairs.get(self.username) if self.tournament else None
        if flair:
            data['fl'] = flair
        return data
