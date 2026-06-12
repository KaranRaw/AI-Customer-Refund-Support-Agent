import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { SessionProvider } from "@/lib/session";
import { AdminPage } from "@/pages/AdminPage";
import { ChatPage } from "@/pages/ChatPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { VoicePage } from "@/pages/VoicePage";

export function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LoginPage />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/voice" element={<VoicePage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
