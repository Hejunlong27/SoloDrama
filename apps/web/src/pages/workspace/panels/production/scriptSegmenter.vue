<template>
  <section class="scriptSegmenter">
    <div class="segmenterHeader"><div><h3>剧本正文</h3><p>可直接输入一句话、故事大纲、小说或剧本，也可以上传文件后按章节切段。</p></div><div class="headerActions"><input ref="fileInput" class="fileInput" type="file" accept=".txt,.md,.markdown,.docx,.pdf,.epub" @change="uploadFile" /><el-button :loading="uploading" @click="fileInput?.click()">上传剧本文件</el-button><el-button :disabled="!text.trim()" @click="splitText">识别章节并切段</el-button></div></div>
    <el-input v-model="text" type="textarea" :rows="9" maxlength="8000000" showWordLimit placeholder="输入一句话创意、故事大纲或粘贴完整剧本……" />
    <div class="splitControls"><span>目标片段长度</span><el-input-number v-model="targetChars" :min="2000" :max="30000" :step="1000" /><span>字</span><el-button type="primary" @click="splitText">生成分段</el-button><span v-if="sourceName" class="sourceName">来源：{{ sourceName }}</span></div>
    <div v-if="segments.length" class="segmentList">
      <div class="segmentSummary"><strong>{{ segments.length }}</strong><span>个片段 · {{ detectedChapterCount }} 个章节 · 共 {{ text.length.toLocaleString() }} 字。先拆分，不自动解析全文。</span></div>
      <el-scrollbar maxHeight="360px">
        <article v-for="(segment, index) in segments" :key="segment.id" class="segmentCard" :class="{ active: index === activeIndex }" @click="activeIndex = index">
          <div class="segmentIndex">{{ String(index + 1).padStart(2, "0") }}</div>
          <div class="segmentBody"><strong>{{ segment.title }}</strong><small>{{ segment.text.length.toLocaleString() }} 字</small><p>{{ compact(segment.text, 180) }}</p></div>
          <el-button size="small" @click.stop="useSegment(segment)">填入创作区</el-button>
        </article>
      </el-scrollbar>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { ElMessage } from "element-plus";
import http from "@/lib/http";

type Segment = { id: string; title: string; text: string };
const text = defineModel<string>({ default: "" });
const fileInput = ref<HTMLInputElement>();
const uploading = ref(false);
const sourceName = ref("");
const targetChars = ref(10000);
const segments = ref<Segment[]>([]);
const activeIndex = ref(0);
const detectedChapterCount = ref(0);
const chapterPattern = /^(?:第[零〇一二三四五六七八九十百千万两\d]+[章节卷回部集幕]|卷[零〇一二三四五六七八九十百千万两\d]+|序章|楔子|引子|尾声|终章|番外(?:篇)?|Chapter\s+\d+|Part\s+\d+).{0,80}$/gim;

function compact(value: string, max: number) { return value.replace(/\s+/g, " ").trim().slice(0, max); }
function splitByChapters(value: string) {
  const matches = [...value.matchAll(chapterPattern)];
  if (!matches.length) return [{ title: "全文", text: value }];
  const chapters: { title: string; text: string }[] = [];
  if (matches[0]!.index! > 0) chapters.push({ title: "开篇", text: value.slice(0, matches[0]!.index) });
  for (const [index, match] of matches.entries()) {
    const start = match.index!;
    const end = matches[index + 1]?.index ?? value.length;
    chapters.push({ title: match[0].trim().slice(0, 100), text: value.slice(start, end).trim() });
  }
  return chapters;
}
function splitChapter(title: string, value: string) {
  if (value.length <= targetChars.value) return [{ title, text: value }];
  const paragraphs = value.split(/(?<=\n)\s*(?=\S)/);
  const chunks: { title: string; text: string }[] = [];
  let current = "";
  for (const paragraph of paragraphs) {
    if (paragraph.length > targetChars.value) {
      if (current.trim()) { chunks.push({ title: `${title}（${chunks.length + 1}）`, text: current.trim() }); current = ""; }
      for (let offset = 0; offset < paragraph.length; offset += targetChars.value) chunks.push({ title: `${title}（${chunks.length + 1}）`, text: paragraph.slice(offset, offset + targetChars.value) });
      continue;
    }
    if (current.length + paragraph.length > targetChars.value) {
      chunks.push({ title: `${title}（${chunks.length + 1}）`, text: current.trim() });
      current = "";
    }
    current += paragraph;
  }
  if (current.trim()) chunks.push({ title: `${title}（${chunks.length + 1}）`, text: current.trim() });
  return chunks;
}
function splitText() {
  if (!text.value.trim()) return ElMessage.warning("请先输入或上传剧本");
  const chapters = splitByChapters(text.value);
  detectedChapterCount.value = chapters.length;
  segments.value = chapters.flatMap(chapter => splitChapter(chapter.title, chapter.text)).map((segment, index) => ({ id: `${index}-${segment.title}`, ...segment }));
  activeIndex.value = 0;
}
function useSegment(segment: Segment) {
  text.value = segment.text;
  ElMessage.success(`已填入：${segment.title}`);
}
async function uploadFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) return ElMessage.error("文件不能超过 20 MB");
  uploading.value = true;
  try {
    const data = await fileToBase64(file);
    const result = await http<{ text: string }>({ method: "POST", url: "/api/production/script/parseFile", data: { fileName: file.name, mimeType: file.type || undefined, data }, timeout: 120000 });
    text.value = result.text;
    sourceName.value = file.name;
    await nextTick();
    splitText();
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "剧本文件解析失败"); }
  finally { uploading.value = false; }
}
function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error ?? new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}
</script>

<style scoped lang="scss">
.scriptSegmenter { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 14px; background: var(--el-bg-color-overlay); }.segmenterHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }.segmenterHeader h3, .segmenterHeader p { margin: 0; }.segmenterHeader h3 { font-size: 16px; }.segmenterHeader p { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 11px; }.headerActions { display: flex; gap: 8px; }.fileInput { display: none; }.splitControls { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-secondary); font-size: 11px; }.sourceName { margin-left: auto; }.segmentList { display: grid; gap: 8px; }.segmentSummary { display: flex; align-items: baseline; gap: 7px; }.segmentSummary strong { font-size: 22px; }.segmentSummary span { color: var(--el-text-color-secondary); font-size: 11px; }.segmentCard { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 10px; margin-bottom: 6px; padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; cursor: pointer; }.segmentCard.active, .segmentCard:hover { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }.segmentIndex { color: var(--el-color-primary); font-size: 11px; }.segmentBody { display: grid; min-width: 0; gap: 2px; }.segmentBody strong { font-size: 12px; }.segmentBody small { color: var(--el-text-color-secondary); font-size: 9px; }.segmentBody p { overflow: hidden; margin: 0; color: var(--el-text-color-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }@media(max-width:760px){.segmenterHeader{flex-direction:column}.headerActions{flex-wrap:wrap}.splitControls{flex-wrap:wrap}.sourceName{width:100%;margin-left:0}.segmentCard{grid-template-columns:30px minmax(0,1fr)}.segmentCard>.el-button{grid-column:2;justify-self:start}}
</style>

