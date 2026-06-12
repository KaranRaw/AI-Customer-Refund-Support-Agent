import { Fragment, useEffect, useRef } from "react";

import type { ChatMessage } from "@/types/chat";
import { ChatStarter, type StarterOrder } from "@/components/chat/ChatStarter";
import { Composer, type ComposerVoice } from "@/components/chat/Composer";
import { BotIcon, ChatBubbleIcon, XIcon } from "@/components/icons";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { QuickReplies } from "@/components/chat/QuickReplies";

export interface StarterData {
  orders: StarterOrder[];
  hasMore: boolean;
  onPick: (order: StarterOrder) => void;
  onAsk: (question: string) => void;
}

export interface ClosedInfo {
  at: string | null; // ISO close time; null when closed before the server stamped it
  verdict: string | null; // the outcome shown on the ending stamp
}

interface Props {
  caseId: string;
  messages: ChatMessage[];
  typing: boolean;
  onSend: (text: string) => void;
  voice: ComposerVoice;
  closed: ClosedInfo | null;
  canEnd: boolean; // a real conversation exists — hide "End chat" on a fresh, untouched chat
  showClosing: boolean; // a verdict was reached and the chat is still open → offer to end
  starter: StarterData | null; // order picker shown on a fresh chat, in place of typing an ID
  onEndChat: () => void;
  onContinue: () => void;
  onNewChat: () => void;
}

// No verdict → return null so the ending stamp doesn't claim a resolution that never happened.
function outcomeLabel(verdict: string | null): string | null {
  switch (verdict) {
    case "approve":
      return "REFUND APPROVED";
    case "deny":
      return "REFUND DECLINED";
    case "escalate":
      return "ESCALATED TO MANAGER";
    default:
      return null;
  }
}

function endStamp(closed: ClosedInfo): string {
  const time = closed.at
    ? new Date(closed.at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
    : "";
  return ["CONVERSATION ENDED", time, outcomeLabel(closed.verdict)].filter(Boolean).join(" · ");
}

export function ChatPanel({
  caseId,
  messages,
  typing,
  onSend,
  voice,
  closed,
  canEnd,
  showClosing,
  starter,
  onEndChat,
  onContinue,
  onNewChat,
}: Props) {
  const msgsRef = useRef<HTMLDivElement>(null);

  // Keep the latest message in view as the conversation grows.
  useEffect(() => {
    const el = msgsRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, typing, showClosing, closed]);

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <div className="chat-bot">
          <BotIcon />
        </div>
        <div className="t">
          <b>Refund assistant</b>
          <span>
            <span className={`chat-dot${closed ? " off" : ""}`} />
            {closed ? "Conversation closed" : "Online · replies instantly"}
          </span>
        </div>
        {!closed && canEnd && (
          <button type="button" className="endbtn" onClick={onEndChat} aria-label="End chat">
            <XIcon />
            End chat
          </button>
        )}
        <span className="chat-case">
          CASE {caseId}
          {closed ? " · CLOSED" : ""}
        </span>
      </div>

      <div className="chat-msgs" ref={msgsRef}>
        {messages.map((message) => (
          <Fragment key={message.id}>
            <MessageBubble message={message} />
            {!closed && message.chips && <QuickReplies replies={message.chips} onSelect={onSend} />}
          </Fragment>
        ))}
        {starter && !closed && (
          <ChatStarter
            orders={starter.orders}
            hasMore={starter.hasMore}
            onPick={starter.onPick}
            onAsk={starter.onAsk}
          />
        )}
        {typing && !closed && (
          <div className="msg-a">
            <span className="typing">
              <i />
              <i />
              <i />
            </span>
          </div>
        )}
        {showClosing && !closed && !typing && (
          <div className="chips">
            <button type="button" className="chip" onClick={onEndChat}>
              That's all, thanks
            </button>
            <button type="button" className="chip alt" onClick={onContinue}>
              I have another issue
            </button>
          </div>
        )}
        {closed && (
          <div className="endline">
            <span>{endStamp(closed)}</span>
          </div>
        )}
      </div>

      {closed ? (
        <div className="endfoot">
          <span>
            You can review this case anytime from <b>Orders</b>
          </span>
          <button type="button" className="newchat" onClick={onNewChat}>
            <ChatBubbleIcon />
            Start a new chat
          </button>
        </div>
      ) : (
        <Composer onSend={onSend} voice={voice} disabled={typing} />
      )}
    </div>
  );
}
