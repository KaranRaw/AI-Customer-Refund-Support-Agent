import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { BackButton } from "@/components/BackButton";
import { BoltIcon, MicIcon, PhoneIcon } from "@/components/icons";
import { useVoice } from "@/hooks/useVoice";
import { useSession } from "@/lib/session";
import "@/styles/voice.css";

type OrbState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

// Pipecat's levels are ~0..1; a little gain makes quiet speech still move the orb.
const GAIN = 1.8;

const LABEL: Record<OrbState, string> = {
  idle: "Tap to start talking",
  connecting: "Connecting…",
  listening: "Listening — go ahead",
  thinking: "Thinking…",
  speaking: "Assistant speaking",
};

export function VoicePage() {
  const { customer } = useSession();
  const {
    state,
    botSpeaking,
    thinking,
    userText,
    botText,
    error,
    connect,
    disconnect,
    micLevelRef,
    botLevelRef,
  } = useVoice({ customerEmail: customer?.email });

  const busy =
    state === "initializing" ||
    state === "initialized" ||
    state === "authenticating" ||
    state === "authenticated" ||
    state === "connecting" ||
    state === "disconnecting";
  const active = state !== "disconnected";

  const orbState: OrbState =
    state === "disconnected"
      ? "idle"
      : busy
        ? "connecting"
        : botSpeaking
          ? "speaking"
          : thinking
            ? "thinking"
            : "listening";

  // Read the live orbState inside the rAF loop without restarting it every state change.
  const orbStateRef = useRef<OrbState>(orbState);
  orbStateRef.current = orbState;
  const stageRef = useRef<HTMLDivElement>(null);

  // Imperative amplitude loop — drives bar heights + orb/ring scale from the live mic
  // (listening) and bot TTS (speaking) levels, without re-rendering React each frame.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const orb = stage.querySelector<HTMLElement>(".orb");
    const bars = Array.from(stage.querySelectorAll<HTMLElement>(".bars i"));
    const rings = Array.from(stage.querySelectorAll<HTMLElement>(".ring"));

    const reset = () => {
      if (orb) orb.style.transform = "";
      rings.forEach((r) => (r.style.transform = ""));
      bars.forEach((b) => (b.style.height = ""));
    };

    if (state === "disconnected") {
      reset();
      return;
    }

    let raf = 0;
    const loop = () => {
      const s = orbStateRef.current;
      let amp = 0;
      if (s === "listening") amp = Math.min(1, micLevelRef.current * GAIN);
      else if (s === "speaking") amp = Math.min(1, botLevelRef.current * GAIN);

      if (s === "listening" || s === "speaking") {
        bars.forEach((b, i) => {
          const j = Math.max(0.15, amp * (0.5 + Math.sin(Date.now() / 90 + i * 1.7) * 0.5));
          b.style.height = `${6 + j * 36}px`;
        });
        if (orb) orb.style.transform = `scale(${1 + amp * 0.06})`;
        rings.forEach((r, i) => (r.style.transform = `scale(${1 + amp * 0.05 * (i + 1)})`));
      } else {
        if (orb) orb.style.transform = "";
        rings.forEach((r) => (r.style.transform = ""));
      }
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(raf);
      reset();
    };
    // Restart only when the session goes active/inactive; state changes within a session
    // are read live via orbStateRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const caption =
    orbState === "listening"
      ? userText
        ? `“${userText}”`
        : "Say something — the orb follows your voice"
      : orbState === "thinking"
        ? "Checking your order… · running policy checks"
        : orbState === "speaking"
          ? botText
            ? `“${botText}”`
            : "Assistant speaking…"
          : orbState === "connecting"
            ? "Setting up the line…"
            : "Press the orb and just start talking — you can interrupt any time.";

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

      <BackButton />

      <div className="vstage-wrap">
        <div className="vstage" data-state={orbState} ref={stageRef}>
          <span className="ring r1" />
          <span className="ring r2" />
          <span className="ring r3" />
          <span className="gr g1" />
          <span className="gr g2" />
          <span className="arc" />
          <button
            type="button"
            className="orb"
            onClick={() => {
              if (orbState === "idle") void connect();
            }}
            disabled={busy}
            aria-label={orbState === "idle" ? "Start talking" : "Voice session active"}
          >
            <span className="micicon">
              <MicIcon />
            </span>
            <span className="bars">
              <i />
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
          </button>
        </div>

        <p className="vstate">{LABEL[orbState]}</p>
        <p className="vcap">{caption}</p>
        {error && <p className="verr">{error}</p>}

        <div className="vctrls">
          {active && (
            <button type="button" className="vcb red" onClick={disconnect}>
              <PhoneIcon />
              Hang up
            </button>
          )}
        </div>

        <p className="vfoot">
          Every decision is checked against our refund policy — and the assistant tells you exactly
          why.
        </p>
      </div>
    </div>
  );
}
