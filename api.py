import requests
import json
from collections import defaultdict
import time
from datetime import datetime
from dateutil import tz
from threading import Lock
from consts import API_TOURNEY_PAGE_DELAY


class Endpoint:
    def __init__(self, name, delay=1.0, num_requests=1):
        self.name = name
        self.delay = delay
        self.num_requests = num_requests
        self.lock = Lock()


class ApiType:
    # Get
    ApiAccount = Endpoint('api/account')
    ApiUser = Endpoint('api/user')
    ApiUserNote = Endpoint('api/user/note')
    ApiUserModLog = Endpoint('api/user/mod-log')
    ApiUsersStatus = Endpoint('api/users/status')
    ReportListBoost = Endpoint('report/list/boost')
    ApiTeamOf = Endpoint('api/team/of')
    AtUsernameFollowing = Endpoint('@/username/following')
    ApiTournamentId = Endpoint('api/tournament/id')
    ApiSwiss = Endpoint('api/swiss')
    ApiTournament = Endpoint('api/tournament')
    TournamentId = Endpoint('tournament', API_TOURNEY_PAGE_DELAY)
    #SwissId = Endpoint('swiss')
    #BroadcastId = Endpoint('broadcast')
    PlayerTop = Endpoint('player/top')
    # Get ndjson
    ApiGamesUser = Endpoint('api/games/user')
    ApiTeamArena = Endpoint('api/team/arena')
    ApiTeamSwiss = Endpoint('api/team/swiss')
    ApiBroadcast = Endpoint('api/broadcast')
    ApiTournamentResults = Endpoint('api/tournament/results')
    ApiSwissResults = Endpoint('api/swiss/results')
    # Post
    ApiUserNote_Post = Endpoint('api/user/note:post')
    ApiWarn = Endpoint('api/warn')
    ApiBooster = Endpoint('api/booster')
    InsightsRefresh = Endpoint('insights/refresh', 60, 4)
    InsightsData = Endpoint('insights/data')
    ModPublicChatTimeout = Endpoint('mod/public-chat/timeout')
    ModWarn = Endpoint('mod/warn')
    ModKid = Endpoint('mod/kid')
    ModTroll = Endpoint('mod/troll')
    ApiUsers = Endpoint('api/users')
    # Delete
    ApiToken_Delete = Endpoint('api/token:delete')


class Api:
    ndjson_lock = Lock()
    verbose = 0  # 0, 1, 2

    def __init__(self):
        self.api_times = defaultdict(list)

    def wait(self, api: Endpoint):
        wait_s = 0
        if len(self.api_times[api.name]) >= api.num_requests:
            now = datetime.now()
            wait_s = api.delay - (now - self.api_times[api.name][-api.num_requests]).total_seconds()
        if wait_s > 0:
            if Api.verbose >= 2:
                print(f'Waiting for "{api.name}" for {wait_s:0.1f}s')
            time.sleep(wait_s)
        self.finish(api)  # or after it's completed?

    def finish(self, api: Endpoint):
        self.api_times[api.name].append(datetime.now())
        if len(self.api_times[api.name]) > api.num_requests:
            self.api_times[api.name] = self.api_times[api.name][-api.num_requests:]

    def get_waiting_time(self, api: Endpoint):
        now = datetime.now()
        if len(self.api_times[api.name]) >= api.num_requests:
            return api.delay - (now - self.api_times[api.name][-api.num_requests]).total_seconds()
        return 0

    def prepare(self, api: Endpoint, url, token, tag, **kwargs):
        if Api.verbose:
            print(f"request {datetime.now(tz=tz.tzutc()):%H:%M:%S.%f}: {tag} {url}")
        self.wait(api)
        if token is None:
            headers = kwargs.pop('headers', None)
        else:
            headers = kwargs.pop('headers', {}).copy()
            headers['Authorization'] = f"Bearer {token}"
        return headers

    def get(self, api: Endpoint, url, token=None, **kwargs):
        with api.lock:
            headers = self.prepare(api, url, token, "GET", **kwargs)
            kwargs.pop('headers', None)
            r = requests.get(url, headers=headers, **kwargs)
            if r.status_code == 429:
                print(f"ERROR: Status 429: {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M:%S.%f} GET: {url}")
                time.sleep(60)
        return r

    def post(self, api: Endpoint, url, token=None, **kwargs):
        with api.lock:
            headers = self.prepare(api, url, token, "POST", **kwargs)
            kwargs.pop('headers', None)
            r = requests.post(url, headers=headers, **kwargs)
            if r.status_code == 429:
                print(f"ERROR: Status 429: {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M:%S.%f} POST: {url}")
                time.sleep(60)
        return r

    def delete(self, api: Endpoint, url, token=None, **kwargs):
        with api.lock:
            headers = self.prepare(api, url, token, "DELETE", **kwargs)
            kwargs.pop('headers', None)
            r = requests.delete(url, headers=headers, **kwargs)
            if r.status_code == 429:
                print(f"ERROR: Status 429: {datetime.now(tz=tz.tzutc()):%Y-%m-%d %H:%M:%S.%f} DELETE: {url}")
                time.sleep(60)
        return r

    def get_ndjson(self, api, url, token, Accept="application/x-ndjson"):
        if Api.verbose:
            print(f"request {datetime.now(tz=tz.tzutc()):%H:%M:%S.%f}: {url}")
        with api.lock:
            self.wait(api)
            headers = {'Accept': Accept,
                       'Authorization': f"Bearer {token}"}
            with Api.ndjson_lock:
                r = requests.get(url, allow_redirects=True, headers=headers)
                if r.status_code == 429:
                    if Api.verbose:
                        print(f"ERROR: Status 429: waiting 60s... {datetime.now():%H:%M:%S.%f} {url}")
                    time.sleep(60)
        if Api.verbose >= 2:
            print(f"finish {datetime.now(tz=tz.tzutc()):%H:%M:%S.%f}: {url}")
        if r.status_code != 200:
            try:
                i1 = url.find(".org/")
                i2 = url.rfind("/")
                endpoint = url[i1 + 4:i2 + 1]
            except:
                endpoint = url
            raise Exception(f"{endpoint}: Status code = {r.status_code}")
        content = r.content.decode("utf-8")
        lines = content.split("\n")[:-1]
        data = [json.loads(line) for line in lines]
        return data
