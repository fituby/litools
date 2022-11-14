from datetime import datetime
import time
from collections import defaultdict
import requests
import traceback
from elements import delta_s, decode_string, read_notes
from consts import BOOST_RING_TOOL


class Mod:
    def __init__(self, token):
        self.token = token
        self.api_times = defaultdict(list)
        self.alt_cache = {}
        self.refresh_openings_times = {}
        self.boost_cache = {}
        self.boost_ring_tool = decode_string(BOOST_RING_TOOL, self)  # returns "" (not None) if not available
        self.is_admin = self.check_admin()
        self.to_read_mod_log = self.is_mod()
        self.to_read_notes = self.is_mod()
        self.last_mod_log_error = None
        self.last_notes_error = None
        self.id, self.name = self.get_public_data()

    def wait_api(self, api_type, delay=1.0, num_requests=1):
        now = datetime.now()
        wait_s = 0
        if len(self.api_times[api_type]) >= num_requests:
            wait_s = delay - delta_s(now, self.api_times[api_type][-num_requests])
        self.api_times[api_type].append(now)
        if len(self.api_times[api_type]) > num_requests:
            self.api_times[api_type] = self.api_times[api_type][-num_requests:]
        if wait_s > 0:
            #print(f'Waiting for "{api_type}" for {wait_s:0.1f}s')
            time.sleep(wait_s)

    def get_waiting_api_time(self, api_type, delay, num_requests):
        now = datetime.now()
        if len(self.api_times[api_type]) >= num_requests:
            return delay - delta_s(now, self.api_times[api_type][-num_requests])
        return 0

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
            self.wait_api('api/account')
            headers = {'Authorization': f"Bearer {self.token}"}
            url = "https://lichess.org/api/account"
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data['id'], data['username']
        except Exception as exception:
            traceback.print_exception(type(exception), exception, exception.__traceback__)
        return "", ""
