from flask import Flask, Response, render_template, request, make_response
from waitress import serve
import logging
import traceback
from boost import get_boost_data
from chat import ChatAnalysis
from elements import get_port
from enum import IntEnum


class Mode(IntEnum):
    AutoLight = -2
    AutoDark = -1
    Dark = 1
    Light = 2


class View:
    def __init__(self, icon_folder="", mode=Mode.AutoDark):
        self.icon_folder = icon_folder
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
            traceback.print_exception(type(exception), exception, exception.__traceback__)
            self.mode = int(Mode.AutoDark)
        except:
            self.mode = int(Mode.AutoDark)
        self.theme = "flatly" if self.mode in [Mode.Light, Mode.AutoLight] else "darkly"
        self.theme_color = "#ffffff" if self.mode in [Mode.Light, Mode.AutoLight] else "#222222"


logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('werkzeug')
logger.setLevel(logging.ERROR)
# if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
#     # template_folder = os.path.join(sys._MEIPASS, 'templates')
#     # static_folder = os.path.join(sys._MEIPASS, 'static')
#     app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/")
# else:
app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/")
view_boost = View("B/")
view_chat = View("C/")
chat = ChatAnalysis()


def update_boost_theme():
    global view_boost
    mode = request.cookies.get('theme_mode', '-1')
    view_boost.set_mode(mode)


@app.route('/boost/', methods=['GET', 'POST'])
@app.route('/boost', methods=['GET', 'POST'])
def create_boost():
    update_boost_theme()
    boost_user = request.form.get("user", None) if request.method == 'POST' else None
    resp = make_response(render_template('/boost.html', boost_user=boost_user, view=view_boost))
    return resp


@app.route('/boost/<user>/', methods=['POST'])
def get_boost_user(user):
    boost = get_boost_data(user.lower())
    resp = make_response(render_template('/boost_get_user.html', boost=boost, view=view_boost))
    return resp


@app.route('/boost/<user>/tournaments/', methods=['GET'])
def create_tournaments(user):
    boost = get_boost_data(user.lower())
    boost.analyse_tournaments()
    resp = make_response(boost.get_tournaments())
    return resp


@app.route('/chat/', methods=['GET'])
@app.route('/chat', methods=['GET'])
def create_chat():
    global view_chat
    mode = request.cookies.get('theme_mode', '-1')
    view_chat.set_mode(mode)
    resp = make_response(render_template('/chat.html', update_frequency=chat.i_update_frequency, view=view_chat))
    return resp


@app.route('/chat/update/', methods=['POST'])
def get_chat_update():
    chat.update_tournaments()
    resp = make_response(chat.get_tournaments())
    return resp


@app.route('/chat/process/', methods=['POST'])
def get_chat_process():
    chat.run()
    data = chat.get_all()
    return make_response(data)


@app.route('/chat/set_msg_ok/<msg_id>', methods=['POST'])
def chat_set_msg_ok(msg_id):
    chat.set_msg_ok(msg_id)
    resp = make_response(chat.get_all())
    return resp


@app.route('/chat/timeout/<msg_id>/<reason>', methods=['POST'])
def chat_timeout(msg_id, reason):
    chat.timeout(msg_id, reason)
    resp = make_response(chat.get_all())
    return resp


@app.route('/chat/timeout_multi/<msg_id>/<reason>', methods=['POST'])
def chat_timeout_multi(msg_id, reason):
    chat.timeout_multi(msg_id, reason)
    resp = make_response(chat.get_all())
    return resp


@app.route('/chat/set_multi_msg_ok/<msg_id>', methods=['POST'])
def chat_set_multi_msg_ok(msg_id):
    chat.set_multi_msg_ok(msg_id)
    return '', 204


@app.route('/chat/set_update/<update_frequency>', methods=['POST'])
def chat_set_update(update_frequency):
    chat.set_update(update_frequency)
    return '', 204


@app.route('/chat/select_message/<msg_id>', methods=['POST'])
def chat_select_message(msg_id):
    resp = make_response(chat.select_message(msg_id))
    return resp


@app.route('/chat/set_tournament/<tourn_id>/<checked>', methods=['POST'])
def chat_set_tournament(tourn_id, checked):
    is_checked = (checked == '1')
    chat.set_tournament(tourn_id, is_checked)
    return '', 204


@app.route('/chat/set_tournament/<tourn_id>', methods=['POST'])
def chat_flip_tournament(tourn_id):
    chat.set_tournament(tourn_id, None)
    return '', 204


@app.route('/chat/set_tournament_group/<group>/<checked>', methods=['POST'])
def chat_set_tournament_group(group, checked):
    is_checked = (checked == '1')
    resp = make_response(chat.set_tournament_group(group, is_checked))
    return resp


@app.route('/chat/set_tournament_group/<group>', methods=['POST'])
def chat_flip_tournament_group(group):
    resp = make_response(chat.set_tournament_group(group, None))
    return resp


@app.route('/chat/add_tournament', methods=['POST'])
def chat_add_tournament():
    page = request.form.get("page", "")
    resp = make_response(chat.add_tournament(page))
    return resp


@app.route('/set_mode/<mode>', methods=['POST'])
def set_mode(mode):
    global view_chat, view_leaderboard, view_boost
    view_chat.set_mode(mode)
    view_boost.set_mode(mode)
    resp = Response(status=204)
    return resp


if __name__ == "__main__":
    serve(app.run(), host="127.0.0.1", port=get_port(), threads=2)