"""Edge nodes that each break one Sparkplug rule: uns/check.py must catch every one."""
from uns import namespace as N
from uns.edge import Edge


class NamesInData(Edge):
    """EM1: DDATA and NDATA carry the metric names as well as the aliases."""

    def data(self, d):
        with self.lock:
            self.d = d
            if not self.born:
                if self.client is not None and self.host_online:
                    self.birth()
                return
            vals = self.values(d)
            for dev in (None, *N.DEVICES.values()):
                changed = [(m.name, m.alias, m.dtype, vals[(dev, m.name)], None) for m in self.devices[dev]
                           if vals[(dev, m.name)] != self.last.get((dev, m.name))]
                if changed:
                    self.publish("NDATA" if dev is None else "DDATA", dev, changed)
            self.last = vals


class SkipsSeq(Edge):
    """EM2: one sequence number is skipped (as if a message were lost)."""

    count = 0

    def _seq(self):
        self.count += 1
        if self.count == 40:
            self.seq = (self.seq + 1) % 256
        return super()._seq()


class WrongBdSeq(Edge):
    """EM3: the NBIRTH's bdSeq is not the one in the CONNECT's will."""

    def birth_metrics(self, device, vals):
        ms = super().birth_metrics(device, vals)
        return [(n, a, t, (v + 1) % 256 if n == N.BDSEQ else v, p) for n, a, t, v, p in ms]


class NoHostWait(Edge):
    """EM4: births as soon as it is connected, without the primary host's STATE."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.wait_for_host = False


class RepeatsValues(Edge):
    """EM5: report by exception broken - a DDATA repeats a value that did not change."""

    def data(self, d):
        super().data(d)
        with self.lock:
            if self.born and self.seq % 25 == 0:
                m = self.devices["HBW"][0]
                self.publish("DDATA", "HBW", [(None, m.alias, m.dtype, self.last[("HBW", m.name)], None)])


EDGES = {"EM1": NamesInData, "EM2": SkipsSeq, "EM3": WrongBdSeq, "EM4": NoHostWait, "EM5": RepeatsValues}
