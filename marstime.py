#!/usr/bin/env python3
import math
import time
import re
import signal
import sys
import praw
from praw.handlers import MultiprocessHandler

try:
    from credentials import *  # NOQA
except ImportError:
    USERNAME = 'someusername'
    PASSWORD = 'somepassword'
    SUBREDDIT = 'somesubreddit'
    SIDEBAR_TAGS = {'start': '[](#edit_start)', 'stop': '[](#edit_stop)'}


def sigint_handler(signal, frame):
    '''Handles ^c'''
    print('Recieved SIGINT! Exiting...')
    sys.exit(0)


def cos(deg):
    return math.cos(deg * math.pi / 180)


def sin(deg):
    return math.sin(deg * math.pi / 180)


def h_to_hms(h):
    x = h * 3600
    hh = math.floor(x / 3600)
    y = x % 3600
    mm = math.floor(y / 60)
    ss = round(y % 60)
    return "{0:02d}:{1:02d}:{2:02d}".format(hh, mm, ss)


def h_to_hm(h):
    x = h * 3600
    hh = math.floor(x / 3600)
    y = x % 3600
    mm = math.floor(y / 60)
    return "{0:02d}:{1:02d}".format(hh, mm)


def within_24(n):
    if n < 0:
        n += 24
    elif n >= 24:
        n -= 24
    return n


class Mars(object):
    def __init__(self):
        self._update()

    def _update(self):
        self.secs = time.time()
        self.jd_ut = 2440587.5 + (self.secs / 8.64e4)
        self.jd_tt = self.jd_ut + (35 + 32.184) / 86400
        self.j2000 = self.jd_tt - 2451545
        self.m = (19.3870 + 0.52402075 * self.j2000) % 360
        self.alpha_fms = (270.3863 + 0.52403840 * self.j2000) % 360
        self.e = 0.09340 + 2.477e-9 * self.j2000
        self.pbs = (
            0.0071 * cos((0.985626 * self.j2000 /  2.2353) +  49.409) +
            0.0057 * cos((0.985626 * self.j2000 /  2.7543) + 168.173) +
            0.0039 * cos((0.985626 * self.j2000 /  1.1177) + 191.837) +
            0.0037 * cos((0.985626 * self.j2000 / 15.7866) +  21.736) +
            0.0021 * cos((0.985626 * self.j2000 /  2.1354) +  15.704) +
            0.0020 * cos((0.985626 * self.j2000 /  2.4694) +  95.528) +
            0.0018 * cos((0.985626 * self.j2000 / 32.8493) +  49.095)
        )
        self.nu_m = (
            (10.691 + 3.0e-7 * self.j2000) * sin(self.m) +
            0.623 * sin(2 * self.m) +
            0.050 * sin(3 * self.m) +
            0.005 * sin(4 * self.m) +
            0.0005 * sin(5 * self.m) +
            self.pbs
        )
        self.nu = self.nu_m + self.m
        self.l_s = (self.alpha_fms + self.nu_m) % 360
        self.eot = (
            2.861 * sin(2 * self.l_s) - 0.071 * sin(4 * self.l_s) + 0.002 *
            sin(6 * self.l_s) - self.nu_m
        )
        self.eot_h = self.eot * 24 / 360
        self.msd = ((self.j2000 - 4.5) / 1.027491252) + 44796 - 0.00096
        self.mtc = (24 * self.msd) % 24

        self.curiosity_lambda = 360 - 137.4
        self.curiosity_sol = math.floor(self.msd - self.curiosity_lambda / 360) - 49268
        self.curiosity_lmst = within_24(self.mtc - self.curiosity_lambda * 24 / 360)
        self.curiosity_ltst = within_24(self.curiosity_lmst + self.eot * 24 / 360)

        self.opportunity_sol_date = self.msd - 46235 - 0.042431
        self.opportunity_sol = math.floor(self.opportunity_sol_date)
        self.opportunity_mission = (24 * self.opportunity_sol_date) % 24
        self.opportunity_ltst = within_24(self.opportunity_mission + self.eot * 24 / 360)

    def mars_sol(self):
        return math.floor(self.msd)

    def curiosity_mission_sol(self):
        return self.curiosity_sol

    def opportunity_mission_sol(self):
        return self.opportunity_sol

    def curiosity_mission_ltst(self):
        return h_to_hm(self.curiosity_ltst)


def update_sidebar(subreddit, text, section):
    """Edits the sidebar in subreddit in-between the allowed tags set by section['start'] and
    section['stop']"""
    sidebar = subreddit.get_wiki_page('config/sidebar')
    sidebar_text = sidebar.content_md
    regex = r'''{}.*?{}'''.format(re.escape(section['start']), re.escape(section['stop']))
    text = section['start'] + text + section['stop']
    to_replace = (('&amp;', '&'), ('&gt;', '>'), ('&lt;', '<'))
    for i in to_replace:
        sidebar_text = sidebar_text.replace(*i)
    replace = re.findall(regex, sidebar_text, re.DOTALL)[0]
    sidebar_text = sidebar_text.replace(replace, text)
    sidebar.edit(content=sidebar_text, reason='automated edit {}'.format(time.time()))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, sigint_handler)
    r = praw.Reddit("/r/{}'s sidebar updater".format(SUBREDDIT), handler=MultiprocessHandler())
    r.login(USERNAME, PASSWORD)
    subreddit = r.get_subreddit(SUBREDDIT)
    last_status = None
    sidebar_template = (
        """\n\n1. **Current Mars Sol Date**: {mars_sol}"""
        """\n1. **Curiosity Mission Sol**: {curiosity_sol}"""
        """\n1. **Curiosity Local True Solar Time**: {curiosity_ltst}"""
        """\n1. **Opportunity Mission Sol**: {opportunity_sol}\n\n"""
    )
    while True:
        m = Mars()
        status = sidebar_template.format(
            mars_sol=m.mars_sol(),
            curiosity_sol=m.curiosity_mission_sol(),
            curiosity_ltst=m.curiosity_mission_ltst(),
            opportunity_sol=m.opportunity_mission_sol()
        )
        if last_status:
            if status != last_status:
                print('Updating sidebar')
                update_sidebar(SUBREDDIT, status, SIDEBAR_TAGS)
        elif last_status is None:
            print('Updating sidebar')
            update_sidebar(SUBREDDIT, status, SIDEBAR_TAGS)
        last_status = status
        time.sleep(30)
