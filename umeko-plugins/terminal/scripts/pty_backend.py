"""Native ConPTY on Windows; a controlling POSIX PTY on macOS/Linux."""
import os, queue, signal, subprocess, threading, time


class Writer:
    def start_writer(self):
        self.input=queue.Queue(maxsize=64);self.closed=False
        self.writer=threading.Thread(target=self.write_loop,daemon=True);self.writer.start()
    def write(self,text):
        if self.closed:raise OSError('Terminal is closed')
        try:self.input.put_nowait(text.encode('utf-8'))
        except queue.Full:raise OSError('Terminal input queue is full') from None
    def write_loop(self):
        while True:
            data=self.input.get()
            if data is None:return
            try:self.write_bytes(data)
            except OSError:return
    def stop_writer(self):
        try:self.input.put_nowait(None)
        except queue.Full:pass


if os.name=='nt':
    import ctypes as C
    from ctypes import wintypes as W
    class COORD(C.Structure):_fields_=[('X',C.c_short),('Y',C.c_short)]
    class STARTUPINFO(C.Structure):
        _fields_=[('cb',W.DWORD),('lpReserved',W.LPWSTR),('lpDesktop',W.LPWSTR),('lpTitle',W.LPWSTR),('dwX',W.DWORD),('dwY',W.DWORD),('dwXSize',W.DWORD),('dwYSize',W.DWORD),('dwXCountChars',W.DWORD),('dwYCountChars',W.DWORD),('dwFillAttribute',W.DWORD),('dwFlags',W.DWORD),('wShowWindow',W.WORD),('cbReserved2',W.WORD),('lpReserved2',C.c_void_p),('hStdInput',W.HANDLE),('hStdOutput',W.HANDLE),('hStdError',W.HANDLE)]
    class STARTUPINFOEX(C.Structure):_fields_=[('StartupInfo',STARTUPINFO),('lpAttributeList',C.c_void_p)]
    class PROCESS_INFORMATION(C.Structure):_fields_=[('hProcess',W.HANDLE),('hThread',W.HANDLE),('dwProcessId',W.DWORD),('dwThreadId',W.DWORD)]
    class BASIC_LIMIT(C.Structure):
        _fields_=[('PerProcessUserTimeLimit',C.c_longlong),('PerJobUserTimeLimit',C.c_longlong),('LimitFlags',W.DWORD),('MinimumWorkingSetSize',C.c_size_t),('MaximumWorkingSetSize',C.c_size_t),('ActiveProcessLimit',W.DWORD),('Affinity',C.c_size_t),('PriorityClass',W.DWORD),('SchedulingClass',W.DWORD)]
    class IO_COUNTERS(C.Structure):_fields_=[(name,C.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class EXTENDED_LIMIT(C.Structure):_fields_=[('BasicLimitInformation',BASIC_LIMIT),('IoInfo',IO_COUNTERS),('ProcessMemoryLimit',C.c_size_t),('JobMemoryLimit',C.c_size_t),('PeakProcessMemoryUsed',C.c_size_t),('PeakJobMemoryUsed',C.c_size_t)]
    kernel=C.WinDLL('kernel32',use_last_error=True)
    def bind(name,arguments,result):
        fn=getattr(kernel,name);fn.argtypes=arguments;fn.restype=result;return fn
    CreatePipe=bind('CreatePipe',[C.POINTER(W.HANDLE),C.POINTER(W.HANDLE),C.c_void_p,W.DWORD],W.BOOL)
    CloseHandle=bind('CloseHandle',[W.HANDLE],W.BOOL)
    CreatePseudoConsole=bind('CreatePseudoConsole',[COORD,W.HANDLE,W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)],C.c_long)
    ResizePseudoConsole=bind('ResizePseudoConsole',[W.HANDLE,COORD],C.c_long)
    ClosePseudoConsole=bind('ClosePseudoConsole',[W.HANDLE],None)
    Initialize=bind('InitializeProcThreadAttributeList',[C.c_void_p,W.DWORD,W.DWORD,C.POINTER(C.c_size_t)],W.BOOL)
    Update=bind('UpdateProcThreadAttribute',[C.c_void_p,W.DWORD,C.c_size_t,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p],W.BOOL)
    Delete=bind('DeleteProcThreadAttributeList',[C.c_void_p],None)
    CreateProcess=bind('CreateProcessW',[W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,W.DWORD,C.c_void_p,W.LPCWSTR,C.POINTER(STARTUPINFO),C.POINTER(PROCESS_INFORMATION)],W.BOOL)
    CreateJob=bind('CreateJobObjectW',[C.c_void_p,W.LPCWSTR],W.HANDLE)
    SetJob=bind('SetInformationJobObject',[W.HANDLE,C.c_int,C.c_void_p,W.DWORD],W.BOOL)
    AssignJob=bind('AssignProcessToJobObject',[W.HANDLE,W.HANDLE],W.BOOL)
    TerminateJob=bind('TerminateJobObject',[W.HANDLE,W.UINT],W.BOOL)
    TerminateProcess=bind('TerminateProcess',[W.HANDLE,W.UINT],W.BOOL)
    ResumeThread=bind('ResumeThread',[W.HANDLE],W.DWORD)
    Wait=bind('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD)
    ExitCode=bind('GetExitCodeProcess',[W.HANDLE,C.POINTER(W.DWORD)],W.BOOL)
    Read=bind('ReadFile',[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p],W.BOOL)
    Write=bind('WriteFile',[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p],W.BOOL)
    def check(value):
        if not value:raise C.WinError(C.get_last_error())

    class NativePty(Writer):
        def __init__(self,argv,cwd,env,columns,rows):
            self.read_handle=W.HANDLE();self.write_handle=W.HANDLE();self.console=W.HANDLE();self.process=None;self.job=None;self.pid=0;self._exit=None
            input_read=W.HANDLE();output_write=W.HANDLE();attributes=None;started=False
            try:
                check(CreatePipe(C.byref(input_read),C.byref(self.write_handle),None,0));check(CreatePipe(C.byref(self.read_handle),C.byref(output_write),None,0))
                result=CreatePseudoConsole(COORD(columns,rows),input_read,output_write,0,C.byref(self.console))
                if result:raise OSError('CreatePseudoConsole failed: 0x%08x'%(result&0xffffffff))
                size=C.c_size_t();Initialize(None,1,0,C.byref(size));attributes=C.create_string_buffer(size.value)
                check(Initialize(attributes,1,0,C.byref(size)));check(Update(attributes,0,0x00020016,self.console,C.sizeof(W.HANDLE),None,None))
                startup=STARTUPINFOEX();startup.StartupInfo.cb=C.sizeof(startup);startup.lpAttributeList=C.cast(attributes,C.c_void_p)
                # A JSONL worker has redirected stdio. Force the child to use
                # ConPTY instead of duplicating those parent pipe handles.
                # https://github.com/microsoft/terminal/discussions/15814
                startup.StartupInfo.dwFlags=0x00000100
                command=C.create_unicode_buffer(subprocess.list2cmdline(argv));environment=C.create_unicode_buffer('\0'.join(key+'='+value for key,value in sorted(env.items(),key=lambda pair:pair[0].upper()))+'\0\0')
                process=PROCESS_INFORMATION()
                check(CreateProcess(argv[0],command,None,None,False,0x00080000|0x00000400|0x00000004,environment,str(cwd),C.byref(startup.StartupInfo),C.byref(process)))
                self.process=process.hProcess;self.pid=process.dwProcessId
                try:
                    self.job=CreateJob(None,None);check(self.job);limits=EXTENDED_LIMIT();limits.BasicLimitInformation.LimitFlags=0x2000
                    check(SetJob(self.job,9,C.byref(limits),C.sizeof(limits)));check(AssignJob(self.job,self.process))
                    self.start_writer()
                    if ResumeThread(process.hThread)==0xffffffff:raise C.WinError(C.get_last_error())
                    started=True
                finally:CloseHandle(process.hThread)
            finally:
                if attributes:Delete(attributes)
                if input_read:CloseHandle(input_read)
                if output_write:CloseHandle(output_write)
                if not started:
                    if self.process:TerminateProcess(self.process,1);CloseHandle(self.process)
                    if self.console:ClosePseudoConsole(self.console)
                    if self.job:CloseHandle(self.job)
                    if self.read_handle:CloseHandle(self.read_handle)
                    if self.write_handle:CloseHandle(self.write_handle)
        def read(self):
            buffer=C.create_string_buffer(32768);count=W.DWORD()
            if not Read(self.read_handle,buffer,len(buffer),C.byref(count),None):
                if C.get_last_error() in (6,109,232):return b''
                raise C.WinError(C.get_last_error())
            return buffer.raw[:count.value]
        def write_bytes(self,data):
            while data:
                count=W.DWORD();check(Write(self.write_handle,data,len(data),C.byref(count),None));data=data[count.value:]
        def resize(self,columns,rows):
            if not self.closed:
                result=ResizePseudoConsole(self.console,COORD(columns,rows))
                if result:raise OSError('ResizePseudoConsole failed')
        def isalive(self):return not self.closed and Wait(self.process,0)==258
        def exit_code(self):
            if self.closed:return self._exit
            code=W.DWORD();return code.value if ExitCode(self.process,C.byref(code)) and code.value!=259 else None
        def close(self):
            if self.closed:return
            self._exit=self.exit_code();self.closed=True;self.stop_writer();TerminateJob(self.job,0)
            # The reader keeps draining while ClosePseudoConsole emits its final frame.
            ClosePseudoConsole(self.console);self.writer.join(.5)
            for handle in (self.job,self.process,self.write_handle,self.read_handle):
                if handle:CloseHandle(handle)
else:
    from ptyprocess import PtyProcess
    class NativePty(Writer):
        def __init__(self,argv,cwd,env,columns,rows):
            self.process=PtyProcess.spawn(argv,cwd=str(cwd),env=env,dimensions=(rows,columns));self.pid=self.process.pid;self._exit=None;self.start_writer()
        def read(self):
            try:return self.process.read(32768)
            except (EOFError,OSError):return b''
        def write_bytes(self,data):
            while data:data=data[self.process.write(data):]
        def resize(self,columns,rows):
            if not self.closed:self.process.setwinsize(rows,columns)
        def isalive(self):return not self.closed and self.process.isalive()
        def exit_code(self):return self._exit if self.closed else self.process.exitstatus
        def close(self):
            if self.closed:return
            self.closed=True;self.stop_writer();groups={self.pid}
            try:
                foreground=os.tcgetpgrp(self.process.fd)
                if foreground>0 and os.getsid(foreground)==self.pid:groups.add(foreground)
            except OSError:pass
            for group in groups:
                try:os.killpg(group,signal.SIGHUP)
                except ProcessLookupError:pass
            self.process.close(force=True);self._exit=self.process.exitstatus;self.writer.join(.5)
