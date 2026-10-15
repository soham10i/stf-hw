// F_InSlice - TRUE while fPhase (0..1 of the PWM period) lies in [fStart, fStart + fDuty), wrapping at 1
FUNCTION F_InSlice : BOOL
VAR_INPUT fPhase, fStart, fDuty : LREAL; END_VAR
F_InSlice := LMOD(fPhase - fStart + 1.0, 1.0) < fDuty;
