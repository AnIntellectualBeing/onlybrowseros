#!/bin/bash
# run.sh NAME PREFS  — offline, with loopback for marionette
cd "$(dirname "$0")"
unshare --net sh -c "ip link set lo up; $(printf '%q ' env "SHOWPROCS=$SHOWPROCS" "NOMIN=$NOMIN" python3 measure.py "$@")"
