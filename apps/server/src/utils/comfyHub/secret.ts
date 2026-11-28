import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { join } from "node:path";
import { lstat, readFile, writeAtomic } from "@solodrama/file";
import { z } from "zod";

const payloadSchema = z.record(z.string(), z.json());
const cipherSchema = z.string().max(16 * 1024 * 1024).regex(/^v1\.[A-Za-z0-9+/]{16}\.[A-Za-z0-9+/]{22}==\.[A-Za-z0-9+/]+={0,2}$/);
const aad = Buffer.from("solodrama:comfyHub:v1");

function decodeKey(value: string) {
  const key = Buffer.from(value, "base64");
  if (key.length !== 32 || key.toString("base64") !== value) throw Object.assign(new Error("云端算力凭据密钥无效"), { status: 503 });
  return key;
}

export function createComfyHubSecret(directory: string) {
  let keyPromise: Promise<Buffer> | undefined;
  const keyPath = join(directory, "secret.key");
  async function readKey(create: boolean) {
    let info = await lstat(keyPath).catch((cause: NodeJS.ErrnoException) => {
      if (cause.code === "ENOENT") return null;
      throw cause;
    });
    if (!info && create) {
      try { await writeAtomic(keyPath, randomBytes(32).toString("base64"), { exclusive: true, mode: 0o600 }); }
      catch (cause) { if ((cause as NodeJS.ErrnoException).code !== "EEXIST") throw cause; }
      info = await lstat(keyPath);
    }
    if (!info) throw Object.assign(new Error("云端算力凭据密钥缺失，请恢复数据目录中的 secret.key"), { status: 503 });
    if (!info.isFile() || info.isSymbolicLink() || info.size > 128) throw Object.assign(new Error("云端算力凭据密钥文件无效"), { status: 503 });
    if (process.platform !== "win32" && (info.mode & 0o077) !== 0) throw Object.assign(new Error("云端算力凭据密钥文件权限必须为 0600"), { status: 503 });
    return decodeKey((await readFile(keyPath, "utf8")).trim());
  }
  function key(create: boolean) {
    if (!keyPromise) {
      const opening = readKey(create);
      keyPromise = opening;
      opening.catch(() => { if (keyPromise === opening) keyPromise = undefined; });
    }
    return keyPromise;
  }
  return {
    async seal(payload: Record<string, unknown>) {
      const data = JSON.stringify(payloadSchema.parse(payload));
      const iv = randomBytes(12);
      const cipher = createCipheriv("aes-256-gcm", await key(true), iv);
      cipher.setAAD(aad);
      const encrypted = Buffer.concat([cipher.update(data, "utf8"), cipher.final()]);
      return ["v1", iv.toString("base64"), cipher.getAuthTag().toString("base64"), encrypted.toString("base64")].join(".");
    },
    async open(value: string): Promise<Record<string, unknown>> {
      const parsed = cipherSchema.safeParse(value);
      if (!parsed.success) throw Object.assign(new Error("云端算力凭据密文无效"), { status: 503 });
      const [, ivText, tagText, encryptedText] = parsed.data.split(".");
      const iv = Buffer.from(ivText!, "base64");
      const tag = Buffer.from(tagText!, "base64");
      const encrypted = Buffer.from(encryptedText!, "base64");
      const decipher = createDecipheriv("aes-256-gcm", await key(false), iv);
      decipher.setAAD(aad);
      decipher.setAuthTag(tag);
      try {
        const data = Buffer.concat([decipher.update(encrypted), decipher.final()]).toString("utf8");
        return payloadSchema.parse(JSON.parse(data));
      } catch {
        throw Object.assign(new Error("云端算力凭据无法解密，请检查数据目录中的 secret.key"), { status: 503 });
      }
    },
  };
}