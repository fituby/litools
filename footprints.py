from multiprocessing.dummy import Pool, Manager
from datetime import datetime, timedelta
from dateutil import tz
from functools import partial
from collections import defaultdict
from elements import log, log_exception, get_user, get_user_link
from api import ApiType
import chess
import chess.variant
import chess.polyglot
from typing import Optional
from enum import IntEnum
import html
import json
import os


manager = Manager()
progress = manager.dict()
similarities = manager.dict()

RATING_GROUPS = [0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500, 9999]
RATING_DEVIATION = 400
UNIQUE_MOVE_MAX_FRACTION = 0.10
UNIQUE_MOVE_MAX_COUNT = 70
MAX_NO_MOVES = 2
STD_NUM_SIMILARITIES = 25
MAX_NUM_SIMILARITIES = 100
THRESHOLD_SIMILARITY = 0.01
DEBUG = False


class VariantDesc:
    def __init__(self, var_id, var_name):
        self.id = var_id
        self.name = var_name
        var = "" if var_id in ["ultraBullet", "bullet", "blitz", "rapid", "classical", "correspondence"] else "-variant"
        name = "960" if var_id == "chess960" else var_name.lower().replace(' ', '-')
        self.flair = f'<img src="https://lichess1.org/assets/______0/flair/img/activity.lichess{var}-{name}.webp" ' \
                     f'style="height:50px">'
        self.flair25 = f'<img src="https://lichess1.org/assets/______0/flair/img/activity.lichess{var}-{name}.webp" ' \
                       f'style="height:25px">'
        self.flair_a = f'<a class="d-flex align-items-center" href="/v/{self.id}">' \
                       f'<img src="https://lichess1.org/assets/______0/flair/img/activity.lichess{var}-{name}.webp" ' \
                       f'style="height:20px"><span class="ms-1">{self.name}</span></a>'


variants_desc1 = {
    "ultraBullet":    "UltraBullet",
    "bullet":         "Bullet",
    "blitz":          "Blitz",
    "rapid":          "Rapid",
    "classical":      "Classical",
    "correspondence": "Correspondence",
    "chess960":       "Chess960"
}
variants_desc2 = {
    "crazyhouse":     "Crazyhouse",
    "antichess":      "Antichess",
    "atomic":         "Atomic",
    "horde":          "Horde",
    "kingOfTheHill":  "King of the Hill",
    "racingKings":    "Racing Kings",
    "threeCheck":     "Three-Check"
}
variants1 = {var_id.lower(): VariantDesc(var_id, var_name) for var_id, var_name in variants_desc1.items()}
variants2 = {var_id.lower(): VariantDesc(var_id, var_name) for var_id, var_name in variants_desc2.items()}
variant_ids = list(variants1.keys())
variant_ids.extend(list(variants2.keys()))


class Status(IntEnum):
    STARTING = 1
    RUNNING = 2
    CANCELLED = 3
    FINISHED = 4
    ERROR = 5


class SimilarPlayer:
    def __init__(self, username, score):
        self.username = username
        self.score = score

    def user_id(self):
        return self.username.lower()

    def add_score(self, score):
        self.score += score


class Similarities:
    def __init__(self, username, total_moves, total_games):
        self.username = username
        self.players = {}
        self.lock = manager.Lock()
        self.num_games = defaultdict(int)
        self.num = 0
        self.total_moves = total_moves
        self.total_games = total_games
        self.num_considered_moves = 0
        self.status = Status.STARTING
        self.curr_game = ""
        self.curr_side = chess.WHITE
        self.curr_move = ""
        self.curr_move_num: int = None
        self.errors = []

    def add_num(self, num):
        with self.lock:
            self.num += num

    def add_considered_move(self):
        with self.lock:
            self.num_considered_moves += 1

    def add_game(self, perf):
        with self.lock:
            self.num_games[perf] += 1

    def user_id(self):
        return self.username.lower()

    def info(self):
        with self.lock:
            user_link = get_user_link(self.username, class_a="", max_len=20)
            games = []
            for perf, n in self.num_games.items():
                var_id = perf.lower()
                v = variants1[var_id].name if var_id in variants1 \
                    else variants2[var_id].name if var_id in variants2 \
                    else perf
                games.append(f"{n:,} {v} game{'' if n == 1 else 's'}")
            str_games = f" in {', '.join(games)}" if games else ""
            return f"<b>{user_link}</b>:" \
                   f" {self.num_considered_moves:,} footprint{'' if self.num_considered_moves == 1 else 's'} over" \
                   f" {self.num:,} move{'' if self.num == 1 else 's'}" \
                   f"{str_games}"

    def percent(self):
        with self.lock:
            if self.status not in [Status.STARTING, Status.RUNNING]:
                return -1
            if self.total_moves <= 0:
                return 100
            return round(100 * self.num / self.total_moves)

    def curr_line(self):
        with self.lock:
            if self.status not in [Status.STARTING, Status.RUNNING]:
                return ""
            if not self.curr_game or not self.curr_move or self.curr_move_num is None:
                return ""
            side = "" if self.curr_side == chess.WHITE else "/black"
            game_link = f"https://lichess.org/{self.curr_game}{side}#{self.curr_move_num}"
            return game_link

    def moves_processed(self):
        with self.lock:
            if (self.total_moves == 0) or (self.status not in [Status.STARTING, Status.RUNNING]):
                return "processing"
            return f"{100 * self.num / self.total_moves:.1f}%: {self.num:,} / {self.total_moves:,}"

    def move_progress(self):
        with self.lock:
            if self.num >= self.total_moves:
                return "moves"
            return f"move {self.num + 1:,} of {self.total_moves:,}"

    def game_progress(self):
        with self.lock:
            num_games = sum(self.num_games.values())
            if num_games > self.total_games:
                return "games"
            return f"game {num_games:,} of {self.total_games:,}"

    def add(self, username, score):
        if DEBUG:
            print(f"@{username} +{score:0.3f}")
        user_id = username.lower()
        with self.lock:
            if user_id in self.players:
                self.players[user_id].add_score(score)
            else:
                self.players[user_id] = SimilarPlayer(username, score)

    def print_result(self, num_considered_moves):
        with self.lock:
            self.players = {pid: p for pid, p in sorted(self.players.items(), key=lambda item: item[1].score, reverse=True)}
            i = 1
            for p in self.players.values():
                similarity = p.score / max(1, num_considered_moves)
                print(f"{i: 2d}: {p.score: 3.0f} / {min(100, similarity * 100): 3.0f} -- {p.username}")
                i += 1
                if i > MAX_NUM_SIMILARITIES or (similarity < THRESHOLD_SIMILARITY and i > STD_NUM_SIMILARITIES):
                    break

    def get_result(self, num_considered_moves):
        data = []
        with self.lock:
            self.players = {pid: p for pid, p in sorted(self.players.items(), key=lambda item: item[1].score, reverse=True)}
            i = 1
            for p in self.players.values():
                similarity = p.score / max(1, num_considered_moves)
                data.append({'username': p.username, 'score': round(min(100.0, similarity * 100), 1)})
                i += 1
                if i > MAX_NUM_SIMILARITIES or (similarity < THRESHOLD_SIMILARITY and i > STD_NUM_SIMILARITIES):
                    break
        return data

    def add_error(self, error):
        self.errors.append(error)
        log(f"FP: {error}")

    def add_exception(self, exception, title):
        error = f"{title}: {str(exception)}"
        self.errors.append(error)
        log_exception(f"FP: {error}", to_print=False)

    def get_errors(self):
        errors = []
        if self.status == Status.ERROR:
            errors.append("FAILED")
        errors.extend(self.errors)
        return html.unescape(" | ".join(errors))


def set_progress(mod_id, status):
    similarities[mod_id].status = status


def check_opening_game(game, username):
    NOPE = 0, None
    player_white = read_player(game, 'white')
    player_black = read_player(game, 'black')
    color = 'white' if player_white['user']['id'] == username.lower() else \
            'black' if player_black['user']['id'] == username.lower() else None
    if color is None:
        return NOPE
    is_white = color == 'white'
    num_moves = len(game.get('moves', "").split())
    num_moves = (num_moves + 1) // 2 if color == 'white' else num_moves // 2 if color == 'black' else 0
    return num_moves, is_white


def filter_opening_games(all_games, username):
    games = []
    total_num_moves = 0
    num_games = 0
    for game in all_games:
        if num_games < 50_000:
            num_moves, is_white = check_opening_game(game, username)
            if num_moves == 0:
                continue
        else:
            break
        num_games += 1
        total_num_moves += num_moves
        games.append(game)
    return games, total_num_moves


def get_zobrist(board):
    zobrist = chess.polyglot.zobrist_hash(board)
    if zobrist >= 2**63:
        return zobrist - 2**64
    return zobrist


def get_chess_variant(variant):
    return "chess" if variant == "standard" else variant


def read_player(game, color):
    player = game['players'][color]
    if player:
        if 'user' in player:
            return player
        if 'aiLevel' in player:
            name = f"aiLevel{player['aiLevel']}"
            return {'user': {'id': name.lower(), 'name': name, 'title': "AI"},
                    'rating': player.get('rating', "?")}
    return {'user': {'id': "anonymous", 'name': "Anonymous"},
            'rating': player.get('rating', "?") if player else "?"}


class AntichessBoard(chess.variant.AntichessBoard):
    aliases = ["Antichess", "Anti chess", "Anti"]
    uci_variant = "antichess"  # Unofficial
    starting_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1"

    def __init__(self, fen: Optional[str] = starting_fen, chess960: bool = False) -> None:
        super().__init__(fen, chess960=chess960)

    def is_stalemate(self) -> bool:
        if not all(has_pieces for has_pieces in self.occupied_co):
            return False
        return not any(self.generate_legal_moves())

    # def is_variant_end(self) -> bool:
    #     return (not all(has_pieces for has_pieces in self.occupied_co)) or self.is_stalemate() --> recursion!

    def is_variant_win(self) -> bool:
        return (not self.occupied_co[self.turn]) or self.is_stalemate()

    def is_variant_loss(self) -> bool:
        return not self.occupied_co[chess.BLACK if self.turn == chess.WHITE else chess.WHITE]

    def is_variant_draw(self) -> bool:
        return False


def get_board(chess_variant, fen_960=""):
    if fen_960:
        fen_960 = fen_960.strip().split()[0]
    board = AntichessBoard() if chess_variant == "antichess" \
        else chess.variant.AtomicBoard() if chess_variant == "atomic" \
        else chess.variant.HordeBoard() if chess_variant == "horde" \
        else chess.variant.RacingKingsBoard() if chess_variant == "racingKings" \
        else chess.variant.ThreeCheckBoard() if chess_variant == "threeCheck" \
        else chess.variant.KingOfTheHillBoard() if chess_variant == "kingOfTheHill" \
        else chess.variant.CrazyhouseBoard() if chess_variant == "crazyhouse" \
        else chess.BaseBoard(board_fen=fen_960) if chess_variant == "chess960" \
        else chess.Board()
    if chess_variant == "chess960":
        pos = board.chess960_pos()
        board = chess.Board.from_chess960_pos(pos)
    return board


def download_games(mod, variants, username, num_games, date_begin, date_end, rated, color):
    params = {
        'perfType': variants,
        'finished': "true",
        'moves': "true",
        'clocks': "true"
    }
    if num_games > 0:
        params['max'] = num_games
    now = datetime.now(tz=tz.tzutc())
    if date_end:
        until = datetime.strptime(date_end, '%Y-%m-%d').replace(tzinfo=tz.tzutc())
        if until > now:
            until = now
    else:
        until = None
    since = datetime.strptime(date_begin, '%Y-%m-%d').replace(tzinfo=tz.tzutc()) if date_begin else None
    if until is None and (since is None or now - since < timedelta(days=182)):
        until = now
    if until is not None:
        until = until.replace(hour=23, minute=59, second=59)
    if since is not None:
        params['since'] = int(since.timestamp() * 1000)
    if until is not None:
        params['until'] = int(until.timestamp() * 1000)
    if rated == 1:
        params['rated'] = "true"
    elif rated == 2:
        params['rated'] = "false"
    if color == 1:
        params['color'] = "white"
    elif color == 2:
        params['color'] = "black"
    url = f"https://lichess.org/api/games/user/{username}"
    games = mod.api.get_ndjson(ApiType.ApiGamesUser, url, mod.token, params=params)
    if not games:
        raise Exception("No games")
    return games


def analyze_footprints(mod, variants, username, num_games, date_begin, date_end, rated, color):
    try:
        if not variants:
            raise Exception("No variant specified")
        var_list = variants.split(",")
        for var in var_list:
            if var not in variant_ids:
                raise Exception("Wrong variant specified")
        if not isinstance(username, str):
            raise Exception("Wrong username")
        if not username:
            raise Exception("No username")
        if len(username) > 20:
            raise Exception("Username is too long")
        num_games = int(num_games)
        if num_games < 1:
            raise Exception("Wrong num games")
        if num_games > 500:
            num_games = 500
        rated = int(rated)
        if rated < 0 or rated > 2:
            raise Exception("Wrong 'rated' option")
        color = int(color)
        if color < 0 or color > 2:
            raise Exception("Wrong 'color' option")
        user_data, api_error = get_user(username, mod)
        if api_error or not user_data:
            raise Exception(api_error)
        username = user_data.get('username', username)
        games = download_games(mod, variants, username, num_games, date_begin, date_end, rated, color)
        all_games, total_num_moves = filter_opening_games(games, username)
        add_opening_task(mod, username, all_games, total_num_moves,
                         partial(task_completed, mod.id), partial(task_failed, mod.id))
    except Exception as e:
        log_exception("analyze_footprints", to_print=False)
        return str(e)
    return None


def cancel_footprints(mod):
    sim = similarities.get(mod.id)
    if sim:
        sim.status = Status.CANCELLED


def get_footprints(mod):
    sim = similarities.get(mod.id)
    if sim:
        data = {
            'status': int(sim.status),
            'progress': sim.percent(),
            'game_progress': sim.game_progress(),
            'moves_processed': sim.moves_processed(),
            'info': sim.info(),
            'res': sim.get_result(sim.num_considered_moves)
        }
        if sim.errors:
            data['error'] = sim.get_errors()
    else:
        data = {
            'status': 0,
            'progress': -1,
            'game_progress': "",
            'moves_processed': "",
            'info': "",
            'res': []
        }
    return data


def task_completed(mod_id, result):
    if similarities[mod_id].status == Status.RUNNING:
        set_progress(mod_id, Status.FINISHED)
    elif similarities[mod_id].status == Status.ERROR:
        task_failed(mod_id, "Exception")


def task_failed(mod_id, error):
    username = "Unknown user"
    if mod_id in similarities:
        username = similarities[mod_id].username
    log(f"ERROR: Failed task for {username}: {error}")
    set_progress(mod_id, Status.ERROR)


def add_opening_task(mod, username, games, num_moves, task_completed, task_failed):
    existing = similarities.get(mod.id)
    if existing and existing.status in [Status.STARTING, Status.RUNNING]:
        return
    similarities[mod.id] = Similarities(username, num_moves, len(games))
    opening_cache = set()
    process_args = [
        {
            'mod':                mod,
            'game':               game,
            'player_of_interest': username,
            'similarities':       similarities[mod.id],
            'opening_cache':      opening_cache
        } for game in games
    ]
    pool = Pool(1)
    pool.map_async(process_game, process_args, callback=task_completed, error_callback=task_failed)
    #pool.map(process_game, process_args)
    #print(similarities[mod.id].get_result(progress[mod.id].num_considered_moves))


def process_game(args):
    global last_request
    sim: Similarities = None
    try:
        mod = args['mod']
        g = args['game']
        username = args['player_of_interest']
        sim = args['similarities']
        opening_cache: set = args['opening_cache']
        chess_variant = get_chess_variant(g['variant'])
        pid = username.lower()

        if sim.status == Status.STARTING:
            sim.status = Status.RUNNING
        elif sim.status != Status.RUNNING:
            return
    except Exception as e:
        try:
            if sim:
                sim.add_exception(e, f"init game analysis: {g['id']}")
            else:
                log_exception(f"init game analysis: {g['id']}")
        except:
            log_exception("init game analysis")
        return

    try:
        fen = g.get('initialFen')
        board = get_board(chess_variant, fen)
        if fen and chess_variant != "chess960":
            board.set_fen(fen)

        player_white = read_player(g, 'white')
        player_black = read_player(g, 'black')
        if player_white and ('user' in player_white) and player_white['user']['id'] == pid:
            turn = chess.WHITE
            rating = player_white.get('rating', "?")
        elif player_black and ('user' in player_black) and player_black['user']['id'] == pid:
            turn = chess.BLACK
            rating = player_black.get('rating', "?")
        else:
            sim.add_error(f"WARNING: Unknown player {username}: {g['id']}")
            return

        ratings = []
        if rating != "?":
            try:
                rating = int(rating)
                for i in range(1, len(RATING_GROUPS)):
                    if RATING_GROUPS[i - 1] - RATING_DEVIATION <= rating <= RATING_GROUPS[i] + RATING_DEVIATION:
                        ratings.append(str(RATING_GROUPS[i - 1]))
            except:
                ratings = []
                sim.add_error(f"WARNING: Unknown rating {rating}: {g['id']}")

        sim.add_game(g.get('perf', "Unknown"))
        moves = g["moves"].split()
        no_moves = 0
        uniqueness = 0
        num_skipped_moves = (len(moves) + 1) // 2 if turn == chess.WHITE else len(moves) // 2 if turn == chess.BLACK else 0
        for i_move in range(len(moves)):
            if sim.status != Status.RUNNING:
                return
            if board.turn == turn:
                sim.add_num(1)
                num_skipped_moves -= 1

            played_move = moves[i_move]
            if i_move != 0:
                board.push_san(moves[i_move - 1])
            legal_moves = list(board.legal_moves)
            if board.turn != turn and uniqueness == 0:
                continue
            score = uniqueness
            uniqueness = 0
            if board.turn == turn and len(legal_moves) <= 1:
                continue
            zobrist = get_zobrist(board)
            if zobrist in opening_cache:
                continue

            fen_i = board.fen()
            params = {
                'variant': "standard" if chess_variant == "chess" else chess_variant,
                'recentGames': 10,  # max: 4
                'topGames': 10,     # max: 4
                'fen': fen_i
            }
            if ratings:
                params['ratings'] = ",".join(ratings)
            cached_file = f"data\\{chess_variant}_{fen_i.replace('/', '_')}_{params.get('ratings', '')}.json"
            if DEBUG and os.path.exists(cached_file):
                with open(cached_file) as f:
                    d = json.load(f)
            else:
                url = "https://explorer.lichess.ovh/lichess"
                r = mod.api.get(ApiType.ApiUser, url, token=mod.token, params=params, allow_redirects=True)
                if r.status_code != 200:
                    msg = f"status {r.status_code}"
                    raise Exception(msg)
                d = r.json()
                if DEBUG:
                    with open(cached_file, 'w') as f:
                        json.dump(d, f, ensure_ascii=False)
            d_moves = d['moves']
            if board.turn == turn:
                opening_cache.add(zobrist)
            num_replies = d['white'] + d['black'] + d['draws']
            if num_replies <= 1 or not d_moves:
                if board.turn == turn:
                    no_moves += 1
                    if no_moves > MAX_NO_MOVES:
                        break
                continue

            if board.turn == turn:
                num_played = 0
                for m in d_moves:
                    if m['san'] != played_move:
                        continue
                    num_played = m['white'] + m['black'] + m['draws']
                    break
                if num_played / num_replies <= UNIQUE_MOVE_MAX_FRACTION or num_played <= UNIQUE_MOVE_MAX_COUNT:
                    uniqueness = min(10.0, num_replies / max(1, num_played) * max(1, min(4, 10 - num_played)))
                    if DEBUG:
                        print(f"U = {uniqueness:.1f}")
            else:
                color = 'white' if turn == chess.WHITE else 'black'
                game_ids = set()
                players = {pid: SimilarPlayer(username, 0)}
                num_alt_games = 0
                for category in ['topGames', 'recentGames']:
                    for gg in d[category]:
                        if gg['id'] in game_ids:
                            continue
                        game_ids.add(gg['id'])
                        player_name = gg[color]['name']
                        player_id = player_name.lower()
                        if player_id in players:
                            players[player_id].score += 1
                        else:
                            players[player_id] = SimilarPlayer(player_name, 1)
                        if player_id != pid:
                            num_alt_games += 1
                if num_alt_games == 0:
                    continue
                if players[pid].score == 0:
                    if num_replies <= num_alt_games:
                        #log.warning(f"no poi: {g['id']} {i_move // 2 + 1}.{played_move}")
                        #continue
                        num_replies += 1
                    players[pid].score = 1
                if num_replies < players[pid].score + num_alt_games:
                    raise Exception(f"num_replies={num_replies} < {players[pid].score} + {num_alt_games}")
                total_num_alt_games = num_replies - players[pid].score
                if total_num_alt_games == 0:
                    continue
                if total_num_alt_games < 0:
                    raise Exception(f"total_num_alt_games={total_num_alt_games}")
                if total_num_alt_games < num_alt_games:
                    raise Exception(f"total_num_alt_games={total_num_alt_games} < {num_alt_games}")
                num_unknown_games = num_replies - len(game_ids)
                if num_unknown_games > total_num_alt_games:
                    raise Exception(f"num_unknown_games={num_unknown_games} > {total_num_alt_games}")
                sim.add_considered_move()
                #score *= max(0.1, 1 - num_unknown_games / total_num_alt_games)
                #score *= max(0.1, min(1.0, (110 - num_replies) / 100))
                for p, sp in players.items():
                    if p != pid:
                        sim.add(sp.username, score * max(0.1, sp.score / total_num_alt_games))
        sim.add_num(num_skipped_moves)
    except Exception as e:
        sim.status = Status.ERROR
        try:
            sim.add_exception(e, f"processing: {g['id']} {i_move // 2 + 1}.{played_move}")
        except:
            sim.add_exception(e, "processing")
