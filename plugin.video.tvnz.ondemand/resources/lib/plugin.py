import os
import string

import arrow
from kodi_six import xbmcplugin
from slyguy import plugin, gui, settings, userdata, inputstream
from slyguy.constants import ROUTE_LIVE_TAG, ROUTE_LIVE_SUFFIX

from .api import API
from .constants import HEADERS
from .language import _

api = API()

@plugin.route('')
def home(**kwargs):
    folder = plugin.Folder()

    folder.add_item(label=_(_.SHOWS, _bold=True),      path=plugin.url_for(shows))
    folder.add_item(label=_(_.CATEGORIES, _bold=True), path=plugin.url_for(categories))
    folder.add_item(label=_(_.SEARCH, _bold=True),     path=plugin.url_for(search))
    folder.add_item(label=_(_.LIVE_TV, _bold=True),    path=plugin.url_for(live_tv))

    if settings.getBool('bookmarks', True):
        folder.add_item(label=_(_.BOOKMARKS, _bold=True),  path=plugin.url_for(plugin.ROUTE_BOOKMARKS), bookmark=False)

    folder.add_item(label=_.SETTINGS,  path=plugin.url_for(plugin.ROUTE_SETTINGS), _kiosk=False, bookmark=False)

    return folder

def _process_show(data):
    label = data['title']
    if data['badge']:
        label = _(_.BADGE, label=label, badge=data['badge']['label'])

    return plugin.Item(
        label = label,
        info  = {'plot': data['synopsis']},
        art   = {'thumb': data['tileImage']['src']+'?width=400', 'fanart': data['coverImage']['src']+'?width=1920&height=548'},
        path  = plugin.url_for(show, slug=data['page']['href'].split('/')[-1]),
    )

def _process_duration(duration):
    if not duration:
        return None

    keys = [['H', 3600], ['M', 60], ['S', 1]]

    seconds = 0
    duration = duration.lstrip('PT')
    for key in keys:
        if key[0] in duration:
            count, duration = duration.split(key[0])
            seconds += float(count) * key[1]

    return int(seconds)

def _process_video(data, showname, categories=None):
    label = '{}'.format(data['labels']['primary'])
    categories = categories or []

    replaces = {
        '${video.broadcastDateTime}': lambda: arrow.get(data['broadcastDateTime']).format('dddd D MMM'),
        '${video.seasonNumber}'     : lambda: data['seasonNumber'],
        '${video.episodeNumber}'    : lambda: data['episodeNumber'],
        '${video.title}'            : lambda: data['title'],
    }

    for replace in replaces:
        if replace in label:
            label = label.replace(replace, replaces[replace]())

    if 'Movies' in categories:
        categories.remove('Movies')
        _type = 'movie'
    else:
        _type = 'episode'

    info = {'plot': data['synopsis'], 'mediatype': _type, 'genre': categories, 'duration': _process_duration(data.get('duration'))}
    if _type == 'episode':
        info['tvshowtitle'] = showname
        info['season'] = data['seasonNumber']
        info['episode'] = data['episodeNumber']
        if data['title'] != showname:
            label = data['title']

    path = None
    meta = data['publisherMetadata']
    if 'brightcoveVideoId' in meta:
        path = plugin.url_for(play, brightcoveId=meta['brightcoveVideoId'])
    elif 'liveStreamUrl' in meta:
        path = plugin.url_for(play, livestream=meta['liveStreamUrl'], _is_live=meta['state'] != 'dvr')

        if meta['state'] == 'live':
            label = _(_.BADGE, label=label, badge=_.LIVE_NOW)
        elif meta['state'] == 'prepromotion':
            label = _(_.BADGE, label=label, badge=_.STARTING_SOON)
        elif meta['state'] == 'dvr':
            pass

    return plugin.Item(
        label    = label,
        info     = info,
        art      = {'thumb': data['image']['src']+'?width=400'},
        playable = path != None,
        path     = path,
    )

@plugin.route()
def shows(sort=None, **kwargs):
    SORT_ALL = 'ALL'
    SORT_0_9 = '0 - 9'

    sortings = [[_(_.ALL, _bold=True), SORT_ALL], [_.ZERO_NINE, SORT_0_9]]
    for letter in string.ascii_uppercase:
        sortings.append([letter, letter])

    if sort is None:
        folder = plugin.Folder(_.SHOWS)

        for sorting in sortings:
            folder.add_item(label=sorting[0], path=plugin.url_for(shows, sort=sorting[1]))

        return folder

    if sort == SORT_ALL:
        label = _.ALL
    elif sort == SORT_0_9:
        label = _.ZERO_NINE
    else:
        label = sort

    folder = plugin.Folder(_(_.SHOWS_LETTER, sort=label))

    count = 0
    for section in api.a_to_z():
        if sort == None:
            folder.add_item(
                label = section['name'],
                info  = {'plot': '{} Shows'.format(len(section['items']))},
                path  = plugin.url_for(shows, sort=section['name']),
            )

        elif sort == section['name'] or sort == SORT_ALL:
            for row in section['items']:
                item = _process_show(row['_embedded'])
                folder.add_items(item)

    return folder

@plugin.route()
def category(slug, title=None, **kwargs):
    _title, shows = api.category(slug)
    folder = plugin.Folder(title or _title)

    for row in shows:
        item = _process_show(row['_embedded'])
        folder.add_items(item)

    return folder

@plugin.route()
def categories(**kwargs):
    folder = plugin.Folder(_.CATEGORIES)

    for row in api.categories():
        folder.add_item(
            label = row['_embedded']['title'],
            info  = {'plot': row['_embedded']['synopsis']},
            art   = {'thumb': row['_embedded']['tileImage']['src']+'?width=400'},
            path  = plugin.url_for(category, slug=row['href'].split('/')[-1]),
        )

    return folder

@plugin.route()
def show(slug,  **kwargs):
    _show, sections, embedded = api.show(slug)

    categories = []
    for i in _show['categories']:
        categories.append(i['label'])

    fanart  = _show['coverImage']['src']+'?width=1920&height=548'
    folder  = plugin.Folder(_show['title'], fanart=fanart)

    count = 0
    for row in sections:
        if row['_embedded']['sectionType'] == 'similarContent':
            folder.add_item(
                label = row['label'],
                art   = {'thumb': _show['tileImage']['src']+'?width=400'},
                path  = plugin.url_for(similar, href=row['_embedded']['id'], label=_show['title'], fanart=fanart),
            )
        else:
            for module in row['_embedded']['layout']['slots']['main']['modules']:
                if module['type'] != 'showVideoCollection':
                    continue
            
                for _list in module['lists']:
                    count += 1
                    if count == 1 and _show['videosAvailable'] == 1:
                        # Try to flatten
                        try:
                            data = embedded[embedded[_list['href']]['content'][0]['href']]
                            item = _process_video(data, _show['title'], categories=categories)
                            folder.add_items(item)
                            continue
                        except:
                            pass

                    item = plugin.Item(
                        label = _list['label'] or module['label'],
                        art   = {'thumb': _show['tileImage']['src']+'?width=400'},
                        path  = plugin.url_for(video_list, href=_list['href'], label=_show['title'], fanart=fanart),
                    )

                    if 'season' in item.label.lower():
                        folder.items.insert(0, item)
                    else:
                        folder.items.append(item)

    return folder

@plugin.route()
def video_list(href, label, fanart, **kwargs):
    if 'sortOrder=oldestFirst' in href:
        limit = 60
        sort_methods = [xbmcplugin.SORT_METHOD_EPISODE, xbmcplugin.SORT_METHOD_UNSORTED, xbmcplugin.SORT_METHOD_LABEL, xbmcplugin.SORT_METHOD_DATEADDED]
    else:
        limit = 10
        sort_methods = [xbmcplugin.SORT_METHOD_UNSORTED, xbmcplugin.SORT_METHOD_EPISODE,xbmcplugin.SORT_METHOD_LABEL, xbmcplugin.SORT_METHOD_DATEADDED]

    folder = plugin.Folder(label, fanart=fanart, sort_methods=sort_methods)

    next_page = href
    while next_page:
        rows, next_page = api.video_list(next_page)

        for row in rows:
            item = _process_video(row['_embedded'], label)
            folder.add_items(item)
        
        if len(folder.items) == limit:
            break

    if next_page:
        folder.add_item(
            label       = _(_.NEXT_PAGE),
            path        = plugin.url_for(video_list, href=next_page, label=label, fanart=fanart),
            specialsort = 'bottom',
        )

    return folder

@plugin.route()
def similar(href, label, fanart, **kwargs):
    folder = plugin.Folder(label, fanart=fanart)

    for row in api.similar(href):
        item = _process_show(row['_embedded'])
        folder.add_items(item)

    return folder

@plugin.route()
def search(**kwargs):
    query = gui.input(_.SEARCH, default=userdata.get('search', '')).strip()
    if not query:
        return

    userdata.set('search', query)

    folder = plugin.Folder(_(_.SEARCH_FOR, query=query))

    for row in api.search(query):
        if row['type'] == 'show':
            item = _process_show(row)
        elif row['type'] == 'category':
            slug = row['page']['href'].split('/')[-1]
            if slug == 'shows':
                slug = 'all'

            item = plugin.Item(
                label = row['title'],
                info  = {'plot': row['searchDescription'] or row['synopsis']},
                art   = {'thumb': row['tileImage']['src']+'?width=400'},
                path  = plugin.url_for(category, slug=slug),
            )
        elif row['type'] == 'channel':
            item = plugin.Item(
                label = row['title'],
                info  = {'plot': row['searchDescription'] or row['synopsis']},
                art   = {'thumb': row['tileImage']['src']+'?width=400'},
                path  = plugin.url_for(play, channel=row['page']['href'].split('/')[-1], _is_live=True),
                playable = True,
            )
        else:
            continue

        folder.add_items(item)

    if not folder.items:
        return gui.ok(_.NO_RESULTS, heading=folder.title)

    return folder

@plugin.route()
def live_tv(**kwargs):
    folder = plugin.Folder(_.LIVE_TV)

    for row in api.channels():
        folder.add_item(
            label = row['_embedded']['title'],
            info  = {'plot': row['_embedded']['synopsis']},
            art   = {'thumb': row['_embedded']['tileImage']['src']+'?width=400'},
            playable = True,
            path = plugin.url_for(play, channel=row['href'].split('/')[-1], _is_live=True),
        )

    return folder

@plugin.route()
def play(livestream=None, brightcoveId=None, channel=None, **kwargs):
    if brightcoveId:
        item = api.get_brightcove_src(brightcoveId)

    elif livestream:
        item = plugin.Item(path=livestream, art=False, inputstream=inputstream.HLS(live=True))
        
        if kwargs.get(ROUTE_LIVE_TAG) == ROUTE_LIVE_SUFFIX and not gui.yes_no(_.PLAY_FROM, yeslabel=_.PLAY_FROM_LIVE, nolabel=_.PLAY_FROM_START):
            item.properties['ResumeTime'] = '1'
            item.properties['TotalTime']  = '1'
            
            item.inputstream = inputstream.HLS(force=True, live=True)
            if not item.inputstream.check():
                plugin.exception(_.LIVE_HLS_REQUIRED)

    elif channel:
        data = api.channel(channel)
        item = plugin.Item(path=data['publisherMetadata']['liveStreamUrl'], art=False, inputstream=inputstream.HLS(live=True))

    item.headers = HEADERS
    
    return item