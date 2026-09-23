(*
  ControlLab bulk-material line -- the section 6.2 Auto sequence in IEC 61131-3
  Structured Text, for OpenPLC Runtime (docs/CONTROL-LAB.md, Phase 7 step 4).

  A port of services/control/line_controller.py and its helpers
  (motor_control.py, gate_control.py, alarms.py, hopper_hysteresis.py),
  scan for scan: the same scan order (device supervision, alarm scan,
  acknowledge, e-stop, state machine), the same permissives and trips, the
  same fault reasons (published as codes), the same alarm first-out rules,
  and the same proof windows -- counted in task scans exactly as the Python
  counts dt, so with the 100 ms task below the two behave alike.

  ControlLab is a Modbus TCP remote-I/O device to this program. Configure
  it in OpenPLC under Slave Devices with the five ranges from
  docs/MODBUS-MAP.md ("Controller view"):
      Discrete inputs      start 0    size 12   -> %IX100.0 .. %IX101.3
      Coils                start 0    size 3    -> %QX100.0 .. %QX100.2
      Input registers      start 0    size 2    -> %IW100 .. %IW101
      Holding - read       start 100  size 1    -> %IW102 (after the input registers)
      Holding - write      start 0    size 8    -> %QW100 .. %QW107

  Timings match ControlLab's test rig (services/testing/rig.py), so this
  program and the reference controller answer the same scenarios alike:
  conveyor proof 1.0 s, motor start proof 1.0 s, gate travel 2.0 s,
  purge 2.0 s, restart feeding below 60 % hopper level.
*)

PROGRAM controllab_line
  VAR
    (* ---- field inputs (discrete inputs 0-11) ---- *)
    LSL_101 AT %IX100.0 : BOOL;       (* bin low *)
    ZSO_102 AT %IX100.1 : BOOL;       (* gate open limit *)
    ZSC_102 AT %IX100.2 : BOOL;       (* gate closed limit *)
    M103_RUNNING AT %IX100.3 : BOOL;  (* feeder running (VFD) *)
    M103_FAULT AT %IX100.4 : BOOL;    (* feeder VFD fault *)
    M104_RUNNING AT %IX100.5 : BOOL;  (* conveyor running (contactor aux) *)
    M104_OL AT %IX100.6 : BOOL;       (* conveyor overload *)
    ZSS_104 AT %IX100.7 : BOOL;       (* conveyor motion switch *)
    LSH_105 AT %IX101.0 : BOOL;       (* hopper high *)
    LSHH_105 AT %IX101.1 : BOOL;      (* hopper high-high *)
    ES_001 AT %IX101.2 : BOOL;        (* e-stop healthy, fail-safe *)
    LSH_103 AT %IX101.3 : BOOL;       (* feeder discharge chute plugged: a jam *)

    (* ---- analog inputs (input registers 0-1) and the HMI request word (holding 100) ---- *)
    LT_101 AT %IW100 : INT;           (* bin level, % x100 *)
    WT_105 AT %IW101 : INT;           (* hopper weight, kg x10 *)
    HMI_REQUEST AT %IW102 : WORD;     (* bit 0 start, 1 stop, 2 reset, 3 acknowledge *)

    (* ---- field outputs (coils 0-2) ---- *)
    XV102_CMD_OPEN AT %QX100.0 : BOOL;
    M103_RUN AT %QX100.1 : BOOL;
    M104_RUN AT %QX100.2 : BOOL;

    (* ---- the holding write range 0-6: analog output, status, HMI ack ---- *)
    SC_103 AT %QW100 : INT;           (* feeder speed reference, % x100 *)
    ST_LINE_STATE AT %QW101 : INT;    (* 0 idle 1 starting 2 running 3 stopping 4 faulted 5 estopped *)
    ST_FAULT_REASON AT %QW102 : INT;  (* controller_status.FAULT_REASONS code *)
    ST_ALARMS_ACTIVE AT %QW103 : WORD;
    ST_ALARMS_UNACKED AT %QW104 : WORD;
    ST_FIRST_OUT AT %QW105 : INT;     (* 1 + alarm bit, 0 = none *)
    HMI_ACK AT %QW106 : WORD;
    ST_START_INHIBIT AT %QW107 : WORD; (* why the last start was refused: 1 bin low, 2 hopper HH,
                                          4 unacked alarm, 8 e-stop, 16 faulted; 0 = none *)
  END_VAR

  (* IEC 61131-3: a VAR block holds either located variables or ordinary
     ones, never both -- hence the second block. *)
  VAR
    (* ---- state ---- *)
    state : INT := 0;                 (* codes as ST_LINE_STATE *)
    start_step : INT := 0;            (* 0 conveyor, 1 gate, 2 feeder *)
    fault_reason : INT := 0;
    step_scans : INT := 0;
    purge_scans : INT := 0;
    feed_demand : BOOL := TRUE;

    (* one-shot operator requests, consumed by this scan *)
    start_req : BOOL;
    stop_req : BOOL;
    reset_req : BOOL;
    ack_req : BOOL;
    ack_bits : WORD := 16#0000;
    start_inhibit : WORD := 16#0000;   (* outcome of the most recent start request -- StartInhibit *)

    (* device supervision -- MotorControl / GateControl *)
    conv_last_cmd : BOOL := FALSE;
    conv_proof_scans : INT := 0;
    conv_proof_fault : BOOL := FALSE;
    feed_last_cmd : BOOL := FALSE;
    feed_proof_scans : INT := 0;
    feed_proof_fault : BOOL := FALSE;
    gate_last_cmd : BOOL := FALSE;
    gate_scans : INT := 0;
    gate_travel_fault : BOOL := FALSE;

    (* alarms, in controller_status.ALARMS bit order *)
    alarm_cond : ARRAY[0..9] OF BOOL;
    alarm_active : ARRAY[0..9] OF BOOL;
    alarm_unacked : ARRAY[0..9] OF BOOL;
    first_out_holder : INT := 0;      (* 1-based, 0 = none *)
    was_active : BOOL;
    unacked_trip : BOOL;
    conveyor_confirmed : BOOL;
    trip : INT;
    i : INT;
    bit : WORD;
  END_VAR

  VAR CONSTANT
    LIM_CONV_PROOF : INT := 10;     (* 1.0 s line-level conveyor proof *)
    LIM_MOTOR_PROOF : INT := 10;    (* 1.0 s MotorControl start proof *)
    LIM_GATE_TRAVEL : INT := 20;    (* 2.0 s GateControl travel timeout *)
    LIM_PURGE : INT := 20;          (* 2.0 s belt purge on stop *)
    LIM_RESTART_RAW : INT := 12000; (* 60 % of 2000 kg, in WT-105 raw (kg x10) *)
    LIM_FEED_SPEED : INT := 10000;    (* 100.00 % *)
  END_VAR

  (* ================= HMI request/acknowledge (4-phase) ================= *)
  start_req := FALSE; stop_req := FALSE; reset_req := FALSE; ack_req := FALSE;
  FOR i := 0 TO 3 DO
    bit := SHL(IN := WORD#1, N := i);
    IF (HMI_REQUEST AND bit) <> 0 AND (ack_bits AND bit) = 0 THEN
      ack_bits := ack_bits OR bit;                (* phase 2: take it, acknowledge *)
      CASE i OF
        0: start_req := TRUE;
        1: stop_req := TRUE;
        2: reset_req := TRUE;
        3: ack_req := TRUE;
      END_CASE;
    ELSIF (HMI_REQUEST AND bit) = 0 AND (ack_bits AND bit) <> 0 THEN
      ack_bits := ack_bits AND NOT bit;           (* phase 4: request dropped, release *)
    END_IF;
  END_FOR;

  (* ================= device supervision (MotorControl, GateControl) ================= *)
  (* each reads the command it wrote on the previous scan, as the Python reads the I/O image *)
  IF M104_RUN <> conv_last_cmd THEN conv_proof_scans := 0; conv_proof_fault := FALSE; conv_last_cmd := M104_RUN; END_IF;
  IF NOT M104_RUN OR M104_RUNNING THEN conv_proof_scans := 0;
  ELSE
    conv_proof_scans := conv_proof_scans + 1;
    IF conv_proof_scans >= LIM_MOTOR_PROOF THEN conv_proof_fault := TRUE; END_IF;
  END_IF;

  IF M103_RUN <> feed_last_cmd THEN feed_proof_scans := 0; feed_proof_fault := FALSE; feed_last_cmd := M103_RUN; END_IF;
  IF NOT M103_RUN OR M103_RUNNING THEN feed_proof_scans := 0;
  ELSE
    feed_proof_scans := feed_proof_scans + 1;
    IF feed_proof_scans >= LIM_MOTOR_PROOF THEN feed_proof_fault := TRUE; END_IF;
  END_IF;

  IF XV102_CMD_OPEN <> gate_last_cmd THEN gate_scans := 0; gate_travel_fault := FALSE; gate_last_cmd := XV102_CMD_OPEN; END_IF;
  IF (XV102_CMD_OPEN AND ZSO_102) OR (NOT XV102_CMD_OPEN AND ZSC_102) THEN gate_scans := 0;
  ELSE
    gate_scans := gate_scans + 1;
    IF gate_scans >= LIM_GATE_TRAVEL THEN gate_travel_fault := TRUE; END_IF;
  END_IF;

  conveyor_confirmed := M104_RUNNING AND ZSS_104;

  (* ================= alarms (AlarmManager.scan / acknowledge) ================= *)
  alarm_cond[0] := NOT ES_001;                  (* ES-001.TRIP *)
  alarm_cond[1] := LSL_101;                     (* LSL-101.LOW (warning) *)
  alarm_cond[2] := gate_travel_fault;           (* XV-102.TRAVEL_FAULT *)
  alarm_cond[3] := M103_FAULT;                  (* M-103.FAULT *)
  alarm_cond[4] := feed_proof_fault;            (* M-103.START_PROOF *)
  alarm_cond[5] := M104_OL;                     (* M-104.OL *)
  alarm_cond[6] := M104_RUNNING AND NOT ZSS_104;  (* ZSS-104.LOST *)
  alarm_cond[7] := conv_proof_fault;            (* M-104.START_PROOF *)
  alarm_cond[8] := LSHH_105;                    (* WT-105.HIGH_HIGH *)
  alarm_cond[9] := LSH_103;                     (* LSH-103.JAM *)

  FOR i := 0 TO 9 DO
    was_active := alarm_active[i];
    alarm_active[i] := alarm_cond[i];
    IF alarm_active[i] AND NOT was_active THEN
      alarm_unacked[i] := TRUE;
      IF first_out_holder = 0 THEN first_out_holder := i + 1; END_IF;
    END_IF;
    IF NOT alarm_active[i] AND NOT alarm_unacked[i] AND first_out_holder = i + 1 THEN first_out_holder := 0; END_IF;
  END_FOR;

  IF ack_req THEN
    FOR i := 0 TO 9 DO
      alarm_unacked[i] := FALSE;
      IF NOT alarm_active[i] AND first_out_holder = i + 1 THEN first_out_holder := 0; END_IF;
    END_FOR;
  END_IF;

  unacked_trip := FALSE;
  FOR i := 0 TO 9 DO
    IF i <> 1 AND alarm_unacked[i] THEN unacked_trip := TRUE; END_IF;   (* bit 1 is the only warning *)
  END_FOR;

  (* ================= e-stop overrides every state ================= *)
  IF NOT ES_001 AND state <> 5 THEN
    M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
    state := 5; fault_reason := 1; start_step := 0;
  END_IF;

  (* ================= the line state machine ================= *)
  CASE state OF
    0: (* IDLE -- off, continuously enforced *)
      M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
      IF start_req THEN
        start_inhibit := 16#0000;
        IF LSHH_105 THEN start_inhibit := start_inhibit OR 16#0002; END_IF;
        IF LSL_101 THEN start_inhibit := start_inhibit OR 16#0001; END_IF;
        IF unacked_trip THEN start_inhibit := start_inhibit OR 16#0004; END_IF;
        IF start_inhibit = 0 THEN
          state := 1; start_step := 0; step_scans := 0;
          M104_RUN := TRUE;                                        (* downstream first *)
        END_IF;
      END_IF;

    1: (* STARTING *)
      trip := 0;
      IF LSHH_105 THEN trip := 2;
      ELSIF M104_OL THEN trip := 4;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;
      ELSIF conv_proof_fault THEN trip := 6;
      ELSIF feed_proof_fault THEN trip := 5;
      ELSIF gate_travel_fault THEN trip := 7;
      END_IF;
      IF trip <> 0 THEN
        M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
        state := 4; fault_reason := trip; start_step := 0;
      ELSIF stop_req THEN
        state := 3; M103_RUN := FALSE; XV102_CMD_OPEN := FALSE; purge_scans := 0;
      ELSIF start_step = 0 THEN
        step_scans := step_scans + 1;
        IF conveyor_confirmed THEN
          start_step := 1; step_scans := 0; XV102_CMD_OPEN := TRUE;
        ELSIF step_scans >= LIM_CONV_PROOF THEN
          M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
          state := 4; fault_reason := 6; start_step := 0;
        END_IF;
      ELSIF start_step = 1 THEN
        IF ZSO_102 THEN
          start_step := 2; step_scans := 0; M103_RUN := TRUE; SC_103 := LIM_FEED_SPEED;
        END_IF;
      ELSIF start_step = 2 THEN
        IF M103_RUNNING THEN state := 2; start_step := 0; END_IF;
      END_IF;

    2: (* RUNNING *)
      trip := 0;
      IF LSHH_105 THEN trip := 2;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;                         (* the drive still reports running *)
      ELSIF M104_OL THEN trip := 4;
      ELSIF NOT conveyor_confirmed THEN trip := 8;
      ELSIF gate_travel_fault THEN trip := 9;
      END_IF;
      IF trip <> 0 THEN
        M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
        state := 4; fault_reason := trip;
      ELSIF stop_req THEN
        state := 3; M103_RUN := FALSE; XV102_CMD_OPEN := FALSE; purge_scans := 0;
      ELSE
        (* hopper hysteresis: stop feeding at LSH, resume below 60 % *)
        IF LSH_105 THEN feed_demand := FALSE;
        ELSIF WT_105 < LIM_RESTART_RAW THEN feed_demand := TRUE;
        END_IF;
        M103_RUN := feed_demand;
        IF feed_demand THEN SC_103 := LIM_FEED_SPEED; END_IF;
      END_IF;

    3: (* STOPPING -- upstream first, conveyor purges the belt *)
      trip := 0;
      IF LSHH_105 THEN trip := 2;
      ELSIF M104_OL THEN trip := 4;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;
      ELSIF gate_travel_fault THEN trip := 9;
      END_IF;
      IF trip <> 0 THEN
        M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
        state := 4; fault_reason := trip;
      ELSE
        purge_scans := purge_scans + 1;
        IF purge_scans >= LIM_PURGE THEN
          M104_RUN := FALSE; state := 0; purge_scans := 0;
        END_IF;
      END_IF;

    4: (* FAULTED -- off; reset only once the pass-through causes have cleared *)
      M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
      IF start_req THEN start_inhibit := 16#0010; END_IF;          (* refused, as always; now reported *)
      IF reset_req AND NOT LSHH_105 AND NOT M104_OL AND NOT M103_FAULT AND NOT LSH_103 THEN
        conv_proof_fault := FALSE; conv_proof_scans := 0;
        feed_proof_fault := FALSE; feed_proof_scans := 0;
        gate_travel_fault := FALSE; gate_scans := 0;
        state := 0; fault_reason := 0;
      END_IF;

    5: (* ESTOPPED -- off; reset once the e-stop is healthy again *)
      M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE;
      IF start_req THEN start_inhibit := 16#0008; END_IF;          (* refused, as always; now reported *)
      IF ES_001 AND reset_req THEN
        conv_proof_fault := FALSE; conv_proof_scans := 0;
        feed_proof_fault := FALSE; feed_proof_scans := 0;
        gate_travel_fault := FALSE; gate_scans := 0;
        state := 0; fault_reason := 0;
      END_IF;
  END_CASE;

  (* ================= publish status (controller_status.encode) ================= *)
  ST_LINE_STATE := state;
  ST_FAULT_REASON := fault_reason;
  ST_ALARMS_ACTIVE := 16#0000;
  ST_ALARMS_UNACKED := 16#0000;
  FOR i := 0 TO 9 DO
    bit := SHL(IN := WORD#1, N := i);
    IF alarm_active[i] THEN ST_ALARMS_ACTIVE := ST_ALARMS_ACTIVE OR bit; END_IF;
    IF alarm_unacked[i] THEN ST_ALARMS_UNACKED := ST_ALARMS_UNACKED OR bit; END_IF;
  END_FOR;
  ST_FIRST_OUT := first_out_holder;
  HMI_ACK := ack_bits;
  ST_START_INHIBIT := start_inhibit;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#100ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : controllab_line;
  END_RESOURCE
END_CONFIGURATION
