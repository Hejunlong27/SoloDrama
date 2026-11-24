/// <reference path="./types.d.ts" />

import opencodeGo from "./src/language/opencodeGo";
import commandCode from "./src/language/commandCode";
import deepSeek from "./src/language/deepSeek";
import compshare from "./src/media/compshare";
import solodramaComfy from "./src/media/solodramaComfy";
import solodramaComfyCloud from "./src/media/solodramaComfyCloud";
import solodramaRunningHub from "./src/media/solodramaRunningHub";
import solodramaRunningHubClosed from "./src/media/solodramaRunningHubClosed";
import solodramaTts from "./src/media/solodramaTts";

export type Provider = ProviderDefinition;
export type ProviderPrice = NonNullable<Awaited<ReturnType<NonNullable<Provider["getPrice"]>>>>;
export type ProviderPriceRequest = Parameters<NonNullable<Provider["getPrice"]>>[0];
export type ProviderPriceReference = NonNullable<ProviderPriceRequest["images"]>[number];
export type ProviderBalance = Awaited<ReturnType<NonNullable<Provider["getBalance"]>>>;
export type ProviderTools = ProviderContext["tool"];
export type ProviderTaskData = Parameters<NonNullable<ProviderContext["saveTaskData"]>>[0];
export type AudioConvertOptions = Parameters<ProviderTools["audio"]["convert"]>[1];
export type { FfmpegFactory, FfmpegCommand } from "@solodrama/ffmpeg/types";

export const languageProviders = [opencodeGo, commandCode, deepSeek] as const;
export const mediaProviders = [solodramaComfy, solodramaComfyCloud, solodramaRunningHub, solodramaRunningHubClosed, compshare, solodramaTts] as const;
