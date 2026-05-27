export function LiveIndicator({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span className="text-xs text-subtle" title="Refreshing every 2 seconds">
      Live
    </span>
  );
}
