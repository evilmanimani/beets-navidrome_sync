# beets-navidrome_sync
Work in progress syncing plugin between beets and Navidrome 

Presently no documentation or testing, probably broken atm, like version 0.0000001 pre pre pre pre alpha; check back in a week :)

 **So far, it can do the following:**
- Recursively scan your music folder, grab all the modified (or created (on Windows only apparently??)), and update your Navidrome Created/Updated times to these dates, i.e. set your 'Recently added' order to that of file creation
- will modfiy a local navidrome.db file, or (not fully implemented) connect over SFTP and download a copy to modify as well (works well with Pikapods)
- 2 way syncing - either push, or pull annotations (starred, play counts, ratings) between Navidrome and beets
- Push MusicBrainz metadata into the Navidrome DB
- Will attempt to match tracks by a few means, either by MusicBrainz track ID, path, artist & title, or if all else fails, will try a sort of fuzzy search which matches individual segments of the artist, title, and album to the 'full_text' field in Navidrome's DB, as a result matching success is quite high from initial tests.
- Upload files to your remote SFTP storage directly from the beets prompt (kinda slow compared to WinSCP though, suggestions would be neat)


**TODO: some documentation goes heare**
