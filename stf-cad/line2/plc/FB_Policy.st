// FB_Policy - a learned model evaluated IN the real-time task (TwinCAT 3 Machine Learning inference,
// ONNX, Tc3_MLL FB_MllPrediction - licence TF3800/TF3810 to confirm). Used for fast, bounded decisions:
// drop lead per tube, kick / pass, grip retry. Its output ALWAYS passes FB_SafeEnvelope.
FUNCTION_BLOCK FB_Policy
VAR fbPredict : FB_MllPrediction; END_VAR
