(*
  ControlLab bulk-material line -- the section 6.2 Auto sequence and the section
  6.1 Manual mode in IEC 61131-3 Structured Text, for OpenPLC Runtime
  (docs/CONTROL-LAB.md, Phase 7 step 4; Manual mode completing Phase 2).

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
      Discrete inputs      start 0    size 19   -> %IX100.0 .. %IX102.2
      Coils                start 0    size 5    -> %QX100.0 .. %QX100.4
      Input registers      start 0    size 6    -> %IW100 .. %IW105
      Holding - read       start 100  size 2    -> %IW106 .. %IW107 (after the input registers)
      Holding - write      start 0    size 13   -> %QW100 .. %QW112

  Timings match ControlLab's test rig (services/testing/rig.py), so this
  program and the reference controller answer the same scenarios alike:
  conveyor proof 1.0 s, motor start proof 1.0 s, gate travel 2.0 s,
  purge 2.0 s, restart feeding below 60 % hopper level.
*)

PROGRAM controllab_line
  VAR
    (* ---- field inputs (discrete inputs 0-12) ---- *)
    LSL_101 AT %IX100.0 : BOOL;       (* bin low *)
    ZSO_102 AT %IX100.1 : BOOL;       (* gate open limit *)
    ZSC_102 AT %IX100.2 : BOOL;       (* gate closed limit *)
    M103_RUNNING AT %IX100.3 : BOOL;  (* feeder running (VFD) *)
    M103_FAULT AT %IX100.4 : BOOL;    (* feeder VFD fault *)
    M104_RUNNING AT %IX100.5 : BOOL;  (* conveyor running (contactor aux) *)
    M104_OL AT %IX100.6 : BOOL;       (* conveyor overload *)
    ZSS_104 AT %IX100.7 : BOOL;       (* conveyor motion switch *)
    LSH_105 AT %IX101.0 : BOOL;       (* hopper high switch: 1 = below 80 %, fail-safe *)
    LSHH_105 AT %IX101.1 : BOOL;      (* hopper high-high switch: 1 = below 95 %, fail-safe *)
    ES_001 AT %IX101.2 : BOOL;        (* e-stop healthy, fail-safe *)
    LSH_103 AT %IX101.3 : BOOL;       (* feeder discharge chute plugged: a jam *)
    WT105_FLT AT %IX101.4 : BOOL;    (* hopper weight input channel fault: WT_105 is meaningless *)
    LSL_111 AT %IX101.5 : BOOL;       (* bin B low *)
    ZSO_112 AT %IX101.6 : BOOL;       (* bin B gate open limit *)
    ZSC_112 AT %IX101.7 : BOOL;       (* bin B gate closed limit *)
    LSL_121 AT %IX102.0 : BOOL;       (* bin C low *)
    ZSO_122 AT %IX102.1 : BOOL;       (* bin C gate open limit *)
    ZSC_122 AT %IX102.2 : BOOL;       (* bin C gate closed limit *)

    (* ---- analog inputs (input registers 0-3) and the HMI request word (holding 100) ---- *)
    LT_101 AT %IW100 : INT;           (* bin level, % x100 *)
    WT_105 AT %IW101 : INT;           (* hopper weight, kg x10 *)
    IT_104 AT %IW102 : INT;           (* conveyor motor current, A x100 *)
    FT_104 AT %IW103 : INT;           (* belt scale flow, kg/s x100 *)
    LT_111 AT %IW104 : INT;           (* bin B level, % x100 *)
    LT_121 AT %IW105 : INT;           (* bin C level, % x100 *)
    HMI_REQUEST AT %IW106 : WORD;     (* bit 0 start, 1 stop, 2 reset, 3 acknowledge, 4 select auto,
                                         5 select manual, 6/7 conveyor start/stop, 8/9 gate open/close,
                                         10/11 feeder start/stop *)
    SP_SOURCE_BIN AT %IW107 : INT;    (* HMI setpoint: source bin for the next start, 1 A 2 B 3 C *)

    (* ---- field outputs (coils 0-2) ---- *)
    XV102_CMD_OPEN AT %QX100.0 : BOOL;
    M103_RUN AT %QX100.1 : BOOL;
    M104_RUN AT %QX100.2 : BOOL;
    XV112_CMD_OPEN AT %QX100.3 : BOOL;
    XV122_CMD_OPEN AT %QX100.4 : BOOL;

    (* ---- the holding write range 0-6: analog output, status, HMI ack ---- *)
    SC_103 AT %QW100 : INT;           (* feeder speed reference, % x100 *)
    ST_LINE_STATE AT %QW101 : INT;    (* 0 idle 1 starting 2 running 3 stopping 4 faulted 5 estopped 6 manual *)
    ST_FAULT_REASON AT %QW102 : INT;  (* controller_status.FAULT_REASONS code *)
    ST_ALARMS_ACTIVE AT %QW103 : WORD;
    ST_ALARMS_UNACKED AT %QW104 : WORD;
    ST_FIRST_OUT AT %QW105 : INT;     (* 1 + alarm bit, 0 = none *)
    HMI_ACK AT %QW106 : WORD;
    ST_START_INHIBIT AT %QW107 : WORD; (* why the last start was refused: 1 bin low, 2 hopper HH,
                                          4 unacked alarm, 8 e-stop, 16 faulted, 32 sensor failed,
                                          64 conveyor not running, 128 hopper high, 256 wrong mode,
                                          512 line not idle; 0 = none *)
    ST_MODE AT %QW108 : INT;          (* controller_status.MODES code: 0 AUTO, 1 MANUAL *)
    ST_ALARMS_ACTIVE_2 AT %QW109 : WORD;  (* alarm bits 16-31 *)
    ST_ALARMS_UNACKED_2 AT %QW110 : WORD;
    ST_SOURCE_BIN AT %QW111 : INT;    (* 1 A 2 B 3 C *)
    ST_ACTIVE_BIN AT %QW112 : INT;    (* the bin being drawn from, 0 = none *)
  END_VAR

  (* IEC 61131-3: a VAR block holds either located variables or ordinary
     ones, never both -- hence the second block. *)
  VAR
    (* ---- state ---- *)
    state : INT := 0;                 (* codes as ST_LINE_STATE *)
    mode : INT := 0;                  (* codes as ST_MODE; survives FAULTED and ESTOPPED *)
    start_step : INT := 0;            (* 0 conveyor, 1 gate, 2 feeder *)
    fault_reason : INT := 0;
    step_scans : INT := 0;
    purge_scans : INT := 0;
    clearing : BOOL := FALSE;       (* FAULTED on an upstream trip: the conveyor still clearing the belt *)
    feed_demand : BOOL := TRUE;

    (* one-shot operator requests, consumed by this scan *)
    start_req : BOOL;
    stop_req : BOOL;
    reset_req : BOOL;
    ack_req : BOOL;
    sel_auto_req : BOOL;
    sel_manual_req : BOOL;
    conv_start_req : BOOL;
    conv_stop_req : BOOL;
    gate_open_req : BOOL;
    gate_close_req : BOOL;
    feed_start_req : BOOL;
    feed_stop_req : BOOL;
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
    gate_b_last_cmd : BOOL := FALSE;  (* bins B and C: the same GateControl supervision *)
    gate_b_scans : INT := 0;
    gate_b_travel_fault : BOOL := FALSE;
    gate_c_last_cmd : BOOL := FALSE;
    gate_c_scans : INT := 0;
    gate_c_travel_fault : BOOL := FALSE;
    gate_any_fault : BOOL;            (* any gate not where it was commanded *)
    source_bin : INT := 1;            (* the HMI's setpoint, taken at start: 1 A 2 B 3 C *)
    active_bin : INT := 0;            (* the bin being drawn from, 0 at rest *)
    bin_low_src : BOOL;               (* the source bin's low switch *)
    bin_low_drawn : BOOL;             (* Manual: the low switch of any bin whose gate is commanded open *)

    (* Manual mode -- LineController._scan_manual *)
    man_conv_proven : BOOL := FALSE;  (* the belt proved running after a manual start *)
    man_conv_scans : INT := 0;
    mode_req : INT := -1;             (* -1 none this scan *)
    evaluated : BOOL;
    inh : WORD;
    refused : WORD;

    (* alarms, in controller_status.ALARMS bit order *)
    alarm_cond : ARRAY[0..18] OF BOOL;
    alarm_active : ARRAY[0..18] OF BOOL;
    alarm_unacked : ARRAY[0..18] OF BOOL;
    first_out_holder : INT := 0;      (* 1-based, 0 = none *)
    was_active : BOOL;
    unacked_trip : BOOL;
    conveyor_confirmed : BOOL;
    hopper_high : BOOL;               (* LSH-105 open *)
    hopper_hh_switch : BOOL;          (* LSHH-105 open *)
    hopper_hh_weight : BOOL;          (* WT-105 at or above the high-high setpoint, channel healthy *)
    hh_weight_scans : INT := 0;       (* how long it has been, for the vote's debounce *)
    hopper_hh_weight_vote : BOOL;     (* ... held for LIM_HH_DEBOUNCE scans: the transmitter's vote *)
    hopper_high_high : BOOL;          (* 1oo2: either of the two *)
    conveyor_current_high : BOOL;     (* IT-104 at or above the overcurrent setpoint *)
    oc_scans : INT := 0;              (* ... for how long, while proven running *)
    conveyor_overcurrent : BOOL;      (* held LIM_OVERCURRENT scans: a jam *)
    no_flow_scans : INT := 0;         (* feeder running, gate open, nothing on the belt scale *)
    no_flow : BOOL;
    lsh_mismatch_scans : INT := 0;    (* LevelSwitchCheck delay counters *)
    lshh_mismatch_scans : INT := 0;
    lsh_disagree : BOOL;
    lshh_disagree : BOOL;
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
    LIM_HIGH_RAW : INT := 16000;      (* LSH-105's point, 80 % of 2000 kg, in WT-105 raw *)
    LIM_HIGH_HIGH_RAW : INT := 19000; (* the analog high-high setpoint, 95 % of 2000 kg *)
    LIM_BAND_RAW : INT := 400;        (* cross-check deadband, 2 % of span = 40 kg *)
    LIM_DISAGREE : INT := 10;         (* cross-check delay, 1.0 s *)
    LIM_HH_DEBOUNCE : INT := 5;       (* the transmitter's high-high vote holds 0.5 s before it counts *)
    LIM_OVERCURRENT_RAW : INT := 1500;  (* 15.00 A, 125 % of the conveyor motor's 12 A full load, in IT-104 raw *)
    LIM_OVERCURRENT : INT := 10;      (* ... for 1.0 s *)
    LIM_NO_FLOW_RAW : INT := 20;      (* 0.20 kg/s on the belt scale, in FT-104 raw *)
    LIM_NO_FLOW : INT := 40;          (* 4.0 s: a belt transit plus margin (the test rig's) *)
  END_VAR

  (* ================= HMI request/acknowledge (4-phase) ================= *)
  start_req := FALSE; stop_req := FALSE; reset_req := FALSE; ack_req := FALSE;
  sel_auto_req := FALSE; sel_manual_req := FALSE; conv_start_req := FALSE; conv_stop_req := FALSE;
  gate_open_req := FALSE; gate_close_req := FALSE; feed_start_req := FALSE; feed_stop_req := FALSE;
  FOR i := 0 TO 11 DO
    bit := SHL(IN := WORD#1, N := i);
    IF (HMI_REQUEST AND bit) <> 0 AND (ack_bits AND bit) = 0 THEN
      ack_bits := ack_bits OR bit;                (* phase 2: take it, acknowledge *)
      CASE i OF
        0: start_req := TRUE;
        1: stop_req := TRUE;
        2: reset_req := TRUE;
        3: ack_req := TRUE;
        4: sel_auto_req := TRUE;
        5: sel_manual_req := TRUE;
        6: conv_start_req := TRUE;
        7: conv_stop_req := TRUE;
        8: gate_open_req := TRUE;
        9: gate_close_req := TRUE;
        10: feed_start_req := TRUE;
        11: feed_stop_req := TRUE;
      END_CASE;
    ELSIF (HMI_REQUEST AND bit) = 0 AND (ack_bits AND bit) <> 0 THEN
      ack_bits := ack_bits AND NOT bit;           (* phase 4: request dropped, release *)
    END_IF;
  END_FOR;

  (* ================= the HMI setpoint: source bin (select_source) ================= *)
  IF SP_SOURCE_BIN >= 1 AND SP_SOURCE_BIN <= 3 THEN source_bin := SP_SOURCE_BIN; END_IF;
  bin_low_src := (source_bin = 1 AND LSL_101) OR (source_bin = 2 AND LSL_111) OR (source_bin = 3 AND LSL_121);

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

  IF XV112_CMD_OPEN <> gate_b_last_cmd THEN gate_b_scans := 0; gate_b_travel_fault := FALSE; gate_b_last_cmd := XV112_CMD_OPEN; END_IF;
  IF (XV112_CMD_OPEN AND ZSO_112) OR (NOT XV112_CMD_OPEN AND ZSC_112) THEN gate_b_scans := 0;
  ELSE
    gate_b_scans := gate_b_scans + 1;
    IF gate_b_scans >= LIM_GATE_TRAVEL THEN gate_b_travel_fault := TRUE; END_IF;
  END_IF;
  IF XV122_CMD_OPEN <> gate_c_last_cmd THEN gate_c_scans := 0; gate_c_travel_fault := FALSE; gate_c_last_cmd := XV122_CMD_OPEN; END_IF;
  IF (XV122_CMD_OPEN AND ZSO_122) OR (NOT XV122_CMD_OPEN AND ZSC_122) THEN gate_c_scans := 0;
  ELSE
    gate_c_scans := gate_c_scans + 1;
    IF gate_c_scans >= LIM_GATE_TRAVEL THEN gate_c_travel_fault := TRUE; END_IF;
  END_IF;
  gate_any_fault := gate_travel_fault OR gate_b_travel_fault OR gate_c_travel_fault;

  conveyor_confirmed := M104_RUNNING AND ZSS_104;
  (* the level switches are fail-safe (1 = below the switch point): a broken wire reads high *)
  hopper_high := NOT LSH_105;
  hopper_hh_switch := NOT LSHH_105;
  (* the high-high trip is 1oo2: the switch OR WT-105 (no vote while its channel has failed) *)
  hopper_hh_weight := NOT WT105_FLT AND WT_105 >= LIM_HIGH_HIGH_RAW;
  (* Interlocks.scan / hopper_high_high_weight_vote: noise can't trip it; the switch stays instant *)
  IF hopper_hh_weight THEN
    IF hh_weight_scans < LIM_HH_DEBOUNCE THEN hh_weight_scans := hh_weight_scans + 1; END_IF;
  ELSE
    hh_weight_scans := 0;
  END_IF;
  hopper_hh_weight_vote := hopper_hh_weight AND hh_weight_scans >= LIM_HH_DEBOUNCE;
  hopper_high_high := hopper_hh_switch OR hopper_hh_weight_vote;

  (* the motor current and the belt scale (Interlocks.scan): overcurrent while proven running, and no
     flow while feeding, each an on-delay *)
  conveyor_current_high := IT_104 >= LIM_OVERCURRENT_RAW;
  IF M104_RUNNING AND conveyor_current_high THEN
    IF oc_scans < LIM_OVERCURRENT THEN oc_scans := oc_scans + 1; END_IF;
  ELSE
    oc_scans := 0;
  END_IF;
  conveyor_overcurrent := M104_RUNNING AND conveyor_current_high AND oc_scans >= LIM_OVERCURRENT;
  IF M103_RUNNING AND (ZSO_102 OR ZSO_112 OR ZSO_122) AND FT_104 < LIM_NO_FLOW_RAW THEN
    IF no_flow_scans < LIM_NO_FLOW THEN no_flow_scans := no_flow_scans + 1; END_IF;
  ELSE
    no_flow_scans := 0;
  END_IF;
  no_flow := no_flow_scans >= LIM_NO_FLOW;

  (* switch vs transmitter cross-check (LevelSwitchCheck): a gap wider than the
     deadband, lasting LIM_DISAGREE scans; not judged while WT-105 has failed *)
  IF NOT WT105_FLT AND ((hopper_high AND WT_105 < LIM_HIGH_RAW - LIM_BAND_RAW)
                        OR (NOT hopper_high AND WT_105 >= LIM_HIGH_RAW + LIM_BAND_RAW)) THEN
    IF lsh_mismatch_scans < LIM_DISAGREE THEN lsh_mismatch_scans := lsh_mismatch_scans + 1; END_IF;
  ELSE
    lsh_mismatch_scans := 0;
  END_IF;
  lsh_disagree := lsh_mismatch_scans >= LIM_DISAGREE;
  IF NOT WT105_FLT AND ((hopper_hh_switch AND WT_105 < LIM_HIGH_HIGH_RAW - LIM_BAND_RAW)
                        OR (NOT hopper_hh_switch AND WT_105 >= LIM_HIGH_HIGH_RAW + LIM_BAND_RAW)) THEN
    IF lshh_mismatch_scans < LIM_DISAGREE THEN lshh_mismatch_scans := lshh_mismatch_scans + 1; END_IF;
  ELSE
    lshh_mismatch_scans := 0;
  END_IF;
  lshh_disagree := lshh_mismatch_scans >= LIM_DISAGREE;

  (* ================= alarms (AlarmManager.scan / acknowledge) ================= *)
  alarm_cond[0] := NOT ES_001;                  (* ES-001.TRIP *)
  alarm_cond[1] := LSL_101;                     (* LSL-101.LOW (warning) *)
  alarm_cond[2] := gate_travel_fault;           (* XV-102.TRAVEL_FAULT *)
  alarm_cond[3] := M103_FAULT;                  (* M-103.FAULT *)
  alarm_cond[4] := feed_proof_fault;            (* M-103.START_PROOF *)
  alarm_cond[5] := M104_OL;                     (* M-104.OL *)
  alarm_cond[6] := M104_RUNNING AND NOT ZSS_104;  (* ZSS-104.LOST *)
  alarm_cond[7] := conv_proof_fault;            (* M-104.START_PROOF *)
  alarm_cond[8] := hopper_high_high;            (* WT-105.HIGH_HIGH *)
  alarm_cond[9] := LSH_103;                     (* LSH-103.JAM *)
  alarm_cond[10] := WT105_FLT;                 (* WT-105.FAIL *)
  alarm_cond[11] := lsh_disagree;              (* LSH-105.DISAGREE (warning) *)
  alarm_cond[12] := lshh_disagree;             (* LSHH-105.DISAGREE *)
  alarm_cond[13] := conveyor_overcurrent;      (* IT-104.HIGH *)
  alarm_cond[14] := no_flow;                   (* FT-104.NO_FLOW (warning) *)
  alarm_cond[15] := LSL_111;                   (* LSL-111.LOW (warning) *)
  alarm_cond[16] := gate_b_travel_fault;       (* XV-112.TRAVEL_FAULT *)
  alarm_cond[17] := LSL_121;                   (* LSL-121.LOW (warning) *)
  alarm_cond[18] := gate_c_travel_fault;       (* XV-122.TRAVEL_FAULT *)

  FOR i := 0 TO 18 DO
    was_active := alarm_active[i];
    alarm_active[i] := alarm_cond[i];
    IF alarm_active[i] AND NOT was_active THEN
      alarm_unacked[i] := TRUE;
      IF first_out_holder = 0 THEN first_out_holder := i + 1; END_IF;
    END_IF;
    IF NOT alarm_active[i] AND NOT alarm_unacked[i] AND first_out_holder = i + 1 THEN first_out_holder := 0; END_IF;
  END_FOR;

  IF ack_req THEN
    FOR i := 0 TO 18 DO
      alarm_unacked[i] := FALSE;
      IF NOT alarm_active[i] AND first_out_holder = i + 1 THEN first_out_holder := 0; END_IF;
    END_FOR;
  END_IF;

  unacked_trip := FALSE;
  FOR i := 0 TO 18 DO
    IF i <> 1 AND i <> 11 AND i <> 14 AND i <> 15 AND i <> 17 AND alarm_unacked[i] THEN unacked_trip := TRUE; END_IF;
    (* bits 1, 11, 14, 15, 17 are the warnings *)
  END_FOR;

  (* ================= e-stop overrides every state ================= *)
  IF NOT ES_001 AND state <> 5 THEN
    M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; clearing := FALSE;
    state := 5; fault_reason := 1; start_step := 0;
  END_IF;

  (* ================= mode (LineController._change_mode): only at rest ================= *)
  mode_req := -1;
  IF sel_auto_req THEN mode_req := 0; END_IF;
  IF sel_manual_req THEN mode_req := 1; END_IF;   (* the later bit wins, as the later call does *)
  IF mode_req >= 0 THEN
    IF mode_req = mode THEN
      start_inhibit := 16#0000;
    ELSIF state = 0 OR (state = 6 AND NOT M103_RUN AND NOT M104_RUN AND NOT XV102_CMD_OPEN AND NOT XV112_CMD_OPEN
                        AND NOT XV122_CMD_OPEN) THEN
      mode := mode_req;
      IF mode = 0 THEN state := 0; ELSE state := 6; END_IF; active_bin := 0;          (* _enter_rest *)
      fault_reason := 0; man_conv_proven := FALSE; man_conv_scans := 0;
      start_inhibit := 16#0000;
    ELSE
      start_inhibit := 16#0200;                                      (* LINE_NOT_IDLE *)
    END_IF;
  END_IF;

  (* a device start outside MANUAL is refused and reported (_refuse_device_starts) *)
  IF state <> 6 AND (conv_start_req OR gate_open_req OR feed_start_req) THEN
    IF mode = 0 THEN start_inhibit := 16#0100;                       (* WRONG_MODE *)
    ELSIF state = 5 THEN start_inhibit := 16#0008;                   (* ESTOP_ACTIVE *)
    ELSE start_inhibit := 16#0010;                                   (* LINE_FAULTED *)
    END_IF;
  END_IF;

  (* ================= the line state machine ================= *)
  CASE state OF
    0: (* IDLE -- off, continuously enforced *)
      M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE;
      IF start_req THEN
        start_inhibit := 16#0000;
        IF hopper_high_high THEN start_inhibit := start_inhibit OR 16#0002; END_IF;
        IF bin_low_src THEN start_inhibit := start_inhibit OR 16#0001; END_IF;
        IF unacked_trip THEN start_inhibit := start_inhibit OR 16#0004; END_IF;
        IF WT105_FLT THEN start_inhibit := start_inhibit OR 16#0020; END_IF;   (* unknown means stopped *)
        IF start_inhibit = 0 THEN
          state := 1; start_step := 0; step_scans := 0; active_bin := source_bin;
          M104_RUN := TRUE;                                        (* downstream first *)
        END_IF;
      END_IF;

    1: (* STARTING *)
      trip := 0;
      IF hopper_high_high THEN trip := 2;
      ELSIF M104_OL THEN trip := 4;
      ELSIF conveyor_overcurrent THEN trip := 12;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;
      ELSIF WT105_FLT THEN trip := 11;
      ELSIF conv_proof_fault THEN trip := 6;
      ELSIF feed_proof_fault THEN trip := 5;
      ELSIF gate_any_fault THEN trip := 7;
      END_IF;
      IF trip <> 0 THEN
        (* an upstream trip (feeder trip, feeder fail-to-start, gate fault, jam) keeps a running
           conveyor on to clear the belt; every other trip stops it at once -- LineController.CLEAR_BELT_ON *)
        clearing := M104_RUN AND (trip = 3 OR trip = 5 OR trip = 7 OR trip = 9 OR trip = 10);
        M103_RUN := FALSE; M104_RUN := clearing; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
        state := 4; fault_reason := trip; start_step := 0;
      ELSIF stop_req THEN
        state := 3; M103_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
      ELSIF start_step = 0 THEN
        step_scans := step_scans + 1;
        IF conveyor_confirmed THEN
          start_step := 1; step_scans := 0;
          IF active_bin = 2 THEN XV112_CMD_OPEN := TRUE; ELSIF active_bin = 3 THEN XV122_CMD_OPEN := TRUE;
          ELSE XV102_CMD_OPEN := TRUE; END_IF;
        ELSIF step_scans >= LIM_CONV_PROOF THEN
          M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE;
          state := 4; fault_reason := 6; start_step := 0;
        END_IF;
      ELSIF start_step = 1 THEN
        IF (active_bin = 1 AND ZSO_102) OR (active_bin = 2 AND ZSO_112) OR (active_bin = 3 AND ZSO_122) THEN
          start_step := 2; step_scans := 0; M103_RUN := TRUE; SC_103 := LIM_FEED_SPEED;
        END_IF;
      ELSIF start_step = 2 THEN
        IF M103_RUNNING THEN state := 2; start_step := 0; END_IF;
      END_IF;

    2: (* RUNNING *)
      trip := 0;
      IF hopper_high_high THEN trip := 2;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;                         (* the drive still reports running *)
      ELSIF feed_proof_fault THEN trip := 5;                (* a level-control restart that never ran *)
      ELSIF WT105_FLT THEN trip := 11;                      (* the feed decision reads WT_105 *)
      ELSIF M104_OL THEN trip := 4;
      ELSIF conveyor_overcurrent THEN trip := 12;
      ELSIF NOT conveyor_confirmed THEN
        IF conveyor_current_high THEN trip := 12; ELSE trip := 8; END_IF;   (* _motion_loss_reason: jam or slip *)
      ELSIF gate_any_fault THEN trip := 9;
      END_IF;
      IF trip <> 0 THEN
        (* an upstream trip (feeder trip, feeder fail-to-start, gate fault, jam) keeps a running
           conveyor on to clear the belt; every other trip stops it at once -- LineController.CLEAR_BELT_ON *)
        clearing := M104_RUN AND (trip = 3 OR trip = 5 OR trip = 7 OR trip = 9 OR trip = 10);
        M103_RUN := FALSE; M104_RUN := clearing; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
        state := 4; fault_reason := trip;
      ELSIF stop_req THEN
        state := 3; M103_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
      ELSE
        (* hopper hysteresis: stop feeding at LSH, resume below 60 % *)
        IF hopper_high THEN feed_demand := FALSE;
        ELSIF WT_105 < LIM_RESTART_RAW THEN feed_demand := TRUE;
        END_IF;
        M103_RUN := feed_demand;
        IF feed_demand THEN SC_103 := LIM_FEED_SPEED; END_IF;
      END_IF;

    3: (* STOPPING -- upstream first, conveyor purges the belt *)
      trip := 0;
      IF hopper_high_high THEN trip := 2;
      ELSIF M104_OL THEN trip := 4;
      ELSIF conveyor_overcurrent THEN trip := 12;
      ELSIF M103_FAULT THEN trip := 3;
      ELSIF LSH_103 THEN trip := 10;
      ELSIF gate_any_fault THEN trip := 9;
      END_IF;
      IF trip <> 0 THEN
        (* an upstream trip (feeder trip, feeder fail-to-start, gate fault, jam) keeps a running
           conveyor on to clear the belt; every other trip stops it at once -- LineController.CLEAR_BELT_ON *)
        clearing := M104_RUN AND (trip = 3 OR trip = 5 OR trip = 7 OR trip = 9 OR trip = 10);
        M103_RUN := FALSE; M104_RUN := clearing; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
        state := 4; fault_reason := trip;
      ELSE
        purge_scans := purge_scans + 1;
        IF purge_scans >= LIM_PURGE THEN
          M104_RUN := FALSE; state := 0; purge_scans := 0; active_bin := 0;
        END_IF;
      END_IF;

    4: (* FAULTED -- feed and gate off; the conveyor off too unless it is clearing the belt after an
          upstream trip; reset only once the pass-through causes have cleared *)
      M103_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE;
      IF clearing THEN
        purge_scans := purge_scans + 1;
        IF purge_scans >= LIM_PURGE OR M104_OL OR conveyor_overcurrent OR NOT conveyor_confirmed OR hopper_high_high
           OR WT105_FLT THEN
          clearing := FALSE;
        END_IF;
      END_IF;
      M104_RUN := clearing;
      IF start_req THEN start_inhibit := 16#0010; END_IF;          (* refused, as always; now reported *)
      IF reset_req AND NOT hopper_high_high AND NOT M104_OL AND NOT M103_FAULT AND NOT LSH_103 AND NOT WT105_FLT THEN
        conv_proof_fault := FALSE; conv_proof_scans := 0;
        feed_proof_fault := FALSE; feed_proof_scans := 0;
        gate_travel_fault := FALSE; gate_scans := 0;
        gate_b_travel_fault := FALSE; gate_b_scans := 0; gate_c_travel_fault := FALSE; gate_c_scans := 0;
        clearing := FALSE; M104_RUN := FALSE;                      (* rest means off, in this same scan *)
        IF mode = 0 THEN state := 0; ELSE state := 6; END_IF; active_bin := 0;      (* _enter_rest *)
        fault_reason := 0; man_conv_proven := FALSE; man_conv_scans := 0;
      END_IF;

    5: (* ESTOPPED -- off; reset once the e-stop is healthy again; a trip cause
          still standing sends the line to FAULTED on it, never to IDLE *)
      M103_RUN := FALSE; M104_RUN := FALSE; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE;
      IF start_req THEN start_inhibit := 16#0008; END_IF;          (* refused, as always; now reported *)
      IF ES_001 AND reset_req THEN
        conv_proof_fault := FALSE; conv_proof_scans := 0;
        feed_proof_fault := FALSE; feed_proof_scans := 0;
        gate_travel_fault := FALSE; gate_scans := 0;
        gate_b_travel_fault := FALSE; gate_b_scans := 0; gate_c_travel_fault := FALSE; gate_c_scans := 0;
        trip := 0;                                                 (* same order as _standing_cause *)
        IF hopper_high_high THEN trip := 2;
        ELSIF M104_OL THEN trip := 4;
        ELSIF M103_FAULT THEN trip := 3;
        ELSIF LSH_103 THEN trip := 10;
        ELSIF WT105_FLT THEN trip := 11;
        END_IF;
        IF trip <> 0 THEN
          state := 4; fault_reason := trip;
        ELSE
          IF mode = 0 THEN state := 0; ELSE state := 6; END_IF; active_bin := 0;    (* _enter_rest *)
          fault_reason := 0; man_conv_proven := FALSE; man_conv_scans := 0;
        END_IF;
      END_IF;

    6: (* MANUAL -- the operator drives each device; every protection still enforced *)
      (* the conveyor's own proof, since no start sequence proves it (_supervise_manual_conveyor) *)
      IF NOT M104_RUN THEN man_conv_proven := FALSE; man_conv_scans := 0;
      ELSIF conveyor_confirmed THEN man_conv_proven := TRUE;
      ELSIF NOT man_conv_proven THEN man_conv_scans := man_conv_scans + 1;
      END_IF;
      (* _manual_trip_reason: Auto's trips while the feeder or conveyor runs; a gate fault any time *)
      trip := 0;
      IF M103_RUN OR M104_RUN THEN
        IF hopper_high_high THEN trip := 2;
        ELSIF M104_OL THEN trip := 4;
        ELSIF conveyor_overcurrent THEN trip := 12;
        ELSIF M103_FAULT THEN trip := 3;
        ELSIF LSH_103 THEN trip := 10;
        ELSIF WT105_FLT THEN trip := 11;
        END_IF;
      END_IF;
      IF trip = 0 AND M104_RUN THEN
        IF conv_proof_fault OR (NOT man_conv_proven AND man_conv_scans >= LIM_CONV_PROOF) THEN trip := 6;
        ELSIF man_conv_proven AND NOT conveyor_confirmed THEN
          IF conveyor_current_high THEN trip := 12; ELSE trip := 8; END_IF;
        END_IF;
      END_IF;
      IF trip = 0 AND M103_RUN AND feed_proof_fault THEN trip := 5; END_IF;
      IF trip = 0 AND gate_any_fault THEN trip := 9; END_IF;
      IF trip <> 0 THEN
        clearing := M104_RUN AND (trip = 3 OR trip = 5 OR trip = 7 OR trip = 9 OR trip = 10);
        M103_RUN := FALSE; M104_RUN := clearing; XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; purge_scans := 0;
        state := 4; fault_reason := trip;
      ELSE
        (* the line Stop stops every device; stops before starts *)
        IF stop_req THEN feed_stop_req := TRUE; gate_close_req := TRUE; conv_stop_req := TRUE; END_IF;
        IF feed_stop_req THEN M103_RUN := FALSE; END_IF;
        IF gate_close_req THEN XV102_CMD_OPEN := FALSE; XV112_CMD_OPEN := FALSE; XV122_CMD_OPEN := FALSE; END_IF;
        IF conv_stop_req THEN M104_RUN := FALSE; man_conv_proven := FALSE; man_conv_scans := 0; END_IF;
        evaluated := FALSE; inh := 16#0000;
        IF start_req THEN evaluated := TRUE; inh := inh OR 16#0100; END_IF;       (* WRONG_MODE *)
        IF conv_start_req AND NOT conv_stop_req THEN                              (* _manual_conveyor_refusal *)
          evaluated := TRUE; refused := 16#0000;
          IF hopper_high_high THEN refused := refused OR 16#0002; END_IF;
          IF WT105_FLT THEN refused := refused OR 16#0020; END_IF;
          IF unacked_trip THEN refused := refused OR 16#0004; END_IF;
          inh := inh OR refused;
          IF refused = 0 AND NOT M104_RUN THEN
            M104_RUN := TRUE; man_conv_proven := FALSE; man_conv_scans := 0;
          END_IF;
        END_IF;
        IF gate_open_req AND NOT gate_close_req THEN                              (* no permissive but the e-stop *)
          evaluated := TRUE;                   (* one bin at a time: only the selected bin's gate *)
          XV102_CMD_OPEN := source_bin = 1; XV112_CMD_OPEN := source_bin = 2; XV122_CMD_OPEN := source_bin = 3;
        END_IF;
        IF feed_start_req AND NOT feed_stop_req THEN                              (* _manual_feeder_refusal *)
          evaluated := TRUE; refused := 16#0000;
          IF NOT man_conv_proven THEN refused := refused OR 16#0040; END_IF;
          bin_low_drawn := (XV102_CMD_OPEN AND LSL_101) OR (XV112_CMD_OPEN AND LSL_111) OR (XV122_CMD_OPEN AND LSL_121)
                           OR (NOT XV102_CMD_OPEN AND NOT XV112_CMD_OPEN AND NOT XV122_CMD_OPEN AND bin_low_src);
          IF bin_low_drawn THEN refused := refused OR 16#0001; END_IF;
          IF hopper_high THEN refused := refused OR 16#0080; END_IF;
          IF hopper_high_high THEN refused := refused OR 16#0002; END_IF;
          IF WT105_FLT THEN refused := refused OR 16#0020; END_IF;
          IF unacked_trip THEN refused := refused OR 16#0004; END_IF;
          inh := inh OR refused;
          IF refused = 0 THEN M103_RUN := TRUE; SC_103 := LIM_FEED_SPEED; END_IF;
        END_IF;
        IF evaluated THEN start_inhibit := inh; END_IF;
        (* every scan: the feeder only onto a proven belt, and never past the high switch *)
        IF NOT man_conv_proven OR hopper_high THEN M103_RUN := FALSE; END_IF;
      END_IF;
  END_CASE;

  (* ================= publish status (controller_status.encode) ================= *)
  ST_LINE_STATE := state;
  ST_FAULT_REASON := fault_reason;
  ST_ALARMS_ACTIVE := 16#0000;
  ST_ALARMS_UNACKED := 16#0000;
  ST_ALARMS_ACTIVE_2 := 16#0000;
  ST_ALARMS_UNACKED_2 := 16#0000;
  FOR i := 0 TO 18 DO
    IF i < 16 THEN
      bit := SHL(IN := WORD#1, N := i);
      IF alarm_active[i] THEN ST_ALARMS_ACTIVE := ST_ALARMS_ACTIVE OR bit; END_IF;
      IF alarm_unacked[i] THEN ST_ALARMS_UNACKED := ST_ALARMS_UNACKED OR bit; END_IF;
    ELSE
      bit := SHL(IN := WORD#1, N := i - 16);
      IF alarm_active[i] THEN ST_ALARMS_ACTIVE_2 := ST_ALARMS_ACTIVE_2 OR bit; END_IF;
      IF alarm_unacked[i] THEN ST_ALARMS_UNACKED_2 := ST_ALARMS_UNACKED_2 OR bit; END_IF;
    END_IF;
  END_FOR;
  ST_FIRST_OUT := first_out_holder;
  HMI_ACK := ack_bits;
  ST_START_INHIBIT := start_inhibit;
  ST_MODE := mode;
  ST_SOURCE_BIN := source_bin;
  ST_ACTIVE_BIN := active_bin;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#100ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : controllab_line;
  END_RESOURCE
END_CONFIGURATION
