import libsonic
import sqlite3
import requests
from beets.plugins import BeetsPlugin
from beets.ui import Subcommand
from beets import dbcore
from beets import config
from beets.util import (mkdirall, normpath, sanitize_path, syspath,
                        bytestring_path, path_as_posix, displayable_path)
import pysftp
import math
import sys
import re
from pprint import pprint

# from stackoverflow somewhere
def progressbar(x, y):
    ''' progressbar for the pysftp
    '''
    bar_len = 60
    filled_len = math.ceil(bar_len * x / float(y))
    percents = math.ceil(100.0 * x / float(y))
    bar = '=' * filled_len + '-' * (bar_len - filled_len)
    filesize = f'{math.ceil(y/1024):,} KB' if y > 1024 else f'{y} byte'
    sys.stdout.write(f'[{bar}] {percents}% {filesize}\r')
    sys.stdout.flush()
# [============================================================] 100% 4,342 KB


class NavidromeSyncPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add({
            'navidrome': {
                'host': '',
                'username': '',
                'password': '',
                'port': 443,
            },
            'sftp': {
                'host': '',
                'username': '',
                'password': '',
                'port': 22,
                'directory' : '/music/',
                'dbpath': '/data/navidrome.db'
            }
        })
        self.config['navidrome']['username'].redact = True
        self.config['navidrome']['password'].redact = True
        self.config['sftp']['username'].redact = True
        self.config['sftp']['password'].redact = True

    def commands(self):
        upload = Subcommand('ndupload', help='Sends new tracks matching a query to remote storage')
        upload.func = self.upload
        pull = Subcommand('ndpull', help='pulls playcounts & starred items from Navidrome')
        pull.func = self.nd_pull
        return [pull, upload]
    
    def sftp_connect(self):
        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None
        host = self.config['sftp']['host'].get()
        user = self.config['sftp']['username'].get()
        passw = self.config['sftp']['password'].get()
        port = self.config['sftp']['port'].get()
        return pysftp.Connection(host, username=user, password=passw, port=port, cnopts=cnopts)
    
    def db_connect(self, db_file):
        conn = None
        cur = None
        try:
            conn = sqlite3.connect(db_file)
            cur = conn.cursor()
        except (RuntimeError, TypeError, NameError) as e:
            print(e)

        return (conn, cur)

    def sftp_upload(self, sftp, local, dest):
        self._log.info('Uploading: {}', local)
        sftp.makedirs(re.sub("/[^/]+$", "",dest))
        sftp.put(localpath=local, remotepath=dest, preserve_mtime=True, callback=lambda x,y: progressbar(x,y))
        print("")
        return

    def format_dest_path(self, path):
        local_path = bytestring_path(config['directory'].as_str())
        dest_path = bytestring_path(self.config['sftp']['directory'].as_str())
        local = path_as_posix(path)
        dest = local.replace(local_path, dest_path)
        return dest.decode("utf-8")

    def upload(self, lib, opts, args):
        log = self._log.info

        items = lib.items(args)
        sftp = self.sftp_connect()
        albumart = set()
        if sftp:
            for i in items:
                if i['artpath'] and i['album'] not in albumart:
                    local = i['artpath']
                    albumart.add(i['album'])
                    self.sftp_upload(sftp, local, self.format_dest_path(local))
                local = i['path']
                self.sftp_upload(sftp, local, self.format_dest_path(local))
            log("Upload complete!")
            sftp.close()
        else:
            log("Connection failed")
        return
    
    def subsonic_api_connect(self):
        host = self.config['navidrome']['host'].get()
        user = self.config['navidrome']['username'].get()
        passw = self.config['navidrome']['password'].get()
        port = self.config['navidrome']['port'].get()
        if host and user and passw and port:
            return libsonic.Connection(host , user, passw, port=port)
        else:
            return False

    def nd_pull(self, lib, opts, args):
        local_path = "./temp.db"
        sftp = self.sftp_connect()
        sftp.get(self.config['sftp']['dbpath'].as_str(), local_path)
        (conn, cur) = self.db_connect(local_path)
        tracks = []
        rows = dict()
        for row in cur.execute('SELECT item_id, item_type, play_count, rating, starred FROM annotation;'):
            rows[row[0]] = row
        for (item_id, artist, albumArtist, album, title, mb_trackid) in cur.execute('SELECT id, artist, album_artist, album, title, mbz_track_id FROM media_file;'):
            playCount = 0
            rating = 0
            loved = 0
            if item_id in rows:
                (item_id, item_type, playCount, rating, loved) = rows[item_id]
            tracks.append({
                "nd_item_id": item_id,
                "artist": artist,
                "albumArtist": albumArtist,
                "album": album,
                "title": title,
                "mb_trackid": mb_trackid,
                "loved": loved,
                "rating": rating,
                "playCount": playCount
            })
        self.sync_navidrome_annotations(lib, tracks, self._log)

    # Shamelessly lifted process_tracks func from lastimport.py, with some modification
    def sync_navidrome_annotations(self, lib, tracks, log):
        total = len(tracks)
        total_found = 0
        total_fails = 0
        log.info('Processing {0} tracks...', total)

        for num in range(0, total):
            song = None
            trackid = None
            # trackid = tracks[num]['mbid'].strip()
            item_id = tracks[num]['nd_item_id'].strip()
            artist = tracks[num]['artist'].strip()
            title = tracks[num]['title'].strip()
            album = ''
            if 'album' in tracks[num]:
                album = tracks[num]['album'].strip()

            log.debug('query: {0} - {1} ({2})', artist, title, album)

            # First try to query by musicbrainz's trackid
            if item_id:
                song = lib.items(
                    dbcore.query.MatchQuery('nd_item_id', item_id)
                ).get()

            if song is None and trackid:
                song = lib.items(
                    dbcore.query.MatchQuery('mb_trackid', trackid)
                ).get()

            # If not, try just artist/title
            if song is None:
                log.debug('no album match, trying by artist/title')
                query = dbcore.AndQuery([
                    dbcore.query.SubstringQuery('artist', artist),
                    dbcore.query.SubstringQuery('title', title)
                ])
                song = lib.items(query).get()

            # Last resort, try just replacing to utf-8 quote
            if song is None:
                title = title.replace("'", '\u2019')
                log.debug('no title match, trying utf-8 single quote')
                query = dbcore.AndQuery([
                    dbcore.query.SubstringQuery('artist', artist),
                    dbcore.query.SubstringQuery('title', title)
                ])
                song = lib.items(query).get()

            if song is not None:
                count = int(song.get('play_count', 0))
                new_count = 0
                if 'playCount' in tracks[num]:
                    # log.info("{} - {}", tracks[num]['title'], tracks[num]['playCount'])
                    new_count = int(tracks[num]['playCount'])
                log.debug('match: {0} - {1} ({2}) '
                        'updating: play_count {3} => {4}',
                        song.artist, song.title, song.album, count, new_count)
                if new_count > count:
                    log.info("{} - {} => {}", tracks[num]['title'], count, new_count)
                    song['play_count'] = new_count
                song['loved'] = "True" if tracks[num]['loved'] else "False"
                song['rating'] = tracks[num]['rating']
                song['nd_item_id'] = tracks[num]['nd_item_id']
                song.store()
                total_found += 1
            else:
                total_fails += 1
                log.info('  - No match: {0} - {1} ({2})',
                        artist, title, album)

        if total_fails > 0:
            log.info('Synced {0}/{1} from Navidrome ({2} unknown)',
                    total_found, total, total_fails)

        return total_found, total_fails
 
"""
beet ls -f "$title: $play_count" "albumartist:low tape" "album:travelogue" play_count-

current:
Shore Of Stars: 19
Night Sounds Of St.Petersburg: 16
Sunshine: 11
Atlantis: 10
Nature's Interface: 7
Isolated Island: 4

after:

"""


# from pkgutil import extend_path
# __path__ = extend_path(__path__, __name__)