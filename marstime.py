#!/usr/bin/env python3
import math
import json
import urllib.request
import time
import re
import signal
import sys
from urllib.parse import urlencode
import http.cookiejar

try:
    from credentials import * # NOQA
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


class Reddit(object):
    """Base class to perform the tasks of a redditor."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [('User-agent', '/r/curiosityrover sidebar updater')]
        self._login()

    def _request(self, url, body=None):
        if body is not None:
            body = urlencode(body).encode('utf-8')
        try:
            with self.opener.open(url, data=body) as w:
                time.sleep(2)
                return json.loads(w.read().decode('utf-8'))
        except urllib.error.HTTPError:
            # This should at least help for times when reddit derps up when we request a listing
            return dict()

    def _login(self):
        body = {'user': self.username, 'passwd': self.password, 'api_type': 'json'}
        resp = self._request('http://www.reddit.com/api/login', body)
        self.modhash = resp['json']['data']['modhash']

    def post(self, url, body):
        """Sends a POST to the url and returns the json as a dict."""

        if 'api_type' not in body:
            body['api_type'] = 'json'

        body['uh'] = self.modhash

        return self._request(url, body)

    def get(self, url):
        """Sends a GET to the url and returns the json as a dict."""
        if '.json' not in url:
            url += '.json'
        return self._request(url)

    def sidebar(self, subreddit, text, section):
        """Edits the sidebar in subreddit in-between the allowed tags set by section['start'] and
        section['stop']"""
        sub = self.get(
            'http://www.reddit.com/r/{}/wiki/config/sidebar.json'.format(subreddit))['data']
        regex = r'''{}.*?{}'''.format(re.escape(section['start']), re.escape(section['stop']))
        text = section['start'] + text + section['stop']
        to_replace = (('&amp;', '&'), ('&gt;', '>'), ('&lt;', '<'))
        for i in to_replace:
            sub['content_md'] = sub['content_md'].replace(*i)
        replace = re.findall(regex, sub['content_md'], re.DOTALL)[0]
        sidebar = sub['content_md'].replace(replace, text)
        body = {'content': sidebar, 'page': 'config/sidebar', 'reason': 'automated edit {}'.format(
            time.time())}
        self.post('http://www.reddit.com/r/{}/api/wiki/edit'.format(subreddit), body)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, sigint_handler)
    r = Reddit(USERNAME, PASSWORD)
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
                r.sidebar(SUBREDDIT, status, SIDEBAR_TAGS)
        elif last_status is None:
            print('Updating sidebar')
            r.sidebar(SUBREDDIT, status, SIDEBAR_TAGS)
        last_status = status
        time.sleep(30)

