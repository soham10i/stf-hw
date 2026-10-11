"""
DT-4a: the compiled PLC program, scan by scan, from Python - the I/O image by NAME (the GVL names of plc/GVL_IO.st and
the SIL axis variables of port.py R5).

    plc = PLC()                       # a private copy of libstf2plc.dylib: every instance has its own memory
    plc["tcTC1"] = 2100               # inputs (raw PLC units: 0.1 C, 0..32767 for 0..10 V ...)
    plc.scan()                        # one 10 ms task cycle
    plc["qE1T1"]                      # outputs
"""
import ctypes
import json
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out", "sil")
CT = {"BOOL": ctypes.c_uint8, "INT": ctypes.c_int16, "LREAL": ctypes.c_double, "UDINT": ctypes.c_uint32}


class PLC:
    def __init__(self, lib=None):
        src = lib or os.path.join(OUT, "libstf2plc.dylib")
        meta = json.load(open(os.path.join(os.path.dirname(src), "plc.json")))
        self._tmp = tempfile.mkdtemp(prefix="stf2plc_")
        copy = os.path.join(self._tmp, "libstf2plc.dylib")          # dlopen would share one image per path
        shutil.copy(src, copy)
        self.lib = ctypes.CDLL(copy)
        self.lib.plc_name.restype = ctypes.c_char_p
        self.lib.plc_type.restype = ctypes.c_char_p
        self.lib.plc_ptr.restype = ctypes.c_void_p
        adr = {}
        for i in range(self.lib.plc_count()):
            t = self.lib.plc_type(i).decode()
            adr[self.lib.plc_name(i).decode()] = ctypes.cast(self.lib.plc_ptr(i), ctypes.POINTER(CT[t]))
        self.var = {name: adr[d["address"]] for name, d in meta["io"].items()}
        self.meta = meta
        self.lib.plc_mon.restype = ctypes.c_double
        self.mon_index = {m: i for i, m in enumerate(meta["monitor"])}
        self.lib.plc_init()
        self.scans = 0

    def __getitem__(self, name):
        return self.var[name][0]

    def __setitem__(self, name, value):
        self.var[name][0] = value

    def mon(self, name):
        """A read-only monitor of the program's internal state (build.MONITOR), e.g. 'fbOven.aBroken[3]'."""
        return self.lib.plc_mon(self.mon_index[name])

    def power_cycle(self):
        """Off and on again: the program restarts from its initial values, except its RETAIN variables
        (plc.json "retain": FB_Oven's learned feed-forward, FB_Band's rows on the band), which keep their values."""
        n = self.lib.plc_retain_size()
        buf = (ctypes.c_ubyte * max(n, 1))()
        self.lib.plc_retain_save(buf)
        self.lib.plc_init()
        self.lib.plc_retain_load(buf)

    def scan(self, n=1):
        for _ in range(n):
            self.lib.plc_scan()
        self.scans += n

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
