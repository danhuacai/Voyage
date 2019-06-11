"""
This script retrieves monitoring site, foreign sites,
and keywords from Django database and looks into the monitoring
sites to find matching foreign sites or keywords.
newspaper package is the core to extract and retrieve relevant data.
If any keyword (of text) or foreign sites (of links) matched,
the Article will be stored at Django database as articles.models.Article.
Django's native api is used to easily access and modify the entries.
"""

__author__ = "ACME: CSCC01F14 Team 4"
__authors__ = \
    "Yuya Iwabuchi, Jai Sughand, Xiang Wang, Kyle Bridgemohansingh, Ryan Pan"

import sys
import os

# Add Django directories in the Python paths for django shell to work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                             'Frontend')))
# Append local python lib to the front to assure
# local library(mainly Django 1.7.1) to be used
sys.path.insert(0, os.path.join(os.environ['HOME'],
                                '.local/lib/python2.7/site-packages'))
# newspaper, for populating articles of each site
# and parsing most of the data.
import newspaper
# Used for newspaper's keep_article_html as it was causing error without it
import lxml.html.clean
# Regex, for parsing keywords and sources
import re
# Mainly used to make the explorer sleep
import time
import timeit
# For getting today's date with respect to the TZ specified in Django Settings
from django.utils import timezone
# For extracting 'pub_date's string into Datetime object
import dateutil
# To connect and use the Django Database
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'Frontend.settings'
# For Models connecting with the Django Database
from articles.models import*
from articles.models import Keyword as ArticleKeyword
from articles.models import SourceSite as ArticleSourceSite
from articles.models import SourceTwitter as ArticleSourceTwitter
from articles.models import Version as ArticleVersion

from articles.models import Url as ArticleUrl
from explorer.models import*
from explorer.models import SourceTwitter as ExplorerSourceTwitter
from explorer.models import Keyword as ExplorerKeyword
from explorer.models import SourceSite as ExplorerSourceSite
# To load configurations
import common
# To store the article as warc files
import warc_creator
import Crawler
# To get domain from url
import tld
# To concatenate newspaper's articles and Crawler's articles
import itertools
import requests
# For Logging
import logging
import glob
import datetime
# Custom ExlporerArticle object based on newspaper's Article
from ExplorerArticle import ExplorerArticle
# For multiprocessing
from multiprocessing import Pool, cpu_count, Process
from functools import partial
import signal
from django.db import connection
# For hashing the text
import hashlib


# For handling keyboard inturrupt
def init_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def parse_articles(referring_sites, db_keywords, source_sites_and_aliases, twitter_accounts_explorer):
    """ (list of [str, newspaper.source.Source, str],
         list of str, list of str, str) -> None
    Downloads each db_article in the site, extracts, compares
    with Foreign Sites and Keywords provided.
    Then the db_article which had a match will be stored into the Django database

    Keyword arguments:
    referring_sites     -- List of [name, 'built_article'] of each site
    db_keywords         -- List of keywords
    source_sites_and_aliases       -- Dictionary of foreign site: list of aliases
    """
    added, updated, failed, no_match = 0, 0, 0, 0

    if("DEBUG" in os.environ):
        for s in referring_sites:
            parse_articles_per_site(db_keywords, source_sites_and_aliases, twitter_accounts_explorer, s)
    else:

        connection.close()
        # Initialize multiprocessing by having cpu*2 workers
        pool = Pool(processes=len(referring_sites), maxtasksperchild=1, initializer=init_worker)

        # Use this instead of ^ when using multiprocessing.dummy
        # pool = Pool(processes=cpu_count()*4)

        # pass database informations using partial
        pass_database = partial(parse_articles_per_site, db_keywords, source_sites_and_aliases, twitter_accounts_explorer)

        # Start the multiprocessing
        #result = pool.map_async(pass_database, referring_sites)
        threads = {}
        for s in referring_sites:
            site = str(s)
            threads[site] = Process(target=pass_database, args=([s]))
            threads[site].start()

        sleeo_time = config['min_iteration_time']
        logging.warning("Sleeping for %is"%sleep_time)
       
        while True:
            for s in referring_sites:
                site = str(s)
                if (not threads[site].is_alive()):
                    time.sleep(sleep_time)
                    threads[site].join(10000)
                    threads[site] = Process(target=pass_database, args=([s]))
                    threads[site].start() 
        # Continue until all sites are done crawling
        while (not result.ready()):
            time.sleep(5)

        # Fail-safe to ensure the processes are done
        pool.close()
        pool.join()


def parse_articles_per_site(db_keywords, source_sites_and_aliases, twitter_accounts_explorer, site):

    logging.info("Started multiprocessing of Site: %s", site.name)
    # Setup logging for this site
    setup_logging(site.name)

    # Remove the source site that matches site
    if site.url in source_sites_and_aliases:
        logging.info("Removed Source Site (Referring Site is identical): {0}".format(site.url))
        del source_sites_and_aliases[site.url]

    # Generate list of source sites
    source_sites = list(source_sites_and_aliases.keys())

    # Add aliases to keywords (TODO: track alias seperately)
    db_keywords = sum(list(source_sites_and_aliases.values()), list(ExplorerKeyword.objects.values_list('name', flat=True)))

    article_count = 0
    newspaper_articles = []
    crawlersource_articles = []
    logging.info("Site: %s, Type: %i" % (site.name, site.mode))
    # 0 = newspaper, 1 = crawler, 2 = both
    error_count = 0
    if(site.mode == 0 or site.mode == 2):
        logging.disable(logging.ERROR)
        newspaper_source = newspaper.build(site.url,
                                         memoize_articles=False,
                                         keep_article_html=True,
                                         fetch_images=False,
                                         number_threads=1)
        logging.disable(logging.NOTSET)
        newspaper_articles = newspaper_source.articles
        article_count += newspaper_source.size()
        logging.info("populated {0} articles using newspaper".format(article_count))
    if(site.mode == 1 or site.mode == 2):
        # logging.info("1")
        crawlersource_articles = Crawler.Crawler(site)
        logging.info("Starting MediaCAT crawler with limit: {} from plan b crawler".format(crawlersource_articles.limit))
    # logging.info("2")

    article_iterator = itertools.chain(iter(newspaper_articles), crawlersource_articles)
    processed = 0
    # logging.info("3")

    filters = set(site.referringsitefilter_set.all())
    while True:
        time.sleep(5)
        try:
            try:
                # logging.info("4")
                article = next(article_iterator) 
                # logging.info("5")

            except ZeroDivisionError:
                article_iterator = itertools.chain(iter(newspaper_articles), crawlersource_articles)
                site.is_shallow = True
                site.save()
                processed = 0
                logging.info("sHALLOW activated")

                break
            except StopIteration:
                # logging.info("6")

                break

            processed += 1
            # logging.info("7")

            if url_in_filter(article.url, filters):
                logging.info("Matches with filter, skipping the {0}".format(article.url))
                continue

            print((
                "%s (Article|%s) %i/%i          \r" %
                (str(timezone.localtime(timezone.now()))[:-13],
                 site.name, processed, article_count)))
            logging.info("Processing %s"%article.url)
            # logging.info("8")

            url = article.url
            if 'http://www.' in url:
                url = url[:7] + url[11:]
            elif 'https://www.' in url:
                url = url[:8] + url[12:]
            article = ExplorerArticle(article.url)
            logging.debug("ExplorerArticle Created")
            # Try to download and extract the useful data
            if(not article.is_downloaded):
                if(not article.download()):
                    logging.warning("article skipped because download failed")
                    continue
            url = article.canonical_url.strip()

            if (not article.is_parsed):
                if (not article.preliminary_parse()):
                    logging.warning("article skipped because parse failed")
                    continue

            logging.debug("Article Parsed")

            logging.debug("Title: {0}".format(repr(article.title)))
            if not article.title:
                logging.info("article missing title, skipping")
                continue

            if not article.text:
                logging.info("article missing text, skipping")
                continue

            # Regex the keyword from the article's text
            keywords = get_keywords(article, db_keywords)
            logging.debug("matched keywords: {0}".format(repr(keywords)))
            # Regex the links within article's html
            sources = get_sources_sites(article, source_sites)
            filtered_sources = filter_source_sites(sources[1], source_sites)
            logging.debug("matched sources: {0}".format(repr(sources)))
            twitter_accounts = get_sources_twitter(article, twitter_accounts_explorer)
            logging.debug("matched twitter_accounts: {0}".format(repr(twitter_accounts[0])))


            
            # Add the version stuff here
            # for source in sources[0]:
            # source_article = ExplorerArticle(current_url)
            # source_article.download()
            #
            #
            #
            
            if((not keywords) and (not twitter_accounts[0]) and (all([x[1] in site.url for x in sources[0]]))):#[] gets coverted to false
                logging.debug("skipping article because it's not a match")
                continue

            article.newspaper_parse()
            # Rerun the get_keywords with text parsed by newspaper.
            keywords = get_keywords(article, db_keywords)

            if((not keywords) and (not twitter_accounts[0]) and (all([x[1] in site.url for x in sources[0]]))):#[] gets coverted to false
                logging.debug("skipping article because it's not a match")
                continue
            logging.info("match found")

            # load selectors from db!
            # parameter is a namedtuple of "css" and "regex"
            css_title = set(site.referringsitecssselector_set.filter(field=0))
            title = article.evaluate_css_selectors(css_title) or article.title
            css_author = set(site.referringsitecssselector_set.filter(field=1))
            authors = article.evaluate_css_selectors(css_author)
            if(authors):
                authors = [authors]
            else:
                authors = article.authors
            pub_date = article.evaluate_css_selectors(site.referringsitecssselector_set.filter(field=2))
            if(pub_date):
                pub_date = dateutil.parser.parse(pub_date)
            else:
                pub_date = get_pub_date(article)
            mod_date = article.evaluate_css_selectors(site.referringsitecssselector_set.filter(field=3))

            language = article.language
            text = article.get_text(strip_html=True)
            text_hash = hash_sha256(text)

            date_now=timezone.localtime(timezone.now())

            # Check if the entry already exists
            version_match = ArticleVersion.objects.filter(text_hash=text_hash)
            url_match = ArticleUrl.objects.filter(name=url)

            # if (version_match[0].article.is_source == True):
            #     version_match[0].article.is_referring = True

            # if a data article exists in the version table, and we try to add a data sourced article then set the is_source to true

            # 4 cases:
            # Version  Url      Outcome
            # match    match    Update date_last_seen
            # match    unmatch  Add new Url to article
            # unmatch  match    Add new Version to artcile
            # unmatch  unmatch  Create new Article with respective Version and Url
            if version_match:
                if (version_match[0].article.is_referring == True):
                    version = version_match[0]
                    if url_match:
                        if version_match[0].article != url_match[0].article:
                            logging.warning("Version and Url matches are not pointing to same article! versionMatchId: {0} urlMatchId:{1}".format(version.id, url_match[0].id))
                            continue
                        else:
                            logging.info("Updating date last seen of {0}".format(version.article.id))
                    else:
                        db_article = version.article
                        logging.info("Adding new Url to Article {0}".format(db_article.id))
                        db_article.url_set.create(name=url)
                    version.date_last_seen = date_now
                    version.save()
            else:
                if url_match:
                    # logging.info("AAAAAAAaoudsaosdiasd {0}".format(url))
                    db_article = url_match[0].article

                    if (db_article.is_source == True):
                        version = db_article.version_set.last()
                        version.title=title
                        version.text=text
                        version.text_hash=text_hash
                        version.language=language
                        version.date_added=date_now
                        version.date_last_seen=date_now
                        version.date_published=pub_date
                        version.save()
                    else:
                        logging.info("Adding new Version to Article {0}".format(db_article.id))

                        version = db_article.version_set.create(
                        title=title,
                        text=text,
                        text_hash=text_hash,
                        language=language,
                        date_added=date_now,
                        date_last_seen=date_now,
                        date_published=pub_date) 
                    db_article.is_referring = True
                    db_article.save()


                    for key in keywords:
                        version.keyword_set.create(name=key)

                    for author in authors:
                        version.author_set.create(name=author)
                    for account in twitter_accounts[0]:
                        version.sourcetwitter_set.create(
                            name=account,
                            matched = True)

                    for account in twitter_accounts[1]:
                        version.sourcetwitter_set.create(
                            name=account,
                            matched = False)

                    for source in sources[0]:
                        time.sleep(2)

                        # logging.info("!LLLLLLLLLLLLLLLLLLLLL  Looking at article url {0}".format(source[0]))

                        source_url_match = ArticleUrl.objects.filter(name=source[0])
                        sourcesite_url_match = True
                        if (source_url_match):
                            # logging.info("Matched URL 1")

                            sourcesite_url_match = source_url_match[0].article.version_set.last().sourcesite_set.filter(url=source[0])
                        if (source_url_match and not sourcesite_url_match): # and source_url_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                            # logging.info("Matched URL 1 Not Matched source site 1")

                            # logging.info("TO BE REMOVED found duplicate url obj")

                            source_article_url_match = source_url_match[0].article
                            #curr_last_source = source_article.version_set.last().sourcesite_set.last()

                            source_article_url_match.version_set.last().sourcesite_set.create(
                                url=source[0],
                                domain=source[1],
                                anchor_text=source[2],
                                matched=True,
                                local=(source[1] in site.url),
                                referring_url=url,
                            )
                            db_article.sources.add(source_article_url_match)
                            source_article_url_match.save()

                            db_article.save()

                            continue
                        elif (source_url_match):
                            # logging.info("Matched URL 1 Matched Source site 1")
                            continue
                        # source_version_match = ArticleVersion.objects.filter(text_hash=hash_sha256(source[0]))

                        # if (source_version_match):# and source_version_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                        #     logging.info("TO BE REMOVED found duplicate text_hash obj")
                        #     continue

                            # source_version_match[0].version_set.last().sourcesite_set.create(
                            #     url=source[0],
                            #     domain=source[1],
                            #     anchor_text=source[2],
                            #     matched=True,
                            #     local=(source[1] in site.url),
                            #     referring_url=url,
                            # )
                            # db_article.sources.add(source_version_match[0].article)
                            # source_version_match[0].article.save()

                            # db_article.save()
                            
                        source_article = ExplorerArticle(source[0])
                        source_article.download()

                        

                        #version = db_source_article.version_set.create(#)
                        

                        if(not source_article.is_downloaded):
                            if(not source_article.download()):
                                
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()
                                
                                continue
                                
                        source_article.newspaper_parse()

                        if (not source_article.is_parsed):
                            if (not source_article.preliminary_parse()):
                                
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()
                                logging.warning("Sourced article skipped because parse failed")

                                continue

                        logging.debug("Sourced Article Parsed")

                        logging.debug("Title: {0}".format(repr(article.title)))
                        if not source_article.title:
                            logging.info("Sourced article missing title, skipping")
                            
                            db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()
                            
                            continue                            
                            

                        if not source_article.text:
                            logging.info("Sourced article missing text, skipping")
                            db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()
                            
                            continue
                        
                        css_source_author = set(site.referringsitecssselector_set.filter(field=1))
                        source_authors = source_article.evaluate_css_selectors(css_source_author)
                        if(source_authors):
                            source_authors = [source_authors]
                        else:
                            source_authors = source_article.authors

                        


                        thash = hash_sha256(source_article.get_text(strip_html=True))
                        # if (len(thash) == 0):
                        #     logging.info("Invalid text hash, skip parsing")
                        #     db_source_article.version_set.create(
                        #             text_hash=hash_sha256(source[0]),
                        #             title=source[0],
                        #             source_url=source[0],
                        #             source_anchor_text=source[2],
                        #             source_matched=True,
                        #             source_local=(source[1] in site.url))
                        #     db_source_article.save()
                        #     db_article.sources.add(db_source_article)
                        #     db_source_article.save()

                        #     db_article.save()
                        #     continue

                        source_version_match = ArticleVersion.objects.filter(text_hash=thash)
                        source_url_match = ArticleUrl.objects.filter(name=source[0])

                        if (source_version_match):
                            if (source_url_match):
                                # logging.info("version match AND url match DIODJQWPDJA")

                                source_version_match[0].article.is_source = True
                                
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=True,
                                    local=(source[1] in site.url),
                                    referring_url=url,

                                )
                                source_version_match[0].article.save()                                

                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                continue
                            else:
                                # logging.info("TO BE REMOVED found duplicate text_hash objasdasdasd")
                                source_version_match[0].article.url_set.create(name=source[0])
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=True,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                source_version_match[0].article.save()

                                db_article.save()
                                
                                continue

                        db_source_article = Article(domain=source[1])
                        db_source_article.save()

                        db_source_article.url_set.create(name=source[0])
                        db_source_article.is_source = True
                        db_source_article.save()

                        source_version = db_source_article.version_set.create(
                            title=source_article.title,
                            text=source_article.get_text(strip_html=True),
                            text_hash=thash,
                            language=source_article.language,
                            date_added=date_now,
                            date_last_seen=date_now,
                            date_published=get_pub_date(source_article))

                        source_version.sourcesite_set.create(
                            url=source[0],
                            domain=source[1],
                            anchor_text=source[2],
                            matched=True,
                            local=(source[1] in site.url),
                            referring_url=url,
                        )
                        for author in source_authors:
                            source_version.author_set.create(name=author)
                        
                        keywords_sources = get_keywords(source_article, db_keywords)
                        for key in keywords_sources:
                            source_version.keyword_set.create(name=key)

                        twitter_accounts_sources = get_sources_twitter(source_article, twitter_accounts_explorer)
                        for account in twitter_accounts_sources[0]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = True)

                        for account in twitter_accounts_sources[1]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = False)

                        db_source_article.save()

                        db_article.sources.add(db_source_article)
                        db_source_article.save()

                        db_article.save()
                        # logging.info("CREATED VERSION PPPPPPPpppppppp")

                    # For all sourced articles that were filtered based on
                    # the source sites.
                    for source in filtered_sources:
                        source_sites
                        time.sleep(2)

                        # logging.info("!YYYYYYYYYYYYYYYYYYYYYYY  Looking at article url {0}".format(source[0]))

                        source_url_match = ArticleUrl.objects.filter(name=source[0])
                        sourcesite_url_match = True

                        if (source_url_match):
                            # logging.info("Matched URL 2")

                            sourcesite_url_match = source_url_match[0].article.version_set.last().sourcesite_set.filter(url=source[0])
                        if (source_url_match and not sourcesite_url_match): # and source_url_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                            # logging.info("Matched URL 2 And not source site")

                            # logging.info("TO BE REMOVED found duplicate url obj")
                            
                            
                            source_article_url_match = source_url_match[0].article

                            #curr_last_source = source_article.version_set.last().sourcesite_set.last()

                            source_article_url_match.version_set.last().sourcesite_set.create(
                                url=source[0],
                                domain=source[1],
                                anchor_text=source[2],
                                matched=False,
                                local=(source[1] in site.url),
                                referring_url=url,
                            )
                            db_article.sources.add(source_article_url_match)
                            source_article_url_match.save()

                            db_article.save()

                            continue
                        elif (source_url_match):
                            # logging.info("Matched URL 2 Source site")

                            continue
                        # source_version_match = ArticleVersion.objects.filter(text_hash=hash_sha256(source[0]))

                        # if (source_version_match):#  and source_version_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                        #     logging.info("TO BE REMOVED found duplicate text_hash obj")
                        #     continue
                            # source_version_match[0].version_set.last().sourcesite_set.create(
                            #     url=source[0],
                            #     domain=source[1],
                            #     anchor_text=source[2],
                            #     matched=False,
                            #     local=(source[1] in site.url),
                            #     referring_url=url,
                            # )
                            # db_article.sources.add(source_version_match[0].article)
                            # source_version_match[0].article.save()

                            # db_article.save()
                            
                            
                        source_article = ExplorerArticle(source[0])
                        source_article.download()

                        

                        #version = db_source_article.version_set.create(#)
                        

                        if(not source_article.is_downloaded):
                            if(not source_article.download()):

                                db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()
                                
                                continue
                                
                        source_article.newspaper_parse()

                        if (not source_article.is_parsed):
                            if (not source_article.preliminary_parse()):
                                
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()
                                
                                continue
                                
                        logging.debug("Sourced Article Parsed")

                        logging.debug("Title: {0}".format(repr(article.title)))
                        if not source_article.title:

                            db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()
                            
                            continue

                        if not source_article.text:
                            logging.info("Sourced article missing text, skipping")
                            
                            db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()
                            
                            continue
                        
                        css_source_author = set(site.referringsitecssselector_set.filter(field=1))
                        source_authors = source_article.evaluate_css_selectors(css_source_author)
                        if(source_authors):
                            source_authors = [source_authors]
                        else:
                            source_authors = source_article.authors

                        thash = hash_sha256(source_article.get_text(strip_html=True))
                        # if (len(thash) == 0):
                        #     logging.info("Invalid text hash, skip parsing")
                        #     db_source_article.version_set.create(
                        #             text_hash=hash_sha256(source[0]),
                        #             title=source[0],
                        #             source_url=source[0],
                        #             source_anchor_text=source[2],
                        #             source_matched=True,
                        #             source_local=(source[1] in site.url))
                        #     db_source_article.save()
                        #     db_article.sources.add(db_source_article)
                        #     db_source_article.save()

                        #     db_article.save()
                        #     continue

                        source_version_match = ArticleVersion.objects.filter(text_hash=thash)
                        source_url_match = ArticleUrl.objects.filter(name=source[0])

                        if (source_version_match):
                            if (source_url_match):
                                # logging.info("version match AND url match ofkdaikawdoijoqwpid")
                                source_version_match[0].article.is_source = True
                                source_version_match[0].article.save()
                                
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=False,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                continue
                            else:
                                # logging.info("TO BE REMOVED found duplicate text_hash objasdasdasd")
                                source_version_match[0].article.url_set.create(name=source[0])
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=False,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                source_version_match[0].article.save()

                                db_article.save()
                                
                                continue

                        db_source_article = Article(domain=source[1])
                        db_source_article.save()

                        db_source_article.url_set.create(name=source[0])
                        db_source_article.is_source = True
                        db_source_article.save()

                        source_version = db_source_article.version_set.create(

                            title=source_article.title,
                            text=source_article.get_text(strip_html=True),
                            text_hash=thash,
                            language=source_article.language,
                            date_added=date_now,
                            date_last_seen=date_now,
                            date_published=get_pub_date(source_article))
                        
                        source_version.sourcesite_set(
                            url=source[0],
                            domain=source[1],
                            anchor_text=source[2],
                            matched=False,
                            local=(source[1] in site.url),
                            referring_url=url,
                        )

                        for author in source_authors:
                            source_version.author_set.create(name=author)

                        keywords_sources = get_keywords(source_article, db_keywords)
                        for key in keywords_sources:
                            source_version.keyword_set.create(name=key)

                        twitter_accounts_sources = get_sources_twitter(source_article, twitter_accounts_explorer)
                        for account in twitter_accounts_sources[0]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = True)

                        for account in twitter_accounts_sources[1]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = False)

                        db_source_article.save()
                        db_article.sources.add(db_source_article)
                        db_source_article.save()

                        db_article.save()
                        # logging.info("CREATED VERSION DDDdddddddddd")

                else:
                    # If the db_article is new to the database,
                    # add it to the database
                    # if (version_match[0].article.is_source == True):
                    #     db_article = version_match[0].article

                    #     version = db_article.version_set.last()
                    #     version.title=title
                    #     version.text=text
                    #     version.text_hash=text_hash
                    #     version.language=language
                    #     version.date_added=date_now
                    #     version.date_last_seen=date_now
                    #     version.date_published=pub_date
                        
                    logging.info("Adding new Article to the DB")

                    db_article = Article(domain=site.url)
                    db_article.save()
                    db_article.url_set.create(name=url)
                    # logging.info("Adding new Article to the DB   123")

                    version = db_article.version_set.create(
                    title=title,
                    text=text,
                    text_hash=text_hash,
                    language=language,
                    date_added=date_now,
                    date_last_seen=date_now,
                    date_published=pub_date)
                    # logging.info("Adding new Article to the DB   qqqq")

                    db_article.is_referring = True
                    db_article.save()
                    for key in keywords:
                        version.keyword_set.create(name=key)
                    # logging.info("Adding new Article to the DB    4")

                    for author in authors:
                        version.author_set.create(name=author[:199])
                    for account in twitter_accounts[0]:
                        version.sourcetwitter_set.create(
                            name=account,
                            matched = True)
                    # logging.info("Adding new Article to the DB   5")

                    for account in twitter_accounts[1]:
                        version.sourcetwitter_set.create(
                            name=account,
                            matched = False)
                    # logging.info("Adding new Article to the DB   6")

                    for source in sources[0]:
                        time.sleep(2)

                        # logging.info("!ASDSDAQWDASDSAD  Looking at article url {0}".format(source[0]))

                        source_url_match = ArticleUrl.objects.filter(name=source[0])
                        sourcesite_url_match = True
                        if (source_url_match):
                            # logging.info("Matched URL 3")
                            sourcesite_url_match = source_url_match[0].article.version_set.last().sourcesite_set.filter(url=source[0])
                        if (source_url_match and not sourcesite_url_match): # and source_url_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):          logging.info("TO BE REMOVED found duplicate url obj")
                            # logging.info("Matched URL 3 and Not Source site 3")

                            source_article_url_match = source_url_match[0].article
                            #curr_last_source = source_article.version_set.last().sourcesite_set.last()

                            source_article_url_match.version_set.last().sourcesite_set.create(
                                url=source[0],
                                domain=source[1],
                                anchor_text=source[2],
                                matched=True,
                                local=(source[1] in site.url),
                                referring_url=url,
                            )
                            db_article.sources.add(source_article_url_match)
                            source_article_url_match.save()

                            db_article.save()

                            continue
                        elif (source_url_match):
                            # logging.info("Matched URL 3 and Source site 3")

                            continue
                        # source_version_match = ArticleVersion.objects.filter(text_hash=hash_sha256(source[0]))

                        # if (source_version_match): # and source_version_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                        #     logging.info("TO BE REMOVED found duplicate text_hash obj")
                        #     continue

                            # source_version_match[0].version_set.last().sourcesite_set.create(
                            #     url=source[0],
                            #     domain=source[1],
                            #     anchor_text=source[2],
                            #     matched=True,
                            #     local=(source[1] in site.url),
                            #     referring_url=url,
                            # )
                            # db_article.sources.add(source_version_match[0].article)
                            # source_version_match[0].article.save()

                            # db_article.save()
                            

                        source_article = ExplorerArticle(source[0])
                        source_article.download()
                        

                        #version = db_source_article.version_set.create(#)
                        

                        if(not source_article.is_downloaded):
                            if(not source_article.download()):
                                
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()
                                logging.warning("Sourced article skipped because download failed")
                                
                                continue

                        logging.info("download successful")
                        source_article.newspaper_parse()

                        if (not source_article.is_parsed):
                            if (not source_article.preliminary_parse()):
                                
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()

                                continue

                        logging.info("Sourced Article Parsed")

                        logging.info("Title: {0}".format(repr(article.title)))
                        if not source_article.title:
                            
                            db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()
                            logging.info("Sourced article missing title, skipping")

                            continue

                        if not source_article.text:
                            logging.info("Sourced article missing text, skipping")
                            db_source_article = add_source_article_failed(source[1],source[0], source[2], True, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()

                            continue
                        
                        css_source_author = set(site.referringsitecssselector_set.filter(field=1))
                        source_authors = source_article.evaluate_css_selectors(css_source_author)
                        if(source_authors):
                            source_authors = [source_authors]
                        else:
                            source_authors = source_article.authors

                        thash = hash_sha256(source_article.get_text(strip_html=True))

                        # if (len(thash) == 0):
                        #     logging.info("Invalid text hash, skip parsing")
                        #     db_source_article.version_set.create(
                        #             text_hash=hash_sha256(source[0]),
                        #             title=source[0],
                        #             source_url=source[0],
                        #             source_anchor_text=source[2],
                        #             source_matched=True,
                        #             source_local=(source[1] in site.url))
                        #     db_source_article.save()
                        #     db_article.sources.add(db_source_article)
                        #     db_source_article.save()

                        #     db_article.save()
                        #     continue

                        source_version_match = ArticleVersion.objects.filter(text_hash=thash)
                        source_url_match = ArticleUrl.objects.filter(name=source[0])
                        if (source_version_match):
                            if (source_url_match):
                                # logging.info("version match AND url match wuerrhqwoueuqoiwue")
                                source_version_match[0].article.is_source = True
                                source_version_match[0].article.save()
                                
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=True,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                continue
                            else:
                                # logging.info("TO BE REMOVED found duplicate text_hash objasdasdasd")
                                # source_version_match[0].article.url_set.create(name=source[0])
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=True,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                source_version_match[0].article.save()

                                db_article.save()
                                
                                continue

                        db_source_article = Article(domain=source[1])
                        db_source_article.save()

                        db_source_article.url_set.create(name=source[0])
                        db_source_article.is_source = True
                        db_source_article.save()
                        source_version = db_source_article.version_set.create(
                            title=source_article.title,
                            text=source_article.get_text(strip_html=True),
                            text_hash=thash,
                            language=source_article.language,
                            date_added=date_now,
                            date_last_seen=date_now,
                            date_published=get_pub_date(source_article))

                        source_version.sourcesite_set.create(
                            url=source[0],
                            domain=source[1],
                            anchor_text=source[2],
                            matched=True,
                            local=(source[1] in site.url),
                            referring_url=url,
                        )

                        for author in source_authors:
                            source_version.author_set.create(name=author)

                        keywords_sources = get_keywords(source_article, db_keywords)
                        for key in keywords_sources:
                            source_version.keyword_set.create(name=key)

                        twitter_accounts_sources = get_sources_twitter(source_article, twitter_accounts_explorer)
                        for account in twitter_accounts_sources[0]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = True)

                        for account in twitter_accounts_sources[1]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = False)

                        source_version.save()
                        db_source_article.save()

                        db_article.sources.add(db_source_article)
                        db_source_article.save()

                        db_article.save()

                        # logging.info("CREATED VERSION qqqQQQQQQQQ")

                    # For all sourced articles that were filtered based on
                    # the source sites.
                    for source in filtered_sources:
                        time.sleep(2)
                        # logging.info("!ZZZZZZZZZZZZZZZZ  Looking at article url {0}".format(source[0]))

                        source_url_match = ArticleUrl.objects.filter(name=source[0])
                        sourcesite_url_match = True
                        if (source_url_match):
                            # logging.info("Matched URL 4")

                            sourcesite_url_match = source_url_match[0].article.version_set.last().sourcesite_set.filter(url=source[0])
                        if (source_url_match and not sourcesite_url_match): # and source_url_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                            # logging.info("TO BE REMOVED found duplicate url obj")
                            # logging.info("Matched URL 4 And not Source site 4")

                            source_article_url_match = source_url_match[0].article
                            #curr_last_source = source_article.version_set.last().sourcesite_set.last()

                            source_article_url_match.version_set.last().sourcesite_set.create(
                                url=source[0],
                                domain=source[1],
                                anchor_text=source[2],
                                matched=False,
                                local=(source[1] in site.url),
                                referring_url=url,
                            )
                            db_article.sources.add(source_article_url_match)
                            source_article_url_match.save()

                            db_article.save()

                            continue
                        elif (source_url_match):
                            # logging.info("Matched URL 4 and Source site 4")

                            continue                       
                        # source_version_match = ArticleVersion.objects.filter(text_hash=hash_sha256(source[0]))
                        # sourcesite_hash_match = ArticleSourceSite.objects.filter(text_hash=hash_sha256(source[0]))
                        # if (source_version_match and not sourcesite_hash_match):# and source_version_match[0].article.version_set.last().sourcesite_set.last().referring_url != url):
                        #     logging.info("TO BE REMOVED found duplicate text_hash obj")
                        #     pass
                        # else (sourcesite_hash_match):
                        #     logging.info("TO BE REMOVED found duplicate url obj")
                        #     logging.info("Matched Version Text Hash 4? And not Source site text Hash 4")
                        #     #curr_last_source = source_article.version_set.last().sourcesite_set.last()

                        #     source_article_url_match.version_set.last().sourcesite_set.create(
                        #         url=source[0],
                        #         domain=source[1],
                        #         anchor_text=source[2],
                        #         matched=False,
                        #         local=(source[1] in site.url),
                        #         referring_url=url,
                        #     )
                        #     db_article.sources.add(source_article_url_match)
                        #     source_article_url_match.save()

                        #     db_article.save()
                        #     continue





                            # source_version_match[0].version_set.last().sourcesite_set.create(
                            #     url=source[0],
                            #     domain=source[1],
                            #     anchor_text=source[2],
                            #     matched=False,
                            #     local=(source[1] in site.url),
                            #     referring_url=url,
                            # )
                            # db_article.sources.add(source_version_match[0].article)
                            # source_version_match[0].article.save()

                            # db_article.save()
                            

                        source_article = ExplorerArticle(source[0])
                        source_article.download()



                        #version = db_source_article.version_set.create(#)
                        

                        if(not source_article.is_downloaded):
                            if(not source_article.download()):
                                db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()

                                continue
                                
                        source_article.newspaper_parse()

                        if (not source_article.is_parsed):
                            if (not source_article.preliminary_parse()):

                                db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                                db_article.sources.add(db_source_article)
                                db_source_article.save()
                                db_article.save()

                                continue

                        logging.debug("Sourced Article Parsed")

                        logging.debug("Title: {0}".format(repr(article.title)))
                        if not source_article.title:

                            db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()

                            continue

                        if not source_article.text:

                            db_source_article = add_source_article_failed(source[1],source[0], source[2], False, (source[1] in site.url), site.url)
                            db_article.sources.add(db_source_article)
                            db_source_article.save()
                            db_article.save()

                            continue
                        
                        css_source_author = set(site.referringsitecssselector_set.filter(field=1))
                        source_authors = source_article.evaluate_css_selectors(css_source_author)
                        if(source_authors):
                            source_authors = [source_authors]
                        else:
                            source_authors = source_article.authors

                        thash = hash_sha256(source_article.get_text(strip_html=True))

                        source_version_match = ArticleVersion.objects.filter(text_hash=thash)
                        source_url_match = ArticleUrl.objects.filter(name=source[0])

                        if (source_version_match):
                            if (source_url_match):
                                # logging.info("version match AND url match DIODJQWPDJA")
                                source_version_match[0].article.is_source = True
                                source_version_match[0].article.save()                                
                                

                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=False,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                db_article.save()

                                continue
                            else:
                                # logging.info("TO BE REMOVED found duplicate text_hash objasdasdasd")
                                source_version_match[0].article.url_set.create(name=source[0])
                                source_version_match[0].article.version_set.last().sourcesite_set.create(
                                    url=source[0],
                                    domain=source[1],
                                    anchor_text=source[2],
                                    matched=False,
                                    local=(source[1] in site.url),
                                    referring_url=url,
                                )
                                db_article.sources.add(source_version_match[0].article) # Makes a new version
                                source_version_match[0].article.save()

                                db_article.save()
                                
                                continue

                        db_source_article = Article(domain=source[1])
                        db_source_article.save()

                        db_source_article.url_set.create(name=source[0])
                        db_source_article.is_source = True
                        db_source_article.save()

                        source_version = db_source_article.version_set.create(
                            
                            title=source_article.title,
                            text=source_article.get_text(strip_html=True),
                            text_hash=thash,
                            language=source_article.language,
                            date_added=date_now,
                            date_last_seen=date_now,
                            date_published=get_pub_date(source_article))

                        source_version.sourcesite_set.create(
                            url=source[0],
                            domain=source[1],
                            anchor_text=source[2],
                            matched=False,
                            local=(source[1] in site.url),
                            referring_url=url,
                        )
                        for author in source_authors:
                            source_version.author_set.create(name=author)

                        keywords_sources = get_keywords(source_article, db_keywords)
                        for key in keywords_sources:
                            source_version.keyword_set.create(name=key)

                        twitter_accounts_sources = get_sources_twitter(source_article, twitter_accounts_explorer)
                        for account in twitter_accounts_sources[0]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = True)

                        for account in twitter_accounts_sources[1]:
                            source_version.sourcetwitter_set.create(
                                name=account,
                                matched = False)

                        source_version.save()
                        db_source_article.save()

                        db_article.sources.add(db_source_article)
                        db_source_article.save()

                        db_article.save()
                        # logging.info("CREATED VERSION tttttttttttTTTTTTTTTTTTT")


                # Add the article into queue
                logging.info("Creating new WARC")
                warc_creator.enqueue_article(url, text_hash)
                error_count = 0

        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logging.exception("Unhandled exception while crawling: " + str(e))
            error_count+=1

            # This loop is used to ensure looping error don't cause MediaCat to loop continuously on them
            if (error_count > 10):
                break


    config = common.get_config()['article']
    delta_time = timeit.default_timer() - start
    logging.warning("Delta time is %i"%delta_time)
    logging.warning("Start time is %i"%start)
    sleep_time = max(config['min_iteration_time']-delta_time, 0)
    sleep_time = config['min_iteration_time']
    logging.warning("Sleeping for %is"%sleep_time)
    time.sleep(sleep_time / 2)

    setup_logging(increment=False)
    logging.info("Finished Site: %s"%site.name)


def filter_source_sites(source_list, source_site_list):
    """
    Filters out the sites based on whether they are present in the source_sites
    list or not.
    :param source_list: The list of unfiltered sourced articles.
    :param source_site_list: The list of the actual sourced articles we want.
    :return:
    """
    filtered_list = []
    http_lengths = {'http://': 8, 'https://': 9}
    for site_to_check in source_list:
        # Only the domain url of the site is to be checked.
        site = site_to_check[0]
        # Remove all prefixes and suffixes of the website's url to be able to only compare the domain.
        for key in http_lengths.keys():
            if key in site:
                site = site.replace(key, '')
                site = site[:site.find('/') + http_lengths[key]]
        # Do the check.
        if site in source_site_list:
            filtered_list.append(site_to_check)
    return filtered_list


def add_source_article_failed(domain, title, anchor_text, matched, local, site):
    db_source_article = Article(domain=domain)
    db_source_article.save()

    db_source_article.url_set.create(name=title)
    db_source_article.is_source = True
    logging.warning("Sourced article skipped because download failed")
    db_source_article.version_set.create(
        text_hash=hash_sha256(title),
        title=title,
    ).sourcesite_set.create(
        url=title,
        domain=domain,
        anchor_text=anchor_text,
        matched=matched,
        local=local,
        referring_url=site
    )

    db_source_article.save()

    return db_source_article

def hash_sha256(text):
    hash_text = hashlib.sha256()
    hash_text.update(text.encode('utf-8'))
    return hash_text.hexdigest()


def url_in_filter(url, filters):
    """
    Checks if any of the filters matches the url.
    Filters can be in regex search or normal string comparison.
    """
    for filt in filters:
        if ((filt.regex and re.search(filt.pattern, url, re.IGNORECASE)) or
            (not filt.regex and filt.pattern in url)):
            return True
    return False


def get_sources_sites(article, sites):
    """ (str, list of str) -> list of [str, str]
    Searches and returns links redirected to sites within the html
    links will be storing the whole url and the domain name used for searching.
    Returns empty list if none found

    Keyword arguments:
    html                -- string of html
    sites               -- list of site urls to look for
    """
    result_urls_matched = []
    result_urls_unmatched = []
    # Format the site to assure only the domain name for searching
    formatted_sites = set()

    for site in sites:
        formatted_sites.add(tld.get_tld(site))

    for url in article.get_links(article_text_links_only=True):
        try:
            domain = tld.get_tld(url.href)
        #apparently they don't inherit a common class so I have to hard code it
        except (tld.exceptions.TldBadUrl, tld.exceptions.TldDomainNotFound, tld.exceptions.TldIOError):
            continue
        if domain in formatted_sites:
            # If it matches even once, append the site to the list
            result_urls_matched.append([url.href, domain, url.text])
        else:
            result_urls_unmatched.append([url.href, domain, url.text])

    # Return the list
    return [result_urls_matched, result_urls_unmatched]


def get_sources_twitter(article, source_twitter):
    matched = []
    unmatched = []
    # Twitter handle name specifications
    accounts = re.findall('(?<=^|(?<=[^a-zA-Z0-9-_\.]))@([A-Za-z]+[A-Za-z0-9]+)', article.text)

    for account in set(accounts):
        if account in source_twitter:
            matched.append(account)
        else:
            unmatched.append(account)
    return [matched,unmatched]




def get_pub_date(article):
    """ (newspaper.article.Article) -> str
    Searches and returns date of which the article was published
    Returns None otherwise

    Keyword arguments:
    article         -- 'Newspaper.Article' object of article
    """
    return article.newspaper_article.publish_date


def get_keywords(article, keywords):
    """ (newspaper.article.Article, list of str) -> list of str
    Searches and returns keywords which the article's title or text contains
    Returns empty list otherwise

    Keyword arguments:
    article         -- 'Newspaper.Article' object of article
    keywords        -- List of keywords
    """
    matched_keywords = []

    # For each keyword, check if article's text contains it
    for key in keywords:
        regex = re.compile('[^a-z]' + key + '[^a-z]', re.IGNORECASE)
        if regex.search(article.title) or regex.search(article.get_text(strip_html=True)):
            # If the article's text contains the key, append it to the list
            matched_keywords.append(key)
    # Return the list
    return matched_keywords


def explore():
    """ () -> None
    Connects to keyword and site tables in database,
    crawls within monitoring sites, then pushes articles which matches the
    keywords or foreign sites to the article database
    """

    # Retrieve and store monitoring site information
    referring_sites = ReferringSite.objects.all()
    logging.info("Collected {0} Referring Sites from Database".format(len(referring_sites)))

    source_sites_and_aliases = {}
    keyword_list = []
    source_twitter_list = []

    # Retrieve and store foreign site information
    for site in ExplorerSourceSite.objects.all():
        alias_list = []
        for alias in site.sourcesitealias_set.all():
            alias_list.append(str(alias))
        source_sites_and_aliases[site.url] = alias_list
    logging.info("Collected {0} Source Sites from Database".format(len(source_sites_and_aliases)))

    # Retrieve all stored keywords
    for key in ExplorerKeyword.objects.all():
        keyword_list.append(str(key.name))
    logging.info("Collected {0} Keywords from Database".format(len(keyword_list)))

    # Retrieve all stored twitter_accounts
    twitter_accounts = ExplorerSourceTwitter.objects.all()
    for key in twitter_accounts:
        source_twitter_list.append(str(key.name))
        for alias in key.sourcetwitteralias_set.all():
            source_twitter_list.append(str(alias))
    logging.info("Collected {0} Source Twitter Accounts from Database".format(len(source_twitter_list)))

    # Parse the articles in all sites
    parse_articles(referring_sites, keyword_list, source_sites_and_aliases, source_twitter_list)

def setup_logging(site_name="", increment=True):
    # Load the relevant configs
    config = common.get_config()

    # Logging config
    current_time = timezone.now().strftime('%Y%m%d')
    log_dir = config['projectdir']+"/log"
    prefix = log_dir + "/" + site_name + "article_explorer-"

    try:
        cycle_number = sorted(glob.glob(prefix + current_time + "*.log"))[-1][-7:-4]
        if increment:
            cycle_number = str(int(cycle_number) + 1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        cycle_number = "0"

    # Remove all handlers associated with the root logger object.
    # This will allow logging per site
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(filename=prefix + current_time + "-" + cycle_number.zfill(3) + ".log",
                        level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
    default_logger = logging.getLogger('')
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(default_logger.handlers[0].formatter)
    default_logger.addHandler(console_handler)
    # Finish logging config


if __name__ == '__main__':
    # Load the relevant configs
    config = common.get_config()['article']

    # Main logging
    setup_logging()

    # Connects to Site Database
    logging.debug("Connecting to django/database")
    django.setup()
    logging.debug("Connected to django/database")

    start = timeit.default_timer()
    # The main function, to explore the articles
    logging.info("explorer about to start")
    explore()

    	
    delta_time = timeit.default_timer() - start
    logging.info("Exploring Ended. Took %is"%delta_time)

    sleep_time = max(config['min_iteration_time']-delta_time, 0)
    logging.warning("Sleeping for %is"%sleep_time)

    time.sleep(sleep_time)

    # Re run the program to avoid thread to increase
    logging.info("Starting new cycle")
    os.chmod('article_explorer_run.sh', 0o700)
    os.execl('article_explorer_run.sh', '')
