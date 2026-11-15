from datetime import datetime, timedelta
from dateutil import tz
import json
import random
from elements import Reason, TournType, deltaseconds, delta_s, deltaperiod, get_client_id, shorten, add_timeout_msg
from elements import log, log_exception, Error500
from chat_re import ReUser, Lang
from chat_message import Message
from api import ApiType
from database import Messages, Chats, db
from consts import *


class Tournament:
    def __init__(self, tourney, t_type, link="", is_monitored=False, is_calendar=False):
        self.t_type = t_type
        self.is_calendar = is_calendar
        self.next_distant_check: datetime = None
        self.id = tourney['id']
        self.is_official = (tourney['createdBy'] in ["lichess", "Lichess"])
        self.num_players = tourney['nbPlayers']
        startsAt = tourney.get('startsAt')
        if startsAt is None:
            self.startsAt = datetime.now(tz=tz.tzutc())
        elif isinstance(startsAt, str):
            i1 = startsAt.rfind('.')
            i2 = startsAt.rfind('Z')
            if i1 < 0 and i2 < 0:
                log(f"Error Tournament 'startsAt' {t_type}={self.id}: {tourney}", to_print=True, to_save=True)
                self.startsAt = datetime.now(tz=tz.tzutc())
            else:
                i_start = i1 if i2 < 0 else i2 if i1 < 0 else min(i1, i2)
                self.startsAt = datetime.strptime(startsAt[:i_start], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=tz.tzutc())
        else:
            self.startsAt = datetime.fromtimestamp(startsAt // 1000, tz=tz.tzutc())
        if t_type == TournType.Arena:
            self.name = tourney['fullName'].strip().removesuffix(' Arena').strip()
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
        self.user_flairs = {}
        self.re_usernames = []
        self.errors = []
        self.errors_500 = []
        self.last_error_404: datetime = None
        self.max_score = 0
        self.total_score = 0
        self.is_monitored = is_monitored
        self.is_frequent = False
        self.is_enabled = True
        self.link = link
        self.last_update: datetime = None
        self.is_just_added = False
        self.reports = ""
        self.multiline_reports = ""
        self.is_sync_with_db = False
        self.is_chat_saved = False
        self.keep_max_messages = False

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
        if not self.is_calendar and delta_s(self.startsAt, now_utc) >= CHAT_TOURNAMENT_STARTS_IN * 60:
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

    def is_distant(self, now_utc):
        return self.is_calendar and delta_s(self.startsAt, now_utc) >= CHAT_CALENDAR_STARTS_IN * 60

    def is_distant_check_due(self, now_utc):
        if self.next_distant_check is None:
            self.next_distant_check = now_utc + timedelta(seconds=random.uniform(*CHAT_DISTANT_FIRST_CHECK))
        return now_utc >= self.next_distant_check

    def schedule_distant_check(self, now_utc):
        has_chat = any(not msg.is_official for msg in self.messages)
        period = CHAT_DISTANT_ACTIVE_PERIOD if has_chat else CHAT_DISTANT_PERIOD
        self.next_distant_check = now_utc + timedelta(seconds=period)

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
        if self.is_frequent:
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

    def download(self, msg_lock, now_utc, room_mod):
        new_messages = []
        deleted_messages = []
        if self.errors or self.is_error_404_recently(now_utc):
            return new_messages, deleted_messages
        try:
            db_messages = []
            if not self.is_sync_with_db:
                for msg in Messages.select().where(Messages.tournament == self.id).order_by(-Messages.time, -Messages.id). \
                            limit(CHAT_MAX_NUM_MSGS):
                    data = {'u': msg.username, 't': msg.text, 'r': msg.removed, 'd': msg.disabled}
                    msg_time = msg.time.replace(tzinfo=tz.tzutc())
                    db_messages.append(Message(data, self, msg_time, msg.delay, msg.id, msg.timeout))
                if db_messages:
                    db_messages.reverse()
                    if not self.last_update:
                        self.last_update = db_messages[-1].time
                    new_messages = self.add_messages(db_messages, can_be_old=bool(self.messages))
                self.is_sync_with_db = True
            if room_mod.token:
                url = f"https://lichess.org/api/room/{self.id}/chat"
                r = room_mod.api.get(ApiType.ApiRoomChat, url, token=room_mod.token)
            else:
                url = self.link if self.link else f"https://lichess.org/{self.get_endpoint()}/{self.id}"
                if url and self.t_type == TournType.Study:
                    url = f"{url}#players"
                r = room_mod.api.get(ApiType.TournamentId, url, token=None)
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
                raise Exception(f"Failed to download {url}\nStatus Code {r.status_code}")
            self.last_error_404 = None
            if self.errors_500 and self.errors_500[-1].is_ongoing():
                self.errors_500[-1].complete(now_utc)
            delay = None if self.last_update is None else deltaseconds(now_utc, self.last_update)
            with msg_lock:
                if room_mod.token:
                    newest_messages, deleted_messages = self.process_room_messages(r, now_utc, delay)
                else:
                    newest_messages, deleted_messages = self.process_tourn_messages(r.text, now_utc, delay)
                Tournament.update_db(newest_messages)
            if newest_messages and not self.is_chat_saved:
                self.save_chat()
            new_messages.extend(newest_messages)
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

    def process_room_messages(self, r, now_utc, delay):
        deleted_messages = self.delete_old_messages(CHAT_MAX_NUM_OLD_MSGS if self.keep_max_messages else CHAT_MAX_NUM_MSGS)
        data = r.json()
        data_users = data.get('users', {})
        data_lines = data.get('lines', [])
        # Update users and flairs
        users = {}
        for user_id, d in data_users.items():
            user_name = d['name']
            users[user_id] = user_name
            flair = d.get('flair')
            if flair:
                self.user_flairs[user_name] = flair
        # Add messages
        messages = []
        for line in data_lines:
            user_name = users.get(line['user']) or line['user']
            d = {
                'u': user_name,
                't': line['text'],
                'r': line.get('r', False),
                'd': line.get('d', False)
            }
            messages.append(Message(d, self, now_utc, delay))
        new_messages = self.add_messages(messages, can_be_old=True)
        return new_messages, deleted_messages

    def process_tourn_messages(self, text, now_utc, delay):
        i1 = text.find(CHAT_BEGINNING_MESSAGES_TEXT)
        if i1 < 0:
            return [], []
        i1 = i1 + len(CHAT_BEGINNING_MESSAGES_TEXT) - 1
        i2 = text.find(CHAT_END_MESSAGES_TEXT, i1)
        if i2 < 0:
            raise Exception("ERROR /tournament messages: No ']'")
        deleted_messages = self.delete_old_messages(CHAT_MAX_NUM_OLD_MSGS if self.keep_max_messages else CHAT_MAX_NUM_MSGS)
        text_json = text[i1:i2 + 1]
        data = json.loads(text_json)
        # Update flairs
        for d in data:
            flair = d.get('f', "")
            if flair:
                self.user_flairs[d['u']] = flair
        # Add messages
        messages = [Message(d, self, now_utc, delay) for d in data]
        new_messages = self.add_messages(messages, can_be_old=True)
        return new_messages, deleted_messages

    def delete_old_messages(self, max_num_msgs=CHAT_MAX_NUM_MSGS):
        deleted_messages = []
        if len(self.messages) > max_num_msgs:
            i_cut = len(self.messages) - max_num_msgs
            deleted_messages = self.messages[:i_cut]
            self.messages = self.messages[i_cut:]
        return deleted_messages

    def add_messages(self, messages, can_be_old=True):
        new_messages = []
        do_detect_deleted = True
        i_msg = 0
        is_new = True
        for msg in messages:
            if can_be_old:
                is_new = True
                for i in range(i_msg, len(self.messages)):
                    if msg == self.messages[i]:
                        i_msg = i + 1
                        is_new = False
                        self.messages[i].update(msg)
                        if do_detect_deleted:
                            for j in range(i - 1, -1, -1):
                                if self.messages[j].is_deleted:
                                    break
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
        return new_messages

    @staticmethod
    def update_db(new_messages):
        with db.atomic():
            for msg in new_messages:
                msg_db = Messages.create(time=msg.time.replace(tzinfo=None), delay=msg.delay, username=msg.username,
                                         text=msg.text, removed=msg.is_removed, disabled=msg.is_disabled,
                                         timeout=msg.is_timed_out, tournament=msg.tournament.id)
                msg.db_id = msg_db.id

    def chat_link(self):
        return self.link or (f'https://lichess.org/{self.get_endpoint()}/{self.id}' if self.get_endpoint() else None)

    def save_chat(self):
        try:
            Chats.replace(id=self.id, type=self.t_type.value, name=self.name, url=self.chat_link(),
                          startsAt=self.startsAt.replace(tzinfo=None),
                          checkedAt=datetime.now(tz=tz.tzutc()).replace(tzinfo=None)).execute()
            self.is_chat_saved = True
        except Exception as exception:
            log_exception(exception)

    def set_max_messages(self, flag, chat):
        old_flag = self.keep_max_messages
        self.keep_max_messages = flag
        if flag:
            if not self.messages or self.messages[0].db_id is None:
                raise Exception(f"No messages to load. Tournament ID: {self.id}")
            db_messages = []
            for msg in Messages.select().where((Messages.tournament == self.id) & (Messages.id < self.messages[0].db_id)). \
                    order_by(-Messages.time, -Messages.id).limit(CHAT_MAX_NUM_OLD_MSGS):
                data = {'u': msg.username, 't': msg.text, 'r': msg.removed, 'd': msg.disabled}
                old_msg = Message(data, self, msg.time.replace(tzinfo=tz.tzutc()), msg.delay, msg.id, msg.timeout)
                old_msg.is_deleted = True
                db_messages.append(old_msg)
            new_messages = []
            with chat.msg_lock:
                for msg in db_messages:
                    msg.id = Message.global_id
                    Message.global_id += 1
                    self.messages.insert(0, msg)
                    msg.dont_evaluate()
                    new_messages.append(msg)
                    if not msg.is_official:
                        self.user_names.add(msg.username)
            chat.sync_messages(self.id, new_messages, [])
        elif old_flag:
            with chat.msg_lock:
                deleted_messages = self.delete_old_messages()
            chat.sync_messages(self.id, [], deleted_messages)

    def set_enabled(self, flag, chat):
        self.is_enabled = flag
        if not flag:
            self.set_max_messages(False, chat)

    def is_more(self):
        return (not self.keep_max_messages) and len(self.messages) >= CHAT_MAX_NUM_MSGS

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
        for msg in self.messages[:-CHAT_MAX_NUM_MSGS]:
            msg.dont_evaluate()
        for msg in self.messages[-CHAT_MAX_NUM_MSGS:]:
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

    def get_url(self):
        link = self.link if self.link else f'https://lichess.org/{self.get_endpoint()}/{self.id}'
        if link and self.t_type == TournType.Study:
            link = f"{link}#players"
        return link

    def get_name(self, short=True):
        return shorten(self.name, MAX_LEN_TOURNEY_NAME_SHORT if short else MAX_LEN_TOURNEY_NAME_LONG)

    def get_status(self, now_utc):
        if now_utc < self.startsAt:
            return {'text': "Created", 'c': "text-info", 'i': f"Starts in {deltaperiod(self.startsAt, now_utc)}"}
        if self.t_type == TournType.Arena and now_utc < self.finishesAt:
            return {'text': "Started", 'c': "text-success", 'i': f"Finishes in {deltaperiod(self.finishesAt, now_utc)}"}
        if self.t_type != TournType.Arena and not self.finishesAt:
            return {'text': "Started", 'c': "text-success", 'i': f"Started {deltaperiod(now_utc, self.startsAt)} ago"}
        if self.t_type == TournType.Arena:
            return {'text': "Finished", 'c': "text-muted", 'i': f"Finished {deltaperiod(now_utc, self.finishesAt)} ago"}
        return {'text': "Finished", 'c': "text-muted", 'i': f"Started {deltaperiod(now_utc, self.startsAt)} ago"}

    def get_header(self, now_utc=None, short=True):
        header = {'id': self.id, 'url': self.get_url(), 'name': self.get_name(short)}
        if now_utc:
            header['status'] = self.get_status(now_utc)
        return header

    def get_info(self, now_utc):
        msgs = [msg.to_data() for msg in self.messages if msg.score and not msg.is_hidden()]
        if not msgs and not self.errors and not self.errors_500:
            return None
        errors = self.errors.copy()
        errors.extend([str(err) for err in self.errors_500])
        if self.last_error_404 and (msgs or errors):
            errors.append(f"Tournament removed at {self.last_error_404:%Y-%m-%d %H:%M} UTC"
                          f" (Failed to download: Status Code 404).")
        return {'tourn': self.get_header(now_utc, short=False), 'errors': errors, 'msgs': msgs}

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
            # score_parts: [score for the number of messages (None if hidden), extra score for the combined text]
            score_parts = [{'v': score_int, 'i': f"{num_msgs} messages in a row or in a short period of time"}]
            if combined_msg.score > max_score:
                if score_int <= 0:
                    score_parts[0] = None
                score_parts.append({'v': combined_msg.score,
                                    'i': Reason.to_text(best_reason) if best_reason != Reason.No else ""})
                score_int += combined_msg.score
            if score_int < CHAT_FREQUENT_MSGS_MIN_SCORE[0] or (score_int < CHAT_FREQUENT_MSGS_MIN_SCORE[1] and num_msgs < 5):
                return
            info = {'id': msgs_id, 'score': score_int, 'score_parts': score_parts, 'tourn': self.get_header(now_utc),
                    'msg': combined_msg.to_data(), 'msgs': [None if m is None else m.to_data() for m in msgs]}
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

    def get_list_item(self, now_utc):
        """Data for the tournament lists of the chat page."""
        if now_utc < self.startsAt:
            info = deltaperiod(self.startsAt, now_utc, short=True)
        elif self.t_type == TournType.Arena and now_utc < self.finishesAt:
            info = deltaperiod(self.finishesAt, now_utc, short=True)
        elif self.t_type == TournType.Arena:
            info = deltaperiod(now_utc, self.finishesAt, short=True)
        else:
            info = f'started {deltaperiod(now_utc, self.startsAt, short=True)} ago'
        item = {'id': self.id, 'name': self.get_name(), 'url': self.get_url(), 'info': info, 'n': len(self.messages),
                'active': self.is_active(now_utc)}
        if self.messages:
            item['first'] = self.messages[max(0, len(self.messages) - NUM_MSGS_BEFORE)].id
        if self.t_type == TournType.Swiss and not CHAT_UPDATE_SWISS:
            item['swiss_off'] = True
        if self.is_monitored:
            item['monitored'] = True
        if self.is_frequent:
            item['frequent'] = True
        return item
