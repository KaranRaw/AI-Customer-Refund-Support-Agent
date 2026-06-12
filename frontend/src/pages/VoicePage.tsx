import { Link } from "react-router-dom";

import { BoltIcon, MicIcon } from "@/components/icons";
import { useVoice } from "@/hooks/useVoice";
import { useSession } from "@/lib/session";
import "@/styles/voice.css";

function statusLabel(state: string, botSpeaking: boolean): string {
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
      return "Hanging up…";
    case "error":
      return "Connection error";
    default:
      return "Tap to start talking";
  }
}

export function VoicePage() {
  const { customer } = useSession();
  const { state, botSpeaking, userText, botText, error, connect, disconnect } = useVoice({
    customerEmail: customer?.email,
  });

  const connected = state === "connected" || state === "ready";
  const busy =
    state === "initializing" ||
    state === "initialized" ||
    state === "authenticating" ||
    state === "authenticated" ||
    state === "connecting" ||
    state === "disconnecting";

  return (
    <div className="voice">
      <nav>
        <div className="brand">
          <div className="mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
        </div>
        <div className="links">
          <Link to="/chat">Text chat</Link>
          <Link to="/orders">Orders</Link>
        </div>
      </nav>

      <div className="stage">
        <div className="panel">
          <button
            type="button"
            className={`orb${connected ? " live" : ""}${botSpeaking ? " speaking" : ""}`}
            onClick={() => (connected ? disconnect() : connect())}
            disabled={busy}
            aria-label={connected ? "Hang up" : "Start talking"}
          >
            <MicIcon />
          </button>

          <p className="status">{statusLabel(state, botSpeaking)}</p>
          {error && <p className="verr">{error}</p>}

          {(userText || botText) && (
            <div className="transcript">
              {userText && (
                <p className="t-user">
                  <span>You</span> {userText}
                </p>
              )}
              {botText && (
                <p className="t-bot">
                  <span>Assistant</span> {botText}
                </p>
              )}
            </div>
          )}

          <p className="hint">
            {connected ? (
              <button type="button" className="hang" onClick={disconnect}>
                Hang up
              </button>
            ) : (
              <>
                Full-duplex voice — interrupt any time. Every turn streams to the{" "}
                <Link to="/admin">reasoning dashboard</Link>.
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
