# beets-navidrome_sync
Work in progress syncing plugin between beets and Navidrome, works well enough for my own use on Windows, needs testing on *nix.

 **So far, it can do the following:**
- Recursively scan your music folder, grab all the modified (or created (on Windows only apparently??)), and update your Navidrome Created/Updated times to these dates, i.e. set your 'Recently added' order to that of file creation
- will modfiy a local navidrome.db file, or (not fully implemented) connect over SFTP and download a copy to modify as well (works well with Pikapods)
- 2 way syncing - either push, or pull annotations (starred, play counts, ratings) between Navidrome and beets
- Push MusicBrainz metadata into the Navidrome DB
- Will attempt to match tracks by a few means, either by MusicBrainz track ID, path, artist & title, or if all else fails, will try a sort of fuzzy search which matches individual segments of the artist, title, and album to the 'full_text' field in Navidrome's DB, as a result matching success is quite high from initial tests.
- Upload files to your remote SFTP storage directly from the beets prompt as well as automatically upload items following their import to the library.

**Here's some crap documentation because I'm lazy, courtesy of Copilot (edited somewhat for clarification in parts)**

## Installation

1. Install Beets by following the instructions on the [Beets website](https://beets.io/getting-started/).
2. Install the `pysftp` Python packages by running `pip install pysftp`.
3. Clone this repository or download the ZIP file and extract it to a directory of your choice.
4. Copy the `navidrome_sync` directory to your beetsplug directory.
5. Edit your Beets configuration file (`~/.config/beets/config.yaml`) and add the following lines :

   ```yaml
   plugins: navidrome_sync
   
   navidrome_sync:
     dbpath: /path/to/local/navidrome.db
     dbuser: your-db-username # not necessarily your navidrome login username, for syncing stars/ratings to the right user

   # optional:
     pushtarget : local # can be 'local' (default), 'sftp', 'remote', or 'both' (sftp/remote are the same for now)
     navidrome:
       host: your-navidrome-server.com
       username: your-navidrome-username
       password: your-navidrome-password
     sftp:
       auto: no # default 'no', whether to auto-upload on import (probably not recommended to do your whole db at once with this)
       host: your-sftp-server.com
       username: your-sftp-username
       password: your-sftp-password
       directory: /path/to/remote/music_directory
   ```

   Replace the paths and values with your own Navidrome and SFTP server details.

## Usage

Once you have installed and configured the plugin, you can use the following commands to sync your Beets library with Navidrome and upload your music files to the remote SFTP server:

- `beet ndpull`: pull in annotation data (ratings and starred tracks) to the beets db, they'll be appeneded to a 'rating' and 'starred' field respectively. No real options for this yet.

- `beet ndpush`: push annotation data and MusicBrainz data to the Navidrome DB
The `ndpush` command of the NavidromeSyncPlugin has several command line options that you can use to customize its behavior.

Available options for ndpush:

- `-t`, `--time`: Push directory file times to Navidrome database. This option is disabled by default.
- `-c`, `--ctime`: Additional option for `--time`, uses created time (on Windows) rather than modified time.
- `-b`, `--mb`: Push MusicBrainz data from Beets to Navidrome database. This option is enabled by default.
- `-B`, `--no-mb`: Don't push MusicBrainz data from Beets to Navidrome database.
- `-s`, `--starred`: Push starred tracks to Navidrome database. This option is enabled by default.
- `-S`, `--no-starred`: Don't push starred tracks to Navidrome database.
- `-p`, `--playcounts`: Push play counts to Navidrome database. This option is enabled by default.
- `-P`, `--no-playcounts`: Don't push play counts to Navidrome database.
- `-r`, `--ratings`: Push ratings to Navidrome database. This option is enabled by default.
- `-R`, `--no-ratings`: Don't push ratings to Navidrome database.
- `-l`, `--log`: Log missed items to file.
- `-A`, `--no-annotations`: Don't update any annotations (play counts, ratings, starred, MusicBrainz data).

By default, `ndpush` will push MusicBrainz data, starred tracks, play counts, and ratings to the Navidrome database. You can use the `--no-mb`, `--no-starred`, `--no-playcounts`, and `--no-ratings` options to disable these features.

If you want to push directory file times to the Navidrome database, you can use the `--time` option. If you want to use the created time (on Windows) instead of the modified time, you can use the `--ctime` option.

If you want to log missed items to a file, you can use the `--log` option followed by the path to the log file.

For example, to push only play counts and ratings to the Navidrome database and log missed items to a file, you can use the following command:

```
beet ndpush -prBS --log /path/to/logfile.txt
```

If you want to disable all annotations (play counts, ratings, starred, MusicBrainz data), you can use the `--no-annotations` or `-A` option. Note that this option will override all other annotation-related options, for instance in cases where you only want to update the timestamps, e.g.:

```
beet ndpush -tcA
```
