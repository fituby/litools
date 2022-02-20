import requests
import json
from datetime import datetime
from dateutil import tz
from dateutil.relativedelta import relativedelta
from enum import IntEnum
import yaml
import traceback
import os

config_file = "config.yml"
token: str = None
log_file: str = None
port: int = 5000


STYLE_WORD_BREAK = "word-break:break-word;"  # "word-break:break-all;"


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
    global token, log_file, port
    if token is None:
        try:
            with open(os.path.abspath(f"./{config_file}")) as stream:
                config = yaml.safe_load(stream)
                token = config.get('token', "")
                log_file = config.get('log', "")
                port = config.get('port', port)
        except Exception as e:
            print(f"There appears to be a syntax problem with your config.yml: {e}")
            token = ""
            log_file = ""


def get_token():
    load_config()
    return token


def get_port():
    load_config()
    return port


def get_ndjson(url, Accept="application/x-ndjson"):
    headers = {'Accept': Accept,
               'Authorization': f"Bearer {token}",
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


def timestamp_to_ago(ts_ms, now=None):
    t = datetime.fromtimestamp(ts_ms // 1000)  #, tz=tz.tzutc()) --> omitted to use local time
    if now is None:
        now = datetime.now()
    years = relativedelta(now, t).years
    if years >= 1:
        return "1 year ago" if years == 1 else f"{years} years ago"
    months = relativedelta(now, t).months
    if months >= 1:
        return "1 month ago" if months == 1 else f"{months} months ago"
    weeks = relativedelta(now, t).weeks
    if weeks >= 1:
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    days = relativedelta(now, t).days
    if days >= 1:
        return "1 day ago" if days == 1 else f"{days} days ago"
    hours = relativedelta(now, t).hours
    if hours >= 1:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    minutes = relativedelta(now, t).minutes
    if minutes >= 1:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    seconds = relativedelta(now, t).seconds
    if seconds >= 1:
        return "1 second ago" if seconds == 1 else f"{seconds} seconds ago"


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
