export type ComfyNodeTarget = [nodeId: string, field: string];
export type ComfyWorkflowMapping = {
  prompt?: ComfyNodeTarget;
  negativePrompt?: ComfyNodeTarget;
  images?: ComfyNodeTarget[];
  width?: ComfyNodeTarget;
  height?: ComfyNodeTarget;
  size?: ComfyNodeTarget;
  ratio?: ComfyNodeTarget;
  duration?: ComfyNodeTarget;
  steps?: ComfyNodeTarget;
  seed?: ComfyNodeTarget;
  prefix?: ComfyNodeTarget;
};

type Candidate = { nodeId: string; field: string; key: string; value: unknown; classType: string; title: string };

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isLinkedInput(value: unknown) {
  return Array.isArray(value) && value.length === 2 && typeof value[0] === "string" && typeof value[1] === "number";
}

function nodeCandidates(workflow: Record<string, unknown>): Candidate[] {
  const candidates: Candidate[] = [];
  for (const [nodeId, rawNode] of Object.entries(workflow)) {
    if (!/^\d+$/.test(nodeId) || !isObject(rawNode) || !isObject(rawNode.inputs)) continue;
    const classType = typeof rawNode.class_type === "string" ? rawNode.class_type : "";
    const meta = isObject(rawNode._meta) ? rawNode._meta : {};
    const title = typeof meta.title === "string" ? meta.title : "";
    for (const [key, value] of Object.entries(rawNode.inputs)) {
      if (!isLinkedInput(value)) candidates.push({ nodeId, field: key, key, value, classType, title });
    }
  }
  return candidates;
}

function findCandidate(candidates: Candidate[], fields: RegExp) {
  return candidates.find(item => fields.test(item.key));
}

export function inferComfyMapping(workflow: Record<string, unknown>): ComfyWorkflowMapping {
  const candidates = nodeCandidates(workflow);
  const promptScore = (item: Candidate) => {
    if (typeof item.value !== "string") return -1;
    let score = 0;
    if (/^(text|prompt|positive|positive_prompt|negative|negative_prompt)$/i.test(item.key)) score = 100;
    else if (/^PrimitiveString/i.test(item.classType) && item.key === "value") score = 90;
    else if (/^(prompt|request|description|提示词|描述|台词)$/i.test(item.title.trim())) score = 80;
    else if (/prompt|request|description|提示词|描述|台词/i.test(item.title)) score = 40;
    else if (/string|text|prompt/i.test(item.classType)) score = 30;
    else if (item.key === "value") score = 20;
    if (/negative|负面|负向/i.test(`${item.key} ${item.title} ${item.classType}`)) score -= 200;
    return score;
  };
  const promptCandidates = candidates.filter(item => promptScore(item) >= 20);
  const negative = promptCandidates.filter(item => /negative|负面|负向/i.test(`${item.key} ${item.title} ${item.classType}`))
    .sort((left, right) => promptScore(right) - promptScore(left))[0];
  const prompt = promptCandidates.filter(item => item !== negative)
    .sort((left, right) => promptScore(right) - promptScore(left))[0];
  const images = candidates
    .filter(item => /^(image|image_?\d+|init_image|start_image|end_image|reference_image)$/i.test(item.key) && typeof item.value === "string")
    .sort((left, right) => left.key.localeCompare(right.key, undefined, { numeric: true }))
    .map(item => [item.nodeId, item.field] as ComfyNodeTarget);
  const mapping: ComfyWorkflowMapping = {};
  if (prompt) mapping.prompt = [prompt.nodeId, prompt.field];
  if (negative && negative !== prompt) mapping.negativePrompt = [negative.nodeId, negative.field];
  if (images.length) mapping.images = images;
  const target = (fields: RegExp) => {
    const item = findCandidate(candidates, fields);
    return item ? [item.nodeId, item.field] as ComfyNodeTarget : undefined;
  };
  const width = target(/^width$/i); if (width) mapping.width = width;
  const height = target(/^height$/i); if (height) mapping.height = height;
  const size = target(/^(size|resolution|megapixels)$/i); if (size) mapping.size = size;
  const ratio = target(/^(ratio|aspect_ratio|aspectRatio)$/i); if (ratio) mapping.ratio = ratio;
  const duration = target(/^(duration|duration_seconds|seconds)$/i); if (duration) mapping.duration = duration;
  const steps = target(/^(steps|sample_steps)$/i); if (steps) mapping.steps = steps;
  const seed = target(/^(seed|noise_seed)$/i); if (seed) mapping.seed = seed;
  const prefix = target(/^(filename_prefix|prefix)$/i); if (prefix) mapping.prefix = prefix;
  return mapping;
}

type ComfyUiLink = {
  id: number;
  source: string;
  sourceSlot: number;
  target: string;
  targetSlot: number;
  type: string;
};

export type ComfyWorkflowConversion = {
  workflow: Record<string, unknown>;
  warnings: string[];
  format: "ui" | "api";
};

function uiNodeType(node: Record<string, unknown>) {
  return typeof node.type === "string" ? node.type : "";
}

function nodeMode(node: Record<string, unknown>) {
  const mode = Number(node.mode);
  return Number.isFinite(mode) ? mode : 0;
}

function nodeTitle(node: Record<string, unknown>) {
  if (typeof node.title === "string" && node.title.trim()) return node.title.trim();
  const meta = isObject(node._meta) ? node._meta : {};
  return typeof meta.title === "string" && meta.title.trim() ? meta.title.trim() : uiNodeType(node);
}

function normalizedLinks(value: unknown): Map<number, ComfyUiLink> {
  const links = new Map<number, ComfyUiLink>();
  if (!Array.isArray(value)) return links;
  for (const item of value) {
    if (Array.isArray(item) && item.length >= 5) {
      const id = Number(item[0]);
      const source = String(item[1]);
      const sourceSlot = Number(item[2]);
      const target = String(item[3]);
      const targetSlot = Number(item[4]);
      const type = typeof item[5] === "string" ? item[5] : "";
      if (Number.isFinite(id) && Number.isFinite(sourceSlot) && Number.isFinite(targetSlot)) links.set(id, { id, source, sourceSlot, target, targetSlot, type });
      continue;
    }
    if (!isObject(item)) continue;
    const id = Number(item.id);
    const source = String(item.origin_id ?? item.source_id ?? "");
    const sourceSlot = Number(item.origin_slot ?? item.source_slot);
    const target = String(item.target_id ?? "");
    const targetSlot = Number(item.target_slot);
    const type = typeof item.type === "string" ? item.type : "";
    if (source && Number.isFinite(id) && Number.isFinite(sourceSlot) && Number.isFinite(targetSlot)) links.set(id, { id, source, sourceSlot, target, targetSlot, type });
  }
  return links;
}

function widgetEntries(node: Record<string, unknown>) {
  const inputs = Array.isArray(node.inputs) ? node.inputs : [];
  const widgetInputs = inputs.flatMap(item => {
    if (!isObject(item) || !isObject(item.widget) || typeof item.widget.name !== "string") return [];
    return [{ name: item.widget.name, input: item }];
  });
  const values = node.widgets_values;
  const result: { name: string; value: unknown }[] = [];
  if (Array.isArray(values)) {
    widgetInputs.forEach((entry, index) => {
      if (index < values.length) result.push({ name: entry.name, value: values[index] });
    });
  } else if (isObject(values)) {
    for (const entry of widgetInputs) {
      if (Object.hasOwn(values, entry.name)) result.push({ name: entry.name, value: values[entry.name] });
    }
  }
  return result;
}

function convertUiWorkflow(value: Record<string, unknown>): ComfyWorkflowConversion {
  if (!Array.isArray(value.nodes) || !Array.isArray(value.links)) throw new Error("ComfyUI 界面工作流必须包含 nodes 和 links 数组");
  const nodes = new Map<string, Record<string, unknown>>();
  for (const node of value.nodes) {
    if (!isObject(node)) continue;
    const id = Number(node.id);
    if (Number.isFinite(id)) nodes.set(String(id), node);
  }
  const links = normalizedLinks(value.links);
  const warnings = new Set<string>();
  const addWarning = (message: string) => { if (warnings.size < 20) warnings.add(message); };

  function resolveLink(linkId: unknown, visited = new Set<number>()): unknown {
    const id = Number(linkId);
    if (!Number.isFinite(id)) return undefined;
    if (visited.has(id)) { addWarning(`检测到循环连线 ${id}，已跳过`); return undefined; }
    visited.add(id);
    const link = links.get(id);
    if (!link) { addWarning(`连线 ${id} 不存在，已跳过`); return undefined; }
    const source = nodes.get(link.source);
    if (!source) { addWarning(`连线 ${id} 的源节点 ${link.source} 不存在，已跳过`); return undefined; }
    const type = uiNodeType(source);
    const mode = nodeMode(source);
    if (mode === 2) { addWarning(`节点 ${link.source} 已静音，相关输入已跳过`); return undefined; }
    if (type === "PrimitiveNode") {
      const values = source.widgets_values;
      if (Array.isArray(values)) return values[0];
      if (isObject(values)) return values.value;
      return undefined;
    }
    if (type === "Reroute") {
      const inputs = Array.isArray(source.inputs) ? source.inputs.filter(isObject) : [];
      const upstream = inputs.find(input => input.link != null);
      return upstream ? resolveLink(upstream.link, visited) : undefined;
    }
    if (mode === 4) {
      const inputs = Array.isArray(source.inputs) ? source.inputs.filter(isObject) : [];
      const passthrough = inputs.find(input => input.link != null && (!link.type || input.type === link.type))
        ?? inputs.find(input => input.link != null);
      if (passthrough) return resolveLink(passthrough.link, visited);
      addWarning(`旁路节点 ${link.source} 没有可传递的输入`);
      return undefined;
    }
    if (type === "Note" || type === "MarkdownNote") return undefined;
    return [link.source, link.sourceSlot] as [string, number];
  }

  const workflow: Record<string, unknown> = {};
  for (const [nodeId, node] of [...nodes.entries()].sort(([left], [right]) => Number(left) - Number(right))) {
    const type = uiNodeType(node);
    const mode = nodeMode(node);
    if (!type || ["PrimitiveNode", "Reroute", "Note", "MarkdownNote"].includes(type)) continue;
    if (mode === 2 || mode === 4) continue;
    if (type.startsWith("workflow>")) { addWarning(`子图节点 ${nodeId} 暂不支持自动展开`); continue; }
    const inputs: Record<string, unknown> = {};
    const widgets = new Map(widgetEntries(node).map(item => [item.name, item.value]));
    const inputList = Array.isArray(node.inputs) ? node.inputs.filter(isObject) : [];
    for (const input of inputList) {
      const field = typeof input.name === "string" ? input.name : "";
      if (!field) continue;
      if (input.link != null) {
        const resolved = resolveLink(input.link);
        if (resolved !== undefined) inputs[field] = resolved;
      } else if (isObject(input.widget) && typeof input.widget.name === "string" && widgets.has(input.widget.name)) {
        inputs[input.widget.name] = widgets.get(input.widget.name);
      }
    }
    if (!inputList.some(input => isObject(input.widget)) && isObject(node.widgets_values)) {
      for (const [field, item] of Object.entries(node.widgets_values)) {
        if (field !== "videopreview" && !field.startsWith("choose ")) inputs[field] = item;
      }
      if (Object.keys(node.widgets_values).length) addWarning(`节点 ${nodeId}（${type}）缺少控件名称元数据，已按对象键导入，请检查输入映射`);
    }
    workflow[nodeId] = { class_type: type, inputs, _meta: { title: nodeTitle(node) } };
  }
  if (!Object.keys(workflow).length) throw new Error("没有从 ComfyUI 界面工作流中转换出可执行节点");
  return { workflow, warnings: [...warnings], format: "ui" };
}

export function parseComfyJsonWithReport(text: string): ComfyWorkflowConversion {
  let value: unknown;
  try { value = JSON.parse(text); }
  catch { throw new Error("JSON 文件格式错误，请选择有效的 ComfyUI 工作流文件"); }
  if (!isObject(value)) throw new Error("ComfyUI 工作流必须是 JSON 对象");
  if (Array.isArray(value.nodes) && Array.isArray(value.links)) return convertUiWorkflow(value);
  return { workflow: value, warnings: [], format: "api" };
}

export function parseComfyJson(text: string): Record<string, unknown> {
  return parseComfyJsonWithReport(text).workflow;
}
