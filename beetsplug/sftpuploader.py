import paramiko
import os
import threading
from tqdm import tqdm
from beets.util import bytestring_path, path_as_posix
from beets.ui import decargs
from multiprocessing import Value

class SftpUploader:
    def __init__(self, sftp_config, log):
        self.sftp_config = sftp_config
        self.lock = threading.Lock()
        self.created = False
        self._log = log

    def upload(self, lib, opts, args):
        if not args:
           items = lib
        else:
            items = lib.items(decargs(args))
        # albumart = set()
        artpath = None
        to_upload = []
        for i in items:
            if not artpath and i['artpath']:
                artpath = i['artpath']
                size = os.path.getsize(artpath)  # Calculate size of cover art
                to_upload.append((artpath))
            local = i['path']
            to_upload.append((local))
        
        # if items[0]['artpath']:
        #     local = items[0]['artpath']
        #     size = os.path.getsize(local)  # Calculate size of cover art
        #     to_upload.append((local, size))

        for local, size in to_upload: 
            print(f"Uploading {local.decode('utf-8')} to {str(self.format_dest_path(local))}")
            self.upload_file(local, size)


    def upload_file(self, local, dest = None):
        size = os.path.getsize(local)  # Calculate size of file
        threads_count = 6 
        part_size = int(size / threads_count)
        self.lock = threading.Lock()
        self.created = False
        offset = 0
        threads = []
        progress = Value('i', 0)  # Create shared progress object
        items = []

        for num in range(threads_count):
            if num == threads_count - 1:
                part_size = size - offset
            args = [num, offset, part_size, local, dest or self.format_dest_path(local), progress]
            items.append((part_size, args))
            offset += part_size

        total_size = sum([item[0] for item in items])

        self.mkdir_p(self.sftp_connect(), items[0][1][-2], is_dir=False)

        with tqdm(total=total_size, smoothing=0.8, unit='B', unit_scale=True, desc='Progress') as overall_pbar:
            for item in items:
                thread = threading.Thread(target=self.upload_part, args=item[1])
                threads.append(thread)
                thread.start()
            
            while any(t.is_alive() for t in threads):  # Update progress while threads are running
                    overall_pbar.update(progress.value - overall_pbar.n)

            overall_pbar.update(total_size - overall_pbar.n)  # Update progress to 100%
            overall_pbar.close()

            for num in range(len(threads)):
                threads[num].join()

    def upload_part(self, num, offset, part_size, local_path, remote_path, progress):
        try:
            sftp = self.sftp_connect()

            with open(local_path, "rb") as fl:
                fl.seek(offset)
                with self.lock:
                    m = "r+" if self.created else "w"
                    self.created = True
                    fr = sftp.open(remote_path, m)
                try:
                    fr.seek(offset)
                    fr.set_pipelined(True)
                    size = 0
                    while size < part_size:
                        s = 32768
                        if size + s > part_size:
                            s = part_size - size
                        data = fl.read(s)
                        fr.write(data)
                        size += len(data)
                        progress.value += len(data)  # Update shared progress
                        if len(data) == 0:
                            break             
                finally:
                    fr.close()

            local_stat = os.stat(local_path)
            sftp.utime(remote_path, (local_stat.st_atime, local_stat.st_mtime))
        except (paramiko.ssh_exception.SSHException) as x:
            print(f"Thread {num} failed: {x}")
            raise x

    def sftp_connect(self):
        try:
            sftp_server = self.sftp_config['host']
            port = self.sftp_config['port']
            username = self.sftp_config['username']
            password = self.sftp_config['password']
    
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(sftp_server, port=port, username=username, password=password)
            transport = ssh.get_transport()
            transport.window_size = 2147483647
            sftp = ssh.open_sftp()
            return sftp

        except (paramiko.ssh_exception.SSHException) as x:
            raise x

    def format_dest_path(self, path):
        local_path = bytestring_path(self.sftp_config['local_directory'])
        dest_path = bytestring_path(self.sftp_config['directory'])
        local = path_as_posix(path)
        dest = local.replace(local_path, dest_path)
        return dest.decode("utf-8")
    
    # from https://stackoverflow.com/a/20422692
    def mkdir_p(self, sftp, remote, is_dir=False):
        """
        emulates mkdir_p if required. 
        sftp - is a valid sftp object
        remote - remote path to create. 
        """
        dirs_ = []
        if is_dir:
            dir_ = remote
        else:
            dir_, basename = os.path.split(remote)
        while len(dir_) > 1:
            dirs_.append(dir_)
            dir_, _  = os.path.split(dir_)

        if len(dir_) == 1 and not dir_.startswith("/"): 
            dirs_.append(dir_) # For a remote path like y/x.txt 

        while len(dirs_):
            dir_ = dirs_.pop()
            try:
                sftp.stat(dir_)
            except:
                sftp.mkdir(dir_)    
