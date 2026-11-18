import QtQuick
import QtQuick.Window

// X11: the frozen-frame area picker as a full-monitor window above everything; lenslate grabs the keyboard for Esc.
Window {
    id: win
    visible: false
    color: "black"   // shown until the frozen frame loads
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint

    property url frame: ""
    property string family: "sans-serif"
    signal chosen(int x, int y, int w, int h)
    signal cancelled()

    Picker {
        frame: win.frame; family: win.family
        onChosen: (x, y, w, h) => { win.visible = false; win.chosen(x, y, w, h) }
        onCancelled: { win.visible = false; win.cancelled() }
    }
}
