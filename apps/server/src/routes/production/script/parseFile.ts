import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";
import { readDocument } from "@/utils/documents";

export default Router().post("/", validateFields({
  fileName: z.string().trim().min(1).max(255),
  mimeType: z.string().max(256).optional(),
  data: z.string().min(1).max(28 * 1024 * 1024),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const bytes = Buffer.from(req.body.data, "base64");
  if (!bytes.length || bytes.length > 20 * 1024 * 1024) throw Object.assign(new Error("剧本文件不能为空且不能超过 20 MB"), { status: 400 });
  const markdown = await readDocument(req.body.fileName, bytes, req.body.mimeType);
  const text = markdown.toString("utf8");
  if (Buffer.byteLength(text, "utf8") > 8 * 1024 * 1024) throw Object.assign(new Error("剧本文本超过 8 MB，请先拆分文件"), { status: 413 });
  res.set("Cache-Control", "no-store").json(success({ fileName: req.body.fileName, text, length: text.length }));
});