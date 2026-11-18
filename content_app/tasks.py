import subprocess

def convert_480p(source):
    '''
    Converts the given video file to 480p resolution.
    '''
    target = source.rsplit('.', 1)[0] + '_480p.mp4'
    command = ['ffmpeg', '-i', source, '-s', 'hd480', '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', '-strict', '-2', target]
    subprocess.run(command, check=True)