import sys
import xbmc
import xbmcplugin
from resources.lib.helpers.constants import NO_LABEL_FORMATTING, RANDOMISED_TRAKT, RANDOMISED_LISTS, TRAKT_LIST_OF_LISTS, TMDB_BASIC_LISTS, TRAKT_BASIC_LISTS, TRAKT_SYNC_LISTS
from resources.lib.helpers.rpc import get_kodi_library
from resources.lib.helpers.plugin import convert_type, TYPE_CONTAINER, reconfigure_legacy_params
from resources.lib.script.router import related_lists
from resources.lib.items.listitem import ListItem
from resources.lib.tmdb.api import TMDb
from resources.lib.trakt.api import TraktAPI
from resources.lib.fanarttv.api import FanartTV
from resources.lib.items.utils import ItemUtils
from resources.lib.player.players import Players
from resources.lib.helpers.plugin import ADDON, kodi_log, ADDONPATH, viewitems
from resources.lib.items.basedir import BaseDirLists
from resources.lib.tmdb.lists import TMDbLists
from resources.lib.trakt.lists import TraktLists
from resources.lib.tmdb.search import SearchLists
from resources.lib.tmdb.discover import UserDiscoverLists
from resources.lib.helpers.parser import try_decode, parse_paramstring, try_int
from resources.lib.helpers.setutils import split_items, random_from_list, merge_two_dicts
# from resources.lib.helpers.decorators import timer_report


def filtered_item(item, key, value, exclude=False):
    boolean = False if exclude else True  # Flip values if we want to exclude instead of include
    if key and value and item.get(key) == value:
        boolean = exclude
    return boolean


class Container(object, TMDbLists, BaseDirLists, SearchLists, UserDiscoverLists, TraktLists):
    def __init__(self):
        self.handle = int(sys.argv[1])
        self.paramstring = try_decode(sys.argv[2][1:])
        self.params = parse_paramstring(sys.argv[2][1:])
        self.parent_params = self.params
        self.update_listing = False
        self.plugin_category = ''
        self.container_content = ''
        self.container_update = None
        self.container_refresh = False
        self.item_type = None
        self.kodi_db = None
        self.library = None
        self.tmdb_cache_only = True
        self.trakt_api = TraktAPI()
        self.tmdb_api = TMDb()
        self.is_widget = True if self.params.pop('widget', '').lower() == 'true' else False
        self.hide_watched = ADDON.getSettingBool('widgets_hidewatched') if self.is_widget else False
        self.flatten_seasons = ADDON.getSettingBool('flatten_seasons')
        self.ftv_forced_lookup = self.params.pop('fanarttv', '').lower()
        self.filter_key = self.params.pop('filter_key', None)
        self.filter_value = split_items(self.params.pop('filter_value', None))[0]
        self.exclude_key = self.params.pop('exclude_key', None)
        self.exclude_value = split_items(self.params.pop('exclude_value', None))[0]
        self.pagination = self.pagination_is_allowed()
        self.params = reconfigure_legacy_params(**self.params)

    def pagination_is_allowed(self):
        if self.params.pop('nextpage', '').lower() == 'false':
            return False
        if self.is_widget and not ADDON.getSettingBool('widgets_nextpage'):
            return False
        return True

    def ftv_is_cache_only(self):
        if self.ftv_forced_lookup == 'true':
            return False
        if self.ftv_forced_lookup == 'false':
            return True
        if self.is_widget and ADDON.getSettingBool('widget_fanarttv_lookup'):
            return False
        if not self.is_widget and ADDON.getSettingBool('fanarttv_lookup'):
            return False
        return True

    # @timer_report('add_items')
    def add_items(self, items=None, pagination=True, parent_params=None, kodi_db=None, tmdb_cache_only=True):
        if not items:
            return
        check_is_aired = parent_params.get('info') not in NO_LABEL_FORMATTING
        listitem_utils = ItemUtils(
            kodi_db=self.kodi_db, trakt_api=self.trakt_api, tmdb_api=self.tmdb_api,
            ftv_api=FanartTV(cache_only=self.ftv_is_cache_only()))
        for i in items:
            if not pagination and 'next_page' in i:
                continue
            if self.item_is_excluded(i):
                continue
            listitem = ListItem(parent_params=parent_params, **i)
            listitem.set_details(details=listitem_utils.get_tmdb_details(listitem, cache_only=tmdb_cache_only))  # Quick because only get cached
            listitem.set_episode_label()
            if check_is_aired and listitem.is_unaired():
                continue
            listitem.set_details(details=listitem_utils.get_ftv_details(listitem), reverse=True)  # Slow when not cache only
            listitem.set_details(details=listitem_utils.get_kodi_details(listitem), reverse=True)  # Quick because local db
            listitem.set_playcount(playcount=listitem_utils.get_playcount_from_trakt(listitem))  # Quick because of agressive caching of Trakt object and pre-emptive dict comprehension
            if self.hide_watched and try_int(listitem.infolabels.get('playcount')) != 0:
                continue
            listitem.set_standard_context_menu()  # Set the context menu items
            listitem.set_unique_ids_to_infoproperties()  # Add unique ids to properties so accessible in skins
            listitem.set_params_info_reroute(self.ftv_forced_lookup, self.flatten_seasons)  # Reroute details to proper end point
            listitem.set_params_to_infoproperties(self.plugin_category)  # Set path params to properties for use in skins
            xbmcplugin.addDirectoryItem(
                handle=self.handle,
                url=listitem.get_url(),
                listitem=listitem.get_listitem(),
                isFolder=listitem.is_folder)

    def set_params_to_container(self, **kwargs):
        for k, v in viewitems(kwargs):
            if not k or not v:
                continue
            try:
                xbmcplugin.setProperty(self.handle, u'Param.{}'.format(k), u'{}'.format(v))  # Set params to container properties
            except Exception as exc:
                kodi_log(u'Error: {}\nUnable to set Param.{} to {}'.format(exc, k, v), 1)

    def finish_container(self, update_listing=False, plugin_category='', container_content=''):
        xbmcplugin.setPluginCategory(self.handle, plugin_category)  # Container.PluginCategory
        xbmcplugin.setContent(self.handle, container_content)  # Container.Content
        xbmcplugin.endOfDirectory(self.handle, updateListing=update_listing)

    def item_is_excluded(self, item):
        if self.filter_key and self.filter_value:
            if self.filter_key in item.get('infolabels', {}):
                if filtered_item(item['infolabels'], self.filter_key, self.filter_value):
                    return True
            elif self.filter_key in item.get('infoproperties', {}):
                if filtered_item(item['infoproperties'], self.filter_key, self.filter_value):
                    return True
        if self.exclude_key and self.exclude_value:
            if self.exclude_key in item.get('infolabels', {}):
                if filtered_item(item['infolabels'], self.exclude_key, self.exclude_value, True):
                    return True
            elif self.exclude_key in item.get('infoproperties', {}):
                if filtered_item(item['infoproperties'], self.exclude_key, self.exclude_value, True):
                    return True

    def get_kodi_database(self, tmdb_type):
        if ADDON.getSettingBool('local_db'):
            return get_kodi_library(tmdb_type)

    def get_container_content(self, tmdb_type, season=None, episode=None):
        if tmdb_type == 'tv' and season and episode:
            return convert_type('episode', TYPE_CONTAINER)
        elif tmdb_type == 'tv' and season:
            return convert_type('season', TYPE_CONTAINER)
        return convert_type(tmdb_type, TYPE_CONTAINER)

    def list_randomised_trakt(self, **kwargs):
        kwargs['info'] = RANDOMISED_TRAKT.get(kwargs.get('info'))
        kwargs['randomise'] = True
        self.parent_params = kwargs
        return self.get_items(**kwargs)

    def list_randomised(self, **kwargs):
        params = merge_two_dicts(
            kwargs, RANDOMISED_LISTS.get(kwargs.get('info')))
        item = random_from_list(self.get_items(**params))
        if not item:
            return
        self.plugin_category = item.get('label')
        return self.get_items(**item.get('params', {}))

    # @timer_report('get_items')
    def get_items(self, **kwargs):
        info = kwargs.get('info')
        if info == 'pass':
            return
        if info == 'dir_search':
            return self.list_searchdir_router(**kwargs)
        if info == 'search':
            return self.list_search(**kwargs)
        if info == 'user_discover':
            return self.list_userdiscover(**kwargs)
        if info == 'dir_discover':
            return self.list_discoverdir_router(**kwargs)
        if info == 'discover':
            return self.list_discover(**kwargs)
        if info == 'all_items':
            return self.list_all_items(**kwargs)
        if info == 'trakt_userlist':
            return self.list_userlist(**kwargs)
        if info in ['trakt_becauseyouwatched', 'trakt_becausemostwatched']:
            return self.list_becauseyouwatched(**kwargs)
        if info == 'trakt_inprogress':
            return self.list_inprogress(**kwargs)
        if info == 'trakt_nextepisodes':
            return self.list_nextepisodes(**kwargs)
        if info == 'trakt_calendar':
            return self.list_trakt_calendar(**kwargs)
        if info == 'library_nextaired':
            return self.list_trakt_calendar(library=True, **kwargs)
        if info in TRAKT_LIST_OF_LISTS:
            return self.list_lists(**kwargs)
        if info in RANDOMISED_LISTS:
            return self.list_randomised(**kwargs)
        if info in RANDOMISED_TRAKT:
            return self.list_randomised_trakt(**kwargs)

        if not kwargs.get('tmdb_id'):
            kwargs['tmdb_id'] = self.tmdb_api.get_tmdb_id(**kwargs)

        if info == 'details':
            return self.list_details(**kwargs)
        if info == 'seasons':
            return self.list_seasons(**kwargs)
        if info == 'flatseasons':
            return self.list_flatseasons(**kwargs)
        if info == 'episodes':
            return self.list_episodes(**kwargs)
        if info == 'cast':
            return self.list_cast(**kwargs)
        if info == 'crew':
            return self.list_crew(**kwargs)
        if info == 'trakt_upnext':
            return self.list_upnext(**kwargs)
        if info in TMDB_BASIC_LISTS:
            return self.list_tmdb(**kwargs)
        if info in TRAKT_BASIC_LISTS:
            return self.list_trakt(**kwargs)
        if info in TRAKT_SYNC_LISTS:
            return self.list_sync(**kwargs)
        return self.list_basedir(info)

    def get_directory(self):
        items = self.get_items(**self.params)
        if not items:
            return
        self.add_items(
            items,
            pagination=self.pagination,
            parent_params=self.parent_params,
            kodi_db=self.kodi_db,
            tmdb_cache_only=self.tmdb_cache_only)
        self.finish_container(
            update_listing=self.update_listing,
            plugin_category=self.plugin_category,
            container_content=self.container_content)
        self.set_params_to_container(**self.params)
        if self.container_update:
            xbmc.executebuiltin('Container.Update({})'.format(self.container_update))
        if self.container_refresh:
            xbmc.executebuiltin('Container.Refresh')

    def play_external(self, **kwargs):
        """
        Kodi does 5x retries to resolve url if isPlayable property is set
        Since our external players might not return resolvable files we don't use this method
        Instead we pass url to xbmc.Player() or PlayMedia() or ActivateWindow() depending on context
        However, isPlayable is forced for strm so we need to catch/prevent retries from library strm
        Otherwise Kodi will try to re-trigger the play function because we didn't resolve
        We can get around the retry by setting a dummy resolved item if playing via strm
        TMDbHelper sets an islocal flag in its strm files so we can determine what called play
        Mention of fixes in Matrix that should solve this issue so we won't need this hack anymore
        """

        if kwargs.get('islocal', False):
            xbmcplugin.setResolvedUrl(self.handle, True, ListItem(
                path='{}/resources/poster.png'.format(ADDONPATH)).get_listitem())
        if not kwargs.get('tmdb_id'):
            kwargs['tmdb_id'] = self.tmdb_api.get_tmdb_id(**kwargs)
        return Players(**kwargs).play()

    def context_related(self, **kwargs):
        if not kwargs.get('tmdb_id'):
            kwargs['tmdb_id'] = self.tmdb_api.get_tmdb_id(**kwargs)
        kwargs['container_update'] = True
        related_lists(**kwargs)

    def router(self):
        if self.params.get('info') == 'play':
            return self.play_external(**self.params)
        if self.params.get('info') == 'related':
            return self.context_related(**self.params)
        return self.get_directory()
