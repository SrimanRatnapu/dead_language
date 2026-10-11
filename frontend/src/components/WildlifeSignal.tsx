export function WildlifeSignal({ compact = false }: { compact?: boolean }) {
  return (
    <figure className={`wildlife-signal ${compact ? "wildlife-signal--compact" : ""}`} aria-label="Abstract signal map showing a listing connected to shared price, image, and language evidence.">
      <span className="signal-orbit signal-orbit--outer" />
      <span className="signal-orbit signal-orbit--inner" />
      <span className="signal-path signal-path--one" />
      <span className="signal-path signal-path--two" />
      <span className="signal-leaf signal-leaf--one" />
      <span className="signal-leaf signal-leaf--two" />
      <span className="signal-leaf signal-leaf--three" />
      <span className="signal-core"><span /></span>
    </figure>
  );
}
