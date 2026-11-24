import { projectLanguageOptions } from "@solodrama/node-shared/projectSettings";

export const languageOptions = projectLanguageOptions.map(item => ({ label: item.label, value: item.value }));
export const sampleRateOptions = [8000, 16000, 24000, 48000];
export const formatOptions = ["wav", "mp3", "pcm", "ogg_opus"];
