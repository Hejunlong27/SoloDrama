<template>
  <pluginMarket :visible="visible" initialType="skill" />
</template>

<script setup lang="ts">
import pluginMarket from "../pluginMarket/index.vue";

defineProps<{ visible?: boolean }>();
</script>
