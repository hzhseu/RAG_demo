"""Windows Job Object: kill owned workers when the launcher is closed or crashes."""
import ctypes
import os
import subprocess
import threading

_job = None
_lock = threading.Lock()


def track(process, private=False):
    global _job
    if os.name != 'nt':
        return process
    from ctypes import wintypes as w
    with _lock:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.AssignProcessToJobObject.restype = w.BOOL
        job = _job
        if job is None or private:
            class Basic(ctypes.Structure):
                _fields_ = [('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
            class Extended(ctypes.Structure):
                _fields_ = [('basic',Basic),('io',IO),('process_mem',ctypes.c_size_t),('job_mem',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
            handle = kernel.CreateJobObjectW(None,None)
            info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)):
                process.terminate()
                raise ctypes.WinError(ctypes.get_last_error())
            job = handle
            if not private:
                _job = handle
        if not kernel.AssignProcessToJobObject(job,int(process._handle)):
            process.terminate()
            raise ctypes.WinError(ctypes.get_last_error())
        if private:
            process._nord_job = job
    return process


def close_private_job(process):
    handle = getattr(process, '_nord_job', None)
    if handle:
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        kernel.CloseHandle(handle)
        process._nord_job = None


def run_owned(args, timeout, **kwargs):
    process = track(subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs), private=True)
    try:
        stdout,stderr=process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
    except BaseException:
        close_private_job(process)
        if process.poll() is None:
            process.kill()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    finally:
        close_private_job(process)
