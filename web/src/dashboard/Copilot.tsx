// The copilot's own page: the conversation at full size - history, the chat with its Gemini /
// Local / Voice tabs, and the context the conversation has established (Chat.tsx).
import { Chat } from "./Chat";

// `navigate` opens a page an answer moved to, with the conversation kept open beside it
export function CopilotPage({ go, navigate }: { go: (p: string) => void; navigate?: (p: string) => void }) {
  return <Chat page="copilot" go={go} navigate={navigate} />;
}
