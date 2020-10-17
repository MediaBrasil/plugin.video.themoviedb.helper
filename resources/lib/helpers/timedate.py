import xbmc
import time
import datetime
from resources.lib.helpers.plugin import kodi_log


def get_timestamp(timestamp=None):
    if not timestamp:
        return
    if time.time() > timestamp:
        return
    return timestamp


def set_timestamp(wait_time=60):
    return time.time() + wait_time


def format_date(time_str, str_fmt="%A", time_fmt="%Y-%m-%d", time_lim=10, utc_convert=False):
    if not time_str:
        return
    time_obj = convert_timestamp(time_str, time_fmt, time_lim, utc_convert=utc_convert)
    if not time_obj:
        return
    return time_obj.strftime(str_fmt)


def date_in_range(date_str, days=1, start_date=0, date_fmt="%Y-%m-%dT%H:%M:%S", date_lim=19, utc_convert=False):
    date_a = datetime.date.today() + datetime.timedelta(days=start_date)
    date_z = date_a + datetime.timedelta(days=days)
    mydate = convert_timestamp(date_str, date_fmt, date_lim, utc_convert=utc_convert).date()
    if not mydate or not date_a or not date_z:
        return
    if mydate >= date_a and mydate < date_z:
        return date_str


def get_region_date(date_obj, region='dateshort', del_fmt=':%S'):
    date_fmt = xbmc.getRegion(region).replace(del_fmt, '')
    return date_obj.strftime(date_fmt)


def is_future_timestamp(time_str, time_fmt="%Y-%m-%dT%H:%M:%S", time_lim=19, utc_convert=False, use_today=False, days=0):
    time_obj = convert_timestamp(time_str, time_fmt, time_lim, utc_convert)
    if not isinstance(time_obj, datetime.datetime):
        return
    date_obj = datetime.datetime.today() if use_today else datetime.datetime.now()
    if days:
        date_obj = date_obj + datetime.timedelta(days=days)
    if time_obj > date_obj:
        return time_str


def get_current_date_time(str_fmt='%Y-%m-%d %H:%M'):
    return datetime.datetime.now().strftime(str_fmt)


def get_todays_date(days=0):
    date_obj = datetime.datetime.today()
    if days:
        date_obj + datetime.timedelta(days=days)
    return date_obj.strftime('%Y-%m-%d')


def convert_timestamp(time_str, time_fmt="%Y-%m-%dT%H:%M:%S", time_lim=19, utc_convert=False):
    if not time_str:
        return
    time_str = time_str[:time_lim] if time_lim else time_str
    utc_offset = 0
    if utc_convert:
        utc_offset = -time.timezone // 3600
        utc_offset += 1 if time.localtime().tm_isdst > 0 else 0
    try:
        time_obj = datetime.datetime.strptime(time_str, time_fmt)
        time_obj = time_obj + datetime.timedelta(hours=utc_offset)
        return time_obj
    except TypeError:
        try:
            time_obj = datetime.datetime(*(time.strptime(time_str, time_fmt)[0:6]))
            time_obj = time_obj + datetime.timedelta(hours=utc_offset)
            return time_obj
        except Exception as exc:
            kodi_log(exc, 1)
            return
    except Exception as exc:
        kodi_log(exc, 1)
        return


def age_difference(birthday, deathday=None):
    try:  # Added Error Checking as strptime doesn't work correctly on LibreElec
        deathday = convert_timestamp(deathday, '%Y-%m-%d', 10) if deathday else datetime.datetime.now()
        birthday = convert_timestamp(birthday, '%Y-%m-%d', 10)
        age = deathday.year - birthday.year
        if birthday.month * 100 + birthday.day > deathday.month * 100 + deathday.day:
            age = age - 1  # In year of death person hadn't had their birthday yet
        return age
    except Exception:
        return
