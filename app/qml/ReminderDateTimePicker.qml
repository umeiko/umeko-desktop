import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id:root
    objectName:"reminderDateTimePicker"
    property string mode:"date"
    property int firstYear:2021
    property int lastYear:2046
    property bool initializing:false
    readonly property int year:firstYear+years.currentIndex
    readonly property int month:months.currentIndex+1
    readonly property int day:days.currentIndex+1
    readonly property int daysInMonth:new Date(year,month,0).getDate()
    signal chosen(string dateText,string timeText)
    width:Math.min(parent.width-24,460*Theme.fontScale)
    height:334*Theme.fontScale
    x:(parent.width-width)/2;y:Math.max(12,parent.height-height-12)
    modal:true;focus:true;padding:20*Theme.fontScale
    closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background:Item {
        Rectangle {x:-2;y:3;width:parent.width+4;height:parent.height;radius:12;color:"#14000000"}
        Rectangle {
            anchors.fill:parent;radius:10;border.color:Theme.dark?Qt.lighter(Theme.line,1.2):Qt.darker(Theme.line,1.08)
            gradient:Gradient {
                GradientStop {position:0;color:Theme.surface}
                GradientStop {position:1;color:Theme.dark?Qt.lighter(Theme.bg,1.05):Qt.tint(Theme.surface,"#0ee4e0d8")}
            }
            Rectangle {anchors.fill:parent;anchors.margins:1;radius:9;color:"transparent";border.color:Theme.dark?"#12ffffff":"#c0ffffff"}
        }
    }
    Overlay.modal:Rectangle {color:Theme.dark?"#70000000":"#22000000"}
    function pad(value){return String(value).padStart(2,"0")}
    function openFor(kind,dateText,timeText) {
        initializing=true;mode=kind
        const date=(dateText || "").split("-"),time=(timeText || "").split(":")
        const now=new Date(),year=Number(date[0]) || now.getFullYear()
        firstYear=Math.max(100,Math.min(now.getFullYear()-5,year));lastYear=Math.min(9999,Math.max(now.getFullYear()+20,year))
        years.currentIndex=year-firstYear;months.currentIndex=Math.max(0,(Number(date[1]) || now.getMonth()+1)-1)
        days.currentIndex=Math.min(daysInMonth-1,Math.max(0,(Number(date[2]) || now.getDate())-1))
        hours.currentIndex=Number(time[0]) || 0;minutes.currentIndex=Number(time[1]) || 0
        initializing=false;open();Qt.callLater(snapToSelection)
    }
    function snapToSelection() {
        for(const wheel of [years,months,days,hours,minutes])
            wheel.positionViewAtIndex(wheel.currentIndex,Tumbler.Center)
    }
    onOpened:snapToSelection()
    onDaysInMonthChanged:if(!initializing && days.currentIndex>=daysInMonth)days.currentIndex=daysInMonth-1
    component Wheel:Tumbler {
        id:wheel
        property string suffix:""
        property int start:0
        property bool padded:false
        visibleItemCount:5
        Layout.fillWidth:true;Layout.fillHeight:true
        delegate:Text {
            required property int index
            required property int modelData
            readonly property real distance:Math.abs(Tumbler.displacement)
            text:(wheel.padded?root.pad(modelData+wheel.start):String(modelData+wheel.start))+wheel.suffix
            color:distance<0.5?Theme.ink:Theme.muted
            opacity:Math.max(0.15,1-distance*0.28)
            font.family:Theme.fontFamily;font.pixelSize:Theme.font(distance<0.5?21:18,true)
            horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter
        }
        background:Item {}
    }
    ColumnLayout {
        anchors.fill:parent;spacing:14
        Text {Layout.fillWidth:true;text:I18n.t(root.mode==="date"?"日期":"时间");font.family:Theme.fontFamily;font.pixelSize:Theme.font(15,true);font.weight:Font.DemiBold;color:Theme.ink}
        Item {
            Layout.fillWidth:true;Layout.fillHeight:true
            Rectangle {
                anchors.fill:parent;radius:5;border.color:Theme.dark?"#60000000":"#c8cbd0"
                gradient:Gradient {
                    GradientStop {position:0;color:Theme.dark?Qt.darker(Theme.bg,1.15):"#e8e9eb"}
                    GradientStop {position:0.24;color:Theme.dark?Theme.bg:"#f4f4f3"}
                    GradientStop {position:0.76;color:Theme.dark?Theme.bg:"#f4f4f3"}
                    GradientStop {position:1;color:Theme.dark?Qt.lighter(Theme.bg,1.08):"#e6e7e9"}
                }
                Rectangle {x:1;y:1;width:parent.width-2;height:1;color:Theme.dark?"#30000000":"#12000000"}
                Rectangle {x:2;y:parent.height-1;width:parent.width-4;height:1;color:Theme.dark?"#20ffffff":"#e0ffffff"}
            }
            Rectangle {
                anchors.verticalCenter:parent.verticalCenter;width:parent.width;height:parent.height/5
                gradient:Gradient {
                    GradientStop {position:0;color:Theme.dark?Qt.lighter(Theme.surface,1.3):"#fdfdfc"}
                    GradientStop {position:1;color:Theme.dark?Qt.lighter(Theme.surface,1.12):"#edeeef"}
                }
                border.color:Theme.dark?Qt.lighter(Theme.line,1.3):"#c7cbd0"
                Rectangle {x:1;y:1;width:parent.width-2;height:1;color:Theme.dark?"#20ffffff":"#ffffff"}
            }
            RowLayout {
                anchors.fill:parent;visible:root.mode==="date";spacing:0
                Wheel {id:years;objectName:"reminderYearWheel";model:root.lastYear-root.firstYear+1;start:root.firstYear;suffix:I18n.language==="en"?"":"年";wrap:false}
                Wheel {id:months;objectName:"reminderMonthWheel";model:12;start:1;suffix:I18n.language==="en"?"":"月";wrap:false}
                Wheel {id:days;objectName:"reminderDayWheel";model:root.daysInMonth;start:1;suffix:I18n.language==="en"?"":"日";wrap:false}
            }
            RowLayout {
                anchors.fill:parent;visible:root.mode==="time";spacing:0
                Wheel {id:hours;objectName:"reminderHourWheel";model:24;padded:true;wrap:true}
                Text {text:":";font.pixelSize:Theme.font(22,true);color:Theme.ink}
                Wheel {id:minutes;objectName:"reminderMinuteWheel";model:60;padded:true;wrap:true}
            }
        }
        RowLayout {
            Layout.fillWidth:true;spacing:12*Theme.fontScale
            ReminderButton {objectName:"reminderPickerCancel";Layout.fillWidth:true;text:I18n.t("取消");onClicked:root.close()}
            ReminderButton {objectName:"reminderPickerAccept";Layout.fillWidth:true;text:I18n.t("确定");primary:true;onClicked:{root.chosen(root.year+"-"+root.pad(root.month)+"-"+root.pad(root.day),root.pad(hours.currentIndex)+":"+root.pad(minutes.currentIndex));root.close()}}
        }
    }
}
