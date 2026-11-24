<template>
  <div class="privacy">
    <section class="settingSection" aria-labelledby="localTitle">
      <h3 id="localTitle">本地优先</h3>
      <p class="description">SoloDrama 不使用云端账号，也不发送匿名使用统计。项目、剧本、画布、素材和模型配置默认保存在本机。</p>
    </section>

    <section class="settingSection" aria-labelledby="providerTitle">
      <h3 id="providerTitle">第三方模型服务</h3>
      <p class="description">仅在发起生成或对话时，必要提示词、参考素材和模型参数会发送到你配置的模型服务商。具体处理方式以对应服务商的隐私政策为准。</p>
    </section>

    <section class="settingSection" aria-labelledby="credentialsTitle">
      <h3 id="credentialsTitle">密钥与日志</h3>
      <p class="description">API Key 保存在本机设置中，不会提交到云端。请妥善保护工作区目录和备份文件。</p>
    </section>
  </div>
</template>

<style lang="scss" scoped>
.privacy {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 0 4px 8px;

  .settingSection {
    min-width: 0;

    h3 {
      margin: 0 0 12px;
      color: var(--el-text-color-primary);
      font-size: 14px;
      font-weight: 600;
    }

    .settingHeader {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;

      h3 { margin: 0; }
    }

    .description {
      margin: 8px 0 0;
      color: var(--el-text-color-secondary);
      font-size: 13px;
      line-height: 1.6;
    }

    .metricList {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin: 0;

      .metricItem {
        display: grid;
        grid-template-columns: 88px minmax(0, 1fr);
        gap: 12px;
        font-size: 13px;
        line-height: 1.6;

        dt { color: var(--el-text-color-regular); }
        dd { margin: 0; color: var(--el-text-color-secondary); }
      }
    }

  }
}
</style>
