import simpy
import simpy.rt  # Required for real-time synchronization
import random
import time
import json
import paho.mqtt.client as mqtt 

# --- 1. HARDWARE HEALTH & CONNECTION LAYER ---
# Updated based on "STF Problems in Hardware.xlsx" audit in Lab DC 1.07
HW_STATUS = {
    "M1_CONVEYOR": "BROKEN (23.6V - Terminal Fault)",
    "M2_HORIZONTAL": "FUNCTIONING (22.6V)",
    "M3_VERTICAL": "BROKEN (0V - Wiring Failure)",
    "M4_CANTILEVER": "BROKEN (Wiring Issue - Unreliable)",
    "SENSORS_I1_I4": "FUNCTIONING",
    "SENSORS_I5_I6": "BROKEN (Reference Switches Non-Functional)"
}

# --- 2. MQTT CONFIGURATION (Cyber Layer) ---
MQTT_BROKER = "broker.hivemq.com" 
TOPIC_COMMANDS = "stf/hrl/commands"
TOPIC_TELEMETRY = "stf/hrl/telemetry"

# --- 3. CALIBRATION (Kinematic Data Model) ---
MOTOR_RPM = 214 
PULSES_PER_REV = 75 
SEC_PER_PULSE = 60 / (MOTOR_RPM * PULSES_PER_REV) 

CALIBRATION = {
    "H_OFFSET": 200, "H_STEP": 250, 
    "V_OFFSET": 150, "V_STEP": 200, 
    "IDENT_TIME": 1.5
}

def print_progress_bar(grid, current_id):
    filled_slots = sum(slot is not None for row in grid.values() for slot in row)
    percent = int((filled_slots / 9) * 100)
    bar = "█" * (percent // 10) + "-" * (10 - (percent // 10))
    print(f"--- STATUS: Cookie {current_id} Stored ---")
    print(f"WAREHOUSE CAPACITY: |{bar}| {percent}% Full")
    print("-" * 40)

class HighBayEdgeController:
    def _init_(self, env):
        self.env = env
        self.conveyor = simpy.Resource(env, capacity=1)
        self.crane = simpy.Resource(env, capacity=1)
        self.cantilever = simpy.Resource(env, capacity=1)
        self.grid = {"Row_0": [None]*3, "Row_1": [None]*3, "Row_2": [None]*3}
        self.is_homed = False

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self.on_message
        self.client.on_connect = lambda client, userdata, flags, rc, props: print(">>> Connected to MQTT Broker!")
        self.client.connect(MQTT_BROKER)
        self.client.subscribe(TOPIC_COMMANDS)
        self.client.loop_start()

    def on_message(self, client, userdata, msg):
        cmd = msg.payload.decode().strip().lower()
        print(f"\n[REMOTE CMD RECEIVED]: {cmd}")
        if cmd == "startup":
            self.env.process(self.run_factory_flow())
        elif cmd.startswith("deliver"):
            try:
                cookie_type = cmd.split("_")[1].capitalize()
                self.env.process(self.retrieve_item(cookie_type))
            except IndexError:
                print("!!! ERROR: Invalid deliver command format.")

    def run_factory_flow(self):
        yield self.env.process(self.reference_run())
        yield self.env.process(factory_generator(self.env, self))

    def send_telemetry(self, status_msg):
        data = {
            "status": status_msg,
            "fullness": int((sum(s is not None for r in self.grid.values() for s in r)/9)*100),
            "hardware_health": HW_STATUS
        }
        self.client.publish(TOPIC_TELEMETRY, json.dumps(data))

    def reference_run(self): 
        print(f"[{self.env.now:.2f}s] INITIALIZING: Searching for Reference Switches I1/I4...")
        print(f" -> M2 (Horizontal): [{HW_STATUS['M2_HORIZONTAL']}]")
        print(f" -> M3 (Vertical): [{HW_STATUS['M3_VERTICAL']}]")
        # Simulating reference run duration as a Digital Shadow
        yield self.env.timeout(4.0) 
        self.is_homed = True 
        print(f"[{self.env.now:.2f}s] SUCCESS: Homing sequence complete (Virtual Calibration).")
        self.send_telemetry("Homed and Ready")

    def find_first_available_slot(self):
        for row_name in ["Row_0", "Row_1", "Row_2"]:
            if None in self.grid[row_name]:
                return row_name, self.grid[row_name].index(None)
        return None, None

    def store_cookie(self, cookie_id):
        if not self.is_homed: return

        print(f"[{self.env.now:.2f}s] DETECTED: Cookie {cookie_id} at Light Barrier I3")
        print(f" -> Conveyor M1: [{HW_STATUS['M1_CONVEYOR']}]")
        
        with self.conveyor.request() as req:
            yield req
            # Digital Shadow for Conveyor M1
            yield self.env.timeout(CALIBRATION["IDENT_TIME"])
            cookie_type = random.choice(["Cooked", "Uncooked"])
            print(f"[{self.env.now:.2f}s] SCANNING: Sensor A1/A2 identification: {cookie_type}")

        target_row, col_idx = self.find_first_available_slot()
        if target_row is None:
            print(f"!!! ALERT: WAREHOUSE FULL")
            return

        with self.crane.request() as req:
            yield req
            row_num = int(target_row[-1])
            print(f"[{self.env.now:.2f}s] TRAVELING to Row {row_num}, Col {col_idx}:")
            print(f" -> Motor M2 Status: {HW_STATUS['M2_HORIZONTAL']}")
            print(f" -> Motor M3 Status: {HW_STATUS['M3_VERTICAL']}")
            
            h_pulses = CALIBRATION["H_OFFSET"] + (col_idx * CALIBRATION["H_STEP"])
            v_pulses = CALIBRATION["V_OFFSET"] + (row_num * CALIBRATION["V_STEP"])
            
            # Using max pulses to simulate simultaneous axial movement (timed shadow)
            yield self.env.timeout(max(h_pulses, v_pulses) * SEC_PER_PULSE)
            
            with self.cantilever.request() as c_req:
                yield c_req
                print(f"[{self.env.now:.2f}s] ACTION: Motor M4 [{HW_STATUS['M4_CANTILEVER']}] extending...")
                print(f" -> Sensor I5/I6 Status: {HW_STATUS['SENSORS_I5_I6']} - Bypassing to Virtual Timed Loop")
                yield self.env.timeout(1.2) # Shadow timing for extension
                self.grid[target_row][col_idx] = cookie_type
                print(f"[{self.env.now:.2f}s] ACTION: Motor M4 [{HW_STATUS['M4_CANTILEVER']}] retracting...")
                yield self.env.timeout(1.2) # Shadow timing for retraction
                
                print_progress_bar(self.grid, cookie_id) 
                self.send_telemetry(f"Stored {cookie_type}")

    def retrieve_item(self, cookie_type):
        print(f"[{self.env.now:.2f}s] DISPATCH: Remote request to fetch {cookie_type}...")
        target_loc = None
        for row_name, slots in self.grid.items():
            if cookie_type in slots:
                target_loc = (row_name, slots.index(cookie_type))
                break
        
        if not target_loc:
            print(f"!!! ERROR: {cookie_type} not found in static inventory map.")
            return

        row_name, col_idx = target_loc
        with self.crane.request() as req:
            yield req
            yield self.env.process(self.move_to_slot_logic(int(row_name[-1]), col_idx))
            self.grid[row_name][col_idx] = None 
            print(f"[{self.env.now:.2f}s] SUCCESS: {cookie_type} dispatched from {row_name}, Slot {col_idx}.")
            self.send_telemetry(f"Dispatched {cookie_type}")

    def move_to_slot_logic(self, r, c):
        h = CALIBRATION["H_OFFSET"] + (c * CALIBRATION["H_STEP"])
        v = CALIBRATION["V_OFFSET"] + (r * CALIBRATION["V_STEP"])
        yield self.env.timeout(max(h, v) * SEC_PER_PULSE)

def factory_generator(env, hbw):
    for i in range(12):
        yield env.timeout(random.uniform(5, 8)) 
        env.process(hbw.store_cookie(i))

def keep_alive(env):
    while True:
        yield env.timeout(1)



env = simpy.rt.RealtimeEnvironment(initial_time=0, factor=1.0, strict=False)
env.process(keep_alive(env))
hbw = HighBayEdgeController(env)

print("=" * 60)
print("     STF EDGE CONTROLLER: Awaiting 'startup' via MQTT  ")
print("     Status: LAB DC 1.07 AUDIT APPLIED (REAL-TIME)     ")
print("=" * 60)

# Synchronized Real-time loop
while True:
    try:
        env.step()
    except simpy.core.EmptySchedule:
        time.sleep(0.01)
    except Exception:
        time.sleep(0.01)
        
        