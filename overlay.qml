import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// Transparent, click-through layer-shell surface on the OVERLAY layer (above fullscreen games).
Window {
    id: win
    visible: false
    color: "transparent"   // default Window colour is opaque white
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus

    LayerShell.Window.scope: "lenslate"
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.exclusionZone: -1
    // put the surface on the QWindow's screen (set from Python) instead of letting KWin pick the active one
    LayerShell.Window.screenConfiguration: LayerShell.Window.ScreenFromQWindow
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone

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
