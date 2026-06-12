import { useState, type FormEvent } from "react";

import { MicIcon, SendIcon, XIcon } from "@/components/icons";
import { useVoice } from "@/hooks/useVoice";

export interface ComposerVoice {
  customerEmail?: string | null;
  /** Mints the shared conversation if needed, so voice + text are one thread. */
  ensureConversation: () => Promise<number | null>;
  onUserTurn: (text: string) => void;
  onBotTurn: (text: string) => void;
}

interface Props {
  onSend: (text: string) => void;
  voice: ComposerVoice;
  disabled?: boolean;
}

function voiceStatus(state: string, botSpeaking: boolean): string {
  switch (state) {
    case "initializing":
    case "initialized":
    case "authenticating":
    case "authenticated":
    case "connecting":
      return "Connecting…";
    case "connected":
    case "ready":
      return botSpeaking ? "Assistant speaking…" : "Listening — go ahead";
    case "disconnecting":
      return "Ending…";
    default:
      return "Starting…";
  }
}

export function Composer({ onSend, voice, disabled }: Props) {
  const [value, setValue] = useState("");
  const { state, botSpeaking, error, connect, disconnect } = useVoice({
    customerEmail: voice.customerEmail,
    onUserTurn: voice.onUserTurn,
    onBotTurn: voice.onBotTurn,
  });

  // Show the live strip for any non-idle state (incl. error, so it can be dismissed).
  const voicing = state !== "disconnected";

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  }

  async function startVoice() {
    const id = await voice.ensureConversation();
    void connect(id);
  }

  return (
    <form className="compose" onSubmit={submit}>
      <div className="rowbox">
        {voicing ? (
          <div className="vstrip">
            <span className={`vdot${botSpeaking ? " speaking" : ""}`} />
            <span className="vstatus">{error ?? voiceStatus(state, botSpeaking)}</span>
            <span className={`veq${botSpeaking ? " hot" : ""}`}>
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
            <button type="button" className="vend" onClick={disconnect} aria-label="End voice">
              <XIcon />
            </button>
          </div>
        ) : (
          <div className="vrow">
            <div className="field">
              <input
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="Type a message…"
                disabled={disabled}
              />
            </div>
            <button
              type="button"
              className="rb mic"
              onClick={startVoice}
              aria-label="Talk to the assistant"
            >
              <MicIcon />
            </button>
            <button type="submit" className="rb send" disabled={disabled} aria-label="Send">
              <SendIcon />
            </button>
          </div>
        )}
      </div>
    </form>
  );
}
