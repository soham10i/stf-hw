# Command Queue Architecture

The STF Digital Twin v3.0 introduces a robust **Command Queue architecture** to ensure reliable, sequential, and auditable execution of complex factory operations. This architecture decouples the user-facing API from the hardware-controlling logic, improving system stability and scalability.

## Workflow

The command execution workflow follows these steps:

1.  **Queueing**: A user or automated system makes a request to an API endpoint (e.g., `/order/process`).
2.  **Database Entry**: The API creates a new record in the `commands` table with a `PENDING` status. It does not attempt to execute the command directly.
3.  **Polling**: The `main_controller` process runs independently, periodically polling the database for the oldest command with `PENDING` status.
4.  **Execution**: Once a pending command is found, the controller updates its status to `IN_PROGRESS` and begins executing the required steps using its Finite State Machine (FSM) logic.
5.  **Hardware Interaction**: The controller sends low-level instructions to the mock hardware via MQTT (e.g., move commands, gripper actions).
6.  **Completion**: Upon successful completion, the controller updates the command's status to `COMPLETED`.
7.  **Failure Handling**: If an error occurs during execution, the status is updated to `FAILED`, and a log entry is created with the error details.

This pattern ensures that only one command is executed at a time, preventing conflicts and race conditions between different subsystems.

## Database Schema

The `commands` table is central to this architecture:

| Column         | Type      | Description                                      |
| -------------- | --------- | ------------------------------------------------ |
| `id`           | Integer   | Primary key                                      |
| `command_type` | String    | Type of command (e.g., `PROCESS`, `STORE`)       |
| `target_slot`  | String    | Target inventory slot (e.g., `A1`)               |
| `payload_json` | JSON      | Additional command parameters (e.g., flavor)     |
| `status`       | String    | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`  |
| `created_at`   | DateTime  | Timestamp when the command was queued            |
| `executed_at`  | DateTime  | Timestamp when the controller started execution  |
| `completed_at` | DateTime  | Timestamp when the command finished              |
| `message`      | String    | Result or error message from the controller      |

## Benefits

- **Reliability**: Commands are persisted in the database, ensuring they are not lost if the controller restarts.
- **Decoupling**: The API and controller are fully independent, allowing them to be scaled and updated separately.
- **Auditability**: The `commands` table provides a complete history of all operations, including their status and execution times.
- **Sequential Execution**: The polling mechanism guarantees that commands are processed one at a time, preventing hardware conflicts.
- **Asynchronous Operations**: The API can immediately respond to user requests without waiting for long-running hardware operations to complete.
