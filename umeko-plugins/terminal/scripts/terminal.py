import codecs, copy, json, threading, time
from collections import deque
import pyte
from .pty_backend import NativePty


def render_line(line,columns):
    runs=[];plain=[];current=None
    for column in range(columns):
        cell=line[column];text=cell.data;plain.append(text)
        flags=(1 if cell.bold else 0)|(2 if cell.underscore else 0)|(4 if cell.reverse else 0)|(8 if cell.italics else 0)
        style=(cell.fg,cell.bg,flags)
        if current is not None and tuple(current[2:5])==style:current[1]+=text;current[5]+=1
        else:
            current=[column,text,cell.fg,cell.bg,flags,1];runs.append(current)
    while runs and not runs[-1][1].strip() and runs[-1][3]=='default' and not runs[-1][4]&4:runs.pop()
    return {'text':''.join(plain).rstrip(),'runs':runs}


class Screen(pyte.HistoryScreen):
    def __init__(self,columns,rows,history,respond):
        self.pending=deque(maxlen=history);self.respond=respond;self.alternate=False;self.saved=None;self.bracketed=False
        super().__init__(columns,rows,history=history)
    def index(self):
        top,bottom=self.margins or (0,self.lines-1)
        if self.cursor.y==bottom and not self.alternate:self.pending.append(render_line(self.buffer[top],self.columns))
        super().index()
    def set_mode(self,*modes,**kwargs):
        if kwargs.get('private'):
            if 2004 in modes:self.bracketed=True
            if any(mode in modes for mode in (47,1047,1049)) and not self.alternate:
                self.saved=(copy.deepcopy(self.buffer),copy.deepcopy(self.cursor));self.alternate=True
                self.erase_in_display(2);self.cursor_position()
        super().set_mode(*modes,**kwargs)
    def reset_mode(self,*modes,**kwargs):
        if kwargs.get('private'):
            if 2004 in modes:self.bracketed=False
            if any(mode in modes for mode in (47,1047,1049)) and self.alternate:
                self.alternate=False
                if self.saved:self.buffer,self.cursor=self.saved;self.saved=None
                self.dirty.update(range(self.lines))
        super().reset_mode(*modes,**kwargs)
    def write_process_input(self,data):self.respond(data)


class Terminal:
    def __init__(self,identifier,name,profile,argv,cwd,env,columns,rows,history,changed,group):
        self.id=identifier;self.name=name;self.profile=profile;self.cwd=str(cwd);self.group=group;self.history_limit=history
        self.lock=threading.RLock();self.changed=changed;self.revision=0;self.closed=False;self.exited=False;self.error='';self.last_frame=-1
        self.grants=[];self.backend=NativePty(argv,cwd,env,columns,rows)
        self.screen=Screen(columns,rows,history,self.respond);self.stream=pyte.Stream(self.screen);self.decoder=codecs.getincrementaldecoder('utf-8')('replace')
        self.reader=threading.Thread(target=self.read_loop,name='terminal-'+identifier,daemon=True);self.reader.start()
    def respond(self,data):
        try:self.backend.write(data)
        except OSError:pass
    def read_loop(self):
        try:
            while True:
                data=self.backend.read()
                if not data:break
                # ConPTY must remain drained throughout shutdown to avoid deadlock.
                if self.closed:continue
                text=self.decoder.decode(data)
                with self.lock:self.stream.feed(text);self.revision+=1
                self.changed.set()
        except Exception as error:
            if not self.closed:self.error=type(error).__name__+': '+str(error)
        finally:self.exited=True;self.changed.set()
    def info(self):
        return {'id':self.id,'name':self.name,'profile':self.profile,'cwd':self.cwd,'cwdKind':'initial','pid':self.backend.pid,'group':self.group,'alive':self.backend.isalive(),'exitCode':self.backend.exit_code(),'error':self.error}
    def frame(self,reset=False):
        with self.lock:
            rows=[render_line(self.screen.buffer[index],self.screen.columns) for index in range(self.screen.lines)]
            history=[render_line(line,self.screen.columns) for line in self.screen.history.top] if reset else list(self.screen.pending)
            self.screen.pending.clear();self.last_frame=self.revision
            value={'terminalId':self.id,'revision':self.revision,'reset':reset,'screen':rows,'cursor':{'x':self.screen.cursor.x,'y':self.screen.cursor.y,'hidden':self.screen.cursor.hidden},'columns':self.screen.columns,'rows':self.screen.lines,'historyLimit':self.history_limit,'bracketedPaste':self.screen.bracketed}
            if reset:value['history']=history
            else:value['historyAppend']=history
            # The streaming bridge has a 64 KiB event budget; large bursts fall
            # back to plain cell runs while the complete scrollback stays readable.
            if not reset and len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>58000:
                value['screen']=[{'text':row['text'],'runs':[[0,row['text'],'default','default',0,self.screen.columns]]} for row in rows]
                value['historyAppend']=[];value['resync']=True
            if reset:
                while value['history'] and len(json.dumps(value,ensure_ascii=True))>400000:
                    value['history']=value['history'][max(1,len(value['history'])//4):];value['historyClipped']=True
                if len(json.dumps(value,ensure_ascii=True))>400000:
                    value['screen']=[{'text':row['text'],'runs':[[0,row['text'],'default','default',0,self.screen.columns]]} for row in rows]
            return value
    def contents(self,lines=200,after=-1):
        with self.lock:
            if after==self.revision:return {'terminalId':self.id,'sequence':self.revision,'changed':False,**self.info()}
            history=list(self.screen.history.top)
            rows=[render_line(row,self.screen.columns)['text'] for row in history]+list(self.screen.display)
            text='\n'.join(rows[-lines:]).rstrip();encoded=text.encode('utf-8');clipped=len(encoded)>131072
            return {'terminalId':self.id,'sequence':self.revision,'changed':True,'text':encoded[-131072:].decode('utf-8','replace'),'truncated':clipped or len(rows)>lines,**self.info()}
    def write(self,text):
        if self.closed or not self.backend.isalive():raise OSError('Terminal is no longer running')
        self.backend.write(text)
    def resize(self,columns,rows):
        with self.lock:
            if columns==self.screen.columns and rows==self.screen.lines:return
            self.backend.resize(columns,rows);self.screen.resize(lines=rows,columns=columns);self.revision+=1;self.changed.set()
    def clear(self):
        with self.lock:
            self.screen.erase_in_display(3);self.screen.erase_in_display(2);self.screen.cursor_position();self.revision+=1
            self.changed.set()
    def close(self):
        if self.closed:return
        self.closed=True;self.backend.close();self.reader.join(timeout=1);self.exited=True
