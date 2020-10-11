import xbmc
import xbmcgui
import xbmcvfs
import resources.lib.helpers.rpc as rpc
import resources.lib.helpers.cache as cache
import resources.lib.helpers.timedate as timedate
import resources.lib.helpers.decorators as decorators
from resources.lib.tmdb.api import TMDb
from resources.lib.trakt.api import TraktAPI
from resources.lib.helpers.plugin import kodi_log, ADDON
from resources.lib.helpers.parser import try_int
from resources.lib.helpers.fileutils import validify_filename, make_path, write_to_file, get_tmdb_id_nfo


BASEDIR_MOVIE = ADDON.getSettingString('movies_library') or 'special://profile/addon_data/plugin.video.themoviedb.helper/movies/'
BASEDIR_TV = ADDON.getSettingString('tvshows_library') or 'special://profile/addon_data/plugin.video.themoviedb.helper/tvshows/'
DEBUG_LOGGING = ADDON.getSettingBool('debug_logging')
"""
IMPORTANT: These limits are set to prevent excessive API data usage.
Please respect the APIs that provide this data for free.
"""
LIBRARY_ADD_LIMIT_TVSHOWS = 500
LIBRARY_ADD_LIMIT_MOVIES = 2500


def replace_content(content, old, new):
    content = content.replace(old, new)
    return replace_content(content, old, new) if old in content else content


def clean_content(content, details='info=play'):
    content = content.replace('info=related', details)
    content = content.replace('info=flatseasons', details)
    content = content.replace('info=details', details)
    content = content.replace('fanarttv=True', '')
    content = content.replace('widget=True', '')
    content = content.replace('localdb=True', '')
    content = content.replace('nextpage=True', '')
    content = replace_content(content, '&amp;', '&')
    content = replace_content(content, '&&', '&')
    content = replace_content(content, '?&', '?')
    content = content + '&islocal=True' if '&islocal=True' not in content else content
    return content


def check_overlimit(request):
    """
    IMPORTANT: Do not change limits.
    Please respect the APIs that provide this data for free.
    Returns None if NOT overlimit. Otherwise returns dict containing totals in request.
    """
    if len(request) <= min(LIBRARY_ADD_LIMIT_TVSHOWS, LIBRARY_ADD_LIMIT_MOVIES):
        return

    totals = {}
    for i in request:
        totals[i.get('type', 'none')] = totals.get(i.get('type', 'none'), 0) + 1

    if totals.get('show', 0) <= LIBRARY_ADD_LIMIT_TVSHOWS:
        if totals.get('movie', 0) <= LIBRARY_ADD_LIMIT_MOVIES:
            return

    return totals


def create_file(filename, content, *args, **kwargs):
    """
    Create the file and folder structure: filename=.strm file, content= content of file.
    *args = folders to create.
    """

    # Validify and build path
    path = kwargs.get('basedir', '').replace('\\', '/')  # Convert MS-DOS style paths to UNIX style
    if not path:  # Make sure we actually have a basedir
        return
    for folder in args:
        folder = validify_filename(folder)
        path = '{}{}/'.format(path, folder)

    # Validify content of file
    if kwargs.get('clean_url', True):
        content = clean_content(content)
    if not content:
        return
    if not filename:
        return

    # Check that we can actually make the path
    if not make_path(path, warn_dialog=True):
        return

    # Write out our file
    filepath = '{}{}.{}'.format(path, validify_filename(filename), kwargs.get('file_ext', 'strm'))
    write_to_file(filepath, content)
    kodi_log(['ADD LIBRARY -- Successfully added:\n', filepath, '\n', content], 2)
    return filepath


def create_nfo(tmdb_type, tmdb_id, *args, **kwargs):
    filename = 'movie' if tmdb_type == 'movie' else 'tvshow'
    content = 'https://www.themoviedb.org/{}/{}'.format(tmdb_type, tmdb_id)
    create_file(filename, content, file_ext='nfo', *args, **kwargs)


def create_playlist(items, dbtype, user_slug, list_slug):
    """
    Creates a smart playlist from a list of titles
    """
    filename = '{}-{}-{}'.format(user_slug, list_slug, dbtype)
    filepath = 'special://profile/playlists/video/'
    fcontent = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>']
    fcontent.append(u'<smartplaylist type="{}">'.format(dbtype))
    fcontent.append(u'    <name>{} by {} ({})</name>'.format(list_slug, user_slug, dbtype))
    fcontent.append(u'    <match>any</match>')
    for i in items:
        fcontent.append(u'    <rule field="{}" operator="is"><value>{}</value></rule>'.format(i[0], i[1]))
    fcontent.append(u'</smartplaylist>')
    create_file(filename, '\n'.join(fcontent), basedir=filepath, file_ext='xsp', clean_url=False)


def add_movie(tmdb_id, imdb_id=None, title='', year='', kodi_db=None):
    content = 'plugin://plugin.video.themoviedb.helper/?info=play&tmdb_id={}&tmdb_type=movie'.format(tmdb_id)
    folder = u'{} ({})'.format(title, year)
    kodi_db = kodi_db or rpc.get_kodi_library('movie')
    db_file = kodi_db.get_info(info='file', imdb_id=imdb_id, tmdb_id=tmdb_id)

    if not db_file:
        log_msg = u'Adding {} to library...'.format(folder)
        db_file = create_file(folder, content, folder, basedir=BASEDIR_MOVIE)
        create_nfo('movie', tmdb_id, folder, basedir=BASEDIR_MOVIE)
    else:
        log_msg = u'Found {} in library.'.format(folder)

    kodi_log(log_msg)
    return ('filename', db_file.replace('\\', '/').split('/')[-1])


def add_tvshow(basedir=None, folder=None, url=None, tmdb_id=None, tvdb_id=None, imdb_id=None, p_dialog=None, force=False, kodi_db=None):
    if not basedir or not folder or not url or not tmdb_id:
        return

    # Get our cached info
    cache_name = 'library_autoupdate_tv.{}'.format(tmdb_id)
    cache_info = {} if force else cache.get_cache(cache_name) or {}
    cache_version = 1

    # If there's already a folder for a different show with the same name then create a separate folder
    nfo_id = get_tmdb_id_nfo(basedir, folder) if folder in xbmcvfs.listdir(basedir)[0] else None
    if nfo_id and try_int(nfo_id) != try_int(tmdb_id):
        folder += ' (TMDB {})'.format(tmdb_id)

    # Only use cache info if version matches
    if not cache_info.get('version') or cache_info.get('version') != cache_version:
        cache_info = {}

    # If there is a next check value and it hasn't elapsed then skip the update
    next_check = cache_info.get('next_check')
    if next_check and timedate.is_future_timestamp(next_check, "%Y-%m-%d", 10):
        if DEBUG_LOGGING:
            log_msg = cache_info.get('log_msg') or ''
            kodi_log([
                'Skipping updating', cache_info.get('name'), 'TMDB_id', tmdb_id, '\n',
                'Next update', next_check, log_msg], 2)
        return

    # Get all seasons in the tvshow except specials
    details_tvshow = TMDb().get_request_sc('tv', tmdb_id, append_to_response='external_ids')
    if not details_tvshow:
        return

    # Update IDs from detailed info
    tvdb_id = details_tvshow.get('external_ids', {}).get('tvdb_id') or tvdb_id
    imdb_id = details_tvshow.get('external_ids', {}).get('imdb_id') or imdb_id

    # Create the .nfo file in the folder
    create_nfo('tv', tmdb_id, folder, basedir=basedir)

    # Construct our cache object
    today_date = timedate.get_todays_date()
    my_history = {
        'version': cache_version,
        'name': details_tvshow.get('name', ''),
        'skipped': [],
        'episodes': [],
        'latest_season': 0,
        'next_check': today_date,
        'last_check': today_date,
        'log_msg': ''}

    # Set the next check date for this show
    next_aired = details_tvshow.get('next_episode_to_air', {})
    if next_aired and next_aired.get('air_date'):
        next_aired_dt = next_aired.get('air_date')
        if timedate.is_future_timestamp(next_aired_dt, "%Y-%m-%d", 10):
            if not timedate.is_future_timestamp(next_aired_dt, "%Y-%m-%d", 10, days=7):
                my_history['next_check'] = next_aired.get('air_date')
                my_history['log_msg'] = '\nShow had next aired date this week'
                # Check again on the next aired date
            elif not timedate.is_future_timestamp(next_aired_dt, "%Y-%m-%d", 10, days=30):
                my_history['next_check'] = timedate.get_todays_date(days=7)
                my_history['log_msg'] = '\nShow has next aired date this month'
                # Check again in a week just to be safe in case air date changes
            else:
                my_history['next_check'] = timedate.get_todays_date(days=30)
                my_history['log_msg'] = '\nShow has next aired date in more than a month'
                # Check again in a month just to be safe in case air date changes
        else:
            next_aired = None  # Next aired was in the past for some reason so dont use that date

    last_aired = details_tvshow.get('last_episode_to_air', {})
    if not next_aired and last_aired and last_aired.get('air_date'):
        last_aired_dt = last_aired.get('air_date')
        if timedate.is_future_timestamp(last_aired_dt, "%Y-%m-%d", 10, days=-30):
            my_history['next_check'] = timedate.get_todays_date(days=1)
            my_history['log_msg'] = '\nShow aired in last month but no next aired date'
            # Show might be currently airing but just hasnt updated next date yet so check again tomorrow
        elif timedate.is_future_timestamp(last_aired_dt, "%Y-%m-%d", 10, days=-90):
            my_history['log_msg'] = '\nShow aired in last quarter but not in last month'
            my_history['next_check'] = timedate.get_todays_date(days=7)
            # Show might be on a mid-season break so check again in a week for a return date
        elif details_tvshow.get('status') in ['Canceled', 'Ended']:
            my_history['log_msg'] = '\nShow was canceled or ended'
            my_history['next_check'] = timedate.get_todays_date(days=30)
            # Show was canceled so check again in a month just to be safe
        else:
            my_history['log_msg'] = '\nShow last aired more than 3 months ago and no next aired date set'
            my_history['next_check'] = timedate.get_todays_date(days=7)
            # Show hasnt aired in a while so check every week for a return date

    kodi_db = kodi_db or rpc.get_kodi_library('tv')
    tv_dbid = kodi_db.get_info(info='dbid', imdb_id=imdb_id, tmdb_id=tmdb_id, tvdb_id=tvdb_id)

    prev_added_eps = cache_info.get('episodes') or []
    prev_skipped_eps = cache_info.get('skipped') or []

    seasons = details_tvshow.get('seasons', [])
    s_total = len(seasons)
    for s_count, season in enumerate(seasons):
        # Skip special seasons
        if season.get('season_number', 0) == 0:
            if DEBUG_LOGGING:
                kodi_log(u'{} (TMDB {})\nSpecial Season. Skipping...'.format(
                    details_tvshow.get('name'), tmdb_id), 2)
            s_total -= 1
            continue

        season_name = u'Season {}'.format(season.get('season_number'))

        # Update our progress dialog
        if p_dialog:
            p_dialog_val = ((s_count + 1) * 100) // s_total
            p_dialog_msg = u'{} {} - {}...'.format(
                ADDON.getLocalizedString(32167), details_tvshow.get('original_name'), season_name)
            p_dialog.update(p_dialog_val, message=p_dialog_msg)

        # If weve scanned before we only want to scan the most recent seasons (that have already started airing)
        latest_season = try_int(cache_info.get('latest_season', 0))
        if try_int(season.get('season_number', 0)) < latest_season:
            if DEBUG_LOGGING:
                kodi_log(u'{} (TMDB {})\nPreviously Added {}. Skipping...'.format(
                    details_tvshow.get('name'), tmdb_id, season_name), 2)
            continue

        # Get all episodes in the season except specials
        details_season = TMDb().get_request('tv', tmdb_id, 'season', season.get('season_number'), cache_refresh=True)
        if not details_season:
            kodi_log(u'{} (TMDB {})\nNo details found for {}. Skipping...'.format(
                details_tvshow.get('name'), tmdb_id, season_name))
            return
        episodes = [i for i in details_season.get('episodes', []) if i.get('episode_number', 0) != 0]  # Only get non-special seasons
        skipped_eps, future_eps, library_eps = [], [], []
        for e_count, episode in enumerate(episodes):
            episode_name = 'S{:02d}E{:02d} - {}'.format(
                try_int(season.get('season_number')),
                try_int(episode.get('episode_number')),
                validify_filename(episode.get('name')))

            my_history['episodes'].append(episode_name)

            # Skip episodes we added in the past
            if episode_name in prev_added_eps:
                if episode_name not in prev_skipped_eps:
                    if DEBUG_LOGGING:
                        skipped_eps.append(episode_name)
                    continue

            # Skip future episodes
            if ADDON.getSettingBool('hide_unaired_episodes'):
                if timedate.is_future_timestamp(episode.get('air_date'), "%Y-%m-%d", 10):
                    if DEBUG_LOGGING:
                        future_eps.append(episode_name)
                    my_history['skipped'].append(episode_name)
                    continue

            # Check if item has already been added
            if tv_dbid and rpc.KodiLibrary(
                    dbtype='episode', tvshowid=tv_dbid).get_info(
                    info='dbid', season=season.get('season_number'), episode=episode.get('episode_number')):
                if DEBUG_LOGGING:
                    library_eps.append(episode_name)
                continue

            # Update progress dialog
            if p_dialog:
                p_dialog.update(((e_count + 1) * 100) // len(episodes))

            # Create our .strm file for the episode
            episode_path = 'plugin://plugin.video.themoviedb.helper/?info=play&tmdb_type=tv&islocal=True'
            episode_path = '{}&tmdb_id={}&season={}&episode={}'.format(
                episode_path, tmdb_id, season.get('season_number', 0), episode.get('episode_number'))
            create_file(episode_name, episode_path, folder, season_name, basedir=basedir)

        # Some logging of what we did
        if DEBUG_LOGGING:
            klog_msg = [u'{} (TMDB {}) - {} - Done!'.format(details_tvshow.get('name'), tmdb_id, season_name)]
            if skipped_eps:
                klog_msg += [u'\nSkipped Previously Added Episodes:\n{}'.format(skipped_eps)]
            if library_eps:
                klog_msg += [u'\nSkipped Episodes in Library:\n{}'.format(library_eps)]
            if future_eps:
                klog_msg += [u'\nSkipped Unaired Episodes:\n{}'.format(future_eps)]
            kodi_log(klog_msg, 2)

        # Store a season value of where we got up to
        if len(episodes) > 2:
            # Make sure the season has actually aired!
            if season.get('air_date') and not timedate.is_future_timestamp(season.get('air_date'), "%Y-%m-%d", 10):
                my_history['latest_season'] = try_int(season.get('season_number'))

    # Store details about what we did into the cache
    cache.set_cache(my_history, cache_name, cache_days=120)


def get_userlist(user_slug=None, list_slug=None, confirm=True, busy_dialog=True):
    with decorators.busy_dialog(is_enabled=busy_dialog):
        request = TraktAPI().get_response_json('users', user_slug, 'lists', list_slug, 'items')
    if not request:
        return
    if confirm:
        d_head = ADDON.getLocalizedString(32125)
        i_check_limits = check_overlimit(request)
        if i_check_limits:
            # List over limit so inform user that it is too large to add
            d_body = [
                ADDON.getLocalizedString(32168).format(list_slug, user_slug),
                ADDON.getLocalizedString(32170).format(i_check_limits.get('show'), i_check_limits.get('movie')),
                '',
                ADDON.getLocalizedString(32164).format(LIBRARY_ADD_LIMIT_TVSHOWS, LIBRARY_ADD_LIMIT_MOVIES)]
            xbmcgui.Dialog().ok(d_head, '\n'.join(d_body))
            return
        elif confirm != 2:  # Set confirm param to 2 to only check limits
            # List is within limits so ask for confirmation before adding it
            d_body = [
                ADDON.getLocalizedString(32168).format(list_slug, user_slug),
                ADDON.getLocalizedString(32171).format(len(request)) if len(request) > 20 else '',
                '',
                ADDON.getLocalizedString(32126)]
            if not xbmcgui.Dialog().yesno(d_head, '\n'.join(d_body)):
                return
    return request


def add_userlist(user_slug=None, list_slug=None, confirm=True, allow_update=True, busy_dialog=True, force=False):
    # user_slug = user_slug or sys.listitem.getProperty('Item.user_slug')
    # list_slug = list_slug or sys.listitem.getProperty('Item.list_slug')

    request = get_userlist(user_slug=user_slug, list_slug=list_slug, confirm=confirm, busy_dialog=busy_dialog)
    i_total = len(request)

    p_dialog = xbmcgui.DialogProgressBG() if busy_dialog else None
    p_dialog.create('TMDbHelper', ADDON.getLocalizedString(32166)) if p_dialog else None

    all_movies = []
    all_tvshows = []

    for i_count, i in enumerate(request):
        i_type = i.get('type')
        if i_type not in ['movie', 'show']:
            continue

        item = i.get(i_type, {})
        tmdb_id = item.get('ids', {}).get('tmdb')
        imdb_id = item.get('ids', {}).get('imdb')
        tvdb_id = item.get('ids', {}).get('tvdb')

        if not tmdb_id:  # Extra request for ID lookup is too expensive so skip
            kodi_log(u'{} ({}) - Missing TMDb ID! Skipping...'.format(item.get('title'), item.get('year')), 2)
            continue

        if p_dialog:
            p_dialog.update(
                ((i_count + 1) * 100) // i_total,
                message=u'Adding {} ({})...'.format(item.get('title'), item.get('year')))

        if i_type == 'movie':
            playlist_item = add_movie(tmdb_id=tmdb_id, imdb_id=imdb_id, title=item.get('title'), year=item.get('year'))
            all_movies.append(playlist_item)

        if i_type == 'show':
            playlist_item = ('title', item.get('title'))
            all_tvshows.append(playlist_item)
            add_tvshow(
                basedir=BASEDIR_TV,
                folder=u'{}'.format(item.get('title')),
                url='plugin://plugin.video.themoviedb.helper/?info=seasons&nextpage=True&tmdb_id={}&tmdb_type=tv'.format(tmdb_id),
                tmdb_id=tmdb_id, imdb_id=imdb_id, tvdb_id=tvdb_id, p_dialog=p_dialog, force=force)

    if p_dialog:
        p_dialog.close()
    if all_movies:
        create_playlist(all_movies, 'movies', user_slug, list_slug)
    if all_tvshows:
        create_playlist(all_tvshows, 'tvshows', user_slug, list_slug)
    if allow_update and ADDON.getSettingBool('auto_update'):
        xbmc.executebuiltin('UpdateLibrary(video)')
