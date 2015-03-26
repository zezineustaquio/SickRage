# Author: Jose Eustaquio
# Modified by jkaberg, https://github.com/jkaberg for SceneAccess
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of SickRage.
#
# SickRage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickRage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickRage.  If not, see <http://www.gnu.org/licenses/>.

import re
import traceback
import datetime
import urlparse
import sickbeard
import generic
from sickbeard.common import Quality, cpu_presets
from sickbeard import logger
from sickbeard import tvcache
from sickbeard import db
from sickbeard import classes
from sickbeard import helpers
from sickbeard import show_name_helpers
from sickbeard.exceptions import ex, AuthException
from sickbeard import clients
from lib import requests
from lib.requests import exceptions
from sickbeard.bs4_parser import BS4Parser
from lib.unidecode import unidecode
from sickbeard.helpers import sanitizeSceneName


class ManicomioShareProvider(generic.TorrentProvider):
    def __init__(self):

        generic.TorrentProvider.__init__(self, "ManicomioShare")

        self.supportsBacklog = True

        self.enabled = False
        self._uid = None
        self._hash = None
        self.username = None
        self.password = None
        self.ratio = None
        self.minseed = None
        self.minleech = None
        
        self.urls = {'base_url': 'http://www.manicomio-share.com',
                     'login': 'http://www.manicomio-share.com',
                     'detail': 'http://www.manicomio-share.com/torrents-details.php?id=%s',
                     'search': 'http://www.manicomio-share.com/pesquisa.php?busca=%s&order=desc&sort=seeders&options=0%s',
                     'download': 'http://www.manicomio-share.com/download.php?id=%s',
                     'home': 'http://www.manicomio-share.com/%s'
        }

        self.url = self.urls['base_url']

        self.cache = ManicomioShareCache(self)

        self.categories = "&c123=1&c164=1&c163=1&c124=1&c181=1&c125=1&c122=1&c76=1"

        self.cookies = None

    def isEnabled(self):
        return self.enabled

    def imageName(self):
        return 'manicomio.png'

    def getQuality(self, item, anime=False):

        quality = Quality.sceneQuality(item[0])
        return quality

    def _checkAuth(self):

        if not self.username or not self.password:
            raise AuthException("Your authentication credentials for " + self.name + " are missing, check your config.")

        return True

    def _doLogin(self):

        if any(requests.utils.dict_from_cookiejar(self.session.cookies).values()):
            return True

        if self._uid and self._hash:

            requests.utils.add_dict_to_cookiejar(self.session.cookies, self.cookies)

        else:

            login_params = {'username': self.username,
                            'password': self.password,
                            'dados': 'ok',
            }

            try:
                response = self.session.post(self.urls['login'], data=login_params, timeout=30, verify=False)
            except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError), e:
                logger.log(u'Unable to connect to ' + self.name + ' provider: ' + ex(e), logger.ERROR)
                return False

            if re.search('You need cookies enabled to log in.', response.text) \
                    or response.status_code == 401:
                logger.log(u'Invalid username or password for ' + self.name + ' Check your settings', logger.ERROR)
                return False

            self._uid = requests.utils.dict_from_cookiejar(self.session.cookies)['uid']
            self._hash = requests.utils.dict_from_cookiejar(self.session.cookies)['pass']

            self.cookies = {'uid': self._uid,
                            'pass': self._hash
            }

        return True

    def _get_season_search_strings(self, ep_obj):

        search_string = {'Season': []}
        for show_name in set(show_name_helpers.allPossibleShowNames(self.show)):
            if ep_obj.show.air_by_date or ep_obj.show.sports:
                ep_string = show_name + ' ' + str(ep_obj.airdate).split('-')[0]
            elif ep_obj.show.anime:
                ep_string = show_name + ' ' + "%d" % ep_obj.scene_absolute_number
            else:
                ep_string = show_name + ' ' + str(ep_obj.scene_season) + ' Temporada Completa' #1) showName SXX

            search_string['Season'].append(ep_string)


        return [search_string]

    def _get_episode_search_strings(self, ep_obj, add_string=''):
        search_string = {'Episode': []}

        if not ep_obj:
            return []

        if self.show.air_by_date:
            for show_name in set(show_name_helpers.allPossibleShowNames(self.show)):
                ep_string = sanitizeSceneName(show_name) + ' ' + \
                            str(ep_obj.airdate).replace('-', '|')
                search_string['Episode'].append(ep_string)
        elif self.show.sports:
            for show_name in set(show_name_helpers.allPossibleShowNames(self.show)):
                ep_string = sanitizeSceneName(show_name) + ' ' + \
                            str(ep_obj.airdate).replace('-', '|') + '|' + \
                            ep_obj.airdate.strftime('%b')
                search_string['Episode'].append(ep_string)
        elif self.show.anime:
            for show_name in set(show_name_helpers.allPossibleShowNames(self.show)):
                ep_string = sanitizeSceneName(show_name) + ' ' + \
                            "%i" % int(ep_obj.absolute_number)
                search_string['Episode'].append(ep_string)
        else:
            for show_name in set(show_name_helpers.allPossibleShowNames(self.show)):
                ep_string = show_name_helpers.sanitizeSceneName(show_name) + ' ' + \
                            sickbeard.config.naming_ep_type[2] % {'seasonnumber': ep_obj.scene_season,
                                                                  'episodenumber': ep_obj.scene_episode} + ' %s' % add_string

                search_string['Episode'].append(re.sub('\s+', ' ', ep_string))

        return [search_string]

    def _doSearch(self, search_params, search_mode='eponly', epcount=0, age=0):

        results = []
        items = {'Season': [], 'Episode': [], 'RSS': []}

        if not self._doLogin():
            return results

        for mode in search_params.keys():
            for search_string in search_params[mode]:

                if isinstance(search_string, unicode):
                    search_string = unidecode(search_string)

                if search_string == '':
                    continue
                search_string = str(search_string).replace('.', ' ')
                searchURL = self.urls['search'] % (search_string, self.categories)

                logger.log(u"Search string: " + searchURL, logger.DEBUG)

                data = self.getURL(searchURL)
                if not data:
                    continue

                try:
                    with BS4Parser(data, features=["html5lib", "permissive"]) as html:
                        #Get first entry in table
                        entries = html.select('#closest')

                        if html.find(text='Nenhum Torrent foi Encontrado'):
                            logger.log(u"No results found for: " + search_string + " (" + searchURL + ")", logger.DEBUG)
                            continue

                        if not entries:
                            logger.log(u"The Data returned from " + self.name + " do not contains any torrent",
                                       logger.DEBUG)
                            continue

                        for result in entries:

                            try:
                                title = str(result.select('td')[1].find('a').attrs[u'title'])
                                url = str(result.find("a", {"class": "btn btn-default btn-xs"})['href'])
                                download_url = str(result.find("a", {"class": "btn btn-default btn-xs"})['href'])
                                id = int(result.select('td')[1].find('img').attrs[u'id'].replace('img',''))
                                seeders = int(result.find_all('span',{'class','h3o'})[0].getText())
                                leechers = int(result.find_all('span',{'class','h3o'})[1].getText())
                            except (AttributeError, TypeError):
                                continue

                            if mode != 'RSS' and (seeders < self.minseed or leechers < self.minleech):
                                continue

                            if not title or not download_url:
                                continue

                            item = title, download_url, id, seeders, leechers
                            logger.log(u"Found result: " + title + "(" + searchURL + ")", logger.DEBUG)

                            items[mode].append(item)

                except Exception, e:
                    logger.log(u"Failed parsing " + self.name + " Traceback: " + traceback.format_exc(), logger.ERROR)

            #For each search mode sort all the items by seeders
            items[mode].sort(key=lambda tup: tup[3], reverse=True)

            results += items[mode]

        return results

    def _get_title_and_url(self, item):

        title, url, id, seeders, leechers = item

        if title:
            title = u'' + title
            title = title.replace(' ', '.')

        if url:
            url = str(url).replace('&amp;', '&')

        return (title, url)

    def findPropers(self, search_date=datetime.datetime.today()):

        results = []

        myDB = db.DBConnection()
        sqlResults = myDB.select(
            'SELECT s.show_name, e.showid, e.season, e.episode, e.status, e.airdate FROM tv_episodes AS e' +
            ' INNER JOIN tv_shows AS s ON (e.showid = s.indexer_id)' +
            ' WHERE e.airdate >= ' + str(search_date.toordinal()) +
            ' AND (e.status IN (' + ','.join([str(x) for x in Quality.DOWNLOADED]) + ')' +
            ' OR (e.status IN (' + ','.join([str(x) for x in Quality.SNATCHED]) + ')))'
        )

        if not sqlResults:
            return []

        for sqlshow in sqlResults:
            self.show = curshow = helpers.findCertainShow(sickbeard.showList, int(sqlshow["showid"]))
            if not self.show: continue
            curEp = curshow.getEpisode(int(sqlshow["season"]), int(sqlshow["episode"]))

            searchString = self._get_episode_search_strings(curEp, add_string='PROPER|REPACK')

            for item in self._doSearch(searchString[0]):
                title, url = self._get_title_and_url(item)
                results.append(classes.Proper(title, url, datetime.datetime.today(), self.show))

        return results

    def seedRatio(self):
        return self.ratio


class ManicomioShareCache(tvcache.TVCache):
    def __init__(self, provider):

        tvcache.TVCache.__init__(self, provider)

        self.minTime = 20

    def _getRSSData(self):
        search_params = {'RSS': []}
        return {'entries': self.provider._doSearch(search_params)}


provider = ManicomioShareProvider()
