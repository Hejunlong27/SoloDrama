const rules = [
  {
    type: "input",
    field: "apiKey" as const,
    title: "OpenCode API Key",
    value: "",
    props: { type: "password", showPassword: true, autocomplete: "off" },
  },
] as const;

export default {
  id: "opencodeGo" as const,
  label: "OpenCode Go（Token Plan）",
  icon: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3QgeD0iNCIgeT0iNCIgd2lkdGg9IjU2IiBoZWlnaHQ9IjU2IiByeD0iMTQiIGZpbGw9IiMwYzBjMGMiLz48cGF0aCBkPSJNMTggMjJsMTQgMTQgMTQtMTRNMzIgMzZ2MTgiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzZiOGZmZiIgc3Ryb2tlLXdpZHRoPSI1IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48L3N2Zz4=",
  version: "2.0.0",
  apiUrl: "https://opencode.ai/zen/go/v1",
  protocol: "openai-completions",
  headers: {
    "User-Agent": "SoloDrama/1.0",
    "x-opencode-session": "solodrama",
  },
  readme: "OpenCode Go / Go Plus / Go Teams Token Plan。统一使用 OpenAI Chat Completions 兼容接口；填写 OpenCode API Key 后从 /v1/models 读取模型列表。",
  rules,
  models: [],
} satisfies ProviderDefinition<typeof rules>;
