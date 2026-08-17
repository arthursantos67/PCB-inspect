import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import { I18nProvider } from "@/contexts/I18nContext";
import { QueryProvider } from "@/providers/QueryProvider";
import { serverApiUrl } from "@/lib/runtime-config";

// The API address is published to the browser below, read from the environment on every
// request. Without this the value would be inlined into the bundle when the production image
// is built (see lib/runtime-config.ts), and an operator changing `API_PORT` in their `.env`
// would have no way to make the app follow.
export const dynamic = "force-dynamic";

// Archivo is a grotesque cut for signage and industrial print: sturdy at 12px in a dense
// table, and tight enough at display weights to carry a heading without a second family.
// IBM Plex Mono is the instrument face — every count, rate, identifier and axis tick is set
// in it, which is what makes a number read as a measurement rather than as prose.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PCB-Inspect",
  description: "Local PCB defect inspection dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // The font variables are declared on <html>, not <body>: `html { font-family: var(--font-sans) }`
    // in globals.css resolves them there, and a var that is only defined one level lower makes the
    // whole declaration invalid at computed-value time, silently dropping the page to Times.
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <head>
        <script
          // Runs before any client component, so `apiUrl()` never sees an undefined global.
          dangerouslySetInnerHTML={{
            __html: `window.__PCB_INSPECT_API_URL__=${JSON.stringify(serverApiUrl())}`,
          }}
        />
      </head>
      <body className="antialiased">
        <QueryProvider>
          <AuthProvider>
            <I18nProvider>{children}</I18nProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
