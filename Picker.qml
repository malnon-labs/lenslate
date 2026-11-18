import QtQuick

// Frozen-frame area picker: shared by the Wayland (selector.qml) and X11 (selector-x11.qml) windows.
Item {
    id: win
    anchors.fill: parent
    property url frame: ""
    property string family: "sans-serif"
    signal chosen(int x, int y, int w, int h)
    signal cancelled()

    Item {
        id: root
        anchors.fill: parent
        focus: true
        Component.onCompleted: forceActiveFocus()
        Keys.onEscapePressed: { win.cancelled() }

        Image { anchors.fill: parent; source: win.frame; cache: false; smooth: true }
        Rectangle { anchors.fill: parent; color: "#78000000" }

        // the selected area shows the undimmed frame
        Item {
            id: sel
            visible: area.pressed
            property real x0: 0; property real y0: 0; property real x1: 0; property real y1: 0
            x: Math.min(x0, x1); y: Math.min(y0, y1)
            width: Math.abs(x1 - x0); height: Math.abs(y1 - y0)
            clip: true
            Image { x: -sel.x; y: -sel.y; width: root.width; height: root.height; source: win.frame; cache: false }
            Rectangle { anchors.fill: parent; color: "transparent"; border.color: "#50c8ff"; border.width: 2 }
        }

        Text {
            x: 20; y: 16; color: "white"; font.pixelSize: 16; font.family: win.family
            text: "Drag a box around the text to translate  ·  Esc or right-click to cancel"
            style: Text.Outline; styleColor: "black"
        }

        MouseArea {
            id: area
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.CrossCursor
            onPressed: (m) => {
                if (m.button === Qt.RightButton) { win.cancelled(); return }
                sel.x0 = sel.x1 = m.x; sel.y0 = sel.y1 = m.y
            }
            onPositionChanged: (m) => { if (pressed) { sel.x1 = m.x; sel.y1 = m.y } }
            onReleased: (m) => {
                if (m.button !== Qt.LeftButton) return
                sel.x1 = m.x; sel.y1 = m.y
                var w = Math.abs(sel.x1 - sel.x0), h = Math.abs(sel.y1 - sel.y0)
                                if (w > 20 && h > 12) win.chosen(Math.round(Math.min(sel.x0, sel.x1)), Math.round(Math.min(sel.y0, sel.y1)), Math.round(w), Math.round(h))
                else win.cancelled()
            }
        }
    }
}
