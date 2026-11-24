import { inject, onScopeDispose } from "vue";
import { createBrowserFfmpeg } from "@solodrama/ffmpeg/browser";

export type { BrowserFfmpegFactory, BrowserFfmpegCommand, BrowserFfmpegOptions, FfprobeData } from "@solodrama/ffmpeg/browser";

export function useNodeFfmpeg() {
  const getDirectory = inject<(() => string) | undefined>("workspaceDirectory", undefined);
  const lifetime = new AbortController();
  onScopeDispose(() => lifetime.abort());

  return (signal?: AbortSignal) => {
    if (!getDirectory) throw new Error("当前画布未提供工作区目录");
    return createBrowserFfmpeg(getDirectory(), signal ? AbortSignal.any([lifetime.signal, signal]) : lifetime.signal);
  };
}
