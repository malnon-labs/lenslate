import QtQuick
import QtQuick.Window

// X11: a see-through window the window manager leaves alone (no frame, no focus, clicks pass through), kept above
// the game by lenslate (raised again while shown). lenslate cuts it to the cards (window mask), so it also works
// without a compositing manager.
Window {
    id: win
    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput
           | Qt.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint

    property var cards: []          // [{x,y,w,h,text,bg,fg,px}] in screen-local px
    property bool showCards: true
    property string badge: ""
    property real regionX: 0
    property real regionY: 0
    property string family: "sans-serif"
    property alias badgeRect: view.badgeRect

    Cards {
        id: view
        cards: win.cards; showCards: win.showCards; badge: win.badge
        regionX: win.regionX; regionY: win.regionY; family: win.family
    }
}
