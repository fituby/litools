import html
import re
import traceback
from elements import Reason, TournType
from elements import STYLE_WORD_BREAK


LANGUAGES = {
    'En': "English",
    'Ru': "Russian",
    'De': "German",
    'Es': "Spanish",
    'It': "Italian",
    'Hi': "Hindi",
    'Fr': "French",
    'Tr': "Turkish",
    'Spam': "Spam"
}


class EvalResult:
    def __init__(self, text):
        self.scores = [0] * Reason.Size
        self.ban_points = [0] * Reason.Size
        try:
            self.element = html.escape(text)
        except Exception as exception:
            print(f"ERROR when processing: {text}")
            self.element = text
            traceback.print_exception(type(exception), exception, exception.__traceback__)

    def __iadd__(self, o):
        for i in range(Reason.Size):
            self.scores[i] += o.scores[i]
            self.ban_points[i] += o.ban_points[i]
        return self

    def total_score(self):
        return sum(self.scores)


class TextVariety:
    def __init__(self, max_score=None, ban=None, reason=Reason.Spam, info="TextVariety", class_name="text-warning"):
        self.max_score = max_score
        self.ban = ban
        self.reason = reason
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
                    info = f'{info}\n{self.info}'
                result.element = f'<abbr class="{self.class_name}" title="{info}" style="{STYLE_WORD_BREAK}' \
                                 f'text-decoration:none;">{html.escape(original_msg)}</abbr>'
                if self.ban and self.reason != Reason.No:
                    result.ban_points[self.reason] = result.scores[self.reason] / self.ban
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
        self.info = info
        for tag, lang in LANGUAGES.items():
            if info.startswith(f"{tag}:"):
                self.info = f"{lang}{info[len(tag):]}"
                break
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
        result.scores[self.reason] += self.score * (len(new_msgs) - 1)
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
                str_sep = "\n" if info else ""
                info = f'{info}{str_sep}{self.info}'
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
        return f'<a class="{self.class_name}" href="https://lichess.org/@/{element.lower()}" target="_blank">{element}</a>'


list_res_variety = [
    TextVariety(reason=Reason.Spam, ban=80, info="TextVariety")
]

list_res = {
'En': [
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
    Re(r"(me|i['`]?(\sa|)m(\snot|))\s(an?\s|)(idiot|stupid|no{2,10}b|gay|jerk|lo{1,10}ser|moron|retard|trash|weak)", 5,  # added
       reason=Reason.Spam, info="En: I'm idiot"),
    # En
    Re(r'(f{1,20}|ph)(u|a|e){1,20}c?k{1,}\sme', 5,  # added
       reason=Reason.Offensive, info="En: fuck me"),
    Re(r'(f{1,20}|ph)(u|a|e){1,20}c?kk?(ers?|rs?|u|t|ing?|ign|en|e?d|tard?s?|face|off?|)', 15,  #'+'-->'{1,20}' + changed (...){1,20}  # added several "s?" and "k?"
       reason=Reason.Offensive, info="En: fuck"),
    Re(r'(f|ph)agg?([oi]t|)s?', 30,  # added "s?"
       reason=Reason.Offensive, ban=80, info="En: faggot"),
    Re(r'[ck]um(shots?|)',  # added "s?"
       reason=Reason.Offensive, info="En: cum"),
    Re(r'[ck]unt(ing?|ign|s|)', 30,  # added "|s"
       reason=Reason.Offensive, ban=80, info="En: cunt"),
    Re(r'abortion',
       reason=Reason.Other, info="En: abortion"),
    Re(r'adol(f|ph)',
       reason=Reason.Other, info="En: adolf"),
    Re(r'afraid', 5,
       reason=Reason.Offensive, info="En: afraid"),
    Re(r'anal(plug|sex|)',
       reason=Reason.Offensive, info="En: anal"),
    Re(r'anus',
       reason=Reason.Offensive, info="En: anus"),
    Re(r'arse(holes?|wipe|)',  # added "s?"
       reason=Reason.Offensive, info="En: arse"),
    Re(r'autist(ic|)',
       reason=Reason.Offensive, info="En: autist"),
    Re(r'dumb',
       reason=Reason.Offensive, info="En: dumb"),
    Re(r'(dumb|)ass',
       reason=Reason.Offensive, info="En: ass"),
    Re(r'ass?(hole|fag)s?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: asshole"),
    Re(r'aus?c?hwitz',
       reason=Reason.Offensive, info="En: auschwitz"),
    Re(r'bastard?s?', 20,  # added "s?"
       reason=Reason.Offensive, ban=80, info="En: bastard"),
    Re(r'be[ea]{1,20}ch(es|)', 5,  # '+'-->{1,20}  # added "(es|)"
       reason=Reason.Offensive, info="En: beach"),
    Re(r'bit?ch(es|)', 20,  # added "(es|)"
       reason=Reason.Offensive, info="En: bitch"),
    Re(r'blow(job|)',
       reason=Reason.Other, info="En: blow"),
    Re(r'blumpkin',
       reason=Reason.Other, info="En: blumpkin"),
    Re(r'bollock',
       reason=Reason.Other, info="En: bollock"),
    Re(r'boner',
       reason=Reason.Other, info="En: boner"),
    Re(r'boobs?',  # added "s?"
       reason=Reason.Other, info="En: boob"),
    Re(r'bozos?',  # added
       reason=Reason.Other, info="En: bozo"),
    Re(r'braindead',  # added
       reason=Reason.Offensive, info="En: braindead"),
    Re(r'buggers?',  # added "s?"
       reason=Reason.Offensive, info="En: bugger"),
    Re(r'buk?kake',
       reason=Reason.Other, info="En: bukkake"),
    Re(r'bull?shit',
       reason=Reason.Offensive, info="En: bullshit"),
    Re(r'ch(e{1,20}a?|i{1,20})tt?(ing?|ign|er{1,20}s?|e?d|s?)',  # ea --> (e{1,20}a?|i{1,20}) added "s?", added "{1,20}"
       reason=Reason.Shaming, info="En: cheater"),
    Re(r'chess(|-|_)bot(.?com)?', 50,
       reason=Reason.Spam, info="En: chess-bot.com"),
    Re(r'chickens?', 5,  # added "s?"
       reason=Reason.Offensive, info="En: chicken"),
    Re(r'chink',
       reason=Reason.Offensive, info="En: chick"),
    Re(r'clit(oris|ors?|)',  # added '|ors?'
       reason=Reason.Other, info="En: clitoris"),
    Re(r'clowns?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: clown"),
    Re(r'cock(suc?k(ers?|ing?|ign|e?d)|)', 50,  # added "s?"
       reason=Reason.Offensive, info="En: cocksucker"),
    Re(r'condoms?',  # added "s?"
       reason=Reason.Offensive, info="En: condom"),
    Re(r'coons?', 15,  # added "s?"
       reason=Reason.Offensive, info="En: coon"),
    Re(r'coward?s?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: coward"),
    Re(r'cry(baby|ing|)',
       reason=Reason.Offensive, info="En: cry"),
    Re(r'cunn?ilingus',  # added 's'
       reason=Reason.Other, info="En: cunnilingus"),
    Re(r'dic?k(head|face|suc?ker|)s?',  # added "s?"
       reason=Reason.Offensive, info="En: dick"),
    Re(r'dildos?',  # added "s?"
       reason=Reason.Other, info="En: dildo"),
    Re(r'dogg?ystyle',
       reason=Reason.Other, info="En: doggystyle"),
    Re(r'douche(bag|)', 20,
       reason=Reason.Offensive, info="En: douchebag"),
    Re(r'dykes?', 30,  # added "s?"
       reason=Reason.Offensive, info="En: dyke"),
    Re(r'engine', exclude_tournaments=[TournType.Study],
       reason=Reason.Shaming, info="En: engine"),
    Re(r'fck(er|r|u|k|t|ing?|ign|tard?|face|off?|e?d|)',
       reason=Reason.Offensive, info="En: fck"),
    Re(r'f[oa]llow\s?(me|(4|for)\s?f[oa]llow)', 25,  # added
       reason=Reason.Spam, info="En: follow"),
    Re(r'fo{1,10}l{1,10}(s|e?d|ing?|ign|)',  # added
       reason=Reason.Offensive, info="En: fool"),
    Re(r'foreskin',
       reason=Reason.Other, info="En: foreskin"),
    Re(r'gangbang',
       reason=Reason.Other, info="En: gangbang"),
    Re(r'gaye?s?', 30,  # added "e?s?"
       reason=Reason.Offensive, info="En: gay"),
    Re(r'gobshite?',
       reason=Reason.Offensive, info="En: gobshite"),
    Re(r'gooks?', 50,  # added "s?"
       reason=Reason.Offensive, info="En: gook"),
    Re(r'gypo', 15,
       reason=Reason.Offensive, info="En: gypo"),
    Re(r'h[ae]c?kers?', 20,
       reason=Reason.Shaming, info="En: hacker"),
    Re(r'handjob',
       reason=Reason.Other, info="En: handjob"),
    Re(r'hitler{1,20}', 20,  # '+'-->'{1,20}'
       reason=Reason.Offensive, info="En: hitler"),
    Re(r'homm?o(sexual|)s?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: homosexual"),
    Re(r'honkey',
       reason=Reason.Offensive, info="En: honkey"),
    Re(r'hooker', 30,
       reason=Reason.Offensive, info="En: hooker"),
    Re(r'horny',
       reason=Reason.Other, info="En: horny"),
    Re(r'humping',
       reason=Reason.Other, info="En: humping"),
    Re(r'idiota?s?', 30,  # corrected
       reason=Reason.Offensive, info="En: idiot"),
    Re(r'incest',
       reason=Reason.Other, info="En: incest"),
    Re(r'jerks?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: jerk"),
    Re(r'jizz?(um|)',
       reason=Reason.Other, info="En: jizz"),
    Re(r'labia',
       reason=Reason.Other, info="En: labia"),
    Re(r'lag{1,20}er{1,20}',
       reason=Reason.Shaming, info="En: lagger"),
    Re(r'lamer?',
       reason=Reason.Offensive, info="En: lamer"),
    Re(r'lesbo', 30,
       reason=Reason.Offensive, info="En: lesbo"),
    Re(r'lo{1,20}sers?', 30,  # '+'-->'{1,20}'  # added "s?"
       reason=Reason.Offensive, info="En: loser"),
    Re(r'masturbat(e|ion|ing?|ign|t?e?d)',
       reason=Reason.Other, info="En: masturbation"),
    Re(r'milf',
       reason=Reason.Other, info="En: milf"),
    Re(r'molest(er|)',
       reason=Reason.Offensive, info="En: molester"),
    Re(r'monkeys?',
       reason=Reason.Offensive, info="En: monkey"),
    Re(r'morons?', 30,  # added "s?"
       reason=Reason.Offensive, info="En: moron"),
    Re(r'mother', 20,  # split
       reason=Reason.Offensive, info="En: motherfucker"),
    Re(r'mother(fuc?k(ers?|))', 60,  # added "s?"
       reason=Reason.Offensive, info="En: motherfucker"),
    Re(r'mthrfckrs?', 50,  # added "s?"
       reason=Reason.Offensive, info="En: mthrfckr"),
    Re(r'naz(ie?|y)s?',  # added "(ie?|y)s?"
       reason=Reason.Offensive, info="En: nazi"),
    Re(r'nigg?(er+|a+|ah)s?', 80,  # added '+', '+'  # added "s?"
       ban=-2, reason=Reason.Offensive, info="En: nigger"),
    Re(r'nonce', 50,
       reason=Reason.Offensive, info="En: nonce"),
    Re(r'no{2,25}bs?', 30,  # 'oo+'-->'o{1,25}'  # added "s?"
       reason=Reason.Offensive, info="En: noob"),
    Re(r'nutsac?k',
       reason=Reason.Offensive, info="En: nutsack"),
    Re(r'pa?edo((f|ph)ile|)s?', 30,  # added "s?"
       reason=Reason.Offensive, info="En: paedophile"),
    Re(r'paki', 30,
       reason=Reason.Offensive, info="En: paki"),
    Re(r'pathetic', 30,
       reason=Reason.Offensive, info="En: pathetic"),
    Re(r'pa?ederasts?', 50,  # added "s?"
       ban=-2, reason=Reason.Offensive, info="En: pederast"),
    Re(r'penis',
       reason=Reason.Other, info="En: penis"),
    Re(r'pigs?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: pig"),
    Re(r'pimp',
       reason=Reason.Offensive, info="En: pimp"),
    Re(r'piss',
       reason=Reason.Offensive, info="En: piss"),
    Re(r'poofs?', 30,  # added "s?"
       reason=Reason.Offensive, info="En: poof"),
    Re(r'poon',
       reason=Reason.Other, info="En: poon"),
    Re(r'po{2,20}p(face|e?d|ing?|ign|)',  # 'oo+'-->'o{2,20}'
       reason=Reason.Spam, info="En: poop"),
    Re(r'porn(hub|)',
       reason=Reason.Spam, info="En: porn"),
    Re(r'pric?ks?',  # added "s?"
       reason=Reason.Offensive, info="En: prick"),
    Re(r'prostitute', 15,
       reason=Reason.Offensive, info="En: prostitute"),
    Re(r'punani',
       reason=Reason.Other, info="En: punani"),
    Re(r'puss(i|y|ie|)', 20,
       reason=Reason.Offensive, info="En: pussy"),
    Re(r'queer', 20,
       reason=Reason.Offensive, info="En: queer"),
    Re(r'rape(s|d|)',
       reason=Reason.Offensive, info="En: rape"),
    Re(r'rapist',
       reason=Reason.Offensive, info="En: rapist"),
    Re(r'rect(al|um)',
       reason=Reason.Offensive, info="En: rekt"),
    Re(r'report(e?d|ing?|ign|)', 30,
       reason=Reason.Shaming, info="En: report"),
    Re(r'retard', 30,
       reason=Reason.Offensive, info="En: retard"),
    Re(r'rimjob',
       reason=Reason.Other, info="En: rimjob"),
    Re(r'run', 5,
       reason=Reason.Offensive, info="En: run"),
    Re(r'sandbagg?(er|ing?|ign|e?d|)', 20,
       reason=Reason.Shaming, info="En: sandbagger"),
    Re(r'scared?',
       reason=Reason.Offensive, info="En: scare"),
    Re(r'schlong',
       reason=Reason.Other, info="En: schlong"),
    Re(r'screw(e?d|ing?|ign|)', 5,
       reason=Reason.Offensive, info="En: screw"),
    Re(r'scrotum',
       reason=Reason.Other, info="En: scrotum"),
    Re(r'scumbag', 20,
       reason=Reason.Offensive, info="En: scumbag"),
    Re(r'scum',  # split r'scum(bag|)'
       reason=Reason.Offensive, info="En: scum"),
    Re(r'semen', 5,
       reason=Reason.Other, info="En: semen"),
    Re(r'sex',
       reason=Reason.Other, info="En: sex"),
    Re(r'shag',
       reason=Reason.Other, info="En: shag"),
    Re(r'shemale', 20,
       reason=Reason.Offensive, info="En: shemale"),
    Re(r'shitt?(z|e|y|bag|ed|s|en|ing?|ign|)', 5,  # corrected
       reason=Reason.Offensive, info="En: shit"),
    Re(r'shat', 5,  # added
       reason=Reason.Other, info="En: shit"),
    Re(r'sissy', 20,
       reason=Reason.Offensive, info="En: sissy"),
    Re(r'slags?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: slag"),
    Re(r'slaves?',  # added '?'
       reason=Reason.Offensive, info="En: slave"),
    Re(r'sluts?', 20,  # added '?'
       reason=Reason.Offensive, info="En: slut"),
    Re(r'spastic', 15,
       reason=Reason.Offensive, info="En: spastic"),
    Re(r'spaz{1,20}',  # added '{1,20}'
       reason=Reason.Offensive, info="En: spaz"),
    Re(r'sperm', 30,
       reason=Reason.Other, info="En: sperm"),
    Re(r'spick*', 20,  # added '*'
       reason=Reason.Offensive, info="En: spick"),
    Re(r'spooge',
       reason=Reason.Other, info="En: spooge"),
    Re(r'spunk',
       reason=Reason.Other, info="En: spunk"),
    Re(r'smurff?(er|ing?|ign|)s?', 30,  # added "s?"
       reason=Reason.Shaming, info="En: smurf"),
    Re(r'stfu', 20,
       reason=Reason.Offensive, info="En: stfu"),
    Re(r'stupids?',  # added "?"
       reason=Reason.Offensive, info="En: stupid"),
    Re(r'suicide\s(defen[sc]e|opening)', 0,
       reason=Reason.No, info="En: suicide defence"),
    Re(r'suicide',
       reason=Reason.Offensive, info="En: suicide"),
    Re(r'suck m[ey]', 50,
       ban=-2, reason=Reason.Offensive, info="En: suck my"),
    Re(r'suckers?', 50,
       reason=Reason.Offensive, info="En: sucker"),
    Re(r'terrorist',
       reason=Reason.Offensive, info="En: terrorist"),
    Re(r'tit(t?ies|ty|)(fuc?k|)',
       reason=Reason.Other, info="En: tit"),
    Re(r'tossers?', 15,  # added "s?"
       reason=Reason.Offensive, info="En: tosser"),
    Re(r'trann(y|ie)s?', 40,  # added "s?"
       reason=Reason.Offensive, info="En: tranny"),
    Re(r'trash',
       reason=Reason.Offensive, info="En: trash"),
    Re(r'turd',
       reason=Reason.Offensive, info="En: turd"),
    Re(r'twats?', 20,  # added "s?"
       reason=Reason.Offensive, info="En: twat"),
    Re(r'vags?',  # added "s?"
       reason=Reason.Offensive, info="En: vag"),
    Re(r'vagin(a|al|)',
       reason=Reason.Other, info="En: vagina"),
    Re(r'vibrators?',  # added "s?"
       reason=Reason.Other, info="En: vibrator"),
    Re(r'vulvas?',  # added "s?"
       reason=Reason.Other, info="En: vulva"),
    Re(r'w?hore?s?', 30,  # added "s?"
       reason=Reason.Offensive, info="En: whore"),
    Re(r'wanc?k(er|)', 20,
       reason=Reason.Offensive, info="En: wanker"),
    Re(r'weak', 5, exclude_tournaments=[TournType.Study],
       reason=Reason.Offensive, info="En: weak"),
    Re(r'wetback', 20,
       reason=Reason.Offensive, info="En: wetback"),
    Re(r'wog', 25,
       reason=Reason.Offensive, info="En: wog"),
],
'Ru': [
    # Ru: suppress self-deprecating
    Re(r"я\s(дебил|дурак|придурок|даун|лопух|лох|лошара|лузер|идиот|отморозок)", 2,  # added
       reason=Reason.Spam, info="En: я дебил"),
    # Ru
    Re(r'(|на|по|ни|до|недо)(х|к)у(й|ю|ям?|ем?|и|ев|ями?|ях|йня|йло|йла|йлу)', 40,  # added new elements
       ban=-3, reason=Reason.Offensive, info="Ru: хуй"),
    Re(r'(|от|на|об|по|у)хуяр(ить?|ю|ишь?|им|ите|ят)',  # added
       reason=Reason.Offensive, info="Ru: хуярить"),
    Re(r'(|от)муд(охать|охал|охала|охали|аки?|акам|азвону?|ила)', 30,  # added '|ила'
       reason=Reason.Offensive, info="Ru: мудак"),
    Re(r'(|от|под?)cос(и|ать|ала?|)', 40,
       reason=Reason.Offensive, info="Ru: отсоси"),
    Re(r'(|от|с)п[ие]зд(а|ы|е|у|ить?|ил?а?|или|ошить?|ошил?а?|ошили|охать|охала?|охали|юлить|юлил?а?|юлили|ярить?|ярила?|ярили|яхать|яхала?|яхали|ячить?|ячила?|ячили|якать|якала?|якали|ец|ецкий?|атый?)', 30,  # corrected
       reason=Reason.Offensive, info="Ru: пизда"),
    Re(r'п[ие]зд[ао]бол(|а|ы|е|у|ом|ов|ав|ами?|ах)', 50,  # added
       reason=Reason.Offensive, info="Ru: пиздабол"),
    Re(r'(|отъ?|вы|до|за|у|про|съ?)[её]ба(л|ла|ли|ло|лся|льник|ть|на|нул|нула|нулся|нн?ый|нутый?|нутая|нутые)', 50,  # added '|нутый?|нутая|нутые', '(е|ё)'-->'[её]'
       reason=Reason.Offensive, info="Ru: заебал"),
    Re(r'у?[её]бл(а|о|у|я|ю|е)', 40,  # added 'у?', '(е|ё)'-->'[её]', '|я|ю'
       reason=Reason.Offensive, info="Ru: ёбля"),
    Re(r'у?ебл?ан(|чик|[ие][шщ])(|а|е|у|ами?|ы|ов|оми?|ах|и)', 50,  # added
       ban=-2, reason=Reason.Offensive, info="Ru: еблан"),
    Re(r'([оа]сл[оа])?[её]б(ах?|е|ом?|у|ы|ов|ами?|)', 50,  # added 'у?', '(е|ё)'-->'[её]', etc.
       ban=-2, reason=Reason.Offensive, info="Ru: ёб"),
    Re(r'(|отъ?|вы|до|за|у|про)[её]б(нут|ан+)(ый?|ая|ые|ым|ого|ому?|ой|ую?|ых|ыми?|ых|учка|)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: ёбнутый"),
    Re(r'(|отъ?|вы|до|за|у|про|съ?)(е|ё)б(аш)?(ут?|и|ите?|ишь?|им|ым|ыте?|ышь?|ать?|[её]шь?|[её]т|[её]м|[её]те)', 40,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: отъеби"),
    Re(r'(|за|отъ?|у|съ?)ебись',
       reason=Reason.Offensive, info="Ru: заебись"),
    Re(r'ебуч(ий?|ая|ие|им|его|ему|ей|ую?|их|ими?|их|)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: ебучий"),
    Re(r'(|на|вы)[её]бнуть?ся',  # added (...|ё), '(е|ё)'-->'[её]'
       reason=Reason.Offensive, info="Ru: ебнуться"),
    Re(r'blyat',
       ban=-3, reason=Reason.Other, info="Ru: blyat"),
    Re(r'p[ie]d[aoe]?r', 50,
       ban=-2, reason=Reason.Offensive, info="Ru: pidor"),
    Re(r'анус',
       reason=Reason.Other, info="Ru: анус"),
    Re(r'бля',
       reason=Reason.Other, info="Ru: бля"),
    Re(r'(вы|)бля(дь|ди|де|динам?|дине|дство|ть|док)', 30,  # split r'бля(|дь|ди|де|динам?|дине|дство|ть|док)' and '(вы|)'
       ban=-2, reason=Reason.Offensive, info="Ru: "),
    Re(r'вы[её]бывае?(ть?ся|тесь)',
       reason=Reason.Offensive, info="Ru: выёбываться"),
    Re(r'вступ(ай|айте|ить|аем|ете?)',  # added
       reason=Reason.Spam, info="Ru: вступайте"),
    Re(r'г[ао]ндон(|у|ам?|ы|ов)', 50,
       ban=-2, reason=Reason.Offensive, info="Ru: гандон"),
    Re(r'ген[оа]ц[иы]д(|а|е|у|ом)', 20,  # added
       reason=Reason.Other, info="Ru: геноцид"),
    Re(r'гнид(|ам?|е|у|ы)', 50,
       ban=-2, reason=Reason.Offensive, info="Ru: гнида"),
    Re(r'г[оа]вн[оа]ед(|ам?|е|у|ом|ов|ами|ах|ы)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: говноед"),
    Re(r'г[оа]внюк(|ам?|е|у|ом|ов|ами|ах|и)', 50,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: говнюк"),
    Re(r'г[оа]вн(а|е|у|ом?)', 30,  # added
       reason=Reason.Offensive, info="Ru: говно"),
    Re(r'д[ао]лб[ао][её]б(ам?|у|е|ом|ы|ов|ами?|ах|)', 50,  # corrected
       ban=-2, reason=Reason.Offensive, info="Ru: долбоёб"),
    Re(r'даун(|у|ам?|ы|ов)', 30,
       reason=Reason.Offensive, info="Ru: даун"),
    Re(r'д[еи]бил(|ам?|ы|у|ов)', 30,
       reason=Reason.Offensive, info="Ru: дебил"),
    Re(r'дерьм(а|о|е|вый|вая|вое)',  # added '|е'
       reason=Reason.Offensive, info="Ru: дерьмо"),
    Re(r'задрот(ах?|у|ом|е|ы|ов|ами?|)', 30,  # added
       reason=Reason.Offensive, info="Ru: задрот"),
    Re(r'идиот(|ам?|ы|у|ов)', 20,
       reason=Reason.Offensive, info="Ru: идиот"),
    Re(r'йух', 40,
       reason=Reason.Offensive, info="Ru: хуй"),
    Re(r'к[ао]з(|е|ё)л(ам?|у|ы|ина)',  # added '|ина'
       reason=Reason.Offensive, info="Ru: козёл"),
    Re(r'лопух', 15,
       reason=Reason.Offensive, info="Ru: лопух"),
    Re(r'лох(|у|и|ам?|ушка)', 20,  # added '|ушка'
       reason=Reason.Offensive, info="Ru: лох"),
    Re(r'лошар(|ам?|е|у|ы)', 20,
       reason=Reason.Offensive, info="Ru: лошара"),
    Re(r'лузер(|ам?|у|ов|ы)', 30,
       reason=Reason.Offensive, info="Ru: лузер"),
    Re(r'мраз(ью?|и|ей?|ями|ях)', 50,  # added
       reason=Reason.Offensive, info="Ru: мразь"),
    Re(r'нац[иы]с[тц]с?(а?|у|ом|е|ы|ов|ами?|ах|кий|кого|кому|кими|ком|кие?|ких|кими?|ких)', 50,  # added
       reason=Reason.Offensive, info="Ru: нацист"),
    Re(r'нац[иы]к(а?|у|ом|е|и|ов|ами?|ах)', 50,  # added
       reason=Reason.Offensive, info="Ru: нацик"),
    Re(r'[оа]хуе(|л|ла|ли|ть|нн?о)', 20,
       ban=-3, reason=Reason.Offensive, info="Ru: охуел"),
    Re(r'отморозок', 20,  # added
       reason=Reason.Other, info="Ru: отморозок"),
    Re(r'педераст(|ы|ры?)', 50,  # 'ы?'-->'(|ы|ры?)'
       ban=-2, reason=Reason.Offensive, info="Ru: педераст"),
    Re(r'пид(о|а)р(а|ы|у|ам|асы?|асам?|ов|)', 50,  # added '|'
       ban=-2, reason=Reason.Offensive, info="Ru: пидор"),
    Re(r'пидр', 50,
       reason=Reason.Offensive, info="Ru: пидр"),
    Re(r'поебень',
       reason=Reason.Offensive, info="Ru: поебень"),
    Re(r'придур(ок|кам?|ков|ки)', 25,
       reason=Reason.Offensive, info="Ru: придурок"),
    Re(r'[сc][уy][кk](а|a|ин?ы?|е|у|ам)', 40,  # added 'н?ы?'
       ban=-3, reason=Reason.Offensive, info="Ru: сука"),
    Re(r'(с|з|по)дох(ни|ните?|нишь?|нут|)', 60,  # added
       ban=-3, reason=Reason.Offensive, info="Ru: сдохни"),
    Re(r'сос(и|ите|унок|унку|унке|унков|унками?|унках|унка)', 40,  # added
       reason=Reason.Offensive, info="Ru: соси"),
    Re(r'сперм(а|у|ой|е)', 30,  # added
       reason=Reason.Other, info="Ru: сперма"),
    Re(r'сперм[оа]глот(|а|у|ом|е|ы|ов|ами?|ах|ка|ке|ки|ку|кой)', 50,  # added
       reason=Reason.Offensive, info="Ru: спермоглот"),
    Re(r'сц?ыкун(ы|у|ам?|ом|е|ов|ами|ах|)', 40,  # added
       reason=Reason.Offensive, info="Ru: сыкун"),
    Re(r'сц[ыи]клив(ая?|ой?|ую|ый|ого|[оа]му|ом|ые|ых|ым?и?|ых|ое|)', 40,  # added
       reason=Reason.Offensive, info="Ru: сцыкливый"),
    Re(r'твар(ь|и|е|ина|ине|ину|ины)', 50,
       ban=-3, reason=Reason.Offensive, info="Ru: тварь"),
    Re(r'тупиц(|ам?|ы|е)', 20,
       reason=Reason.Offensive, info="Ru: тупица"),
    Re(r'ублюд(ок|кам?|ков|ку)', 80,
       ban=-2, reason=Reason.Offensive, info="Ru: ублюдок"),
    Re(r'у(ё|е)бищ(е|а|ам|у)', 80,
       ban=-2, reason=Reason.Offensive, info="Ru: уёбище"),
    Re(r'урод(е|а|ами?|у|оми?|ы|ов|ах|)', 40,  #added
       reason=Reason.Offensive, info="Ru: урод"),
    Re(r'вырод(ок|ка|ку|коми?|ке|ки|ков|ками?|ках)', 40,  #added
       reason=Reason.Offensive, info="Ru: выродок"),
    Re(r'у(ё|е)б(ок|ка|ку|ком|ке|ки|ков|ками?|ках)', 60,  #added
       ban=-2, reason=Reason.Offensive, info="Ru: уёбок"),
    Re(r'фаш[иы]с[тц]с?(а?|у|ом|е|ы|ов|ами?|ах|кий|кого|кому|кими|ком|кие?|ких|кими?|ких)', 50,  # added
       reason=Reason.Offensive, info="Ru: фашист"),
    Re(r'хак{1,2}ер(|а|у|ом|е|ы|ов|ами?|ах)', 20,  #added
       reason=Reason.Shaming, info="Ru: хакер"),
    Re(r'хохл[яа]нди(я|и|ю|е|ей)', 50,  # added
       reason=Reason.Offensive, info="Ru: хохляндия"),
    Re(r'хох(ол|лу|ла|лом|ле|лы|лов|лами?|лах)', 40,  # added
       reason=Reason.Offensive, info="Ru: хохол"),
    Re(r'\bхохл[ао]', 40, is_separate_word=False,  # added
       reason=Reason.Offensive, info="Ru: хохол"),
    Re(r'ху[её]во',  # '(е|ё)'-->'[её]' split r'ху[её](во|сос)'
       reason=Reason.Other, info="Ru: хуесос"),
    Re(r'хуесос(ы?|ина)', 50,  # added (ы?|ина)
       ban=-2, reason=Reason.Offensive, info="Ru: хуесос"),
    Re(r'ху[еи]т(а|е|ы)',
       reason=Reason.Offensive, info="Ru: хуета"),
    Re(r'читак(|и|ам?|у|ов)',  # added '|'
       reason=Reason.Shaming, info="Ru: читак"),
    Re(r'читер(|ила?|ить?|ишь?|ша|ы|ам?|у|ов)',
       reason=Reason.Shaming, info="Ru: читер"),
    Re(r'ч[её]рн[оа]жоп(ый?|ого|ому|ыми?|ая|ой|ую|ые|ых|)', 80,
       reason=Reason.Offensive, info="Ru: чёрножопый"),
    Re(r'член[оа]сос(|а|у|ом|е|ы|ов|ами?|ах|ка|ке|ки|ку|кой)', 50,  # added
       ban=-2, reason=Reason.Offensive, info="Ru: членосос"),
    Re(r'чмо(|шник|тнутый|тнутая|тнутые)', 50,  # added '|тнутый|тнутая|тнутые'
       ban=-2, reason=Reason.Offensive, info="Ru: чмо"),
    Re(r'ч[ую]р(ках?|ки|ке|ку|кой|ок|ками?)', 50,  # added
       reason=Reason.Offensive, info="Ru: чурка"),
    Re(r'шмар(|ам?|е|ы)', 30,  # added '|'
       reason=Reason.Offensive, info="Ru: шмара"),
    Re(r'шлюх(|ам?|е|и)', 30,
       reason=Reason.Offensive, info="Ru: шлюха"),
],
'De': [
    Re(r'angsthase',
        reason=Reason.Offensive, info="De: angsthase"),
    Re(r'arschloch', 20,
        reason=Reason.Offensive, info="De: asshole"),
    Re(r'bl(ö|oe|o)dmann?',
        reason=Reason.Offensive, info="De: blödmann"),
    Re(r'drecksa(u|ck)',
        reason=Reason.Offensive, info="De: drecksack"),
    Re(r'ficker', 40,
        reason=Reason.Offensive, info="De: fucker"),
    Re(r'fotze', 60,
        reason=Reason.Offensive, info="De: motherfucker"),
    Re(r'hurensohn',
        reason=Reason.Offensive, info="De: hurensohn"),
    Re(r'mistkerl',
        reason=Reason.Offensive, info="De: mistkerl"),
    Re(r'miststück', 20,
        reason=Reason.Offensive, info="De: bastard"),
    Re(r'neger',
        reason=Reason.Offensive, info="De: neger"),
    Re(r'pisser',
        reason=Reason.Offensive, info="De: pisser"),
    Re(r'schlampe', 30,
        reason=Reason.Offensive, info="De: bitch"),
    Re(r'schwanzlutscher',
        reason=Reason.Offensive, info="De: schwanzlutscher"),
    Re(r'schwuchtel',
        reason=Reason.Offensive, info="De: schwuchtel"),
    Re(r'spasti', 20,
        reason=Reason.Offensive, info="De: dumbass"),
    Re(r'trottel',
        reason=Reason.Offensive, info="De: trottel"),
    Re(r'wichser',
        reason=Reason.Offensive, info="De: wichser"),
],
'Es': [
    Re(r'cabr[oó]na?',
        reason=Reason.Offensive, info="Es: cabróna"),
    Re(r'ching(ue|a)',
        reason=Reason.Offensive, info="Es: chingue"),
    Re(r'chupame',
        reason=Reason.Offensive, info="Es: chupame"),
    Re(r'cobarde',
        reason=Reason.Offensive, info="Es: cobarde"),
    Re(r'est[úu]pid[ao]',
        reason=Reason.Offensive, info="Es: estúpido"),
    Re(r'imbecil',
        reason=Reason.Offensive, info="Es: imbecil"),
    Re(r'madre',
        reason=Reason.Offensive, info="Es: madre"),
    Re(r'maric[oó]n',
        reason=Reason.Offensive, info="Es: maricón"),
    Re(r'mierda',
        reason=Reason.Offensive, info="Es: mierda"),
    Re(r'pendejo',
        reason=Reason.Offensive, info="Es: pendejo"),
    Re(r'put[ao]',
        reason=Reason.Offensive, info="Es: puta"),
    Re(r'trampa',
        reason=Reason.Offensive, info="Es: trampa"),
    Re(r'trampos[ao]',
        reason=Reason.Offensive, info="Es: tramposo"),
    Re(r'verga',
        reason=Reason.Offensive, info="Es: verga"),
],
'It': [
    Re(r'baldracca',
        reason=Reason.Offensive, info="It: baldracca"),
    Re(r'bastardo',
        reason=Reason.Offensive, info="It: bastardo"),
    Re(r'cazzo',
        reason=Reason.Offensive, info="It: cazzo"),
    Re(r'coglione',
        reason=Reason.Offensive, info="It: coglione"),
    Re(r'cretino',
        reason=Reason.Offensive, info="It: cretino"),
    Re(r'di merda',
        reason=Reason.Offensive, info="It: di merda"),
    Re(r'figa',
        reason=Reason.Offensive, info="It: figa"),
    Re(r'putt?ana',
        reason=Reason.Offensive, info="It: puttana"),
    Re(r'stronzo',
        reason=Reason.Offensive, info="It: stronzo"),
    Re(r'troia',
        reason=Reason.Offensive, info="It: troia"),
    Re(r'vaffanculo',
        reason=Reason.Offensive, info="It: vaffanculo"),
    Re(r'sparati',
        reason=Reason.Offensive, info="It: sparati"),
],
'Hi': [
    Re(r'(madar|be?hen|beti)chod', 60,
        reason=Reason.Offensive, info="Hi: motherfucker"),
    Re(r'chutiya', 50,
        reason=Reason.Offensive, info="Hi: fucker/bastard"),
    Re(r'chut',
        reason=Reason.Other, info="Hi: pussy"),
    Re(r'lund',
        reason=Reason.Other, info="Hi: dick"),
    Re(r'gadha',
        reason=Reason.Offensive, info="Hi: donkey"),
    Re(r'bhadwa',
        reason=Reason.Offensive, info="Hi: pimp"),
    Re(r'bhadwachod', 50,
        reason=Reason.Offensive, info="Hi: fuck you pimp"),
    Re(r'gaa?ndu?',
        reason=Reason.Offensive, info="Hi: ass"),
    Re(r'gaand\smardunga', 60,
        reason=Reason.Offensive, info="Hi: I'll fuck your ass"),
    Re(r'gaa?ndu', 40,
        reason=Reason.Offensive, info="Hi: asshole"),
    Re(r'hijra',
        reason=Reason.Offensive, info="Hi: transgender"),
    Re(r'suwar',
        reason=Reason.Offensive, info="Hi: pig"),
    Re(r'jha(a|n)t',
        reason=Reason.Other, info="Hi: pubic hair"),
    Re(r'jha(a|n)tu', 40,
        reason=Reason.Offensive, info="Hi: you're pubic hair"),
    Re(r'bh?o?sdi?\s?ke?', 50,
        reason=Reason.Offensive, info="Hi: meaning: different sexual/obscene connotations"),
],
'Fr': [
    Re(r'connard',
        reason=Reason.Offensive, info="Fr: asshole"),
    Re(r'fdp',
        reason=Reason.Offensive, info="Fr: fdp"),
    Re(r'pd',
        reason=Reason.Offensive, info="Fr: pd"),
    Re(r'pute',
        reason=Reason.Offensive, info="Fr: pute"),
    Re(r'triche(ur|)',
        reason=Reason.Offensive, info="Fr: triche"),
],
'Tr': [
    Re(r'am[iı]na (koyay[iı]m|koy?dum)',
        reason=Reason.Offensive, info="Tr: amına koyayım"),
    Re(r'amc[iı]k',
        reason=Reason.Offensive, info="Tr: amcık"),
    Re(r'anan[iı]n am[iı]',
        reason=Reason.Offensive, info="Tr: ananın amı"),
    Re(r'ann?an[iı](zi)? s[ii̇]k[eii̇]y[ii̇]m',
        reason=Reason.Offensive, info="Tr: annanı sikeyim"),
    Re(r'aptal',
        reason=Reason.Offensive, info="Tr: aptal"),
    Re(r'beyinsiz',
        reason=Reason.Offensive, info="Tr: beyinsiz"),
    Re(r'bok yedin',
        reason=Reason.Offensive, info="Tr: bok yedin"),
    Re(r'gerizekal[iı]',
        reason=Reason.Offensive, info="Tr: gerizekalı"),
    Re(r'ibne',
        reason=Reason.Offensive, info="Tr: ibne"),
    Re(r'ka[sş]ar',
        reason=Reason.Offensive, info="Tr: kaşar"),
    Re(r'orospu( ([çc]o[çc]u[ğg]?u|evlad[ıi]))?',
        reason=Reason.Offensive, info="Tr: orospu çoçuğu"),
    Re(r'piç(lik)?',
        reason=Reason.Offensive, info="Tr: piçlik"),
    Re(r'pu[sş]t',
        reason=Reason.Offensive, info="Tr: puşt"),
    Re(r'salak',
        reason=Reason.Offensive, info="Tr: salak"),
    Re(r's[ii̇]kecem',
        reason=Reason.Offensive, info="Tr: sikecem"),
    Re(r'sikiyonuz',
        reason=Reason.Offensive, info="Tr: sikiyonuz"),
    Re(r's[ii̇]kt[ii̇]r',
        reason=Reason.Offensive, info="Tr: siktir"),
    Re(r'yarra[gğ][iı] yediniz',
        reason=Reason.Offensive, info="Tr: yarrağı yediniz"),
],
'Spam': [
    # Broadcasts
    Re(r'^b+l+u+e+n+d+e+r+$', 60, exclude_tournaments=[TournType.Arena, TournType.Swiss],
       reason=Reason.Spam, info="Spam: [broadcast] blunder"),
    Re(r'^d+r+a+w+$', 60, exclude_tournaments=[TournType.Arena, TournType.Swiss],
       reason=Reason.Spam, info="Spam: [broadcast] draw"),
    # Re(r"bl[ue]+nder+", 20,  # added
    #    reason=Reason.Spam, info="Spam: blunder"),
    # Website links
    Re(r'https?:\/\/(www\.)?lichess\.org\/@\/blog\/', 40,
       reason=Reason.Spam, info="Link: Link: blog"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/@\/[-a-zA-Z0-9@:%._\+~#=]{0,30}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/[-a-zA-Z0-9@:%._\+~#=]{8,12}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/variant\/?[-a-zA-Z0-9@:%._\+~#=]{0,20}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'https?:\/\/(www\.)?lichess\.org\/page\/?[-a-zA-Z0-9@:%._\+~#=]{0,40}', 0, class_name="text-success",
       reason=Reason.No),
    Re(r'^https?:\/\/(www\.)?lichess\.org\/racer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}$', 60, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Link: racer"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/racer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}', 50,
       reason=Reason.Spam, info="Link"),
    Re(r'https?:\/\/(www\.)?lichess\.org\/streamer\/[-a-zA-Z0-9@:%._\+~#=]{5,8}', 40,
       reason=Reason.Spam, info="Link"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)dQw4w9WgXcQ', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)55DLs_7VJNE', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)oHg5SJYRHA0', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)lNv3pcPVhlY', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)lpiB2wMc49g', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)iik25wqIuFo', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)xvFZjo5PgG0', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)j8PxqgliIno', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)PyoRdu-i0AQ', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)HIcSWuKMwOw', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)g7YjojDbJGY', 60,
       ban=-1, reason=Reason.Spam, info="Link: Rickrolling"),
    Re(r'(https?:\/\/|)(www\.)?youtu(be\.com\/watch\?v=|\.be\/)RoozSjudh0I', 60,
       ban=-1, reason=Reason.Spam, info="Link: Spam"),
    Re(r'https?:\/\/(www\.)?(youtu|youtube|twitch|instagram)[-a-zA-Z0-9@:%._\+~#=]{0,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)', 40,
       reason=Reason.Spam, info="Link"),
    Re(r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)', 10,
       reason=Reason.Spam, info="Link"),
    # Spam
    Re(r'((.)\2{20,})', 80, is_capturing_groups=True, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Spam: (.) x20"),
    Re(r'((.)\2{17,19})', 50, is_capturing_groups=True, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: (.) x17..19"),
    Re(r'((.)\2{12,16})', 10, is_capturing_groups=True, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="Spam: (.) x12..16"),
    # Variety
    TextVariety(reason=Reason.Spam, ban=80, info="TextVariety"),
    # Spam
    Re(r'((..)\2{10,})', 80, is_capturing_groups=True, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Spam: (..) x10"),
    Re(r'((..)\2{8,9})', 50, is_capturing_groups=True, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: (..) x8..9"),
    Re(r'((..)\2{6,7})', 10, is_capturing_groups=True, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="Spam: (..) x6..7"),
    Re(r'[\W_\-]{25,}', 80, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Spam: [$] x25"),
    Re(r'[\W_\-]{15,24}', 50, is_separate_word=False,
       ban=-3, reason=Reason.Spam, info="Spam: [$] x15..24"),
    Re(r'[^\w!?\.\s]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [$ !] x10..14"),
    Re(r'[\W_\-\d]{40,}', 80, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Spam: [$7] x40"),
    Re(r'[\W_\-\d]{25,39}', 50, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [$7] x25..39"),
    Re(r'[\W_\-\d]{15,24}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [$7] x15..24"),
    Re(r'[a-zа-я\d]{50,}', 80, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [ab] x50"), #ban=-1,
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{45,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [^ -.] x45"),
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{35,44}', 50, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [^ -.] x35..44"),
    Re(r'[^\s\.,_!\-?;:\+\\\/' '\u0590-\u06FF' '\u0E00-\u0E7F' '\u3041-\u3096' '\u30A0-\u30FF' ']{25,34}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [^ -.] x25..34"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{50,}', 80, is_separate_word=False,
       ban=-1, reason=Reason.Spam, info="Spam: [b] x50"),  # without y
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{30,}', 60, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [b] x30"),  # without y
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{22,29}', 50, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b] x22..29"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{15,21}', 30, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b] x15..21"),
    Re(r'[qwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b] x10..14"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{35,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [b ] x35"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{25,34}', 50, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b ] x25..34"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{20,24}', 30, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b ] x20..24"),
    Re(r'[\s\Wqwrtpsdfghjklzxcvbnmйцкнгшщзхъфвпрлджчсмтьб]{15,19}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [b ] x15..19"),
    Re(r'[euioaёуеыаоэяю]{30,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [a] x30"),
    Re(r'[euioaёуеыаоэяю]{20,29}', 50, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a] x20..29"),
    Re(r'[euioaёуеыаоэяю]{15,19}', 30, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a] x15..19"),
    Re(r'[euioaёуеыаоэяю]{10,14}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a] x10..14"),
    Re(r'[\s\Weuioaёуеыаоэяю]{35,}', 80, is_separate_word=False,
       ban=-2, reason=Reason.Spam, info="Spam: [a ] x35"),
    Re(r'[\s\Weuioaёуеыаоэяю]{25,34}', 50, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a ] x25..34"),
    Re(r'[\s\Weuioaёуеыаоэяю]{20,24}', 30, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a ] x20..24"),
    Re(r'[\s\Weuioaёуеыаоэяю]{15,19}', 10, is_separate_word=False,
       reason=Reason.Spam, info="Spam: [a ] x15..19"),
]
}

re_spaces = re.compile(r'\s{2,}', re.IGNORECASE)
