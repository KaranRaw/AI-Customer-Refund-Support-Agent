import { createContext, useContext, useState, type ReactNode } from "react";

import type { Customer } from "@/types";

interface SessionValue {
  customer: Customer | null;
  signIn: (customer: Customer) => void;
  signOut: () => void;
}

const STORAGE_KEY = "refundai.customer";
const SessionContext = createContext<SessionValue | null>(null);

function loadCustomer(): Customer | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Customer) : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [customer, setCustomer] = useState<Customer | null>(loadCustomer);

  function signIn(next: Customer) {
    setCustomer(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  function signOut() {
    setCustomer(null);
    localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <SessionContext.Provider value={{ customer, signIn, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}
