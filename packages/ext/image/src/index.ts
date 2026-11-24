import { defineExt } from "@solodrama/ext-scaffold/runtime";
import metadata from "./metadata";

export default defineExt({ ...metadata, load: () => import("./index.vue") });
