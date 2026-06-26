import type { Metadata } from "next";
import { Newsreader, Public_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/**
 * Classical serif display face — headings and assistant voice.
 * Exposed as --font-serif CSS custom property.
 * req: frontend-shell-017
 */
const newsreader = Newsreader({
  variable: "--font-serif",
  subsets: ["latin"],
  display: "swap",
  // Include italic for literary/philosophical tone (common in serif display usage)
  style: ["normal", "italic"],
});

/**
 * Quiet humanist sans-serif — UI labels, body text, chrome.
 * Exposed as --font-sans CSS custom property; applied to <body> as the base face.
 * req: frontend-shell-017
 */
const publicSans = Public_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

/**
 * Monospace — tokens, ids, metadata fields.
 * Exposed as --font-mono CSS custom property.
 * req: frontend-shell-017
 */
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Philosophy School",
  description: "A conversational learning environment for philosophy.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${publicSans.variable} ${jetbrainsMono.variable}`}
    >
      {/*
       * The base font-sans class is applied via the Tailwind @layer base rule in globals.css
       * (html { @apply font-sans; }), which resolves to --font-sans = Public Sans.
       * No PostHog / analytics SDK is loaded here — frontend-shell-022.
       */}
      <body>{children}</body>
    </html>
  );
}
