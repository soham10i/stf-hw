// FB_AmrPorts - every buffer raises a task with a DEADLINE (its autonomy left):
// hopper level (IO-Link ToF), cassette full (lift counter), tray magazine, reject drawer level.
// Earliest deadline first; one visit serves every pending task at a port (line_sim proves it).
FUNCTION_BLOCK FB_AmrPorts
