import xbmc
import resources.lib.helpers.window as window
import resources.lib.monitor.common as monitor_common
from resources.lib.monitor.common import CommonMonitorFunctions
from resources.lib.monitor.images import ImageFunctions
from resources.lib.helpers.plugin import ADDON, kodi_log
from resources.lib.helpers.parser import try_decode
from threading import Thread


def get_container():
    widget_id = window.get_property('WidgetContainer', is_type=int)
    if widget_id:
        return 'Container({0}).'.format(widget_id)
    return 'Container.'


def get_container_item(container=None):
    if xbmc.getCondVisibility(
            "[Window.IsVisible(DialogPVRInfo.xml) | "
            "Window.IsVisible(movieinformation)] + "
            "!Skin.HasSetting(TMDbHelper.ForceWidgetContainer)"):
        return 'ListItem.'
    return '{}ListItem.'.format(container or get_container())


class ListItemMonitor(CommonMonitorFunctions):
    def __init__(self):
        super(ListItemMonitor, self).__init__()
        self.cur_item = 0
        self.pre_item = 1
        self.cur_folder = None
        self.pre_folder = None
        self.property_prefix = 'ListItem'

    def get_container(self):
        self.container = get_container()
        self.container_item = get_container_item(self.container)

    def get_infolabel(self, infolabel):
        return xbmc.getInfoLabel('{}{}'.format(self.container_item, infolabel))

    def get_position(self):
        return xbmc.getInfoLabel('{}CurrentItem'.format(self.container))

    def get_numitems(self):
        return xbmc.getInfoLabel('{}NumItems'.format(self.container))

    def get_imdb_id(self):
        imdb_id = self.get_infolabel('IMDBNumber') or ''
        if imdb_id.startswith('tt'):
            return imdb_id
        return ''

    def get_query(self):
        if self.get_infolabel('TvShowTitle'):
            return try_decode(self.get_infolabel('TvShowTitle'))
        if self.get_infolabel('Title'):
            return try_decode(self.get_infolabel('Title'))
        if self.get_infolabel('Label'):
            return try_decode(self.get_infolabel('Label'))

    def get_season(self):
        if self.dbtype == 'episodes':
            return self.get_infolabel('Season')
        return ''

    def get_episode(self):
        if self.dbtype == 'episodes':
            return self.get_infolabel('Episode')
        return ''

    def get_dbtype(self):
        if self.get_infolabel('Property(tmdb_type)') == 'person':
            return 'actors'
        elif xbmc.getCondVisibility(
                "Window.IsVisible(DialogPVRInfo.xml) | "
                "Window.IsVisible(MyPVRChannels.xml) | "
                "Window.IsVisible(MyPVRGuide.xml)"):
            return 'tvshows'
        dbtype = self.get_infolabel('dbtype')
        if not dbtype and self.container == 'Container.':
            return xbmc.getInfoLabel('Container.Content()') or ''
        return '{0}s'.format(dbtype) if dbtype else ''

    def get_tmdb_type(self, dbtype=None):
        dbtype = dbtype or self.dbtype
        if dbtype in ['tvshows', 'seasons', 'episodes']:
            return 'tv'
        if dbtype == 'movies':
            return 'movie'
        if dbtype == 'sets':
            return 'collection'
        if dbtype in ['actors', 'directors']:
            return 'person'

    def set_cur_item(self):
        self.dbtype = self.get_dbtype()
        self.dbid = self.get_infolabel('dbid')
        self.imdb_id = self.get_imdb_id()
        self.query = self.get_query()
        self.year = self.get_infolabel('year')
        self.season = self.get_season()
        self.episode = self.get_episode()

    def get_cur_item(self):
        return (
            self.get_infolabel('dbtype'),
            self.get_infolabel('dbid'),
            self.get_infolabel('imdb'),
            self.get_infolabel('label'),
            self.get_infolabel('year'),
            self.get_infolabel('season'),
            self.get_infolabel('episode'))

    def is_same_item(self, update=False):
        self.cur_item = self.get_cur_item()
        if self.cur_item == self.pre_item:
            return self.cur_item
        if update:
            self.pre_item = self.cur_item

    def get_cur_folder(self):
        return (self.container, xbmc.getInfoLabel('Container.Content()'), self.get_numitems())

    def is_same_folder(self, update=True):
        self.cur_folder = self.get_cur_folder()
        if self.cur_folder == self.pre_folder:
            return self.cur_folder
        if update:
            self.pre_folder = self.cur_folder

    def process_artwork(self, details, tmdb_type):
        try:
            if self.dbtype not in ['movies', 'tvshows', 'episodes']:
                if tmdb_type not in ['movie', 'tv']:
                    return
            if ADDON.getSettingBool('service_fanarttv_lookup'):
                details = self.get_fanarttv_artwork(details, tmdb_type)
            if not self.is_same_item():
                return
            self.set_iter_properties(details.get('art', {}), monitor_common.SETMAIN_ARTWORK)

            # Crop Image
            if details.get('clearlogo'):
                if xbmc.getCondVisibility("Skin.HasSetting(TMDbHelper.EnableCrop)"):
                    self.crop_img = ImageFunctions(method='crop', artwork=details.get('clearlogo'))
                    self.crop_img.setName('crop_img')
                    self.crop_img.start()

        except Exception as exc:
            kodi_log(u'Func: process_artwork\n{}'.format(exc), 1)

    def process_ratings(self, details, tmdb_type, tmdb_id):
        try:
            if tmdb_type not in ['movie', 'tv']:
                return
            details = self.get_omdb_ratings(details)
            if tmdb_type == 'movie':
                details = self.get_imdb_top250_rank(details)
            if tmdb_type in ['movie', 'tv']:
                details = self.get_trakt_ratings(
                    details, 'movie' if tmdb_type == 'movie' else 'show',
                    season=self.season, episode=self.episode)
            if not self.is_same_item():
                return
            self.set_iter_properties(details.get('infoproperties', {}), monitor_common.SETPROP_RATINGS)
        except Exception as exc:
            kodi_log(u'Func: process_ratings\n{}'.format(exc), 1)

    def clear_on_scroll(self):
        if not self.properties and not self.index_properties:
            return
        if self.is_same_item():
            return
        ignore_keys = None
        if self.dbtype in ['episodes', 'seasons']:
            ignore_keys = monitor_common.SETMAIN_ARTWORK
        self.clear_properties(ignore_keys=ignore_keys)

    def get_artwork(self, source='', fallback=''):
        source = source.lower()
        infolabels = ['Art(thumb)']
        if source == 'poster':
            infolabels = ['Art(tvshow.poster)', 'Art(poster)', 'Art(thumb)']
        elif source == 'fanart':
            infolabels = ['Art(fanart)', 'Art(thumb)']
        elif source == 'landscape':
            infolabels = ['Art(landscape)', 'Art(fanart)', 'Art(thumb)']
        elif source and source != 'thumb':
            infolabels = source.split("|")
        for i in infolabels:
            artwork = self.get_infolabel(i)
            if artwork:
                return artwork
        return fallback

    def get_listitem(self):
        self.get_container()

        # Don't bother getting new details if we've got the same item
        if self.is_same_item(update=True):
            return

        # Parent folder item so clear properties and stop
        if self.get_infolabel('Label') == '..':
            return self.clear_properties()

        # Set our is_updating flag
        window.get_property('IsUpdating', 'True')

        # If the folder changed let's clear all the properties before doing a look-up
        # Possible that our new look-up will fail so good to have a clean slate
        if not self.is_same_folder():
            self.clear_properties()

        # Get look-up details
        self.set_cur_item()

        # Blur Image
        if xbmc.getCondVisibility("Skin.HasSetting(TMDbHelper.EnableBlur)"):
            self.blur_img = ImageFunctions(method='blur', artwork=self.get_artwork(
                source=window.get_property('Blur.SourceImage'),
                fallback=window.get_property('Blur.Fallback')))
            self.blur_img.setName('blur_img')
            self.blur_img.start()

        # Desaturate Image
        if xbmc.getCondVisibility("Skin.HasSetting(TMDbHelper.EnableDesaturate)"):
            self.desaturate_img = ImageFunctions(method='desaturate', artwork=self.get_artwork(
                source=window.get_property('Desaturate.SourceImage'),
                fallback=window.get_property('Desaturate.Fallback')))
            self.desaturate_img.setName('desaturate_img')
            self.desaturate_img.start()

        # CompColors
        if xbmc.getCondVisibility("Skin.HasSetting(TMDbHelper.EnableColors)"):
            self.colors_img = ImageFunctions(method='colors', artwork=self.get_artwork(
                source=window.get_property('Colors.SourceImage'),
                fallback=window.get_property('Colors.Fallback')))
            self.colors_img.setName('colors_img')
            self.colors_img.start()

        # Allow early exit to only do image manipulations
        if xbmc.getCondVisibility("!Skin.HasSetting(TMDbHelper.Service)"):
            return window.get_property('IsUpdating', clear_property=True)

        # Need a TMDb type to do a details look-up so exit if we don't have one
        tmdb_type = self.get_tmdb_type()
        if not tmdb_type:
            return window.get_property('IsUpdating', clear_property=True)

        # Immediately clear some properties like ratings and artwork
        # Don't want these to linger on-screen if the look-up takes a moment
        if self.dbtype not in ['episodes', 'seasons']:
            self.clear_property_list(monitor_common.SETMAIN_ARTWORK)
        self.clear_property_list(monitor_common.SETPROP_RATINGS)

        # Get TMDb Details
        tmdb_id = self.get_tmdb_id(
            tmdb_type, self.imdb_id, self.query,
            year=self.year if tmdb_type == 'movie' else None,
            episode_year=self.year if tmdb_type == 'tv' else None)
        details = self.tmdb_api.get_details(tmdb_type, tmdb_id, self.season, self.episode)
        if not details:
            self.clear_properties()
            return window.get_property('IsUpdating', clear_property=True)

        # TODO: Need to update Next Aired with a shorter cache time than details
        # if tmdb_type == 'tv' and details.get('infoproperties'):
        #     details['infoproperties'].update(self.tmdb_api.get_tvshow_nextaired(tmdb_id))

        # TODO: Get our artwork properties
        if xbmc.getCondVisibility("!Skin.HasSetting(TMDbHelper.DisableArtwork)"):
            thread_artwork = Thread(target=self.process_artwork, args=[details, tmdb_type])
            thread_artwork.start()

        # Item changed whilst retrieving details so lets clear and get next item
        if not self.is_same_item():
            ignore_keys = None
            if self.dbtype in ['episodes', 'seasons']:
                ignore_keys = monitor_common.SETMAIN_ARTWORK
            self.clear_properties(ignore_keys=ignore_keys)
            return window.get_property('IsUpdating', clear_property=True)

        # TODO: Get person stats
        # if tmdb_type == 'person':
        #     if xbmc.getCondVisibility("!Skin.HasSetting(TMDbHelper.DisablePersonStats)"):
        #         details = self.get_kodi_person_stats(details)

        # Get our item ratings
        if xbmc.getCondVisibility("!Skin.HasSetting(TMDbHelper.DisableRatings)"):
            thread_ratings = Thread(target=self.process_ratings, args=[details, tmdb_type, tmdb_id])
            thread_ratings.start()

        self.set_properties(details)
        window.get_property('IsUpdating', clear_property=True)
