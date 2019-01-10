#!/bin/sh
curl -X POST -d "TransmissionBT finish download torrent "${TR_TORRENT_NAME}"" http://localhost:8094/download/done