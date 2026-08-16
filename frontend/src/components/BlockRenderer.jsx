export function BlockRenderer({ blocks = [] }) {
  return (
    <div className="space-y-6" data-testid="blog-blocks">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "heading":
            return (
              <h2 key={i} className="font-display text-2xl sm:text-3xl font-bold tracking-tight pt-4">
                {b.text}
              </h2>
            );
          case "subheading":
            return (
              <h3 key={i} className="font-display text-xl font-semibold pt-2">
                {b.text}
              </h3>
            );
          case "quote":
            return (
              <blockquote
                key={i}
                className="border-l-4 border-primary pl-5 py-1 text-lg sm:text-xl italic text-foreground/90"
              >
                {b.text}
              </blockquote>
            );
          case "list":
            return (
              <ul key={i} className="space-y-2 pl-1">
                {(b.items || []).map((it, j) => (
                  <li key={j} className="flex gap-3 text-base leading-relaxed text-foreground/90">
                    <span className="mt-2 w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                    <span>{it}</span>
                  </li>
                ))}
              </ul>
            );
          case "code":
            return (
              <pre key={i} className="font-mono text-sm bg-secondary rounded-md p-4 overflow-x-auto">
                <code>{b.text}</code>
              </pre>
            );
          case "image":
            return (
              <figure key={i} className="my-4">
                <img src={b.url} alt={b.caption || ""} className="w-full rounded-md" />
                {b.caption && <figcaption className="text-sm text-muted-foreground mt-2">{b.caption}</figcaption>}
              </figure>
            );
          default:
            return (
              <p key={i} className="text-base sm:text-lg leading-relaxed text-foreground/90">
                {b.text}
              </p>
            );
        }
      })}
    </div>
  );
}
