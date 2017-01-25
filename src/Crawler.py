from urlparse import urlparse, urljoin, urlunparse
import random
import common
import re
import logging
from ExplorerArticle import ExplorerArticle
import urlnorm
import psycopg2
from pybloom_live import ScalableBloomFilter
from collections import deque

'''
An iterator class for iterating over articles in a given site
'''

class Crawler(object):
    def __init__(self, site):
        '''
        (Crawler, str) -> Crawler
        creates a Crawler with a given origin_url
        '''
        self.site = site
        self.filters = site.referringsitefilter_set.all()
        self.domain = urlparse(site.url).netloc

        # http://alexeyvishnevsky.com/2013/11/tips-on-optimizing-scrapy-for-a-high-performance/
        # fork of pybloom: https://github.com/joseph-fox/python-bloomfilter
        self.visited = ScalableBloomFilter(
            initial_capacity=10000000,
            error_rate=0.00001)
        self.to_visit = deque()

        # Initial url
        self.to_visit.append(site.url)

        # Limit
        self.limit = common.get_config()["crawler"]["limit"]

        """
        self.probabilistic_n = common.get_config()["crawler"]["n"]
        self.probabilistic_k = common.get_config()["crawler"]["k"]

        self.db = psycopg2.connect(host='localhost',
                                   database=common.get_config()["crawler"]["postgresql"]["name"],
                                   user=common.get_config()["crawler"]["postgresql"]["user"],
                                   password=common.get_config()["crawler"]["postgresql"]["password"])
                                   
        self.cursor = self.db.cursor()
        self.already_added_urls = set()
        self.visited_table = "visited_" + str(site.id)
        self.tovisit_table = "tovisit_" + str(site.id)

        #self.cursor.execute("DROP TABLE IF EXISTS " + self.visited_table)
        #self.cursor.execute("CREATE TABLE " + self.visited_table + " (url VARCHAR(1024) PRIMARY KEY)")
        self.cursor.execute("DROP TABLE IF EXISTS " + self.tovisit_table)
        self.cursor.execute(u"CREATE TABLE " + self.tovisit_table + " (id SERIAL PRIMARY KEY, url VARCHAR(1024))")

        #self.cursor.execute(u"INSERT INTO " + self.visited_table + " VALUES (%s)", (site.url,))
        self.cursor.execute(u"INSERT INTO " + self.tovisit_table + " VALUES (DEFAULT, %s)", (site.url,))

        self.db.commit()
        """

    def __iter__(self):
        return self

    def next(self):
        '''
        (Crawler) -> newspaper.Article
        returns the next article in the sequence
        '''

        #standard non-recursive tree iteration
        try:
            while(True):

                if (len(self.visited) > self.limit):
                    raise StopIteration('Limit reached: {:d}'.format(self.limit))
                # if(self.pages_visited > self.probabilistic_n):
                #     raise StopIteration
                # self.cursor.execute("SELECT * FROM " + self.tovisit_table + " ORDER BY id LIMIT 1")
                # row = self.cursor.fetchone()
                # if(row):
                #     row_id = row[0]
                #     current_url = row[1]
                #     self.cursor.execute("DELETE FROM " + self.tovisit_table + " WHERE id=%s", (row_id,))
                # else:
                #     raise StopIteration

                # if(self._should_skip()):
                #     logging.info(u"skipping {0} randomly".format(current_url))
                #     continue

                try:
                    current_url = self.to_visit.pop()
                except IndexError:
                    raise StopIteration('to_visit is empty')

                self.visited.add(current_url)

                logging.info(u"visiting {0}".format(current_url))
                #use newspaper to download and parse the article
                article = ExplorerArticle(current_url)
                article.download()


                # get urls from the article
                for link in article.get_links():
                    url = urljoin(current_url, link.href, False)
                    if self.url_in_filter(url, self.filters):
                        logging.info("skipping url \"{0}\" because it matches filter".format(url))
                        continue
                    try:
                        parsed_url = urlparse(url)
                        parsed_as_list = list(parsed_url)
                        if(parsed_url.scheme != u"http" and parsed_url.scheme != u"https"):
                            logging.info(u"skipping url with invalid scheme: {0}".format(url))
                            continue
                        parsed_as_list[5] = ''
                        url = urlunparse(urlnorm.norm_tuple(*parsed_as_list))
                    except Exception as e:
                        logging.info(u"skipping malformed url {0}. Error: {1}".format(url, str(e)))
                        continue
                    if(not parsed_url.netloc.endswith(self.domain)):
                        continue

                    # If the url have been visited in the past, skip
                    if (url in self.visited):
                        continue

                    # Append the url to to_visit queue
                    self.to_visit.append(url)
                    logging.info(u"added {0} to the to_visit".format(url))

                return article
        except StopIteration as e:
            raise e
        except Exception as e:
            raise e

    def url_in_filter(self, url, filters):
        """
        Checks if any of the filters matches the url.
        Filters can be in regex search or normal string comparison.
        """
        for filt in filters:
            if ((filt.regex and re.search(filt.pattern, url, re.IGNORECASE)) or
                (not filt.regex and filt.pattern in url)):
                return True
        return False

    # def __del__(self):
    #     self.cleanup()

    # def cleanup(self):
    #     if(self.db):
    #         self.db.close()
    #         self.db = None
    #     if(self.cursor):
    #         self.cursor.close()
    #         self.cursor = None