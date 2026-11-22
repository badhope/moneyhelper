import "./sw-register";
import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { RemotePairView } from "./components/RemotePairView";
import { ErrorBoundary } from "./lib/ErrorBoundary";
import { ThemeProvider } from "./lib/theme";
import { I18nProvider } from "./lib/i18n";
import { setQueryClient } from "@/lib/store";
import { Toaster } from "@/lib/toast";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
setQueryClient(queryClient);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            {window.location.pathname === "/remote" || window.location.pathname === "/remote/" ? (
              <RemotePairView />
            ) : (
              <App />
            )}
            <Toaster />
          </ThemeProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </I18nProvider>
  </React.StrictMode>,
);

