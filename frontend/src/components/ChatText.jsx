// Render common AI formatting as React elements; raw HTML stays escaped.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index} className="rounded bg-background/50 px-1 font-mono text-[0.9em]">{part.slice(1, -1)}</code>;
    return part;
  });
}

export function ChatText({ text = "" }) {
  return <div className="space-y-1 break-words">{text.split("\n").map((line, index) => {
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    if (heading) return <div key={index} className="font-semibold pt-2">{inline(heading[1])}</div>;
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) return <div key={index} className="flex gap-2"><span aria-hidden="true">•</span><span>{inline(bullet[1])}</span></div>;
    return <div key={index} className={line ? "whitespace-pre-wrap" : "h-2"}>{inline(line)}</div>;
  })}</div>;
}
