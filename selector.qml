import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// Frozen-frame region picker on the overlay layer; takes the keyboard exclusively (for Esc).
Window {
    id: win
    visible: false
    color: "black"   // shown until the frozen frame loads
    flags: Qt.FramelessWindowHint

    LayerShell.Window.scope: "lenslate-select"
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.exclusionZone: -1
    // put the surface on the QWindow's screen (set from Python) instead of letting KWin pick the active one
    LayerShell.Window.screenConfiguration: LayerShell.Window.ScreenFromQWindow
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityExclusive

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
