"""Windows ProcessSupervisorPort using Job Object KILL_ON_JOB_CLOSE (DEC-008, DEC-020, BR-AI-04, NFR-15)."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Sequence

import psutil

from jarvis.domain.models import RuntimeOwnershipMode
from jarvis.domain.ports import ManagedProcessHandle

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJobProcessSupervisor:
    """Supervises managed_local workers inside a Win32 Job Object while strictly protecting external_local PIDs."""

    def __init__(self) -> None:
        self._managed: dict[int, subprocess.Popen[bytes]] = {}
        self._external: dict[int, ManagedProcessHandle] = {}
        self._job_handle: int | None = None
        if sys.platform == "win32":
            self._job_handle = self._create_kill_on_close_job()

    @staticmethod
    def _create_kill_on_close_job() -> int:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError("CreateJobObjectW failed.")

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle),
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            raise OSError("SetInformationJobObject(KILL_ON_JOB_CLOSE) failed.")
        return int(handle)

    def _assign_pid_to_job(self, pid: int) -> None:
        if sys.platform != "win32" or self._job_handle is None:
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        proc_handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
        if not proc_handle:
            raise OSError(f"OpenProcess failed for PID {pid}.")
        try:
            ok = kernel32.AssignProcessToJobObject(ctypes.c_void_p(self._job_handle), ctypes.c_void_p(proc_handle))
            if not ok:
                raise OSError(f"AssignProcessToJobObject failed for PID {pid}.")
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(proc_handle))

    def spawn_managed(
        self,
        command: Sequence[str],
        label: str,
        env_overrides: dict[str, str] | None = None,
    ) -> ManagedProcessHandle:
        env = dict(os.environ)
        if env_overrides:
            env.update(env_overrides)
        proc = subprocess.Popen(  # noqa: S603
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        try:
            self._assign_pid_to_job(proc.pid)
        except Exception:
            proc.kill()
            proc.wait(timeout=3)
            raise
        self._managed[proc.pid] = proc
        return ManagedProcessHandle(
            process_id=proc.pid,
            ownership_mode=RuntimeOwnershipMode.MANAGED_LOCAL,
            label=label,
        )

    def register_external(self, process_id: int, label: str) -> ManagedProcessHandle:
        handle = ManagedProcessHandle(
            process_id=process_id,
            ownership_mode=RuntimeOwnershipMode.EXTERNAL_LOCAL,
            label=label,
        )
        self._external[process_id] = handle
        return handle

    def terminate_process(self, handle: ManagedProcessHandle, *, force_external_approved: bool = False) -> bool:
        """Terminate managed_local processes; refuse external_local unless explicitly approved (BR-AI-04)."""
        if handle.ownership_mode != RuntimeOwnershipMode.MANAGED_LOCAL:
            if not force_external_approved:
                return False
            try:
                p = psutil.Process(handle.process_id)
                p.terminate()
                p.wait(timeout=5.0)
                return True
            except psutil.NoSuchProcess:
                return False

        proc = self._managed.pop(handle.process_id, None)
        if proc is None:
            return False
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
        return True

    def is_alive(self, process_id: int) -> bool:
        proc = self._managed.get(process_id)
        if proc is not None:
            return proc.poll() is None
        try:
            p = psutil.Process(process_id)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def close_all_managed(self) -> int:
        """Close the Win32 Job Object and terminate all managed_local children (external_local untouched)."""
        closed = 0
        for pid in list(self._managed.keys()):
            proc = self._managed.pop(pid, None)
            if proc is not None:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=1.0)
                closed += 1

        if sys.platform == "win32" and self._job_handle is not None:
            kernel32 = ctypes.windll.kernel32
            kernel32.TerminateJobObject(ctypes.c_void_p(self._job_handle), 1)
            kernel32.CloseHandle(ctypes.c_void_p(self._job_handle))
            self._job_handle = None
        return closed
