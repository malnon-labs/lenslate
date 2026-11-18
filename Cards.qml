import QtQuick

// The translation cards and the status badge: shared by the Wayland (overlay.qml) and X11 (overlay-x11.qml) windows.
Item {
    id: win
    anchors.fill: parent
    property var cards: []          // [{x,y,w,h,text,bg,fg,px}] in screen-local px
    property bool showCards: true
    property string badge: ""
    property real regionX: 0
    property real regionY: 0
    property string family: "sans-serif"
    // where the badge is drawn (the X11 window is cut to the cards and the badge)
    property rect badgeRect: badgeBox.visible ? Qt.rect(badgeBox.x, badgeBox.y, badgeBox.width, badgeBox.height) : Qt.rect(0, 0, 0, 0)

    Repeater {
        model: win.showCards ? win.cards : []
        delegate: Rectangle {
            x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
            radius: 3
            color: modelData.bg
            Text {
                anchors.fill: parent
                // margins must match layout_card() in lenslate.py, which measured the text with them
                anchors.leftMargin: modelData.mx; anchors.rightMargin: modelData.mx
                anchors.topMargin: modelData.my; anchors.bottomMargin: modelData.my
                text: modelData.text
                textFormat: Text.PlainText   // game text like "<b>" or "&lt;" must show as written, not as markup
                color: modelData.fg
                font.pixelSize: modelData.px
                font.family: win.family
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: modelData.align === "left" ? Text.AlignLeft : Text.AlignHCenter
                // see-through cards: a thin outline in the card colour keeps the text readable over the
                // original text showing through
                style: modelData.outline ? Text.Outline : Text.Normal
                styleColor: modelData.bgs
            }
        }
    }

    Rectangle {
        id: badgeBox
        visible: win.showCards && win.badge !== ""
        x: win.regionX + 6; y: win.regionY + 6
        width: badgeText.implicitWidth + 16; height: badgeText.implicitHeight + 8
        radius: 5; color: "#bb000000"
        Text { id: badgeText; anchors.centerIn: parent; text: win.badge; color: "white"
               font.pixelSize: 13; font.bold: true; font.family: win.family }
    }
}
