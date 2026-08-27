#!/usr/bin/env sh
# Installed to ~/.xinitrc by setup.sh. Started via `startx` from
# ~/.bash_profile on autologin at tty1. This brings up just enough X to
# host a kiosk browser - no desktop environment.
#
# Chromium itself is NOT launched here - it's managed by the
# kiosk-chromium.service systemd user unit (see setup/kiosk-chromium.service)
# so that a crash/OOM gets it restarted automatically (Restart=always)
# instead of taking the whole X session down with it.

# Never blank the screen or suspend the display - this is a wall-mounted
# always-on dashboard.
xset s off
xset s noblank
xset -dpms

# Hide the mouse cursor when idle (there's a touchscreen, no mouse).
unclutter -idle 0.5 -root &

# Minimal window manager - just enough to give Chromium a fullscreen,
# undecorated window. openbox-session runs in the foreground and keeps
# this script (and therefore the X session) alive.
exec openbox-session
