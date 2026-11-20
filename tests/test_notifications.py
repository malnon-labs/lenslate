"""Desktop notifications inside the area: what dbus-monitor prints is understood, notification lines are recognised
(and the game's own text is not), and the spots the desktop names are covered in the picture."""
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401 - sets up the scratch folders first
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

import notifications as notif
import lenslate as ls  # noqa: E402

# recorded from dbus-monitor on Plasma 6 (notify-send -a probeapp 'Sum "q" mary' $'body line1\nline2'), plus a
# signal before it and a critical one after it
MONITOR = '''signal time=1795203186.506706 sender=org.freedesktop.DBus -> destination=:1.945 serial=4294967295 path=/org/freedesktop/DBus; interface=org.freedesktop.DBus; member=NameAcquired
   string ":1.945"
method call time=1795203187.510957 sender=:1.946 -> destination=:1.53 serial=9 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "probeapp"
   uint32 0
   string ""
   string "Sum "q" mary"
   string "body line1
line2"
   array [
   ]
   array [
      dict entry(
         string "urgency"
         variant             byte 1
      )
      dict entry(
         string "sender-pid"
         variant             int64 95117
      )
   ]
   int32 3000
method call time=1795203190.1 sender=:1.950 -> destination=:1.53 serial=4 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Discord"
   uint32 0
   string "discord"
   string "Ana"
   string "<b>are you coming tonight?</b>"
   array [
      string "default"
      string "Open"
   ]
   array [
      dict entry(
         string "urgency"
         variant             byte 2
      )
   ]
   int32 -1
'''


class Parser(unittest.TestCase):
    def test_dbus_monitor_output(self):
        got = list(notif.parse_monitor(MONITOR.splitlines(True)))
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], {"app": "probeapp", "summary": 'Sum "q" mary', "body": "body line1\nline2",
                                  "expire": 3000, "urgency": 1})
        self.assertEqual((got[1]["app"], got[1]["summary"], got[1]["expire"], got[1]["urgency"]),
                         ("Discord", "Ana", -1, 2))

    def test_garbage_is_ignored(self):
        self.assertEqual(list(notif.parse_monitor(["", "nonsense\n", "   string \"x\"\n"])), [])


class Matching(unittest.TestCase):
    def setUp(self):
        self.w = notif.Watcher()
        self.w.add({"app": "Discord", "summary": "Ana", "body": "<b>are you coming tonight?</b>", "expire": -1,
                    "urgency": 1}, now=100.0)

    def test_lines_of_the_notification(self):
        for line in ("are you coming tonight?", "Are you comlng tonight", "Discord", "coming tonight"):
            self.assertTrue(self.w.matches(line, now=101.0), line)

    def test_the_games_own_text_stays(self):
        for line in ("New Game", "Options", "OK", "Ana", "Continue", "tonight we ride to the castle gates"):
            self.assertFalse(self.w.matches(line, now=101.0), line)

    def test_it_expires(self):
        self.assertTrue(self.w.active(now=100.0 + notif.SHOWN_S))
        self.assertFalse(self.w.active(now=100.0 + notif.SHOWN_S + notif.GRACE_S + 0.1))
        self.assertFalse(self.w.matches("are you coming tonight?", now=200.0))

    def test_critical_stays_longer_and_cjk(self):
        self.w.add({"app": "微信", "summary": "张三", "body": "今晚来吗", "expire": -1, "urgency": 2}, now=100.0)
        self.assertTrue(self.w.matches("今晚来吗", now=100.0 + notif.STICKY_S))
        self.assertFalse(self.w.matches("设置", now=101.0))


class Covering(unittest.TestCase):
    def setUp(self):
        ls._CLEAN.clear()

    def _img(self, color):
        img = QImage(200, 100, QImage.Format_RGB32)
        img.fill(QColor(color))
        return img

    def test_spot_is_taken_from_the_previous_picture(self):
        area = QRect(1000, 500, 100, 50)        # logical; the picture is 2x (200 % scale)
        with mock.patch.object(ls, "notification_rects", return_value=[]):
            ls.cover_notifications(self._img("blue"), area)
        with mock.patch.object(ls, "notification_rects", return_value=[QRect(1050, 480, 200, 40)]):
            out = ls.cover_notifications(self._img("red"), area)
        self.assertEqual(out.pixelColor(150, 10).name(), "#0000ff")      # under the notification: the old picture
        self.assertEqual(out.pixelColor(50, 10).name(), "#ff0000")       # beside it: the new one
        self.assertEqual(out.pixelColor(150, 70).name(), "#ff0000")      # below it

    def test_flat_colour_without_a_previous_picture(self):
        area = QRect(0, 0, 100, 50)
        img = self._img("green")
        img.setPixelColor(150, 30, QColor("white"))
        with mock.patch.object(ls, "notification_rects", return_value=[QRect(60, 0, 40, 50)]):
            out = ls.cover_notifications(img, area)
        self.assertEqual(out.pixelColor(150, 30).name(), "#008000")

    def test_nothing_to_cover_is_the_same_picture(self):
        img = self._img("blue")
        with mock.patch.object(ls, "notification_rects", return_value=[QRect(5000, 5000, 10, 10)]):
            self.assertIs(ls.cover_notifications(img, QRect(0, 0, 100, 50)), img)

    def test_blank_boxes(self):
        out = ls.blank_boxes(self._img("red"), [[10, 10, 30, 20]])
        self.assertEqual(out.pixelColor(20, 15).name(), "#000000")
        self.assertEqual(out.pixelColor(50, 50).name(), "#ff0000")


if __name__ == "__main__":
    unittest.main()
