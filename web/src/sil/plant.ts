// Upgrade 13: the plant the compiled PLC program runs against.
//
// It sees only the PLC's outputs (%QX) and answers only with inputs (%IX, the
// RFID tag and colour reading in %IW, encoder positions in %ID). Every number
// comes from public/sil/plant.json, which stf-cad/hbw/sil/plant.py takes from
// the same models as the CAD and the proofs. Material is tracked: moulds with
// their RFID tags, cookies with their flavour and whether they are baked, so a
// light barrier, the vacuum switch, the RFID heads and the colour sensor
// report what is physically there, not what the program expects.
//
// The same file runs the proof (sil/run.py, under Node) and the public twin.

/* eslint-disable @typescript-eslint/no-explicit-any */
export type PlantParams = any;
export type IoEntry = { name: string; bit?: number; word?: number };
export type IoMap = { ix: IoEntry[]; qx: IoEntry[]; iw: IoEntry[]; id: IoEntry[]; mw: IoEntry[] };

export type Mould = { id: number; cookie: number };            // cookie 0 = empty
export type PlantEvent = { t: number; text: string };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export class Plant {
  t = 0;
  readonly p: PlantParams;
  // ---- HBW
  x: number; z: number; y: number;                 // travel, lift, Ausleger
  fork: Mould | null = null;
  slots: Record<string, Mould | null> = {};
  belt: { m: Mould; y: number }[] = [];
  rfDwell = new Map<number, [number, number]>();   // mould -> time in RP1 / RP2 window
  // ---- VGR
  sw: number; rr: number; pz: number;
  cup = 0;                                         // the cookie held by vacuum
  vacT = 0;                                        // time the vacuum has been on (or off) in this state
  // ---- oven
  slider: number; door: number; sauger: number; lower: number; turn: number; push: number;
  tray = 0; saugerCup = 0; nest = 0; ovenBelt: { c: number; y: number } | null = null;
  bakeAcc = new Map<number, number>();
  baked = new Map<number, boolean>();
  // ---- sorting
  line: { c: number; x: number }[] = [];
  travel = 0;                                      // sorting belt travel, for the pulse counter
  ejT = [0, 0, 0];
  barT = [0, 0, 0];
  bays: number[][];
  // ---- bookkeeping
  flags: string[] = [];
  events: PlantEvent[] = [];
  private qi: Record<string, number> = {};
  private ii: Record<string, number> = {};
  private wi: Record<string, number> = {};
  private di: Record<string, number> = {};

  constructor(p: PlantParams, io: IoMap) {
    this.p = p;
    io.qx.forEach((e) => (this.qi[e.name] = e.bit!));
    io.ix.forEach((e) => (this.ii[e.name] = e.bit!));
    io.iw.forEach((e) => (this.wi[e.name] = e.word!));
    io.id.forEach((e) => (this.di[e.name] = e.word!));
    const h = p.hbw.init, v = p.vgr.init, o = p.oven.init;
    this.x = h.travel; this.z = h.lift; this.y = h.fork;
    this.sw = v.swivel; this.rr = v.reach; this.pz = v.plunge;
    this.slider = o.slider; this.door = o.door; this.sauger = o.sauger; this.lower = o.lower;
    this.turn = o.turn; this.push = o.push;
    for (const s of p.hbw.slots) {
      const m = p.slots0[s];
      this.slots[s] = m ? { id: m.mould, cookie: m.cookie } : null;
    }
    this.bays = p.bays0.map((b: number[]) => [...b]);
    for (const [k, c] of Object.entries<any>(p.cookies)) this.baked.set(Number(k), c.baked);
  }

  private log(text: string) { this.events.push({ t: this.t, text }); }
  private flag(text: string) {
    if (!this.flags.includes(text)) { this.flags.push(text); this.log(`PLANT: ${text}`); }
  }
  cookieName(c: number) { return this.p.cookies[c]?.id ?? `#${c}`; }
  mouldName(m: number) { return this.p.moulds[m] ?? `M${m}`; }

  // ------------------------------------------------------------------ inputs
  /** Write the plant's state into the PLC's input image. */
  writeInputs(ix: Uint8Array, iw: Int16Array, id: Float32Array) {
    const set = (n: string, v: boolean) => { const b = this.ii[n]; if (b !== undefined) ix[b] = v ? 1 : 0; };
    const P = this.p, H = P.hbw, B = H.belt, O = P.oven, S = P.sorting;
    // HBW
    set("hbw_I1", this.x >= H.cv_x - 0.5);
    set("hbw_I4", this.z <= 0.5);
    set("hbw_I5", this.y >= H.fork_out - 0.5);
    set("hbw_I6", this.y <= 0.5);
    set("hbw_I2", this.belt.some((b) => b.y <= B.crane_end + 0.5));
    set("hbw_I3", this.belt.some((b) => b.y >= B.vgr_end - 0.5));
    const rf1 = this.belt.find((b) => (this.rfDwell.get(b.m.id)?.[0] ?? 0) >= B.rfid_s);
    const rf2 = this.belt.find((b) => (this.rfDwell.get(b.m.id)?.[1] ?? 0) >= B.rfid_s);
    set("hbw_RF1_Valid", !!rf1);
    set("hbw_RF2_Valid", !!rf2);
    iw[this.wi["hbw_RF2_Tag"]] = rf2 ? rf2.m.id : 0;
    id[this.di["hbw_PosTravel"]] = this.x;
    id[this.di["hbw_PosLift"]] = this.z;
    // VGR
    set("vgr_I1", this.pz >= P.vgr.transit - 0.5);
    set("vgr_I2", this.rr <= 0.5);
    set("vgr_I3", this.sw <= 0.5);
    set("vgr_I4", this.cup !== 0);
    id[this.di["vgr_PosPlunge"]] = this.pz;
    id[this.di["vgr_PosReach"]] = this.rr;
    id[this.di["vgr_PosSwivel"]] = this.sw;
    // oven
    set("oven_I1", this.turn >= O.turn.sauger - 0.5);
    set("oven_I4", Math.abs(this.turn - O.turn.saege) <= 0.5);
    set("oven_I2", this.turn <= O.turn.band + 0.5);
    set("oven_I5", this.sauger >= O.sauger.tt - 0.5);
    set("oven_I8", this.sauger <= O.sauger.oven + 0.5);
    set("oven_I6", this.slider <= O.slider.in + 0.5);
    set("oven_I7", this.slider >= O.slider.out - 0.5);
    set("oven_I10", this.door >= 0.99);
    set("oven_I11", this.door <= 0.01);
    set("oven_I12", this.lower >= 0.99);
    set("oven_I13", this.lower <= 0.01);
    set("oven_I14", this.push >= 0.99);
    set("oven_I15", this.push <= 0.01);
    set("oven_I3", !!this.ovenBelt && this.ovenBelt.y >= O.belt.end - 0.5);
    // sorting
    set("sorting_I1", Math.floor(this.travel / (S.pulse_mm / 2)) % 2 === 0);
    set("sorting_I2", this.line.some((l) => Math.abs(l.x - S.inlet_x) <= 10));
    set("sorting_I3", this.line.some((l) => l.x >= S.after_x && l.x <= S.after_x + 15));
    set("sorting_I5", this.barT[0] > 0);
    set("sorting_I6", this.barT[1] > 0);
    set("sorting_I7", this.barT[2] > 0);
    const under = this.line.find((l) => Math.abs(l.x - S.sensor_x) <= S.sensor_window);
    iw[this.wi["sorting_A4"]] = under ? (this.baked.get(under.c) ? P.cookies[under.c].mV : S.raw_mv) : S.belt_mv;
    set("cell_SafetyOK", true);
  }

  // ------------------------------------------------------------------ physics
  /** Advance dt seconds with the PLC's outputs applied. */
  step(qx: Uint8Array, dt: number) {
    const q = (n: string) => qx[this.qi[n]] === 1;
    const dir = (neg: string, pos: string, what: string) => {
      const a = q(neg), b = q(pos);
      if (a && b) this.flag(`${what}: driven both ways at once`);
      return a && !b ? -1 : b && !a ? 1 : 0;
    };
    this.t += dt;
    this.hbw(dir, dt);
    this.vgr(q, dir, dt);
    this.oven(q, dir, dt);
    this.sorting(q, dt);
  }

  private hbw(dir: (a: string, b: string, w: string) => number, dt: number) {
    const H = this.p.hbw, B = H.belt;
    const v = H.v * dt;
    const dx = dir("hbw_Q3", "hbw_Q4", "crane travel") * v;
    const dz = dir("hbw_Q5", "hbw_Q6", "crane lift") * v;
    const dy = dir("hbw_Q8", "hbw_Q7", "Ausleger") * v;
    if (dx !== 0 && this.y > 2) this.flag("the crane travelled with the Ausleger out");
    const z0 = this.z;
    this.x = clamp(this.x + dx, 0, H.cv_x);
    this.z = clamp(this.z + dz, 0, 400);
    this.y = clamp(this.y + dy, 0, H.fork_out);
    // a mould changes hands when the lift passes the shelf (or the belt) with the Ausleger out
    if (dz !== 0 && this.y >= H.fork_out - 1) {
      const cross = (lvl: number) => (z0 < lvl && this.z >= lvl ? 1 : z0 >= lvl && this.z < lvl ? -1 : 0);
      if (Math.abs(this.x - H.cv_x) <= 2) {
        const c = cross(H.belt_z);
        const at = this.belt.find((b) => Math.abs(b.y - B.crane_end) <= 2);
        if (c > 0 && !this.fork && at) {
          this.fork = at.m; this.belt = this.belt.filter((b) => b !== at);
          this.log(`crane picks ${this.mouldName(at.m.id)} off the belt`);
        } else if (c < 0 && this.fork) {
          if (at) this.flag("the crane set a mould down onto another on the belt");
          else { this.belt.push({ m: this.fork, y: B.crane_end }); this.log(`crane sets ${this.mouldName(this.fork.id)} on the belt`); this.fork = null; }
        }
      } else {
        const col = H.cols.findIndex((cx: number) => Math.abs(this.x - cx) <= 2);
        if (col >= 0) {
          for (const [row, rz] of Object.entries<number>(H.rows)) {
            const c = cross(rz - 10);
            if (!c) continue;
            const s = `${row}${col + 1}`;
            if (c > 0 && !this.fork && this.slots[s]) {
              this.fork = this.slots[s]; this.slots[s] = null;
              this.log(`crane takes ${this.mouldName(this.fork!.id)} out of ${s}`);
            } else if (c < 0 && this.fork) {
              if (this.slots[s]) this.flag(`the crane set a mould down onto ${s}, which was full`);
              else { this.slots[s] = this.fork; this.log(`crane stores ${this.mouldName(this.fork.id)} in ${s}`); this.fork = null; }
            }
          }
        } else if (dz !== 0 && this.y > 2) this.flag("the lift moved with the Ausleger out, away from a rack column");
      }
    }
    // the belt: moulds ride it between the two end stops
    const bd = dir("hbw_Q2", "hbw_Q1", "HBW belt") * B.v * dt;
    for (const b of this.belt) {
      b.y = clamp(b.y + bd, B.crane_end, B.vgr_end);
      const d = this.rfDwell.get(b.m.id) ?? [0, 0];
      d[0] = Math.abs(b.y - B.rp1) <= B.rp_window ? d[0] + dt : 0;
      d[1] = Math.abs(b.y - B.rp2) <= B.rp_window ? d[1] + dt : 0;
      this.rfDwell.set(b.m.id, d);
    }
  }

  /** The station the cup is over and touching, if any. */
  private vgrStation(): string | null {
    const V = this.p.vgr;
    for (const [name, s] of Object.entries<any>(V.stations)) {
      if (Math.abs(this.sw - s.swivel) <= V.seal.swivel && Math.abs(this.rr - s.reach) <= V.seal.reach
        && this.pz <= s.contact + V.seal.plunge) return name;
    }
    return null;
  }

  private stationCookie(st: string): number {
    const H = this.p.hbw;
    if (st === "belt") { const b = this.belt.find((x) => x.y >= H.belt.vgr_end - 0.5); return b ? b.m.cookie : 0; }
    if (st === "oven") return this.slider >= this.p.oven.slider.out - 0.5 ? this.tray : 0;
    if (st.startsWith("bay_")) { const i = this.p.sorting.bays.indexOf(st.slice(4)); return this.bays[i]?.[0] ?? 0; }
    return 0;
  }

  private takeFrom(st: string) {
    const H = this.p.hbw;
    if (st === "belt") { const b = this.belt.find((x) => x.y >= H.belt.vgr_end - 0.5)!; b.m.cookie = 0; }
    else if (st === "oven") this.tray = 0;
    else if (st.startsWith("bay_")) this.bays[this.p.sorting.bays.indexOf(st.slice(4))].shift();
  }

  private putInto(st: string, c: number): boolean {
    const H = this.p.hbw;
    if (st === "belt") {
      const b = this.belt.find((x) => x.y >= H.belt.vgr_end - 0.5);
      if (!b || b.m.cookie) return false;
      b.m.cookie = c; return true;
    }
    if (st === "oven") {
      if (this.slider < this.p.oven.slider.out - 0.5 || this.tray) return false;
      this.tray = c; return true;
    }
    return false;
  }

  private vgr(q: (n: string) => boolean, dir: (a: string, b: string, w: string) => number, dt: number) {
    const V = this.p.vgr;
    this.pz = clamp(this.pz + dir("vgr_Q2", "vgr_Q1", "VGR plunge") * V.v_mm * dt, V.plunge[0], V.plunge[1]);
    this.rr = clamp(this.rr + dir("vgr_Q3", "vgr_Q4", "VGR reach") * V.v_mm * dt, V.reach[0], V.reach[1]);
    this.sw = clamp(this.sw + dir("vgr_Q6", "vgr_Q5", "VGR swivel") * V.v_deg * dt, -180, 180);
    const st = this.vgrStation();
    if (st && this.pz < V.stations[st].contact - V.overtravel - 1) this.flag(`the VGR drove its cup into ${st}`);
    const vac = q("vgr_Q8");
    if (vac && !this.cup) {
      const c = st ? this.stationCookie(st) : 0;
      this.vacT = c ? this.vacT + dt : 0;
      if (c && this.vacT >= V.vac_on) {
        this.takeFrom(st!); this.cup = c; this.vacT = 0;
        this.log(`VGR picks ${this.cookieName(c)} at ${st}`);
      }
    } else if (!vac && this.cup) {
      this.vacT += dt;
      if (this.vacT >= V.vac_off) {
        const c = this.cup;
        this.cup = 0; this.vacT = 0;
        if (st && this.putInto(st, c)) this.log(`VGR sets ${this.cookieName(c)} down at ${st}`);
        else this.flag(`the VGR dropped ${this.cookieName(c)} ${st ? `at ${st}` : "in mid-air"}`);
      }
    } else this.vacT = 0;
  }

  private oven(q: (n: string) => boolean, dir: (a: string, b: string, w: string) => number, dt: number) {
    const O = this.p.oven;
    const ds = dir("oven_Q5", "oven_Q6", "Ofenschieber");
    if (ds !== 0 && this.door < 0.99) this.flag("the Ofenschieber moved while the door was not open");
    this.slider = clamp(this.slider + ds * O.slider.v * dt, O.slider.in, O.slider.out);
    this.door = clamp(this.door + (q("oven_Q13") ? 1 : -1) * dt / O.door_s, 0, 1);
    this.sauger = clamp(this.sauger + dir("oven_Q7", "oven_Q8", "Sauger") * O.sauger.v * dt, O.sauger.oven, O.sauger.tt);
    this.lower = clamp(this.lower + (q("oven_Q12") ? 1 : -1) * dt / O.lower_s, 0, 1);
    this.turn = clamp(this.turn + dir("oven_Q1", "oven_Q2", "Drehtisch") * O.turn.v * dt, O.turn.band, O.turn.sauger);
    this.push = clamp(this.push + (q("oven_Q14") ? 1 : -1) * dt / O.push_s, 0, 1);
    // baking: the cookie inside, the door shut, the lamp on
    if (this.tray && q("oven_Q9") && this.slider <= O.slider.in + 0.5 && this.door <= 0.01) {
      const a = (this.bakeAcc.get(this.tray) ?? 0) + dt;
      this.bakeAcc.set(this.tray, a);
      if (a >= O.bake_s - 2 * dt && !this.baked.get(this.tray)) {
        this.baked.set(this.tray, true); this.log(`${this.cookieName(this.tray)} is baked`);
      }
    }
    // the Sauger: picks the tray's cookie at the oven, lays it in the Drehtisch's nest
    const atOven = this.sauger <= O.sauger.oven + 0.5, atTt = this.sauger >= O.sauger.tt - 0.5;
    if (q("oven_Q11")) {
      if (!this.saugerCup && this.lower >= 0.99 && atOven && this.tray && this.slider >= O.slider.out - 0.5) {
        this.saugerCup = this.tray; this.tray = 0; this.log(`oven Sauger lifts ${this.cookieName(this.saugerCup)} off the tray`);
      }
    } else if (this.saugerCup) {
      if (atTt && this.turn >= O.turn.sauger - 0.5 && !this.nest) {
        this.nest = this.saugerCup; this.log(`oven Sauger lays ${this.cookieName(this.nest)} in the Drehtisch`);
      } else this.flag(`the oven Sauger dropped ${this.cookieName(this.saugerCup)}`);
      this.saugerCup = 0;
    }
    // the Auswerfer pushes the nest's cookie onto the oven belt
    if (this.push >= 0.99 && this.nest && this.turn <= O.turn.band + 0.5 && !this.ovenBelt) {
      this.ovenBelt = { c: this.nest, y: O.belt.start }; this.nest = 0;
      this.log(`Auswerfer pushes ${this.cookieName(this.ovenBelt.c)} onto the oven belt`);
    }
    if (this.ovenBelt && q("oven_Q3")) this.ovenBelt.y = Math.min(O.belt.end, this.ovenBelt.y + O.belt.v * dt);
  }

  private sorting(q: (n: string) => boolean, dt: number) {
    const S = this.p.sorting, O = this.p.oven;
    if (q("sorting_Q1")) {
      // the sorting belt drags the cookie at the oven belt's end across the corner
      if (this.ovenBelt && this.ovenBelt.y >= O.belt.end - 0.5) {
        this.line.push({ c: this.ovenBelt.c, x: S.inlet_x }); this.ovenBelt = null;
      }
      this.travel += S.v * dt;
      for (const l of this.line) l.x += S.v * dt;
    }
    for (let i = 0; i < 3; i++) {
      this.barT[i] = Math.max(0, this.barT[i] - dt);
      if (q(`sorting_Q${3 + i}`)) {
        this.ejT[i] += dt;
        const hit = this.line.find((l) => Math.abs(l.x - S.eject_x[i]) <= S.eject_window);
        if (hit && this.ejT[i] >= S.eject_push_s) {
          this.line = this.line.filter((l) => l !== hit);
          if (this.bays[i].length >= S.bay_cap) this.flag(`bay ${S.bays[i]} overflowed`);
          this.bays[i].push(hit.c); this.barT[i] = S.barrier_s;
          this.log(`${this.cookieName(hit.c)} ejected into bay ${S.bays[i]}`);
        }
      } else this.ejT[i] = 0;
    }
    const lost = this.line.find((l) => l.x > S.eject_x[2] + 60);
    if (lost) this.flag(`${this.cookieName(lost.c)} ran off the end of the sorting belt`);
  }
}
