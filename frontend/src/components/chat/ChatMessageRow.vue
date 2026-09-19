<template>
  <div :class="rowClass">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ChatMessageRole } from "@/types/chat";

const props = defineProps<{
  surface: "embed" | "debug";
  role: ChatMessageRole;
}>();

const rowClass = computed(() => {
  if (props.surface === "embed") {
    return "flex flex-col space-y-4 animate-fade-in-up";
  }
  return [
    "flex w-full",
    props.role === "user" ? "justify-end" : "justify-start",
  ];
});
</script>
