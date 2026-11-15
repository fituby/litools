from flask import Flask, Response, render_template, request, make_response, session, redirect
from flask_compress import Compress
from flask_minify import minify
from waitress import serve
from functools import wraps
import logging
import threading
import base64
from secrets import token_bytes
import hashlib
from urllib.parse import urlencode, quote_plus, urlsplit
import requests
from datetime import datetime, timedelta
from dateutil import tz
import math
import re
from peewee import DoesNotExist
from boost import get_boost_data, send_boost_note, send_mod_action
from leaderboard import update_leaderboard
from chat import ChatAnalysis
from alt import Alts
from footprints import analyze_footprints, cancel_footprints, get_footprints, variants1, variants2
from search import search_users
from mod import Mod, ModInfo, View
from api import get_user_agent
from elements import get_client_id, get_host, get_port, get_num_threads, get_embed_lichess
from elements import get_token, get_room_token, get_uri, delta_s, close_account
from elements import log, log_exception, log_read, is_username
from database import Mods, Authentication
from consts import *


logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('werkzeug')
logger.setLevel(logging.ERROR)
# if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
#     # template_folder = os.path.join(sys._MEIPASS, 'templates')
#     # static_folder = os.path.join(sys._MEIPASS, 'static')
#     app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/")
# else:
app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/")
app.secret_key = token_bytes(32)
app.config['SESSION_TYPE'] = 'memcached'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = get_uri().startswith("https://")
Compress(app)  # must be registered before minify: after_request hooks run in reverse order
minify(app=app, html=True, js=True, cssless=True)


def url_origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


@app.before_request
def check_origin():
    """Rejects state-changing requests sent from other websites (CSRF)."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    origin = request.headers.get('Origin')
    if origin and origin.lower() not in (url_origin(get_uri()), url_origin(request.host_url)):
        log_bad_request(f"cross-site {request.method} {request.path} from {origin}")
        return Response(status=403)
    return None


@app.after_request
def add_security_headers(resp):
    resp.headers.setdefault('X-Frame-Options', "DENY")
    resp.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
    resp.headers.setdefault('X-Content-Type-Options', "nosniff")
    resp.headers.setdefault('Referrer-Policy', "strict-origin-when-cross-origin")
    return resp
chat = ChatAnalysis()
auto_mod_token = get_token()
auto_mod = Mod(auto_mod_token) if auto_mod_token else None
non_mod = Mod("")
room_mod_token = get_room_token()
room_mod = Mod(room_mod_token) if room_mod_token else non_mod
mod_cache = {}
re_state = re.compile(r'[\w-]')


def with_mod(page=False, allow=None, update_theme=False, update_seenAt=False):
    """Passes the logged-in moderator to the view as its first argument.
    Without a valid login, pages redirect to /login and API requests get 401.
    allow: permission check of the tool (e.g. Mod.is_boost); moderators without it get 403."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            try:
                mod = get_mod(request.cookies, update_theme=update_theme, update_seenAt=update_seenAt)
            except Exception:
                return redirect('/login') if page else Response(status=401)
            if allow and not allow(mod):
                return Response("You don't have access to this tool.", status=403)
            return view(mod, *args, **kwargs)
        return wrapper
    return decorator


@app.route('/lb/<variant>', methods=['GET'])
@app.route('/lb/<variant>/', methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True)
def create_leaderboard(mod, variant):
    leaderboard, lb_last_update, variant = update_leaderboard(non_mod, variant)
    dt = f"{lb_last_update:%d %B %H:%M}" if lb_last_update else ""
    return render_template('/leaderboard.html', variant=variant, dt=dt, mod=mod, view=mod.view, icon="L/")


@app.route("/lb_<variant>.txt")
@with_mod()
def make_leaderboard(mod, variant):
    leaderboard, lb_last_update, variant = update_leaderboard(mod, variant)
    return {'data': leaderboard}


@app.route('/boost/', methods=['GET', 'POST'])
@app.route('/boost', methods=['GET', 'POST'])
@with_mod(page=True, update_theme=True, update_seenAt=True, allow=Mod.is_boost)
def create_boost(mod):
    boost_user = request.form.get("user", None) if request.method == 'POST' else None
    if not is_username(boost_user):
        boost_user = None
    return render_template('/boost.html', boost_user=boost_user, embed_lichess=get_embed_lichess(),
                           mod=mod, view=mod.view, icon="B/")


@app.route('/boost/<user>/', methods=['POST'])
@with_mod(update_seenAt=True, allow=Mod.is_boost)
def get_boost_user(mod, user):
    if not is_username(user):
        return Response("Invalid username", status=400)
    before = request.form.get("before", None)
    num_games = request.form.get("num_games", None)
    perf_type = request.form.get("perf_type", None)
    boost = get_boost_data(user.lower(), mod, num_games, before, perf_type)
    return boost.get_output(mod)


@app.route('/boost/<user>/tournaments/', methods=['GET'])
@with_mod(allow=Mod.is_boost)
def create_tournaments(mod, user):
    if not is_username(user):
        return Response("Invalid username", status=400)
    boost = get_boost_data(user.lower(), mod)
    return boost.get_tournaments(mod)


@app.route('/boost/send_note', methods=['POST'])
@with_mod(allow=Mod.is_boost)
def boost_send_note(mod):
    user = request.form.get("user", None)
    if not is_username(user):
        return Response("Invalid username", status=400)
    note = request.form.get("note", None)
    return send_boost_note(note, user, mod)


@app.route('/boost/mod_action', methods=['POST'])
@with_mod(allow=Mod.is_boost)
def boost_mod_action(mod):
    user = request.form.get("user", None)
    if not is_username(user):
        return Response("Invalid username", status=400)
    action = request.form.get("action", None)
    return send_mod_action(action, user, mod)


@app.route('/alt/', methods=['GET', 'POST'])
@app.route('/alt', methods=['GET', 'POST'])
@with_mod(page=True, update_theme=True, update_seenAt=True, allow=Mod.is_alt)
def create_alt(mod):
    form = request.form if request.method == 'POST' else {}
    return render_template('/alt.html', embed_lichess=get_embed_lichess(), mod=mod, view=mod.view, icon="A/",
                           alts=form.get("alts"), num_games=form.get("num_games"),
                           date_begin=form.get("date_begin"), date_end=form.get("date_end"))


@app.route('/alts/<step>/', methods=['POST'])
@with_mod(update_theme=True, allow=Mod.is_alt)
def get_alts(mod, step):
    alt_names = request.form.get("alts", None)
    num_games = request.form.get("num_games", None)
    date_begin = request.form.get("date_begin", None)
    date_end = request.form.get("date_end", None)
    force_refresh_openings = bool(request.form.get("force_refresh_openings", False))
    return Alts.get_response(step, alt_names, num_games, date_begin, date_end, force_refresh_openings, mod)


@app.route('/chat/', methods=['GET'])
@app.route('/chat', methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True)
def create_chat(mod):
    return render_template('/chat.html', update_frequency=chat.i_update_frequency, mod=mod, view=mod.view, icon="C/")


@app.route('/chat/update/<state>', methods=['POST'])
@with_mod()
def get_chat_update(mod, state):
    return chat.get_tournaments_data(state)


def chat_changes(mod):
    """The parts of the chat data that changed since the versions the page sent with its request."""
    return chat.get_changes(mod, request.form.get("reports_state"), request.form.get("selected_version"))


@app.route('/chat/process', methods=['POST'])
@with_mod()
def get_chat_process(mod):
    return chat_changes(mod)


@app.route('/chat/set_msg_ok/<msg_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_set_msg_ok(mod, msg_id):
    chat.set_msg_ok(msg_id)
    return chat_changes(mod)


@app.route('/chat/timeout/<msg_id>/<reason>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_timeout(mod, msg_id, reason):
    chat.timeout(msg_id, reason, mod)
    return chat_changes(mod)


@app.route('/chat/timeout_multi/<msg_id>/<reason>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_timeout_multi(mod, msg_id, reason):
    excluded = {int(i) for i in request.form.getlist("excluded[]") if i.isdigit()}
    chat.timeout_multi(msg_id, reason, mod, excluded)
    return chat_changes(mod)


@app.route('/chat/set_multi_msg_ok/<msg_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_set_multi_msg_ok(mod, msg_id):
    chat.set_multi_msg_ok(msg_id)
    return Response(status=204)


@app.route('/chat/warn/<username>/<subject>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_warn(mod, username, subject):
    if not is_username(username):
        return Response("Invalid username", status=400)
    chat.warn(username, subject, mod)
    return chat_changes(mod)


@app.route('/chat/set_update/<update_frequency>', methods=['POST'])
@with_mod()
def chat_set_update(mod, update_frequency):
    chat.set_update(update_frequency)
    return Response(status=204)


@app.route('/chat/select_message/<msg_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_select_message(mod, msg_id):
    chat.select_message(msg_id, mod)
    return chat_changes(mod)


@app.route('/chat/refresh_selected', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_refresh_selected(mod):
    chat.refresh_selected(mod, room_mod, auto_mod)
    return chat_changes(mod)


@app.route('/chat/clear_errors/<tourn_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_clear_errors(mod, tourn_id):
    chat.clear_errors(tourn_id)
    return chat_changes(mod)


@app.route('/chat/set_tournament/<tourn_id>/<checked>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_set_tournament(mod, tourn_id, checked):
    chat.set_tournament(tourn_id, checked == '1')
    return Response(status=204)


@app.route('/chat/set_tournament/<tourn_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_flip_tournament(mod, tourn_id):
    chat.set_tournament(tourn_id, None)
    return Response(status=204)


@app.route('/chat/delete_tournament/<tourn_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_delete_tournament(mod, tourn_id):
    return chat.delete_tournament(tourn_id)


@app.route('/chat/set_frequent/<tourn_id>/<checked>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_set_frequent(mod, tourn_id, checked):
    return chat.set_frequent(tourn_id, checked == '1')


@app.route('/chat/set_tournament_group/<group>/<checked>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_set_tournament_group(mod, group, checked):
    return chat.set_tournament_group(group, checked == '1')


@app.route('/chat/set_tournament_group/<group>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_flip_tournament_group(mod, group):
    return chat.set_tournament_group(group, None)


@app.route('/chat/add_tournament', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_add_tournament(mod):
    page = request.form.get("page", "")
    data = chat.add_tournament(page, non_mod, room_mod)  # add `, auto_mod` to auto time out after adding a tournament
    data.update(chat_changes(mod))
    return data


@app.route('/chat/load_more/<tourn_id>', methods=['POST'])
@with_mod(update_seenAt=True)
def chat_load_more(mod, tourn_id):
    data = chat.load_more(tourn_id, mod)
    data.update(chat_changes(mod))
    return data


@app.route('/chat/send_note', methods=['POST'])
@with_mod()
def chat_send_note(mod):
    if not is_username(request.form.get("user")):
        return Response("Invalid username", status=400)
    is_ok = chat.send_note(request.form.get("note"), request.form.get("user"), mod)
    data = chat_changes(mod)
    data['ok'] = is_ok
    return data


@app.route('/chat/custom_timeout', methods=['POST'])
@with_mod(update_seenAt=True)
def custom_timeout(mod):
    msg_ids = request.form.getlist("ids[]") or None
    reason = request.form.get("reason", 0)
    chat.custom_timeout(msg_ids, reason, mod)
    return chat_changes(mod)


@app.route('/comms/', methods=['GET'])
@app.route('/comms', methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True, allow=Mod.is_mod)
def create_comms(mod):
    return render_template('/comms.html', mod=mod, view=mod.view, icon="C/")


@app.route('/comms', methods=['POST'])
@with_mod(update_seenAt=True, allow=Mod.is_mod)
def query_comms(mod):
    data = request.form
    username = data.get("username", "").strip()
    text = data.get("text", "").strip()
    tournId = data.get("tournId", "").strip()
    date_begin = data.get("date_begin", None)
    date_end = data.get("date_end", None)
    num_msgs = data.get("num_msgs", '100')
    msgs = chat.msgs_query(username, text, tournId, date_begin, date_end, num_msgs, mod)
    if msgs is None:
        return Response(status=401)
    return msgs


@app.route('/fp/', methods=['GET'])
@app.route('/fp', methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True, allow=Mod.is_alt)
def create_fp(mod):
    return render_template('/fp.html', mod=mod, variants1=variants1, variants2=variants2, view=mod.view, icon="F/")


@app.route('/fp/analyze', methods=['POST'])
@with_mod(update_theme=True, update_seenAt=True, allow=Mod.is_alt)
def analyze_fp(mod):
    try:
        data = request.form
        error = analyze_footprints(mod, data.get("variants"), data.get("player"), data.get("num_games"),
                                   data.get("date_begin"), data.get("date_end"), data.get("rated"), data.get("color"))
    except Exception as exception:
        log_exception(exception)
        return Response(status=400)
    if error:
        return Response(error, status=400)
    return Response(status=204)


@app.route('/fp/cancel', methods=['POST'])
@with_mod(update_seenAt=True, allow=Mod.is_alt)
def cancel_fp(mod):
    cancel_footprints(mod)
    return Response(status=204)


@app.route('/fp/data', methods=['POST'])
@with_mod(update_seenAt=True, allow=Mod.is_alt)
def get_fp_data(mod):
    return get_footprints(mod)


@app.route('/search/', methods=['GET'])
@app.route('/search', methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True, allow=Mod.is_mod)
def create_search(mod):
    return render_template('/search.html', mod=mod, view=mod.view, icon="")


@app.route('/search', methods=['POST'])
@with_mod(update_seenAt=True, allow=Mod.is_mod)
def query_search(mod):
    query = request.form.get("query", None)
    if not query:
        return {'data': [], 'error': 'No query provided'}
    match_type = request.form.get("match_type", "regex")
    return search_users(query, mod, match_type)


@app.route('/mod/close_account', methods=['POST'])
@with_mod(allow=Mod.is_mod)
def close_account_route(mod):
    user = request.form.get("user", None)
    if not is_username(user):
        return {'error': 'No valid user provided'}
    if close_account(user, mod):
        return {'status': 'success'}
    return {'error': 'Failed to close account'}


@app.route('/set_mode/<mode>', methods=['POST'])
@with_mod()
def set_mode(mod, mode):
    mod.view.set_mode(mode)
    return Response(status=204)


def chat_loop():
    global chat
    last_update_count = 0
    while True:
        if chat.wait_refresh_tournaments():
            chat.update_tournaments(non_mod)
        chat.wait_refresh_chats()
        chat.update_chats(room_mod, auto_mod)
        if chat.update_count >= last_update_count + 100:
            last_update_count = chat.update_count
            chat.clear_messages_database()


def encode_base64(b):
    return base64.b64encode(b, altchars=b'-_').replace(b'=', b'')


def get_mod_token(token1, print_exception=False):
    try:
        if not token1 or len(token1) < 5 or len(token1) > 512:
            raise Exception("There's no token stored as a cookie in your browser. Are cookies allowed for this website?")
        token_prefix = token1[:4]
        b_token1 = base64.b64decode(token1[4:], altchars=b'-_')
        hash1 = hashlib.sha224(b_token1).digest()
        token_hash = base64.b64encode(hash1, altchars=b'-_').decode("ascii")
        try:
            mod_db = Mods.get(tokenHash=token_hash)
        except DoesNotExist:
            raise Exception("An unknown token is saved in your browser. <br>Outdated?")
        if not mod_db.enabled or mod_db.expiresAt < datetime.now(tz=tz.tzutc()).replace(tzinfo=None):
            raise Exception("The token saved in your browser has expired.")
        key = mod_db.tokenKey
        b_token2 = key * int(math.ceil(len(b_token1) / 24))
        b_token2 = b_token2[:len(b_token1)]
        b_token = bytes(a ^ b for (a, b) in zip(b_token1, b_token2))
        token = token_prefix + base64.b64encode(b_token, altchars=b'-_').decode("ascii")
        return token, token_hash, mod_db
    except Exception as exception:
        if print_exception:
            log_exception(exception)
        raise Exception(f'Failed to read the token stored in your browser: {exception}')


def save_token(access_token, expires_in):
    token_prefix = access_token[:4]
    token = access_token[4:]
    b_token = base64.b64decode(token, altchars=b'-_')
    key = token_bytes(24)
    b_token2 = key * int(math.ceil(len(b_token) / 24))
    b_token2 = b_token2[:len(b_token)]
    b_token1 = bytes(a ^ b for (a, b) in zip(b_token, b_token2))
    hash1 = hashlib.sha224(b_token1).digest()
    token1 = token_prefix + base64.b64encode(b_token1, altchars=b'-_').decode("ascii")
    # Save cookie
    resp = make_response(redirect('/'))
    now_utc = datetime.now(tz=tz.tzutc())
    expires_date = now_utc + timedelta(seconds=expires_in)
    resp.set_cookie('token', token1, max_age=timedelta(seconds=expires_in), secure=True, httponly=True, samesite='Lax')
    # Save token in the DB
    m = Mod(access_token, check_perms=False, get_public_data=True)
    token_hash = base64.b64encode(hash1, altchars=b'-_').decode("ascii")
    now_utc = now_utc.replace(tzinfo=None)
    expires_date = expires_date.replace(tzinfo=None)
    Mods.create(modId=m.id, tokenKey=key, tokenHash=token_hash, createdAt=now_utc, expiresAt=expires_date, seenAt=now_utc)
    return resp


def get_mod(cookies, update_theme=False, update_seenAt=False, print_exception=False):
    if auto_mod:
        if update_theme:
            auto_mod.update_theme(cookies)
        return auto_mod
    token1 = cookies.get('token')
    now_tz = datetime.now(tz=tz.tzutc()).replace(tzinfo=None)
    mod_info = mod_cache.get(token1)
    if not mod_info or delta_s(now_tz, mod_info.last_updated) > UPDATE_INTERVAL_MOD_PERMS:
        token, current_session, mod_db = get_mod_token(token1, print_exception)
        mod = Mod(token, current_session, mod_db=mod_db)
        if not mod.is_timeout:
            raise Exception(f"@{mod.name} does not have proper permissions.")
        mod_info = ModInfo(mod, now_tz, now_tz)
        mod_cache[token1] = mod_info
    if update_seenAt and delta_s(now_tz, mod_info.last_seenAt) > UPDATE_INTERVAL_MODS_SEEN_AT:
        mod_info.mod.mod_db.seenAt = now_tz
        mod_info.mod.mod_db.save()
    if update_theme:
        mod_info.mod.update_theme(cookies)
    return mod_info.mod


def create_main_page(mod, error_title="", error_text=""):
    view = mod.view if mod else View()
    variant = request.cookies.get('lb_variant', 'bullet')
    resp = make_response(render_template('/main.html', mod=mod, view=view, variant=variant, icon="",
                                         error_title=error_title, error_text=error_text))
    return resp


def get_auth_error(args, error_title):
    error = args.get('error')
    error_description = args.get('error_description')
    if error and error_description:
        return f"{error_title} error: {error}. <br>Info: {error_description}."
    elif error:
        return f"{error_title} error: {error}."
    elif error_description:
        return f"{error_title} error info: {error_description}."
    return ""


@app.route("/", methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True)
def index(mod):
    return create_main_page(mod)


@app.route('/log/<int:lines>/<int:page>', methods=['GET'])
@app.route('/log/<int:lines>/<int:page>/', methods=['GET'])
@app.route('/log/<int:lines>', defaults={'page': 0}, methods=['GET'])
@app.route('/log/<int:lines>/', defaults={'page': 0}, methods=['GET'])
@app.route("/log", defaults={'lines': 100, 'page': 0}, methods=['GET'])
@app.route("/log/", defaults={'lines': 100, 'page': 0}, methods=['GET'])
@with_mod(page=True, update_theme=True, update_seenAt=True)
def log_data(mod, lines, page):
    reverse = request.args.get('reverse', "true").lower() not in ["false", "0"]
    text = log_read(lines, page, reverse) if mod.is_admin else f"Version: {LITOOLS_VERSION[1:]}"
    return render_template('/log.html', view=mod.view, icon="", log=text)


@app.route("/logout", methods=['GET'])
@with_mod(page=True)
def logout(mod):
    try:
        mod.logout()
        token1 = request.cookies.get('token')
        mod_cache.pop(token1, None)
        return make_response(redirect('/login'))
    except Exception as exception:
        log_exception(exception)
        resp = create_main_page(mod, error_title="Logout error", error_text=str(exception))
        return resp


@app.route('/login', methods=['GET'])
def login():
    try:
        now_tz = datetime.now(tz=tz.tzutc()).replace(tzinfo=None)
        verifier = encode_base64(token_bytes(32))  # len(verifier) == 43
        state = encode_base64(token_bytes(16)).decode('ascii')  # len(state) == 22
        challenge = encode_base64(hashlib.sha256(verifier).digest())  # len(challenge) == 43
        verifier = verifier.decode('ascii')
        with Mod.auth_lock:
            query_delete_old_states = Authentication.delete().where(Authentication.expiresAt < now_tz)
            query_delete_old_states.execute()
            Authentication.create(state=state, verifier=verifier, expiresAt=now_tz + timedelta(hours=1))
        params = {'response_type': 'code',
                  'client_id': get_client_id(),
                  'redirect_uri': f'{get_uri()}{AUTH_ENDPOINT}',
                  'scope': 'web:mod note:write',
                  'code_challenge_method': 'S256',
                  'code_challenge': challenge,
                  'state': state}
        session['code_verifier'] = verifier
        session['state'] = state
        resp = make_response(redirect(f'https://lichess.org/oauth?{urlencode(params, quote_via=quote_plus)}'))
    except Exception as exception:
        log_exception(exception)
        mod_none: Mod = None
        resp = create_main_page(mod_none, error_title="Login error", error_text=str(exception))
    return resp


def log_bad_request(info):
    ip = str(request.access_route[0] if len(request.access_route) == 1
             else list(request.access_route) if request.access_route else "-")
    ua = str(request.user_agent)
    al = str(request.accept_languages)
    log(f"ERROR: bad request: {info}: [IP]{ip} [UA]{ua} [Lang]{al}", to_print=False, to_save=True)


@app.route(AUTH_ENDPOINT, methods=['GET'])
def oauth2_callback():
    try:
        error = get_auth_error(request.args, "Authorization")
        state = request.args.get('state') or (session['state'] if 'state' in session else None)
        if error:
            if state and (len(state) != 22 or re_state.sub("", state)):
                log_bad_request("oauth2 error & malformed state='{state}'")
            raise Exception(error)
        if not state:
            raise Exception("Failed to get 'state'.")
        if re_state.sub("", state):
            log_bad_request("malformed state")
            raise Exception(f"Wrongs state='{state}'.")
        if len(state) != 22:
            raise Exception(f"Wrongs state length '{state}'.")
        code = request.args.get('code')
        if not code:
            raise Exception(f"Failed to get 'code' for state='{state}'.")
        if re_state.sub("", code):
            log_bad_request("malformed code")
            raise Exception(f"Wrongs code='{state}'.")
        headers = {'Content-Type': 'application/json', 'User-Agent': get_user_agent()}
        verifier = ""
        with Mod.auth_lock:
            try:
                element = Authentication.get(state=state)
            except DoesNotExist:
                raise Exception(f"The obtained state='{state}' is incorrect.")
            verifier = element.verifier
            element.delete_instance()
        if not verifier:
            raise Exception(f"Failed to load 'verifier' for state='{state}'.")
        data = {'grant_type': 'authorization_code',
                'code': code,
                'code_verifier': verifier,
                'redirect_uri': f'{get_uri()}{AUTH_ENDPOINT}',
                'client_id': get_client_id()}
        r = requests.post(f"https://lichess.org/api/token", headers=headers, json=data)
        if r.status_code != 200:
            try:
                error_info = get_auth_error(r.json(), "Access Token")
                error_info = f" <br>{error_info}"
            except:
                error_info = ""
            raise Exception(f"Failed to get the API token from Lichess.<br>Status code: {r.status_code}.{error_info}")
        res = r.json()
        error = get_auth_error(res, "OAuth2 authorization")
        if error:
            raise Exception(error)
        token_type = res.get('token_type')
        if token_type and token_type != "Bearer":
            raise Exception(f"The obtained token_type='{token_type}'. The expected value: 'Bearer'.")
        access_token = res.get('access_token')
        if not access_token:
            raise Exception(f"Failed to get 'access_token'.")
        if len(access_token) < 5:
            raise Exception(f"The obtained access_token='{access_token}' is incorrect.")
        expires_in = res.get('expires_in')
        if not expires_in:
            raise Exception(f"Failed to get 'expires_in'.")
        resp = save_token(access_token, expires_in)
    except Exception as exception:
        log_exception(exception)
        mod_none: Mod = None
        resp = create_main_page(mod_none, error_title="Authorization error", error_text=str(exception))
    return resp


@app.route('/revoke_token/<token_hash>', methods=['DELETE'])
@with_mod()
def revoke_token(mod, token_hash):
    if not mod.id or not Mod.revoke_token(token_hash, mod.id):
        return Response(status=400)
    for token1, mod_info in list(mod_cache.items()):  # the revoked session must stop working right away
        if mod_info.mod.current_session == token_hash:
            mod_cache.pop(token1, None)
    return Response(status=204)


if __name__ == "__main__":
    log(f"Started: {LITOOLS_VERSION}", to_print=True, to_save=True)
    thread = threading.Thread(name="chat_loop", target=chat_loop)
    thread.start()
    serve(app, host=get_host(), port=get_port(), threads=get_num_threads())
