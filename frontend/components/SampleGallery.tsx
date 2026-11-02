import * as api from "@/lib/api";

/** "Try a sample walkdown": credited stock clips with cached results, plus their finished examples. */
export function SampleGallery({
  samples,
  examples,
  selected,
  busy,
  onSelect,
  onOpenExample,
}: {
  samples: api.Sample[];
  examples: api.Example[];
  selected: string | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onOpenExample: (id: string) => void;
}) {
  const exampleIds = new Set(examples.map((e) => e.id));
  return (
    <div className="samples">
      {samples.map((s) => (
        <div key={s.id} className={`sample-card${selected === s.id ? " selected" : ""}`}>
          <button className="sample-pick" onClick={() => onSelect(s.id)} disabled={busy} aria-pressed={selected === s.id}>
            <img src={`${api.API_URL}${s.thumbnail}`} alt="" loading="lazy" />
            <span className="sample-text">
              <span className="sample-title">{s.title}</span>
              <span className="sample-desc">{s.description}</span>
            </span>
          </button>
          <div className="sample-foot">
            <span className="credit">
              Stock footage:{" "}
              <a href={s.credit.url} target="_blank" rel="noreferrer">
                {s.credit.author} / {s.credit.source}
              </a>
            </span>
            {exampleIds.has(s.example) && (
              <button className="linkish" onClick={() => onOpenExample(s.example)} disabled={busy}>
                Open finished example
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
