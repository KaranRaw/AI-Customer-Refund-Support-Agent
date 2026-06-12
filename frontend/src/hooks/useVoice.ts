import { useEffect, useRef, useState } from "react";

import { PipecatClient, type TransportState } from "@pipecat-ai/client-js";
import { ProtobufFrameSerializer, WebSocketTransport } from "@pipecat-ai/websocket-transport";

import { voiceLiveUrl } from "@/api/client";

interface UseVoiceOptions {
  customerEmail?: string | null;
  /** Called once per completed user/bot turn — lets the chat append the spoken turns. */
  onUserTurn?: (text: string) => void;
  onBotTurn?: (text: string) => void;
}

/**
 * Owns the Pipecat client lifecycle for a live-voice session. Shared by the /voice
 * page and the in-chat voice modal. The client is created lazily on first connect
 * (NOT in useState) so React StrictMode can't disconnect a fresh client on mount.
 */
export function useVoice(options: UseVoiceOptions) {
  const [state, setState] = useState<TransportState>("disconnected");
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [userText, setUserText] = useState("");
  const [botText, setBotText] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Live amplitudes (0..1) for the orb animation. Kept in refs, NOT state: the audio-level
  // callbacks fire ~20x/sec and driving React state that fast would thrash re-renders. The
  // page reads these in a requestAnimationFrame loop instead. Read-only — they never touch
  // mic capture, so they can't affect the call.
  const micLevelRef = useRef(0);
  const botLevelRef = useRef(0);

  const clientRef = useRef<PipecatClient | null>(null);
  // Latest options in a ref so the once-created client callbacks always see fresh values.
  const optsRef = useRef(options);
  optsRef.current = options;

  function getClient(): PipecatClient {
    if (!clientRef.current) {
      clientRef.current = new PipecatClient({
        transport: new WebSocketTransport({
          serializer: new ProtobufFrameSerializer(),
          recorderSampleRate: 16000,
          playerSampleRate: 24000,
        }),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onTransportStateChanged: (s) => setState(s),
          onBotStartedSpeaking: () => {
            setBotSpeaking(true);
            setThinking(false); // the reply is now audible — leave the thinking state
          },
          onBotStoppedSpeaking: () => setBotSpeaking(false),
          onLocalAudioLevel: (level) => {
            micLevelRef.current = level;
          },
          onRemoteAudioLevel: (level) => {
            botLevelRef.current = level;
          },
          onUserTranscript: (data) => {
            if (data.final) {
              setUserText(data.text);
              setBotText("");
              setThinking(false); // user is speaking again — back to listening
              optsRef.current.onUserTurn?.(data.text);
            }
          },
          // The agent reply arrives as an RTVI server message — speech is injected via
          // TTSSpeakFrame, which bypasses the LLM-text frames onBotTranscript watches.
          onServerMessage: (data) => {
            const raw = data as {
              type?: string;
              text?: string;
              data?: { type?: string; text?: string };
            };
            const payload = raw?.data ?? raw;
            if (payload?.type === "thinking") {
              setThinking(true); // agent started running, before the spoken reply
            } else if (payload?.type === "bot_reply" && payload.text) {
              setBotText(payload.text);
              optsRef.current.onBotTurn?.(payload.text);
            }
          },
        },
      });
    }
    return clientRef.current;
  }

  useEffect(() => {
    return () => {
      void clientRef.current?.disconnect();
    };
  }, []);

  async function connect(conversationId?: number | null) {
    setError(null);
    setUserText("");
    setBotText("");
    setThinking(false);
    micLevelRef.current = 0;
    botLevelRef.current = 0;
    // Guard: if called straight from onClick the arg is a MouseEvent, not an id.
    const cid = typeof conversationId === "number" ? conversationId : null;
    try {
      await getClient().connect({
        wsUrl: voiceLiveUrl(optsRef.current.customerEmail, cid),
      });
    } catch {
      setError("Couldn't start voice — check mic permission and try again.");
    }
  }

  function disconnect() {
    void clientRef.current?.disconnect();
  }

  return {
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
  };
}
