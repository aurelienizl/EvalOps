/** Render the supported Markdown subset without interpreting HTML or code as markup. */
import { escapeHtml } from "./html.js";

function inlineEnd(text, delimiter, start) {
  if (delimiter === "`") return text.indexOf("`", start);
  for (let i = start; i < text.length; i++) {
    if (text[i] === "`") {
      const codeEnd = text.indexOf("`", i + 1);
      if (codeEnd !== -1) { i = codeEnd; continue; }
    }
    if (text.startsWith(delimiter, i)) return i;
  }
  return -1;
}

function inlineMarkdown(text, depth = 0) {
  if (depth > 12) return escapeHtml(text);
  let html = "";
  for (let i = 0; i < text.length;) {
    const delimiter = text[i] === "`" ? "`" : text.startsWith("**", i) ? "**" : text[i] === "*" ? "*" : null;
    const end = delimiter ? inlineEnd(text, delimiter, i + delimiter.length) : -1;
    if (delimiter && end > i + delimiter.length) {
      const content = text.slice(i + delimiter.length, end);
      const tag = delimiter === "`" ? "code" : delimiter === "**" ? "strong" : "em";
      html += `<${tag}>${tag === "code" ? escapeHtml(content) : inlineMarkdown(content, depth + 1)}</${tag}>`;
      i = end + delimiter.length;
    } else {
      html += text[i] === "\n" ? "<br>" : escapeHtml(text[i]);
      i++;
    }
  }
  return html;
}

export function renderSafeMarkdown(markdown) {
  if (!markdown) return "";
  const lines = String(markdown).replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  const isBlockStart = line => /^\s*```|^#{1,3}\s+|^\s*(?:[-*]|\d+\.)\s+/.test(line);

  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = line.match(/^\s*```([\w-]*)\s*$/);
    if (fence) {
      const code = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
      if (i < lines.length) i++;
      blocks.push(`<pre><code class="language-${fence[1]}">${escapeHtml(code.join("\n").trim())}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    const list = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (list) {
      const ordered = /^\d/.test(list[1]);
      const pattern = ordered ? /^\s*\d+\.\s+(.*)$/ : /^\s*[-*]\s+(.*)$/;
      const items = [];
      let item;
      while (i < lines.length && (item = lines[i].match(pattern))) {
        items.push(`<li>${inlineMarkdown(item[1])}</li>`);
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      blocks.push(`<${tag}>${items.join("\n")}</${tag}>`);
      continue;
    }
    const paragraph = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) paragraph.push(lines[i++]);
    blocks.push(`<p>${inlineMarkdown(paragraph.join("\n"))}</p>`);
  }
  return blocks.join("\n");
}
