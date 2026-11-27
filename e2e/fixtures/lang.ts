/**
 * Which language is a reply in? Speech-to-text and answers vary, so the suite never compares whole sentences.
 * English has no Devanagari. Hindi and Marathi share the script, so they are told apart by very common
 * function words (verb "to be", postpositions) that each language uses and the other does not.
 */
const DEVANAGARI = /[ऀ-ॿ]/;
const HI = new Set(["है", "हैं", "में", "से", "का", "की", "के", "सभी", "मैं", "सिर्फ़", "कोई", "हुए", "नहीं"]);
const MR = new Set(["आहे", "आहेत", "पैकी", "सध्या", "मी", "फक्त", "चे", "ची", "मिनिटांपासून", "सर्व", "आणि", "झाली", "नाही"]);

export type Lang = "en" | "hi" | "mr" | "unknown";

export function replyLanguage(text: string): Lang {
  if (!DEVANAGARI.test(text)) return /[a-z]{3,}/i.test(text) ? "en" : "unknown";
  const words = text.split(/[\s,.।!?:;()"]+/).filter(Boolean);
  const hi = words.filter((w) => HI.has(w)).length, mr = words.filter((w) => MR.has(w)).length;
  return hi > mr ? "hi" : mr > hi ? "mr" : "unknown";
}

export const script = (text: string): "devanagari" | "latin" | "none" =>
  DEVANAGARI.test(text) ? "devanagari" : /[a-z]/i.test(text) ? "latin" : "none";

/** "pi 3", "pi-3", "Pi 3", "पाई 3" all name the same device. */
export const mentionsDevice = (text: string, device: string): boolean => {
  const n = device.split("-")[1];
  return new RegExp(`(pi|पाई)[\\s-]?${n}(?!\\d)`, "i").test(text);
};
