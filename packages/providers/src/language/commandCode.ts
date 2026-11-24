const rules = [
  {
    type: "input",
    field: "apiKey" as const,
    title: "Command Code API Key",
    value: "",
    props: { type: "password", showPassword: true, autocomplete: "off" },
  },
] as const;

export default {
  id: "commandCode" as const,
  label: "Command Code（Token Plan）",
  icon: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3QgeD0iNCIgeT0iNCIgd2lkdGg9IjU2IiBoZWlnaHQ9IjU2IiByeD0iMTQiIGZpbGw9IiMxMDE3MjgiLz48cGF0aCBkPSJNMjAgMjJsMTIgMTAtMTIgMTBNMzYgNDJoMTIiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmODY2NCIgc3Ryb2tlLXdpZHRoPSI1IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4=",
  version: "2.0.0",
  apiUrl: "https://api.commandcode.ai/provider/v1",
  protocol: "openai-completions",
  headers: { "User-Agent": "SoloDrama/1.0" },
  readme: "Command Code Provider API / Token Plan。统一使用 OpenAI Chat Completions 兼容接口；填写 Command Code API Key 后获取模型列表。",
  rules,
  models: [],
} satisfies ProviderDefinition<typeof rules>;