from datetime import datetime, timedelta
from dateutil import tz
import json
from elements import Reason, TournType, deltaseconds, delta_s, deltaperiod, shorten, add_timeout_msg, Error500
from elements import log, log_exception
from chat_re import ReUser, Lang
from chat_message import Message
from api import ApiType
from consts import *


class Tournament:
    def __init__(self, tourney, t_type, link="", is_monitored=False):
        self.t_type = t_type
        self.id = tourney['id']
        self.is_official = (tourney['createdBy'] == "lichess")
        self.num_players = tourney['nbPlayers']
        startsAt = tourney.get('startsAt')
        if startsAt is None:
            self.startsAt = datetime.now(tz=tz.tzutc())
        elif isinstance(startsAt, str):
            i = startsAt.rfind('.')
            if i < 0:
                log(f"Error Tournament 'startsAt' {t_type}={self.id}: {tourney}", to_print=True, to_save=True)
                self.startsAt = datetime.now(tz=tz.tzutc())
            else:
                self.startsAt = datetime.strptime(startsAt[:i], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=tz.tzutc())
        else:
            self.startsAt = datetime.fromtimestamp(startsAt // 1000, tz=tz.tzutc())
        if t_type == TournType.Arena:
            self.name = tourney['fullName'].rstrip('Arena').strip()
            finishesAt = tourney.get('finishesAt')
            if finishesAt:
                self.finishesAt = datetime.fromtimestamp(finishesAt // 1000, tz=tz.tzutc())
            else:
                self.finishesAt = self.startsAt + timedelta(minutes=tourney['minutes'])
        else:
            self.name = f"Swiss {tourney['name']}" if t_type == TournType.Swiss else tourney['name']
            self.finishesAt = (tourney['status'] == 'finished')
        self.messages = []
        self.user_names = set()
        self.re_usernames = []
        self.errors = []
        self.errors_500 = []
        self.last_error_404: datetime = None
        self.max_score = 0
        self.total_score = 0
        self.is_monitored = is_monitored
        self.is_enabled = True
        self.link = link
        self.last_update: datetime = None
        self.is_just_added = False
        self.reports = ""
        self.multiline_reports = ""

    def update(self, tourn):
        self.startsAt = tourn.startsAt
        self.finishesAt = tourn.finishesAt
        self.num_players = tourn.num_players

    def finish_time_estimated(self):
        if self.t_type == TournType.Arena:
            return self.finishesAt
        elif self.t_type == TournType.Swiss:
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
        if delta_s(self.startsAt, now_utc) >= CHAT_TOURNAMENT_STARTS_IN * 60:
            return False
        finishes_at = self.finish_time_estimated()
        if finishes_at is not None:
            return delta_s(now_utc, finishes_at) < CHAT_TOURNAMENT_FINISHED_AGO * 60
        if not self.finishesAt:
            return True
        return delta_s(now_utc, self.startsAt) < CHAT_SWISS_STARTED_AGO * 60

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
        return (self.t_type == TournType.Arena and now_utc >= self.finishesAt) \
               or (self.t_type != TournType.Arena and self.finishesAt)

    def is_error_404_recently(self, now_utc):
        return self.last_error_404 is not None and delta_s(now_utc, self.last_error_404) < DELAY_ERROR_CHAT_404

    def is_error_404_too_long(self, now_utc):
        return self.last_error_404 is not None and delta_s(now_utc, self.last_error_404) >= TIME_CHAT_REMOVED_404

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
            if self.t_type != TournType.Study or len(self.messages) > 5:
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

    def get_endpoint(self):
        return "tournament" if self.t_type == TournType.Arena else "swiss" if self.t_type == TournType.Swiss else ""

    def download(self, msg_lock, now_utc, non_mod):
        new_messages = []
        deleted_messages = []
        if self.errors or self.is_error_404_recently(now_utc):
            return new_messages, deleted_messages
        try:
            headers = {'User-Agent': "Mozilla/5.0 (X11; U; Linux i686; en-US) AppleWebKit/532.0 (KHTML, like Gecko) "
                                     "Chrome/4.0.212.0 Safari/532.0"}
            #if not self.is_arena:
            #    token = mod.token  # otherwise it doesn't load messages
            token = None
            url = self.link if self.link else f"https://lichess.org/{self.get_endpoint()}/{self.id}"
            r = non_mod.api.get(ApiType.TournamentId, url, token=token, headers=headers)
            if r.status_code != 200:
                if r.status_code >= 500:
                    if self.errors_500 and self.errors_500[-1].is_ongoing():
                        return new_messages, deleted_messages
                    self.errors_500.append(Error500(now_utc, r.status_code))
                    return new_messages, deleted_messages
                elif r.status_code == 404:
                    if self.last_error_404 is None:
                        self.last_error_404 = now_utc
                    return new_messages, deleted_messages
                raise Exception(f"Failed to download {url}<br>Status Code {r.status_code}")
            self.last_error_404 = None
            if self.errors_500 and self.errors_500[-1].is_ongoing():
                self.errors_500[-1].complete(now_utc)
            delay = None if self.last_update is None else deltaseconds(now_utc, self.last_update)
            with msg_lock:
                new_messages, deleted_messages = self.process_messages(r.text, now_utc, delay)
            self.last_update = now_utc
        except Exception as exception:
            log_exception(exception)
            self.errors.append(f"{now_utc:%Y-%m-%d %H:%M} UTC: {exception}")
        except:
            self.errors.append(f"ERROR at {now_utc:%Y-%m-%d %H:%M} UTC")
        self.re_usernames = []  # TODO: initialize with user names of tournament players (fetch once?)
        for user in self.user_names:
            re_user = r"(https?:\/\/)?(lichess\.org\/)?@?\/?" + user
            self.re_usernames.append(ReUser(re_user, 0, info=user, class_name="text-muted"))
        return new_messages, deleted_messages

    def update_reports(self, now_utc, reset_multi_messages):
        self.reports = self.get_info(now_utc)
        self.process_frequent_data(now_utc, reset_multi_messages)

    def process_messages(self, text, now_utc, delay):
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
            msg = Message(d, self, now_utc, delay)
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
            if msg.score is not None:
                continue
            msg.evaluate(self.re_usernames)
            is_msg_visible = not msg.is_reset and not msg.is_removed \
                and not msg.is_disabled and not msg.is_official  # if not msg.is_hidden(): # w/o is_timed_out
            #   and not msg.is_deleted
            if is_msg_visible:
                if msg.score > self.max_score:
                    self.max_score = msg.score
                self.total_score += msg.score
                if not msg.is_hidden():
                    if msg.best_ban_reason() != Reason.No:
                        add_timeout_msg(to_timeout, msg)
        #self.process_usernames(r.text)  # doesn't work with token
        return to_timeout

    def set_reports(self, now_utc):
        self.reports = self.get_info(now_utc)

    def has_sus_messages(self):
        for msg in self.messages:
            if msg.score and not msg.is_hidden():
                return True
        return False

    def get_link(self, short=True):
        name = shorten(self.name, MAX_LEN_TOURNEY_NAME_SHORT if short else MAX_LEN_TOURNEY_NAME_LONG)
        link = self.link if self.link else f'https://lichess.org/{self.get_endpoint()}/{self.id}'
        tournament = f'<a href="{link}" target="_blank">{name}</a>'
        return tournament

    def get_status(self, now_utc):
        if now_utc < self.startsAt:
            return f'<abbr title="Starts in {deltaperiod(self.startsAt, now_utc)}" class="text-info">Created</abbr>'
        if self.t_type == TournType.Arena and now_utc < self.finishesAt:
            return f'<abbr title="Finishes in {deltaperiod(self.finishesAt, now_utc)}" class="text-success">Started</abbr>'
        if self.t_type != TournType.Arena and not self.finishesAt:
            return f'<abbr title="Started {deltaperiod(now_utc, self.startsAt)} ago" class="text-success">Started</abbr>'
        if self.t_type == TournType.Arena:
            return f'<abbr title="Finished {deltaperiod(now_utc, self.finishesAt)} ago" class="text-muted">Finished</abbr>'
        return f'<abbr title="Started {deltaperiod(now_utc, self.startsAt)} ago" class="text-muted">Finished</abbr>'

    def get_info(self, now_utc):
        msgs = [msg.get_info('A', add_mscore=True) for msg in self.messages if msg.score and not msg.is_hidden()]
        if not msgs and not self.errors and not self.errors_500:
            return ""
        errors = self.errors.copy()
        errors.extend([str(err) for err in self.errors_500])
        if self.last_error_404 and (msgs or errors):
            errors.extend(f"Tournament removed at {self.last_error_404:%Y-%m-%d %H:%M} UTC"
                          f" (Failed to download: Status Code 404).")
        header = f'<div class="d-flex user-select-none justify-content-between px-1 mb-1" ' \
                 f'style="background-color:rgba(128,128,128,0.2);">' \
                 f'{self.get_link(short=False)}{self.get_status(now_utc)}</div>'
        btn_clear = f'<div><button class="btn btn-info align-baseline flex-grow-1 py-0 px-1" ' \
                    f'onclick="clear_errors(\'{self.id}\');">Clear errors</button></div>' if errors else ""
        errors = f'<div class="text-warning px-1"><div>{"</div><div>".join(errors)}</div>{btn_clear}</div>' if errors else ""
        return f'<div class="col rounded m-1 px-0" style="background-color:rgba(128,128,128,0.2);min-width:350px">' \
               f'{header}{errors}{"".join(msgs)}</div>'

    def clear_errors(self):
        self.errors.clear()
        self.errors_500.clear()

    def process_frequent_data(self, now_utc, reset_multi_messages):
        if not self.messages:
            return [], {}
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
                    if delta_s(um.time, first_msg_time) >= max(1.0, API_TOURNEY_PAGE_DELAY):
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
            real_msgs = [um for um in msgs if (um is not None and um.delay is not None
                                               and um.text.lower() not in STD_SHORT_MESSAGES)]
            if not real_msgs:
                return
            num_msgs = len(real_msgs)
            if num_msgs < NUM_FREQUENT_MESSAGES and delta_s(now_utc, self.last_update) > MAX_TIME_FREQUENT_MESSAGES:
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
                len_real_msgs = len(real_msgs) if self.t_type == TournType.Study else (2 * len(real_msgs) - len(msgs))
                if len_real_msgs >= 8:
                    coef = 20 if mean_len < 3 else 15 if mean_len < 4 else 10 if mean_len < 5 else 5 if mean_len < 6 \
                              else 2 if mean_len < 10 else 1.5 if mean_len < 15 else 1
                elif len_real_msgs >= 5:
                    coef = 5 if mean_len < 3 else 4 if mean_len < 4 else 2 if mean_len < 5 else 1.5 if mean_len < 10 else 1
                else:
                    coef = 1
                t_1 = real_msgs[0].time - timedelta(seconds=real_msgs[0].delay)
                t_9 = real_msgs[min(len(real_msgs) - 1, 9)].time
                dt = deltaseconds(t_9, t_1)
                coef_decrease = max(1, min(10, dt / 60))
                score_int = int(score_int * coef / coef_decrease)
            combined_text = " ".join([m.text for m in real_msgs])
            combined_msg = Message({'u': user_name, 't': combined_text}, real_msgs[-1].tournament, real_msgs[-1].time)
            combined_msg.id = -msgs_id  # for recommended_timeouts
            max_score = max([(0 if m.score is None else m.score) for m in real_msgs])
            combined_msg.evaluate(self.re_usernames)
            best_ban_reason = combined_msg.best_ban_reason()
            if best_ban_reason != Reason.No or score_int > MULTI_MSG_MIN_TIMEOUT_SCORE:
                combined_msg.text = f'[multiline] {" | ".join([m.text for m in real_msgs])}'
                if score_int > MULTI_MSG_MIN_TIMEOUT_SCORE:
                    combined_msg.reasons[Reason.Spam] = score_int / MULTI_MSG_MIN_TIMEOUT_SCORE
                    combined_msg.score = score_int
                    combined_msg.languages |= Lang.Spam
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
                        combined_msg.text = f'[multiline] ' \
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
            if score_int < CHAT_FREQUENT_MSGS_MIN_SCORE[0] or (score_int < CHAT_FREQUENT_MSGS_MIN_SCORE[1] and num_msgs < 5):
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
                             f'onclick="timeout_multi(\'{tag}{msgs_id}\', {int(best_reason)});">{r}</button>{button_ban}'
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
            is_to_be_processed = not msg.is_disabled and not msg.is_timed_out  # and not msg.is_deleted
            is_among_first_messages = delta_s(msg.time, first_msg_time) < max(1.0, API_TOURNEY_PAGE_DELAY)
            keys = list(user_msgs.keys())
            for username in keys:
                if not is_to_be_processed or username != last_user:
                    if not is_among_first_messages \
                            and delta_s(msg.time, get_last_time(username)) < TIME_FREQUENT_MESSAGES:
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
        self.multiline_reports = output
        return multi_messages, to_timeout

    def get_list_item(self, now_utc, monitored=False):
        checked = ' checked=""' if monitored or ((self.t_type != TournType.Swiss or CHAT_UPDATE_SWISS)
                                                 and self.is_active(now_utc)) else ""
        disabled = "" if monitored or self.t_type != TournType.Swiss or CHAT_UPDATE_SWISS else ' disabled'
        if now_utc < self.startsAt:
            info = f'{deltaperiod(self.startsAt, now_utc, short=True)}'
        elif self.t_type == TournType.Arena and now_utc < self.finishesAt:
            info = f'{deltaperiod(self.finishesAt, now_utc, short=True)}'
        elif self.t_type == TournType.Arena:
            info = f'{deltaperiod(now_utc, self.finishesAt, short=True)}'
        else:
            info = f'started {deltaperiod(now_utc, self.startsAt, short=True)} ago'
        num_messages = f'{len(self.messages):03d}' if self.t_type != TournType.Swiss \
                                                      or CHAT_UPDATE_SWISS or len(self.messages) else "&minus;&minus;&minus;"
        if len(self.messages) > 0:
            tag = 'T'
            i = max(0, len(self.messages) - NUM_MSGS_BEFORE)
            num_class = "btn-secondary" if len(self.messages) < 100 else "btn-primary"
            num_messages = f'<button class="brt {num_class} align-baseline flex-grow-0 px-1 py-0"  ' \
                           f'onclick="select_message(event,\'{tag}{self.messages[i].id}\')">{num_messages}</button>'
        else:
            num_messages = f'<span class="px-1">{num_messages}</span>'
        text_class = " text-info" if self.is_monitored else ""
        id_prefix = "tt" if monitored else "t"
        onchange = "delete_tournament" if monitored else "set_tournament"
        return f"""<div class="form-check form-switch">
          <input class="form-check-input" type="checkbox" id="{id_prefix}_{self.id}" 
          onchange="{onchange}('{self.id}')"{checked}{disabled}>
          <label class="form-check-label d-flex justify-content-between{text_class}" for="t_{self.id}">
          <span>{num_messages} {self.get_link()}</span><span>{info}</span></label>
        </div>"""
