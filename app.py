from flask import Flask, Response, render_template, request, make_response, session, redirect
from waitress import serve
import logging
import threading
import base64
from secrets import token_bytes
import hashlib
from urllib.parse import urlencode, quote_plus
import requests
from datetime import datetime, timedelta
from dateutil import tz
import math
from peewee import DoesNotExist
from boost import get_boost_data, send_boost_note, send_mod_action
from chat import ChatAnalysis
from alt import Alts
from mod import Mod, ModInfo, View
from elements import get_host, get_port, get_num_threads, get_embed_lichess, get_token, get_uri, delta_s, log, log_exception
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
chat = ChatAnalysis()
auto_mod_token = get_token()
auto_mod = Mod(auto_mod_token) if auto_mod_token else None
non_mod = Mod("")
mod_cache = {}


@app.route('/boost/', methods=['GET', 'POST'])
@app.route('/boost', methods=['GET', 'POST'])
def create_boost():
    try:
        mod = get_mod(request.cookies, update_theme=True, update_seenAt=True)
    except:
        return make_response(redirect('/login'))
    boost_user = request.form.get("user", None) if request.method == 'POST' else None
    resp = make_response(render_template('/boost.html', boost_user=boost_user, embed_lichess=get_embed_lichess(),
                                         mod=mod, view=mod.view, icon="B/"))
    return resp


@app.route('/boost/<user>/', methods=['POST'])
def get_boost_user(user):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    before = request.form.get("before", None)
    num_games = request.form.get("num_games", None)
    perf_type = request.form.get("perf_type", None)
    boost = get_boost_data(user.lower(), mod, num_games, before, perf_type)
    resp = make_response(boost.get_output(mod))
    return resp


@app.route('/boost/<user>/tournaments/', methods=['GET'])
def create_tournaments(user):
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    boost = get_boost_data(user.lower(), mod)
    resp = make_response(boost.get_tournaments(mod))
    return resp


@app.route('/boost/send_note', methods=['POST'])
def boost_send_note():
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    user = request.form.get("user", None)
    note = request.form.get("note", None)
    data = send_boost_note(note, user, mod)
    resp = make_response(data)
    return resp


@app.route('/boost/mod_action', methods=['POST'])
def boost_mod_action():
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    user = request.form.get("user", None)
    action = request.form.get("action", None)
    data = send_mod_action(action, user, mod)
    resp = make_response(data)
    return resp


@app.route('/alt/', methods=['GET', 'POST'])
@app.route('/alt', methods=['GET', 'POST'])
def create_alt():
    try:
        mod = get_mod(request.cookies, update_theme=True, update_seenAt=True)
    except:
        return make_response(redirect('/login'))
    alts = request.form.get("alts", None) if request.method == 'POST' else None
    num_games = request.form.get("num_games", None) if request.method == 'POST' else None
    date_begin = request.form.get("date_begin", None) if request.method == 'POST' else None
    date_end = request.form.get("date_end", None) if request.method == 'POST' else None
    resp = make_response(render_template('/alt.html', embed_lichess=get_embed_lichess(), mod=mod, view=mod.view, icon="A/",
                                         alts=alts, num_games=num_games, date_begin=date_begin, date_end=date_end))
    return resp


@app.route('/alts/<step>/', methods=['POST'])
def get_alts(step):
    try:
        mod = get_mod(request.cookies, update_theme=True)
    except:
        return Response(status=400)
    alt_names = request.form.get("alts", None)
    num_games = request.form.get("num_games", None)
    date_begin = request.form.get("date_begin", None)
    date_end = request.form.get("date_end", None)
    force_refresh_openings = bool(request.form.get("force_refresh_openings", False))
    resp = Alts.get_response(step, alt_names, num_games, date_begin, date_end, force_refresh_openings, mod)
    return make_response(resp)


@app.route('/chat/', methods=['GET'])
@app.route('/chat', methods=['GET'])
def create_chat():
    try:
        mod = get_mod(request.cookies, update_theme=True, update_seenAt=True)
    except:
        return make_response(redirect('/login'))
    resp = make_response(render_template('/chat.html', update_frequency=chat.i_update_frequency,
                                         mod=mod, view=mod.view, icon="C/"))
    return resp


@app.route('/chat/update/<state>', methods=['POST'])
def get_chat_update(state):
    try:
        get_mod(request.cookies)  # can be omitted
    except:
        return Response(status=400)
    resp = make_response(chat.get_tournaments_data(state))
    return resp


@app.route('/chat/process/<state>', methods=['POST'])
def get_chat_process(state):
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    data = chat.get_all_data(mod, state)
    return make_response(data)


@app.route('/chat/set_msg_ok/<msg_id>', methods=['POST'])
def chat_set_msg_ok(msg_id):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    chat.set_msg_ok(msg_id)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/chat/timeout/<msg_id>/<reason>', methods=['POST'])
def chat_timeout(msg_id, reason):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    chat.timeout(msg_id, reason, mod)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/chat/timeout_multi/<msg_id>/<reason>', methods=['POST'])
def chat_timeout_multi(msg_id, reason):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    chat.timeout_multi(msg_id, reason, mod)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/chat/set_multi_msg_ok/<msg_id>', methods=['POST'])
def chat_set_multi_msg_ok(msg_id):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    chat.set_multi_msg_ok(msg_id)
    return '', 204


@app.route('/chat/warn/<username>/<subject>', methods=['POST'])
def chat_warn(username, subject):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    chat.warn(username, subject, mod)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/chat/set_update/<update_frequency>', methods=['POST'])
def chat_set_update(update_frequency):
    try:
        get_mod(request.cookies)  # can be omitted
    except:
        return Response(status=400)
    chat.set_update(update_frequency)
    return '', 204


@app.route('/chat/select_message/<msg_id>', methods=['POST'])
def chat_select_message(msg_id):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    resp = make_response(chat.select_message(msg_id, mod))
    return resp


@app.route('/chat/refresh_selected', methods=['POST'])
def chat_refresh_selected():
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    resp = make_response(chat.refresh_selected(mod, non_mod, auto_mod))
    return resp


@app.route('/chat/clear_errors/<tourn_id>', methods=['POST'])
def chat_clear_errors(tourn_id):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    chat.clear_errors(tourn_id)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/chat/set_tournament/<tourn_id>/<checked>', methods=['POST'])
def chat_set_tournament(tourn_id, checked):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    is_checked = (checked == '1')
    chat.set_tournament(tourn_id, is_checked)
    return Response(status=204)


@app.route('/chat/set_tournament/<tourn_id>', methods=['POST'])
def chat_flip_tournament(tourn_id):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    chat.set_tournament(tourn_id, None)
    return Response(status=204)


@app.route('/chat/delete_tournament/<tourn_id>', methods=['POST'])
def chat_delete_tournament(tourn_id):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    resp = make_response(chat.delete_tournament(tourn_id))
    return resp


@app.route('/chat/set_tournament_group/<group>/<checked>', methods=['POST'])
def chat_set_tournament_group(group, checked):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    is_checked = (checked == '1')
    resp = make_response(chat.set_tournament_group(group, is_checked))
    return resp


@app.route('/chat/set_tournament_group/<group>', methods=['POST'])
def chat_flip_tournament_group(group):
    try:
        get_mod(request.cookies, update_seenAt=True)  # can be omitted
    except:
        return Response(status=400)
    resp = make_response(chat.set_tournament_group(group, None))
    return resp


@app.route('/chat/add_tournament', methods=['POST'])
def chat_add_tournament():
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    page = request.form.get("page", "")
    data = chat.add_tournament(page, non_mod)  # add `, auto_mod` to auto time out after adding a tournament
    data.update(chat.get_all(mod))
    resp = make_response(data)
    return resp


@app.route('/chat/load_more/<tourn_id>', methods=['POST'])
def chat_load_more(tourn_id):
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    resp = make_response(chat.load_more(tourn_id, mod))
    return resp


@app.route('/chat/send_note', methods=['POST'])
def chat_send_note():
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    note = request.form.get("note", None)
    user = request.form.get("user", None)
    data = chat.send_note(note, user, mod)
    #resp = make_response(data)  # needs 'user-info', see chat.send_note() --> workaround:
    all_data = chat.get_all(mod)
    all_data.update(data)
    resp = make_response(all_data)
    return resp


@app.route('/chat/custom_timeout', methods=['POST'])
def custom_timeout():
    try:
        mod = get_mod(request.cookies, update_seenAt=True)
    except:
        return Response(status=400)
    data = request.form.to_dict(flat=False)
    msg_ids = data.get("ids[]", None)
    reason = data.get("reason", 0)
    if isinstance(reason, list):
        reason = reason[0]
    chat.custom_timeout(msg_ids, reason, mod)
    resp = make_response(chat.get_all(mod))
    return resp


@app.route('/set_mode/<mode>', methods=['POST'])
def set_mode(mode):
    try:
        mod = get_mod(request.cookies)
    except:
        return Response(status=400)
    mod.view.set_mode(mode)
    resp = Response(status=204)
    return resp


def chat_loop():
    global chat
    last_update_count = 0
    while True:
        if chat.wait_refresh_tournaments():
            chat.update_tournaments(non_mod)
        chat.wait_refresh_chats()
        chat.update_chats(non_mod, auto_mod)
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
    resp.set_cookie('token', token1, max_age=timedelta(seconds=expires_in), secure=True, httponly=True)
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
    resp = make_response(render_template('/main.html', mod=mod, view=view, icon="",
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
def index():
    try:
        mod = get_mod(request.cookies, update_theme=True, update_seenAt=True)
        resp = create_main_page(mod)
        return resp
    except:
        return make_response(redirect('/login'))


@app.route("/logout", methods=['GET'])
def logout():
    try:
        mod = get_mod(request.cookies)
    except:
        return make_response(redirect('/login'))
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
        verifier = encode_base64(token_bytes(32))
        state = encode_base64(token_bytes(16)).decode('ascii')
        challenge = encode_base64(hashlib.sha256(verifier).digest())
        verifier = verifier.decode('ascii')
        with Mod.auth_lock:
            query_delete_old_states = Authentication.delete().where(Authentication.expiresAt < now_tz)
            query_delete_old_states.execute()
            Authentication.create(state=state, verifier=verifier, expiresAt=now_tz + timedelta(hours=1))
        params = {'response_type': 'code',
                  'client_id': CLIENT_ID,
                  'redirect_uri': f'{get_uri()}{AUTH_ENDPOINT}',
                  'scope': 'web:mod',
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


@app.route(AUTH_ENDPOINT, methods=['GET'])
def oauth2_callback():
    try:
        error = get_auth_error(request.args, "Authorization")
        if error:
            raise Exception(error)
        state = request.args.get('state') or (session['state'] if 'state' in session else None)
        if not state:
            raise Exception("Failed to get 'state'.")
        code = request.args.get('code')
        if not code:
            raise Exception(f"Failed to get 'code' for state='{state}'.")
        headers = {'Content-Type': 'application/json'}
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
                'client_id': CLIENT_ID}
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
def revoke_token(token_hash):
    try:
        get_mod(request.cookies)  # can be omitted
    except:
        return Response(status=400)
    is_deleted = Mod.revoke_token(token_hash)
    if is_deleted:
        return Response(status=204)
    return Response(status=400)


if __name__ == "__main__":
    log(f"Started: {LITOOLS_VERSION}", to_print=True, to_save=True)
    thread = threading.Thread(name="chat_loop", target=chat_loop)
    thread.start()
    serve(app.run(), host=get_host(), port=get_port(), threads=get_num_threads())
