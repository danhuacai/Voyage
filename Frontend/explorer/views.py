from django.shortcuts import HttpResponse
from django.http import HttpResponseRedirect
from subprocess import Popen
from explorer.models import ReferringSite, SourceSite, Keyword, ReferringTwitter, SourceTwitter
import sys, os, time, json

import newspaper

def validate_site(site):
    try:
        s = newspaper.build(site, memoize_articles=False,
                            keep_article_html=True,
                            fetch_images=False,
                            language='en')
        return HttpResponse(format('%s articles found using RSS Scan!' % s.size()))
    except:
        return HttpResponse(format('%s is not a valid Referring Site!' % site))

def command(request):
    if request.method == 'POST':
        if request.POST.get('acommand') == 'Run':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "article", "run"], cwd=path)

        if request.POST.get('acommand') == 'Pause':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "article", "pause"], cwd=path)

        if request.POST.get('acommand') == 'Stop':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "article", "stop"], cwd=path)

        if request.POST.get('acommand') == '[F]Stop':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "article", "fstop"], cwd=path)

        if request.POST.get('tcommand') == 'Run':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "twitter", "run"], cwd=path)

        if request.POST.get('tcommand') == 'Pause':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "twitter", "pause"], cwd=path)

        if request.POST.get('tcommand') == 'Stop':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "twitter", "stop"], cwd=path)

        if request.POST.get('tcommand') == '[F]Stop':
            path = os.path.dirname(os.path.realpath(__file__))
            Popen(["python", path + "/../../src/executer.py", "twitter", "fstop"], cwd=path)

        if request.POST.get('url'):
        	return validate_site(request.POST.get('url'))

        if request.POST.get('referring'):
            referring = request.POST.get('referring')
            for site in SourceSite.objects.all():
                if site.url == referring:
                    return HttpResponse(format('%s exists in Source Sites Scope.' % referring))
            return HttpResponse(format('%s does not exist in Source Sites Scope.' % referring))

    return HttpResponseRedirect("/admin")

def getJson(request):
    scope = {'referring_sites':{}, 'source_sites': {}, 
             'keywords': [], 'referring_twitter_accounts': [], 'source_twitter_accounts': []}

    for site in ReferringSite.objects.all():
        scope['referring_sites'][site.url] = {'name': site.name}

    for site in SourceSite.objects.all():
        scope['source_sites'][site.url] = {'name': site.name}

    for key in Keyword.objects.all():
        scope['keywords'].append(key.name)

    for acc in ReferringTwitter.objects.all():
        scope['referring_twitter_accounts'].append(acc.name)
    for acc in SourceTwitter.objects.all():
	scope['source_twitter_accounts'].append(acc.name)

    res = HttpResponse(json.dumps(scope, indent=2, sort_keys=True))
    res['Content-Disposition'] = format('attachment; filename=scope-%s.json' 
                                        % time.strftime("%Y%m%d-%H%M%S"))
    return res
