"""Windows ConPTY with owned handles and an independently drained output pipe.

API lifecycle: https://learn.microsoft.com/windows/console/creating-a-pseudoconsole-session
"""
import ctypes as c
from ctypes import wintypes as w
import queue
import subprocess
import threading
import time


class JobLimits(c.Structure):
    _fields_=[('per_process_time',c.c_longlong),('per_job_time',c.c_longlong),('flags',w.DWORD),
        ('min_working_set',c.c_size_t),('max_working_set',c.c_size_t),('active_limit',w.DWORD),
        ('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]


class ExtendedJobLimits(c.Structure):
    _fields_=[('basic',JobLimits),('io',c.c_ulonglong*6),('process_memory',c.c_size_t),
        ('job_memory',c.c_size_t),('peak_process_memory',c.c_size_t),('peak_job_memory',c.c_size_t)]


class JobAccounting(c.Structure):
    _fields_=[('user_time',c.c_longlong),('kernel_time',c.c_longlong),('period_user_time',c.c_longlong),
        ('period_kernel_time',c.c_longlong),('page_faults',w.DWORD),('total',w.DWORD),('active',w.DWORD),('terminated',w.DWORD)]


class WindowsJob:
    """Track normal CreateProcess descendants, including between observer polls.

    No time, CPU or memory limit. Closing the observer releases its own group.
    External brokers/WMI-created processes are outside this Windows job.
    """
    def __init__(self):
        self.api=c.WinDLL('kernel32',use_last_error=True);self.handle=None
        signatures={'CreateJobObjectW':(w.HANDLE,[c.c_void_p,w.LPCWSTR]),
            'SetInformationJobObject':(w.BOOL,[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]),
            'QueryInformationJobObject':(w.BOOL,[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p]),
            'AssignProcessToJobObject':(w.BOOL,[w.HANDLE,w.HANDLE]),'TerminateJobObject':(w.BOOL,[w.HANDLE,w.UINT]),
            'OpenProcess':(w.HANDLE,[w.DWORD,w.BOOL,w.DWORD]),'OpenThread':(w.HANDLE,[w.DWORD,w.BOOL,w.DWORD]),
            'ResumeThread':(w.DWORD,[w.HANDLE]),'CloseHandle':(w.BOOL,[w.HANDLE])}
        for name,(restype,args) in signatures.items():
            method=getattr(self.api,name);method.restype=restype;method.argtypes=args
        self.handle=self.api.CreateJobObjectW(None,None);self.check(self.handle)
        limits=ExtendedJobLimits();limits.basic.flags=0x00002000
        try:self.check(self.api.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)))
        except BaseException:self.close();raise

    @staticmethod
    def check(value):
        if not value:raise c.WinError(c.get_last_error())

    def assign(self,pid,handle=None):
        owned=handle is None
        if owned:handle=self.api.OpenProcess(0x0101,False,pid);self.check(handle)
        try:self.check(self.api.AssignProcessToJobObject(self.handle,handle))
        finally:
            if owned:self.api.CloseHandle(handle)

    def resume(self,thread_id=None,handle=None):
        owned=handle is None
        if owned:handle=self.api.OpenThread(0x0002,False,thread_id);self.check(handle)
        try:
            if self.api.ResumeThread(handle)==0xffffffff:raise c.WinError(c.get_last_error())
        finally:
            if owned:self.api.CloseHandle(handle)

    def accounting(self):
        value=JobAccounting();self.check(self.api.QueryInformationJobObject(self.handle,1,c.byref(value),c.sizeof(value),None))
        return {'backend':'Windows-Job','total_processes':value.total,'active_processes':value.active,
            'terminated_processes':value.terminated,'scope':'normal CreateProcess descendants; external brokers and WMI are not covered'}

    def stop(self):
        self.check(self.api.TerminateJobObject(self.handle,1));deadline=time.monotonic()+4
        while self.accounting()['active_processes'] and time.monotonic()<deadline:time.sleep(.005)
        status=self.accounting()
        return {'owned_process_stopped':status['active_processes']==0,'job_accounting':status}

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None


class Coord(c.Structure):
    _fields_=[('X',c.c_short),('Y',c.c_short)]


class Startup(c.Structure):
    _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),('lpTitle',w.LPWSTR),
        ('dwX',w.DWORD),('dwY',w.DWORD),('dwXSize',w.DWORD),('dwYSize',w.DWORD),
        ('dwXCountChars',w.DWORD),('dwYCountChars',w.DWORD),('dwFillAttribute',w.DWORD),('dwFlags',w.DWORD),
        ('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',c.POINTER(c.c_byte)),
        ('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]


class StartupEx(c.Structure):
    _fields_=[('StartupInfo',Startup),('lpAttributeList',c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]


class WindowsTerminal:
    def __init__(self,argv,cwd,environment,terminal):
        self.api=c.WinDLL('kernel32',use_last_error=True)
        def api(name,restype,args):
            method=getattr(self.api,name);method.restype=restype;method.argtypes=args;return method
        self.create_pipe=api('CreatePipe',w.BOOL,[c.POINTER(w.HANDLE),c.POINTER(w.HANDLE),c.c_void_p,w.DWORD])
        self.close_handle=api('CloseHandle',w.BOOL,[w.HANDLE])
        self.create_console=api('CreatePseudoConsole',c.c_long,[Coord,w.HANDLE,w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)])
        self.close_console=api('ClosePseudoConsole',None,[w.HANDLE])
        self.resize_console=api('ResizePseudoConsole',c.c_long,[w.HANDLE,Coord])
        self.initialize_attributes=api('InitializeProcThreadAttributeList',w.BOOL,[c.c_void_p,w.DWORD,w.DWORD,c.POINTER(c.c_size_t)])
        self.update_attributes=api('UpdateProcThreadAttribute',w.BOOL,[c.c_void_p,w.DWORD,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p])
        self.delete_attributes=api('DeleteProcThreadAttributeList',None,[c.c_void_p])
        self.create_process=api('CreateProcessW',w.BOOL,[w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(Startup),c.POINTER(ProcessInfo)])
        self.read_file=api('ReadFile',w.BOOL,[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p])
        self.write_file=api('WriteFile',w.BOOL,[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p])
        self.wait=api('WaitForSingleObject',w.DWORD,[w.HANDLE,w.DWORD])
        self.exit_code=api('GetExitCodeProcess',w.BOOL,[w.HANDLE,c.POINTER(w.DWORD)])
        self.queue=queue.Queue();self.eof=False;self.closed=False;self.console=w.HANDLE();self.process=None
        self.input_read=w.HANDLE();self.input_write=w.HANDLE();self.output_read=w.HANDLE();self.output_write=w.HANDLE()
        self.attributes=None;self.attributes_initialized=False;self.reader=None;self.job=None;self.started=False
        try:
            self.job=WindowsJob()
            self.check(self.create_pipe(c.byref(self.input_read),c.byref(self.input_write),None,0))
            self.check(self.create_pipe(c.byref(self.output_read),c.byref(self.output_write),None,0))
            size=self.size(terminal['columns'],terminal['rows'])
            self.hresult(self.create_console(size,self.input_read,self.output_write,0,c.byref(self.console)))
            self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
            count=c.c_size_t()
            self.initialize_attributes(None,1,0,c.byref(count))
            if not count.value:raise c.WinError(c.get_last_error())
            self.attributes=c.create_string_buffer(count.value)
            self.check(self.initialize_attributes(self.attributes,1,0,c.byref(count)));self.attributes_initialized=True
            self.check(self.update_attributes(self.attributes,0,0x00020016,self.console,c.sizeof(w.HANDLE),None,None))
            startup=StartupEx();startup.StartupInfo.cb=c.sizeof(StartupEx);startup.StartupInfo.dwFlags=0x00000100
            startup.lpAttributeList=c.cast(self.attributes,c.c_void_p)
            information=ProcessInfo()
            command=c.create_unicode_buffer(subprocess.list2cmdline(argv))
            env=c.create_unicode_buffer('\0'.join(key+'='+value for key,value in sorted(environment.items(),key=lambda item:item[0].upper()))+'\0\0')
            self.check(self.create_process(argv[0],command,None,None,False,0x00080000|0x00000400|0x4,
                env,str(cwd),c.byref(startup.StartupInfo),c.byref(information)))
            self.pid=information.dwProcessId;self.process=information.hProcess
            try:
                self.job.assign(self.pid,self.process);self.job.resume(handle=information.hThread);self.started=True
            finally:self.close_handle(information.hThread)
            # Release our child-side pipe copies after process creation so EOF
            # can propagate when ConPTY closes its own references.
            self.close_handle(self.input_read);self.input_read=w.HANDLE()
            self.close_handle(self.output_write);self.output_write=w.HANDLE()
            self.delete_attributes(self.attributes);self.attributes_initialized=False
        except BaseException:
            self.close();raise

    @staticmethod
    def check(success):
        if not success:raise c.WinError(c.get_last_error())

    @staticmethod
    def hresult(value):
        if value<0:raise OSError('Windows pseudoconsole HRESULT 0x'+format(value&0xffffffff,'08x'))

    @staticmethod
    def size(columns,rows):
        if not 0<columns<=32767 or not 0<rows<=32767:raise ValueError('Windows COORD dimensions must fit positive signed 16-bit values')
        return Coord(columns,rows)

    def _read(self):
        buffer=c.create_string_buffer(65536);count=w.DWORD()
        try:
            while True:
                if not self.read_file(self.output_read,buffer,len(buffer),c.byref(count),None):
                    error=c.get_last_error()
                    if error not in {109,232}:self.queue.put(('error',str(c.WinError(error))))
                    break
                if not count.value:break
                self.queue.put(('terminal',buffer.raw[:count.value]))
        finally:self.queue.put(('eof',None))

    def read(self):
        rows=[]
        while True:
            try:channel,data=self.queue.get_nowait()
            except queue.Empty:break
            if channel=='eof':self.eof=True
            elif channel=='error':raise OSError(data)
            else:rows.append((channel,data))
        return rows

    def poll(self):
        if self.wait(self.process,0)==258:return None
        value=w.DWORD();self.check(self.exit_code(self.process,c.byref(value)))
        return value.value

    def finalize_output(self):
        if self.console.value:
            console=self.console;self.console=w.HANDLE()
            # The output reader drains the final frame through real pipe EOF.
            self.close_console(console)

    def write_some(self,data):
        buffer=c.create_string_buffer(data);count=w.DWORD()
        self.check(self.write_file(self.input_write,buffer,len(data),c.byref(count),None))
        return count.value

    def close_input(self):raise ValueError('A pseudoterminal has no separate stdin EOF; send input or an explicit signal')
    def signal(self,name):
        if name=='interrupt':raise ValueError('Interrupt is sent through the ConPTY input channel')
        terminate=self.api.TerminateProcess;terminate.restype=w.BOOL;terminate.argtypes=[w.HANDLE,w.UINT]
        self.check(terminate(self.process,1));return 'TerminateProcess'
    def resize(self,columns,rows):self.hresult(self.resize_console(self.console,self.size(columns,rows)))
    def complete(self):return self.eof

    def close(self):
        if self.closed:return
        self.closed=True
        if self.process and not self.started:
            terminate=self.api.TerminateProcess;terminate.restype=w.BOOL;terminate.argtypes=[w.HANDLE,w.UINT]
            terminate(self.process,1)
        if self.job is not None:self.job.close()
        for name in ['input_read','output_write']:
            handle=getattr(self,name)
            if handle:self.close_handle(handle);setattr(self,name,w.HANDLE())
        self.finalize_output()
        if self.reader is not None:self.reader.join(timeout=2)
        if self.attributes_initialized:self.delete_attributes(self.attributes);self.attributes_initialized=False
        for handle in [self.input_read,self.input_write,self.output_read,self.output_write,self.process]:
            if handle:self.close_handle(handle)
