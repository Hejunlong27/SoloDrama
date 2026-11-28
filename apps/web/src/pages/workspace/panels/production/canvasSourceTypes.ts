import type { ProductionCanvasBinding } from "@solodrama/production";

export type CanvasSourceKind = "script" | "image" | "video" | "audio";
export type CanvasSuggestedTarget = "episode" | "character" | "location" | "prop" | "shot" | "asset";
export type CanvasSource = {
  id: string;
  sourceHash: string;
  canvasPath: string;
  canvasName: string;
  nodeId: string;
  kind: CanvasSourceKind;
  label: string;
  typeLabel: string;
  preview?: string;
  textPath?: string;
  mediaPath?: string;
  mediaMimeType?: string;
  prompt?: string;
  model?: string;
  suggestedTarget: CanvasSuggestedTarget;
  binding?: ProductionCanvasBinding;
};
export type CanvasSourcePreview = {
  sources: CanvasSource[];
  canvasCount: number;
  boundCount: number;
  skippedFiles: number;
};
export type CanvasImportRequest = {
  source: CanvasSource;
  targetType?: CanvasSuggestedTarget;
  targetId?: string;
};