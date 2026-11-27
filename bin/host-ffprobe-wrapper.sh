#!/run/host/usr/bin/bash
exec /run/host/lib64/ld-linux-x86-64.so.2 --library-path /run/host/lib64:/run/host/usr/lib64:/run/host/usr/lib64/fdk-aac:/run/host/usr/lib64/ffmpeg:/run/host/usr/lib64/pulseaudio:/run/host/usr/lib64/samba /run/host/usr/bin/ffprobe "$@"
