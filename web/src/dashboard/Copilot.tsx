// The copilot's own page: the conversation at full size - history, the chat with its Gemini /
// Local / Voice tabs, and the context the conversation has established (Chat.tsx).
import { Chat } from "./Chat";

export function CopilotPage({ go }: { go: (p: string) => void }) {
  return <Chat page="copilot" go={go} />;
}
