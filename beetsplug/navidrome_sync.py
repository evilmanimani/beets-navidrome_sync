'''
This is my first beets plugin, and first time doing anything with Python, coming from Javscript and Autohotkey
Please be gentle :)

TODO:
- Confirmation prompt for imports
- Maybe support updating a remote db via sqlite3 commands sent to the remote server, in cases wher that's supported
- Sync starred back to LastFM (ListenBrainz?)
'''
import sqlite3, os, sys, re, datetime 
from functools import partial
import pysftp
from beets.plugins import BeetsPlugin
from beets.ui import (Subcommand)
from beets import dbcore, config
from sftpuploader import SftpUploader
from beets.util import (bytestring_path, path_as_posix)



class NavidromeSyncPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add({
            'dbpath': '',
            'dbuser': '',
            'temp_path': "./temp.db",
            'pushtarget': 'local', # accepts: sftp, remote, local, or both
            "push-annotations": True,
            # 'ratingkey': 'rating',
            # 'favoritekey': 'starred',
            'navidrome': {
                'host': '',
                'username': '',
                'password': '',
                'port': 443,
            },
            'sftp': {
                'auto': False,
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
        sftp_config = {
            'host': self.config['sftp']['host'].get(),
            'username': self.config['sftp']['username'].get(),
            'password': self.config['sftp']['password'].get(),
            'port': self.config['sftp']['port'].get(),
            'directory': self.config['sftp']['directory'].get(),
            'local_directory': config['directory'].as_str(),
        }
        check = ['host', 'username', 'port', 'password', 'directory']
        self.imported_items = []
        if self.config['sftp']['auto'] and all(k in sftp_config and sftp_config[k] for k in check):
            self.uploader = SftpUploader(sftp_config, self._log)
            if self.config['sftp']['auto'].get():
                self.register_listener('import_task_files', self.add_imported_items)
                self.register_listener('import', self.sftp_auto)

    def add_imported_items(self, task):
        if task.is_album:
            for item in task.items:
                self.imported_items.append(item)
        else:
            self.imported_items.append(task.item)

    def sftp_auto(self, *rest):
        items = self.imported_items
        if len(items) == 0: return
        self._log.info('Auto upload enabled, uploading to remote storage...')
        self.uploader.upload(items, None, None)
        self._log.info('Upload complete')


    def commands(self):
        nddb = Subcommand('nddb', help="Update remote DB")
        nddb.func = self.update_remote_db
        upload = Subcommand('ndupload', help='Sends new tracks matching a query to remote storage')
        upload.func = self.upload
        pull = Subcommand('ndpull', help='Pulls playcounts & starred items from Navidrome')
        pull.func = partial(self.nd_sync, 'pull')
        push = Subcommand('ndpush', help='Push file times to Navidrome')
        push.parser.add_option( '-t', '--time',          action='store_true',    default=False,      help="push directory file times to Navidrome db.")
        push.parser.add_option( '-c', '--ctime',         action='store_true',    default=False,      help="additional option for --time, uses created time (on Windows) rather than modified time.")
        push.parser.add_option( '-b', '--mb',            action='store_true',    default=True,       help="push MusicBrainz data from beets to Navidrome db.")
        push.parser.add_option( '-B', '--no-mb',         action='store_false',   dest='mb',          help="Don't push MusicBrainz data from beets to Navidrome db.")
        push.parser.add_option( '-s', '--starred',       action='store_true',    default=True,       help="Push starred tracks")
        push.parser.add_option( '-S', '--no-starred',    action='store_false',   dest='starred',     help="Don't push starred tracks")
        push.parser.add_option( '-p', '--playcounts',    action='store_true',    default=True,       help="Push play counts")
        push.parser.add_option( '-P', '--no-playcounts', action='store_false',   dest='playcounts',  help="Don't push play counts")
        push.parser.add_option( '-r', '--ratings',       action='store_true',    default=True,       help="Push ratings")
        push.parser.add_option( '-R', '--no-ratings',    action='store_false',   dest='ratings',     help="Don't push ratings")
        push.parser.add_option( '-l', '--log',                                   dest='log_path',    help="Log missed items to file")
        push.parser.add_option( '-A', '--no-annotations',action='store_true',    default=False,      help="Don't update any annotations (play counts, ratings, starred, MusicBrainz data)")
        push.func = partial(self.nd_sync, 'push')
        return [push, pull, upload, nddb]
    
    def nd_sync(self, lib, opts, args, mode):
        
        target = self.config['pushtarget'].as_str()
        remoteEnabled = re.search('^(sftp|remote|both)$', target)
        localEnabled = re.search('^(local|both)$', target)
        for enabled, func in ((remoteEnabled, self.get_remote_db), (localEnabled, self.get_local_db)):
            if enabled: 
               (conn, cur) = func()
            if not conn:
                self._log.info(f'Unable to connect to configured DB path for function "{mode}". Exiting...')
                continue
            if mode == 'push':
                if opts.time:
                    self.nd_push_file_mtime(conn, cur, opts.ctime, args)
                if self.config['push-annotations']:
                    if opts.no_annotations or (not opts.mb and not opts.starred and not opts.playcounts and not opts.ratings):
                        self._log.info("At least one of either --mb, --starred, --playcounts, or --ratings must be enabled to process!")
                        return
                    else:
                        self.nd_push_annotations(conn, cur, lib, opts, args)
            elif mode == 'pull':
                self.nd_pull(lib, conn, cur)
        return

    def get_local_db(self, *rest):
        dbpath = self.config['dbpath'].as_str()
        if not dbpath:
            self._log.info('Configure a valid local dbpath to continue. Exiting...')
            return
        return self.db_connect(dbpath)
     
    def get_remote_db(self, *rest):
        local_path = self.config['temp_path'].as_str()
        with self.sftp_connect() as sftp:
            sftp.get(self.config['sftp']['dbpath'].as_str(), local_path)
            return self.db_connect(local_path)

    def nd_push_annotations(self, conn, cur, lib, opts, args):
        user_name = self.config['dbuser'].as_str()
        if not user_name:
            self._log.info('Set dbuser in config to a valid Navidrome username for new or modified annotations')
            return
        cur.execute('SELECT id FROM user WHERE user_name = ?', (user_name,))
        user_id = cur.fetchone()[0]
        print(user_id)
        if not user_id:
            self._log.info('Configured dbuser username does not return a valid user_id. Exiting...')
            return
        self._log.info('Pushing ' +
                    ('starred, ' if opts.starred else '') +
                    ('play-counts, ' if opts.playcounts else '') +
                    ('ratings, ' if opts.ratings else '') +
                    ('musicbrainz data, ' if opts.mb else '') +
                    'to Navidrome DB'                         
        )
        all_items = []
        for i in lib.items(args):
            all_items.append((
                i['path'].decode('utf-8'),
                i['artist'],
                i['albumartist'],
                i['title'],
                i['album'],
                i['mb_trackid'],
                i['mb_albumid'],
                i['mb_artistid'],
                i['mb_albumartistid'],
                i['albumtype'],
                i['mb_releasetrackid'],
                i['play_count'] if 'play_count' in i else 0,
                i['rating'] if 'rating' in i else 0,
                i['starred'] if 'starred' in i else 'False',
                i['mtime'] if 'mtime' in i else 'NULL'
            ))
            # all_items.extend(items)
        total = len(all_items)
        if total == 0:
            self._log.info('Supplied query returned zero results. Exiting...')
            return
        matched = 0
        updated = 0
        missed = 0
        missed_log = []
        ids = []
        paths = []
        local_path = config['directory'].as_str()
        for (
                path, 
                artist, 
                albumartist,
                title, 
                album,
                mb_trackid, 
                mb_albumid, 
                mb_artistid, 
                mb_albumartistid, 
                albumtype, 
                mb_releasetrackid, 
                play_count, 
                rating, 
                starred, 
                mtime
            ) in all_items:
            path = path.replace('\\', '/').replace(local_path, '')
            cur.execute(''' SELECT id, updated_at, mbz_track_id
                            FROM media_file 
                            WHERE (mbz_track_id = ?)
                            OR (path LIKE ?)
                            OR (artist = ? AND title = ?);''',
                        (mb_trackid, artist, title, f'%{path}%'))
            needle = [artist, albumartist, album, title]
            (id, updated_at, mbz_track_id) = cur.fetchone() or self.fuzzy_search(needle, cur)
            if not id:
                missed += 1
                missed_log.append(f'missed:{artist},{title},{path},{mb_trackid}')
            else:
                matched += 1
                if path not in paths and id not in ids and (opts.starred or opts.playcounts or opts.ratings):
                    updated += 1
                    paths.append(path)
                    ids.append(id)
                    updated_at = re.sub("T|Z", " ", updated_at).strip()
                    mtime = re.sub("T|Z", " ", convert_time(mtime)).strip() if starred and opts.starred else "NULL"
                    starred = 1 if starred == 'True' and opts.starred else 0
                    rating = rating if opts.ratings else 0
                    play_count = play_count if opts.playcounts else 0
                    cur.execute('SELECT ann_id FROM annotation WHERE item_id = ?', (id,))
                    rows = cur.fetchall()
                    if len(rows) == 0:
                        cur.execute(''' INSERT into annotation (ann_id, user_id, item_id, item_type, play_count, play_date, rating, starred, starred_at)
                                        VALUES  (lower(hex(randomblob(4))) || '-' || 
                                                lower(hex(randomblob(2))) || '-4' || 
                                                substr(lower(hex(randomblob(2))),2) || '-' || 
                                                substr('89ab',abs(random()) % 4 + 1, 1) || 
                                                substr(lower(hex(randomblob(2))),2) || '-' || 
                                                lower(hex(randomblob(6))),
                                                ?, ?, "media_file", ?, NULL, ?, ?, ?);''',
                                            (user_id, id, play_count, rating, starred, mtime))
                    else:
                        cur.execute(''' UPDATE annotation 
                                        SET starred = ?, 
                                            starred_at = ?, 
                                            play_count = ?,
                                            rating = ? 
                                        WHERE item_id = ?
                                        AND user_id = ?
                                        AND item_type = "media_file";'''
                                    , (starred, mtime, play_count, rating, id, user_id))
                    if opts.mb: 
                        cur.execute(''' UPDATE media_file
                                        SET mbz_track_id = ?,
                                            mbz_album_id = ?,
                                            mbz_artist_id = ?,
                                            mbz_album_artist_id = ?,
                                            mbz_album_type = ?,
                                            mbz_release_track_id = ?
                                        WHERE id = ?''', 
                                        (mb_trackid, mb_albumid, mb_artistid, mb_albumartistid, albumtype, mb_releasetrackid, id))
            update_progress(total=total, matched=matched, updated=updated, missed=missed)
        print('')
        if opts.log_path is not None:
            f = open(opts.log_path, "w", encoding='utf-8')
            f.write('\r\n'.join(missed_log))
            f.close()
        self._log.info('Navidrome push complete')
        conn.commit()
        conn.close()

    def nd_push_file_mtime(self, conn, cur, get_ctime, args):
        self._log.info('Pushing ' + ('ctime' if get_ctime else 'mtime') + ' to date-added field for media files in Navidrome DB')
        # (conn, cur) = self.get_remote_db()
        (conn, cur) = self.db_connect(self.config['dbpath'].as_str())
        items = self.collect_file_info(args) #filter list passed as tuple
        # pprint(items)
        self._log.info('Scan complete, matching files to DB entries...')
        time_index = 2 if get_ctime else 1
        albumIDs = []
        total = len(items)
        matched = 0
        missed = 0
        for item in items:
            path = item[0]
            utc = item[time_index]
            utc_m = utc.replace('Z', '.000000000Z')
            cur.execute(
                ''' UPDATE media_file 
                    SET updated_at = :utc, created_at = :utc_m
                    WHERE path LIKE :path;''',
                {"utc": utc, "utc_m": utc_m, "path": f'%{path}%'}
            )
            cur.execute(f'SELECT album_id FROM media_file WHERE path LIKE "%{path}%";')
            row = cur.fetchone()
            if row:
                matched += 1
                albumID = row[0]
                if albumID not in albumIDs:
                    albumIDs.append(albumID)
                    cur.execute(
                            ''' UPDATE album
                                SET updated_at = :utc, created_at = :utc_m
                                WHERE id = :id;''',
                                { "utc": utc, "utc_m": utc_m, "id": albumID }
                            )
            else: missed += 1 
            update_progress(total=total, matched=matched, missed=missed)
        conn.commit()
        conn.close()
        print('')
    
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

    def format_dest_path(self, path):
        '''
        Formats the destination path for SFTP upload, i dunno what I'm doing here, lol
        Untested on Linux, but should work... maybe?'''
        local_path = bytestring_path(config['directory'].as_str())
        dest_path = bytestring_path(self.config['sftp']['directory'].as_str())
        local = path_as_posix(path)
        dest = local.replace(local_path, dest_path)
        return dest.decode("utf-8")
    
    def upload(self, lib, opts, args):
        self.uploader.upload(lib, opts, args)
        self._log.info('Upload complete')
    
    # def nd_api(self, lib, opts, args):
    #     conn = self.subsonic_api_connect()
    #     return

    # Unused at the moment
    # def subsonic_api_connect(self):
    #     host = self.config['navidrome']['host'].get()
    #     user = self.config['navidrome']['username'].get()
    #     passw = self.config['navidrome']['password'].get()
    #     port = self.config['navidrome']['port'].get()
    #     if host and user and passw and port:
    #         return libsonic.Connection(host , user, passw, port=port)
    #     else:
    #         return False

    def nd_pull(self, lib, conn, cur):
        tracks = []
        rows = dict()
        for row in cur.execute('SELECT item_id, item_type, play_count, rating, starred FROM annotation;'):
            rows[row[0]] = row
        for (item_id, artist, albumArtist, album, title, mb_trackid) in cur.execute('SELECT id, artist, album_artist, album, title, mbz_track_id FROM media_file;'):
            playCount = 0
            rating = 0
            starred = 0
            if item_id in rows:
                (item_id, item_type, playCount, rating, starred) = rows[item_id]
            tracks.append({
                "nd_item_id": item_id,
                "artist": artist,
                "albumArtist": albumArtist,
                "album": album,
                "title": title,
                "mb_trackid": mb_trackid,
                "starred": starred,
                "rating": rating,
                "playCount": playCount
            })
        self.process_navidrome_annotations(lib, tracks, self._log)

    # Shamelessly lifted process_tracks func from lastimport.py, with some modification
    def process_navidrome_annotations(self, lib, tracks, log):
        total = len(tracks)
        total_found = 0
        total_fails = 0
        log.info('Processing {0} tracks...', total)

        for num in range(0, total):
            song = None
            trackid = None
            item_id = tracks[num]['nd_item_id'].strip()
            artist = tracks[num]['artist'].strip()
            title = tracks[num]['title'].strip()
            album = ''
            if 'album' in tracks[num]:
                album = tracks[num]['album'].strip()

            log.debug('query: {0} - {1} ({2})', artist, title, album)

            # Try with previously saved Navidrome item id
            if item_id:
                song = lib.items(
                    dbcore.query.MatchQuery('nd_item_id', item_id)
                ).get()

            # Then try to query by musicbrainz's trackid
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
                    new_count = int(tracks[num]['playCount'])
                log.debug('match: {0} - {1} ({2}) '
                        'updating: play_count {3} => {4}',
                        song.artist, song.title, song.album, count, new_count)
                if new_count > count:
                    log.info("{} - {} => {}", tracks[num]['title'], count, new_count)
                    song['play_count'] = new_count
                song['starred'] = "True" if tracks[num]['starred'] else "False"
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
    

    def update_remote_db(self, *rest):
        local_path = self.config['temp_path'].as_str()
        with self.sftp_connect() as sftp:
            self.sftp_upload(sftp, local_path, (self.config['sftp']['dbpath'].as_str()))
            self._log.info('Remote DB updated, complete a full refresh in Navidrome for changes to take effect')
        return

    def fuzzy_search(self, needle, cur):
        '''
        compares each string segment of the needle to the 'full_text' db field
        if all segments are found: returns tuple of (id, updated_at, mbz_track_id)
        returns (None, None, None) if not
        '''
        haystack_re = re.compile('[^a-zA-Z0-9A-zÀ-ÖØ-öø-įĴ-őŔ-žǍ-ǰǴ-ǵǸ-țȞ-ȟȤ-ȳɃɆ-ɏḀ-ẞƀ-ƓƗ-ƚƝ-ơƤ-ƥƫ-ưƲ-ƶẠ-ỿ\s]', re.MULTILINE) # should catch all all diacritics?? i dunno
        haystack = []
        for (t, i, u, m) in cur.execute('SELECT full_text, id, updated_at, mbz_track_id FROM media_file;'):
            haystack.append((t, i, u, m)) 
        if needle[0] == needle[1]: # artist & album artist are passed as first two items of list
            needle.pop()
        needle = re.sub(haystack_re, '', ' '.join(needle).lower().replace('the', ''))
        l = needle.split()
        for (string, *rest) in haystack:
            if all(s in string for s in l):
                return(rest)                
        return (None, None, None)

    def collect_file_info(self, filter_list=()):
        directory = config['directory'].as_str()
        file_info_list = []
        re_image = re.compile(r'\.(png|jpe?g|gif)$', re.I)
        matched = 0
        for root, dirs, files in os.walk(directory):
            for file in files:
                match = False
                file_path = os.path.join(root, file)
                # print (file_path)
                # Get the file creation time (metadata may not be available on all platforms)
                try: created_time = convert_time(os.path.getctime(file_path))
                except OSError: created_time = None
                try: modified_time = convert_time(os.path.getmtime(file_path))
                except OSError: modified_time = None                
                if filter_list:
                    match = len(list(filter(lambda e: e.casefold() in file_path.casefold(), filter_list))) > 0 and not re.search(re_image, file)
                else: match = True
                if match: 
                    matched += 1
                    file_info_list.append((file, modified_time, created_time))
                sys.stdout.write(f'  --- Scanning music directory: found {str(matched).ljust(6)} ---\r')
                sys.stdout.flush()
        print('')
        return file_info_list                    

def convert_time(t): return datetime.datetime.fromtimestamp(int(t), tz=datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

def update_progress(**kwargs): # =total, matched, updated, missed):
    # total, matched, updated, missed = [kwargs.get(k) for k in (list(kwargs))]
    total, matched, updated, missed = [kwargs.get(k) for k in ('total', 'matched', 'updated', 'missed')]
    pad_int = lambda s: str(s).rjust(len(str(total)))
    per = ((matched + (missed or 0)) / total) * 100
    updated_str = f'{pad_int(updated)} updated, ' if updated is not None else ''
    sys.stdout.write(f'  --- {pad_int(matched)} of {pad_int(total)} matched ({updated_str}{pad_int(missed)} missed) - {str(int(per)).rjust(3)}% complete ---\r')
    sys.stdout.flush()

