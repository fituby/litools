from datetime import datetime, timedelta
from dateutil import tz
from dateutil.relativedelta import relativedelta
from enum import IntEnum, Enum, IntFlag
import traceback
import os
import html
import re
import hashlib
import math
import base64
import struct
from itertools import chain
from pygal.style import DarkStyle
from api import ApiType
from consts import *


refresh_insights_times = {}

STYLE_WORD_BREAK = "word-break:break-word;"  # "word-break:break-all;"
re_link = re.compile(r'\bhttps?:\/\/(?:www\.)?[-_a-zA-Z0-9]*\.?lichess\.(?:ovh|org)\/[-a-zA-Z0-9@:%&\?\$\.,_\+~#=\/]+\b', re.IGNORECASE)
url_symbols = "abcdefghijklmnopqrstuvwxyz1234567890/?@&=$-_.+!,()'*{}^~[]#%<>; "

country_names = {'GB-WLS': 'Wales󠁧󠁢󠁷󠁬󠁳󠁿', 'GB-SCT': 'Scotland󠁢󠁳󠁣󠁴󠁿󠁧󠁢󠁷󠁬󠁳󠁿',
         'GB-ENG': 'England󠁢󠁥󠁮󠁧󠁿', 'GB-NIR': 'Northern Ireland󠁢󠁥󠁮󠁧󠁿',
         "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AG": "Antigua and Barbuda",
         "AI": "Anguilla", "AL": "Albania", "AM": "Armenia", "AN": "Netherlands Antilles", "AO": "Angola", "AQ": "Antarctica",
         "AR": "Argentina", "AS": "American Samoa", "AT": "Austria", "AU": "Australia", "AW": "Aruba",
         "AX": "Åland Islands", "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BB": "Barbados",
         "BD": "Bangladesh", "BE": "Belgium", "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Bahrain",
         "BI": "Burundi", "BJ": "Benin", "BL": "Saint Barthélemy", "BM": "Bermuda", "BN": "Brunei Darussalam",
         "BO": "Bolivia", "BQ": "Bonaire, Sint Eustatius and Saba", "BR": "Brazil", "BS": "Bahamas",
         "BT": "Bhutan", "BV": "Bouvet Island", "BW": "Botswana", "BY": "Belarus", "BZ": "Belize",
         "CA": "Canada", "CC": "Cocos (Keeling) Islands", "CD": "Congo", "CF": "Central African Republic",
         "CG": "Congo", "CH": "Switzerland", "CI": "Côte D'Ivoire", "CK": "Cook Islands", "CL": "Chile",
         "CM": "Cameroon", "CN": "China", "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba",
         "CV": "Cape Verde", "CW": "Curaçao", "CX": "Christmas Island", "CY": "Cyprus", "CZ": "Czech Republic",
         "DE": "Germany", "DJ": "Djibouti", "DK": "Denmark", "DM": "Dominica", "DO": "Dominican Republic",
         "DZ": "Algeria", "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "EH": "Western Sahara",
         "ER": "Eritrea", "ES": "Spain", "ES-CT": "Catalonia", "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji",
         "FK": "Falkland Islands (Malvinas)", "FM": "Micronesia", "FO": "Faroe Islands", "FR": "France",
         "GA": "Gabon", "GB": "United Kingdom", "GD": "Grenada", "GE": "Georgia", "GF": "French Guiana",
         "GG": "Guernsey", "GH": "Ghana", "GI": "Gibraltar", "GL": "Greenland", "GM": "Gambia", "GN": "Guinea",
         "GP": "Guadeloupe", "GQ": "Equatorial Guinea", "GR": "Greece", "GS": "South Georgia",
         "GT": "Guatemala", "GU": "Guam", "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong Kong",
         "HM": "Heard Island and Mcdonald Islands", "HN": "Honduras", "HR": "Croatia", "HT": "Haiti",
         "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IM": "Isle of Man",
         "IN": "India", "IO": "British Indian Ocean Territory", "IQ": "Iraq", "IR": "Iran", "IS": "Iceland",
         "IT": "Italy", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordan", "JP": "Japan", "KE": "Kenya",
         "KG": "Kyrgyzstan", "KH": "Cambodia", "KI": "Kiribati", "KM": "Comoros", "KN": "Saint Kitts and Nevis",
         "KP": "North Korea", "KR": "South Korea", "KW": "Kuwait", "KY": "Cayman Islands", "KZ": "Kazakhstan",
         "LA": "Lao People's Democratic Republic", "LB": "Lebanon", "LC": "Saint Lucia", "LI": "Liechtenstein",
         "LK": "Sri Lanka", "LR": "Liberia", "LS": "Lesotho", "LT": "Lithuania", "LU": "Luxembourg",
         "LV": "Latvia", "LY": "Libya", "MA": "Morocco", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro",
         "MF": "Saint Martin (French Part)", "MG": "Madagascar", "MH": "Marshall Islands", "MK": "Macedonia",
         "ML": "Mali", "MM": "Myanmar", "MN": "Mongolia", "MO": "Macao", "MP": "Northern Mariana Islands",
         "MQ": "Martinique", "MR": "Mauritania", "MS": "Montserrat", "MT": "Malta", "MU": "Mauritius",
         "MV": "Maldives", "MW": "Malawi", "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique",
         "NA": "Namibia", "NC": "New Caledonia", "NE": "Niger", "NF": "Norfolk Island", "NG": "Nigeria",
         "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NR": "Nauru", "NU": "Niue",
         "NZ": "New Zealand", "OM": "Oman", "PA": "Panama", "PE": "Peru", "PF": "French Polynesia",
         "PG": "Papua New Guinea", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
         "PM": "Saint Pierre and Miquelon", "PN": "Pitcairn", "PR": "Puerto Rico",
         "PS": "Palestinian Territory", "PT": "Portugal", "PW": "Palau", "PY": "Paraguay", "QA": "Qatar",
         "RE": "Réunion", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia",
         "SB": "Solomon Islands", "SC": "Seychelles", "SD": "Sudan", "SE": "Sweden", "SG": "Singapore",
         "SH": "Saint Helena, Ascension and Tristan Da Cunha", "SI": "Slovenia", "SJ": "Svalbard and Jan Mayen",
         "SK": "Slovakia", "SL": "Sierra Leone", "SM": "San Marino", "SN": "Senegal", "SO": "Somalia",
         "SR": "Suriname", "SS": "South Sudan", "ST": "Sao Tome and Principe", "SV": "El Salvador",
         "SX": "Sint Maarten (Dutch Part)", "SY": "Syrian Arab Republic", "SZ": "Swaziland",
         "TC": "Turks and Caicos Islands", "TD": "Chad", "TF": "French Southern Territories", "TG": "Togo",
         "TH": "Thailand", "TJ": "Tajikistan", "TK": "Tokelau", "TL": "Timor-Leste", "TM": "Turkmenistan",
         "TN": "Tunisia", "TO": "Tonga", "TR": "Turkey", "TT": "Trinidad and Tobago", "TV": "Tuvalu",
         "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
         "UM": "United States Minor Outlying Islands", "US": "United States", "UY": "Uruguay",
         "UZ": "Uzbekistan", "VA": "Vatican City", "VC": "Saint Vincent and The Grenadines", "VE": "Venezuela",
         "VG": "Virgin Islands, British", "VI": "Virgin Islands, U.S.", "VN": "Viet Nam", "VU": "Vanuatu",
         "WF": "Wallis and Futuna", "WS": "Samoa", "YE": "Yemen", "YT": "Mayotte", "ZA": "South Africa",
         "ZM": "Zambia", "ZW": "Zimbabwe",
         'EU': 'European Union', "_pirate": "Pirate Flag", "_rainbow": "Rainbow Flag",
         "_united-nations": "United Nations", '_earth': 'Earth', "_lichess": "Lichess Flag", "_russia-wbw": "Russia BWB"}


def flair_to_text(flair):
    i1 = flair.find('.')
    if i1 <= 0 and i1 < len(flair):
        flair_name = flair
    else:
        flair_name = flair[i1+1:].replace('-', ' ')
        if flair_name:
            flair_name = f"{flair_name[0].upper()}{flair_name[1:]}"
    return flair_name


def get_flair_element(flair, size=30):
    if not flair:
        return ""
    return f'<abbr class="user-flair text-info pr-1" title="{flair_to_text(flair)}" style="text-decoration:none;">' \
           f'<img src="https://lichess1.org/assets/______0/flair/img/{flair}.webp" ' \
           f'style="max-width:{size}px;"></abbr>'


def get_highlight_style(opacity, is_diff=False):
    return f"background-color:rgba(160,119,0,{opacity});" if is_diff else f"background-color:rgba(0,160,119,{opacity});"


def add_timeout_msg(timeouts, msg):
    user_msg = timeouts.get(msg.username)
    if user_msg is None or msg.score > user_msg.score:
        timeouts[msg.username] = msg


def get_log_file():
    return os.getenv("LOG_FILE", "./log/log.txt")


def get_token():
    token = os.getenv("TOKEN")
    if token:
        log("using token", to_print=True, to_save=True)
    return token


def get_db():
    return os.getenv("DB_FILE", "./db/litools.sqlite")


def get_host():
    return os.getenv("HOST", "0.0.0.0")


def get_port():
    return int(os.getenv("PORT", 5000))


def get_num_threads():
    return int(os.getenv("NUM_THREADS", 2))


def get_uri():
    return os.getenv("APP_URL", "http://localhost:5000")


def get_client_id():
    return os.getenv("CLIENT_ID", "litools")


def get_embed_lichess():
    return os.getenv("EMBED_LICHESS", "False") == "True"


def needs_to_refresh_insights(user_id, now=None):
    if now is None:
        now = datetime.now()
    return user_id not in refresh_insights_times \
        or delta_s(now, refresh_insights_times[user_id]) > REFRESH_OPENINGS_PERIOD


def set_insights_refreshed(user_id, now=None):
    if now is None:
        now = datetime.now()
    for u_id in list(refresh_insights_times.keys()):
        if delta_s(now, refresh_insights_times[u_id]) >= REFRESH_OPENINGS_PERIOD:
            del refresh_insights_times[u_id]
    refresh_insights_times[user_id] = now


def render(chart, style=DarkStyle, theme_color="#222222"):
    style = style(major_label_font_size=16, label_font_size=16,  # value_label_font_size=18, value_font_size=18,
                  title_font_size=24, legend_font_size=18, tooltip_font_size=20,
                  background=theme_color, plot_background=theme_color)  # background='transparent')
    return f'<embed type="image/svg+xml" src={chart.render_data_uri(style=style)} />'


class TournType(Enum):
    Unknown = 0
    Arena = 1
    Swiss = 2
    Study = 3


class Profile:
    def __init__(self):
        self.country = ""
        self.location = ""
        self.bio = ""
        self.firstName = ""
        self.lastName = ""
        self.fideRating = 0
        self.uscfRating = 0
        self.ecfRating = 0

    def set(self, data):
        self.country = data.get('flag', "")
        self.location = data.get('location', "")
        bio = data.get('bio', "")
        try:
            self.bio = html.escape(bio)
        except Exception as exception:
            print(f"ERROR when processing bio: {bio}")
            self.bio = "<ERROR>"
        self.firstName = data.get('firstName', "")
        self.lastName = data.get('lastName', "")
        self.fideRating = data.get('fideRating', 0)
        self.uscfRating = data.get('uscfRating', 0)
        self.ecfRating = data.get('ecfRating', 0)

    def get_info(self):
        info = []
        name = f"{self.firstName} {self.lastName}".strip()
        if name:
            info.append(f'<div><span class="text-muted">Name:</span> {name}</div>')
        if self.location:
            info.append(f'<div><span class="text-muted">Location:</span> {self.location}</div>')
        if self.bio:
            info.append(f'<div class="text-break"><span class="text-muted">Bio:</span> {self.bio}</div>')
        ratings = []
        if self.fideRating:
            ratings.append(f"FIDE = {self.fideRating}")
        if self.uscfRating:
            ratings.append(f"USCF = {self.uscfRating}")
        if self.ecfRating:
            ratings.append(f"ECF = {self.ecfRating}")
        str_ratings = ", ".join(ratings)
        if str_ratings:
            info.append(f'<div><span class="text-muted">Ratings:</span> {str_ratings}</div>')
        return "".join(info)


class User:
    def __init__(self, username):
        self.name = username
        self.id = username.lower()
        self.disabled = False
        self.tosViolation = False
        self.patron = False
        self.flair = ""
        self.verified = False
        self.title = ""
        self.country = ""
        self.createdAt: int = None
        self.seenAt: int = None
        self.num_games = 0
        self.num_rated_games = 0
        self.profile = Profile()
        self.is_error = False

    def is_titled(self):
        return self.title and self.title != "BOT"

    def get_name(self, postfix=""):
        if self.title:
            if self.title == "BOT":
                title = f'<span style="color:#cd63d9">{self.title}</span> '
            else:
                title = f'<span class="text-warning">{self.title}</span> '
        else:
            title = ""
        return f'{title}<a href="https://lichess.org/@/{self.id}{postfix}" class="pr-1" target="_blank">{self.name}</a>'

    def get_short_name(self, max_len=10):
        if len(self.name) > max_len:
            title_name = f'{self.title} {self.name}'.strip()
            return f'<abbr title="{title_name}" style="text-decoration:none;">{shorten(self.name, max_len)}</abbr>'
        return self.name

    def get_disabled(self):
        if not self.disabled:
            return ""
        return '<abbr title="Closed" class="px-1" style="text-decoration:none;font-size:19px;">' \
               '<i class="fas fa-times text-danger" style="font-size:19px"></i></abbr>'

    def get_patron(self):
        if not self.patron:
            return ""
        return '<abbr title="Lichess Patron" class="text-info px-1" style="text-decoration:none;">' \
               '<i class="fas fa-gem"></i></abbr>'

    def get_flair(self):
        return get_flair_element(self.flair)

    def get_verified(self):
        if not self.verified:
            return ""
        return '<abbr title="Verified" class="text-info px-1" style="text-decoration:none;">' \
               '<i class="fas fa-check"></i></abbr>'

    def get_tosViolation(self):
        if not self.tosViolation:
            return ""
        return '<abbr title="TOS Violation" class="px-1" style="text-decoration:none;font-size:19px;' \
               'color:#e74c3c;background-color:#f39c12;"><i class="far fa-angry"></i></abbr>'

    def get_country(self):
        country = self.profile.country
        if not country:
            return ""
        country_img = f'<img src="https://lichess1.org/assets/______0/flags/{country}.png" style="max-width:30px;">'
        country_name = country_names.get(country, None)
        if country_name is None:
            country_name = country.upper()
            if country_name[0] == '_':
                country_name = country_name[1:]
        if country_name:
            return f'<abbr class="px-1" title="{country_name}" style="text-decoration:none;">{country_img}</abbr>'
        return f'<span class="px-1">{country_img}</span>'

    def get_name_info(self, limits_created_days_ago):
        part1 = f'{self.get_flair()}{self.get_patron()}{self.get_name()}{self.get_disabled()}{self.get_verified()}'
        part2 = f'{self.get_tosViolation()}{self.get_country()} {self.get_created(limits_created_days_ago)}'
        return f'<div class="mr-2">{part1}{part2}</div>'

    def get_num_games(self, limits_num_played_games):
        if self.num_games == 0 and self.num_rated_games == 0:
            return ""
        class_games = f' class="text-danger"' if self.num_rated_games <= limits_num_played_games[0] \
            else f' class="text-warning"' if self.num_rated_games <= limits_num_played_games[1] else ""
        return f'<div><abbr{class_games} title="Number of rated games" style="text-decoration:none;">' \
               f'<b>{self.num_rated_games:,}</b></abbr> / <abbr title="Total number of games" ' \
               f'style="text-decoration:none;">{self.num_games:,}</abbr> games</div>'

    def get_user_info(self, limits_created_days_ago, limits_num_played_games):
        return f'<div class="d-flex justify-content-between align-items-baseline mt-3">' \
               f'{self.get_name_info(limits_created_days_ago)}{self.get_num_games(limits_num_played_games)}</div>'

    def get_createdAt(self):
        return datetime.fromtimestamp(self.createdAt // 1000, tz=tz.tzutc()) if self.createdAt else None

    def get_created_days_ago(self):
        if not self.createdAt:
            return "&mdash;"
        return datetime.fromtimestamp(self.createdAt // 1000, tz=tz.tzutc()) if self.createdAt else None

    def get_created(self, limits_created_days_ago):
        if not self.createdAt:
            return ""
        now_utc = datetime.now(tz=tz.tzutc())
        created_ago = timestamp_to_ago(self.createdAt, now_utc)
        days = (now_utc - self.get_createdAt()).days
        class_created = ' class="text-danger"' if days <= limits_created_days_ago[0] \
            else ' class="text-warning"' if days <= limits_created_days_ago[1] else ""
        return f'<abbr{class_created} title="Account created {created_ago}" style="text-decoration:none;">' \
               f'<b>{created_ago}</b></abbr>'

    def get_seenAt(self):
        return datetime.fromtimestamp(self.seenAt // 1000, tz=tz.tzutc()) if self.seenAt else None

    def get_seen(self):
        if not self.seenAt:
            return ""
        now_utc = datetime.now(tz=tz.tzutc())
        seen_ago = timestamp_to_ago(self.seenAt, now_utc)
        return f'<abbr title="Account active {seen_ago}" style="text-decoration:none;">' \
               f'<b>{seen_ago}</b></abbr>'

    def get_profile(self):
        return self.profile.get_info()

    def set(self, user):
        self.name = user['username']
        self.disabled = user.get('disabled', False)
        if not self.disabled:
            self.tosViolation = user.get('tosViolation', False)
            self.patron = user.get('patron', False)
            self.flair = user.get('flair', "")
            self.verified = user.get('verified', False)
            self.title = user.get('title', "")
            self.createdAt = user['createdAt']
            self.seenAt = user.get('seenAt', None)
            self.num_games = user['count']['all']
            self.num_rated_games = user['count']['rated']
            self.profile.set(user.get('profile', {}))


class UserData(User):
    def __init__(self, username, mod):
        super().__init__(username)
        self.data, api_error = get_user(username, mod)
        if self.data and not api_error:
            self.set(self.data)
        self.mod_log = ""
        self.actions = []
        self.notes = ""
        self.bio_add = ""
        self.errors = [api_error] if api_error else []
        self.is_error = not not api_error
        self.time_update = datetime.now(tz=tz.tzutc())

    def is_up_to_date(self):
        return delta_s(datetime.now(tz=tz.tzutc()), self.time_update) <= LIFETIME_USER_CACHE

    def get_profile(self):
        if self.bio_add:
            old_bio = self.profile.bio
            self.profile.bio = f'<span>{self.profile.bio} {self.bio_add}</span>'
            str_profile = super().get_profile()
            self.profile.bio = old_bio
            return str_profile
        return super().get_profile()


def get_user(username, mod):
    try:
        url = f"https://lichess.org/api/user/{username}"
        r = mod.api.get(ApiType.ApiUser, url, token=mod.token)
        if r.status_code == 200:
            return r.json(), ""
        return None, f"ERROR /api/user/: Status Code {r.status_code}"
    except Exception as exception:
        log_exception(exception)
        return None, str(exception)
    except:
        return None, "ERROR"


class VariantPlayed:
    def __init__(self, variant_name, perf, add_note_links=False):
        self.name = variant_name
        self.rd = perf.get('rd', 0)
        self.prov = perf.get('prov', False)
        self.rating = perf.get('rating', 0)
        self.num_games = perf.get('games', 0)
        self.progress = perf.get('prog', 0)
        self.min_rating: int = None
        self.max_rating: int = None
        self.stable_rating_range = []  # [self.rating, self.rating]
        # ^  pre-initialization might have been needed for check_variants(), see below
        self.detailed_progress = []
        self.num_recent_games: int = None
        self.add_note_links = add_note_links

    def get_rating(self):
        if self.rating == 0:
            rating = "?"
        else:
            rating = str(self.rating)
            if self.prov:
                if not self.num_recent_games:
                    rating += '?'
                else:
                    rating += '<span class="text-warning">?</span>'
            progress = f"&plusmn;{self.rd} " if self.rd > 60 else ""
            class_rating = ""
            if abs(self.progress) > BOOST_SUS_PROGRESS:
                progress = f"{progress}progress: +{self.progress}" if self.progress > 0 \
                    else f"{progress}progress: &minus;{abs(self.progress)}"
                class_rating = "" if not self.num_recent_games else ' class="text-danger" style="text-decoration:none;"' \
                    if self.num_games >= BOOST_SUS_NUM_GAMES else ' class="text-warning" style="text-decoration:none;"'
            if progress:
                rating = f'<abbr title="{progress}"{class_rating}>{rating}</abbr>'
        return rating

    def get_info(self):
        if self.num_games == 0:
            return ""
        if self.name:
            name = f"{self.name[0].upper()}{self.name[1:]}"
        else:
            name = "Unknown Variant"
        if abs(self.progress) > BOOST_SUS_PROGRESS:
            progress = f"+{self.progress}" if self.progress > 0 else f"&minus;{abs(self.progress)}"
            prog = f'<span class="text-danger px-1">{progress}</span>'
        else:
            prog = ""
        return f'<div><span class="text-success">{name}</span>: {self.get_rating()} ' \
               f'over {self.num_games:,} game{"" if self.num_games == 1 else "s"}{prog}</div>'

    def get_table_row(self, are_recent_games):
        if self.num_games == 0:
            return ""
        if self.name:
            name = f"{self.name[0].upper()}{self.name[1:]}"
        else:
            name = "Unknown Variant"
        if are_recent_games:
            if self.min_rating is None or self.max_rating is None or self.num_recent_games is None\
                    or self.num_recent_games <= 1:
                str_range = ""
            else:
                rating_diff = self.stable_rating_range[1] - self.stable_rating_range[0]
                color = ' class="text-danger"' if rating_diff >= BOOST_SUS_RATING_DIFF[1] else ' class="text-warning"' \
                    if rating_diff >= BOOST_SUS_RATING_DIFF[0] else ""
                str_detailed_progress = "&Delta;{}: {}".format(rating_diff,
                                                               " &rarr; ".join(reversed(self.detailed_progress)))
                if rating_diff == 0:
                    str_range = f"{self.stable_rating_range[0]}?"
                else:
                    str_range = f'<span{color}>{self.stable_rating_range[0]}</span>&hellip;' \
                                f'<span{color}>{self.stable_rating_range[1]}</span>'
                is_min_stable = self.stable_rating_range[0] == self.min_rating
                is_max_stable = self.stable_rating_range[1] == self.max_rating
                if not is_min_stable or not is_max_stable:
                    str_detailed_progress = f'{self.min_rating}{"" if is_min_stable else "?"}&hellip;' \
                                            f'{self.max_rating}{"" if is_max_stable else "?"} {str_detailed_progress}'
                str_range = f'<abbr title="{str_detailed_progress}" style="text-decoration:none;">{str_range}</abbr>'
            str_num_recent_games = "&ndash;" if not self.num_recent_games else f"{self.num_recent_games:,}"
            rows_recent_games = f'<td class="text-center">{str_num_recent_games}</td>' \
                                f'<td class="text-center">{str_range}</td>'
        else:
            rows_recent_games = ""
        perf_link = ""
        if self.num_recent_games and self.add_note_links:
            link = f'https://lichess.org/@/{{username}}/perf/{self.name}'
            perf_link = f'<a href="{link}" target="_blank">open</a>'
            name = f'<button class="btn btn-primary w-100 py-0" ' \
                   f'onclick="add_to_notes(this)" data-selection=\'{link}\'>{name}</button>'
        row_class = ' class="text-muted"' if not self.num_recent_games else ""
        row = f'''<tr{row_class}>
                    <td class="text-left">{name}</td>
                    <td class="text-left">{perf_link}</td>
                    <td class="text-left">{self.get_rating()}</td>
                    {rows_recent_games}
                    <td class="text-right">{self.num_games:,}</td>
                  </tr>'''
        return row


class Storm:
    def __init__(self, perfs=None):
        perf = perfs.get('storm', {}) if perfs else {}
        self.runs = perf.get('runs', 0)
        self.score = perf.get('score', 0)

    def is_ok(self):
        return self.runs > 0 and self.score > 0

    def get_info(self):
        if not self.is_ok():
            return ""
        return f'<div class="mb-3 px-2">Strom: {self.score} over {self.runs} runs</div>'


class Variants:
    def __init__(self, add_note_links=False):
        self.variants = []
        self.storm = Storm()
        self.add_note_links = add_note_links
        self.are_recent_games = False

    def set(self, perfs):
        self.storm = Storm(perfs)
        for variant_name, perf in perfs.items():
            if variant_name != "strom":
                self.variants.append(VariantPlayed(variant_name, perf, self.add_note_links))
        self.variants.sort(key=lambda variant: (-999999 if variant.name == "puzzle" else 0) + variant.num_games,
                           reverse=True)

    def get_table(self, num_games):
        rows = [variant.get_table_row(self.are_recent_games) for variant in self.variants]
        if not rows:
            return ""
        str_games = f'Number of games played among the last ' \
                    f'{num_games} game{"" if num_games == 1 else "s"} analyzed'
        rows_recent_games = f'<th class="text-center" style="cursor:default;"><abbr title="{str_games}"' \
                            f' style="text-decoration:none;"><i class="fas fa-hashtag"></i></abbr></th>' \
                            f'<th class="text-center" style="cursor:default;">Range</th>' if self.are_recent_games else ""
        table = f'''<div class="column">
            <table id="variants_table" class="table table-sm table-striped table-hover text-center text-nowrap mt-3">
              <thead><tr>
                <th class="text-left" style="cursor:default;">Variant</th>
                <th></th>
                <th class="text-left" style="cursor:default;">Rating</th>
                {rows_recent_games}
                <th class="text-right" style="cursor:default;"><abbr title="Total number of rated games played" 
                    style="text-decoration:none;"># games</abbr></th>
              </tr></thead>
              {"".join(rows)}
            </table>
          </div>'''
        return f"{table}{self.storm.get_info()}"

    def set_rating_ranges(self, games):
        for variant, ratings in games.all_user_ratings.items():
            for v in self.variants:
                if v.name == variant:
                    v.min_rating = min(ratings)
                    v.max_rating = max(ratings)
                    if len(ratings) <= 10:
                        v.detailed_progress = [str(rating) for rating in ratings]
                    else:
                        step = len(ratings) / 10
                        v.detailed_progress = [str(ratings[int(round(i * step))]) for i in range(10)]
                    v.num_recent_games = len(ratings)
                    num_stable_games = v.num_games - NUM_FIRST_GAMES_TO_EXCLUDE
                    # Ratings are in reverse order
                    i_end = min(len(ratings), num_stable_games)
                    stable_ratings = ratings[:i_end] if i_end > 0 else [ratings[0]]
                    v.stable_rating_range = [min(stable_ratings), max(stable_ratings)]
        self.are_recent_games = True

    def get_most_played_variant(self):
        max_num_recent_games = 0
        variant = ""
        for v in self.variants:
            if v.num_recent_games and (v.num_recent_games > max_num_recent_games):
                max_num_recent_games = v.num_recent_games
                variant = v.name
        return variant, max_num_recent_games

    def __iter__(self):
        return iter(self.variants)


def add_variant_rating(ratings, variant, rating):
    if variant in ratings:
        ratings[variant].append(rating)
    else:
        ratings[variant] = [rating]


def get_user_ids(game):
    if 'user' in game['players']['black']:
        black_id = game['players']['black']['user']['id']
    elif 'aiLevel' in game['players']['black']:
        black_id = "AI"
    else:
        black_id = "Unknown Player"
    if 'user' in game['players']['white']:
        white_id = game['players']['white']['user']['id']
    elif 'aiLevel' in game['players']['white']:
        white_id = "AI"
    else:
        white_id = "Unknown Player"
    return white_id, black_id


class PerfType(IntFlag):
    ultraBullet = 2 ** 0
    bullet = 2 ** 1
    blitz = 2 ** 2
    rapid = 2 ** 3
    classical = 2 ** 4
    correspondence = 2 ** 5
    crazyhouse = 2 ** 6
    chess960 = 2 ** 7
    kingOfTheHill = 2 ** 8
    threeCheck = 2 ** 9
    antichess = 2 ** 10
    atomic = 2 ** 11
    horde = 2 ** 12
    racingKings = 2 ** 13

    @staticmethod
    def all():
        return 0b11111111111111

    @staticmethod
    def all_but_correspondence():
        return 0b11111111011111

    @staticmethod
    def to_index(perf_type):
        return 0 if perf_type == PerfType.ultraBullet \
            else 1 if perf_type == PerfType.bullet \
            else 2 if perf_type == PerfType.blitz \
            else 6 if perf_type == PerfType.rapid \
            else 3 if perf_type == PerfType.classical \
            else 4 if perf_type == PerfType.correspondence \
            else 18 if perf_type == PerfType.crazyhouse \
            else 11 if perf_type == PerfType.chess960 \
            else 12 if perf_type == PerfType.kingOfTheHill \
            else 15 if perf_type == PerfType.threeCheck \
            else 13 if perf_type == PerfType.antichess \
            else 14 if perf_type == PerfType.atomic \
            else 16 if perf_type == PerfType.horde \
            else 17 if perf_type == PerfType.racingKings \
            else -1


class Games:
    def __init__(self, user_id, max_num_games, max_num_days, statuses_to_discard,
                 percent_extra_games_to_download=0, download_moves=True, only_rated=True):
        self.user_id = user_id
        self.games = []
        self.since: int = None
        self.until: datetime = None
        self.max_num_games: int = max_num_games
        self.max_num_days = max_num_days
        self.percent_extra_games_to_download = percent_extra_games_to_download
        self.download_moves = download_moves
        self.only_rated = only_rated
        self.statuses_to_discard = statuses_to_discard
        self.all_user_ratings = {}

    def download(self, mod, since=None, before=None, perf_type=None):
        now_utc = datetime.now(tz=tz.tzutc())
        self.until = None
        if before:
            try:
                self.until = datetime.strptime(before, '%Y-%m-%dT%H:%M').replace(tzinfo=tz.tzutc())
            except Exception as exception:
                before = None
                log_exception(exception)
        if before:
            str_until = f"&until={int(self.until.timestamp() * 1000)}"
        else:
            str_until = ""
            self.until = now_utc
        ts_Xmonths_ago = int((self.until - timedelta(days=self.max_num_days)).timestamp() * 1000)
        if since is None or (self.until != now_utc and since >= self.until):
            since = ts_Xmonths_ago
        else:
            since = max(ts_Xmonths_ago, int(since.timestamp() * 1000))
        max_num_games = int(round(self.max_num_games * (1 + self.percent_extra_games_to_download / 100)))
        moves = "" if self.download_moves else "&moves=false"
        rated = "rated=true&" if self.only_rated else ""
        perfs = []
        if perf_type:
            for pt in PerfType:
                if perf_type & pt.value:
                    perfs.append(pt.name)
        str_perfType = f'perfType={",".join(perfs)}&' if perfs else ""
        url = f"https://lichess.org/api/games/user/{self.user_id}?{rated}{str_perfType}finished=true&max={max_num_games}" \
              f"{moves}&since={since}{str_until}"
        self.since = None if since == ts_Xmonths_ago else since
        games = mod.api.get_ndjson(ApiType.ApiGamesUser, url, mod.token)
        if len(games) > self.max_num_games:
            num_to_delete = len(games) - self.max_num_games
            self.games = []
            for game in games:
                if num_to_delete > 0 and (game['status'] in self.statuses_to_discard):
                    num_to_delete -= 1
                else:
                    self.games.append(game)
            if len(self.games) > self.max_num_games:
                self.games = self.games[:self.max_num_games]
        else:
            self.games = games
        # Delete correspondence games in variants
        if not (perf_type & PerfType.correspondence):
            for i in range(len(self.games) - 1, -1, -1):
                if self.games[i]['speed'] == "correspondence":
                    del self.games[i]
        # TODO: Delete AI games?
        # for i in range(len(self.games) - 1, -1, -1):
        #     if 'aiLevel' in self.games[i]['players']['black'] or 'aiLevel' in self.games[i]['players']['white']:
        #         del self.games[i]
        # Get variant ratings
        self.all_user_ratings = {}
        for game in self.games:
            white_id, black_id = get_user_ids(game)
            if white_id == self.user_id:
                user_color = 'white'
            elif black_id == self.user_id:
                user_color = 'black'
            else:
                raise Exception("Error games: no player")
            variant = game['variant']
            if variant == "standard":
                variant = game['speed']
            user_rating = game['players'][user_color]['rating']
            add_variant_rating(self.all_user_ratings, variant, user_rating)

    def __iter__(self):
        return iter(self.games)

    def __getitem__(self, key):
        return self.games[key]

    def __len__(self):
        return len(self.games)

    def get_num(self):
        str_s = "" if len(self.games) == 1 else "s"
        str_num = f'<abbr title="{len(self.games)} latest game{str_s} analyzed ({self.max_num_games} requested)" ' \
                  f'style="text-decoration:none;"><b>{len(self.games)} game{str_s}</b></abbr>'
        first_createdAt: datetime = None
        if self.games:
            first_createdAt = datetime.fromtimestamp(self.games[-1]['createdAt'] // 1000, tz=tz.tzutc())
        if len(self.games) > 1:
            last_createdAt = datetime.fromtimestamp(self.games[0]['createdAt'] // 1000, tz=tz.tzutc())
            num_days = (last_createdAt - first_createdAt).days
            str_num = f'{str_num} for <b>{num_days} day{"" if num_days == 1 else "s"}</b>'
        if self.since:
            since = datetime.fromtimestamp(self.since // 1000, tz=tz.tzutc())
            str_num = f'{str_num} from <abbr title="Date/Time of the last manual warning">{since:%Y-%m-%d %H:%M} UTC</abbr>'
        elif self.games:
            str_num = f'{str_num} from {first_createdAt:%Y-%m-%d %H:%M} UTC'
        return f'<div class="mb-3">{str_num}</div>'


def datetime_to_ago(t, now_utc=None, short=False):
    if now_utc is None:
        now_utc = datetime.now(tz=tz.tzutc())
    years = relativedelta(now_utc, t).years
    if years >= 1:
        return f"{years}Y" if short else "1 year ago" if years == 1 else f"{years} years ago"
    months = relativedelta(now_utc, t).months
    if months >= 1:
        return f"{months}M" if short else "1 month ago" if months == 1 else f"{months} months ago"
    weeks = relativedelta(now_utc, t).weeks
    if weeks >= 1:
        return f"{weeks}W" if short else "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    days = relativedelta(now_utc, t).days
    if days >= 1:
        return f"{days}D" if short else "1 day ago" if days == 1 else f"{days} days ago"
    hours = relativedelta(now_utc, t).hours
    if hours >= 1:
        return f"{hours}h" if short else "1 hour ago" if hours == 1 else f"{hours} hours ago"
    minutes = relativedelta(now_utc, t).minutes
    if minutes >= 1:
        return f"{minutes}m" if short else "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    seconds = relativedelta(now_utc, t).seconds
    if seconds >= 1:
        return f"{seconds}s" if short else "1 second ago" if seconds == 1 else f"{seconds} seconds ago"
    if seconds == 0:
        return "now"
    return "right now"


def timestamp_to_ago(ts_ms, now_utc=None, short=False):
    t = datetime.fromtimestamp(ts_ms // 1000, tz=tz.tzutc())
    return datetime_to_ago(t, now_utc, short)


def datetime_to_abbr_ago(dt, now_utc=None, short=False):
    return f'<abbr title="{dt:%Y-%m-%d %H:%M:%S} UTC" style="text-decoration:none;">' \
           f'{datetime_to_ago(dt, now_utc, short)}</abbr>'


def datetime_to_abbr_in(dt, now_utc, short=False):
    str_period = datetime_to_ago(now_utc, dt, short)
    if " ago" in str_period:
        str_period = f'in {str_period.replace(" ago", "")}'
    return f'<abbr title="{dt:%Y-%m-%d %H:%M:%S} UTC" style="text-decoration:none;">{str_period}</abbr>'

def timestamp_to_abbr_ago(ts_ms, now_utc=None, short=False):
    t = datetime.fromtimestamp(ts_ms // 1000, tz=tz.tzutc())
    return datetime_to_abbr_ago(t, now_utc, short)


def delta_s(dt2, dt1):
    diff = dt2 - dt1
    return diff.total_seconds()


def deltaseconds(dt2, dt1):
    return int(delta_s(dt2, dt1))


def deltaperiod(dt2, dt1, short=False, show_seconds=False):
    seconds = deltaseconds(dt2, dt1)
    return deltainterval(seconds, short, show_seconds)


def deltainterval(seconds, short=False, show_seconds=False):
    seconds = int(round(seconds))
    if seconds >= 24 * 60 * 60:
        hours = int(round(seconds / (60 * 60)))
        days = hours // 24
        hours = (hours - days * 24)
        out = f"{days}d" if short else f"{days} day{'' if days == 1 else 's'}"
        if hours == 0:
            return out
        return f"{out}{hours}h" if short else f"{out} {hours} hour{'' if hours == 1 else 's'}"
    if seconds >= 60 * 60:
        minutes = int(round(seconds / 60))
        hours = minutes // 60
        minutes = (minutes - hours * 60)
        out = f"{hours}h" if short else f"{hours} hour{'' if hours == 1 else 's'}"
        if minutes == 0:
            return out
        return f"{out}{minutes:02d}m" if short else f"{out} {minutes} minute{'' if minutes == 1 else 's'}"
    minutes = seconds // 60
    seconds = (seconds - minutes * 60)
    if show_seconds:
        if minutes:
            out = f"{minutes}m" if short else f"{minutes} minute{'' if minutes == 1 else 's'}"
        else:
            out = ""
        if short:
            return f"{out}{seconds:02d}s"
        if seconds == 0:
            return out if out else "0 seconds"
        str_seconds = f"{seconds} second{'' if seconds == 1 else 's'}"
        return f"{out} {str_seconds}" if out else str_seconds
    minutes = int(round(minutes + seconds / 60))
    return f"{minutes}m" if short else f"{minutes} minute{'' if minutes == 1 else 's'}"


def shorten(original_name, max_len):
    if original_name:
        if len(original_name) > max_len:
            name = original_name[:max_len]
            i = max(name[:-1].rfind(' '), name[:-1].rfind('-'), name[:-1].rfind(','), name[:-1].rfind('.'),
                    name[:-1].rfind('!'), name[:-1].rfind('?'))  # TODO: regex
            if i >= 0.7 * max_len:
                name = f"{name[:i]}&hellip;"
            else:
                name = f"{name[:-1]}&hellip;"
        else:
            name = original_name
    else:
        name = "?"
    return name


def get_tc(game):
    try:
        if 'clock' not in game:
            if game['speed'] == "correspondence":
                return "Correspondence"
            return "Unknown"
        t1 = game['clock']['initial']
        t2 = game['clock']['increment']
        str_t1 = "1/4" if t1 == 15 else "1/2" if t1 == 30 else "3/4" if t1 == 45 else "1.5" if t1 == 90 else str(t1 // 60)
        return f"{str_t1}+{t2}"
    except:
        return "Unknown_TC"


class Reason(IntEnum):
    No = 0
    Shaming = 1
    Offensive = 2
    Spam = 3
    Other = 4
    Size = 5

    @staticmethod
    def to_text(reason):
        if reason == Reason.Shaming:
            return "Public shaming"
        if reason == Reason.Offensive:
            return "Offensive language"
        if reason == Reason.Spam:
            return "Spam"
        if reason == Reason.Other:
            return "Other"
        return "No action needed"

    @staticmethod
    def to_tag(reason):
        if reason == Reason.Shaming:
            return "shaming"
        if reason == Reason.Offensive:
            return "insult"
        if reason == Reason.Spam:
            return "spam"
        if reason == Reason.Other:
            return "other"
        return None

    @staticmethod
    def to_Tag(reason):
        tag = Reason.to_tag(reason)
        return "NO" if tag is None else f"{tag[0].upper()}{tag[1:]}"


def log(text, to_print=False, to_save=True, verbose=1):
    if verbose > VERBOSE:
        return
    now_utc = datetime.now(tz=tz.tzutc())
    line = f"{now_utc: %Y-%m-%d %H:%M:%S} UTC: {text}"
    if to_print:
        print(line)
    if not to_save:
        return
    try:
        with open(get_log_file(), "a", encoding="utf-8") as file:
            file.write(f"{line}\n")
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)


def log_exception(exception, to_print=True, to_save=True):
    if to_print:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
    text = f"EXCEPTION: {exception}"
    log(text, to_print=False, to_save=to_save)


def log_read(lines_per_page=100, page=0, reverse=True):
    if lines_per_page < 0 or page < 0:
        return ""
    max_size = 50_000_000
    log_file = get_log_file()
    file_size = os.stat(log_file).st_size
    with open(log_file, "r", encoding="utf-8") as file:
        if file_size > max_size:
            file.seek(file_size - max_size)
            all_lines = file.readlines()[1:]
        else:
            all_lines = file.readlines()
    offset = page * lines_per_page
    if len(all_lines) <= offset:
        return ""
    lines = all_lines[-offset - lines_per_page:] if offset == 0 else all_lines[-offset - lines_per_page: -offset]
    if reverse:
        lines.reverse()
    lines.insert(0, f"Version: {LITOOLS_VERSION[1:]}\nLog size: {file_size:,}\nLines: {len(all_lines):,}\n\n")
    return html.escape("".join(lines)).replace('\n', "<br>").replace(' ', "&nbsp;")


def get_user_link(username, no_name="Unknown User", class_a="text-info", max_len=10):
    if username:
        if len(username) > max_len:
            user_url = username
            username = f'{username[:max_len - 1]}&hellip;'
        else:
            user_url = username.lower()
        return f'<a class="{class_a}" href="https://lichess.org/@/{user_url}" target="_blank">{username}</a>'
    return f'<i>{no_name}</i>'


def get_user_comm_href(username):
    return f"https://lichess.org/mod/{username}/communication"


def read_notes(username, mod):
    url = f"https://lichess.org/api/user/{username}/note"
    r = mod.api.get(ApiType.ApiUserNote, url, token=mod.token)
    if r.status_code != 200:
        raise Exception(f"ERROR /api/user/{username}/note: Status Code {r.status_code}")
    data = r.json()
    notes = list(chain.from_iterable(data)) if data and isinstance(data[0], list) else data
    return notes


def get_notes(username, mod, mod_log_data=None):
    info = []
    try:
        data = mod_log_data.get('notes') if mod_log_data else None
        if not data:
            data = read_notes(username, mod)
        now_utc = datetime.now(tz=tz.tzutc())
        for note in data:
            is_dox_note = note.get('dox', False)
            author = None
            author_data = note.get('from')
            if author_data:
                author = author_data.get('name')
            author = get_user_link(author, class_a="text-danger" if is_dox_note else "text-info")
            text = note.get('text', "")
            links = re_link.findall(text)
            pos = 0
            strings = []
            for link in links:
                i = text.find(link)
                if i >= 0:
                    strings.append(html.escape(text[pos:i]).replace('\n', "<br>"))
                    strings.append(f'<a class="text-info" href="{link}" target="_blank">{link}</a>')
                    pos = i + len(link)
            strings.append(html.escape(text[pos:]).replace('\n', "<br>"))
            text = "".join(strings)
            note_time = note.get('date', None)
            str_time = f'<br><small class="text-muted">{timestamp_to_abbr_ago(note_time, now_utc)}</small>' \
                if note_time else ""
            is_mod_note = note.get('mod', False)
            str_mod = "" if is_mod_note else "<br>User Note"
            info.append(f'<tr><td class="text-left text-nowrap mr-2">{author}:{str_time}{str_mod}</td>'
                        f'<td class="text-left text-wrap" style="{STYLE_WORD_BREAK}">{text}</td></tr>')
    except Exception as exception:
        log_exception(exception)
        if not info:
            return None
    return f'<table class="table table-sm table-striped table-hover border text-nowrap">' \
           f'<tbody>{"".join(info)}</tbody></table>' if info else ""


def add_note(username, note, mod):
    try:
        data = {'text': note,
                'mod': True}
        url = f"https://lichess.org/api/user/{username}/note"
        r = mod.api.post(ApiType.ApiUserNote_Post, url, token=mod.token, json=data)
        if r.status_code == 200:
            log(f"ADD NOTE for @{username}:\n{note}", False, True, 2)
            return True
    except Exception as exception:
        log_exception(exception)
    return False


def load_mod_log(username, mod):
    try:
        url = f"https://lichess.org/api/user/{username}/mod-log"
        r = mod.api.get(ApiType.ApiUserModLog, url, token=mod.token)
        if r.status_code != 200:
            raise Exception(f"ERROR /api/user/{username}/mod-log: Status Code {r.status_code}")
        data = r.json()
        if data.get('notes') and isinstance(data['notes'][0], list):
            data['notes'] = list(chain.from_iterable(data['notes']))
        return data
    except Exception as exception:
        log_exception(exception)
    return None


def load_timeout_log(username, mod):
    try:
        url = f"https://lichess.org/mod/chat-user/{username}"
        r = mod.api.get(ApiType.ModChatUser, url, token=mod.token)
        if r.status_code != 200:
            raise Exception(f"ERROR /mod/chat-user/{username}: Status Code {r.status_code}")
        data = r.json()
        if not data:
            return None
        history = data.get('history', [])
        if not history:
            return {'logs': []}
        log = []
        for h in history:
            item = {
                'mod': h.get('mod', ""),
                'action': 'chatTimeout',
                'date': h['date'],
                'details': h.get('reason', "")
            }
            log.append(item)
        return {'logs': [log]}
    except Exception as exception:
        log_exception(exception)
    return None


class ModActionType(IntEnum):
    Standard = 0
    Boost = 1
    Chat = 2
    Alt = 3


def get_table_row_for_actions(actions, now_utc):
    if not actions:
        return ""
    if len(actions) == 1:
        return actions[0].get_table_row(now_utc)
    date = f'{actions[0].get_date(now_utc).replace(" ago", "")}&hellip;<br>{actions[-1].get_date(now_utc)}'
    action_class = actions[0].get_class(now_utc)
    row = f'<tr>' \
          f'<td class="text-left align-middle {actions[0].get_date_class(now_utc)}">{date}</td>' \
          f'<td class="text-left align-middle">{actions[0].get_mod_name()}</td>' \
          f'<td class="text-left align-middle {action_class}">{actions[0].get_full_action()}</td>' \
          f'<td class="text-right align-middle {action_class}" style="font-size:23px">' \
          f'<b>&times;{len(actions)}</b></td>' \
          f'</tr>'
    return row


def get_mod_log(data, mod, action_type=ModActionType.Standard):
    actions = []
    try:
        for d in data['logs']:
            for action_data in d:
                if action_type == ModActionType.Boost:
                    actions.append(BoostModAction(action_data))
                elif action_type == ModActionType.Chat:
                    actions.append(ChatModAction(action_data))
                elif action_type == ModActionType.Alt:
                    actions.append(ModAction(action_data))
                else:
                    actions.append(ModAction(action_data))
        ModAction.update_names(actions, mod)
        now_utc = datetime.now(tz=tz.tzutc())
        info = []
        action_stack = []
        for action in actions:
            if action.is_combinable(action_stack, now_utc):
                action_stack.append(action)
            else:
                if action_stack:
                    info.append(get_table_row_for_actions(action_stack, now_utc))
                action_stack = [action]
        if action_stack:
            info.append(get_table_row_for_actions(action_stack, now_utc))
        out_info = f'<table class="table table-sm table-striped table-hover border mb-0">' \
                   f'<tbody>{"".join(info)}</tbody></table>' if info else ""
        return out_info, actions
    except Exception as exception:
        log_exception(exception)
    return "", actions


class ModAction:
    names = {'lichess': 'Lichess'}
    actions = {
        'alt': "mark as alt",
        'unalt': "un-mark as alt",
        'engine': "mark as engine",
        'unengine': "un-mark as engine",
        'booster': "mark as booster",
        'unbooster': "un-mark as booster",
        'deletePost': "delete forum post",
        'disableTwoFactor': "disable 2fa",
        'closeAccount': "close account",
        'selfCloseAccount': "self close account",
        'reopenAccount': "reopen account",
        'openTopic': "reopen topic",
        'closeTopic': "close topic",
        'showTopic': "show topic",
        'hideTopic': "unfeature topic",
        'stickyTopic': "sticky topic",
        'unstickyTopic': "un-sticky topic",
        'postAsAnonMod': "post as a lichess moderator",
        'editAsAnonMod': "edit a lichess moderator post",
        'setTitle': "set FIDE title",
        'removeTitle': "remove FIDE title",
        'setEmail': "set email address",
        'practiceConfig': "update practice config",
        'deleteTeam': "delete team",
        'disableTeam': "disable team",
        'enableTeam': "enable team",
        'terminateTournament': "terminate tournament",
        'chatTimeout': "timeout",  # "chat timeout",
        'troll': "shadowban",
        'untroll': "un-shadowban",
        'permissions': "set permissions",
        'kickFromRankings': "kick from rankings",
        'reportban': "reportban",
        'unreportban': "un-reportban",
        'rankban': "rankban",
        'unrankban': "un-rankban",
        'modMessage': "send message",
        'coachReview': "disapprove coach review",
        'cheatDetected': 'cheat detected',  # "game lost by cheat detection",
        'cli': "run CLI command",
        'garbageCollect': "garbage collect",
        'streamerDecline': "decline streamer",
        'streamerList': "list streamer",
        'streamerUnlist': "unlist streamer",
        'streamerFeature': "feature streamer",
        'streamerUnfeature': "unfeature streamer",
        'streamerTier': "set streamer tier",
        'blogTier': "set blog tier",
        'blogPostEdit': "edit blog post",
        'teamKick': "kick from team",
        'teamEdit': "edited team",
        'appealPost': "posted in appeal",
        'setKidMode': "set kid mode",
        # additional
        'teamMadeOwner': 'made team owner',
        'deleteQaAnswer': 'delete QA answer',
    }
    warnings = {
        'spam': "Warning: Spam is not permitted",
        'insult': "Warning: Offensive language",
        'shaming': "Warning: Accusations",
        'trolling': "Warning: Chat/Forum trolling",
        'ad': "Warning: Advertisements",
        'team_ad': "Warning: Team advertisements",
        'stalling': "Warning: Leaving games / stalling on time",
        'kidMode': "Account set to kid mode",
    }

    @staticmethod
    def update_names(actions, mod):
        is_ids = all([((not action.mod_id) or action.mod_id.islower()) for action in actions])
        if not is_ids:
            # load_timeout_log() returns usernames, not user ids
            for action in actions:
                if action.mod_id:
                    mod_username = action.mod_id
                    action.mod_id = action.mod_id.lower()
                    if action.mod_id not in ModAction.names:
                        ModAction.names[action.mod_id] = mod_username
            return
        ids = set()
        for action in actions:
            if action.mod_id and (action.mod_id not in ModAction.names):
                ids.add(action.mod_id)
        ids = list(ids)
        if ids:
            url = f"https://lichess.org/api/users/status?ids={','.join(ids)}"
            r = mod.api.get(ApiType.ApiUsersStatus, url, token=mod.token)
            if r.status_code != 200:
                raise Exception(f"ERROR /api/users/status?ids={','.join(ids)}: Status Code {r.status_code}")
            data = r.json()
            for d in data:
                ModAction.names[d['id']] = d['name']

    def __init__(self, data):
        self.mod_id = data.get('mod', "")
        self.action = data.get('action', "")
        self.date = data['date']
        self.details = html.escape(data.get('details', ""))

    def get_mod_name(self):
        mod = ModAction.names.get(self.mod_id)
        mod_link = get_user_link(mod, "Unknown Mod")
        return mod_link

    def is_warning(self):
        return self.action == 'modMessage' and self.details.startswith("Warning")

    def is_perms(self):
        return self.action == 'permissions'

    def get_timeout_reason(self):
        return Reason.Shaming if self.details.startswith('shaming') else \
            Reason.Offensive if self.details.startswith('insult') else \
            Reason.Spam if self.details.startswith('spam') else \
            Reason.Other if self.details.startswith('other') else Reason.No

    def get_action(self):
        if self.is_warning():
            if self.details == ModAction.warnings['spam']:
                action = "Warning: Spam"
            elif self.details == ModAction.warnings['stalling']:
                action = "Warning: Time burner"
            else:
                action = self.details  # "warning"
        elif self.action == 'chatTimeout':
            if self.details.startswith('shaming'):
                action = "Timeout: Accusations"
            elif self.details.startswith('insult'):
                action = "Timeout: Insult"
            elif self.details.startswith('spam'):
                action = "Timeout: Spam"
            elif self.details.startswith('other'):
                action = "Timeout: Other"
            else:
                action = "Timeout"
        else:
            action = ModAction.actions.get(self.action, self.action)
        return f'<b>{action}</b>'

    def get_full_action(self):
        if self.action == "cheatDetected" and self.details.startswith("game "):
            return f'<a class="text-info" href="https://lichess.org/{self.details[5:]}" ' \
                   f'target="_blank">{self.get_action()}</a>'
        if self.details:
            style = f' style="text-decoration:none;"' if self.is_warning() else ""
            return f'<abbr title="{self.details}"{style}>{self.get_action()}</abbr>'
        else:
            return self.get_action()

    def get_date(self, now_utc):
        return timestamp_to_abbr_ago(self.date, now_utc)

    def get_datetime(self):
        return datetime.fromtimestamp(self.date // 1000, tz=tz.tzutc())

    def is_old(self, now_utc):
        return self.get_datetime() + relativedelta(months=6) < now_utc

    def is_new(self, now_utc):
        return self.get_datetime() + timedelta(minutes=TIMEOUT_RANGE[1]) > now_utc

    def get_date_class(self, now_utc):
        if self.is_old(now_utc):
            return "text-muted"
        if self.is_new(now_utc):
            return "table-warning"
        return ""  # "bg-info"

    def get_class(self, now_utc):
        if self.action in ['engine', 'booster', 'troll', 'alt', 'closeAccount']:
            return "table-danger"
        if self.action in ['cheatDetected']:
            return "table-warning"
        if self.action in ['permissions', 'setTitle', 'appealPost',
                           'unengine', 'unbooster', 'untroll', 'unalt', 'reopenAccount']:
            return "table-info"
        if self.is_warning():
            return "table-secondary" if self.is_old(now_utc) else "table-info"
        return self.get_date_class(now_utc)

    def get_table_row(self, now_utc):
        class_mod = " table-warning" if self.is_new(now_utc) else ""
        row = f'<tr>' \
              f'<td class="text-left align-middle {self.get_date_class(now_utc)}">{self.get_date(now_utc)}</td>' \
              f'<td class="text-left align-middle{class_mod}">{self.get_mod_name()}</td>' \
              f'<td colspan="2" class="text-left align-middle {self.get_class(now_utc)}">{self.get_full_action()}</td>' \
              f'</tr>'
        return row

    def is_combinable(self, action_stack, now_utc):
        if not action_stack:
            return True
        if self.action != action_stack[0].action:
            return False
        if self.details != action_stack[0].details:
            return False
        if self.mod_id != action_stack[0].mod_id:
            return False
        return action_stack[0].is_old(now_utc) == self.is_old(now_utc)


class BoostModAction(ModAction):
    def __init__(self, data):
        super().__init__(data)

    def get_special_action(self):
        if self.is_warning():
            if self.mod_id == "lichess" and self.details == "Warning: possible sandbagging":
                return "Auto warning: sandbagging"
            if self.details == "Warning: Sandbagging":
                return "Warning: Sandbagging"
            if self.mod_id == "lichess" and self.details == "Warning: possible boosting":
                return "Auto warning: boosting"
            if self.details == "Warning: Boosting":
                return "Warning: Boosting"
            if self.details in ["Warning: Failure to start tournament games", "Warning: Throwing casual games"]:
                return self.details
        return None

    def get_action(self):
        action = self.get_special_action()
        if action:
            return f'<b>{action}</b>'
        return super().get_action()

    def get_class(self, now_utc):
        action = self.get_special_action()
        if action:
            if action.startswith("Auto warning:"):
                return "table-success" if self.is_old(now_utc) else "table-warning"
            else:
                return "table-success" if self.is_old(now_utc) else "table-danger"
        if self.action in ['engine', 'booster', 'alt', 'closeAccount']:
            return "table-danger"
        if self.action in ['troll', 'permissions', 'setTitle',
                           'unengine', 'unbooster', 'unalt', 'reopenAccount']:
            return "table-info"
        if self.action in ['cheatDetected']:
            return "table-warning"
        if self.is_warning():
            return "table-secondary" if self.is_old(now_utc) else "table-info"
        return self.get_date_class(now_utc)


class ChatModAction(ModAction):
    chat_warnings = [ModAction.warnings['shaming'], ModAction.warnings['insult'], ModAction.warnings['trolling'],
                     ModAction.warnings['spam'], ModAction.warnings['ad'], ModAction.warnings['team_ad'],
                     "Warning: Inappropriate (personal/sex-related)", "Warning: Excessive draw offers / takeback requests",
                     "Warning: Abusing Reports"]

    def __init__(self, data):
        super().__init__(data)

    @classmethod
    def from_timeout_data(cls, data):
        d = {
            'mod': data.get('mod', ""),
            'action': 'chatTimeout',
            'date': data['date'],
            'details': data.get('reason', "")
        }
        return cls(d)

    def get_class(self, now_utc):
        if self.is_warning():
            if self.details in ChatModAction.chat_warnings:
                return "table-secondary" if self.is_old(now_utc) else "table-warning"
            return "table-muted" if self.is_old(now_utc) else "table-info"
        if self.action in ['engine', 'booster', 'troll', 'alt', 'closeAccount']:
            return "table-danger"
        if self.action in ['terminateTournament', 'cheatDetected']:
            return "table-secondary" if self.is_old(now_utc) else "table-warning"
        if self.action in ['deletePost', 'chatTimeout']:
            return "table-secondary" if self.is_old(now_utc) else "table-success"
        if self.action in ['permissions', 'setTitle', 'appealPost', 'setKidMode',
                           'unengine', 'unbooster', 'untroll', 'unalt', 'reopenAccount']:
            return "table-info"
        return self.get_date_class(now_utc)

    def is_timeout(self):
        return self.action == 'chatTimeout'

    def is_shaming(self):
        return self.details == ModAction.warnings['shaming']

    def is_insult(self):
        return self.details == ModAction.warnings['insult']

    def is_spam(self):
        return self.details == ModAction.warnings['spam']

    def is_trolling(self):
        return self.details == ModAction.warnings['trolling']

    def is_ad(self):
        return self.details == ModAction.warnings['ad']

    def is_team_ad(self):
        return self.details == ModAction.warnings['team_ad']

    def is_comm_warning(self):
        return self.action == 'modMessage' and (
            self.is_shaming() or self.is_insult() or self.is_spam() or self.is_trolling() or
            self.is_ad() or self.is_team_ad() or self.details.startswith("Warning: Excessive"))

    def is_SB(self):
        return self.action == 'troll'

    def is_kidMode(self):
        return self.action == 'setKidMode'


def warn_user(username, subject, mod):
    try:
        url = f"https://lichess.org/mod/{username}/warn?subject={subject}"
        r = mod.api.post(ApiType.ApiWarn, url, token=mod.token)
        if r.status_code == 200:
            log(f"WARNING @{username}: {subject}", True, True, 2)
            return True
    except Exception as exception:
        log_exception(exception)
    return False


def warn_sandbagging(username, mod):
    return warn_user(username, "Warning: Sandbagging", mod)


def warn_failure_to_start(username, mod):
    return warn_user(username, "Warning: Failure to start tournament games", mod)


def warn_boosting(username, mod):
    return warn_user(username, "Warning: Boosting", mod)


def mark_booster(username, mod):
    try:
        url = f"https://lichess.org/mod/{username}/booster/true"
        r = mod.api.post(ApiType.ApiBooster, url, token=mod.token)
        if r.status_code == 200:
            log(f'MARK BOOST: @{username}', True, True, 2)
            return True
    except Exception as exception:
        log_exception(exception)
    return False


class WarningStats:
    def __init__(self):
        self.active = 0
        self.total = 0

    def add(self, action, now_utc):
        self.total += 1
        if not action.is_old(now_utc):
            self.active += 1

    def get_active(self):
        return self.active if self.active else "&mdash;"

    def get_total(self):
        return self.total if self.total else "&mdash;"


def get_boost_reports(mod):
    try:
        url = f"https://lichess.org/report/list/boost"
        r = mod.api.get(ApiType.ReportListBoost, url, token=mod.token)
        if r.status_code != 200:
            raise Exception(f"ERROR /report/list/boost: Status Code {r.status_code}")
        return r.json()
    except Exception as exception:
        log_exception(exception)
    return None


class Notes:
    def __init__(self):
        self.username = ""
        self.content = []

    def clear(self):
        self.username = ""
        self.content = []

    def add(self, msg):
        if not msg:
            return
        if msg.username.lower() == self.username.lower():
            self.content.append(html.escape(msg.text))
        else:
            self.username = msg.username
            self.content = [html.escape(msg.text)]

    def __str__(self):
        if not self.username:
            return ""
        content = [f'{self.username}: "{text}"' for text in self.content]
        return '\n'.join(content).replace('"', '&quot;')


def decode_string(text, mod):
    try:
        text = base64.b64decode(text)
        data = read_notes("lol", mod)
        note = data[0]['text'].encode("ascii")
        key = hashlib.sha512(note).digest()
        key = (key * int(math.ceil(len(text) / len(key))))[:len(text)]
        decoded = bytes(a ^ b for (a, b) in zip(text, key))
        text_decoded = bytearray(len(decoded) * 8 // 6)
        for i in range(len(decoded) // 3):
            b = struct.unpack('bbb', decoded[i * 3: (i + 1) * 3])
            text_decoded[i * 4 + 0] = b[0] & 0b00111111
            text_decoded[i * 4 + 1] = ((b[1] << 2) & 0b00111100) | ((b[0] >> 6) & 0b00000011)
            text_decoded[i * 4 + 2] = ((b[2] << 4) & 0b00110000) | ((b[1] >> 4) & 0b00001111)
            text_decoded[i * 4 + 3] = (b[2] >> 2) & 0b00111111
        out = [url_symbols[c] for c in text_decoded]
        return "".join(out).replace(' ', "")
    except:
        return None


class Error500:
    def __init__(self, start, status_code):
        self.start = start
        self.end = None
        self.description = f"Lichess internal problem {status_code} (server restart?)"

    def is_ongoing(self):
        return self.end is None

    def complete(self, dt):
        self.end = dt

    def __str__(self):
        if self.end:
            if self.start.day == self.end.day and self.start.month == self.end.month and self.start.year == self.end.year:
                return f"{self.description} from {self.start:%Y-%m-%d %H:%M} to {self.end:%H:%M} UTC"
            return f"{self.description} from {self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} UTC"
        return f"{self.description} at {self.start:%Y-%m-%d %H:%M} UTC"
