import requests
import json
from datetime import datetime
from dateutil import tz
from dateutil.relativedelta import relativedelta
from enum import IntEnum
import yaml
import traceback
import os
import html
import re

config_file = "config.yml"
token: str = None
log_file: str = None
port: int = 5000
embed_lichess = False


STYLE_WORD_BREAK = "word-break:break-word;"  # "word-break:break-all;"
re_link = re.compile(r'\bhttps?:\/\/(?:www\.)?[-_a-zA-Z0-9]*\.?lichess\.(?:ovh|org)\/[-a-zA-Z0-9@:%&\?\$\.,_\+~#=\/]+\b', re.IGNORECASE)


country_flags = {'GB-WLS': '🏴󠁧󠁢󠁷󠁬󠁳󠁿', 'GB-SCT': '🏴󠁧󠁢󠁳󠁣󠁴󠁿󠁧󠁢󠁷󠁬󠁳󠁿', 'GB-ENG': '🏴󠁧󠁢󠁥󠁮󠁧󠁿', 'GB-NIR': '🇬🇧NIR󠁧󠁢󠁥󠁮󠁧󠁿',
        'AD': '🇦🇩', 'AE': '🇦🇪', 'AF': '🇦🇫', 'AG': '🇦🇬', 'AI': '🇦🇮', 'AL': '🇦🇱', 'AM': '🇦🇲', 'AO': '🇦🇴', 'AQ': '🇦🇶', 'AR': '🇦🇷', 'AS': '🇦🇸', 'AT': '🇦🇹', 'AU': '🇦🇺', 'AW': '🇦🇼', 'AX': '🇦🇽', 'AZ': '🇦🇿', 'BA': '🇧🇦', 'BB': '🇧🇧', 'BD': '🇧🇩', 'BE': '🇧🇪', 'BF': '🇧🇫', 'BG': '🇧🇬', 'BH': '🇧🇭', 'BI': '🇧🇮', 'BJ': '🇧🇯', 'BL': '🇧🇱', 'BM': '🇧🇲', 'BN': '🇧🇳', 'BO': '🇧🇴', 'BQ': '🇧🇶', 'BR': '🇧🇷', 'BS': '🇧🇸', 'BT': '🇧🇹', 'BV': '🇧🇻', 'BW': '🇧🇼', 'BY': '🇧🇾', 'BZ': '🇧🇿', 'CA': '🇨🇦', 'CC': '🇨🇨', 'CD': '🇨🇩', 'CF': '🇨🇫', 'CG': '🇨🇬', 'CH': '🇨🇭', 'CI': '🇨🇮', 'CK': '🇨🇰', 'CL': '🇨🇱', 'CM': '🇨🇲', 'CN': '🇨🇳', 'CO': '🇨🇴', 'CR': '🇨🇷', 'CU': '🇨🇺', 'CV': '🇨🇻', 'CW': '🇨🇼', 'CX': '🇨🇽', 'CY': '🇨🇾', 'CZ': '🇨🇿', 'DE': '🇩🇪', 'DJ': '🇩🇯', 'DK': '🇩🇰', 'DM': '🇩🇲', 'DO': '🇩🇴', 'DZ': '🇩🇿', 'EC': '🇪🇨', 'EE': '🇪🇪', 'EG': '🇪🇬', 'EH': '🇪🇭', 'ER': '🇪🇷', 'ES': '🇪🇸', 'ET': '🇪🇹', 'FI': '🇫🇮', 'FJ': '🇫🇯', 'FK': '🇫🇰', 'FM': '🇫🇲', 'FO': '🇫🇴', 'FR': '🇫🇷', 'GA': '🇬🇦', 'GB': '🇬🇧', 'GD': '🇬🇩', 'GE': '🇬🇪', 'GF': '🇬🇫', 'GG': '🇬🇬', 'GH': '🇬🇭', 'GI': '🇬🇮', 'GL': '🇬🇱', 'GM': '🇬🇲', 'GN': '🇬🇳', 'GP': '🇬🇵', 'GQ': '🇬🇶', 'GR': '🇬🇷', 'GS': '🇬🇸', 'GT': '🇬🇹', 'GU': '🇬🇺', 'GW': '🇬🇼', 'GY': '🇬🇾', 'HK': '🇭🇰', 'HM': '🇭🇲', 'HN': '🇭🇳', 'HR': '🇭🇷', 'HT': '🇭🇹', 'HU': '🇭🇺', 'ID': '🇮🇩', 'IE': '🇮🇪', 'IL': '🇮🇱', 'IM': '🇮🇲', 'IN': '🇮🇳', 'IO': '🇮🇴', 'IQ': '🇮🇶', 'IR': '🇮🇷', 'IS': '🇮🇸', 'IT': '🇮🇹', 'JE': '🇯🇪', 'JM': '🇯🇲', 'JO': '🇯🇴', 'JP': '🇯🇵', 'KE': '🇰🇪', 'KG': '🇰🇬', 'KH': '🇰🇭', 'KI': '🇰🇮', 'KM': '🇰🇲', 'KN': '🇰🇳', 'KP': '🇰🇵', 'KR': '🇰🇷', 'KW': '🇰🇼', 'KY': '🇰🇾', 'KZ': '🇰🇿', 'LA': '🇱🇦', 'LB': '🇱🇧', 'LC': '🇱🇨', 'LI': '🇱🇮', 'LK': '🇱🇰', 'LR': '🇱🇷', 'LS': '🇱🇸', 'LT': '🇱🇹', 'LU': '🇱🇺', 'LV': '🇱🇻', 'LY': '🇱🇾', 'MA': '🇲🇦', 'MC': '🇲🇨', 'MD': '🇲🇩', 'ME': '🇲🇪', 'MF': '🇲🇫', 'MG': '🇲🇬', 'MH': '🇲🇭', 'MK': '🇲🇰', 'ML': '🇲🇱', 'MM': '🇲🇲', 'MN': '🇲🇳', 'MO': '🇲🇴', 'MP': '🇲🇵', 'MQ': '🇲🇶', 'MR': '🇲🇷', 'MS': '🇲🇸', 'MT': '🇲🇹', 'MU': '🇲🇺', 'MV': '🇲🇻', 'MW': '🇲🇼', 'MX': '🇲🇽', 'MY': '🇲🇾', 'MZ': '🇲🇿', 'NA': '🇳🇦', 'NC': '🇳🇨', 'NE': '🇳🇪', 'NF': '🇳🇫', 'NG': '🇳🇬', 'NI': '🇳🇮', 'NL': '🇳🇱', 'NO': '🇳🇴', 'NP': '🇳🇵', 'NR': '🇳🇷', 'NU': '🇳🇺', 'NZ': '🇳🇿', 'OM': '🇴🇲', 'PA': '🇵🇦', 'PE': '🇵🇪', 'PF': '🇵🇫', 'PG': '🇵🇬', 'PH': '🇵🇭', 'PK': '🇵🇰', 'PL': '🇵🇱', 'PM': '🇵🇲', 'PN': '🇵🇳', 'PR': '🇵🇷', 'PS': '🇵🇸', 'PT': '🇵🇹', 'PW': '🇵🇼', 'PY': '🇵🇾', 'QA': '🇶🇦', 'RE': '🇷🇪', 'RO': '🇷🇴', 'RS': '🇷🇸', 'RU': '🇷🇺', 'RW': '🇷🇼', 'SA': '🇸🇦', 'SB': '🇸🇧', 'SC': '🇸🇨', 'SD': '🇸🇩', 'SE': '🇸🇪', 'SG': '🇸🇬', 'SH': '🇸🇭', 'SI': '🇸🇮', 'SJ': '🇸🇯', 'SK': '🇸🇰', 'SL': '🇸🇱', 'SM': '🇸🇲', 'SN': '🇸🇳', 'SO': '🇸🇴', 'SR': '🇸🇷', 'SS': '🇸🇸', 'ST': '🇸🇹', 'SV': '🇸🇻', 'SX': '🇸🇽', 'SY': '🇸🇾', 'SZ': '🇸🇿', 'TC': '🇹🇨', 'TD': '🇹🇩', 'TF': '🇹🇫', 'TG': '🇹🇬', 'TH': '🇹🇭', 'TJ': '🇹🇯', 'TK': '🇹🇰', 'TL': '🇹🇱', 'TM': '🇹🇲', 'TN': '🇹🇳', 'TO': '🇹🇴', 'TR': '🇹🇷', 'TT': '🇹🇹', 'TV': '🇹🇻', 'TW': '🇹🇼', 'TZ': '🇹🇿', 'UA': '🇺🇦', 'UG': '🇺🇬', 'UM': '🇺🇲', 'US': '🇺🇸', 'UY': '🇺🇾', 'UZ': '🇺🇿', 'VA': '🇻🇦', 'VC': '🇻🇨', 'VE': '🇻🇪', 'VG': '🇻🇬', 'VI': '🇻🇮', 'VN': '🇻🇳', 'VU': '🇻🇺', 'WF': '🇼🇫', 'WS': '🇼🇸', 'YE': '🇾🇪', 'YT': '🇾🇹', 'ZA': '🇿🇦', 'ZM': '🇿🇲', 'ZW': '🇿🇼',
        'EU': '🇪🇺', '_pirate': '🏴‍☠️', '_rainbow': '🏳️‍🌈', '_united-nations': '🇺🇳', '_earth': '🌍',
        '_lichess': '<img class="align-top" style="height:19px; width:19px;" src="https://lichess.org/favicon.ico"/>'}
country_names = {'GB-WLS': 'Wales󠁧󠁢󠁷󠁬󠁳󠁿', 'GB-SCT': 'Scotland󠁢󠁳󠁣󠁴󠁿󠁧󠁢󠁷󠁬󠁳󠁿',
         'GB-ENG': 'England󠁢󠁥󠁮󠁧󠁿', 'GB-NIR': 'Northern Ireland󠁢󠁥󠁮󠁧󠁿',
         "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AG": "Antigua and Barbuda",
         "AI": "Anguilla", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AQ": "Antarctica",
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
         "ER": "Eritrea", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji",
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
         "_united-nations": "United Nations", '_earth': 'Earth', "_lichess": "Lichess Flag"}


def load_config():
    global token, log_file, port, embed_lichess
    if token is None:
        try:
            with open(os.path.abspath(f"./{config_file}")) as stream:
                config = yaml.safe_load(stream)
                token = config.get('token', "")
                log_file = config.get('log', "")
                port = config.get('port', port)
                embed_lichess = config.get('embed_lichess', False)
        except Exception as e:
            print(f"There appears to be a syntax problem with your {config_file}: {e}")
            token = ""
            log_file = ""


def get_token():
    load_config()
    return token


def get_port():
    load_config()
    return port


def get_embed_lichess():
    load_config()
    return embed_lichess


def get_ndjson(url, Accept="application/x-ndjson"):
    headers = {'Accept': Accept,
               'Authorization': f"Bearer {token}"
    }
    r = requests.get(url, allow_redirects=True, headers=headers)
    if r.status_code != 200:
        try:
            i1 = url.find(".org/")
            i2 = url.rfind("/")
            api = url[i1 + 4:i2 + 1]
        except:
            api = url
        raise Exception(f"{api}: Status code = {r.status_code}")
    content = r.content.decode("utf-8")
    lines = content.split("\n")[:-1]
    data = [json.loads(line) for line in lines]
    return data


def timestamp_to_ago(ts_ms, now_utc=None):
    t = datetime.fromtimestamp(ts_ms // 1000, tz=tz.tzutc())
    if now_utc is None:
        now_utc = datetime.now(tz=tz.tzutc())
    years = relativedelta(now_utc, t).years
    if years >= 1:
        return "1 year ago" if years == 1 else f"{years} years ago"
    months = relativedelta(now_utc, t).months
    if months >= 1:
        return "1 month ago" if months == 1 else f"{months} months ago"
    weeks = relativedelta(now_utc, t).weeks
    if weeks >= 1:
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    days = relativedelta(now_utc, t).days
    if days >= 1:
        return "1 day ago" if days == 1 else f"{days} days ago"
    hours = relativedelta(now_utc, t).hours
    if hours >= 1:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    minutes = relativedelta(now_utc, t).minutes
    if minutes >= 1:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    seconds = relativedelta(now_utc, t).seconds
    if seconds >= 1:
        return "1 second ago" if seconds == 1 else f"{seconds} seconds ago"
    if seconds == 0:
        return "now"
    return "right now"


def timestamp_to_abbr_ago(ts_ms, now_utc=None):
    t = datetime.fromtimestamp(ts_ms // 1000, tz=tz.tzutc())
    return f'<abbr title="{t:%Y-%m-%d %H:%M:%S}" style="text-decoration:none;">{timestamp_to_ago(ts_ms, now_utc)}</abbr>'


def deltaseconds(dt2, dt1):
    diff = dt2 - dt1
    return diff.days*24*60*60 + diff.seconds


def deltaperiod(dt2, dt1, short=False, show_seconds=False):
    seconds = deltaseconds(dt2, dt1)
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
        out = f"{minutes}m" if short else f"{minutes} minute{'' if minutes == 1 else 's'}"
        if seconds == 0:
            return out
        return f"{out}{seconds:02d}s" if short else f"{out} {seconds} second{'' if seconds == 1 else 's'}"
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


def log(text, to_print=False):
    global log_file
    if log_file is None:
        load_config()
    if not log_file:
        return
    try:
        now_utc = datetime.now(tz=tz.tzutc())
        with open(log_file, "a", encoding="utf-8") as file:
            line = f"{now_utc: %Y-%m-%d %H:%M:%S}: {text}"
            if to_print:
                print(line)
            file.write(f"{line}\n")
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        log_file = ""


def get_user_link(username, no_name="Unknown User"):
    if username:
        if len(username) > 10:
            user_url = username
            username = f'{username[:9]}&hellip;'
        else:
            user_url = username.lower()
        return f'<a class="text-info" href="https://lichess.org/@/{user_url}" target="_blank">{username}</a>'
    return f'<i>{no_name}</i>'


def get_notes(username, mod_log_data=None):
    info = []
    try:
        data = mod_log_data.get('notes') if mod_log_data else None
        if not data:
            headers = {'Authorization': f"Bearer {get_token()}"}
            url = f"https://lichess.org/api/user/{username}/note"
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                raise Exception(f"ERROR /api/user/{username}/note: Status Code {r.status_code}")
            data = r.json()
        now_utc = datetime.now(tz=tz.tzutc())
        for d in data:
            for note in d:
                author = None
                author_data = note.get('from')
                if author_data:
                    author = author_data.get('name')
                author = get_user_link(author)
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
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        if not info:
            return None
    return f'<table class="table table-sm table-striped table-hover border text-nowrap">' \
           f'<tbody>{"".join(info)}</tbody></table>' if info else ""


def add_note(username, note):
    try:
        headers = {'Authorization': f"Bearer {get_token()}"}
        data = {'text': note,
                'mod': True}
        url = f"https://lichess.org/api/user/{username}/note"
        r = requests.post(url, headers=headers, json=data)
        return r.status_code == 200
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
    return False


def load_mod_log(username):
    try:
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = f"https://lichess.org/api/user/{username}/mod-log"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            raise Exception(f"ERROR /api/user/{username}/mod-log: Status Code {r.status_code}")
        return r.json()
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
    return None


class ModActionType(IntEnum):
    Standard = 0
    Boost = 1
    Chat = 2


def get_mod_log(data, action_type=ModActionType.Standard):
    actions = []
    try:
        for d in data['logs']:
            for action_data in d:
                if action_type == ModActionType.Boost:
                    actions.append(BoostModAction(action_data))
                elif action_type == ModActionType.Chat:
                    actions.append(ChatModAction(action_data))
                else:
                    actions.append(ModAction(action_data))
        ModAction.update_names(actions)
        now_utc = datetime.now(tz=tz.tzutc())
        info = [action.get_table_row(now_utc) for action in actions]
        out_info = f'<table class="table table-sm table-striped table-hover border mb-0">' \
                   f'<tbody>{"".join(info)}</tbody></table>' if info else ""
        return out_info, actions
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
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

    @staticmethod
    def update_names(actions):
        ids = set()
        for action in actions:
            if action.mod_id and action.mod_id not in ModAction.names:
                ids.add(action.mod_id)
        ids = list(ids)
        if ids:
            headers = {'Authorization': f"Bearer {get_token()}"}
            url = f"https://lichess.org/api/users/status?ids={','.join(ids)}"
            r = requests.get(url, headers=headers)
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

    def get_action(self):
        if self.is_warning():
            if self.details == "Warning: Spam is not permitted":
                action = "Warning: Spam"
            elif self.details == "Warning: leaving games / stalling on time":
                action = "Warning: time burner"
            else:
                action = self.details  # "warning"
        elif self.action == 'chatTimeout':
            if self.details.startswith('shaming'):
                action = "Timeout: Shaming"
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

    def get_date_class(self, now_utc):
        if self.is_old(now_utc):
            return "text-muted"
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
        row = f'<tr>' \
              f'<td class="text-left align-middle {self.get_date_class(now_utc)}">{self.get_date(now_utc)}</td>' \
              f'<td class="text-left align-middle">{self.get_mod_name()}</td>' \
              f'<td class="text-left align-middle {self.get_class(now_utc)}">{self.get_full_action()}</td>' \
              f'</tr>'
        return row


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
        if self.action in ['cheatDetected', 'troll', 'permissions', 'setTitle',
                           'unengine', 'unbooster', 'unalt', 'reopenAccount']:
            return "table-info"
        if self.is_warning():
            return "table-secondary" if self.is_old(now_utc) else "table-info"
        return self.get_date_class(now_utc)


class ChatModAction(ModAction):
    def __init__(self, data):
        super().__init__(data)

    def get_class(self, now_utc):
        if self.is_warning():
            if self.details in ["Warning: Accusations", "Warning: Offensive language",
                                "Warning: Chat/Forum trolling", "Warning: spam is not permitted"]:
                return "table-secondary" if self.is_old(now_utc) else "table-warning"
            return "table-muted" if self.is_old(now_utc) else "table-info"
        if self.action in ['engine', 'booster', 'troll', 'alt', 'closeAccount']:
            return "table-danger"
        if self.action in ['deletePost', 'terminateTournament', 'cheatDetected']:
            return "table-secondary" if self.is_old(now_utc) else "table-warning"
        if self.action in ['chatTimeout']:
            return "table-secondary" if self.is_old(now_utc) else "table-success"
        if self.action in ['permissions', 'setTitle', 'appealPost', 'setKidMode',
                           'unengine', 'unbooster', 'untroll', 'unalt', 'reopenAccount']:
            return "table-info"
        return self.get_date_class(now_utc)


def warn_user(username, subject):
    try:
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = f"https://lichess.org/mod/{username}/warn?subject={subject}"
        r = requests.post(url, headers=headers)
        return r.status_code == 200
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
    return False


def warn_sandbagging(username):
    return warn_user(username, "Warning: Sandbagging")


def warn_boosting(username):
    return warn_user(username, "Warning: Boosting")


def mark_booster(username):
    try:
        headers = {'Authorization': f"Bearer {get_token()}"}
        url = f"https://lichess.org/mod/{username}/booster/true"
        r = requests.post(url, headers=headers)
        return r.status_code == 200
    except Exception as exception:
        traceback.print_exception(type(exception), exception, exception.__traceback__)
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
