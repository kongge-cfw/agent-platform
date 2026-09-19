export interface SseLineParser {
  feed(chunk: string): string[];
  flush(): string[];
}

export function createSseLineParser(): SseLineParser {
  let buffer = "";

  return {
    feed(chunk: string): string[] {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      return lines
        .map((line) => line.trim())
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6).trim());
    },
    flush(): string[] {
      const line = buffer.trim();
      buffer = "";
      return line.startsWith("data: ") ? [line.slice(6).trim()] : [];
    },
  };
}
