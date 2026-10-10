// UI strings live in UTF-8 JSON files beside this one, never in code (BRIEF §11).
import ar from "./ar.json";
import en from "./en.json";
import fr from "./fr.json";

export const LOCALES = ["ar", "en", "fr"] as const;
export type Locale = (typeof LOCALES)[number];
export type StringKey = keyof typeof en;

const STRINGS: Record<Locale, Record<StringKey, string>> = { ar, en, fr };

export const LOCALE_NAMES: Record<Locale, string> = { ar: "العربية", en: "English", fr: "Français" };

export function dir(locale: Locale): "rtl" | "ltr" {
  return locale === "ar" ? "rtl" : "ltr";
}

export function t(locale: Locale, key: StringKey): string {
  return STRINGS[locale][key];
}

/** The same page in another language: swap the first path segment. */
export function switchLocale(pathname: string, to: Locale): string {
  const parts = pathname.split("/");
  parts[1] = to;
  return parts.join("/") || `/${to}/`;
}
