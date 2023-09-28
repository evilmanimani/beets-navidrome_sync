import subprocess
import pexpect

host= 'eviltunes.pikapod.net'
username= 'p21685'
password= '16PM49dDAAqokYREYUyrYclv'
directory= '/music'
# Define SFTP connection parameters
# host = 'your_remote_host'
port = 22  # Default SSH port
# username = 'your_username'
# password = 'your_password'
remote_path = '/data/'
local_file = './test.txt'

# Construct the SFTP command
sftp_command = f'sftp -oPort={port} {username}@{host}:{remote_path}'

# Use subprocess to run the SFTP command
try:
    sftp_process = subprocess.Popen(sftp_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)

    # sftp_process.stdin.write(f'yes\n')
    # Send password to SFTP session
    sftp_process.stdin.write(f'{password}\n')

    # Send the 'put' command to upload the local file
    sftp_process.stdin.write(f'put {local_file}\n')

    # Exit the SFTP session
    sftp_process.stdin.write('exit\n')

    sftp_process.communicate()  # Wait for the SFTP process to complete
    sftp_process.stdin.close()
    sftp_process.stdout.close()
    sftp_process.stderr.close()

    print(f'Successfully sent {local_file} to {host}:{remote_path}')
except subprocess.CalledProcessError as e:
    print(f'Error: {e}')
