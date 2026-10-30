"""Virtualized terminal grid: paint visible rows, keep PTY input out of QML."""
import math, os, unicodedata
# Keep optional standard-library PTY dependencies in frozen desktop packages.
if os.name=='nt':
    import ctypes.wintypes
else:
    import fcntl, pty, resource, termios, tty
from PySide6.QtCore import Property, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType

COLORS={'black':'#000000','red':'#cd3131','green':'#0dbc79','brown':'#e5e510','blue':'#2472c8','magenta':'#bc3fbc','cyan':'#11a8cd','white':'#e5e5e5',
    'brightblack':'#666666','brightred':'#f14c4c','brightgreen':'#23d18b','brightbrown':'#f5f543','brightblue':'#3b8eea','brightmagenta':'#d670d6','brightcyan':'#29b8db','brightwhite':'#ffffff'}
LIGHT_COLORS={'black':'#202020','red':'#aa3731','green':'#287b2f','brown':'#9b6a00','blue':'#1b64c8','magenta':'#a626a4','cyan':'#087b8f','white':'#6b6b6b',
    'brightblack':'#666666','brightred':'#c73737','brightgreen':'#2d8a34','brightbrown':'#aa7500','brightblue':'#2675df','brightmagenta':'#b62dac','brightcyan':'#00859b','brightwhite':'#828282'}


class TerminalView(QQuickPaintedItem):
    input=Signal(str);inputRejected=Signal(str);resized=Signal(int,int);contextMenuRequested=Signal(float,float)
    styleChanged=Signal();selectionChanged=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setAcceptedMouseButtons(Qt.LeftButton|Qt.RightButton);self.setAcceptHoverEvents(True);self.setCursor(Qt.IBeamCursor)
        self.setFlag(self.Flag.ItemAcceptsInputMethod,True)
        available=set(QFontDatabase.families())
        self._family=next((name for name in ('Cascadia Mono','Consolas','Menlo','DejaVu Sans Mono') if name in available),QFontDatabase.systemFont(QFontDatabase.FixedFont).family());self._size=12.0
        self._background=QColor('#ffffff');self._foreground=QColor('#202020');self._cursor_color=QColor('#2684ff')
        self._history=[];self._screen=[];self._cursor={};self._revision=-1;self._scroll=0;self._limit=1000;self._bracketed=False
        self._start=None;self._end=None;self._drag=False;self._preedit='';self._blink=True;self._dimensions=(0,0)
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.blink);self.timer.start();self.metrics()

    def metrics(self):
        self._font=QFont(self._family);self._font.setPixelSize(max(8,round(self._size)));self._font.setStyleHint(QFont.Monospace)
        self._metrics=QFontMetricsF(self._font);self._cw=max(1,self._metrics.horizontalAdvance('M'));self._ch=math.ceil(self._metrics.height()+2)
        self.dimensions();self.update()
    def dimensions(self):
        value=(min(240,max(20,int((self.width()-8)/self._cw))),min(100,max(4,int((self.height()-8)/self._ch))))
        if value!=self._dimensions:self._dimensions=value;self.resized.emit(*value)
    def geometryChange(self,new,old):super().geometryChange(new,old);self.dimensions()
    def blink(self):
        if self.hasActiveFocus():self._blink=not self._blink;self.update()
    def family(self):return self._family
    def set_family(self,value):
        if value and value!=self._family:self._family=value;self.metrics();self.styleChanged.emit()
    fontFamily=Property(str,family,set_family,notify=styleChanged)
    def size(self):return self._size
    def set_size(self,value):
        if value!=self._size:self._size=value;self.metrics();self.styleChanged.emit()
    fontSize=Property(float,size,set_size,notify=styleChanged)
    def background(self):return self._background
    def set_background(self,value):self._background=QColor(value);self.update();self.styleChanged.emit()
    backgroundColor=Property(QColor,background,set_background,notify=styleChanged)
    def foreground(self):return self._foreground
    def set_foreground(self,value):self._foreground=QColor(value);self.update();self.styleChanged.emit()
    foregroundColor=Property(QColor,foreground,set_foreground,notify=styleChanged)
    def cursor_color(self):return self._cursor_color
    def set_cursor_color(self,value):self._cursor_color=QColor(value);self.update();self.styleChanged.emit()
    cursorColor=Property(QColor,cursor_color,set_cursor_color,notify=styleChanged)
    @Property(bool,notify=selectionChanged)
    def hasSelection(self):return self._start is not None and self._end is not None and self._start!=self._end

    @Slot('QVariantMap')
    def applyFrame(self,frame):
        revision=frame.get('revision',0)
        if revision<=self._revision and not frame.get('reset'):return
        self._revision=revision;self._limit=min(5000,max(100,int(frame.get('historyLimit',self._limit))))
        if frame.get('reset'):
            self._history=list(frame.get('history',[]));self._scroll=0;self.clear_selection()
        else:
            appended=frame.get('historyAppend',[]);self._history.extend(appended)
            if self._scroll:self._scroll+=len(appended)
        trim=max(0,len(self._history)-self._limit)
        if trim:self._history=self._history[trim:];self.clear_selection()
        self._screen=frame.get('screen',self._screen);self._cursor=frame.get('cursor',self._cursor);self._bracketed=bool(frame.get('bracketedPaste',False))
        self._scroll=min(self._scroll,max(0,len(self._history)));self.update()
    @Slot()
    def reset(self):self._history=[];self._screen=[];self._revision=-1;self._scroll=0;self.clear_selection();self.update()
    def clear_selection(self):self._start=self._end=None;self.selectionChanged.emit()
    def color(self,value,default):
        if value=='default' or not value:return default
        palette=LIGHT_COLORS if self._background.lightness()>128 else COLORS
        color=QColor(palette.get(value,'#'+value if len(value)==6 else value))
        return color if color.isValid() else default
    def lines(self):return self._history+self._screen
    def top(self):return max(0,len(self._history)-self._scroll)
    def bounds(self):return sorted((self._start,self._end)) if self.hasSelection else None
    def paint(self,painter):
        painter.fillRect(self.boundingRect(),self._background);painter.setFont(self._font)
        lines=self.lines();top=self.top();selection=self.bounds()
        for visible in range(self._dimensions[1]+1):
            index=top+visible
            if index>=len(lines):break
            y=4+visible*self._ch;line=lines[index]
            for run in line.get('runs',[]):
                column,text,fg,bg,flags,cells=run
                foreground=self.color(fg,self._foreground);background=self.color(bg,self._background)
                if flags&4:foreground,background=background,foreground
                painter.fillRect(QRectF(4+column*self._cw,y,cells*self._cw,self._ch),background)
                font=QFont(self._font);font.setBold(bool(flags&1));font.setUnderline(bool(flags&2));font.setItalic(bool(flags&8));painter.setFont(font);painter.setPen(foreground)
                painter.drawText(QRectF(4+column*self._cw,y,cells*self._cw+2,self._ch),Qt.AlignLeft|Qt.AlignVCenter,text)
            if selection and selection[0][0]<=index<=selection[1][0]:
                left=selection[0][1] if index==selection[0][0] else 0;right=selection[1][1] if index==selection[1][0] else self._dimensions[0]
                painter.fillRect(QRectF(4+left*self._cw,y,max(0,right-left)*self._cw,self._ch),QColor(60,130,220,105))
        cursor_y=len(self._history)+self._cursor.get('y',0)-top
        if self.hasActiveFocus() and self._blink and not self._cursor.get('hidden') and 0<=cursor_y<self._dimensions[1]:
            color=QColor(self._cursor_color);color.setAlpha(190)
            painter.fillRect(QRectF(4+self._cursor.get('x',0)*self._cw,4+cursor_y*self._ch,self._cw,self._ch),color)
        if self._preedit:
            painter.setFont(self._font);painter.setPen(self._foreground)
            painter.drawText(QRectF(4+self._cursor.get('x',0)*self._cw,4+max(0,cursor_y)*self._ch,self.width(),self._ch),Qt.AlignLeft|Qt.AlignVCenter,self._preedit)
    def point(self,event):
        position=event.position()
        return (min(max(0,len(self.lines())-1),self.top()+max(0,int((position.y()-4)/self._ch))),min(self._dimensions[0],max(0,int((position.x()-4)/self._cw))))
    def mousePressEvent(self,event):
        self.forceActiveFocus()
        if event.button()==Qt.RightButton:self.contextMenuRequested.emit(event.position().x(),event.position().y());event.accept();return
        self._start=self._end=self.point(event);self._drag=True;self.selectionChanged.emit();self.update();event.accept()
    def mouseMoveEvent(self,event):
        if self._drag:self._end=self.point(event);self.selectionChanged.emit();self.update();event.accept()
    def mouseReleaseEvent(self,event):self._drag=False;event.accept()
    def wheelEvent(self,event):
        self._scroll=min(len(self._history),max(0,self._scroll+(3 if event.angleDelta().y()>0 else -3)));self.update();event.accept()
    @staticmethod
    def columns(text,start,end):
        result=[];column=0
        for char in text:
            width=0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ('W','F') else 1
            if start<=column<end:result.append(char)
            column+=width
        return ''.join(result)
    @Slot(result=str)
    def selectedText(self):
        bounds=self.bounds()
        if not bounds:return ''
        lines=self.lines();start,end=bounds;selected=[]
        for index in range(start[0],min(len(lines),end[0]+1)):
            selected.append(self.columns(lines[index].get('text',''),start[1] if index==start[0] else 0,end[1] if index==end[0] else self._dimensions[0]).rstrip())
        return '\n'.join(selected)
    @Slot()
    def copy(self):
        if self.hasSelection:QGuiApplication.clipboard().setText(self.selectedText())
    @Slot()
    def selectAll(self):self._start=(0,0);self._end=(max(0,len(self.lines())-1),self._dimensions[0]);self.selectionChanged.emit();self.update()
    @Slot()
    def paste(self):
        text=QGuiApplication.clipboard().text().replace('\r\n','\n')
        if len(text)>16000:self.inputRejected.emit('一次粘贴最多 16000 字符，请分段粘贴');return
        if text:self.send(('\x1b[200~'+text+'\x1b[201~') if self._bracketed else text.replace('\n','\r'))
    def send(self,text):self._scroll=0;self.clear_selection();self._blink=True;self.input.emit(text);self.update()
    def keyPressEvent(self,event):
        key=event.key();mod=event.modifiers();control=bool(mod&Qt.ControlModifier);shift=bool(mod&Qt.ShiftModifier);meta=bool(mod&Qt.MetaModifier)
        if (control and shift or meta) and key==Qt.Key_C:self.copy();event.accept();return
        if (control and shift or meta) and key==Qt.Key_V:self.paste();event.accept();return
        if control and key==Qt.Key_C and self.hasSelection:self.copy();event.accept();return
        if shift and key in (Qt.Key_PageUp,Qt.Key_PageDown):
            self._scroll=min(len(self._history),max(0,self._scroll+(self._dimensions[1] if key==Qt.Key_PageUp else -self._dimensions[1])));self.update();event.accept();return
        special={Qt.Key_Return:'\r',Qt.Key_Enter:'\r',Qt.Key_Backspace:'\x7f',Qt.Key_Tab:'\t',Qt.Key_Backtab:'\x1b[Z',Qt.Key_Escape:'\x1b',Qt.Key_Up:'\x1b[A',Qt.Key_Down:'\x1b[B',Qt.Key_Right:'\x1b[C',Qt.Key_Left:'\x1b[D',Qt.Key_Home:'\x1b[H',Qt.Key_End:'\x1b[F',Qt.Key_Delete:'\x1b[3~',Qt.Key_Insert:'\x1b[2~',Qt.Key_PageUp:'\x1b[5~',Qt.Key_PageDown:'\x1b[6~',Qt.Key_F1:'\x1bOP',Qt.Key_F2:'\x1bOQ',Qt.Key_F3:'\x1bOR',Qt.Key_F4:'\x1bOS',Qt.Key_F5:'\x1b[15~',Qt.Key_F6:'\x1b[17~',Qt.Key_F7:'\x1b[18~',Qt.Key_F8:'\x1b[19~',Qt.Key_F9:'\x1b[20~',Qt.Key_F10:'\x1b[21~',Qt.Key_F11:'\x1b[23~',Qt.Key_F12:'\x1b[24~'}
        text=special.get(key,'')
        if key in (Qt.Key_Up,Qt.Key_Down,Qt.Key_Right,Qt.Key_Left,Qt.Key_Home,Qt.Key_End) and (control or shift or mod&Qt.AltModifier):
            modifier=1+int(shift)+2*int(bool(mod&Qt.AltModifier))+4*int(control);text='\x1b[1;'+str(modifier)+text[-1]
        if control and Qt.Key_A<=key<=Qt.Key_Z and not mod&Qt.AltModifier:text=chr(key-Qt.Key_A+1)
        elif not text:text=event.text()
        if text:
            if mod&Qt.AltModifier and not control and key not in (Qt.Key_Up,Qt.Key_Down,Qt.Key_Right,Qt.Key_Left,Qt.Key_Home,Qt.Key_End):text='\x1b'+text
            self.send(text);event.accept()
        else:super().keyPressEvent(event)
    def inputMethodEvent(self,event):
        if event.commitString():self.send(event.commitString())
        self._preedit=event.preeditString();self.update();event.accept()
    def inputMethodQuery(self,query):
        if query==Qt.ImEnabled:return True
        if query==Qt.ImCursorRectangle:return QRectF(4+self._cursor.get('x',0)*self._cw,4+self._cursor.get('y',0)*self._ch,self._cw,self._ch)
        if query==Qt.ImSurroundingText:return ''
        return super().inputMethodQuery(query)


def register_terminal_types():qmlRegisterType(TerminalView,'Umeko.Terminal',1,0,'TerminalView')
