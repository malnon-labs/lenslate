#!/bin/bash
# Runs INSIDE the container (see run.sh): Xvfb, a real Cinnamon session, then one lenslate AppImage on X11.
# Results go to /out (screenshots, logs); the summary lines start with "==".
set -u
export DISPLAY=:1 XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=X-Cinnamon APPIMAGE_EXTRACT_AND_RUN=1 NO_CLEANUP=1
export XDG_RUNTIME_DIR=/tmp/rt; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
[ -d /models ] && export LENSLATE_MODELS=/models
mkdir -p ~/.config/lenslate
printf '[translator]\nsources = "ja"\nkind = "mt"\n[ocr]\nreading = "fast"\n[general]\nsetup_done = true\n' > ~/.config/lenslate/config.toml
Xvfb :1 -screen 0 1920x1080x24 >/tmp/xvfb.log 2>&1 &
sleep 2; eval "$(dbus-launch --sh-syntax)"; export DBUS_SESSION_BUS_ADDRESS
cinnamon --replace >/tmp/cinnamon.log 2>&1 &
sleep 12
pgrep -x cinnamon >/dev/null && echo "== cinnamon running" || echo "== CINNAMON DID NOT START"
A=/dist/lenslate.AppImage
# first start (the offline image imports its pack here): two at once, as a hotkey during the first start would
t0=$(date +%s); ($A version > /out/v1.log 2>&1 &); sleep 2; $A version > /out/v2.log 2>&1
while pgrep -f 'lenslate.py version' >/dev/null; do sleep 1; done
echo "== first start: $(( $(date +%s) - t0 )) s, pack imports: $(cat /out/v*.log | grep -ac 'installing its translators'), $(grep -ah '^lenslate 0' /out/v*.log | head -1)"
echo "== capture: $($A capture 2>&1 | grep -v '^qt\.' | head -1)"
# 1. a Cinnamon notification inside a whole-screen area (Cinnamon gives no position: left out by its text)
# (first, before any window: Cinnamon holds notifications back over a window that fills the screen)
(LENSLATE_DEBUG=1 $A region 1300 0 620 400 >/out/lens-notify.log 2>&1 &); sleep 8
for i in $(seq 30); do   # Cinnamon's notification service comes up a while after the session
  gdbus call --session -d org.freedesktop.Notifications -o /org/freedesktop/Notifications \
    -m org.freedesktop.Notifications.GetServerInformation >/dev/null 2>&1 && break; sleep 1; done
gdbus call --session -d org.freedesktop.Notifications -o /org/freedesktop/Notifications \
  -m org.freedesktop.Notifications.GetServerInformation 2>&1 | grep -q Cinnamon || echo "== (no Cinnamon notification service)"
sleep 3
notify-send -a Chat -t 20000 "田中さん" "今夜のパーティーに来ますか？駅の前で待っています"; sleep 1.5
$A now >/dev/null; sleep 12
import -window root /out/notification.png
echo "== notification: $(grep -ah 'notification text left out' /out/lens-notify.log | tail -1 | cut -c1-100)"
$A quit >/dev/null; sleep 2
# 2. cards on a test screen in an X11 window
display -geometry +100+100 /samples/3-dialogue.png & sleep 3
WID=$(xdotool search --name 3-dialogue | head -1); xdotool windowactivate "$WID" 2>/dev/null; sleep 1
(LENSLATE_DEBUG=1 $A region 120 140 1880 900 >/out/lens.log 2>&1 &); sleep 10
xdotool windowactivate "$WID" 2>/dev/null; sleep 1; $A now >/dev/null; sleep 20
import -window root /out/cards.png
echo "== read: $(grep -aE 'ocr .*blocks' /out/lens.log | head -1 | cut -c1-120)"
# 3. hotkeys changed inside lenslate, then pressed in Cinnamon
echo "== hotkeys set: $($A hotkeys set now=Ctrl+Alt+X toggle=Ctrl+Alt+C 2>&1 | grep -v '^qt\.' | tail -1)"
sleep 3
n0=$(grep -ac 'command: now' /out/lens.log); xdotool key --clearmodifiers ctrl+alt+x; sleep 6
echo "== Ctrl+Alt+X ran now: $([ "$(grep -ac 'command: now' /out/lens.log)" -gt "$n0" ] && echo yes || echo NO)"
n0=$(grep -ac 'command: toggle' /out/lens.log); xdotool key --clearmodifiers ctrl+alt+c; sleep 6
echo "== Ctrl+Alt+C ran toggle: $([ "$(grep -ac 'command: toggle' /out/lens.log)" -gt "$n0" ] && echo yes || echo NO)"
xdotool key --clearmodifiers ctrl+alt+c; sleep 2
echo "== hotkeys remove: $($A hotkeys remove 2>&1 | grep -v '^qt\.' | tail -1)"
$A quit >/dev/null
cp -r ~/.cache/lenslate/debug /out/ 2>/dev/null
