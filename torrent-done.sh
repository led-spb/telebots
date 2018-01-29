#!/bin/sh
CUR_DIR=$(dirname $0)
echo "Download \"${TR_TORRENT_NAME}\" finished" | $CUR_DIR/torrentbot.py -c $CUR_DIR/torrentbot.conf notify