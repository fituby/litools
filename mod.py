from datetime import datetime
from dateutil import tz
from enum import IntEnum
from threading import Lock
from elements import decode_string, read_notes, datetime_to_abbr_ago, datetime_to_abbr_in, log_exception
from database import Mods
from api import Api, ApiType
from consts import BOOST_RING_TOOL


class Mod:
    login_button = f'<a href="/login" class="btn btn-lg btn-primary>Log in</a>'
    auth_lock = Lock()

    @staticmethod
    def revoke_token(token_hash):
        try:
            mod_db = Mods.get(tokenHash=token_hash)
            mod_db.delete_instance()
            return True
        except:
            return False

    def __init__(self, token, current_session="", mod_db=None, check_perms=True, get_public_data=True):
        self.token = token
        self.current_session = current_session
        self.mod_db = mod_db
        self.api = Api()
        self.alt_cache = {}
        self.alt_group_cache = {}
        self.refresh_openings_times = {}
        self.boost_cache = {}
        self.boost_ring_tool = ""
        self.is_admin = False
        self.to_read_mod_log = False
        self.to_read_notes = False
        if check_perms and token:
            self.check_perms()
        self.last_mod_log_error = None
        self.last_notes_error = None
        self.id = ""
        self.name = ""
        if get_public_data and token:
            self.set_public_data()
        self.view = View()

    def check_perms(self):
        self.boost_ring_tool = decode_string(BOOST_RING_TOOL, self)  # returns "" (not None) if not available
        self.is_admin = self.check_admin()
        self.to_read_mod_log = self.is_mod()
        self.to_read_notes = self.is_mod()

    def is_mod(self):
        return not not self.boost_ring_tool  # workaround

    def check_admin(self):
        num = 0
        try:
            data = read_notes("test", self)
            num = sum([len(d) for d in data])
        except:
            pass
        return num >= 2  # workaround

    def get_public_data(self):
        try:
            url = "https://lichess.org/api/account"
            r = self.api.get(ApiType.ApiAccount, url, token=self.token)
            if r.status_code == 200:
                data = r.json()
                return data['id'], data['username']
        except Exception as exception:
            log_exception(exception)
        return "", ""

    def set_public_data(self):
        self.id, self.name = self.get_public_data()

    def logout(self):
        if not self.current_session or not self.id or not self.name:
            raise Exception("There's no active session.")
        try:
            url = "https://lichess.org/api/token"
            r = self.api.delete(ApiType.ApiToken_Delete, url, token=self.token)
            if r.status_code != 204:
                raise Exception(f"Failed to log out of Lichess.<br>Status code: {r.status_code}")
            self.mod_db.delete_instance()
        except Exception as exception:
            log_exception(exception)
            raise exception

    def status_info(self):
        if not self.id or not self.name:
            return f'<p class="mb-2">You\'re logged in as an anonymous</p>{Mod.login_button}'
        try:
            name = f'<p class="ml-2 mb-2">You\'re logged in as <a href="https://lichess.org/@/{self.id}" ' \
                   f'target="_blank">{self.name}</a></p>'
            logout = f'<a href="/logout" class="btn btn-lg btn-primary ml-3 mb-2">Log out</a>' \
                if self.current_session else ""
            return f'<div class="row align-items-baseline">{logout}{name}</div>'
        except Exception as exception:
            log_exception(exception)
            return f'<div class="col my-2"><h2 class="text-danger text-center">Error</h2>' \
                   f'<h4>Failed to load mod info: {exception}</h4></div>{Mod.login_button}'

    def sessions_info(self):
        if not self.id or not self.name:
            return ""
        try:
            sessions = list(Mods.select().where((Mods.modId == self.id) & Mods.enabled).order_by(Mods.seenAt.desc()))
            if not sessions:
                return f'You do not have any active sessions (tokens) on this website.'
            now_tz = datetime.now(tz=tz.tzutc()).replace(tzinfo=None)
            rows = []
            is_revoke = False
            for session in sessions:
                is_current = self.current_session and self.current_session == session.tokenHash
                session_tag = f'<span>{len(rows) + 1} &mdash; {session.tokenHash[:8].replace("-", "&amp;")}</span>'
                if is_current:
                    session_tag = f'{session_tag}<span class="text-warning ml-2">CURRENT</span>'
                row = f'<tr id="{session.tokenHash}">' \
                      f'<td class="text-left align-baseline">{session_tag}</td>' \
                      f'<td class="align-baseline">{datetime_to_abbr_ago(session.seenAt, now_tz)}</td>' \
                      f'<td class="align-baseline">{datetime_to_abbr_ago(session.createdAt, now_tz)}</td>' \
                      f'<td class="align-baseline">{datetime_to_abbr_in(session.expiresAt, now_tz)}</td>'
                if is_current:
                    row = f'{row}<td class="align-baseline"><a href="/logout" class="btn btn-danger">Log out</a></td>'
                else:
                    row = f'{row}<td class="align-baseline"><button class="btn btn-danger" onclick="revoke_token(this);">' \
                          f'Revoke</button></td>'
                    is_revoke = True
                row = f'{row}</tr>'
                rows.append(row)
            revoke_info = f'<p><small>* If you revoke tokens, they will become invalid for use on this website, but will ' \
                          f'not be deleted from Lichess.<br>To remove them from Lichess, you have to <b>log out</b> after ' \
                          f'logging in with the token you want to remove.<br>Alternatively, you can delete them ' \
                          f'<a href="https://lichess.org/account/security" target="_blank">directly on lichess</a>.' \
                          f'</small></p>' if is_revoke else ""
            table = f'<table id="table-sessions" ' \
                    f'class="table table-striped table-hover text-center w-auto text-nowrap mt-5">' \
                    f'<thead><tr><th>Session</th>' \
                    f'<th>Active</th>' \
                    f'<th>Created</th>' \
                    f'<th>Expires</th>' \
                    f'<th>Revoke</th></tr></thead>{"".join(rows)}</table>'
            return f'{table}{revoke_info}'
        except Exception as exception:
            log_exception(exception)
            return f'<div class="col my-2"><h2 class="text-danger text-center">Error</h2>' \
                   f'<h4>Failed to load sessions info: {exception}</h4></div>{Mod.login_button}'

    def session_id(self):
        return self.current_session[:8].replace("-", "&") if self.current_session else "-"

    def get_bar(self):
        if not self.name:
            return ""
        field_class = "" if self.current_session else " disabled"
        field = f'<a href="/" class="btn btn-secondary{field_class} ml-2 py-0">{self.name}</a>'
        return f'<div class="d-flex flex-row align-items-baseline p-2" style="position:absolute;top:0px;right:0px">' \
               f'{field}</div>'

    def update_theme(self, cookies):
        mode = cookies.get('theme_mode', '-1')
        self.view.set_mode(mode)

    def is_chat(self):
        return not not self.token

    def is_boost(self):
        return self.is_mod()

    def is_alt(self):
        return self.is_admin


class ModInfo:
    def __init__(self, mod, last_seenAt, last_updated):
        self.mod = mod
        self.last_seenAt = last_seenAt
        self.last_updated = last_updated


class Mode(IntEnum):
    AutoLight = -2
    AutoDark = -1
    Dark = 1
    Light = 2


class View:
    def __init__(self, mode=Mode.AutoDark):
        self.theme = ""
        self.theme_color = ""
        self.mode = int(mode)
        self.set_mode(mode)

    def set_mode(self, mode):
        try:
            self.mode = int(mode)
            if self.mode not in [Mode.AutoLight, Mode.AutoDark, Mode.Dark, Mode.Light]:
                self.mode = int(Mode.AutoDark)
        except Exception as exception:
            log_exception(exception)
            self.mode = int(Mode.AutoDark)
        except:
            self.mode = int(Mode.AutoDark)
        self.theme = "flatly" if self.mode in [Mode.Light, Mode.AutoLight] else "darkly"
        self.theme_color = "#ffffff" if self.mode in [Mode.Light, Mode.AutoLight] else "#222222"
