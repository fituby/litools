import html
import re
from enum import IntFlag
from elements import Reason, TournType, log_exception
from elements import STYLE_WORD_BREAK


class Lang(IntFlag):
    No = 0
    Spam = 2**0
    En = 2**1
    Ru = 2**2
    De = 2**3
    Es = 2**4
    It = 2**5
    Hi = 2**6
    Fr = 2**7
    Tr = 2**8


LANGUAGES = {
    Lang.En: "English",
    Lang.Ru: "Russian",
    Lang.De: "German",
    Lang.Es: "Spanish",
    Lang.It: "Italian",
    Lang.Hi: "Hindi",
    Lang.Fr: "French",
    Lang.Tr: "Turkish",
    Lang.Spam: "Spam"
}


class EvalResult:
    def __init__(self, text):
        self.scores = [0] * Reason.Size
        self.ban_points = [0] * Reason.Size
        self.languages = Lang.No
        try:
            self.element = html.escape(text)
        except Exception as exception:
            print(f"ERROR when processing: {text}")
            self.element = text
            log_exception(exception)

    def __iadd__(self, o):
        for i in range(Reason.Size):
            self.scores[i] += o.scores[i]
            self.ban_points[i] += o.ban_points[i]
        self.languages |= o.languages
        return self

    def total_score(self):
        return sum(self.scores)


class TextVariety:
    def __init__(self, max_score=None, ban=None, reason=Reason.Spam, info="TextVariety", class_name="text-warning"):
        self.max_score = max_score
        self.ban = ban
        self.reason = reason
        self.lang = Lang.No
        self.info = info
        self.class_name = class_name
        self.exclude_tournaments = None

    def eval(self, original_msg, res, it):
        result = EvalResult(original_msg)
        if not original_msg:
            return result
        text = re.sub(r'[^\w]', "", original_msg)
        text_wo_spaces = re.sub(r'[^\s]', "", original_msg)
        num_special_symbols = len(text_wo_spaces) - len(text)
        s = set(text)
        if len(s) < 12:
            if len(s) in [2, 3, 4] and num_special_symbols <= 30 and '0' in s and '1' in s and len(text) >= 35:
                result.scores[self.reason] += 50 if len(text) >= 45 else 20  # binary code
            elif len(s) == 2 and len(text) >= 35:
                result.scores[self.reason] += 80
            elif len(s) == 3 and len(text) >= 45:
                result.scores[self.reason] += 80
            elif 3 * len(s) + 50 < len(text):
                result.scores[self.reason] += 80
            elif 3 * len(s) + 20 < len(text):
                result.scores[self.reason] += 50
            elif 3 * len(s) + 8 < len(text):
                result.scores[self.reason] += 10
            if num_special_symbols > 50:
                result.scores[self.reason] += 80
            elif num_special_symbols > 30 and num_special_symbols > 3 * len(s):
                result.scores[self.reason] += 50
            elif num_special_symbols > 15 and num_special_symbols > 3 * len(s):
                result.scores[self.reason] += 10
            if self.max_score:
                result.scores[self.reason] = min(self.max_score, result.scores[self.reason])
            if result.scores[self.reason] > 0:
                is_ban = False if not self.ban else 0 < self.ban <= result.scores[self.reason]
                info = f"[{'Suggested timeout' if is_ban else 'Reason'}]  {Reason.to_text(self.reason)}"
                if self.info:
                    str_lang = f"{LANGUAGES[self.lang]}: " if self.lang != Lang.No else ""
                    info = f'{info}\n{str_lang}{self.info}'
                result.element = f'<abbr class="{self.class_name}" title="{info}" style="{STYLE_WORD_BREAK}' \
                                 f'text-decoration:none;">{html.escape(original_msg)}</abbr>'
                if self.ban and self.reason != Reason.No:
                    result.ban_points[self.reason] = result.scores[self.reason] / self.ban
                result.languages |= self.lang
                return result
        it += 1
        if it < len(res):
            new_result = res[it].eval(original_msg, res, it)
            result += new_result
            result.element = new_result.element
        return result


class Re:
    def __init__(self, str_re, score=10, max_score=None, ban=None, reason=Reason.No, info="",
                 class_name="text-warning", is_separate_word=True, is_capturing_groups=False, exclude_tournaments=None):
        self.exclude_tournaments = exclude_tournaments
        self.is_capturing_groups = is_capturing_groups
        if is_capturing_groups:
            assert str_re[0] == "(" and str_re[-1] == ")"
        else:
            str_re = re.sub(r'\(', r"(?:", str_re)  # (...) is a capturing group, (?:...) is a non-capturing group
        if is_separate_word:
            str_re = r"\b{}\b".format(str_re)
        self.re = re.compile(str_re, re.IGNORECASE)
        self.score = score
        self.max_score = (-max_score * score) if max_score and max_score < 0 else max_score
        self.ban = ban
        self.reason = reason
        self.lang = Lang.No
        self.info = info
        self.class_name = class_name

    def eval(self, original_msg, res, it):
        result = EvalResult(original_msg)
        if not original_msg:
            return result
        elements = self.re.findall(original_msg)
        if self.is_capturing_groups:
            for i in range(len(elements)):
                elements[i] = elements[i][0]
            new_msgs = []
            j = 0
            for el in elements:
                i1 = original_msg.find(el, j)
                new_msgs.append(original_msg[j:i1])
                j = i1 + len(el)
            new_msgs.append(original_msg[j:])
        else:
            new_msgs = self.re.split(original_msg)
        if len(new_msgs) > 1:
            result.scores[self.reason] += self.score * (len(new_msgs) - 1)
            result.languages |= self.lang
        if self.max_score:
            result.scores[self.reason] = min(self.max_score, result.scores[self.reason])
        is_ban = False if not self.ban else (0 < self.ban <= result.scores[self.reason]
                                             or (self.ban < 0 and result.scores[self.reason] >= -self.ban * self.score))
        if self.ban and self.reason != Reason.No:
            result.ban_points[self.reason] = (result.scores[self.reason] / self.ban) if self.ban > 0 \
                else (result.scores[self.reason] / (-self.ban * self.score))
        it += 1
        for i in range(len(new_msgs)):
            if it < len(res):
                result_i = res[it].eval(new_msgs[i], res, it)
                new_msgs[i] = result_i.element
                result += result_i
            else:
                new_msgs[i] = html.escape(new_msgs[i])
        if len(new_msgs) == 1:
            result.element = new_msgs[0]
            return result
        for i in range(len(elements)):
            elements[i] = html.escape(elements[i])
            if self.reason == Reason.No:
                info = ""
            else:
                info = f"[{'Suggested timeout' if is_ban else 'Reason'}]  {Reason.to_text(self.reason)}"
            if self.info:
                str_lang = f"{LANGUAGES[self.lang]}: " if self.lang != Lang.No else ""
                str_sep = "\n" if info else ""
                info = f'{info}{str_sep}{str_lang}{self.info}'
                elements[i] = self.format_element(elements[i], info)
        elements.append("")
        result.element = "".join(f'{text}{element}' for text, element in zip(new_msgs, elements))
        return result

    def format_element(self, element, info):
        if info:
            return f'<abbr class="{self.class_name}" title="{info}" style="{STYLE_WORD_BREAK}text-decoration:none;">' \
                   f'{element}</abbr>'
        return f'<span class="{self.class_name}" style="{STYLE_WORD_BREAK}">{element}</span>'


class ReUser(Re):
    def __init__(self, str_re, score=10, max_score=None, ban=None, reason=Reason.No, info="", class_name="text-warning",
                 is_separate_word=True, is_capturing_groups=False):
        super().__init__(str_re, score, max_score, ban, reason, info, class_name, is_separate_word, is_capturing_groups)

    def format_element(self, element, info):
        i = max(element[:-1].rfind('/'), element[:-1].rfind('@'))
        name = element[i + 1:] if i >= 0 else element
        return f'<a class="{self.class_name}" href="https://lichess.org/@/{name.lower()}" target="_blank">{element}</a>'


list_res_variety = {
Lang.Spam: [
    TextVariety(reason=Reason.Spam, ban=80, info="TextVariety")
]
}

list_res = {
Lang.En: [
    # Critical
    Re(r'cancers?', 50, max_score=-2,  # added "s?"
       reason=Reason.Offensive, info="Critical: cancer"),
    Re(r'(ho?pe ((yo)?[uy](r (famil[yi]|m[ou]m|mother))?( and )*)+ (die|burn)s?|((die|burn)s? irl))', 90,
       reason=Reason.Offensive, ban=-1, info="Critical: Hope you die"),
    Re(r'^kill ((yo)?[uy]r ?(self|famil[yi]|m[ou]m|mother)( and )?)+', 90, is_separate_word=False,
       reason=Reason.Offensive, ban=-1, info="Critical: Kill yourself"),
    Re(r'(hang|neck) ((yo)?[uy]r ?(self|family)( and )?)+', 90,
       reason=Reason.Offensive, ban=-2, info="Critical: Hang yourself"),
    Re(r"k+y+s+'?(e?d|)", 100,  # added several "+" and "'?(e?d|)"
       reason=Reason.Offensive, info="Critical: kys"),
    # En: suppress self-deprecating
    Re(r"(me|i['`]?(\sa|)m(\snot|\sso|\ssuch|))\s(an?\s|)(idiot|stupid|no{2,10}b|gay|jerk|lo{1,10}ser|moron|retard(ed|)|trash|weak)", 5,  # added
       reason=Reason.Spam, info="I'm idiot"),
    # En
    Re(r'(f{1,20}|ph)(u|a|e){1,20}c?k{1,}\sme', 5,  # added
       reason=Reason.Offensive, info="fuck me"),
    Re(r'(f{1,20}|ph)(u|a|e){1,20}c?kk?(ers?|rs?|u|t|ing?|ign|en|e?d|tard?s?|face|off?|)', 15,  #'+'-->'{1,20}' + changed (...){1,20}  # added several "s?" and "k?"
       reason=Reason.Offensive, info="fuck"),
    Re(r'(f|ph)agg?([oi]t|)s?', 30,  # added "s?"
       reason=Reason.Offensive, ban=80, info="faggot"),
    Re(r'[ck]um(shots?|)',  # added "s?"
       reason=Reason.Offensive, info="cum"),
    Re(r'[ck]unt(ing?|ign|s|)', 30,  # added "|s"
       reason=Reason.Offensive, ban=80, info="cunt"),
    Re(r'abortion',
       reason=Reason.Other, info="abortion"),
    Re(r'adol(f|ph)',
       reason=Reason.Other, info="adolf"),
    Re(r'afraid', 5,
       reason=Reason.Offensive, info="afraid"),
    Re(r'anal(plug|sex|)',
       reason=Reason.Offensive, info="anal"),
    Re(r'anus',
       reason=Reason.Offensive, info="anus"),
    Re(r'arse(holes?|wipe|)',  # added "s?"
       reason=Reason.Offensive, info="arse"),
    Re(r'autist(ic|)',
       reason=Reason.Offensive, info="autist"),
    Re(r'dumb',
       reason=Reason.Offensive, info="dumb"),
    Re(r'(dumb|)ass',
       reason=Reason.Offensive, info="ass"),
    Re(r'ass?(hole|fag)s?', 20,  # added "s?"
       reason=Reason.Offensive, info="asshole"),
    Re(r'aus?c?hwitz',
       reason=Reason.Offensive, info="auschwitz"),
    Re(r'bastard?s?', 20,  # added "s?"
       reason=Reason.Offensive, ban=80, info="bastard"),
    Re(r'be[ea]{1,20}ch(es|)', 5,  # '+'-->{1,20}  # added "(es|)"
       reason=Reason.Offensive, info="beach"),
    Re(r'bit?ch(es|)', 20,  # added "(es|)"
       reason=Reason.Offensive, info="bitch"),
    Re(r'blow(job|)',
       reason=Reason.Other, info="blow"),
    Re(r'blumpkin',
       reason=Reason.Other, info="blumpkin"),
    Re(r'bollock',
       reason=Reason.Other, info="bollock"),
    Re(r'boner',
       reason=Reason.Other, info="boner"),
    Re(r'boobs?',  # added "s?"
       reason=Reason.Other, info="boob"),
    Re(r'bozos?',  # added
       reason=Reason.Other, info="bozo"),
    Re(r'braindead',  # added
       reason=Reason.Offensive, info="braindead"),
    Re(r'buggers?',  # added "s?"
       reason=Reason.Offensive, info="bugger"),
    Re(r'buk?kake',
       reason=Reason.Other, info="bukkake"),
    Re(r'bull?shit',
       reason=Reason.Offensive, info="bullshit"),
    Re(r'ch(e{1,20}a?|i{1,20})tt?(ing?|ign|er{1,20}s?|e?d|s?)', exclude_tournaments=[TournType.Study],
       reason=Reason.Shaming, info="cheater"),  # ea --> (e{1,20}a?|i{1,20}) added "s?", added "{1,20}"
    Re(r'chess(|-|_)bot(.?com)?', 50,
       reason=Reason.Spam, info="chess-bot.com"),
    Re(r'chickens?', 5,  # added "s?"
       reason=Reason.Offensive, info="chicken"),
    Re(r'chink',
       reason=Reason.Offensive, info="chick"),
    Re(r'clit(oris|ors?|)',  # added '|ors?'
       reason=Reason.Other, info="clitoris"),
    Re(r'clowns?', 20,  # added "s?"
       reason=Reason.Offensive, info="clown"),
    Re(r'cock(suc?k(ers?|ing?|ign|e?d)|)', 50,  # added "s?"
       reason=Reason.Offensive, info="cocksucker"),
    Re(r'condoms?',  # added "s?"
       reason=Reason.Offensive, info="condom"),
    Re(r'coons?', 15,  # added "s?"
       reason=Reason.Offensive, info="coon"),
    Re(r'coward?s?', 20,  # added "s?"
       reason=Reason.Offensive, info="coward"),
    Re(r'cry(baby|ing|)',
       reason=Reason.Offensive, info="cry"),
    Re(r'cunn?ilingus',  # added 's'
       reason=Reason.Other, info="cunnilingus"),
    Re(r'dic?k(head|face|suc?ker|)s?',  # added "s?"
       reason=Reason.Offensive, info="dick"),
    Re(r'dildos?',  # added "s?"
       reason=Reason.Other, info="dildo"),
    Re(r'dogg?ystyle',
       reason=Reason.Other, info="doggystyle"),
    Re(r'douche(bag|)', 20,
       reason=Reason.Offensive, info="douchebag"),
    Re(r'dykes?', 30,  # added "s?"
       reason=Reason.Offensive, info="dyke"),
    Re(r'engine', exclude_tournaments=[TournType.Study],
       reason=Reason.Shaming, info="engine"),
    Re(r'fck(er|r|u|k|t|ing?|ign|tard?|face|off?|e?d|)',
       reason=Reason.Offensive, info="fck"),
    Re(r'f[oa]llow\s?(me|(4|for)\s?f[oa]llow)', 25,  # added
       reason=Reason.Spam, info="follow"),
    Re(r'fo{1,10}l{1,10}(s|e?d|ing?|ign|)',  # added
       reason=Reason.Offensive, info="fool"),
    Re(r'foreskin',
       reason=Reason.Other, info="foreskin"),
    Re(r'gangbang',
       reason=Reason.Other, info="gangbang"),
    Re(r'gaye?s?', 30,  # added "e?s?"
       reason=Reason.Offensive, info="gay"),
    Re(r'gobshite?',
       reason=Reason.Offensive, info="gobshite"),
    Re(r'gooks?', 50,  # added "s?"
       reason=Reason.Offensive, info="gook"),
    Re(r'gypo', 15,
       reason=Reason.Offensive, info="gypo"),
    Re(r'h[ae]c?kers?', 20,
       reason=Reason.Shaming, info="hacker"),
    Re(r'handjob',
       reason=Reason.Other, info="handjob"),
    Re(r'hitler{1,20}', 20,  # '+'-->'{1,20}'
       reason=Reason.Offensive, info="hitler"),
    Re(r'homm?o(sexual|)s?', 20,  # added "s?"
       reason=Reason.Offensive, info="homosexual"),
    Re(r'honkey',
       reason=Reason.Offensive, info="honkey"),
    Re(r'hooker', 30,
       reason=Reason.Offensive, info="hooker"),
    Re(r'horny',
       reason=Reason.Other, info="horny"),
    Re(r'humping',
       reason=Reason.Other, info="humping"),
    Re(r'idiota?s?', 30,  # corrected
       reason=Reason.Offensive, info="idiot"),
    Re(r'incest',
       reason=Reason.Other, info="incest"),
    Re(r'jerks?', 20,  # added "s?"
       reason=Reason.Offensive, info="jerk"),
    Re(r'jizz?(um|)',
       reason=Reason.Other, info="jizz"),
    Re(r'labia',
       reason=Reason.Other, info="labia"),
    Re(r'lag{1,20}er{1,20}',
       reason=Reason.Shaming, info="lagger"),
    Re(r'lamer?',
       reason=Reason.Offensive, info="lamer"),
    Re(r'lesbo', 30,
       reason=Reason.Offensive, info="lesbo"),
    Re(r'lo{1,20}sers?', 30,  # '+'-->'{1,20}'  # added "s?"
       reason=Reason.Offensive, info="loser"),
    Re(r'masturbat(e|ion|ing?|ign|t?e?d)',
       reason=Reason.Other, info="masturbation"),
    Re(r'milf',
       reason=Reason.Other, info="milf"),
    Re(r'molest(er|)',
       reason=Reason.Offensive, info="molester"),
    Re(r'monkeys?',
       reason=Reason.Offensive, info="monkey"),
    Re(r'morons?', 30,  # added "s?"
       reason=Reason.Offensive, info="moron"),
    Re(r'mother', 20,  # split
       reason=Reason.Offensive, info="motherfucker"),
    Re(r'mother(fuc?k(ers?|))', 60,  # added "s?"
       reason=Reason.Offensive, info="motherfucker"),
    Re(r'mthrfckrs?', 50,  # added "s?"
       reason=Reason.Offensive, info="mthrfckr"),
    Re(r'naz(ie?|y)s?',  # added "(ie?|y)s?"
       reason=Reason.Offensive, info="nazi"),
    Re(r'niger', 40,
       reason=Reason.Offensive, info="niger"),
    Re(r'n+i+g+(e+r+|a+|a+h+)s?', 80,  # added '+', '+'  # added "s?"
       ban=-2, reason=Reason.Offensive, info="nigger"),
    Re(r'nonce', 50,
       reason=Reason.Offensive, info="nonce"),
    Re(r'no{2,25}bs?', 30,  # 'oo+'-->'o{1,25}'  # added "s?"
       reason=Reason.Offensive, info="noob"),
    Re(r'nutsac?k',
       reason=Reason.Offensive, info="nutsack"),
    Re(r'p{1,10}a{1,10}i{1,10}r{1,10}\sme{1,10}', 5,
       reason=Reason.Spam, info="pair me"),
    Re(r'pa?edo((f|ph)ile|)s?', 30,  # added "s?"
       reason=Reason.Offensive, info="paedophile"),
    Re(r'paki', 30,
       reason=Reason.Offensive, info="paki"),
    Re(r'pathetic', 30,
       reason=Reason.Offensive, info="pathetic"),
    Re(r'pa?ederasts?', 50,  # added "s?"
       ban=-2, reason=Reason.Offensive, info="pederast"),
    Re(r'penis',
       reason=Reason.Other, info="penis"),
    Re(r'pigs?', 20,  # added "s?"
       reason=Reason.Offensive, info="pig"),
    Re(r'pimp',
       reason=Reason.Offensive, info="pimp"),
    Re(r'piss',
       reason=Reason.Offensive, info="piss"),
    Re(r'poofs?', 30,  # added "s?"
       reason=Reason.Offensive, info="poof"),
    Re(r'poon',
       reason=Reason.Other, info="poon"),
    Re(r'po{2,20}p(face|e?d|ing?|ign|)',  # 'oo+'-->'o{2,20}'
       reason=Reason.Spam, info="poop"),
    Re(r'porn(hub|)',
       reason=Reason.Spam, info="porn"),
    Re(r'pric?ks?',  # added "s?"
       reason=Reason.Offensive, info="prick"),
    Re(r'prostitute', 15,
       reason=Reason.Offensive, info="prostitute"),
    Re(r'punani',
       reason=Reason.Other, info="punani"),
    Re(r'puss(i|y|ie|)', 20,
       reason=Reason.Offensive, info="pussy"),
    Re(r'queer', 20,
       reason=Reason.Offensive, info="queer"),
    Re(r'rape(s|d|)',
       reason=Reason.Offensive, info="rape"),
    Re(r'rapist',
       reason=Reason.Offensive, info="rapist"),
    Re(r'rect(al|um)',
       reason=Reason.Offensive, info="rekt"),
    Re(r'report(e?d|ing?|ign|)', 30,
       reason=Reason.Shaming, info="report"),
    Re(r'retard(ed|)', 30,
       reason=Reason.Offensive, info="retard"),
    Re(r'rimjob',
       reason=Reason.Other, info="rimjob"),
    Re(r'run', 5,
       reason=Reason.Offensive, info="run"),
    Re(r'sandbagg?(er|ing?|ign|e?d|)', 20,
       reason=Reason.Shaming, info="sandbagger"),
    Re(r'scared?',
       reason=Reason.Offensive, info="scare"),
    Re(r'schlong',
       reason=Reason.Other, info="schlong"),
    Re(r'screw(e?d|ing?|ign|)', 5,
       reason=Reason.Offensive, info="screw"),
    Re(r'scrotum',
       reason=Reason.Other, info="scrotum"),
    Re(r'scumbag', 20,
       reason=Reason.Offensive, info="scumbag"),
    Re(r'scum',  # split r'scum(bag|)'
       reason=Reason.Offensive, info="scum"),
    Re(r'semen', 5,
       reason=Reason.Other, info="semen"),
    Re(r'sex',
       reason=Reason.Other, info="sex"),
    Re(r'shag',
       reason=Reason.Other, info="shag"),
    Re(r'shemale', 20,
       reason=Reason.Offensive, info="shemale"),
    Re(r'shitt?(z|e|y|bag|ed|s|en|ing?|ign|)', 5,  # corrected
       reason=Reason.Offensive, info="shit"),
    Re(r'shat', 5,  # added
       reason=Reason.Other, info="shit"),
    Re(r'sissy', 20,
       reason=Reason.Offensive, info="sissy"),
    Re(r'slags?', 20,  # added "s?"
       reason=Reason.Offensive, info="slag"),
    Re(r'slaves?',  # added '?'
       reason=Reason.Offensive, info="slave"),
    Re(r'sluts?', 20,  # added '?'
       reason=Reason.Offensive, info="slut"),
    Re(r'spastic', 15,
       reason=Reason.Offensive, info="spastic"),
    Re(r'spaz{1,20}',  # added '{1,20}'
       reason=Reason.Offensive, info="spaz"),
    Re(r'sperm', 30,
       reason=Reason.Other, info="sperm"),
    Re(r'spick*', 20,  # added '*'
       reason=Reason.Offensive, info="spick"),
    Re(r'spooge',
       reason=Reason.Other, info="spooge"),
    Re(r'spunk',
       reason=Reason.Other, info="spunk"),
    Re(r'smurff?(er|ing?|ign|)s?', 30,  # added "s?"
       reason=Reason.Shaming, info="smurf"),
    Re(r'stfu', 20,
       reason=Reason.Offensive, info="stfu"),
    Re(r'stupids?',  # added "?"
       reason=Reason.Offensive, info="stupid"),
    Re(r'suicide\s(defen[sc]e|opening)', 0,
       reason=Reason.No, info="suicide defence"),
    Re(r'suicide',
       reason=Reason.Offensive, info="suicide"),
    Re(r'suck m[ey]', 50,
       ban=-2, reason=Reason.Offensive, info="suck my"),
    Re(r'suckers?', 50,
       reason=Reason.Offensive, info="sucker"),
    Re(r'terrorist',
       reason=Reason.Offensive, info="terrorist"),
    Re(r'tit(t?ies|ty|)(fuc?k|)',
       reason=Reason.Other, info="tit"),
    Re(r'tossers?', 15,  # added "s?"
       reason=Reason.Offensive, info="tosser"),
    Re(r'trann(y|ie)s?', 40,  # added "s?"
       reason=Reason.Offensive, info="tranny"),
    Re(r'trash',
       reason=Reason.Offensive, info="trash"),
    Re(r'turd',
       reason=Reason.Offensive, info="turd"),
    Re(r'twats?', 20,  # added "s?"
       reason=Reason.Offensive, info="twat"),
    Re(r'vags?',  # added "s?"
       reason=Reason.Offensive, info="vag"),
    Re(r'vagin(a|al|)',
       reason=Reason.Other, info="vagina"),
    Re(r'vibrators?',  # added "s?"
       reason=Reason.Other, info="vibrator"),
    Re(r'vulvas?',  # added "s?"
       reason=Reason.Other, info="vulva"),
    Re(r'w?hore?s?', 30,  # added "s?"
       reason=Reason.Offensive, info="whore"),
    Re(r'wanc?k(er|)', 20,
       reason=Reason.Offensive, info="wanker"),
    Re(r'weak', 5, exclude_tournaments=[TournType.Study],
       reason=Reason.Offensive, info="weak"),
    Re(r'wetback', 20,
       reason=Reason.Offensive, info="wetback"),
    Re(r'wog', 25,
       reason=Reason.Offensive, info="wog"),
],
Lang.Ru: [
    # Ru: suppress self-deprecating
    Re(r"я\s(д[еи]бил|дурак|придурок|даун|лопух|лох|лошара|лузер|идиот|отморозок)", 2,  # added
       reason=Reason.Spam, info="я дебил"),
    # Ru
    Re(r'(|на|по|ни|до|недо)(х|к)у(й|ю|ям?|ем?|и|ев|ями?|ях|йня|йло|йла|йлу)', 40,  # added new elements
       ban=-3, reason=Reason.Offensive, info="хуй"),
    Re(r'(|от|на|об|по|у)хуяр(ить?|ю|ишь?|им|ите|ят)',  # added
       reason=Reason.Offensive, info="хуярить"),
    Re(r'(|от)муд(охать|охал|охала|охали|аки?|акам|азвону?|ила)', 30,  # added '|ила'
       reason=Reason.Offensive, info="мудак"),
    Re(r'(|от|под?)cос(и|ать|ала?|)', 40,
       reason=Reason.Offensive, info="отсоси"),
    Re(r'(|от|с)п[ие]зд(а|ы|е|у|ить?|ил?а?|или|ошить?|ошил?а?|ошили|охать|охала?|охали|юлить|юлил?а?|юлили|ярить?|ярила?|ярили|яхать|яхала?|яхали|ячить?|ячила?|ячили|якать|якала?|якали|ец|ецкий?|атый?)', 30,  # corrected
       reason=Reason.Offensive, info="пизда"),
    Re(r'п[ие]зд[ао]бол(|а|ы|е|у|ом|ов|ав|ами?|ах)', 50,  # added
       reason=Reason.Offensive, info="пиздабол"),
    Re(r'(|отъ?|вы|до|за|у|про|съ?)[её]ба(л|ла|ли|ло|лся|льник|ть|на|нул|нула|нулся|нулись?|нн?ый|нутый?|нутая|нутые)', 50,  # added '|нутый?|нутая|нутые', '(е|ё)'-->'[её]'
       reason=Reason.Offensive, info="заебал"),
    Re(r'у?[её]бл(а|о|у|я|ю|е)', 40,  # added 'у?', '(е|ё)'-->'[её]', '|я|ю'
       reason=Reason.Offensive, info="ёбля"),
    Re(r'ебанат(|а|у|оми?|е|ы|ов|ав|ами?|ах)', 50,  # added
       reason=Reason.Offensive, info="ебанат"),
    Re(r'у?ебл?ан(|чик|[ие][шщ])(|а|е|у|ами?|ы|ов|оми?|ах|и)', 50,  # added
       ban=-2, reason=Reason.Offensive, info="еблан"),
    Re(r'([оа]сл[оа])?[её]б(ах?|е|ом?|у|ы|ов|ами?|)', 50,  # added 'у?', '(е|ё)'-->'[её]', etc.
       ban=-2, reason=Reason.Offensive, info="ёб"),
    Re(r'(|отъ?|вы|до|за|у|про)[её]б(нут|ан+)(ый?|ая|ые|ым|ого|ому?|ой|ую?|ых|ыми?|ых|учка|)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="ёбнутый"),
    Re(r'(|от(|ъ|ь)|вы|до|за|у|про|с(|ъ|ь))(е|ё)б(аш)?(ут?|и|ите?|ишь?|им|ым|ыте?|ышь?|ать?|[её]шь?|[её]т|[её]м|[её]те)(|с(|ь|ъ))', 40,  # added
       ban=-3, reason=Reason.Offensive, info="отъеби"),
    Re(r'(|за|отъ?|у|съ?)ебись',
       reason=Reason.Offensive, info="заебись"),
    Re(r'ебуч(ий?|ая|ие|им|его|ему|ей|ую?|их|ими?|их|)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="ебучий"),
    Re(r'(|на|вы)[её]бнуть?ся',  # added (...|ё), '(е|ё)'-->'[её]'
       reason=Reason.Offensive, info="ебнуться"),
    Re(r'blyat',
       ban=-3, reason=Reason.Other, info="blyat"),
    Re(r'p[ie]d[aoe]?r', 50,
       ban=-2, reason=Reason.Offensive, info="pidor"),
    Re(r'анус',
       reason=Reason.Other, info="анус"),
    Re(r'бля',
       reason=Reason.Other, info="бля"),
    Re(r'(вы|)бля(дь|ди|де|динам?|дине|дство|ть|док)', 30,  # split r'бля(|дь|ди|де|динам?|дине|дство|ть|док)' and '(вы|)'
       ban=-2, reason=Reason.Offensive, info="блядь"),
    Re(r'вы[её]бывае?(ть?ся|тесь)',
       reason=Reason.Offensive, info="выёбываться"),
    Re(r'вступ(ай|айте|ить|аем|ете?)',  # added
       reason=Reason.Spam, info="вступайте"),
    Re(r'г[ао]ндон(|у|ам?|ы|ов)', 50,
       ban=-2, reason=Reason.Offensive, info="гандон"),
    Re(r'ген[оа]ц[иы]д(|а|е|у|ом)', 20,  # added
       reason=Reason.Other, info="геноцид"),
    Re(r'гнид(|ам?|е|у|ы)', 50,
       ban=-2, reason=Reason.Offensive, info="гнида"),
    Re(r'г[оа]вн[оа]ед(|ам?|е|у|ом|ов|ами|ах|ы)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="говноед"),
    Re(r'г[оа]внюк(|ам?|е|у|ом|ов|ами|ах|и)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="говнюк"),
    Re(r'г[оа]вн(а|е|у|ом?)', 30,  # added
       reason=Reason.Offensive, info="говно"),
    Re(r'д[ао]лб[ао][её]б(ам?|у|е|ом|ы|ов|ами?|ах|)', 50,  # corrected
       ban=-2, reason=Reason.Offensive, info="долбоёб"),
    Re(r'даун(|у|ам?|ы|ов)', 30,
       reason=Reason.Offensive, info="даун"),
    Re(r'д[еи]бил(|ам?|ы|у|ов)', 30,
       reason=Reason.Offensive, info="дебил"),
    Re(r'дерьм(а|о|е|вый|вая|вое)',  # added '|е'
       reason=Reason.Offensive, info="дерьмо"),
    Re(r'задрот(ах?|у|ом|е|ы|ов|ами?|)', 30,  # added
       reason=Reason.Offensive, info="задрот"),
    Re(r'залуп(а|ы|у|е|ой|и|ы|ами?|ах|)', 30,  # added
       reason=Reason.Other, info="залупа"),
    Re(r'идиот(|ам?|ы|у|ов)', 20,
       reason=Reason.Offensive, info="идиот"),
    Re(r'йух', 40,
       reason=Reason.Offensive, info="хуй"),
    Re(r'к[ао]з(|е|ё)л(ам?|у|ы|ина)',  # added '|ина'
       reason=Reason.Offensive, info="козёл"),
    Re(r'лопух', 15,
       reason=Reason.Offensive, info="лопух"),
    Re(r'лох(|у|и|ам?|ушка)', 20,  # added '|ушка'
       reason=Reason.Offensive, info="лох"),
    Re(r'лошар(|ам?|е|у|ы)', 20,
       reason=Reason.Offensive, info="лошара"),
    Re(r'лузер(|ам?|у|ов|ы)', 30,
       reason=Reason.Offensive, info="лузер"),
    Re(r'мраз(ью?|и|ей?|ями|ях)', 50,  # added
       reason=Reason.Offensive, info="мразь"),
    Re(r'нац[иы]с[тц]с?(а?|у|ом|е|ы|ов|ами?|ах|кий|кого|кому|кими|ком|кие?|ких|кими?|ких)', 50,  # added
       reason=Reason.Offensive, info="нацист"),
    Re(r'нац[иы]к(а?|у|ом|е|и|ов|ами?|ах)', 50,  # added
       reason=Reason.Offensive, info="нацик"),
    Re(r'[оа]хуе(|л|ла|ли|ть|нн?о)', 20,
       ban=-3, reason=Reason.Offensive, info="охуел"),
    Re(r'отморозок', 20,  # added
       reason=Reason.Other, info="отморозок"),
    Re(r'педераст(|ы|ры?)', 50,  # 'ы?'-->'(|ы|ры?)'
       ban=-2, reason=Reason.Offensive, info="педераст"),
    Re(r'пид(о|а)р(а|ы|у|ам|асы?|асам?|ов|)', 50,  # added '|'
       ban=-2, reason=Reason.Offensive, info="пидор"),
    Re(r'пидр', 50,
       reason=Reason.Offensive, info="пидр"),
    Re(r'поебень',
       reason=Reason.Offensive, info="поебень"),
    Re(r'придур(ок|кам?|ков|ки)', 25,
       reason=Reason.Offensive, info="придурок"),
    Re(r'[сc][уy][кk](а|a|ин?ы?|е|у|ам)', 40,  # added 'н?ы?'
       ban=-3, reason=Reason.Offensive, info="сука"),
    Re(r'(с|з|по)дох(ни|ните?|нишь?|нут|)', 60,  # added
       ban=-3, reason=Reason.Offensive, info="сдохни"),
    Re(r'(у|по)мр(и|ите?|ешь?|ёшь?|ут|ете?|ёте?)', 40,  # added
       reason=Reason.Offensive, info="умри"),
    Re(r'смерт(ь|и|ью|ей|ями?|ях)', 30,  # added
       reason=Reason.Offensive, info="смерть"),
    Re(r'сос(и|ите|унок|унку|унке|унков|унками?|унках|унка)', 40,  # added
       reason=Reason.Offensive, info="соси"),
    Re(r'сперм(а|у|ой|е)', 30,  # added
       reason=Reason.Other, info="сперма"),
    Re(r'сперм[оа]глот(|а|у|ом|е|ы|ов|ами?|ах|ка|ке|ки|ку|кой)', 50,  # added
       reason=Reason.Offensive, info="спермоглот"),
    Re(r'сц?ыкун(ы|у|ам?|ом|е|ов|ами|ах|)', 40,  # added
       reason=Reason.Offensive, info="сыкун"),
    Re(r'сц[ыи]клив(ая?|ой?|ую|ый|ого|[оа]му|ом|ые|ых|ым?и?|ых|ое|)', 40,  # added
       reason=Reason.Offensive, info="сцыкливый"),
    Re(r'твар(ь|и|е|ина|ине|ину|ины)', 50,
       ban=-3, reason=Reason.Offensive, info="тварь"),
    Re(r'тупиц(|ам?|ы|е)', 20,
       reason=Reason.Offensive, info="тупица"),
    Re(r'ублюд(ок|кам?|ков|ку)', 80,
       ban=-2, reason=Reason.Offensive, info="ублюдок"),
    Re(r'у(ё|е)бищ(е|а|ам|у)', 80,
       ban=-2, reason=Reason.Offensive, info="уёбище"),
    Re(r'урод(е|а|ами?|у|оми?|ы|ов|ах|)', 40,  #added
       reason=Reason.Offensive, info="урод"),
    Re(r'вырод(ок|ка|ку|коми?|ке|ки|ков|ками?|ках)', 40,  #added
       reason=Reason.Offensive, info="выродок"),
    Re(r'у(ё|е)б(ок|ка|ку|ком|ке|ки|ков|ками?|ках)', 60,  #added
       ban=-2, reason=Reason.Offensive, info="уёбок"),
    Re(r'фаш[иы]с[тц]с?(а?|у|ом|е|ы|ов|ами?|ах|кий|кого|кому|кими|ком|кие?|ких|кими?|ких)', 50,  # added
       reason=Reason.Offensive, info="фашист"),
    Re(r'хак{1,2}ер(|а|у|ом|е|ы|ов|ами?|ах)', 20,  #added
       reason=Reason.Shaming, info="хакер"),
    Re(r'хохл[яа]нди(я|и|ю|е|ей)', 50,  # added
       reason=Reason.Offensive, info="хохляндия"),
    Re(r'хох(ол|лу|ла|лом|ле|лы|лов|лами?|лах)', 40,  # added
       reason=Reason.Offensive, info="хохол"),
    Re(r'\bхохл[ао]', 40, is_separate_word=False,  # added
       reason=Reason.Offensive, info="хохол"),
    Re(r'ху[её]во',  # '(е|ё)'-->'[её]' split r'ху[её](во|сос)'
       reason=Reason.Other, info="хуесос"),
    Re(r'хуесос(ы?|ина)', 50,  # added (ы?|ина)
       ban=-2, reason=Reason.Offensive, info="хуесос"),
    Re(r'ху[еи]т(а|е|ы)',
       reason=Reason.Offensive, info="хуета"),
    Re(r'читак(|и|ам?|у|ов)',  # added '|'
       reason=Reason.Shaming, info="читак"),
    Re(r'читер(|ила?|ить?|ишь?|ша|ы|ам?|у|ов)',
       reason=Reason.Shaming, info="читер"),
    Re(r'ч[её]рн[оа]жоп(ый?|ого|ому|ыми?|ая|ой|ую|ые|ых|)', 80,
       reason=Reason.Offensive, info="чёрножопый"),
    Re(r'член[оа]сос(|а|у|ом|е|ы|ов|ами?|ах|ка|ке|ки|ку|кой)', 50,  # added
       ban=-2, reason=Reason.Offensive, info="членосос"),
    Re(r'чмо(|шник|тнутый|тнутая|тнутые)', 50,  # added '|тнутый|тнутая|тнутые'
       ban=-2, reason=Reason.Offensive, info="чмо"),
    Re(r'ч[ую]р(ках?|ки|ке|ку|кой|ок|ками?)', 50,  # added
       reason=Reason.Offensive, info="чурка"),
    Re(r'шмар(|ам?|е|ы)', 30,  # added '|'
       reason=Reason.Offensive, info="шмара"),
    Re(r'шлюх(|ам?|е|и)', 30,
       reason=Reason.Offensive, info="шлюха"),
],
Lang.De: [
    Re(r'angsthase',
        reason=Reason.Offensive, info="angsthase"),
    Re(r'arschloch', 20,
        reason=Reason.Offensive, info="asshole"),
    Re(r'bl(ö|oe|o)dmann?',
        reason=Reason.Offensive, info="blödmann"),
    Re(r'drecksa(u|ck)',
        reason=Reason.Offensive, info="drecksack"),
    Re(r'ficker', 40,
        reason=Reason.Offensive, info="fucker"),
    Re(r'fotze', 60,
        reason=Reason.Offensive, info="motherfucker"),
    Re(r'hurensohn',
        reason=Reason.Offensive, info="hurensohn"),
    Re(r'mistkerl',
        reason=Reason.Offensive, info="mistkerl"),
    Re(r'miststück', 20,
        reason=Reason.Offensive, info="bastard"),
    Re(r'neger',
        reason=Reason.Offensive, info="neger"),
    Re(r'pisser',
        reason=Reason.Offensive, info="pisser"),
    Re(r'schlampe', 30,
        reason=Reason.Offensive, info="bitch"),
    Re(r'schwanzlutscher',
        reason=Reason.Offensive, info="schwanzlutscher"),
    Re(r'schwuchtel',
        reason=Reason.Offensive, info="schwuchtel"),
    Re(r'spasti', 20,
        reason=Reason.Offensive, info="dumbass"),
    Re(r'trottel',
        reason=Reason.Offensive, info="trottel"),
    Re(r'wichser',
        reason=Reason.Offensive, info="wichser"),
],
Lang.Es: [
    Re(r'cabr[oó]na?',
        reason=Reason.Offensive, info="cabróna"),
    Re(r'ching(ue|a)',
        reason=Reason.Offensive, info="chingue"),
    Re(r'chupame',
        reason=Reason.Offensive, info="chupame"),
    Re(r'cobarde',
        reason=Reason.Offensive, info="cobarde"),
    Re(r'est[úu]pid[ao]',
        reason=Reason.Offensive, info="estúpido"),
    Re(r'imbecil',
        reason=Reason.Offensive, info="imbecil"),
    Re(r'madre',
        reason=Reason.Offensive, info="madre"),
    Re(r'maric[oó]n',
        reason=Reason.Offensive, info="maricón"),
    Re(r'mierda',
        reason=Reason.Offensive, info="mierda"),
    Re(r'pendejo',
        reason=Reason.Offensive, info="pendejo"),
    Re(r'put[ao]',
        reason=Reason.Offensive, info="puta"),
    Re(r'trampa',
        reason=Reason.Offensive, info="trampa"),
    Re(r'trampos[ao]',
        reason=Reason.Offensive, info="tramposo"),
    Re(r'verga',
        reason=Reason.Offensive, info="verga"),
],
Lang.It: [
    Re(r'baldracca',
        reason=Reason.Offensive, info="baldracca"),
    Re(r'bastardo',
        reason=Reason.Offensive, info="bastardo"),
    Re(r'cazzo',
        reason=Reason.Offensive, info="cazzo"),
    Re(r'coglione',
        reason=Reason.Offensive, info="coglione"),
    Re(r'cretino',
        reason=Reason.Offensive, info="cretino"),
    Re(r'di merda',
        reason=Reason.Offensive, info="di merda"),
    Re(r'figa',
        reason=Reason.Offensive, info="figa"),
    Re(r'putt?ana',
        reason=Reason.Offensive, info="puttana"),
    Re(r'stronzo',
        reason=Reason.Offensive, info="stronzo"),
    Re(r'troia',
        reason=Reason.Offensive, info="troia"),
    Re(r'vaffanculo',
        reason=Reason.Offensive, info="vaffanculo"),
    Re(r'sparati',
        reason=Reason.Offensive, info="sparati"),
],
Lang.Hi: [
    Re(r'(madar|be?hen|beti)chod', 60,
        reason=Reason.Offensive, info="motherfucker"),
    Re(r'chutiya', 50,
        reason=Reason.Offensive, info="fucker/bastard"),
    Re(r'chut',
        reason=Reason.Other, info="pussy"),
    Re(r'lund',
        reason=Reason.Other, info="dick"),
    Re(r'gadha',
        reason=Reason.Offensive, info="donkey"),
    Re(r'bhadwa',
        reason=Reason.Offensive, info="pimp"),
    Re(r'bhadwachod', 50,
        reason=Reason.Offensive, info="fuck you pimp"),
    Re(r'gaa?ndu?',
        reason=Reason.Offensive, info="ass"),
    Re(r'gaand\smardunga', 60,
        reason=Reason.Offensive, info="I'll fuck your ass"),
    Re(r'gaa?ndu', 40,
        reason=Reason.Offensive, info="asshole"),
    Re(r'hijra',
        reason=Reason.Offensive, info="transgender"),
    Re(r'suwar',
        reason=Reason.Offensive, info="pig"),
    Re(r'jha(a|n)t',
        reason=Reason.Other, info="pubic hair"),
    Re(r'jha(a|n)tu', 40,
        reason=Reason.Offensive, info="you're pubic hair"),
    Re(r'bh?o?sdi?\s?ke?', 50,
        reason=Reason.Offensive, info="meaning: different sexual/obscene connotations"),
],
Lang.Fr: [
    Re(r'connard',
        reason=Reason.Offensive, info="asshole"),
    Re(r'fdp',
        reason=Reason.Offensive, info="son of a bitch"),
    Re(r'pd',
        reason=Reason.Offensive, info="pd"),
    Re(r'pute',
        reason=Reason.Offensive, info="pute"),
    Re(r'triche(ur|)',
        reason=Reason.Offensive, info="triche"),
],
Lang.Tr: [
    Re(r'am[iı]na (koyay[iı]m|koy?dum)',
        reason=Reason.Offensive, info="amına koyayım"),
    Re(r'amc[iı]k',
        reason=Reason.Offensive, info="amcık"),
    Re(r'anan[iı]n am[iı]',
        reason=Reason.Offensive, info="ananın amı"),
    Re(r'ann?an[iı](zi)? s[ii̇]k[eii̇]y[ii̇]m',
        reason=Reason.Offensive, info="annanı sikeyim"),
    Re(r'aptal',
        reason=Reason.Offensive, info="aptal"),
    Re(r'beyinsiz',
        reason=Reason.Offensive, info="beyinsiz"),
    Re(r'bok yedin',
        reason=Reason.Offensive, info="bok yedin"),
    Re(r'gerizekal[iı]',
        reason=Reason.Offensive, info="gerizekalı"),
    Re(r'ibne',
        reason=Reason.Offensive, info="ibne"),
    Re(r'ka[sş]ar',
        reason=Reason.Offensive, info="kaşar"),
    Re(r'orospu( ([çc]o[çc]u[ğg]?u|evlad[ıi]))?',
        reason=Reason.Offensive, info="orospu çoçuğu"),
    Re(r'piç(lik)?',
        reason=Reason.Offensive, info="piçlik"),
    Re(r'pu[sş]t',
        reason=Reason.Offensive, info="puşt"),
    Re(r'salak',
        reason=Reason.Offensive, info="salak"),
    Re(r's[ii̇]kecem',
        reason=Reason.Offensive, info="sikecem"),
    Re(r'sikiyonuz',
        reason=Reason.Offensive, info="sikiyonuz"),
    Re(r's[ii̇]kt[ii̇]r',
        reason=Reason.Offensive, info="siktir"),
    Re(r'yarra[gğ][iı] yediniz',
        reason=Reason.Offensive, info="yarrağı yediniz"),
],
Lang.Spam: [
    # Broadcasts
    Re(r'^b+l+u+e+n+d+e+r+$', 60, exclude_tournaments=[TournType.Arena, TournType.Swiss],
       reason=Reason.Spam, info="[broadcast] blunder"),
    Re(r'^d+r+a+w+$', 60, exclude_tournaments=[TournType.Arena, TournType.Swiss],
       reason=Reason.Spam, info="[broadcast] draw"),
    # Re(r"bl[ue]+nder+", 20,  # added
    #    reason=Reason.Spam, info="blunder"),
    # Website links
    Re(r'https?:\/\/(www\.)?lichess\.org\/@\/blog\/', 40,
       reason=Reason.Spam, info="[link] blog"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/@\/[-a-zA-Z0-9@:%._\+~#=]{0,30}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/[-a-zA-Z0-9@:%._\+~#=]{8,12}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/variant\/?[-a-zA-Z0-9@:%._\+~#=]{0,20}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/page\/?[-a-zA-Z0-9@:%._\+~#=]{0,40}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.thijs\.com\/[-a-zA-Z0-9@:%._\+~#=\/]{0,80}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'^https?:\/\/(www\.)?lichess\.org\/racer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}$', 60, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="[link] racer"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/racer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}', 50,
       reason=Reason.Spam, info="[link] racer"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/streamer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}', 40,
       reason=Reason.Spam, info="[link] streamer"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)dQw4w9WgXcQ', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)55DLs_7VJNE', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)oHg5SJYRHA0', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)lNv3pcPVhlY', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)lpiB2wMc49g', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)iik25wqIuFo', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)xvFZjo5PgG0', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)j8PxqgliIno', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)PyoRdu-i0AQ', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)HIcSWuKMwOw', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)g7YjojDbJGY', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)p7YXXieghto', 60,
       ban=-1, reason=Reason.Spam, info="[link] Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)RoozSjudh0I', 60,
       ban=-1, reason=Reason.Spam, info="[link] Spam"),
    Re(r'https?:\/\/(www\.)?(youtu|youtube|twitch|instagram)[-a-zA-Z0-9@:%._\+~#=]{0,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)', 40,
       reason=Reason.Spam, info="Link"),
    Re(r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)', 10,
       reason=Reason.Spam, info="Link"),
    # Spam
    Re(r'((.)\2{20,})', 80, is_capturing_groups=True, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="(.) x20"),
    Re(r'((.)\2{17,19})', 50, is_capturing_groups=True, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="(.) x17..19"),
    Re(r'((.)\2{12,16})', 10, is_capturing_groups=True, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="(.) x12..16"),
    # Variety
    TextVariety(reason=Reason.Spam, ban=80, info="TextVariety"),
    # Spam
    Re(r'((..)\2{10,})', 80, is_capturing_groups=True, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="(..) x10"),
    Re(r'((..)\2{8,9})', 50, is_capturing_groups=True, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="(..) x8..9"),
    Re(r'((..)\2{6,7})', 10, is_capturing_groups=True, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="(..) x6..7"),
    Re(r'[\W_\-]{25,}', 80, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="[$] x25"),
    Re(r'[\W_\-]{15,24}', 50, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="[$] x15..24"),
    Re(r'[^\w!?\.\s]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[$ !] x10..14"),
    Re(r'[\W_\-\d]{40,}', 80, is_separate_word=False,
       reason=Reason.Spam, info="[$7] x40"),  #ban=-1,
    Re(r'[\W_\-\d]{25,39}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[$7] x25..39"),  #ban=-2,
    Re(r'[\W_\-\d]{15,24}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[$7] x15..24"),
    Re(r'[a-zа-я\d]{50,}', 80, is_separate_word=False,
       reason=Reason.Spam, info="[ab] x50"), #ban=-1,
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{45,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="[^ -.] x45"),
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{35,44}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[^ -.] x35..44"),
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{25,34}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[^ -.] x25..34"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{50,}', 80, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="[b] x50"),  # without y
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{30,}', 60, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="[b] x30"),  # without y
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{22,29}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[b] x22..29"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{15,21}', 30, is_separate_word=False,
       reason=Reason.Spam, info="[b] x15..21"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[b] x10..14"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{35,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="[b ] x35"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{25,34}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[b ] x25..34"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{20,24}', 30, is_separate_word=False,
       reason=Reason.Spam, info="[b ] x20..24"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{15,19}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[b ] x15..19"),
    Re(r'[euioaёуеыаоэяю]{30,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="[a] x30"),
    Re(r'[euioaёуеыаоэяю]{20,29}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[a] x20..29"),
    Re(r'[euioaёуеыаоэяю]{15,19}', 30, is_separate_word=False,
       reason=Reason.Spam, info="[a] x15..19"),
    Re(r'[euioaёуеыаоэяю]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[a] x10..14"),
    Re(r'[\s\Weuioaёуеыаоэяю]{35,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="[a ] x35"),
    Re(r'[\s\Weuioaёуеыаоэяю]{25,34}', 50, is_separate_word=False,
       reason=Reason.Spam, info="[a ] x25..34"),
    Re(r'[\s\Weuioaёуеыаоэяю]{20,24}', 30, is_separate_word=False,
       reason=Reason.Spam, info="[a ] x20..24"),
    Re(r'[\s\Weuioaёуеыаоэяю]{15,19}', 10, is_separate_word=False,
       reason=Reason.Spam, info="[a ] x15..19"),
]
}

re_spaces = re.compile(r'\s{2,}', re.IGNORECASE)
